from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import Settings
from .contracts import Pair, PaperRun
from .runtime import preflight_live_source_status, preflight_status, resolve_runtime_availability
from .single_cycle_runtime import (
    build_run_artifact_writer,
    execute_single_cycle,
    load_configured_single_cycle_sources,
    load_single_cycle_fixture,
)


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
    run_forward_parser.add_argument("--strict-liquidation", choices=["true", "false"], default=None)
    return parser


def run_forward(
    report_dir: Path | None = None,
    strict_liquidation: bool | None = None,
    input_file: Path | None = None,
    pair: Pair | None = None,
    now_utc: datetime | None = None,
) -> int:
    settings = Settings.from_env()
    if report_dir is not None:
        settings.report_output_dir = report_dir
    if strict_liquidation is not None:
        settings.strict_liquidation = strict_liquidation

    run = PaperRun.new(
        run_id=f"paper-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}",
        strategy=settings.strategy,
        runtime_mode=settings.runtime_mode,
        report_output_dir=str(settings.report_output_dir),
        report_filename_pattern=settings.report_filename_pattern,
        initial_equity=settings.initial_equity,
        notional_pct=settings.notional_pct,
        fee_bps=settings.fee_bps,
        slippage_bps=settings.slippage_bps,
        decision_buffer_seconds=settings.decision_buffer_seconds,
        market_state_staleness_sec=settings.market_state_staleness_seconds,
        orderbook_staleness_sec=settings.orderbook_staleness_seconds,
        strict_liquidation=settings.strict_liquidation,
    )

    source_bundle = None
    try:
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
            print(f"run blocked: {run.status_reason}")
            return 2

        if input_file is None and pair is not None:
            status, reason = preflight_live_source_status(availability)
            if status == "blocked":
                run.mark_blocked(reason)
                print(f"run blocked: {run.status_reason}")
                return 2
            source_bundle = load_configured_single_cycle_sources(
                settings,
                pair=pair,
                now_utc=now_utc,
            )

        if source_bundle is None:
            print(f"run ready: {run.run_id}")
            return 0

        result = execute_single_cycle(
            settings=settings,
            run=run,
            source_bundle=source_bundle,
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
        print(f"run failed: {run.status_reason}")
        print(f"summary: {artifact_paths.summary_path}")
        return 1

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
        return run_forward(
            report_dir=args.report_dir,
            strict_liquidation=strict,
            input_file=args.input_file,
            pair=args.pair,
            now_utc=args.now_utc,
        )
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
