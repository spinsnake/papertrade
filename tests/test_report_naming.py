from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from papertrade.trading_logic.contracts import PaperRun
from papertrade.data_management.report import MarkdownReportWriter, format_as_of_round, render_report_filename


class ReportNamingTests(unittest.TestCase):
    def test_report_filename_rendering_uses_windows_safe_as_of_round(self) -> None:
        as_of_round = datetime(2026, 3, 31, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(format_as_of_round(as_of_round), "20260331T080000Z")
        filename = render_report_filename(
            "{strategy}__{run_id}__{as_of_round}__{report_type}.md",
            strategy="hybrid_aggressive_safe_valid",
            run_id="paper-20260331-000000",
            as_of_round=as_of_round,
            report_type="summary",
        )
        self.assertEqual(
            filename,
            "hybrid_aggressive_safe_valid__paper-20260331-000000__20260331T080000Z__summary.md",
        )
        self.assertNotIn(":", filename)

    def test_report_writer_uses_rendered_filename_for_summary(self) -> None:
        run = PaperRun.new(
            run_id="paper-20260331-000000",
            strategy="hybrid_aggressive_safe_valid",
            runtime_mode="forward_market_listener",
            report_output_dir="reports",
            report_filename_pattern="{strategy}__{run_id}__{as_of_round}__{report_type}.md",
            initial_equity=Decimal("100"),
            notional_pct=Decimal("0.01"),
            fee_bps=Decimal("4"),
            slippage_bps=Decimal("4"),
            decision_buffer_seconds=30,
            market_state_staleness_sec=120,
            orderbook_staleness_sec=15,
            strict_liquidation=True,
        )
        as_of_round = datetime(2026, 3, 31, 8, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmpdir:
            writer = MarkdownReportWriter(
                output_dir=Path(tmpdir),
                filename_pattern=run.report_filename_pattern,
            )
            path = writer.report_path(run=run, as_of_round=as_of_round, report_type="summary")

        self.assertEqual(
            path.name,
            "hybrid_aggressive_safe_valid__paper-20260331-000000__20260331T080000Z__summary.md",
        )

