from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import Settings
from .enums import RunStatus
from .contracts import Pair, PaperRun
from .continuous_runtime import (
    ContinuousForwardRunner,
    build_real_now_provider,
    build_real_source_loader,
    build_simulated_now_provider,
    real_sleep,
)
from .portfolio import PortfolioSimulator
from .runtime import preflight_live_source_status, preflight_status, resolve_runtime_availability
from .single_cycle_runtime import (
    build_run_artifact_writer,
    close_source_bundle,
    execute_single_cycle,
    load_configured_single_cycle_sources,
    load_single_cycle_fixture,
)
from .state_store import SQLiteStateStore


def _parse_pair(value: str) -> Pair:
    for separator in ("/", "-", ":"):
        if separator in value:
            base, quote = value.split(separator, 1)
            if not base or not quote:
                break
            return Pair(base=base.upper(), quote=quote.upper())
    raise argparse.ArgumentTypeError("pair must be BASE/QUOTE, BASE-QUOTE, or BASE:QUOTE")


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="papertrade")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run_forward_parser = subcommands.add_parser("run-forward")
    run_forward_parser.add_argument("--pair", type=_parse_pair, default=None)
    run_forward_parser.add_argument("--now-utc", type=_parse_datetime, default=None)
    run_forward_parser.add_argument("--report-dir", type=Path, default=None)
    run_forward_parser.add_argument("--input-file", type=Path, default=None)
    run_forward_parser.add_argument("--continuous", action="store_true")
    run_forward_parser.add_argument("--max-cycles", type=int, default=None)
    run_forward_parser.add_argument("--poll-seconds", type=int, default=30)
    run_forward_parser.add_argument("--strict-liquidation", choices=["true", "false"], default=None)
    run_forward_parser.add_argument("--state-db", type=Path, default=None)
    run_forward_parser.add_argument("--platform-db", type=Path, default=None)
    run_forward_parser.add_argument("--platform-postgres-dsn", default=None)
    run_forward_parser.add_argument("--resume-latest", action="store_true")
    run_forward_parser.add_argument("--resume-run-id", default=None)
    return parser


def run_forward(
    report_dir: Path | None = None,
    strict_liquidation: bool | None = None,
    input_file: Path | None = None,
    pair: Pair | None = None,
    now_utc: datetime | None = None,
    continuous: bool = False,
    max_cycles: int | None = None,
    poll_seconds: int = 30,
    state_db: Path | None = None,
    platform_db: Path | None = None,
    platform_postgres_dsn: str | None = None,
    resume_latest: bool = False,
    resume_run_id: str | None = None,
) -> int:
    settings = Settings.from_env()
    runner: ContinuousForwardRunner | None = None
    if report_dir is not None:
        settings.report_output_dir = report_dir
    if strict_liquidation is not None:
        settings.strict_liquidation = strict_liquidation
    if state_db is not None:
        settings.state_db_path = state_db
    if platform_db is not None:
        settings.platform_db_path = platform_db
    if platform_postgres_dsn is not None:
        settings.platform_postgres_dsn = platform_postgres_dsn or None
    if settings.state_db_path is None and settings.platform_db_path is not None:
        settings.state_db_path = settings.platform_db_path
    settings.validate()
    if resume_latest and resume_run_id is not None:
        raise ValueError("resume_latest and resume_run_id are mutually exclusive")
    if (resume_latest or resume_run_id is not None) and settings.state_db_path is None:
        raise ValueError("state_db_path must be configured to resume runs")

    state_store = SQLiteStateStore(settings.state_db_path) if settings.state_db_path is not None else None
    run = _resolve_run(
        settings=settings,
        state_store=state_store,
        resume_latest=resume_latest,
        resume_run_id=resume_run_id,
    )

    source_bundle = None
    try:
        if continuous and input_file is not None:
            raise ValueError("continuous mode does not support --input-file")
        if continuous and now_utc is not None and max_cycles is None:
            raise ValueError("continuous mode with --now-utc requires --max-cycles")

        if state_store is not None:
            state_store.save_run(run)

        if input_file is not None:
            source_bundle = load_single_cycle_fixture(input_file)
        availability = resolve_runtime_availability(
            settings,
            has_liquidation_source_override=(
                source_bundle.has_liquidation_source
                if source_bundle is not None
                else None
            ),
        )
        status, reason = preflight_status(settings, availability)
        if status == "blocked":
            run.mark_blocked(reason)
            if state_store is not None:
                state_store.save_run(run)
            print(f"run blocked: {run.status_reason}")
            return 2

        if input_file is None and (pair is not None or continuous):
            status, reason = preflight_live_source_status(availability)
            if status == "blocked":
                run.mark_blocked(reason)
                if state_store is not None:
                    state_store.save_run(run)
                print(f"run blocked: {run.status_reason}")
                return 2

            if continuous:
                runner = ContinuousForwardRunner(
                    settings=settings,
                    run=run,
                    source_loader=build_real_source_loader(settings, pair),
                    state_store=state_store,
                    pair=pair,
                )
                if now_utc is None:
                    now_provider = build_real_now_provider()
                    sleep_fn = real_sleep
                else:
                    now_provider = build_simulated_now_provider(
                        start_utc=now_utc,
                        step_seconds=max(poll_seconds, 8 * 60 * 60),
                    )
                    sleep_fn = lambda _: None

                completed_cycles = runner.run_loop(
                    max_cycles=max_cycles,
                    poll_seconds=poll_seconds,
                    now_provider=now_provider,
                    sleep_fn=sleep_fn,
                )
                print(f"run finished: {run.run_id}")
                print(f"completed_cycles: {completed_cycles}")
                if runner.last_cycle_result is not None:
                    print(f"processed_pairs: {len(runner.last_cycle_result.results)}")
                if runner.last_result is not None:
                    print(f"summary: {runner.last_result.artifact_paths.summary_path}")
                    print(f"last_cycle: {runner.last_result.cycle_artifact_path}")
                return 0

            source_bundle = load_configured_single_cycle_sources(
                settings,
                pair=pair,
                now_utc=now_utc,
            )

        if source_bundle is None:
            if state_store is not None:
                state_store.save_run(run)
            print(f"run ready: {run.run_id}")
            return 0

        portfolio = None
        if state_store is not None:
            portfolio = PortfolioSimulator.from_state(
                run=run,
                positions=state_store.load_positions(run.run_id),
                trades=state_store.load_trades(run.run_id),
            )

        result = execute_single_cycle(
            settings=settings,
            run=run,
            source_bundle=source_bundle,
            portfolio=portfolio,
        )
        _persist_single_cycle_result(
            state_store=state_store,
            run=run,
            result=result,
            portfolio=portfolio,
        )
    except Exception as exc:
        run.mark_failed(str(exc))
        as_of_round = source_bundle.now_utc if source_bundle is not None else datetime.now(timezone.utc)
        artifact_writer = build_run_artifact_writer(Path(run.report_output_dir), run.report_filename_pattern)
        artifact_paths = artifact_writer.write_outputs(
            run=run,
            as_of_round=as_of_round,
            open_positions=0,
            closed_trades=[],
        )
        if state_store is not None:
            state_store.save_run(run)
            state_store.record_report(run_id=run.run_id, as_of_round=as_of_round, report_type="summary", report_path=artifact_paths.summary_path)
            state_store.record_report(run_id=run.run_id, as_of_round=as_of_round, report_type="run_metadata", report_path=artifact_paths.run_metadata_path)
            state_store.record_report(run_id=run.run_id, as_of_round=as_of_round, report_type="trade_log", report_path=artifact_paths.trade_log_path)
        print(f"run failed: {run.status_reason}")
        print(f"summary: {artifact_paths.summary_path}")
        return 1
    finally:
        if runner is not None:
            runner.close()
        elif source_bundle is not None:
            close_source_bundle(source_bundle)

    print(f"run finished: {run.run_id}")
    print(f"summary: {result.artifact_paths.summary_path}")
    print(f"cycle: {result.cycle_artifact_path}")
    if result.opened_position_id is not None:
        print(f"opened_position: {result.opened_position_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run-forward":
        strict = None
        if args.strict_liquidation is not None:
            strict = args.strict_liquidation == "true"
        try:
            return run_forward(
                report_dir=args.report_dir,
                strict_liquidation=strict,
                input_file=args.input_file,
                pair=args.pair,
                now_utc=args.now_utc,
                continuous=args.continuous,
                max_cycles=args.max_cycles,
                poll_seconds=args.poll_seconds,
                state_db=args.state_db,
                platform_db=args.platform_db,
                platform_postgres_dsn=args.platform_postgres_dsn,
                resume_latest=args.resume_latest,
                resume_run_id=args.resume_run_id,
            )
        except ValueError as exc:
            parser.error(str(exc))
    parser.error(f"unknown command: {args.command}")
    return 2


def _resolve_run(
    *,
    settings: Settings,
    state_store: SQLiteStateStore | None,
    resume_latest: bool,
    resume_run_id: str | None,
) -> PaperRun:
    if state_store is None:
        return _new_run(settings)

    existing_run = None
    if resume_run_id is not None:
        existing_run = state_store.load_run(resume_run_id)
        if existing_run is None:
            raise ValueError(f"resume_run_id not found: {resume_run_id}")
    elif resume_latest:
        existing_run = state_store.load_latest_resumable_run(
            strategy=settings.strategy,
            runtime_mode=settings.runtime_mode,
        )
        if existing_run is None:
            raise ValueError("no resumable run found")

    if existing_run is None:
        return _new_run(settings)

    existing_run.status = RunStatus.RUNNING
    existing_run.status_reason = "ok"
    existing_run.finished_at = None
    existing_run.report_output_dir = str(settings.report_output_dir)
    existing_run.report_filename_pattern = settings.report_filename_pattern
    existing_run.decision_buffer_seconds = settings.decision_buffer_seconds
    existing_run.market_state_staleness_sec = settings.market_state_staleness_seconds
    existing_run.orderbook_staleness_sec = settings.orderbook_staleness_seconds
    existing_run.bybit_taker_fee_bps = settings.bybit_taker_fee_bps
    existing_run.bitget_taker_fee_bps = settings.bitget_taker_fee_bps
    existing_run.fee_bps = settings.fee_bps
    existing_run.slippage_bps = settings.slippage_bps
    existing_run.strict_liquidation = settings.strict_liquidation
    return existing_run


def _new_run(settings: Settings) -> PaperRun:
    return PaperRun.new(
        run_id=f"paper-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}",
        strategy=settings.strategy,
        runtime_mode=settings.runtime_mode,
        report_output_dir=str(settings.report_output_dir),
        report_filename_pattern=settings.report_filename_pattern,
        initial_equity=settings.initial_equity,
        notional_pct=settings.notional_pct,
        slippage_bps=settings.slippage_bps,
        decision_buffer_seconds=settings.decision_buffer_seconds,
        market_state_staleness_sec=settings.market_state_staleness_seconds,
        orderbook_staleness_sec=settings.orderbook_staleness_seconds,
        strict_liquidation=settings.strict_liquidation,
        bybit_taker_fee_bps=settings.bybit_taker_fee_bps,
        bitget_taker_fee_bps=settings.bitget_taker_fee_bps,
    )


def _persist_single_cycle_result(
    *,
    state_store: SQLiteStateStore | None,
    run: PaperRun,
    result,
    portfolio: PortfolioSimulator | None,
) -> None:
    if state_store is None:
        return

    state_store.save_run(run)
    state_store.replace_feature_snapshots([result.cycle_result.feature])
    resolved_portfolio = portfolio or PortfolioSimulator(run=run)
    state_store.replace_portfolio_state(
        run_id=run.run_id,
        positions=resolved_portfolio.positions.values(),
        trades=resolved_portfolio.trades,
    )
    state_store.record_report(
        run_id=run.run_id,
        as_of_round=result.funding_decision.funding_round,
        report_type="summary",
        report_path=result.artifact_paths.summary_path,
    )
    state_store.record_report(
        run_id=run.run_id,
        as_of_round=result.funding_decision.funding_round,
        report_type="run_metadata",
        report_path=result.artifact_paths.run_metadata_path,
    )
    state_store.record_report(
        run_id=run.run_id,
        as_of_round=result.funding_decision.funding_round,
        report_type="trade_log",
        report_path=result.artifact_paths.trade_log_path,
    )
    state_store.record_report(
        run_id=run.run_id,
        as_of_round=result.funding_decision.funding_round,
        report_type="cycle",
        report_path=result.cycle_artifact_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
