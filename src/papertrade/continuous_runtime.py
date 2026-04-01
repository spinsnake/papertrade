from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import time
from typing import Callable, Sequence

from .config import Settings
from .contracts import Pair, PaperRun
from .portfolio import PortfolioSimulator
from .state_store import SQLiteStateStore
from .sources.liquidation import BybitLiveLiquidationSource
from .sources.platform_db import PostgresPlatformDBSource, SQLitePlatformDBSource, sync_all_instruments_from_source
from .single_cycle_runtime import (
    PreparedCycleRuntime,
    SingleCycleExecutionResult,
    SingleCycleSourceBundle,
    build_run_artifact_writer,
    execute_cycle,
    load_configured_single_cycle_sources,
    prepare_cycle_runtime,
)


SourceLoader = Callable[[datetime], SingleCycleSourceBundle | Sequence[SingleCycleSourceBundle]]


@dataclass(frozen=True)
class ContinuousCycleResult:
    funding_round: datetime
    results: tuple[SingleCycleExecutionResult, ...]


@dataclass
class ContinuousForwardRunner:
    settings: Settings
    run: PaperRun
    source_loader: SourceLoader
    state_store: SQLiteStateStore | None = None
    pair: Pair | None = None
    portfolio: PortfolioSimulator = field(init=False)
    processed_rounds: set[datetime] = field(default_factory=set)
    last_result: SingleCycleExecutionResult | None = None
    last_cycle_result: ContinuousCycleResult | None = None

    def __post_init__(self) -> None:
        if self.state_store is not None:
            positions = self.state_store.load_positions(self.run.run_id)
            trades = self.state_store.load_trades(self.run.run_id)
            self.portfolio = PortfolioSimulator.from_state(
                run=self.run,
                positions=positions,
                trades=trades,
            )
            self.state_store.save_run(self.run)
        else:
            self.portfolio = PortfolioSimulator(run=self.run)

    def process_cycle(self, now_utc: datetime) -> ContinuousCycleResult | None:
        source_bundles = _normalize_source_bundles(self.source_loader(now_utc))
        prepared_items: list[tuple[SingleCycleSourceBundle, PreparedCycleRuntime, datetime]] = []
        seen_pairs: set[Pair] = set()
        cycle_funding_round: datetime | None = None

        for source_bundle in source_bundles:
            if source_bundle.pair in seen_pairs:
                raise ValueError("source_loader returned duplicate pairs for the same continuous cycle")
            seen_pairs.add(source_bundle.pair)

            prepared_runtime = prepare_cycle_runtime(
                settings=self.settings,
                source_bundle=source_bundle,
                run=self.run,
            )
            funding_decision = prepared_runtime.scheduler.next_decision(source_bundle.now_utc)
            if cycle_funding_round is None:
                cycle_funding_round = funding_decision.funding_round
            elif funding_decision.funding_round != cycle_funding_round:
                raise ValueError("all source bundles in a continuous cycle must resolve to the same funding round")

            prepared_items.append((source_bundle, prepared_runtime, funding_decision.funding_round))

        if cycle_funding_round is None:
            raise ValueError("source_loader returned no source bundles")
        if cycle_funding_round in self.processed_rounds:
            return None

        results: list[SingleCycleExecutionResult] = []
        for source_bundle, prepared_runtime, _ in prepared_items:
            result = execute_cycle(
                run=self.run,
                portfolio=self.portfolio,
                source_bundle=source_bundle,
                prepared_runtime=prepared_runtime,
                mark_run_finished=False,
            )
            results.append(result)

        cycle_result = ContinuousCycleResult(
            funding_round=cycle_funding_round,
            results=tuple(results),
        )
        self.processed_rounds.add(cycle_funding_round)
        self.last_cycle_result = cycle_result
        self.last_result = results[-1] if results else None
        self._sync_state_store(cycle_result)
        return cycle_result

    def finish(self) -> None:
        self.run.mark_finished()
        artifact_writer = build_run_artifact_writer(self._report_dir(), self.run.report_filename_pattern)
        if self.last_result is None:
            paths = artifact_writer.write_outputs(
                run=self.run,
                as_of_round=datetime.now(timezone.utc),
                open_positions=0,
                closed_trades=self.portfolio.trades,
            )
            as_of_round = datetime.now(timezone.utc)
        else:
            as_of_round = self.last_cycle_result.funding_round if self.last_cycle_result is not None else self.last_result.funding_decision.funding_round
            paths = artifact_writer.write_outputs(
                run=self.run,
                as_of_round=as_of_round,
                open_positions=sum(1 for position in self.portfolio.positions.values() if position.state.value == "open"),
                closed_trades=self.portfolio.trades,
            )

        if self.state_store is not None:
            self.state_store.save_run(self.run)
            self.state_store.record_report(run_id=self.run.run_id, as_of_round=as_of_round, report_type="summary", report_path=paths.summary_path)
            self.state_store.record_report(run_id=self.run.run_id, as_of_round=as_of_round, report_type="run_metadata", report_path=paths.run_metadata_path)
            self.state_store.record_report(run_id=self.run.run_id, as_of_round=as_of_round, report_type="trade_log", report_path=paths.trade_log_path)

    def close(self) -> None:
        close = getattr(self.source_loader, "close", None)
        if callable(close):
            close()

    def run_loop(
        self,
        *,
        max_cycles: int | None,
        poll_seconds: int,
        now_provider: Callable[[], datetime],
        sleep_fn: Callable[[float], None],
    ) -> int:
        if max_cycles is not None and max_cycles <= 0:
            raise ValueError("max_cycles must be positive")
        if poll_seconds < 0:
            raise ValueError("poll_seconds must not be negative")

        completed_cycles = 0
        while max_cycles is None or completed_cycles < max_cycles:
            cycle_result = self.process_cycle(now_provider())
            if cycle_result is not None:
                completed_cycles += 1
            if max_cycles is not None and completed_cycles >= max_cycles:
                break
            sleep_fn(float(poll_seconds))

        self.finish()
        return completed_cycles

    def _report_dir(self):
        from pathlib import Path

        return Path(self.run.report_output_dir)

    def _sync_state_store(self, cycle_result: ContinuousCycleResult) -> None:
        if self.state_store is None:
            return
        self.state_store.save_run(self.run)
        self.state_store.replace_feature_snapshots(
            result.cycle_result.feature
            for result in cycle_result.results
        )
        self.state_store.replace_portfolio_state(
            run_id=self.run.run_id,
            positions=self.portfolio.positions.values(),
            trades=self.portfolio.trades,
        )
        for result in cycle_result.results:
            self.state_store.record_report(
                run_id=self.run.run_id,
                as_of_round=result.funding_decision.funding_round,
                report_type="summary",
                report_path=result.artifact_paths.summary_path,
            )
            self.state_store.record_report(
                run_id=self.run.run_id,
                as_of_round=result.funding_decision.funding_round,
                report_type="run_metadata",
                report_path=result.artifact_paths.run_metadata_path,
            )
            self.state_store.record_report(
                run_id=self.run.run_id,
                as_of_round=result.funding_decision.funding_round,
                report_type="trade_log",
                report_path=result.artifact_paths.trade_log_path,
            )
            self.state_store.record_report(
                run_id=self.run.run_id,
                as_of_round=result.funding_decision.funding_round,
                report_type="cycle",
                report_path=result.cycle_artifact_path,
            )


def build_real_source_loader(settings: Settings, pair: Pair | None) -> SourceLoader:
    return RealSourceLoader(settings=settings, pair=pair)


@dataclass
class RealSourceLoader:
    settings: Settings
    pair: Pair | None
    _shared_liquidation_source: BybitLiveLiquidationSource | None = field(init=False, default=None)
    _shared_pairs: tuple[Pair, ...] = field(init=False, default_factory=tuple)
    _resolved_pairs_cache: tuple[Pair, ...] = field(init=False, default_factory=tuple)
    _resolved_pairs_loaded_at: datetime | None = field(init=False, default=None)

    def __call__(self, now_utc: datetime) -> tuple[SingleCycleSourceBundle, ...]:
        pairs = self._resolve_pairs()
        liquidation_source = self._get_shared_liquidation_source(pairs)
        return tuple(
            load_configured_single_cycle_sources(
                self.settings,
                pair=cycle_pair,
                now_utc=now_utc,
                liquidation_source_override=liquidation_source,
                liquidation_source_configured_override=(
                    self.settings.live_liquidation_source if liquidation_source is not None else None
                ),
            )
            for cycle_pair in pairs
        )

    def close(self) -> None:
        if self._shared_liquidation_source is None:
            return
        self._shared_liquidation_source.stop()
        self._shared_liquidation_source = None
        self._shared_pairs = ()

    def _resolve_pairs(self) -> tuple[Pair, ...]:
        if self.pair is not None:
            return (self.pair,)
        if (
            self._resolved_pairs_cache
            and self._resolved_pairs_loaded_at is not None
            and datetime.now(timezone.utc) - self._resolved_pairs_loaded_at < timedelta(hours=1)
        ):
            return self._resolved_pairs_cache

        if self.settings.live_platform_sources and self.settings.platform_db_path is not None:
            from .sources.platform_db import ExchangeRestPlatformDBSource

            platform_db_source = SQLitePlatformDBSource(self.settings.platform_db_path)
            live_reference_source = ExchangeRestPlatformDBSource(
                bybit_base_url=self.settings.bybit_rest_base_url,
                bitget_base_url=self.settings.bitget_rest_base_url,
            )
            sync_all_instruments_from_source(platform_db_source, live_reference_source)
        elif self.settings.platform_postgres_dsn:
            platform_db_source = PostgresPlatformDBSource(self.settings.platform_postgres_dsn)
        elif self.settings.live_platform_sources:
            from .sources.platform_db import ExchangeRestPlatformDBSource

            platform_db_source = ExchangeRestPlatformDBSource(
                bybit_base_url=self.settings.bybit_rest_base_url,
                bitget_base_url=self.settings.bitget_rest_base_url,
            )
        else:
            if self.settings.platform_db_path is None:
                raise ValueError("platform_db_path must be configured")
            platform_db_source = SQLitePlatformDBSource(self.settings.platform_db_path)

        pairs = tuple(platform_db_source.list_pairs())
        if not pairs:
            raise ValueError("no eligible pairs found in platform_db_source")
        self._resolved_pairs_cache = pairs
        self._resolved_pairs_loaded_at = datetime.now(timezone.utc)
        return pairs

    def _get_shared_liquidation_source(
        self,
        pairs: tuple[Pair, ...],
    ) -> BybitLiveLiquidationSource | None:
        if not self.settings.live_liquidation_source:
            return None
        if self._shared_liquidation_source is not None and self._shared_pairs == pairs:
            return self._shared_liquidation_source

        self.close()
        self._shared_pairs = pairs
        self._shared_liquidation_source = BybitLiveLiquidationSource(
            pairs=pairs,
            ws_url=self.settings.bybit_liquidation_ws_url,
            cache_path=self.settings.live_liquidation_cache_path,
        )
        return self._shared_liquidation_source


def build_simulated_now_provider(
    *,
    start_utc: datetime,
    step_seconds: int,
) -> Callable[[], datetime]:
    current = start_utc - timedelta(seconds=step_seconds)

    def _provider() -> datetime:
        nonlocal current
        current = current + timedelta(seconds=step_seconds)
        return current

    return _provider


def build_real_now_provider() -> Callable[[], datetime]:
    return lambda: datetime.now(timezone.utc)


def real_sleep(seconds: float) -> None:
    time.sleep(seconds)


def _normalize_source_bundles(
    loaded: SingleCycleSourceBundle | Sequence[SingleCycleSourceBundle],
) -> tuple[SingleCycleSourceBundle, ...]:
    if isinstance(loaded, SingleCycleSourceBundle):
        return (loaded,)
    return tuple(loaded)
