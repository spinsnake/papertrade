from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Protocol

from ...trading_logic.contracts import Level, MarketState, Orderbook, Pair
from ...trading_logic.scheduler import ensure_utc
from .http_client import HttpJsonClient


class PlatformBridgeSource(Protocol):
    def get_market_state(self, exchange: str, pair: Pair) -> MarketState | None:
        ...

    def get_orderbook(self, exchange: str, pair: Pair) -> Orderbook | None:
        ...


@dataclass
class InMemoryPlatformBridge:
    market_states: dict[tuple[str, Pair], MarketState] = field(default_factory=dict)
    orderbooks: dict[tuple[str, Pair], Orderbook] = field(default_factory=dict)

    def put_market_state(self, exchange: str, state: MarketState) -> None:
        self.market_states[(exchange, state.pair)] = state

    def put_orderbook(self, exchange: str, orderbook: Orderbook) -> None:
        self.orderbooks[(exchange, orderbook.pair)] = orderbook

    def get_market_state(self, exchange: str, pair: Pair) -> MarketState | None:
        return self.market_states.get((exchange, pair))

    def get_orderbook(self, exchange: str, pair: Pair) -> Orderbook | None:
        return self.orderbooks.get((exchange, pair))


@dataclass(frozen=True)
class FilePlatformBridge:
    market_state_path: Path
    orderbook_path: Path

    def get_market_state(self, exchange: str, pair: Pair) -> MarketState | None:
        candidates = [
            self._market_state_from_record(record)
            for record in self._load_records(self.market_state_path)
            if str(record.get("exchange")) == exchange and _pair_from_record(record) == pair
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda state: state.updated_at, reverse=True)
        return candidates[0]

    def get_orderbook(self, exchange: str, pair: Pair) -> Orderbook | None:
        candidates = [
            self._orderbook_from_record(record)
            for record in self._load_records(self.orderbook_path)
            if str(record.get("exchange")) == exchange and _pair_from_record(record) == pair
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda orderbook: orderbook.updated_at, reverse=True)
        return candidates[0]

    def _load_records(self, path: Path) -> list[dict[str, object]]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"{path} must contain a JSON array")
        records: list[dict[str, object]] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError(f"{path} records must be JSON objects")
            records.append(item)
        return records

    def _market_state_from_record(self, record: dict[str, object]) -> MarketState:
        pair = _pair_from_record(record)
        return MarketState(
            pair=pair,
            index_price=_decimal(record["index_price"]),
            mark_price=_decimal(record["mark_price"]),
            funding_rate=_decimal(record["funding_rate"]),
            open_interest=_decimal(record["open_interest"]),
            base_volume=_decimal(record.get("base_volume", "0")),
            quote_volume=_decimal(record.get("quote_volume", "0")),
            sequence=int(record.get("sequence", 0)),
            updated_at=_datetime(record["updated_at"]),
        )

    def _orderbook_from_record(self, record: dict[str, object]) -> Orderbook:
        pair = _pair_from_record(record)
        bids = tuple(_level(item) for item in _list_of_dicts(record.get("bids", [])))
        asks = tuple(_level(item) for item in _list_of_dicts(record.get("asks", [])))
        return Orderbook(
            pair=pair,
            bids=bids,
            asks=asks,
            sequence=int(record.get("sequence", 0)),
            updated_at=_datetime(record["updated_at"]),
        )


@dataclass(frozen=True)
class ExchangeRestPlatformBridge:
    bybit_base_url: str = "https://api.bybit.com"
    bitget_base_url: str = "https://api.bitget.com"
    http_client: HttpJsonClient = HttpJsonClient()

    def get_market_state(self, exchange: str, pair: Pair) -> MarketState | None:
        if exchange == "bybit":
            return self._get_bybit_market_state(pair)
        if exchange == "bitget":
            return self._get_bitget_market_state(pair)
        raise ValueError(f"unsupported exchange: {exchange}")

    def get_orderbook(self, exchange: str, pair: Pair) -> Orderbook | None:
        if exchange == "bybit":
            return self._get_bybit_orderbook(pair)
        if exchange == "bitget":
            return self._get_bitget_orderbook(pair)
        raise ValueError(f"unsupported exchange: {exchange}")

    def _get_bybit_market_state(self, pair: Pair) -> MarketState:
        payload = self.http_client.get_json(
            self.bybit_base_url,
            "/v5/market/tickers",
            {
                "category": "linear",
                "symbol": pair.symbol,
            },
        )
        if int(payload.get("retCode", -1)) != 0:
            raise ValueError(f"bybit tickers request failed: {payload}")
        ticker = _first_item(payload.get("result", {}).get("list"), "bybit ticker")
        updated_at = _millis_to_datetime(payload.get("time"))
        return MarketState(
            pair=pair,
            index_price=_decimal(ticker["indexPrice"]),
            mark_price=_decimal(ticker["markPrice"]),
            funding_rate=_decimal(ticker["fundingRate"]),
            open_interest=_decimal(ticker["openInterest"]),
            base_volume=_decimal(ticker.get("volume24h", "0")),
            quote_volume=_decimal(ticker.get("turnover24h", "0")),
            sequence=0,
            updated_at=updated_at,
        )

    def _get_bybit_orderbook(self, pair: Pair) -> Orderbook:
        payload = self.http_client.get_json(
            self.bybit_base_url,
            "/v5/market/tickers",
            {
                "category": "linear",
                "symbol": pair.symbol,
            },
        )
        if int(payload.get("retCode", -1)) != 0:
            raise ValueError(f"bybit tickers request failed: {payload}")
        ticker = _first_item(payload.get("result", {}).get("list"), "bybit ticker")
        updated_at = _millis_to_datetime(payload.get("time"))
        return Orderbook(
            pair=pair,
            bids=(_level_from_values(ticker["bid1Price"], ticker["bid1Size"]),),
            asks=(_level_from_values(ticker["ask1Price"], ticker["ask1Size"]),),
            sequence=0,
            updated_at=updated_at,
        )

    def _get_bitget_market_state(self, pair: Pair) -> MarketState:
        symbol = _bitget_symbol(pair)
        ticker_payload = self.http_client.get_json(
            self.bitget_base_url,
            "/api/v2/mix/market/ticker",
            {
                "symbol": symbol,
                "productType": _bitget_product_type(pair),
            },
        )
        if str(ticker_payload.get("code")) != "00000":
            raise ValueError(f"bitget ticker request failed: {ticker_payload}")
        ticker = _first_item(ticker_payload.get("data"), "bitget ticker")

        updated_at = _millis_to_datetime(ticker.get("ts"))
        return MarketState(
            pair=pair,
            index_price=_decimal(ticker["indexPrice"]),
            mark_price=_decimal(ticker["markPrice"]),
            funding_rate=_decimal(ticker["fundingRate"]),
            open_interest=_decimal(ticker["holdingAmount"]),
            base_volume=_decimal(ticker.get("baseVolume", "0")),
            quote_volume=_decimal(ticker.get("quoteVolume", "0")),
            sequence=0,
            updated_at=updated_at,
        )

    def _get_bitget_orderbook(self, pair: Pair) -> Orderbook:
        symbol = _bitget_symbol(pair)
        payload = self.http_client.get_json(
            self.bitget_base_url,
            "/api/v2/mix/market/ticker",
            {
                "symbol": symbol,
                "productType": _bitget_product_type(pair),
            },
        )
        if str(payload.get("code")) != "00000":
            raise ValueError(f"bitget ticker request failed: {payload}")
        ticker = _first_item(payload.get("data"), "bitget ticker")
        updated_at = _millis_to_datetime(ticker.get("ts"))
        return Orderbook(
            pair=pair,
            bids=(_level_from_values(ticker["bidPr"], ticker["bidSz"]),),
            asks=(_level_from_values(ticker["askPr"], ticker["askSz"]),),
            sequence=0,
            updated_at=updated_at,
        )


def _list_of_dicts(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise ValueError("list payload must be a JSON array")
    items: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("list items must be JSON objects")
        items.append(item)
    return items


def _pair_from_record(record: dict[str, object]) -> Pair:
    pair_payload = record.get("pair")
    if isinstance(pair_payload, dict):
        return Pair(base=str(pair_payload["base"]), quote=str(pair_payload["quote"]))
    return Pair(base=str(record["base"]), quote=str(record["quote"]))


def _level(record: dict[str, object]) -> Level:
    return Level(
        price=_decimal(record["price"]),
        size=_decimal(record["size"]),
    )


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("datetime values must be ISO strings")
    normalized = value.replace("Z", "+00:00")
    return ensure_utc(datetime.fromisoformat(normalized))


def _millis_to_datetime(value: object) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(int(str(value)) / 1000, tz=timezone.utc)


def _first_item(payload: object, context: str) -> dict[str, object]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ValueError(f"{context} response missing first item")
    return payload[0]


def _level_from_values(price: object, size: object) -> Level:
    return Level(
        price=_decimal(price),
        size=_decimal(size),
    )


def _bitget_symbol(pair: Pair) -> str:
    if pair.quote != "USDT":
        raise ValueError("bitget live bridge currently supports only USDT-margined pairs")
    return pair.symbol


def _bitget_product_type(pair: Pair) -> str:
    if pair.quote == "USDT":
        return "USDT-FUTURES"
    raise ValueError("bitget live bridge currently supports only USDT-margined pairs")


LiveHttpPlatformBridge = ExchangeRestPlatformBridge
