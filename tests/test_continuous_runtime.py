from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from papertrade.config import Settings
from papertrade.continuous_runtime import ContinuousForwardRunner, build_simulated_now_provider
from papertrade.contracts import PaperRun, Pair
from papertrade.single_cycle_runtime import load_single_cycle_fixture
from papertrade.state_store import SQLiteStateStore


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


def make_fixture_payload(
    *,
    pair: Pair | None = None,
    now_utc: str,
    bybit_rate: str,
    bitget_rate: str,
    bybit_updated_at: str,
    bitget_updated_at: str,
    bybit_orderbook_updated_at: str,
    bitget_orderbook_updated_at: str,
    funding_history: list[dict[str, str]],
) -> dict[str, object]:
    resolved_pair = pair or Pair("BTC", "USDT")
    return {
        "now_utc": now_utc,
        "pair": {
            "base": resolved_pair.base,
            "quote": resolved_pair.quote,
        },
        "market_states": {
            "bybit": {
                "index_price": "100",
                "mark_price": "101",
                "funding_rate": bybit_rate,
                "open_interest": "100",
                "updated_at": bybit_updated_at,
            },
            "bitget": {
                "index_price": "100",
                "mark_price": "100.5",
                "funding_rate": bitget_rate,
                "open_interest": "90",
                "updated_at": bitget_updated_at,
            },
        },
        "orderbooks": {
            "bybit": {
                "bids": [{"price": "100", "size": "3"}],
                "asks": [{"price": "101", "size": "1"}],
                "updated_at": bybit_orderbook_updated_at,
            },
            "bitget": {
                "bids": [{"price": "100", "size": "1"}],
                "asks": [{"price": "101", "size": "1"}],
                "updated_at": bitget_orderbook_updated_at,
            },
        },
        "funding_history": funding_history,
        "liquidation_events": [],
    }


def make_run(settings: Settings) -> PaperRun:
    return PaperRun.new(
        run_id="paper-continuous-test",
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


class ContinuousRuntimeTests(unittest.TestCase):
    def test_continuous_runner_opens_settles_and_closes_over_three_rounds(self) -> None:
        risky_payload, safe_payload = make_artifact_payloads()
        pair = Pair("BTC", "USDT")
        cycle_times = (
            datetime(2025, 1, 11, 7, 59, 0, tzinfo=timezone.utc),
            datetime(2025, 1, 11, 15, 59, 0, tzinfo=timezone.utc),
            datetime(2025, 1, 11, 23, 59, 0, tzinfo=timezone.utc),
        )

        cycle_payloads = {
            cycle_times[0]: make_fixture_payload(
                now_utc="2025-01-11T07:59:00+00:00",
                bybit_rate="0.0005",
                bitget_rate="0.0002",
                bybit_updated_at="2025-01-11T07:59:20+00:00",
                bitget_updated_at="2025-01-11T07:59:20+00:00",
                bybit_orderbook_updated_at="2025-01-11T07:59:25+00:00",
                bitget_orderbook_updated_at="2025-01-11T07:59:25+00:00",
                funding_history=[
                    {"exchange": "bybit", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0005"},
                    {"exchange": "bitget", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0002"},
                    {"exchange": "bybit", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0004"},
                    {"exchange": "bitget", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0001"},
                    {"exchange": "bybit", "time": "2025-01-10T08:00:00+00:00", "funding_rate": "0.0003"},
                    {"exchange": "bitget", "time": "2025-01-10T08:00:00+00:00", "funding_rate": "0.0001"},
                ],
            ),
            cycle_times[1]: make_fixture_payload(
                now_utc="2025-01-11T15:59:00+00:00",
                bybit_rate="0.0004",
                bitget_rate="0.0001",
                bybit_updated_at="2025-01-11T15:59:20+00:00",
                bitget_updated_at="2025-01-11T15:59:20+00:00",
                bybit_orderbook_updated_at="2025-01-11T15:59:25+00:00",
                bitget_orderbook_updated_at="2025-01-11T15:59:25+00:00",
                funding_history=[
                    {"exchange": "bybit", "time": "2025-01-11T08:00:00+00:00", "funding_rate": "0.0005"},
                    {"exchange": "bitget", "time": "2025-01-11T08:00:00+00:00", "funding_rate": "0.0002"},
                    {"exchange": "bybit", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0005"},
                    {"exchange": "bitget", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0002"},
                    {"exchange": "bybit", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0004"},
                    {"exchange": "bitget", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0001"},
                ],
            ),
            cycle_times[2]: make_fixture_payload(
                now_utc="2025-01-11T23:59:00+00:00",
                bybit_rate="0.0006",
                bitget_rate="0.0001",
                bybit_updated_at="2025-01-11T23:59:20+00:00",
                bitget_updated_at="2025-01-11T23:59:20+00:00",
                bybit_orderbook_updated_at="2025-01-11T23:59:25+00:00",
                bitget_orderbook_updated_at="2025-01-11T23:59:25+00:00",
                funding_history=[
                    {"exchange": "bybit", "time": "2025-01-11T16:00:00+00:00", "funding_rate": "0.0004"},
                    {"exchange": "bitget", "time": "2025-01-11T16:00:00+00:00", "funding_rate": "0.0001"},
                    {"exchange": "bybit", "time": "2025-01-11T08:00:00+00:00", "funding_rate": "0.0005"},
                    {"exchange": "bitget", "time": "2025-01-11T08:00:00+00:00", "funding_rate": "0.0002"},
                    {"exchange": "bybit", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0005"},
                    {"exchange": "bitget", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0002"},
                ],
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            risky_path = base_dir / "risky.json"
            safe_path = base_dir / "safe.json"
            risky_path.write_text(json.dumps(risky_payload), encoding="utf-8")
            safe_path.write_text(json.dumps(safe_payload), encoding="utf-8")

            bundle_by_time = {}
            for now_value, payload in cycle_payloads.items():
                fixture_path = base_dir / f"{now_value.strftime('%Y%m%dT%H%M%S')}.json"
                fixture_path.write_text(json.dumps(payload), encoding="utf-8")
                bundle_by_time[now_value] = load_single_cycle_fixture(fixture_path)

            settings = Settings(
                report_output_dir=base_dir / "reports",
                risky_artifact_path=risky_path,
                safe_artifact_path=safe_path,
            )
            run = make_run(settings)
            runner = ContinuousForwardRunner(
                settings=settings,
                run=run,
                pair=pair,
                source_loader=lambda now_utc: bundle_by_time[now_utc],
            )

            completed_cycles = runner.run_loop(
                max_cycles=3,
                poll_seconds=8 * 60 * 60,
                now_provider=build_simulated_now_provider(
                    start_utc=cycle_times[0],
                    step_seconds=8 * 60 * 60,
                ),
                sleep_fn=lambda _: None,
            )

        self.assertEqual(completed_cycles, 3)
        self.assertEqual(run.status.value, "finished")
        self.assertEqual(len(runner.portfolio.trades), 1)
        self.assertEqual(runner.portfolio.trades[0].entry_round, datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(runner.portfolio.trades[0].exit_round, datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(runner.last_result.cycle_result.decision.reason_code, "position_already_open")
        open_positions = [position for position in runner.portfolio.positions.values() if position.state.value == "open"]
        self.assertEqual(open_positions, [])

    def test_process_cycle_skips_duplicate_funding_round(self) -> None:
        risky_payload, safe_payload = make_artifact_payloads()
        pair = Pair("BTC", "USDT")
        now_utc = datetime(2025, 1, 11, 7, 59, 0, tzinfo=timezone.utc)
        payload = make_fixture_payload(
            now_utc="2025-01-11T07:59:00+00:00",
            bybit_rate="0.0005",
            bitget_rate="0.0002",
            bybit_updated_at="2025-01-11T07:59:20+00:00",
            bitget_updated_at="2025-01-11T07:59:20+00:00",
            bybit_orderbook_updated_at="2025-01-11T07:59:25+00:00",
            bitget_orderbook_updated_at="2025-01-11T07:59:25+00:00",
            funding_history=[
                {"exchange": "bybit", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0005"},
                {"exchange": "bitget", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0002"},
                {"exchange": "bybit", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0004"},
                {"exchange": "bitget", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0001"},
                {"exchange": "bybit", "time": "2025-01-10T08:00:00+00:00", "funding_rate": "0.0003"},
                {"exchange": "bitget", "time": "2025-01-10T08:00:00+00:00", "funding_rate": "0.0001"},
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            risky_path = base_dir / "risky.json"
            safe_path = base_dir / "safe.json"
            fixture_path = base_dir / "cycle.json"
            risky_path.write_text(json.dumps(risky_payload), encoding="utf-8")
            safe_path.write_text(json.dumps(safe_payload), encoding="utf-8")
            fixture_path.write_text(json.dumps(payload), encoding="utf-8")

            settings = Settings(
                report_output_dir=base_dir / "reports",
                risky_artifact_path=risky_path,
                safe_artifact_path=safe_path,
            )
            run = make_run(settings)
            source_bundle = load_single_cycle_fixture(fixture_path)
            runner = ContinuousForwardRunner(
                settings=settings,
                run=run,
                pair=pair,
                source_loader=lambda _: source_bundle,
            )

            first_result = runner.process_cycle(now_utc)
            duplicate_result = runner.process_cycle(now_utc)

        self.assertIsNotNone(first_result)
        self.assertIsNone(duplicate_result)

    def test_continuous_runner_processes_multiple_pairs_in_one_loop(self) -> None:
        risky_payload, safe_payload = make_artifact_payloads()
        btc_pair = Pair("BTC", "USDT")
        eth_pair = Pair("ETH", "USDT")
        cycle_times = (
            datetime(2025, 1, 11, 7, 59, 0, tzinfo=timezone.utc),
            datetime(2025, 1, 11, 15, 59, 0, tzinfo=timezone.utc),
            datetime(2025, 1, 11, 23, 59, 0, tzinfo=timezone.utc),
        )

        def _history(entries: list[tuple[str, str]]) -> list[dict[str, str]]:
            history: list[dict[str, str]] = []
            for time_value, bybit_rate, bitget_rate in entries:
                history.append({"exchange": "bybit", "time": time_value, "funding_rate": bybit_rate})
                history.append({"exchange": "bitget", "time": time_value, "funding_rate": bitget_rate})
            return history

        payloads_by_time = {
            cycle_times[0]: (
                make_fixture_payload(
                    pair=btc_pair,
                    now_utc="2025-01-11T07:59:00+00:00",
                    bybit_rate="0.0005",
                    bitget_rate="0.0002",
                    bybit_updated_at="2025-01-11T07:59:20+00:00",
                    bitget_updated_at="2025-01-11T07:59:20+00:00",
                    bybit_orderbook_updated_at="2025-01-11T07:59:25+00:00",
                    bitget_orderbook_updated_at="2025-01-11T07:59:25+00:00",
                    funding_history=_history(
                        [
                            ("2025-01-11T00:00:00+00:00", "0.0005", "0.0002"),
                            ("2025-01-10T16:00:00+00:00", "0.0004", "0.0001"),
                            ("2025-01-10T08:00:00+00:00", "0.0003", "0.0001"),
                        ]
                    ),
                ),
                make_fixture_payload(
                    pair=eth_pair,
                    now_utc="2025-01-11T07:59:00+00:00",
                    bybit_rate="0.0007",
                    bitget_rate="0.0003",
                    bybit_updated_at="2025-01-11T07:59:20+00:00",
                    bitget_updated_at="2025-01-11T07:59:20+00:00",
                    bybit_orderbook_updated_at="2025-01-11T07:59:25+00:00",
                    bitget_orderbook_updated_at="2025-01-11T07:59:25+00:00",
                    funding_history=_history(
                        [
                            ("2025-01-11T00:00:00+00:00", "0.0007", "0.0003"),
                            ("2025-01-10T16:00:00+00:00", "0.0006", "0.0002"),
                            ("2025-01-10T08:00:00+00:00", "0.0005", "0.0002"),
                        ]
                    ),
                ),
            ),
            cycle_times[1]: (
                make_fixture_payload(
                    pair=btc_pair,
                    now_utc="2025-01-11T15:59:00+00:00",
                    bybit_rate="0.0004",
                    bitget_rate="0.0001",
                    bybit_updated_at="2025-01-11T15:59:20+00:00",
                    bitget_updated_at="2025-01-11T15:59:20+00:00",
                    bybit_orderbook_updated_at="2025-01-11T15:59:25+00:00",
                    bitget_orderbook_updated_at="2025-01-11T15:59:25+00:00",
                    funding_history=_history(
                        [
                            ("2025-01-11T08:00:00+00:00", "0.0005", "0.0002"),
                            ("2025-01-11T00:00:00+00:00", "0.0005", "0.0002"),
                            ("2025-01-10T16:00:00+00:00", "0.0004", "0.0001"),
                        ]
                    ),
                ),
                make_fixture_payload(
                    pair=eth_pair,
                    now_utc="2025-01-11T15:59:00+00:00",
                    bybit_rate="0.0006",
                    bitget_rate="0.0002",
                    bybit_updated_at="2025-01-11T15:59:20+00:00",
                    bitget_updated_at="2025-01-11T15:59:20+00:00",
                    bybit_orderbook_updated_at="2025-01-11T15:59:25+00:00",
                    bitget_orderbook_updated_at="2025-01-11T15:59:25+00:00",
                    funding_history=_history(
                        [
                            ("2025-01-11T08:00:00+00:00", "0.0007", "0.0003"),
                            ("2025-01-11T00:00:00+00:00", "0.0007", "0.0003"),
                            ("2025-01-10T16:00:00+00:00", "0.0006", "0.0002"),
                        ]
                    ),
                ),
            ),
            cycle_times[2]: (
                make_fixture_payload(
                    pair=btc_pair,
                    now_utc="2025-01-11T23:59:00+00:00",
                    bybit_rate="0.0006",
                    bitget_rate="0.0001",
                    bybit_updated_at="2025-01-11T23:59:20+00:00",
                    bitget_updated_at="2025-01-11T23:59:20+00:00",
                    bybit_orderbook_updated_at="2025-01-11T23:59:25+00:00",
                    bitget_orderbook_updated_at="2025-01-11T23:59:25+00:00",
                    funding_history=_history(
                        [
                            ("2025-01-11T16:00:00+00:00", "0.0004", "0.0001"),
                            ("2025-01-11T08:00:00+00:00", "0.0005", "0.0002"),
                            ("2025-01-11T00:00:00+00:00", "0.0005", "0.0002"),
                        ]
                    ),
                ),
                make_fixture_payload(
                    pair=eth_pair,
                    now_utc="2025-01-11T23:59:00+00:00",
                    bybit_rate="0.0008",
                    bitget_rate="0.0002",
                    bybit_updated_at="2025-01-11T23:59:20+00:00",
                    bitget_updated_at="2025-01-11T23:59:20+00:00",
                    bybit_orderbook_updated_at="2025-01-11T23:59:25+00:00",
                    bitget_orderbook_updated_at="2025-01-11T23:59:25+00:00",
                    funding_history=_history(
                        [
                            ("2025-01-11T16:00:00+00:00", "0.0006", "0.0002"),
                            ("2025-01-11T08:00:00+00:00", "0.0007", "0.0003"),
                            ("2025-01-11T00:00:00+00:00", "0.0007", "0.0003"),
                        ]
                    ),
                ),
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            risky_path = base_dir / "risky.json"
            safe_path = base_dir / "safe.json"
            risky_path.write_text(json.dumps(risky_payload), encoding="utf-8")
            safe_path.write_text(json.dumps(safe_payload), encoding="utf-8")

            bundles_by_time = {}
            for now_value, payloads in payloads_by_time.items():
                cycle_bundles = []
                for index, payload in enumerate(payloads):
                    fixture_path = base_dir / f"{now_value.strftime('%Y%m%dT%H%M%S')}_{index}.json"
                    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
                    cycle_bundles.append(load_single_cycle_fixture(fixture_path))
                bundles_by_time[now_value] = tuple(cycle_bundles)

            settings = Settings(
                report_output_dir=base_dir / "reports",
                risky_artifact_path=risky_path,
                safe_artifact_path=safe_path,
            )
            run = make_run(settings)
            runner = ContinuousForwardRunner(
                settings=settings,
                run=run,
                source_loader=lambda now_utc: bundles_by_time[now_utc],
            )

            completed_cycles = runner.run_loop(
                max_cycles=3,
                poll_seconds=8 * 60 * 60,
                now_provider=build_simulated_now_provider(
                    start_utc=cycle_times[0],
                    step_seconds=8 * 60 * 60,
                ),
                sleep_fn=lambda _: None,
            )

        self.assertEqual(completed_cycles, 3)
        self.assertEqual(run.status.value, "finished")
        self.assertEqual(len(runner.portfolio.trades), 2)
        self.assertEqual(sorted(trade.pair.symbol for trade in runner.portfolio.trades), ["BTCUSDT", "ETHUSDT"])
        self.assertIsNotNone(runner.last_cycle_result)
        self.assertEqual(len(runner.last_cycle_result.results), 2)
        open_positions = [position for position in runner.portfolio.positions.values() if position.state.value == "open"]
        self.assertEqual(open_positions, [])

    def test_continuous_runner_recovers_open_positions_from_state_store(self) -> None:
        risky_payload, safe_payload = make_artifact_payloads()
        pair = Pair("BTC", "USDT")
        cycle_times = (
            datetime(2025, 1, 11, 7, 59, 0, tzinfo=timezone.utc),
            datetime(2025, 1, 11, 15, 59, 0, tzinfo=timezone.utc),
        )

        cycle_payloads = {
            cycle_times[0]: make_fixture_payload(
                now_utc="2025-01-11T07:59:00+00:00",
                bybit_rate="0.0005",
                bitget_rate="0.0002",
                bybit_updated_at="2025-01-11T07:59:20+00:00",
                bitget_updated_at="2025-01-11T07:59:20+00:00",
                bybit_orderbook_updated_at="2025-01-11T07:59:25+00:00",
                bitget_orderbook_updated_at="2025-01-11T07:59:25+00:00",
                funding_history=[
                    {"exchange": "bybit", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0005"},
                    {"exchange": "bitget", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0002"},
                    {"exchange": "bybit", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0004"},
                    {"exchange": "bitget", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0001"},
                    {"exchange": "bybit", "time": "2025-01-10T08:00:00+00:00", "funding_rate": "0.0003"},
                    {"exchange": "bitget", "time": "2025-01-10T08:00:00+00:00", "funding_rate": "0.0001"},
                ],
            ),
            cycle_times[1]: make_fixture_payload(
                now_utc="2025-01-11T15:59:00+00:00",
                bybit_rate="0.0004",
                bitget_rate="0.0001",
                bybit_updated_at="2025-01-11T15:59:20+00:00",
                bitget_updated_at="2025-01-11T15:59:20+00:00",
                bybit_orderbook_updated_at="2025-01-11T15:59:25+00:00",
                bitget_orderbook_updated_at="2025-01-11T15:59:25+00:00",
                funding_history=[
                    {"exchange": "bybit", "time": "2025-01-11T08:00:00+00:00", "funding_rate": "0.0005"},
                    {"exchange": "bitget", "time": "2025-01-11T08:00:00+00:00", "funding_rate": "0.0002"},
                    {"exchange": "bybit", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0005"},
                    {"exchange": "bitget", "time": "2025-01-11T00:00:00+00:00", "funding_rate": "0.0002"},
                    {"exchange": "bybit", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0004"},
                    {"exchange": "bitget", "time": "2025-01-10T16:00:00+00:00", "funding_rate": "0.0001"},
                ],
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            risky_path = base_dir / "risky.json"
            safe_path = base_dir / "safe.json"
            risky_path.write_text(json.dumps(risky_payload), encoding="utf-8")
            safe_path.write_text(json.dumps(safe_payload), encoding="utf-8")
            state_store = SQLiteStateStore(base_dir / "state.sqlite3")

            bundle_by_time = {}
            for now_value, payload in cycle_payloads.items():
                fixture_path = base_dir / f"{now_value.strftime('%Y%m%dT%H%M%S')}.json"
                fixture_path.write_text(json.dumps(payload), encoding="utf-8")
                bundle_by_time[now_value] = load_single_cycle_fixture(fixture_path)

            settings = Settings(
                report_output_dir=base_dir / "reports",
                risky_artifact_path=risky_path,
                safe_artifact_path=safe_path,
                state_db_path=base_dir / "state.sqlite3",
            )
            initial_run = make_run(settings)
            first_runner = ContinuousForwardRunner(
                settings=settings,
                run=initial_run,
                pair=pair,
                source_loader=lambda now_utc: bundle_by_time[now_utc],
                state_store=state_store,
            )

            first_result = first_runner.process_cycle(cycle_times[0])
            resumed_run = state_store.load_run(initial_run.run_id)
            assert resumed_run is not None
            resumed_runner = ContinuousForwardRunner(
                settings=settings,
                run=resumed_run,
                pair=pair,
                source_loader=lambda now_utc: bundle_by_time[now_utc],
                state_store=state_store,
            )
            second_result = resumed_runner.process_cycle(cycle_times[1])

        self.assertIsNotNone(first_result)
        self.assertIsNotNone(second_result)
        self.assertEqual(len(first_runner.portfolio.trades), 0)
        self.assertEqual(len(resumed_runner.portfolio.trades), 0)
        open_positions = [position for position in resumed_runner.portfolio.positions.values() if position.state.value == "open"]
        self.assertEqual(len(open_positions), 1)
        self.assertEqual(open_positions[0].rounds_collected, 2)
        self.assertEqual(len(open_positions[0].rounds), 2)
