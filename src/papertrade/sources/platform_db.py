from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import sqlite3
from typing import Protocol, Sequence

from ..contracts import Funding, Instrument, OpenInterest, Pair
from ..scheduler import ensure_utc


class PlatformDBSource(Protocol):
    def list_instruments(self) -> Sequence[Instrument]:
        ...

    def list_pairs(self) -> Sequence[Pair]:
        ...

    def load_funding_history(self, pair: Pair, exchange: str, limit: int) -> Sequence[Funding]:
        ...

    def load_open_interest_history(self, pair: Pair, exchange: str, limit: int) -> Sequence[OpenInterest]:
        ...


@dataclass
class InMemoryPlatformDBSource:
    instruments: list[Instrument] = field(default_factory=list)
    fundings: list[Funding] = field(default_factory=list)
    open_interests: list[OpenInterest] = field(default_factory=list)

    def put_instrument(self, instrument: Instrument) -> None:
        self.instruments.append(instrument)

    def put_funding(self, funding: Funding) -> None:
        self.fundings.append(funding)

    def put_open_interest(self, open_interest: OpenInterest) -> None:
        self.open_interests.append(open_interest)

    def list_instruments(self) -> Sequence[Instrument]:
        return tuple(self.instruments)

    def list_pairs(self) -> Sequence[Pair]:
        pairs: list[Pair] = []
        seen: set[Pair] = set()
        for instrument in self.instruments:
            if instrument.funding_interval != 8:
                continue
            pair = instrument.pair
            if pair in seen:
                continue
            seen.add(pair)
            pairs.append(pair)
        return tuple(pairs)

    def load_funding_history(self, pair: Pair, exchange: str, limit: int) -> Sequence[Funding]:
        validated_limit = _validate_limit(limit)
        if validated_limit == 0:
            return ()

        filtered = [
            funding
            for funding in self.fundings
            if funding.pair == pair and funding.exchange == exchange
        ]
        filtered.sort(key=lambda funding: funding.time, reverse=True)
        return tuple(filtered[:validated_limit])

    def load_open_interest_history(self, pair: Pair, exchange: str, limit: int) -> Sequence[OpenInterest]:
        validated_limit = _validate_limit(limit)
        if validated_limit == 0:
            return ()

        filtered = [
            open_interest
            for open_interest in self.open_interests
            if open_interest.pair == pair and open_interest.exchange == exchange
        ]
        filtered.sort(key=lambda open_interest: open_interest.time, reverse=True)
        return tuple(filtered[:validated_limit])


def _validate_limit(limit: int) -> int:
    if limit < 0:
        raise ValueError("limit must not be negative")
    return limit


@dataclass(frozen=True)
class SQLitePlatformDBSource:
    path: Path

    def list_instruments(self) -> Sequence[Instrument]:
        query = """
            SELECT
                exchange,
                base,
                quote,
                margin_asset,
                contract_multiplier,
                tick_size,
                lot_size,
                min_qty,
                max_qty,
                min_notional,
                max_leverage,
                funding_interval,
                launch_time
            FROM instruments
            ORDER BY base, quote, exchange
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(query).fetchall()
        return tuple(self._instrument_from_row(row) for row in rows)

    def list_pairs(self) -> Sequence[Pair]:
        pairs: list[Pair] = []
        seen: set[Pair] = set()
        for instrument in self.list_instruments():
            if instrument.funding_interval != 8:
                continue
            pair = instrument.pair
            if pair in seen:
                continue
            seen.add(pair)
            pairs.append(pair)
        return tuple(pairs)

    def load_funding_history(self, pair: Pair, exchange: str, limit: int) -> Sequence[Funding]:
        validated_limit = _validate_limit(limit)
        if validated_limit == 0:
            return ()

        query = """
            SELECT time, exchange, base, quote, funding_rate
            FROM funding
            WHERE base = ? AND quote = ? AND exchange = ?
            ORDER BY time DESC
            LIMIT ?
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(query, (pair.base, pair.quote, exchange, validated_limit)).fetchall()
        return tuple(self._funding_from_row(row) for row in rows)

    def load_open_interest_history(self, pair: Pair, exchange: str, limit: int) -> Sequence[OpenInterest]:
        validated_limit = _validate_limit(limit)
        if validated_limit == 0:
            return ()

        query = """
            SELECT time, exchange, base, quote, open_interest
            FROM open_interest
            WHERE base = ? AND quote = ? AND exchange = ?
            ORDER BY time DESC
            LIMIT ?
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(query, (pair.base, pair.quote, exchange, validated_limit)).fetchall()
        return tuple(self._open_interest_from_row(row) for row in rows)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _instrument_from_row(self, row: sqlite3.Row) -> Instrument:
        return Instrument(
            exchange=str(row["exchange"]),
            base=str(row["base"]),
            quote=str(row["quote"]),
            margin_asset=str(row["margin_asset"]),
            contract_multiplier=_decimal(row["contract_multiplier"]),
            tick_size=_decimal(row["tick_size"]),
            lot_size=_decimal(row["lot_size"]),
            min_qty=_decimal(row["min_qty"]),
            max_qty=_decimal(row["max_qty"]),
            min_notional=_decimal(row["min_notional"]),
            max_leverage=int(row["max_leverage"]),
            funding_interval=int(row["funding_interval"]),
            launch_time=_datetime(row["launch_time"]),
        )

    def _funding_from_row(self, row: sqlite3.Row) -> Funding:
        return Funding(
            time=_datetime(row["time"]),
            exchange=str(row["exchange"]),
            base=str(row["base"]),
            quote=str(row["quote"]),
            funding_rate=_decimal(row["funding_rate"]),
        )

    def _open_interest_from_row(self, row: sqlite3.Row) -> OpenInterest:
        return OpenInterest(
            time=_datetime(row["time"]),
            exchange=str(row["exchange"]),
            base=str(row["base"]),
            quote=str(row["quote"]),
            open_interest=_decimal(row["open_interest"]),
        )


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("datetime columns must be stored as ISO strings")
    normalized = value.replace("Z", "+00:00")
    return ensure_utc(datetime.fromisoformat(normalized))
