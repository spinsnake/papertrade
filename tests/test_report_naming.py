from __future__ import annotations

from datetime import datetime, timezone
import unittest

from papertrade.report import format_as_of_round, render_report_filename


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
