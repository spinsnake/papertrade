from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
from typing import Any, Callable, Protocol, Sequence

from ..contracts import Funding, Instrument, OpenInterest, Pair
from ..scheduler import ensure_utc
from .http_client import HttpJsonClient


class PlatformDBSource(Protocol):
    def list_instruments(self) -> Sequence[Instrument]:
        ...

    def list_pairs(self) -> Sequence[Pair]:
        ...

    def get_instrument(self, pair: Pair, exchange: str) -> Instrument | None:
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
        return _eligible_pairs_from_instruments(self.instruments)

    def get_instrument(self, pair: Pair, exchange: str) -> Instrument | None:
        for instrument in self.instruments:
            if instrument.pair == pair and instrument.exchange == exchange:
                return instrument
        return None

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


def _eligible_pairs_from_instruments(instruments: Sequence[Instrument]) -> tuple[Pair, ...]:
    pair_exchanges: dict[Pair, set[str]] = {}
    pair_order: list[Pair] = []
    for instrument in instruments:
        if instrument.funding_interval != 8:
            continue
        pair = instrument.pair
        if pair not in pair_exchanges:
            pair_exchanges[pair] = set()
            pair_order.append(pair)
        pair_exchanges[pair].add(instrument.exchange)

    return tuple(pair for pair in pair_order if len(pair_exchanges[pair]) >= 2)


@dataclass(frozen=True)
class SQLitePlatformDBSource:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

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
        return _eligible_pairs_from_instruments(self.list_instruments())

    def get_instrument(self, pair: Pair, exchange: str) -> Instrument | None:
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
            WHERE base = ? AND quote = ? AND exchange = ?
            LIMIT 1
        """
        with closing(self._connect()) as connection:
            row = connection.execute(query, (pair.base, pair.quote, exchange)).fetchone()
        if row is None:
            return None
        return self._instrument_from_row(row)

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

    def upsert_instruments(self, instruments: Sequence[Instrument]) -> None:
        rows = [
            (
                instrument.exchange,
                instrument.base,
                instrument.quote,
                instrument.margin_asset,
                str(instrument.contract_multiplier),
                str(instrument.tick_size),
                str(instrument.lot_size),
                str(instrument.min_qty),
                str(instrument.max_qty),
                str(instrument.min_notional),
                instrument.max_leverage,
                instrument.funding_interval,
                instrument.launch_time.isoformat(),
            )
            for instrument in instruments
        ]
        if not rows:
            return

        query = """
            INSERT INTO instruments (
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange, base, quote) DO UPDATE SET
                margin_asset = excluded.margin_asset,
                contract_multiplier = excluded.contract_multiplier,
                tick_size = excluded.tick_size,
                lot_size = excluded.lot_size,
                min_qty = excluded.min_qty,
                max_qty = excluded.max_qty,
                min_notional = excluded.min_notional,
                max_leverage = excluded.max_leverage,
                funding_interval = excluded.funding_interval,
                launch_time = excluded.launch_time
        """
        with closing(self._connect()) as connection:
            connection.executemany(query, rows)
            connection.commit()

    def upsert_funding_history(self, rows: Sequence[Funding]) -> None:
        payload = [
            (
                row.time.isoformat(),
                row.exchange,
                row.base,
                row.quote,
                str(row.funding_rate),
            )
            for row in rows
        ]
        if not payload:
            return

        query = """
            INSERT INTO funding (time, exchange, base, quote, funding_rate)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(exchange, base, quote, time) DO UPDATE SET
                funding_rate = excluded.funding_rate
        """
        with closing(self._connect()) as connection:
            connection.executemany(query, payload)
            connection.commit()

    def upsert_open_interest_history(self, rows: Sequence[OpenInterest]) -> None:
        payload = [
            (
                row.time.isoformat(),
                row.exchange,
                row.base,
                row.quote,
                str(row.open_interest),
            )
            for row in rows
        ]
        if not payload:
            return

        query = """
            INSERT INTO open_interest (time, exchange, base, quote, open_interest)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(exchange, base, quote, time) DO UPDATE SET
                open_interest = excluded.open_interest
        """
        with closing(self._connect()) as connection:
            connection.executemany(query, payload)
            connection.commit()

    def ping(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("SELECT 1").fetchone()
            row = connection.execute(
                """
                SELECT
                    (SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'instruments') AS instruments_table,
                    (SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'funding') AS funding_table,
                    (SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'open_interest') AS open_interest_table
                """
            ).fetchone()
        required = {
            "instruments": row["instruments_table"],
            "funding": row["funding_table"],
            "open_interest": row["open_interest_table"],
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(f"missing sqlite platform tables: {', '.join(missing)}")

    def _migrate(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS instruments (
                    exchange TEXT NOT NULL,
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    margin_asset TEXT NOT NULL,
                    contract_multiplier TEXT NOT NULL,
                    tick_size TEXT NOT NULL,
                    lot_size TEXT NOT NULL,
                    min_qty TEXT NOT NULL,
                    max_qty TEXT NOT NULL,
                    min_notional TEXT NOT NULL,
                    max_leverage INTEGER NOT NULL,
                    funding_interval INTEGER NOT NULL,
                    launch_time TEXT NOT NULL,
                    PRIMARY KEY (exchange, base, quote)
                );

                CREATE TABLE IF NOT EXISTS funding (
                    time TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    funding_rate TEXT NOT NULL,
                    PRIMARY KEY (exchange, base, quote, time)
                );

                CREATE TABLE IF NOT EXISTS open_interest (
                    time TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    open_interest TEXT NOT NULL,
                    PRIMARY KEY (exchange, base, quote, time)
                );

                CREATE INDEX IF NOT EXISTS idx_funding_pair_exchange_time
                    ON funding (base, quote, exchange, time DESC);
                CREATE INDEX IF NOT EXISTS idx_open_interest_pair_exchange_time
                    ON open_interest (base, quote, exchange, time DESC);

                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                """
            )
            connection.commit()

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
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if not isinstance(value, str):
        raise ValueError("datetime columns must be stored as ISO strings")
    normalized = value.replace("Z", "+00:00")
    return ensure_utc(datetime.fromisoformat(normalized))


@dataclass(frozen=True)
class ExchangeRestPlatformDBSource:
    bybit_base_url: str = "https://api.bybit.com"
    bitget_base_url: str = "https://api.bitget.com"
    http_client: HttpJsonClient = HttpJsonClient()

    def list_instruments(self) -> Sequence[Instrument]:
        instruments: list[Instrument] = []
        bybit_payloads = self._load_bybit_instruments()
        bitget_payload = self.http_client.get_json(
            self.bitget_base_url,
            "/api/v2/mix/market/contracts",
            {"productType": "USDT-FUTURES"},
        )
        if str(bitget_payload.get("code")) != "00000":
            raise ValueError(f"bitget contracts request failed: {bitget_payload}")

        for item in bybit_payloads:
            if str(item.get("status")) != "Trading":
                continue
            if str(item.get("contractType")) != "LinearPerpetual":
                continue
            if str(item.get("quoteCoin")) != "USDT":
                continue
            instruments.append(
                Instrument(
                    exchange="bybit",
                    base=str(item["baseCoin"]),
                    quote=str(item["quoteCoin"]),
                    margin_asset="USDT",
                    contract_multiplier=Decimal("1"),
                    tick_size=_decimal(item.get("priceFilter", {}).get("tickSize", "0")),
                    lot_size=_decimal(item.get("lotSizeFilter", {}).get("qtyStep", "0")),
                    min_qty=_decimal(item.get("lotSizeFilter", {}).get("minOrderQty", "0")),
                    max_qty=_decimal(item.get("lotSizeFilter", {}).get("maxOrderQty", "0")),
                    min_notional=Decimal("0"),
                    max_leverage=int(Decimal(str(item.get("leverageFilter", {}).get("maxLeverage", "0")))),
                    funding_interval=8,
                    launch_time=_millis_to_datetime(item["launchTime"]),
                )
            )

        data = bitget_payload.get("data")
        if not isinstance(data, list):
            raise ValueError("bitget contracts response missing data array")
        for item in data:
            if not isinstance(item, dict):
                continue
            if str(item.get("symbolStatus")) != "normal":
                continue
            instruments.append(
                Instrument(
                    exchange="bitget",
                    base=str(item["baseCoin"]),
                    quote=str(item["quoteCoin"]),
                    margin_asset="USDT",
                    contract_multiplier=Decimal("1"),
                    tick_size=_bitget_tick_size(item),
                    lot_size=_decimal(item.get("sizeMultiplier", "0")),
                    min_qty=_decimal(item.get("minTradeNum", "0")),
                    max_qty=Decimal("0"),
                    min_notional=Decimal("0"),
                    max_leverage=0,
                    funding_interval=8,
                    launch_time=_millis_to_datetime(item.get("offTime") if str(item.get("offTime")) not in {"", "-1"} else None),
                )
            )
        return tuple(instruments)

    def list_pairs(self) -> Sequence[Pair]:
        return _eligible_pairs_from_instruments(self.list_instruments())

    def get_instrument(self, pair: Pair, exchange: str) -> Instrument | None:
        for instrument in self.list_instruments():
            if instrument.pair == pair and instrument.exchange == exchange:
                return instrument
        return None

    def load_funding_history(self, pair: Pair, exchange: str, limit: int) -> Sequence[Funding]:
        validated_limit = _validate_limit(limit)
        if validated_limit == 0:
            return ()
        if exchange == "bybit":
            payload = self.http_client.get_json(
                self.bybit_base_url,
                "/v5/market/funding/history",
                {
                    "category": "linear",
                    "symbol": pair.symbol,
                    "limit": str(min(validated_limit, 200)),
                },
            )
            if int(payload.get("retCode", -1)) != 0:
                raise ValueError(f"bybit funding history request failed: {payload}")
            items = payload.get("result", {}).get("list")
            if not isinstance(items, list):
                raise ValueError("bybit funding history response missing list")
            return tuple(
                Funding(
                    time=_millis_to_datetime(item["fundingRateTimestamp"]),
                    exchange="bybit",
                    base=pair.base,
                    quote=pair.quote,
                    funding_rate=_decimal(item["fundingRate"]),
                )
                for item in items[:validated_limit]
                if isinstance(item, dict)
            )
        if exchange == "bitget":
            payload = self.http_client.get_json(
                self.bitget_base_url,
                "/api/v2/mix/market/history-fund-rate",
                {
                    "symbol": _bitget_symbol(pair),
                    "productType": _bitget_product_type(pair),
                    "pageSize": str(min(validated_limit, 100)),
                    "pageNo": "1",
                },
            )
            if str(payload.get("code")) != "00000":
                raise ValueError(f"bitget funding history request failed: {payload}")
            items = payload.get("data")
            if not isinstance(items, list):
                raise ValueError("bitget funding history response missing data array")
            return tuple(
                Funding(
                    time=_millis_to_datetime(item.get("fundingTime") or item.get("fundingRateTimestamp")),
                    exchange="bitget",
                    base=pair.base,
                    quote=pair.quote,
                    funding_rate=_decimal(item["fundingRate"]),
                )
                for item in items[:validated_limit]
                if isinstance(item, dict)
            )
        raise ValueError(f"unsupported exchange: {exchange}")

    def load_open_interest_history(self, pair: Pair, exchange: str, limit: int) -> Sequence[OpenInterest]:
        validated_limit = _validate_limit(limit)
        if validated_limit == 0:
            return ()
        if exchange == "bybit":
            payload = self.http_client.get_json(
                self.bybit_base_url,
                "/v5/market/open-interest",
                {
                    "category": "linear",
                    "symbol": pair.symbol,
                    "intervalTime": "5min",
                    "limit": str(min(validated_limit, 50)),
                },
            )
            if int(payload.get("retCode", -1)) != 0:
                raise ValueError(f"bybit open-interest request failed: {payload}")
            items = payload.get("result", {}).get("list")
            if not isinstance(items, list):
                raise ValueError("bybit open-interest response missing list")
            return tuple(
                OpenInterest(
                    time=_millis_to_datetime(item["timestamp"]),
                    exchange="bybit",
                    base=pair.base,
                    quote=pair.quote,
                    open_interest=_decimal(item["openInterest"]),
                )
                for item in items[:validated_limit]
                if isinstance(item, dict)
            )
        if exchange == "bitget":
            payload = self.http_client.get_json(
                self.bitget_base_url,
                "/api/v2/mix/market/open-interest",
                {
                    "symbol": _bitget_symbol(pair),
                    "productType": _bitget_product_type(pair),
                },
            )
            if str(payload.get("code")) != "00000":
                raise ValueError(f"bitget open-interest request failed: {payload}")
            item = payload.get("data")
            if not isinstance(item, dict):
                raise ValueError("bitget open-interest response missing data object")
            first = _first_open_interest_item(item.get("openInterestList"))
            return (
                OpenInterest(
                    time=_millis_to_datetime(item["ts"]),
                    exchange="bitget",
                    base=pair.base,
                    quote=pair.quote,
                    open_interest=_decimal(first["size"]),
                ),
            )
        raise ValueError(f"unsupported exchange: {exchange}")

    def ping(self) -> None:
        self.http_client.get_json(self.bybit_base_url, "/v5/market/time", {})

    def _load_bybit_instruments(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        cursor = ""
        while True:
            params = {
                "category": "linear",
                "limit": "1000",
            }
            if cursor:
                params["cursor"] = cursor
            payload = self.http_client.get_json(
                self.bybit_base_url,
                "/v5/market/instruments-info",
                params,
            )
            if int(payload.get("retCode", -1)) != 0:
                raise ValueError(f"bybit instruments request failed: {payload}")
            result = payload.get("result", {})
            page_items = result.get("list")
            if not isinstance(page_items, list):
                raise ValueError("bybit instruments response missing list")
            for item in page_items:
                if isinstance(item, dict):
                    items.append(item)
            next_cursor = str(result.get("nextPageCursor", ""))
            if not next_cursor:
                break
            cursor = next_cursor
        return items


@dataclass(frozen=True)
class PostgresPlatformDBSource:
    dsn: str
    connect_timeout_seconds: float = 5.0
    connection_factory: Callable[[], Any] | None = None

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
        return _eligible_pairs_from_instruments(self.list_instruments())

    def get_instrument(self, pair: Pair, exchange: str) -> Instrument | None:
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
            WHERE base = %s AND quote = %s AND exchange = %s
            LIMIT 1
        """
        with closing(self._connect()) as connection:
            row = connection.execute(query, (pair.base, pair.quote, exchange)).fetchone()
        if row is None:
            return None
        return self._instrument_from_row(row)

    def load_funding_history(self, pair: Pair, exchange: str, limit: int) -> Sequence[Funding]:
        validated_limit = _validate_limit(limit)
        if validated_limit == 0:
            return ()

        query = """
            SELECT time, exchange, base, quote, funding_rate
            FROM funding
            WHERE base = %s AND quote = %s AND exchange = %s
            ORDER BY time DESC
            LIMIT %s
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
            WHERE base = %s AND quote = %s AND exchange = %s
            ORDER BY time DESC
            LIMIT %s
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(query, (pair.base, pair.quote, exchange, validated_limit)).fetchall()
        return tuple(self._open_interest_from_row(row) for row in rows)

    def ping(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("SELECT 1").fetchone()
            row = connection.execute(
                """
                SELECT
                    to_regclass('public.instruments') AS instruments_table,
                    to_regclass('public.funding') AS funding_table,
                    to_regclass('public.open_interest') AS open_interest_table
                """
            ).fetchone()
        required = {
            "instruments": row["instruments_table"],
            "funding": row["funding_table"],
            "open_interest": row["open_interest_table"],
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(f"missing platform tables: {', '.join(missing)}")

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

    def _instrument_from_row(self, row: Any) -> Instrument:
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

    def _funding_from_row(self, row: Any) -> Funding:
        return Funding(
            time=_datetime(row["time"]),
            exchange=str(row["exchange"]),
            base=str(row["base"]),
            quote=str(row["quote"]),
            funding_rate=_decimal(row["funding_rate"]),
        )

    def _open_interest_from_row(self, row: Any) -> OpenInterest:
        return OpenInterest(
            time=_datetime(row["time"]),
            exchange=str(row["exchange"]),
            base=str(row["base"]),
            quote=str(row["quote"]),
            open_interest=_decimal(row["open_interest"]),
        )


def _millis_to_datetime(value: object) -> datetime:
    if value in {None, "", "-1"}:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return datetime.fromtimestamp(int(str(value)) / 1000, tz=timezone.utc)


def _bitget_symbol(pair: Pair) -> str:
    if pair.quote != "USDT":
        raise ValueError("bitget live platform DB source currently supports only USDT-margined pairs")
    return pair.symbol


def _bitget_product_type(pair: Pair) -> str:
    if pair.quote == "USDT":
        return "USDT-FUTURES"
    raise ValueError("bitget live platform DB source currently supports only USDT-margined pairs")


def _bitget_tick_size(item: dict[str, object]) -> Decimal:
    price_end_step = str(item.get("priceEndStep", "0"))
    price_place = int(str(item.get("pricePlace", "0")))
    if price_place <= 0:
        return Decimal(price_end_step)
    return Decimal(price_end_step) / (Decimal(10) ** price_place)


def _first_open_interest_item(payload: object) -> dict[str, object]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ValueError("bitget open-interest response missing first data item")
    return payload[0]


LivePlatformDBSource = ExchangeRestPlatformDBSource


def sync_all_instruments_from_source(
    target: SQLitePlatformDBSource,
    source: PlatformDBSource,
) -> int:
    instruments = tuple(source.list_instruments())
    target.upsert_instruments(instruments)
    return len(instruments)


def sync_pair_history_from_source(
    target: SQLitePlatformDBSource,
    source: PlatformDBSource,
    *,
    pair: Pair,
    funding_limit: int = 8,
    open_interest_limit: int = 8,
) -> None:
    instruments: list[Instrument] = []
    for exchange in ("bybit", "bitget"):
        instrument = source.get_instrument(pair, exchange)
        if instrument is not None:
            instruments.append(instrument)
        target.upsert_funding_history(source.load_funding_history(pair, exchange, funding_limit))
        target.upsert_open_interest_history(source.load_open_interest_history(pair, exchange, open_interest_limit))
    if instruments:
        target.upsert_instruments(instruments)
