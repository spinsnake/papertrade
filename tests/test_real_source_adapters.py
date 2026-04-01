from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from papertrade.contracts import Pair
from papertrade.sources.liquidation import JsonFileLiquidationSource
from papertrade.sources.platform_bridge import FilePlatformBridge
from papertrade.sources.platform_db import SQLitePlatformDBSource


def make_sqlite_db(path: Path) -> None:
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
        connection.executemany(
            """
            INSERT INTO instruments (
                exchange,
                base,
                quote,
                margin_asset,
                contract_multiplier,
                tick_size,
                lot_size,
                min_qty,
                max_qty,
                min_notional,
                max_leverage,
                funding_interval,
                launch_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "bybit",
                    "BTC",
                    "USDT",
                    "USDT",
                    "1",
                    "0.1",
                    "0.001",
                    "0.001",
                    "100",
                    "10",
                    50,
                    8,
                    "2024-01-01T00:00:00+00:00",
                ),
                (
                    "bitget",
                    "BTC",
                    "USDT",
                    "USDT",
                    "1",
                    "0.1",
                    "0.001",
                    "0.001",
                    "100",
                    "10",
                    50,
                    8,
                    "2024-01-01T00:00:00+00:00",
                ),
            ],
        )
        connection.executemany(
            "INSERT INTO funding (time, exchange, base, quote, funding_rate) VALUES (?, ?, ?, ?, ?)",
            [
                ("2025-01-11T00:00:00+00:00", "bybit", "BTC", "USDT", "0.0005"),
                ("2025-01-11T00:00:00+00:00", "bitget", "BTC", "USDT", "0.0002"),
                ("2025-01-10T16:00:00+00:00", "bybit", "BTC", "USDT", "0.0004"),
                ("2025-01-10T16:00:00+00:00", "bitget", "BTC", "USDT", "0.0001"),
            ],
        )
        connection.executemany(
            "INSERT INTO open_interest (time, exchange, base, quote, open_interest) VALUES (?, ?, ?, ?, ?)",
            [
                ("2025-01-11T00:00:00+00:00", "bybit", "BTC", "USDT", "100"),
                ("2025-01-11T00:00:00+00:00", "bitget", "BTC", "USDT", "90"),
            ],
        )
        connection.commit()
    finally:
        connection.close()


class RealSourceAdapterTests(unittest.TestCase):
    def test_sqlite_platform_db_source_reads_instruments_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite3"
            make_sqlite_db(db_path)
            source = SQLitePlatformDBSource(db_path)
            pair = Pair("BTC", "USDT")

            pairs = source.list_pairs()
            funding_history = source.load_funding_history(pair, "bybit", 2)
            open_interest_history = source.load_open_interest_history(pair, "bitget", 1)

        self.assertEqual(pairs, (pair,))
        self.assertEqual(len(funding_history), 2)
        self.assertEqual(funding_history[0].funding_rate, Decimal("0.0005"))
        self.assertEqual(open_interest_history[0].open_interest, Decimal("90"))

    def test_file_platform_bridge_reads_latest_market_state_and_orderbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            market_state_path = base_dir / "market_states.json"
            orderbook_path = base_dir / "orderbooks.json"
            market_state_path.write_text(
                json.dumps(
                    [
                        {
                            "exchange": "bybit",
                            "base": "BTC",
                            "quote": "USDT",
                            "index_price": "99",
                            "mark_price": "100",
                            "funding_rate": "0.0001",
                            "open_interest": "80",
                            "updated_at": "2025-01-11T07:58:00+00:00",
                        },
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
                    ]
                ),
                encoding="utf-8",
            )
            orderbook_path.write_text(
                json.dumps(
                    [
                        {
                            "exchange": "bybit",
                            "base": "BTC",
                            "quote": "USDT",
                            "bids": [{"price": "100", "size": "3"}],
                            "asks": [{"price": "101", "size": "1"}],
                            "updated_at": "2025-01-11T07:59:25+00:00",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            bridge = FilePlatformBridge(market_state_path=market_state_path, orderbook_path=orderbook_path)

            market_state = bridge.get_market_state("bybit", Pair("BTC", "USDT"))
            orderbook = bridge.get_orderbook("bybit", Pair("BTC", "USDT"))

        assert market_state is not None
        assert orderbook is not None
        self.assertEqual(market_state.mark_price, Decimal("101"))
        self.assertEqual(orderbook.best_bid().size, Decimal("3"))

    def test_json_file_liquidation_source_sums_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            events_path = Path(tmpdir) / "liquidations.json"
            events_path.write_text(
                json.dumps(
                    [
                        {
                            "base": "BTC",
                            "quote": "USDT",
                            "time": "2025-01-11T00:00:00+00:00",
                            "usd_size": "10",
                        },
                        {
                            "base": "BTC",
                            "quote": "USDT",
                            "time": "2025-01-11T04:00:00+00:00",
                            "usd_size": "15",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            source = JsonFileLiquidationSource(events_path)
            total = source.sum_bybit_liquidation_usd(
                Pair("BTC", "USDT"),
                datetime(2025, 1, 11, 0, 0, tzinfo=timezone.utc),
                datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(total, Decimal("25"))
