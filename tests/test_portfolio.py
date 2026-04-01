from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from papertrade.contracts import EntryDecision, Pair, PaperPosition, PaperRun
from papertrade.enums import PositionState
from papertrade.portfolio import PortfolioSimulator
from papertrade.scheduler import RoundScheduler


def make_run() -> PaperRun:
    return PaperRun.new(
        run_id="paper-test",
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


def make_decision() -> EntryDecision:
    return EntryDecision(
        funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
        pair=Pair("BTC", "USDT"),
        selected=True,
        reason_code="selected",
        short_exchange="bybit",
        long_exchange="bitget",
        safe_score=Decimal("0.9"),
        risky_score=Decimal("0.9"),
        signed_spread_bps=Decimal("5"),
    )


class PortfolioTests(unittest.TestCase):
    def test_closed_position_requires_close_reason(self) -> None:
        with self.assertRaises(ValueError):
            PaperPosition(
                position_id="p1",
                run_id="run1",
                strategy="hybrid_aggressive_safe_valid",
                state=PositionState.CLOSED,
                pair=Pair("BTC", "USDT"),
                short_exchange="bybit",
                long_exchange="bitget",
                entry_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
                planned_exit_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
                actual_exit_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
                entry_time=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
                entry_safe_score=Decimal("0.9"),
                entry_risky_score=Decimal("0.9"),
                entry_signed_spread_bps=Decimal("5"),
                entry_reason_code="selected",
                notional=Decimal("1"),
            )

    def test_three_round_lifecycle_closes_position(self) -> None:
        simulator = PortfolioSimulator(run=make_run())
        scheduler = RoundScheduler()
        position = simulator.open_position(
            decision=make_decision(),
            entry_time=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            planned_exit_round=scheduler.exit_round(datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc)),
        )

        simulator.settle_round(
            position_id=position.position_id,
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            bybit_funding_rate_bps=Decimal("5"),
            bitget_funding_rate_bps=Decimal("2"),
        )
        simulator.settle_round(
            position_id=position.position_id,
            funding_round=datetime(2025, 1, 11, 16, 0, tzinfo=timezone.utc),
            bybit_funding_rate_bps=Decimal("4"),
            bitget_funding_rate_bps=Decimal("1"),
        )
        final_position = simulator.settle_round(
            position_id=position.position_id,
            funding_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
            bybit_funding_rate_bps=Decimal("3"),
            bitget_funding_rate_bps=Decimal("1"),
        )

        self.assertIs(final_position.state, PositionState.CLOSED)
        self.assertEqual(final_position.close_reason, "completed_three_rounds")
        self.assertEqual(len(simulator.trades), 1)

    def test_settlement_error_when_funding_missing_at_round2(self) -> None:
        simulator = PortfolioSimulator(run=make_run())
        position = simulator.open_position(
            decision=make_decision(),
            entry_time=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            planned_exit_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

        final_position = simulator.settle_round(
            position_id=position.position_id,
            funding_round=datetime(2025, 1, 11, 16, 0, tzinfo=timezone.utc),
            bybit_funding_rate_bps=None,
            bitget_funding_rate_bps=Decimal("1"),
        )
        self.assertIs(final_position.state, PositionState.SETTLEMENT_ERROR)
        self.assertEqual(final_position.close_reason, "settlement_error")
