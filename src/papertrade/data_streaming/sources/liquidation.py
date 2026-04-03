from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import threading
from typing import Protocol

from ...trading_logic.contracts import Pair
from ...trading_logic.scheduler import ensure_utc


class LiquidationSource(Protocol):
    def sum_bybit_liquidation_usd(self, pair: Pair, start: datetime, end: datetime) -> Decimal:
        ...

    def covers_bybit_liquidation_window(self, pair: Pair, start: datetime, end: datetime) -> bool:
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

    def covers_bybit_liquidation_window(self, pair: Pair, start: datetime, end: datetime) -> bool:
        del pair, start, end
        return True


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

    def covers_bybit_liquidation_window(self, pair: Pair, start: datetime, end: datetime) -> bool:
        del pair, start, end
        return True

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


@dataclass
class BybitLiveLiquidationSource:
    pairs: tuple[Pair, ...]
    ws_url: str = "wss://stream.bybit.com/v5/public/linear"
    cache_path: Path | None = None
    reconnect_seconds: float = 5.0
    reconnect_grace_seconds: float = 120.0
    recent_window_hours: int = 8
    _events: dict[Pair, list[LiquidationEvent]] = field(init=False, default_factory=dict)
    _coverage_start: dict[Pair, datetime] = field(init=False, default_factory=dict)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)
    _stop_event: threading.Event = field(init=False, default_factory=threading.Event)
    _thread: threading.Thread | None = field(init=False, default=None)
    _started: bool = field(init=False, default=False)
    _last_update: datetime | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        normalized_pairs = tuple(dict.fromkeys(self.pairs))
        if not normalized_pairs:
            raise ValueError("pairs must not be empty")
        self.pairs = normalized_pairs
        self._events = {pair: [] for pair in self.pairs}
        self._load_cache()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_forever,
            name="papertrade-bybit-liquidation",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2)
        self._thread = None
        self._started = False
        self._persist_cache()

    def put_event(self, event: LiquidationEvent) -> None:
        with self._lock:
            if event.pair not in self._events:
                self._events[event.pair] = []
            self._events[event.pair].append(event)
            self._last_update = event.time
            self._prune_locked(reference_time=event.time)

    def set_coverage_start(self, pair: Pair, coverage_start: datetime) -> None:
        with self._lock:
            self._coverage_start[pair] = ensure_utc(coverage_start)
            if pair not in self._events:
                self._events[pair] = []

    def sum_bybit_liquidation_usd(self, pair: Pair, start: datetime, end: datetime) -> Decimal:
        if end < start:
            raise ValueError("end must not be earlier than start")
        self.start()
        with self._lock:
            self._prune_locked(reference_time=end)
            total = Decimal("0")
            for event in self._events.get(pair, ()):
                if start <= event.time < end:
                    total += event.usd_size
            return total

    def covers_bybit_liquidation_window(self, pair: Pair, start: datetime, end: datetime) -> bool:
        del end
        self.start()
        with self._lock:
            coverage_start = self._coverage_start.get(pair)
            if coverage_start is None:
                return False
            return coverage_start <= start

    def _run_forever(self) -> None:
        try:
            from websockets.sync.client import connect
        except ImportError:
            return

        while not self._stop_event.is_set():
            try:
                with connect(self.ws_url) as websocket:
                    self._mark_connected(datetime.now(timezone.utc))
                    websocket.send(
                        json.dumps(
                            {
                                "op": "subscribe",
                                "args": [f"allLiquidation.{pair.symbol}" for pair in self.pairs],
                            }
                        )
                    )
                    while not self._stop_event.is_set():
                        try:
                            message = websocket.recv(timeout=1)
                        except TimeoutError:
                            continue
                        if not isinstance(message, str):
                            continue
                        self._handle_message(message)
            except Exception:
                if self._stop_event.wait(self.reconnect_seconds):
                    break

    def _handle_message(self, message: str) -> None:
        payload = json.loads(message)
        if not isinstance(payload, dict):
            return
        topic = payload.get("topic")
        data = payload.get("data")
        if not isinstance(topic, str) or not topic.startswith("allLiquidation.") or not isinstance(data, list):
            return

        pair = _pair_from_symbol(topic.split(".", 1)[1])
        if pair not in self._events:
            return

        for item in data:
            if not isinstance(item, dict):
                continue
            time_value = item.get("T") or item.get("updatedTime") or item.get("time")
            price = item.get("p") or item.get("price")
            size = item.get("v") or item.get("size")
            if time_value is None or price is None or size is None:
                continue
            self.put_event(
                LiquidationEvent(
                    time=_millis_to_datetime(time_value),
                    pair=pair,
                    usd_size=Decimal(str(price)) * Decimal(str(size)),
                )
            )
        with self._lock:
            self._last_update = datetime.now(timezone.utc)
        self._persist_cache()

    def _mark_connected(self, connected_at: datetime) -> None:
        with self._lock:
            for pair in self.pairs:
                coverage_start = self._coverage_start.get(pair)
                if coverage_start is None:
                    self._coverage_start[pair] = connected_at
                    continue
                if self._last_update is None:
                    self._coverage_start[pair] = connected_at
                    continue
                if connected_at - self._last_update > timedelta(seconds=self.reconnect_grace_seconds):
                    self._coverage_start[pair] = connected_at

    def _prune_locked(self, *, reference_time: datetime) -> None:
        cutoff = ensure_utc(reference_time) - timedelta(hours=self.recent_window_hours, minutes=5)
        for pair, events in self._events.items():
            self._events[pair] = [event for event in events if event.time >= cutoff]

    def _load_cache(self) -> None:
        if self.cache_path is None or not self.cache_path.is_file():
            return
        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        last_update_value = payload.get("last_update")
        if isinstance(last_update_value, str):
            self._last_update = _datetime(last_update_value)
        coverage = payload.get("coverage_start")
        if isinstance(coverage, dict):
            for symbol, value in coverage.items():
                if not isinstance(symbol, str) or not isinstance(value, str):
                    continue
                pair = _pair_from_symbol(symbol)
                if pair in self._events:
                    self._coverage_start[pair] = _datetime(value)
        events = payload.get("events")
        if isinstance(events, list):
            for item in events:
                if not isinstance(item, dict):
                    continue
                symbol = item.get("symbol")
                time_value = item.get("time")
                usd_size = item.get("usd_size")
                if not isinstance(symbol, str) or not isinstance(time_value, str) or usd_size is None:
                    continue
                pair = _pair_from_symbol(symbol)
                if pair not in self._events:
                    continue
                self._events[pair].append(
                    LiquidationEvent(
                        time=_datetime(time_value),
                        pair=pair,
                        usd_size=Decimal(str(usd_size)),
                    )
                )
        if self._last_update is not None and datetime.now(timezone.utc) - self._last_update > timedelta(seconds=self.reconnect_grace_seconds):
            self._coverage_start.clear()

    def _persist_cache(self) -> None:
        if self.cache_path is None:
            return
        with self._lock:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "last_update": self._last_update.isoformat() if self._last_update is not None else None,
                "coverage_start": {
                    pair.symbol: coverage_start.isoformat()
                    for pair, coverage_start in self._coverage_start.items()
                },
                "events": [
                    {
                        "symbol": event.pair.symbol,
                        "time": event.time.isoformat(),
                        "usd_size": str(event.usd_size),
                    }
                    for pair in self.pairs
                    for event in self._events.get(pair, [])
                ],
            }
        self.cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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


def _millis_to_datetime(value: object) -> datetime:
    return datetime.fromtimestamp(int(str(value)) / 1000, tz=timezone.utc)


def _pair_from_symbol(symbol: str) -> Pair:
    if symbol.endswith("USDT"):
        return Pair(base=symbol[:-4], quote="USDT")
    raise ValueError(f"unsupported symbol format: {symbol}")
