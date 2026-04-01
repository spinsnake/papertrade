from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from papertrade.config import Settings
from papertrade.contracts import PaperRun
from papertrade.single_cycle_runtime import execute_single_cycle, load_single_cycle_fixture


def make_artifact_payloads() -> tuple[dict[str, object], dict[str, object]]:
    risky_payload: dict[str, object] = {
        "name": "risky",
        "feature_order": [
            "current_abs_funding_spread_bps",
            "rolling3_mean_abs_funding_spread_bps",
            "lag1_current_abs_funding_spread_bps",
        ],
        "means": {
            "current_abs_funding_spread_bps": "0",
            "rolling3_mean_abs_funding_spread_bps": "0",
            "lag1_current_abs_funding_spread_bps": "0",
        },
        "stds": {
            "current_abs_funding_spread_bps": "1",
            "rolling3_mean_abs_funding_spread_bps": "1",
            "lag1_current_abs_funding_spread_bps": "1",
        },
        "weights": {
            "current_abs_funding_spread_bps": "1",
            "rolling3_mean_abs_funding_spread_bps": "1",
            "lag1_current_abs_funding_spread_bps": "1",
        },
        "bias": "0",
        "threshold": "0.5",
    }
    safe_payload: dict[str, object] = {
        "name": "safe",
        "feature_order": [
            "bybit_premium_bps",
            "premium_abs_gap_bps",
            "bitget_futures_premium_bps",
            "bybit_open_interest",
            "oi_gap",
            "oi_total",
            "book_imbalance_abs_gap",
            "bybit_liquidation_amount_8h",
        ],
        "means": {
            "bybit_premium_bps": "0",
            "premium_abs_gap_bps": "0",
            "bitget_futures_premium_bps": "0",
            "bybit_open_interest": "0",
            "oi_gap": "0",
            "oi_total": "0",
            "book_imbalance_abs_gap": "0",
            "bybit_liquidation_amount_8h": "0",
        },
        "stds": {
            "bybit_premium_bps": "1",
            "premium_abs_gap_bps": "1",
            "bitget_futures_premium_bps": "1",
            "bybit_open_interest": "100",
            "oi_gap": "10",
            "oi_total": "100",
            "book_imbalance_abs_gap": "1",
            "bybit_liquidation_amount_8h": "1",
        },
        "weights": {
            "bybit_premium_bps": "1",
            "premium_abs_gap_bps": "1",
            "bitget_futures_premium_bps": "1",
            "bybit_open_interest": "1",
            "oi_gap": "1",
            "oi_total": "1",
            "book_imbalance_abs_gap": "1",
            "bybit_liquidation_amount_8h": "1",
        },
        "bias": "0",
        "threshold": "0.5",
    }
    return risky_payload, safe_payload


def make_fixture_payload() -> dict[str, object]:
    return {
        "now_utc": "2025-01-11T07:59:00+00:00",
        "pair": {
            "base": "BTC",
            "quote": "USDT",
        },
        "market_states": {
            "bybit": {
                "index_price": "100",
                "mark_price": "101",
                "funding_rate": "0.0005",
                "open_interest": "100",
                "updated_at": "2025-01-11T07:59:20+00:00",
            },
            "bitget": {
                "index_price": "100",
                "mark_price": "100.5",
                "funding_rate": "0.0002",
                "open_interest": "90",
                "updated_at": "2025-01-11T07:59:20+00:00",
            },
        },
        "orderbooks": {
            "bybit": {
                "bids": [{"price": "100", "size": "3"}],
                "asks": [{"price": "101", "size": "1"}],
                "updated_at": "2025-01-11T07:59:25+00:00",
            },
            "bitget": {
                "bids": [{"price": "100", "size": "1"}],
                "asks": [{"price": "101", "size": "1"}],
                "updated_at": "2025-01-11T07:59:25+00:00",
            },
        },
        "funding_history": [
            {"exchange": "bybit", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0005"},
            {"exchange": "bitget", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0002"},
            {"exchange": "bybit", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0004"},
            {"exchange": "bitget", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0001"},
            {"exchange": "bybit", "time": "2025-01-10T08:00:00+00:00", "funding_rate": "0.0003"},
            {"exchange": "bitget", "time": "2025-01-10T08:00:00+00:00", "funding_rate": "0.0001"},
        ],
        "liquidation_events": [],
    }


def make_run(settings: Settings) -> PaperRun:
    return PaperRun.new(
        run_id="paper-runtime-test",
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


class SingleCycleRuntimeTests(unittest.TestCase):
    def test_execute_single_cycle_collects_evaluates_and_writes_outputs(self) -> None:
        risky_payload, safe_payload = make_artifact_payloads()
        fixture_payload = make_fixture_payload()

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            risky_path = base_dir / "risky.json"
            safe_path = base_dir / "safe.json"
            fixture_path = base_dir / "fixture.json"
            risky_path.write_text(json.dumps(risky_payload), encoding="utf-8")
            safe_path.write_text(json.dumps(safe_payload), encoding="utf-8")
            fixture_path.write_text(json.dumps(fixture_payload), encoding="utf-8")

            settings = Settings(
                report_output_dir=base_dir / "reports",
                risky_artifact_path=risky_path,
                safe_artifact_path=safe_path,
            )
            run = make_run(settings)
            fixture = load_single_cycle_fixture(fixture_path)

            result = execute_single_cycle(
                settings=settings,
                run=run,
                source_bundle=fixture,
            )

            summary_content = result.artifact_paths.summary_path.read_text(encoding="utf-8")
            metadata = json.loads(result.artifact_paths.run_metadata_path.read_text(encoding="utf-8"))
            cycle_payload = json.loads(result.cycle_artifact_path.read_text(encoding="utf-8"))

        self.assertEqual(run.status.value, "finished")
        self.assertTrue(result.cycle_result.decision.selected)
        self.assertIsNotNone(result.opened_position_id)
        self.assertIn("open_positions: `1`", summary_content)
        self.assertEqual(metadata["status"], "finished")
        self.assertEqual(cycle_payload["decision"]["reason_code"], "selected")
        self.assertEqual(
            cycle_payload["funding_decision"]["funding_round"],
            datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc).isoformat(),
        )
