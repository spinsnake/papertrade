from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest

from papertrade.contracts import EntryDecision, PaperRun, Pair
from papertrade.portfolio import PortfolioSimulator
from papertrade.state_store import SQLiteStateStore


def make_run(report_dir: Path) -> PaperRun:
    return PaperRun.new(
        run_id="paper-state-store",
        strategy="hybrid_aggressive_safe_valid",
        runtime_mode="forward_market_listener",
        report_output_dir=str(report_dir),
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


class SQLiteStateStoreTests(unittest.TestCase):
    def test_state_store_round_trips_run_positions_and_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            store = SQLiteStateStore(base_dir / "state.sqlite3")
            run = make_run(base_dir / "reports")
            portfolio = PortfolioSimulator(run=run)
            pair = Pair("BTC", "USDT")
            position = portfolio.open_position(
                decision=EntryDecision(
                    funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
                    pair=pair,
                    selected=True,
                    reason_code="selected",
                    short_exchange="bybit",
                    long_exchange="bitget",
                    safe_score=Decimal("0.8"),
                    risky_score=Decimal("0.7"),
                    signed_spread_bps=Decimal("10"),
                ),
                entry_time=datetime(2025, 1, 11, 7, 59, tzinfo=timezone.utc),
                planned_exit_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
            )
            portfolio.settle_round(
                position_id=position.position_id,
                funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
                bybit_funding_rate_bps=Decimal("5"),
                bitget_funding_rate_bps=Decimal("2"),
            )
            portfolio.settle_round(
                position_id=position.position_id,
                funding_round=datetime(2025, 1, 11, 16, 0, tzinfo=timezone.utc),
                bybit_funding_rate_bps=Decimal("4"),
                bitget_funding_rate_bps=Decimal("1"),
            )
            portfolio.settle_round(
                position_id=position.position_id,
                funding_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
                bybit_funding_rate_bps=Decimal("6"),
                bitget_funding_rate_bps=Decimal("1"),
            )
            run.mark_finished()

            store.save_run(run)
            store.replace_portfolio_state(
                run_id=run.run_id,
                positions=portfolio.positions.values(),
                trades=portfolio.trades,
            )

            loaded_run = store.load_run(run.run_id)
            loaded_positions = store.load_positions(run.run_id)
            loaded_trades = store.load_trades(run.run_id)

        self.assertIsNotNone(loaded_run)
        self.assertEqual(loaded_run.status.value, "finished")
        self.assertEqual(loaded_run.bybit_taker_fee_bps, Decimal("1"))
        self.assertEqual(loaded_run.bitget_taker_fee_bps, Decimal("1"))
        self.assertEqual(len(loaded_positions), 1)
        self.assertEqual(loaded_positions[0].state.value, "closed")
        self.assertEqual(loaded_positions[0].close_reason, "completed_three_rounds")
        self.assertEqual(len(loaded_positions[0].rounds), 3)
        self.assertEqual(len(loaded_trades), 1)
        self.assertEqual(loaded_trades[0].bybit_fee_bps, Decimal("2"))
        self.assertEqual(loaded_trades[0].bitget_fee_bps, Decimal("2"))
        self.assertEqual(loaded_trades[0].close_reason, "completed_three_rounds")

    def test_state_store_schema_requires_close_reason_for_closed_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.sqlite3"
            store = SQLiteStateStore(state_path)
            connection = sqlite3.connect(state_path)
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO paper_positions (
                            position_id, run_id, strategy, state, base, quote, symbol, short_exchange,
                            long_exchange, entry_round, planned_exit_round, actual_exit_round, entry_time,
                            exit_time, entry_safe_score, entry_risky_score, entry_signed_spread_bps,
                            entry_reason_code, notional, rounds_collected, gross_bps, fee_bps, slippage_bps,
                            net_bps, gross_pnl, fee_pnl, slippage_pnl, net_pnl, equity_before, equity_after,
                            close_reason
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "pos-1",
                            "run-1",
                            "hybrid_aggressive_safe_valid",
                            "closed",
                            "BTC",
                            "USDT",
                            "BTCUSDT",
                            "bybit",
                            "bitget",
                            "2025-01-11T08:00:00+00:00",
                            "2025-01-12T00:00:00+00:00",
                            "2025-01-12T00:00:00+00:00",
                            "2025-01-11T07:59:00+00:00",
                            "2025-01-12T00:00:00+00:00",
                            "0.8",
                            "0.7",
                            "10",
                            "selected",
                            "1",
                            3,
                            "12",
                            "4",
                            "4",
                            "4",
                            "0.0012",
                            "-0.0004",
                            "-0.0004",
                            "0.0004",
                            "100",
                            "100.0004",
                            None,
                        ),
                    )
            finally:
                connection.close()
