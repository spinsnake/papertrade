from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from papertrade.trading_logic.contracts import EntryDecision, Pair, PaperPosition, PaperRun
from papertrade.trading_logic.enums import PositionState
from papertrade.trading_logic.portfolio import PortfolioSimulator
from papertrade.trading_logic.scheduler import RoundScheduler


def make_run(
    *,
    initial_equity: Decimal = Decimal("100"),
    notional_pct: Decimal = Decimal("0.01"),
    fee_bps: Decimal = Decimal("4"),
    bybit_taker_fee_bps: Decimal | None = None,
    bitget_taker_fee_bps: Decimal | None = None,
    slippage_bps: Decimal = Decimal("4"),
) -> PaperRun:
    return PaperRun.new(
        run_id="paper-test",
        strategy="hybrid_aggressive_safe_valid",
        runtime_mode="forward_market_listener",
        report_output_dir="reports",
        report_filename_pattern="{strategy}__{run_id}__{as_of_round}__{report_type}.md",
        initial_equity=initial_equity,
        notional_pct=notional_pct,
        slippage_bps=slippage_bps,
        decision_buffer_seconds=30,
        market_state_staleness_sec=120,
        orderbook_staleness_sec=15,
        strict_liquidation=True,
        fee_bps=fee_bps,
        bybit_taker_fee_bps=bybit_taker_fee_bps,
        bitget_taker_fee_bps=bitget_taker_fee_bps,
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
        self.assertEqual(simulator.trades[0].round1_gross_bps, Decimal("3"))
        self.assertEqual(simulator.trades[0].round2_gross_bps, Decimal("3"))
        self.assertEqual(simulator.trades[0].round3_gross_bps, Decimal("2"))
        self.assertEqual(simulator.trades[0].round1_gross_pnl, Decimal("0.0003"))
        self.assertEqual(simulator.trades[0].round2_gross_pnl, Decimal("0.0003"))
        self.assertEqual(simulator.trades[0].round3_gross_pnl, Decimal("0.0002"))

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

    def test_settlement_rejects_round_before_entry(self) -> None:
        simulator = PortfolioSimulator(run=make_run())
        position = simulator.open_position(
            decision=make_decision(),
            entry_time=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            planned_exit_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

        with self.assertRaisesRegex(ValueError, "funding_round must not be before entry_round"):
            simulator.settle_round(
                position_id=position.position_id,
                funding_round=datetime(2025, 1, 11, 0, 0, tzinfo=timezone.utc),
                bybit_funding_rate_bps=Decimal("5"),
                bitget_funding_rate_bps=Decimal("2"),
            )

    def test_settlement_rejects_non_increasing_rounds(self) -> None:
        simulator = PortfolioSimulator(run=make_run())
        position = simulator.open_position(
            decision=make_decision(),
            entry_time=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            planned_exit_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

        simulator.settle_round(
            position_id=position.position_id,
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            bybit_funding_rate_bps=Decimal("5"),
            bitget_funding_rate_bps=Decimal("2"),
        )

        with self.assertRaisesRegex(ValueError, "funding_round must be strictly increasing"):
            simulator.settle_round(
                position_id=position.position_id,
                funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
                bybit_funding_rate_bps=Decimal("4"),
                bitget_funding_rate_bps=Decimal("1"),
            )

    def test_settlement_rejects_round_after_planned_exit(self) -> None:
        simulator = PortfolioSimulator(run=make_run())
        position = simulator.open_position(
            decision=make_decision(),
            entry_time=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            planned_exit_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

        with self.assertRaisesRegex(ValueError, "funding_round must not be after planned_exit_round"):
            simulator.settle_round(
                position_id=position.position_id,
                funding_round=datetime(2025, 1, 12, 8, 0, tzinfo=timezone.utc),
                bybit_funding_rate_bps=Decimal("5"),
                bitget_funding_rate_bps=Decimal("2"),
            )

    def test_closing_loss_updates_max_drawdown_pct(self) -> None:
        simulator = PortfolioSimulator(
            run=make_run(
                notional_pct=Decimal("1"),
                fee_bps=Decimal("1000"),
                slippage_bps=Decimal("0"),
            )
        )
        scheduler = RoundScheduler()
        position = simulator.open_position(
            decision=make_decision(),
            entry_time=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            planned_exit_round=scheduler.exit_round(datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc)),
        )

        simulator.settle_round(
            position_id=position.position_id,
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            bybit_funding_rate_bps=Decimal("0"),
            bitget_funding_rate_bps=Decimal("0"),
        )
        simulator.settle_round(
            position_id=position.position_id,
            funding_round=datetime(2025, 1, 11, 16, 0, tzinfo=timezone.utc),
            bybit_funding_rate_bps=Decimal("0"),
            bitget_funding_rate_bps=Decimal("0"),
        )
        simulator.settle_round(
            position_id=position.position_id,
            funding_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
            bybit_funding_rate_bps=Decimal("0"),
            bitget_funding_rate_bps=Decimal("0"),
        )

        self.assertEqual(simulator.run.current_equity, Decimal("90"))
        self.assertEqual(simulator.run.peak_equity, Decimal("100"))
        self.assertEqual(simulator.run.max_drawdown_pct, Decimal("10"))

    def test_close_completed_accumulates_entry_and_exit_slippage_bps(self) -> None:
        simulator = PortfolioSimulator(run=make_run(slippage_bps=Decimal("4")))
        scheduler = RoundScheduler()
        position = simulator.open_position(
            decision=make_decision(),
            entry_time=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            planned_exit_round=scheduler.exit_round(datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc)),
            entry_slippage_bps=Decimal("2.5"),
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
            exit_slippage_bps=Decimal("1.5"),
        )

        self.assertEqual(final_position.slippage_bps, Decimal("4.0"))

    def test_close_completed_uses_exchange_specific_roundtrip_fee_bps(self) -> None:
        simulator = PortfolioSimulator(
            run=make_run(
                bybit_taker_fee_bps=Decimal("5.5"),
                bitget_taker_fee_bps=Decimal("6"),
                slippage_bps=Decimal("0"),
            )
        )
        scheduler = RoundScheduler()
        position = simulator.open_position(
            decision=make_decision(),
            entry_time=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            planned_exit_round=scheduler.exit_round(datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc)),
        )

        simulator.settle_round(
            position_id=position.position_id,
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            bybit_funding_rate_bps=Decimal("0"),
            bitget_funding_rate_bps=Decimal("0"),
        )
        simulator.settle_round(
            position_id=position.position_id,
            funding_round=datetime(2025, 1, 11, 16, 0, tzinfo=timezone.utc),
            bybit_funding_rate_bps=Decimal("0"),
            bitget_funding_rate_bps=Decimal("0"),
        )
        final_position = simulator.settle_round(
            position_id=position.position_id,
            funding_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
            bybit_funding_rate_bps=Decimal("0"),
            bitget_funding_rate_bps=Decimal("0"),
        )

        self.assertEqual(final_position.fee_bps, Decimal("23.0"))
        self.assertEqual(simulator.trades[0].bybit_fee_bps, Decimal("11.0"))
        self.assertEqual(simulator.trades[0].bitget_fee_bps, Decimal("12"))

