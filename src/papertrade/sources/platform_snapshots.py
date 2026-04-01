from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import sqlite3
from typing import Any, Callable, Protocol

from ..contracts import FundingRoundSnapshot, Pair
from ..normalization import normalize_open_interest
from ..scheduler import ensure_utc
from ..sources.platform_db import PlatformDBSource


class FundingRoundSnapshotSource(Protocol):
    def get_snapshot(
        self,
        *,
        exchange: str,
        pair: Pair,
        funding_round: datetime,
    ) -> FundingRoundSnapshot | None:
        ...


class FundingRoundSnapshotStore(Protocol):
    def put_snapshot(self, snapshot: FundingRoundSnapshot) -> None:
        ...


@dataclass
class InMemoryFundingRoundSnapshotSource:
    snapshots: dict[tuple[str, Pair, datetime], FundingRoundSnapshot] = field(default_factory=dict)

    def put_snapshot(self, snapshot: FundingRoundSnapshot) -> None:
        self.snapshots[(snapshot.exchange, snapshot.pair, snapshot.funding_round)] = snapshot

    def get_snapshot(
        self,
        *,
        exchange: str,
        pair: Pair,
        funding_round: datetime,
    ) -> FundingRoundSnapshot | None:
        return self.snapshots.get((exchange, pair, funding_round))


@dataclass(frozen=True)
class SQLiteFundingRoundSnapshotSource:
    path: Path
    platform_db_source: PlatformDBSource
    open_interest_mode: str = "raw"

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def get_snapshot(
        self,
        *,
        exchange: str,
        pair: Pair,
        funding_round: datetime,
    ) -> FundingRoundSnapshot | None:
        query = """
            SELECT
                funding_round,
                decision_cutoff,
                exchange,
                base,
                quote,
                symbol,
                market_state_observed_at,
                orderbook_observed_at,
                funding_rate_bps,
                mark_price,
                index_price,
                open_interest,
                bid_price,
                ask_price,
                bid_amount,
                ask_amount,
                book_imbalance,
                liquidation_amount_8h,
                liquidation_complete,
                snapshot_valid,
                reason_code
            FROM funding_round_snapshots
            WHERE exchange = ? AND symbol = ? AND funding_round = ?
            LIMIT 1
        """
        with closing(self._connect()) as connection:
            row = connection.execute(query, (exchange, pair.symbol, funding_round.isoformat())).fetchone()
        if row is None:
            return None
        return _row_to_snapshot(
            row=row,
            platform_db_source=self.platform_db_source,
            open_interest_mode=self.open_interest_mode,
        )

    def put_snapshot(self, snapshot: FundingRoundSnapshot) -> None:
        query = """
            INSERT INTO funding_round_snapshots (
                funding_round,
                decision_cutoff,
                exchange,
                base,
                quote,
                symbol,
                market_state_observed_at,
                orderbook_observed_at,
                funding_rate_bps,
                mark_price,
                index_price,
                open_interest,
                bid_price,
                ask_price,
                bid_amount,
                ask_amount,
                book_imbalance,
                liquidation_amount_8h,
                liquidation_complete,
                snapshot_valid,
                reason_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange, symbol, funding_round) DO UPDATE SET
                decision_cutoff = excluded.decision_cutoff,
                base = excluded.base,
                quote = excluded.quote,
                market_state_observed_at = excluded.market_state_observed_at,
                orderbook_observed_at = excluded.orderbook_observed_at,
                funding_rate_bps = excluded.funding_rate_bps,
                mark_price = excluded.mark_price,
                index_price = excluded.index_price,
                open_interest = excluded.open_interest,
                bid_price = excluded.bid_price,
                ask_price = excluded.ask_price,
                bid_amount = excluded.bid_amount,
                ask_amount = excluded.ask_amount,
                book_imbalance = excluded.book_imbalance,
                liquidation_amount_8h = excluded.liquidation_amount_8h,
                liquidation_complete = excluded.liquidation_complete,
                snapshot_valid = excluded.snapshot_valid,
                reason_code = excluded.reason_code
        """
        values = (
            snapshot.funding_round.isoformat(),
            snapshot.decision_cutoff.isoformat(),
            snapshot.exchange,
            snapshot.pair.base,
            snapshot.pair.quote,
            snapshot.pair.symbol,
            _datetime_string(snapshot.market_state_observed_at),
            _datetime_string(snapshot.orderbook_observed_at),
            _decimal_string(snapshot.funding_rate_bps),
            _decimal_string(snapshot.mark_price),
            _decimal_string(snapshot.index_price),
            _decimal_string(snapshot.open_interest),
            _decimal_string(snapshot.bid_price),
            _decimal_string(snapshot.ask_price),
            _decimal_string(snapshot.bid_amount),
            _decimal_string(snapshot.ask_amount),
            _decimal_string(snapshot.book_imbalance),
            _decimal_string(snapshot.liquidation_amount_8h),
            int(snapshot.liquidation_complete),
            int(snapshot.snapshot_valid),
            snapshot.reason_code,
        )
        with closing(self._connect()) as connection:
            connection.execute(query, values)
            connection.commit()

    def ping(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("SELECT 1").fetchone()
            row = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'funding_round_snapshots'
                """
            ).fetchone()
        if row is None:
            raise ValueError("missing sqlite table: funding_round_snapshots")

    def _migrate(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS funding_round_snapshots (
                    funding_round TEXT NOT NULL,
                    decision_cutoff TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market_state_observed_at TEXT NULL,
                    orderbook_observed_at TEXT NULL,
                    funding_rate_bps TEXT NULL,
                    mark_price TEXT NULL,
                    index_price TEXT NULL,
                    open_interest TEXT NULL,
                    bid_price TEXT NULL,
                    ask_price TEXT NULL,
                    bid_amount TEXT NULL,
                    ask_amount TEXT NULL,
                    book_imbalance TEXT NULL,
                    liquidation_amount_8h TEXT NULL,
                    liquidation_complete INTEGER NOT NULL,
                    snapshot_valid INTEGER NOT NULL,
                    reason_code TEXT NOT NULL,
                    PRIMARY KEY (exchange, symbol, funding_round)
                );

                CREATE INDEX IF NOT EXISTS idx_funding_round_snapshots_pair_round
                    ON funding_round_snapshots (base, quote, funding_round DESC);
            """
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


@dataclass(frozen=True)
class PostgresFundingRoundSnapshotSource:
    dsn: str
    platform_db_source: PlatformDBSource
    connect_timeout_seconds: float = 5.0
    open_interest_mode: str = "raw"
    connection_factory: Callable[[], Any] | None = None

    def get_snapshot(
        self,
        *,
        exchange: str,
        pair: Pair,
        funding_round: datetime,
    ) -> FundingRoundSnapshot | None:
        query = """
            SELECT
                funding_round,
                decision_cutoff,
                exchange,
                base,
                quote,
                symbol,
                market_state_observed_at,
                orderbook_observed_at,
                funding_rate_bps,
                mark_price,
                index_price,
                open_interest,
                bid_price,
                ask_price,
                bid_amount,
                ask_amount,
                book_imbalance,
                liquidation_amount_8h,
                liquidation_complete,
                snapshot_valid,
                reason_code
            FROM funding_round_snapshots
            WHERE exchange = %s AND symbol = %s AND funding_round = %s
            LIMIT 1
        """
        with closing(self._connect()) as connection:
            row = connection.execute(query, (exchange, pair.symbol, funding_round)).fetchone()
        if row is None:
            return None
        return _row_to_snapshot(
            row=row,
            platform_db_source=self.platform_db_source,
            open_interest_mode=self.open_interest_mode,
        )

    def ping(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("SELECT 1").fetchone()
            row = connection.execute(
                "SELECT to_regclass('public.funding_round_snapshots') AS funding_round_snapshots_table"
            ).fetchone()
        if row["funding_round_snapshots_table"] is None:
            raise ValueError("missing platform table: funding_round_snapshots")

    def _connect(self):
        if self.connection_factory is not None:
            return self.connection_factory()

        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            self.dsn,
            connect_timeout=self.connect_timeout_seconds,
            row_factory=dict_row,
        )


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if not isinstance(value, str):
        raise ValueError("datetime columns must be stored as ISO strings")
    normalized = value.replace("Z", "+00:00")
    return ensure_utc(datetime.fromisoformat(normalized))


def _datetime_or_none(value: object) -> datetime | None:
    if value is None:
        return None
    return _datetime(value)


def _row_to_snapshot(
    *,
    row: Any,
    platform_db_source: PlatformDBSource,
    open_interest_mode: str,
) -> FundingRoundSnapshot:
    snapshot = FundingRoundSnapshot(
        funding_round=_datetime(row["funding_round"]),
        decision_cutoff=_datetime(row["decision_cutoff"]),
        exchange=str(row["exchange"]),
        pair=Pair(base=str(row["base"]), quote=str(row["quote"])),
        market_state_observed_at=_datetime_or_none(row["market_state_observed_at"]),
        orderbook_observed_at=_datetime_or_none(row["orderbook_observed_at"]),
        funding_rate_bps=_decimal_or_none(row["funding_rate_bps"]),
        mark_price=_decimal_or_none(row["mark_price"]),
        index_price=_decimal_or_none(row["index_price"]),
        open_interest=_decimal_or_none(row["open_interest"]),
        bid_price=_decimal_or_none(row["bid_price"]),
        ask_price=_decimal_or_none(row["ask_price"]),
        bid_amount=_decimal_or_none(row["bid_amount"]),
        ask_amount=_decimal_or_none(row["ask_amount"]),
        book_imbalance=_decimal_or_none(row["book_imbalance"]),
        liquidation_amount_8h=_decimal_or_none(row["liquidation_amount_8h"]),
        liquidation_complete=bool(row["liquidation_complete"]),
        snapshot_valid=bool(row["snapshot_valid"]),
        reason_code=str(row["reason_code"]),
    )

    if snapshot.open_interest is None:
        return snapshot

    instrument = platform_db_source.get_instrument(snapshot.pair, snapshot.exchange)
    normalized_open_interest = normalize_open_interest(
        snapshot.open_interest,
        instrument=instrument,
        mark_price=snapshot.mark_price,
        mode=open_interest_mode,
    )
    return replace(snapshot, open_interest=normalized_open_interest)


def _decimal_string(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _datetime_string(value: datetime | None) -> str | None:
    return None if value is None else ensure_utc(value).isoformat()
