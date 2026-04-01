from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import Settings
from .contracts import Funding, FundingRoundSnapshot, Level, MarketState, OpenInterest, Orderbook, Pair, PaperRun
from .orchestrator import (
    SingleCycleInput,
    SingleCycleResult,
    SingleCycleOrchestrator,
    build_platform_db_backed_orchestrator,
)
from .persistence import CsvTradeLogWriter, JsonArtifactStore, RunArtifactPaths, RunArtifactWriter
from .portfolio import PortfolioSimulator
from .report import MarkdownReportWriter, format_as_of_round
from .scheduler import FundingDecision, RoundScheduler, ensure_utc
from .scoring import LogisticArtifact, load_artifact_pair
from .slippage import estimate_entry_slippage_bps, estimate_exit_slippage_bps
from .snapshot_collector import SnapshotCollector
from .sources.liquidation import (
    BybitLiveLiquidationSource,
    InMemoryLiquidationSource,
    JsonFileLiquidationSource,
    LiquidationEvent,
    LiquidationSource,
)
from .sources.platform_bridge import ExchangeRestPlatformBridge, FilePlatformBridge, InMemoryPlatformBridge, PlatformBridgeSource
from .sources.platform_db import (
    InMemoryPlatformDBSource,
    PlatformDBSource,
    PostgresPlatformDBSource,
    SQLitePlatformDBSource,
    sync_pair_history_from_source,
)
from .sources.platform_snapshots import (
    FundingRoundSnapshotSource,
    FundingRoundSnapshotStore,
    PostgresFundingRoundSnapshotSource,
    SQLiteFundingRoundSnapshotSource,
)


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
    platform_db_source: PlatformDBSource
    bridge: PlatformBridgeSource | None = None
    snapshot_source: FundingRoundSnapshotSource | None = None
    snapshot_store: FundingRoundSnapshotStore | None = None
    liquidation_source: LiquidationSource | None = None
    liquidation_source_configured: bool = False

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
    settled_position_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedCycleRuntime:
    scheduler: RoundScheduler
    collector: SnapshotCollector | None
    orchestrator: SingleCycleOrchestrator
    artifact_writer: RunArtifactWriter
    risky_artifact: LogisticArtifact
    safe_artifact: LogisticArtifact
    slippage_model: str


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
    liquidation_source_override: LiquidationSource | None = None,
    liquidation_source_configured_override: bool | None = None,
) -> SingleCycleSourceBundle:
    bridge: PlatformBridgeSource | None = None
    snapshot_source: FundingRoundSnapshotSource | None = None
    snapshot_store: FundingRoundSnapshotStore | None = None

    if settings.live_platform_sources and settings.platform_db_path is not None:
        bridge = ExchangeRestPlatformBridge(
            bybit_base_url=settings.bybit_rest_base_url,
            bitget_base_url=settings.bitget_rest_base_url,
        )
        from .sources.platform_db import ExchangeRestPlatformDBSource

        live_reference_source = ExchangeRestPlatformDBSource(
            bybit_base_url=settings.bybit_rest_base_url,
            bitget_base_url=settings.bitget_rest_base_url,
        )
        platform_db_source = SQLitePlatformDBSource(settings.platform_db_path)
        sync_pair_history_from_source(
            platform_db_source,
            live_reference_source,
            pair=pair,
            funding_limit=8,
            open_interest_limit=8,
        )
        snapshot_store = SQLiteFundingRoundSnapshotSource(
            path=settings.platform_db_path,
            platform_db_source=platform_db_source,
            open_interest_mode=settings.open_interest_mode,
        )
    elif settings.platform_postgres_dsn:
        platform_db_source: PlatformDBSource = PostgresPlatformDBSource(settings.platform_postgres_dsn)
        snapshot_source = PostgresFundingRoundSnapshotSource(
            dsn=settings.platform_postgres_dsn,
            platform_db_source=platform_db_source,
            open_interest_mode=settings.open_interest_mode,
        )
    elif settings.live_platform_sources:
        bridge = ExchangeRestPlatformBridge(
            bybit_base_url=settings.bybit_rest_base_url,
            bitget_base_url=settings.bitget_rest_base_url,
        )
        from .sources.platform_db import ExchangeRestPlatformDBSource

        platform_db_source = ExchangeRestPlatformDBSource(
            bybit_base_url=settings.bybit_rest_base_url,
            bitget_base_url=settings.bitget_rest_base_url,
        )
    else:
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
        platform_db_source = SQLitePlatformDBSource(settings.platform_db_path)

    liquidation_source = liquidation_source_override
    liquidation_source_configured = False if liquidation_source_configured_override is None else liquidation_source_configured_override
    if liquidation_source_override is None and liquidation_source_configured_override is None:
        if settings.live_liquidation_source:
            liquidation_source = BybitLiveLiquidationSource(
                pairs=(pair,),
                ws_url=settings.bybit_liquidation_ws_url,
                cache_path=settings.live_liquidation_cache_path,
            )
            liquidation_source_configured = True
        elif settings.liquidation_events_path is not None and settings.liquidation_events_path.is_file():
            liquidation_source = JsonFileLiquidationSource(settings.liquidation_events_path)
            liquidation_source_configured = True

    return SingleCycleSourceBundle(
        now_utc=ensure_utc(now_utc or datetime.now(timezone.utc)),
        pair=pair,
        bridge=bridge,
        snapshot_source=snapshot_source,
        snapshot_store=snapshot_store,
        platform_db_source=platform_db_source,
        liquidation_source=liquidation_source,
        liquidation_source_configured=liquidation_source_configured,
    )


def execute_single_cycle(
    *,
    settings: Settings,
    run: PaperRun,
    source_bundle: SingleCycleSourceBundle,
    portfolio: PortfolioSimulator | None = None,
) -> SingleCycleExecutionResult:
    prepared_runtime = prepare_cycle_runtime(
        settings=settings,
        source_bundle=source_bundle,
        run=run,
    )
    portfolio = portfolio or PortfolioSimulator(run=run)
    return execute_cycle(
        run=run,
        portfolio=portfolio,
        source_bundle=source_bundle,
        prepared_runtime=prepared_runtime,
        mark_run_finished=True,
    )


def prepare_cycle_runtime(
    *,
    settings: Settings,
    source_bundle: SingleCycleSourceBundle,
    run: PaperRun,
) -> PreparedCycleRuntime:
    if settings.risky_artifact_path is None or settings.safe_artifact_path is None:
        raise ValueError("artifact paths must be configured for single-cycle runtime")

    risky_artifact, safe_artifact = load_artifact_pair(
        risky_artifact_path=settings.risky_artifact_path,
        safe_artifact_path=settings.safe_artifact_path,
    )
    scheduler = RoundScheduler(decision_buffer_seconds=settings.decision_buffer_seconds)
    collector = None
    if source_bundle.bridge is not None:
        collector = SnapshotCollector(
            bridge=source_bundle.bridge,
            platform_db_source=source_bundle.platform_db_source,
            liquidation_source=source_bundle.liquidation_source,
            market_state_staleness_seconds=settings.market_state_staleness_seconds,
            orderbook_staleness_seconds=settings.orderbook_staleness_seconds,
            open_interest_mode=settings.open_interest_mode,
        )
    orchestrator = build_platform_db_backed_orchestrator(
        platform_db_source=source_bundle.platform_db_source,
        risky_artifact=risky_artifact,
        safe_artifact=safe_artifact,
        scheduler=scheduler,
        require_complete_liquidation=settings.strict_liquidation,
    )
    return PreparedCycleRuntime(
        scheduler=scheduler,
        collector=collector,
        orchestrator=orchestrator,
        artifact_writer=build_run_artifact_writer(Path(run.report_output_dir), run.report_filename_pattern),
        risky_artifact=risky_artifact,
        safe_artifact=safe_artifact,
        slippage_model=settings.slippage_model,
    )


def execute_cycle(
    *,
    run: PaperRun,
    portfolio: PortfolioSimulator,
    source_bundle: SingleCycleSourceBundle,
    prepared_runtime: PreparedCycleRuntime,
    mark_run_finished: bool,
) -> SingleCycleExecutionResult:
    funding_decision = prepared_runtime.scheduler.next_decision(source_bundle.now_utc)
    bybit_snapshot, bitget_snapshot = _resolve_pair_snapshots(
        source_bundle=source_bundle,
        prepared_runtime=prepared_runtime,
        funding_decision=funding_decision,
    )
    _persist_pair_snapshots(
        snapshot_store=source_bundle.snapshot_store,
        snapshots=(bybit_snapshot, bitget_snapshot),
    )
    cycle_result = prepared_runtime.orchestrator.evaluate(
        SingleCycleInput(
            now_utc=source_bundle.now_utc,
            pair=source_bundle.pair,
            bybit_snapshot=bybit_snapshot,
            bitget_snapshot=bitget_snapshot,
            risky_artifact=prepared_runtime.risky_artifact,
            safe_artifact=prepared_runtime.safe_artifact,
            has_open_position=portfolio.has_open_position(source_bundle.pair),
        )
    )

    opened_position_id = None
    if cycle_result.decision.selected:
        entry_slippage_bps = estimate_entry_slippage_bps(
            decision=cycle_result.decision,
            notional=run.current_equity * run.notional_pct,
            bybit_snapshot=bybit_snapshot,
            bitget_snapshot=bitget_snapshot,
            platform_db_source=source_bundle.platform_db_source,
            model=prepared_runtime.slippage_model,
            fallback_total_bps=run.slippage_bps,
        )
        position = portfolio.open_position(
            decision=cycle_result.decision,
            entry_time=source_bundle.now_utc,
            planned_exit_round=prepared_runtime.scheduler.exit_round(cycle_result.decision.funding_round),
            entry_slippage_bps=entry_slippage_bps,
        )
        opened_position_id = position.position_id

    settled_position_ids = _settle_positions_for_round(
        portfolio=portfolio,
        pair=source_bundle.pair,
        funding_round=funding_decision.funding_round,
        bybit_snapshot=bybit_snapshot,
        bitget_snapshot=bitget_snapshot,
        platform_db_source=source_bundle.platform_db_source,
        slippage_model=prepared_runtime.slippage_model,
        fallback_slippage_bps=run.slippage_bps,
        bybit_funding_rate_bps=bybit_snapshot.funding_rate_bps,
        bitget_funding_rate_bps=bitget_snapshot.funding_rate_bps,
    )

    if mark_run_finished:
        run.mark_finished()

    artifact_paths = prepared_runtime.artifact_writer.write_outputs(
        run=run,
        as_of_round=funding_decision.funding_round,
        open_positions=sum(1 for position in portfolio.positions.values() if position.state.value == "open"),
        closed_trades=portfolio.trades,
    )
    cycle_artifact_path = prepared_runtime.artifact_writer.json_store.write_json(
        f"cycles/{run.run_id}__{source_bundle.pair.symbol}__{format_as_of_round(funding_decision.funding_round)}.json",
        {
            "funding_decision": funding_decision,
            "bybit_snapshot": bybit_snapshot,
            "bitget_snapshot": bitget_snapshot,
            "feature": cycle_result.feature,
            "decision": cycle_result.decision,
            "opened_position_id": opened_position_id,
            "settled_position_ids": settled_position_ids,
        },
    )
    return SingleCycleExecutionResult(
        funding_decision=funding_decision,
        cycle_result=cycle_result,
        artifact_paths=artifact_paths,
        cycle_artifact_path=cycle_artifact_path,
        opened_position_id=opened_position_id,
        settled_position_ids=settled_position_ids,
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


def close_source_bundle(source_bundle: SingleCycleSourceBundle) -> None:
    stop = getattr(source_bundle.liquidation_source, "stop", None)
    if callable(stop):
        stop()


def _resolve_pair_snapshots(
    *,
    source_bundle: SingleCycleSourceBundle,
    prepared_runtime: PreparedCycleRuntime,
    funding_decision: FundingDecision,
) -> tuple[FundingRoundSnapshot, FundingRoundSnapshot]:
    if source_bundle.snapshot_source is not None:
        bybit_snapshot = source_bundle.snapshot_source.get_snapshot(
            exchange="bybit",
            pair=source_bundle.pair,
            funding_round=funding_decision.funding_round,
        )
        bitget_snapshot = source_bundle.snapshot_source.get_snapshot(
            exchange="bitget",
            pair=source_bundle.pair,
            funding_round=funding_decision.funding_round,
        )
        resolved_bybit = _ensure_snapshot(
            snapshot=bybit_snapshot,
            exchange="bybit",
            pair=source_bundle.pair,
            funding_decision=funding_decision,
        )
        resolved_bitget = _ensure_snapshot(
            snapshot=bitget_snapshot,
            exchange="bitget",
            pair=source_bundle.pair,
            funding_decision=funding_decision,
        )
        return (
            _hydrate_liquidation_window(
                snapshot=resolved_bybit,
                liquidation_source=source_bundle.liquidation_source,
            ),
            _hydrate_liquidation_window(
                snapshot=resolved_bitget,
                liquidation_source=source_bundle.liquidation_source,
            ),
        )

    if prepared_runtime.collector is None:
        raise ValueError("collector is required when snapshot_source is not configured")

    return prepared_runtime.collector.collect_pair_snapshots(
        pair=source_bundle.pair,
        funding_decision=funding_decision,
    )


def _ensure_snapshot(
    *,
    snapshot: FundingRoundSnapshot | None,
    exchange: str,
    pair: Pair,
    funding_decision: FundingDecision,
) -> FundingRoundSnapshot:
    if snapshot is None:
        return FundingRoundSnapshot(
            funding_round=funding_decision.funding_round,
            decision_cutoff=funding_decision.decision_cutoff,
            exchange=exchange,
            pair=pair,
            market_state_observed_at=None,
            orderbook_observed_at=None,
            funding_rate_bps=None,
            mark_price=None,
            index_price=None,
            open_interest=None,
            bid_price=None,
            ask_price=None,
            bid_amount=None,
            ask_amount=None,
            book_imbalance=None,
            liquidation_amount_8h=None if exchange == "bybit" else Decimal("0"),
            liquidation_complete=(exchange != "bybit"),
            snapshot_valid=False,
            reason_code=f"missing_platform_snapshot_{exchange}",
        )

    if snapshot.funding_round != funding_decision.funding_round or snapshot.decision_cutoff != funding_decision.decision_cutoff:
        return replace(
            snapshot,
            funding_round=funding_decision.funding_round,
            decision_cutoff=funding_decision.decision_cutoff,
            snapshot_valid=False,
            reason_code=f"snapshot_round_mismatch_{exchange}",
        )
    return snapshot


def _hydrate_liquidation_window(
    *,
    snapshot: FundingRoundSnapshot,
    liquidation_source: LiquidationSource | None,
) -> FundingRoundSnapshot:
    if snapshot.exchange != "bybit":
        return replace(snapshot, liquidation_amount_8h=Decimal("0"), liquidation_complete=True)
    if snapshot.liquidation_complete and snapshot.liquidation_amount_8h is not None:
        return snapshot
    if liquidation_source is None:
        return snapshot

    liquidation_start = snapshot.funding_round - timedelta(hours=8)
    liquidation_end = snapshot.funding_round
    amount = liquidation_source.sum_bybit_liquidation_usd(snapshot.pair, liquidation_start, liquidation_end)
    complete = True
    covers_window = getattr(liquidation_source, "covers_bybit_liquidation_window", None)
    if callable(covers_window):
        complete = bool(covers_window(snapshot.pair, liquidation_start, liquidation_end))
    return replace(
        snapshot,
        liquidation_amount_8h=amount,
        liquidation_complete=complete,
    )


def _settle_positions_for_round(
    *,
    portfolio: PortfolioSimulator,
    pair: Pair,
    funding_round: datetime,
    bybit_snapshot: FundingRoundSnapshot,
    bitget_snapshot: FundingRoundSnapshot,
    platform_db_source: PlatformDBSource,
    slippage_model: str,
    fallback_slippage_bps: Decimal,
    bybit_funding_rate_bps: Decimal | None,
    bitget_funding_rate_bps: Decimal | None,
) -> tuple[str, ...]:
    settled: list[str] = []
    for position_id, position in tuple(portfolio.positions.items()):
        if position.pair != pair or position.state.value != "open":
            continue
        if position.entry_round > funding_round or position.planned_exit_round < funding_round:
            continue
        if position.rounds and position.rounds[-1].funding_round >= funding_round:
            continue
        exit_slippage_bps = None
        if position.rounds_collected + 1 == 3:
            exit_slippage_bps = estimate_exit_slippage_bps(
                position=position,
                bybit_snapshot=bybit_snapshot,
                bitget_snapshot=bitget_snapshot,
                platform_db_source=platform_db_source,
                model=slippage_model,
                fallback_total_bps=fallback_slippage_bps,
            )
        portfolio.settle_round(
            position_id=position_id,
            funding_round=funding_round,
            bybit_funding_rate_bps=bybit_funding_rate_bps,
            bitget_funding_rate_bps=bitget_funding_rate_bps,
            exit_slippage_bps=exit_slippage_bps,
        )
        settled.append(position_id)
    return tuple(settled)


def _persist_pair_snapshots(
    *,
    snapshot_store: FundingRoundSnapshotStore | None,
    snapshots: tuple[FundingRoundSnapshot, FundingRoundSnapshot],
) -> None:
    if snapshot_store is None:
        return
    for snapshot in snapshots:
        snapshot_store.put_snapshot(snapshot)


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
