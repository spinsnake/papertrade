from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from ..trading_logic.contracts import PaperRun, PaperTrade


WINDOWS_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*]')


def format_as_of_round(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y%m%dT%H%M%SZ")


def render_report_filename(
    pattern: str,
    *,
    strategy: str,
    run_id: str,
    as_of_round: datetime,
    report_type: str,
) -> str:
    rendered = (
        pattern.replace("{strategy}", strategy)
        .replace("{run_id}", run_id)
        .replace("{as_of_round}", format_as_of_round(as_of_round))
        .replace("{report_type}", report_type)
    )
    if WINDOWS_FORBIDDEN_CHARS.search(rendered):
        raise ValueError("rendered report filename is not Windows-safe")
    return rendered


@dataclass(frozen=True)
class MarkdownReportWriter:
    output_dir: Path
    filename_pattern: str

    def report_path(self, *, run: PaperRun, as_of_round: datetime, report_type: str) -> Path:
        filename = render_report_filename(
            self.filename_pattern,
            strategy=run.strategy,
            run_id=run.run_id,
            as_of_round=as_of_round,
            report_type=report_type,
        )
        return self.output_dir / filename

    def render_summary(
        self,
        *,
        run: PaperRun,
        as_of_round: datetime,
        open_positions: int,
        closed_trades: list[PaperTrade],
    ) -> str:
        return "\n".join(
            [
                "# Forward Paper Trade",
                "",
                "## Run Config",
                "",
                f"- run_id: `{run.run_id}`",
                f"- runtime_mode: `{run.runtime_mode}`",
                f"- status_reason: `{run.status_reason}`",
                f"- strategy: `{run.strategy}`",
                f"- current_equity: `{run.current_equity}`",
                f"- bybit_taker_fee_bps: `{run.bybit_taker_fee_bps}`",
                f"- bitget_taker_fee_bps: `{run.bitget_taker_fee_bps}`",
                f"- roundtrip_fee_bps: `{run.fee_bps}`",
                "",
                "## Runtime Status",
                "",
                f"- status: `{run.status.value}`",
                f"- as_of_round: `{as_of_round.isoformat()}`",
                f"- open_positions: `{open_positions}`",
                f"- closed_trades: `{len(closed_trades)}`",
            ]
        )

    def write_summary(
        self,
        *,
        run: PaperRun,
        as_of_round: datetime,
        open_positions: int,
        closed_trades: list[PaperTrade],
        report_type: str = "summary",
    ) -> Path:
        path = self.report_path(run=run, as_of_round=as_of_round, report_type=report_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = self.render_summary(
            run=run,
            as_of_round=as_of_round,
            open_positions=open_positions,
            closed_trades=closed_trades,
        )
        path.write_text(content, encoding="utf-8")
        return path
