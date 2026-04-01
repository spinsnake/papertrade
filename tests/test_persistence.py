from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from papertrade.contracts import PaperRun, PaperTrade, Pair
from papertrade.persistence import CsvTradeLogWriter, JsonArtifactStore, RunArtifactWriter
from papertrade.report import MarkdownReportWriter


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


def make_trade() -> PaperTrade:
    pair = Pair("BTC", "USDT")
    return PaperTrade(
        trade_id="trade-1",
        run_id="paper-test",
        position_id="position-1",
        strategy="hybrid_aggressive_safe_valid",
        pair=pair,
        short_exchange="bybit",
        long_exchange="bitget",
        entry_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
        exit_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
        entry_time=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
        exit_time=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
        rounds_held=3,
        entry_safe_score=Decimal("0.9"),
        entry_risky_score=Decimal("0.8"),
        notional=Decimal("1"),
        gross_bps=Decimal("8"),
        bybit_fee_bps=Decimal("2"),
        bitget_fee_bps=Decimal("2"),
        fee_bps=Decimal("4"),
        slippage_bps=Decimal("4"),
        net_bps=Decimal("0"),
        gross_pnl=Decimal("0.0008"),
        fee_pnl=Decimal("-0.0004"),
        slippage_pnl=Decimal("-0.0004"),
        net_pnl=Decimal("0"),
        equity_before=Decimal("100"),
        equity_after=Decimal("100"),
        close_reason="completed_three_rounds",
    )


class PersistenceTests(unittest.TestCase):
    def test_markdown_report_writer_writes_summary_file(self) -> None:
        run = make_run()
        trade = make_trade()
        as_of_round = datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmpdir:
            writer = MarkdownReportWriter(
                output_dir=Path(tmpdir),
                filename_pattern=run.report_filename_pattern,
            )
            path = writer.write_summary(
                run=run,
                as_of_round=as_of_round,
                open_positions=0,
                closed_trades=[trade],
            )

            content = path.read_text(encoding="utf-8")
            path_exists = path.exists()

        self.assertTrue(path_exists)
        self.assertIn("# Forward Paper Trade", content)
        self.assertIn("closed_trades: `1`", content)

    def test_json_artifact_store_serializes_run_metadata(self) -> None:
        run = make_run()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonArtifactStore(Path(tmpdir))
            path = store.write_json("runs/paper-test.json", run)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["run_id"], "paper-test")
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["initial_equity"], "100")

    def test_csv_trade_log_writer_writes_trade_rows(self) -> None:
        trade = make_trade()
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = CsvTradeLogWriter(Path(tmpdir))
            path = writer.write_trades("trades/paper-test.csv", [trade])
            content = path.read_text(encoding="utf-8")

        self.assertIn("trade_id,run_id,position_id", content)
        self.assertIn("bybit_fee_bps,bitget_fee_bps,fee_bps", content)
        self.assertIn("trade-1", content)
        self.assertIn("BTCUSDT", content)

    def test_run_artifact_writer_writes_summary_metadata_and_trade_log(self) -> None:
        run = make_run()
        trade = make_trade()
        as_of_round = datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            artifact_writer = RunArtifactWriter(
                report_writer=MarkdownReportWriter(
                    output_dir=base_dir / "reports",
                    filename_pattern=run.report_filename_pattern,
                ),
                json_store=JsonArtifactStore(base_dir),
                trade_log_writer=CsvTradeLogWriter(base_dir),
            )
            paths = artifact_writer.write_outputs(
                run=run,
                as_of_round=as_of_round,
                open_positions=0,
                closed_trades=[trade],
            )

            summary_content = paths.summary_path.read_text(encoding="utf-8")
            metadata = json.loads(paths.run_metadata_path.read_text(encoding="utf-8"))
            trade_log_content = paths.trade_log_path.read_text(encoding="utf-8")
            summary_exists = paths.summary_path.exists()
            metadata_exists = paths.run_metadata_path.exists()
            trade_log_exists = paths.trade_log_path.exists()

        self.assertTrue(summary_exists)
        self.assertTrue(metadata_exists)
        self.assertTrue(trade_log_exists)
        self.assertIn("paper-test", summary_content)
        self.assertEqual(metadata["status"], "running")
        self.assertIn("trade-1", trade_log_content)
