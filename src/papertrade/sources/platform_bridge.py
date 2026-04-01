from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Protocol

from ..contracts import Level, MarketState, Orderbook, Pair
from ..scheduler import ensure_utc


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
