from __future__ import annotations

from datetime import datetime, timezone
import unittest

from papertrade.scheduler import RoundScheduler


class SchedulerTests(unittest.TestCase):
    def test_round_scheduler_uses_utc_8h_boundaries(self) -> None:
        scheduler = RoundScheduler()
        decision = scheduler.next_decision(datetime(2025, 1, 11, 7, 0, tzinfo=timezone.utc))
        self.assertEqual(decision.funding_round, datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc))

    def test_decision_cutoff_is_thirty_seconds_before_round(self) -> None:
        scheduler = RoundScheduler()
        decision = scheduler.next_decision(datetime(2025, 1, 11, 7, 0, tzinfo=timezone.utc))
        self.assertEqual(decision.decision_cutoff, datetime(2025, 1, 11, 7, 59, 30, tzinfo=timezone.utc))

    def test_position_exit_round_inclusive_three_funding_rounds(self) -> None:
        scheduler = RoundScheduler()
        exit_round = scheduler.exit_round(datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(exit_round, datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc))
