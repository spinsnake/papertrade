from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch
import unittest

from papertrade.cli import main


class CLITests(unittest.TestCase):
    def _write_platform_db(self, path: Path, pairs: tuple[tuple[str, str], ...] = (("BTC", "USDT"),)) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                CREATE TABLE instruments (
                    exchange TEXT NOT NULL,
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    margin_asset TEXT NOT NULL,
                    contract_multiplier TEXT NOT NULL,
                    tick_size TEXT NOT NULL,
                    lot_size TEXT NOT NULL,
                    min_qty TEXT NOT NULL,
                    max_qty TEXT NOT NULL,
                    min_notional TEXT NOT NULL,
                    max_leverage INTEGER NOT NULL,
                    funding_interval INTEGER NOT NULL,
                    launch_time TEXT NOT NULL
                );
                CREATE TABLE funding (
                    time TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    funding_rate TEXT NOT NULL
                );
                CREATE TABLE open_interest (
                    time TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    open_interest TEXT NOT NULL
                );
                """
            )
            instrument_rows = []
            funding_rows = []
            open_interest_rows = []
            by_pair_rates = {
                ("BTC", "USDT"): ("0.0005", "0.0002", "0.0004", "0.0001", "0.0003", "0.0001"),
                ("ETH", "USDT"): ("0.0007", "0.0003", "0.0006", "0.0002", "0.0005", "0.0002"),
            }
            by_pair_open_interest = {
                ("BTC", "USDT"): ("100", "90"),
                ("ETH", "USDT"): ("80", "70"),
            }
            for base, quote in pairs:
                instrument_rows.extend(
                    [
                        ("bybit", base, quote, "USDT", "1", "0.1", "0.001", "0.001", "100", "10", 50, 8, "2024-01-01T00:00:00+00:00"),
                        ("bitget", base, quote, "USDT", "1", "0.1", "0.001", "0.001", "100", "10", 50, 8, "2024-01-01T00:00:00+00:00"),
                    ]
                )
                rates = by_pair_rates.get((base, quote), by_pair_rates[("BTC", "USDT")])
                funding_rows.extend(
                    [
                        ("2025-01-11T00:00:00+00:00", "bybit", base, quote, rates[0]),
                        ("2025-01-11T00:00:00+00:00", "bitget", base, quote, rates[1]),
                        ("2025-01-10T16:00:00+00:00", "bybit", base, quote, rates[2]),
                        ("2025-01-10T16:00:00+00:00", "bitget", base, quote, rates[3]),
                        ("2025-01-10T08:00:00+00:00", "bybit", base, quote, rates[4]),
                        ("2025-01-10T08:00:00+00:00", "bitget", base, quote, rates[5]),
                    ]
                )
                open_interest_values = by_pair_open_interest.get((base, quote), by_pair_open_interest[("BTC", "USDT")])
                open_interest_rows.extend(
                    [
                        ("2025-01-11T00:00:00+00:00", "bybit", base, quote, open_interest_values[0]),
                        ("2025-01-11T00:00:00+00:00", "bitget", base, quote, open_interest_values[1]),
                    ]
                )
            connection.executemany(
                """
                INSERT INTO instruments (
                    exchange, base, quote, margin_asset, contract_multiplier, tick_size,
                    lot_size, min_qty, max_qty, min_notional, max_leverage, funding_interval, launch_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                instrument_rows,
            )
            connection.executemany(
                "INSERT INTO funding (time, exchange, base, quote, funding_rate) VALUES (?, ?, ?, ?, ?)",
                funding_rows,
            )
            connection.executemany(
                "INSERT INTO open_interest (time, exchange, base, quote, open_interest) VALUES (?, ?, ?, ?, ?)",
                open_interest_rows,
            )
            connection.commit()
        finally:
            connection.close()

    def test_main_run_forward_returns_blocked_exit_code(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            exit_code = main(["run-forward"])
        self.assertEqual(exit_code, 2)

    def test_main_run_forward_executes_single_cycle_from_input_file(self) -> None:
        risky_payload = {
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
        safe_payload = {
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
        fixture_payload = {
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

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            risky_path = base_dir / "risky.json"
            safe_path = base_dir / "safe.json"
            fixture_path = base_dir / "fixture.json"
            report_dir = base_dir / "reports"
            risky_path.write_text(json.dumps(risky_payload), encoding="utf-8")
            safe_path.write_text(json.dumps(safe_payload), encoding="utf-8")
            fixture_path.write_text(json.dumps(fixture_payload), encoding="utf-8")

            stdout = io.StringIO()
            with patch.dict(
                "os.environ",
                {
                    "PAPERTRADE_RISKY_ARTIFACT_PATH": str(risky_path),
                    "PAPERTRADE_SAFE_ARTIFACT_PATH": str(safe_path),
                },
                clear=True,
            ):
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "run-forward",
                            "--input-file",
                            str(fixture_path),
                            "--report-dir",
                            str(report_dir),
                        ]
                    )

            output = stdout.getvalue()
            runs_dir_exists = (report_dir / "runs").exists()
            cycles_dir_exists = (report_dir / "cycles").exists()

        self.assertEqual(exit_code, 0)
        self.assertIn("run finished:", output)
        self.assertTrue(runs_dir_exists)
        self.assertTrue(cycles_dir_exists)

    def test_main_run_forward_executes_single_cycle_from_real_source_files(self) -> None:
        risky_payload = {
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
        safe_payload = {
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

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            risky_path = base_dir / "risky.json"
            safe_path = base_dir / "safe.json"
            db_path = base_dir / "platform.sqlite3"
            market_states_path = base_dir / "market_states.json"
            orderbooks_path = base_dir / "orderbooks.json"
            liquidations_path = base_dir / "liquidations.json"
            report_dir = base_dir / "reports"
            risky_path.write_text(json.dumps(risky_payload), encoding="utf-8")
            safe_path.write_text(json.dumps(safe_payload), encoding="utf-8")
            self._write_platform_db(db_path)
            market_states_path.write_text(
                json.dumps(
                    [
                        {
                            "exchange": "bybit",
                            "base": "BTC",
                            "quote": "USDT",
                            "index_price": "100",
                            "mark_price": "101",
                            "funding_rate": "0.0005",
                            "open_interest": "100",
                            "updated_at": "2025-01-11T07:59:20+00:00",
                        },
                        {
                            "exchange": "bitget",
                            "base": "BTC",
                            "quote": "USDT",
                            "index_price": "100",
                            "mark_price": "100.5",
                            "funding_rate": "0.0002",
                            "open_interest": "90",
                            "updated_at": "2025-01-11T07:59:20+00:00",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            orderbooks_path.write_text(
                json.dumps(
                    [
                        {
                            "exchange": "bybit",
                            "base": "BTC",
                            "quote": "USDT",
                            "bids": [{"price": "100", "size": "3"}],
                            "asks": [{"price": "101", "size": "1"}],
                            "updated_at": "2025-01-11T07:59:25+00:00",
                        },
                        {
                            "exchange": "bitget",
                            "base": "BTC",
                            "quote": "USDT",
                            "bids": [{"price": "100", "size": "1"}],
                            "asks": [{"price": "101", "size": "1"}],
                            "updated_at": "2025-01-11T07:59:25+00:00",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            liquidations_path.write_text("[]", encoding="utf-8")

            stdout = io.StringIO()
            with patch.dict(
                "os.environ",
                {
                    "PAPERTRADE_RISKY_ARTIFACT_PATH": str(risky_path),
                    "PAPERTRADE_SAFE_ARTIFACT_PATH": str(safe_path),
                    "PAPERTRADE_PLATFORM_DB_PATH": str(db_path),
                    "PAPERTRADE_MARKET_STATE_SNAPSHOT_PATH": str(market_states_path),
                    "PAPERTRADE_ORDERBOOK_SNAPSHOT_PATH": str(orderbooks_path),
                    "PAPERTRADE_LIQUIDATION_EVENTS_PATH": str(liquidations_path),
                },
                clear=True,
            ):
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "run-forward",
                            "--pair",
                            "BTC/USDT",
                            "--now-utc",
                            "2025-01-11T07:59:00+00:00",
                            "--report-dir",
                            str(report_dir),
                        ]
                    )

            output = stdout.getvalue()
            runs_dir_exists = (report_dir / "runs").exists()
            cycles_dir_exists = (report_dir / "cycles").exists()

        self.assertEqual(exit_code, 0)
        self.assertIn("run finished:", output)
        self.assertTrue(runs_dir_exists)
        self.assertTrue(cycles_dir_exists)

    def test_main_run_forward_executes_continuous_real_source_mode(self) -> None:
        risky_payload = {
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
        safe_payload = {
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

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            risky_path = base_dir / "risky.json"
            safe_path = base_dir / "safe.json"
            db_path = base_dir / "platform.sqlite3"
            market_states_path = base_dir / "market_states.json"
            orderbooks_path = base_dir / "orderbooks.json"
            liquidations_path = base_dir / "liquidations.json"
            report_dir = base_dir / "reports"
            risky_path.write_text(json.dumps(risky_payload), encoding="utf-8")
            safe_path.write_text(json.dumps(safe_payload), encoding="utf-8")
            self._write_platform_db(db_path)
            market_states_path.write_text(
                json.dumps(
                    [
                        {
                            "exchange": "bybit",
                            "base": "BTC",
                            "quote": "USDT",
                            "index_price": "100",
                            "mark_price": "101",
                            "funding_rate": "0.0005",
                            "open_interest": "100",
                            "updated_at": "2025-01-11T07:59:20+00:00",
                        },
                        {
                            "exchange": "bitget",
                            "base": "BTC",
                            "quote": "USDT",
                            "index_price": "100",
                            "mark_price": "100.5",
                            "funding_rate": "0.0002",
                            "open_interest": "90",
                            "updated_at": "2025-01-11T07:59:20+00:00",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            orderbooks_path.write_text(
                json.dumps(
                    [
                        {
                            "exchange": "bybit",
                            "base": "BTC",
                            "quote": "USDT",
                            "bids": [{"price": "100", "size": "3"}],
                            "asks": [{"price": "101", "size": "1"}],
                            "updated_at": "2025-01-11T07:59:25+00:00",
                        },
                        {
                            "exchange": "bitget",
                            "base": "BTC",
                            "quote": "USDT",
                            "bids": [{"price": "100", "size": "1"}],
                            "asks": [{"price": "101", "size": "1"}],
                            "updated_at": "2025-01-11T07:59:25+00:00",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            liquidations_path.write_text("[]", encoding="utf-8")

            stdout = io.StringIO()
            with patch.dict(
                "os.environ",
                {
                    "PAPERTRADE_RISKY_ARTIFACT_PATH": str(risky_path),
                    "PAPERTRADE_SAFE_ARTIFACT_PATH": str(safe_path),
                    "PAPERTRADE_PLATFORM_DB_PATH": str(db_path),
                    "PAPERTRADE_MARKET_STATE_SNAPSHOT_PATH": str(market_states_path),
                    "PAPERTRADE_ORDERBOOK_SNAPSHOT_PATH": str(orderbooks_path),
                    "PAPERTRADE_LIQUIDATION_EVENTS_PATH": str(liquidations_path),
                },
                clear=True,
            ):
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "run-forward",
                            "--pair",
                            "BTC/USDT",
                            "--continuous",
                            "--max-cycles",
                            "1",
                            "--now-utc",
                            "2025-01-11T07:59:00+00:00",
                            "--report-dir",
                            str(report_dir),
                        ]
                    )

            output = stdout.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertIn("completed_cycles: 1", output)

    def test_main_run_forward_executes_continuous_multi_pair_mode(self) -> None:
        risky_payload = {
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
        safe_payload = {
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

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            risky_path = base_dir / "risky.json"
            safe_path = base_dir / "safe.json"
            db_path = base_dir / "platform.sqlite3"
            market_states_path = base_dir / "market_states.json"
            orderbooks_path = base_dir / "orderbooks.json"
            liquidations_path = base_dir / "liquidations.json"
            report_dir = base_dir / "reports"
            risky_path.write_text(json.dumps(risky_payload), encoding="utf-8")
            safe_path.write_text(json.dumps(safe_payload), encoding="utf-8")
            self._write_platform_db(db_path, pairs=(("BTC", "USDT"), ("ETH", "USDT")))
            market_states_path.write_text(
                json.dumps(
                    [
                        {
                            "exchange": "bybit",
                            "base": "BTC",
                            "quote": "USDT",
                            "index_price": "100",
                            "mark_price": "101",
                            "funding_rate": "0.0005",
                            "open_interest": "100",
                            "updated_at": "2025-01-11T07:59:20+00:00",
                        },
                        {
                            "exchange": "bitget",
                            "base": "BTC",
                            "quote": "USDT",
                            "index_price": "100",
                            "mark_price": "100.5",
                            "funding_rate": "0.0002",
                            "open_interest": "90",
                            "updated_at": "2025-01-11T07:59:20+00:00",
                        },
                        {
                            "exchange": "bybit",
                            "base": "ETH",
                            "quote": "USDT",
                            "index_price": "50",
                            "mark_price": "50.5",
                            "funding_rate": "0.0007",
                            "open_interest": "80",
                            "updated_at": "2025-01-11T07:59:20+00:00",
                        },
                        {
                            "exchange": "bitget",
                            "base": "ETH",
                            "quote": "USDT",
                            "index_price": "50",
                            "mark_price": "50.2",
                            "funding_rate": "0.0003",
                            "open_interest": "70",
                            "updated_at": "2025-01-11T07:59:20+00:00",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            orderbooks_path.write_text(
                json.dumps(
                    [
                        {
                            "exchange": "bybit",
                            "base": "BTC",
                            "quote": "USDT",
                            "bids": [{"price": "100", "size": "3"}],
                            "asks": [{"price": "101", "size": "1"}],
                            "updated_at": "2025-01-11T07:59:25+00:00",
                        },
                        {
                            "exchange": "bitget",
                            "base": "BTC",
                            "quote": "USDT",
                            "bids": [{"price": "100", "size": "1"}],
                            "asks": [{"price": "101", "size": "1"}],
                            "updated_at": "2025-01-11T07:59:25+00:00",
                        },
                        {
                            "exchange": "bybit",
                            "base": "ETH",
                            "quote": "USDT",
                            "bids": [{"price": "50", "size": "4"}],
                            "asks": [{"price": "51", "size": "1"}],
                            "updated_at": "2025-01-11T07:59:25+00:00",
                        },
                        {
                            "exchange": "bitget",
                            "base": "ETH",
                            "quote": "USDT",
                            "bids": [{"price": "50", "size": "1"}],
                            "asks": [{"price": "51", "size": "1"}],
                            "updated_at": "2025-01-11T07:59:25+00:00",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            liquidations_path.write_text("[]", encoding="utf-8")

            stdout = io.StringIO()
            with patch.dict(
                "os.environ",
                {
                    "PAPERTRADE_RISKY_ARTIFACT_PATH": str(risky_path),
                    "PAPERTRADE_SAFE_ARTIFACT_PATH": str(safe_path),
                    "PAPERTRADE_PLATFORM_DB_PATH": str(db_path),
                    "PAPERTRADE_MARKET_STATE_SNAPSHOT_PATH": str(market_states_path),
                    "PAPERTRADE_ORDERBOOK_SNAPSHOT_PATH": str(orderbooks_path),
                    "PAPERTRADE_LIQUIDATION_EVENTS_PATH": str(liquidations_path),
                },
                clear=True,
            ):
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "run-forward",
                            "--continuous",
                            "--max-cycles",
                            "1",
                            "--poll-seconds",
                            "0",
                            "--now-utc",
                            "2025-01-11T07:59:00+00:00",
                            "--report-dir",
                            str(report_dir),
                        ]
                    )

            output = stdout.getvalue()
            cycle_files = list((report_dir / "cycles").glob("*.json"))

        self.assertEqual(exit_code, 0)
        self.assertIn("completed_cycles: 1", output)
        self.assertIn("processed_pairs: 2", output)
        self.assertEqual(len(cycle_files), 2)
