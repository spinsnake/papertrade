from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import Settings
from .contracts import Funding, Level, MarketState, OpenInterest, Orderbook, Pair, PaperRun
from .orchestrator import (
    SingleCycleInput,
    SingleCycleResult,
    build_platform_db_backed_orchestrator,
)
from .persistence import CsvTradeLogWriter, JsonArtifactStore, RunArtifactPaths, RunArtifactWriter
from .portfolio import PortfolioSimulator
from .report import MarkdownReportWriter
from .scheduler import FundingDecision, RoundScheduler, ensure_utc
from .scoring import load_artifact_pair
from .snapshot_collector import SnapshotCollector
from .sources.liquidation import (
    InMemoryLiquidationSource,
    JsonFileLiquidationSource,
    LiquidationEvent,
    LiquidationSource,
)
from .sources.platform_bridge import FilePlatformBridge, InMemoryPlatformBridge, PlatformBridgeSource
from .sources.platform_db import InMemoryPlatformDBSource, PlatformDBSource, SQLitePlatformDBSource


def _decimal(value: object, *, default: str | None = None) -> Decimal:
    if value is None:
        if default is None:
            raise ValueError("decimal value is required")
        return Decimal(default)
    return Decimal(str(value))


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("datetime value must be a string")
    normalized = value.replace("Z", "+00:00")
    return ensure_utc(datetime.fromisoformat(normalized))


def _pair(payload: object) -> Pair:
    if not isinstance(payload, dict):
        raise ValueError("pair must be an object")
    return Pair(
        base=str(payload["base"]),
        quote=str(payload["quote"]),
    )


def _level(payload: object) -> Level:
    if not isinstance(payload, dict):
        raise ValueError("orderbook level must be an object")
    return Level(
        price=_decimal(payload["price"]),
        size=_decimal(payload["size"]),
    )


@dataclass(frozen=True)
class SingleCycleSourceBundle:
    now_utc: datetime
    pair: Pair
    bridge: PlatformBridgeSource
    platform_db_source: PlatformDBSource
    liquidation_source: LiquidationSource | None
    liquidation_source_configured: bool

    @property
    def has_liquidation_source(self) -> bool:
        return self.liquidation_source_configured


@dataclass(frozen=True)
class SingleCycleExecutionResult:
    funding_decision: FundingDecision
    cycle_result: SingleCycleResult
    artifact_paths: RunArtifactPaths
    cycle_artifact_path: Path
    opened_position_id: str | None


def load_single_cycle_fixture(path: str | Path) -> SingleCycleSourceBundle:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("single-cycle fixture must be a JSON object")

    pair = _pair(payload["pair"])
    bridge = InMemoryPlatformBridge()
    platform_db_source = InMemoryPlatformDBSource()

    market_states = payload.get("market_states", {})
    if not isinstance(market_states, dict):
        raise ValueError("market_states must be an object")
    for exchange, item in market_states.items():
        if not isinstance(item, dict):
            raise ValueError("market state must be an object")
        bridge.put_market_state(
            str(exchange),
            MarketState(
                pair=pair,
                index_price=_decimal(item["index_price"]),
                mark_price=_decimal(item["mark_price"]),
                funding_rate=_decimal(item["funding_rate"]),
                open_interest=_decimal(item["open_interest"]),
                base_volume=_decimal(item.get("base_volume"), default="0"),
                quote_volume=_decimal(item.get("quote_volume"), default="0"),
                sequence=int(item.get("sequence", 0)),
                updated_at=_datetime(item["updated_at"]),
            ),
        )

    orderbooks = payload.get("orderbooks", {})
    if not isinstance(orderbooks, dict):
        raise ValueError("orderbooks must be an object")
    for exchange, item in orderbooks.items():
        if not isinstance(item, dict):
            raise ValueError("orderbook must be an object")
        bridge.put_orderbook(
            str(exchange),
            Orderbook(
                pair=pair,
                bids=tuple(_level(level) for level in item.get("bids", [])),
                asks=tuple(_level(level) for level in item.get("asks", [])),
                sequence=int(item.get("sequence", 0)),
                updated_at=_datetime(item["updated_at"]),
            ),
        )

    for funding in _funding_history(pair, payload.get("funding_history", [])):
        platform_db_source.put_funding(funding)
    for open_interest in _open_interest_history(pair, payload.get("open_interest_history", [])):
        platform_db_source.put_open_interest(open_interest)

    liquidation_source_configured = "liquidation_events" in payload
    liquidation_source: LiquidationSource | None = None
    if liquidation_source_configured:
        events = [
            LiquidationEvent(
                time=_datetime(item["time"]),
                pair=_pair(item["pair"]) if isinstance(item, dict) and "pair" in item else pair,
                usd_size=_decimal(item["usd_size"]),
            )
            for item in _list_payload(payload.get("liquidation_events"))
        ]
        liquidation_source = InMemoryLiquidationSource(events=events)

    return SingleCycleSourceBundle(
        now_utc=_datetime(payload["now_utc"]),
        pair=pair,
        bridge=bridge,
        platform_db_source=platform_db_source,
        liquidation_source=liquidation_source,
        liquidation_source_configured=liquidation_source_configured,
    )


def load_configured_single_cycle_sources(
    settings: Settings,
    *,
    pair: Pair,
    now_utc: datetime | None = None,
) -> SingleCycleSourceBundle:
    if settings.platform_db_path is None:
        raise ValueError("platform_db_path must be configured")
    if settings.market_state_snapshot_path is None:
        raise ValueError("market_state_snapshot_path must be configured")
    if settings.orderbook_snapshot_path is None:
        raise ValueError("orderbook_snapshot_path must be configured")

    bridge = FilePlatformBridge(
        market_state_path=settings.market_state_snapshot_path,
        orderbook_path=settings.orderbook_snapshot_path,
    )
    liquidation_source = None
    liquidation_source_configured = False
    if settings.liquidation_events_path is not None and settings.liquidation_events_path.is_file():
        liquidation_source = JsonFileLiquidationSource(settings.liquidation_events_path)
        liquidation_source_configured = True

    return SingleCycleSourceBundle(
        now_utc=ensure_utc(now_utc or datetime.now(timezone.utc)),
        pair=pair,
        bridge=bridge,
        platform_db_source=SQLitePlatformDBSource(settings.platform_db_path),
        liquidation_source=liquidation_source,
        liquidation_source_configured=liquidation_source_configured,
    )


def execute_single_cycle(
    *,
    settings: Settings,
    run: PaperRun,
    source_bundle: SingleCycleSourceBundle,
) -> SingleCycleExecutionResult:
    if settings.risky_artifact_path is None or settings.safe_artifact_path is None:
        raise ValueError("artifact paths must be configured for single-cycle runtime")

    risky_artifact, safe_artifact = load_artifact_pair(
        risky_artifact_path=settings.risky_artifact_path,
        safe_artifact_path=settings.safe_artifact_path,
    )
    scheduler = RoundScheduler(decision_buffer_seconds=settings.decision_buffer_seconds)
    funding_decision = scheduler.next_decision(source_bundle.now_utc)
    collector = SnapshotCollector(
        bridge=source_bundle.bridge,
        liquidation_source=source_bundle.liquidation_source,
        market_state_staleness_seconds=settings.market_state_staleness_seconds,
        orderbook_staleness_seconds=settings.orderbook_staleness_seconds,
    )
    bybit_snapshot, bitget_snapshot = collector.collect_pair_snapshots(
        pair=source_bundle.pair,
        funding_decision=funding_decision,
    )

    portfolio = PortfolioSimulator(run=run)
    orchestrator = build_platform_db_backed_orchestrator(
        platform_db_source=source_bundle.platform_db_source,
        risky_artifact=risky_artifact,
        safe_artifact=safe_artifact,
        scheduler=scheduler,
    )
    cycle_result = orchestrator.evaluate(
        SingleCycleInput(
            now_utc=source_bundle.now_utc,
            pair=source_bundle.pair,
            bybit_snapshot=bybit_snapshot,
            bitget_snapshot=bitget_snapshot,
            risky_artifact=risky_artifact,
            safe_artifact=safe_artifact,
            has_open_position=portfolio.has_open_position(source_bundle.pair),
        )
    )

    opened_position_id = None
    if cycle_result.decision.selected:
        position = portfolio.open_position(
            decision=cycle_result.decision,
            entry_time=source_bundle.now_utc,
            planned_exit_round=scheduler.exit_round(cycle_result.decision.funding_round),
        )
        opened_position_id = position.position_id

    run.mark_finished()
    artifact_writer = build_run_artifact_writer(Path(run.report_output_dir), run.report_filename_pattern)
    artifact_paths = artifact_writer.write_outputs(
        run=run,
        as_of_round=funding_decision.funding_round,
        open_positions=sum(1 for position in portfolio.positions.values() if position.state.value == "open"),
        closed_trades=portfolio.trades,
    )
    cycle_artifact_path = artifact_writer.json_store.write_json(
        f"cycles/{run.run_id}.json",
        {
            "funding_decision": funding_decision,
            "bybit_snapshot": bybit_snapshot,
            "bitget_snapshot": bitget_snapshot,
            "feature": cycle_result.feature,
            "decision": cycle_result.decision,
            "opened_position_id": opened_position_id,
        },
    )
    return SingleCycleExecutionResult(
        funding_decision=funding_decision,
        cycle_result=cycle_result,
        artifact_paths=artifact_paths,
        cycle_artifact_path=cycle_artifact_path,
        opened_position_id=opened_position_id,
    )


def build_run_artifact_writer(base_dir: Path, filename_pattern: str) -> RunArtifactWriter:
    return RunArtifactWriter(
        report_writer=MarkdownReportWriter(
            output_dir=base_dir,
            filename_pattern=filename_pattern,
        ),
        json_store=JsonArtifactStore(base_dir),
        trade_log_writer=CsvTradeLogWriter(base_dir),
    )


def _funding_history(pair: Pair, payload: object) -> list[Funding]:
    history: list[Funding] = []
    for item in _list_payload(payload):
        history.append(
            Funding(
                time=_datetime(item["time"]),
                exchange=str(item["exchange"]),
                base=pair.base,
                quote=pair.quote,
                funding_rate=_decimal(item["funding_rate"]),
            )
        )
    return history


def _open_interest_history(pair: Pair, payload: object) -> list[OpenInterest]:
    history: list[OpenInterest] = []
    for item in _list_payload(payload):
        history.append(
            OpenInterest(
                time=_datetime(item["time"]),
                exchange=str(item["exchange"]),
                base=pair.base,
                quote=pair.quote,
                open_interest=_decimal(item["open_interest"]),
            )
        )
    return history


def _list_payload(payload: object) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError("payload must be a list")
    normalized: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("list items must be objects")
        normalized.append(item)
    return normalized
