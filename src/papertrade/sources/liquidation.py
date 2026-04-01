from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Protocol

from ..contracts import Pair
from ..scheduler import ensure_utc


class LiquidationSource(Protocol):
    def sum_bybit_liquidation_usd(self, pair: Pair, start: datetime, end: datetime) -> Decimal:
        ...


@dataclass(frozen=True)
class LiquidationEvent:
    time: datetime
    pair: Pair
    usd_size: Decimal


@dataclass
class InMemoryLiquidationSource:
    events: list[LiquidationEvent] = field(default_factory=list)

    def put_event(self, event: LiquidationEvent) -> None:
        self.events.append(event)

    def sum_bybit_liquidation_usd(self, pair: Pair, start: datetime, end: datetime) -> Decimal:
        if end < start:
            raise ValueError("end must not be earlier than start")

        total = Decimal("0")
        for event in self.events:
            if event.pair != pair:
                continue
            if start <= event.time < end:
                total += event.usd_size
        return total


@dataclass(frozen=True)
class JsonFileLiquidationSource:
    path: Path

    def sum_bybit_liquidation_usd(self, pair: Pair, start: datetime, end: datetime) -> Decimal:
        if end < start:
            raise ValueError("end must not be earlier than start")

        total = Decimal("0")
        for item in self._load_events():
            event_pair = _pair_from_record(item)
            if event_pair != pair:
                continue
            event_time = _datetime(item["time"])
            if start <= event_time < end:
                total += Decimal(str(item["usd_size"]))
        return total

    def _load_events(self) -> list[dict[str, object]]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("liquidation events file must contain a JSON array")
        events: list[dict[str, object]] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("liquidation events must be JSON objects")
            events.append(item)
        return events


def _pair_from_record(record: dict[str, object]) -> Pair:
    pair_payload = record.get("pair")
    if isinstance(pair_payload, dict):
        return Pair(base=str(pair_payload["base"]), quote=str(pair_payload["quote"]))
    return Pair(base=str(record["base"]), quote=str(record["quote"]))


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("datetime values must be ISO strings")
    normalized = value.replace("Z", "+00:00")
    return ensure_utc(datetime.fromisoformat(normalized))
