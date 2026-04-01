from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import Settings
from .contracts import PaperRun
from .runtime import preflight_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="papertrade")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run_forward_parser = subcommands.add_parser("run-forward")
    run_forward_parser.add_argument("--report-dir", type=Path, default=None)
    run_forward_parser.add_argument("--strict-liquidation", choices=["true", "false"], default=None)
    return parser


def run_forward(report_dir: Path | None = None, strict_liquidation: bool | None = None) -> int:
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
    has_model_artifacts = settings.risky_artifact_path is not None and settings.safe_artifact_path is not None
    status, reason = preflight_status(
        settings,
        has_liquidation_source=False,
        has_model_artifacts=has_model_artifacts,
    )
    if status == "blocked":
        run.mark_blocked(reason)
        print(f"run blocked: {run.status_reason}")
        return 2

    print(f"run ready: {run.run_id}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run-forward":
        strict = None
        if args.strict_liquidation is not None:
            strict = args.strict_liquidation == "true"
        return run_forward(report_dir=args.report_dir, strict_liquidation=strict)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
