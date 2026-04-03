from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from papertrade.trading_logic.contracts import FundingRoundSnapshot, Instrument, Pair
from papertrade.data_streaming.sources.platform_snapshots import PostgresFundingRoundSnapshotSource, SQLiteFundingRoundSnapshotSource


class _FakeCursor:
    def __init__(self, row=None, rows=None) -> None:
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeConnection:
    def __init__(self, snapshot_row, *, table_exists: bool = True) -> None:
        self.snapshot_row = snapshot_row
        self.table_exists = table_exists

    def execute(self, query, params=None):
        normalized = " ".join(str(query).split())
        if normalized.startswith("SELECT 1"):
            return _FakeCursor({"ok": 1})
        if "to_regclass('public.funding_round_snapshots')" in normalized:
            return _FakeCursor(
                {"funding_round_snapshots_table": "funding_round_snapshots" if self.table_exists else None}
            )
        if "FROM funding_round_snapshots" in normalized:
            return _FakeCursor(self.snapshot_row)
        raise AssertionError(f"unexpected query: {normalized}")

    def close(self) -> None:
        return None


class _FakePlatformDBSource:
    def __init__(self, instrument: Instrument | None) -> None:
        self.instrument = instrument

    def get_instrument(self, pair: Pair, exchange: str) -> Instrument | None:
        return self.instrument


class PlatformSnapshotSourceTests(unittest.TestCase):
    def test_postgres_snapshot_source_normalizes_open_interest_from_platform_snapshot(self) -> None:
        pair = Pair("BTC", "USDT")
        instrument = Instrument(
            exchange="bybit",
            base="BTC",
            quote="USDT",
            margin_asset="USDT",
            contract_multiplier=Decimal("0.001"),
            tick_size=Decimal("0.1"),
            lot_size=Decimal("0.001"),
            min_qty=Decimal("0.001"),
            max_qty=Decimal("100"),
            min_notional=Decimal("10"),
            max_leverage=50,
            funding_interval=8,
            launch_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        snapshot_row = {
            "funding_round": datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            "decision_cutoff": datetime(2025, 1, 11, 7, 59, 30, tzinfo=timezone.utc),
            "exchange": "bybit",
            "base": "BTC",
            "quote": "USDT",
            "symbol": "BTCUSDT",
            "market_state_observed_at": datetime(2025, 1, 11, 7, 59, 20, tzinfo=timezone.utc),
            "orderbook_observed_at": datetime(2025, 1, 11, 7, 59, 25, tzinfo=timezone.utc),
            "funding_rate_bps": Decimal("5"),
            "mark_price": Decimal("100"),
            "index_price": Decimal("99.5"),
            "open_interest": Decimal("1000"),
            "bid_price": Decimal("99.9"),
            "ask_price": Decimal("100.1"),
            "bid_amount": Decimal("3"),
            "ask_amount": Decimal("2"),
            "book_imbalance": Decimal("0.2"),
            "liquidation_amount_8h": None,
            "liquidation_complete": False,
            "snapshot_valid": True,
            "reason_code": "ok",
        }

        source = PostgresFundingRoundSnapshotSource(
            dsn="postgres://unused",
            platform_db_source=_FakePlatformDBSource(instrument),
            open_interest_mode="mark_notional",
            connection_factory=lambda: _FakeConnection(snapshot_row),
        )

        snapshot = source.get_snapshot(exchange="bybit", pair=pair, funding_round=snapshot_row["funding_round"])

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.open_interest, Decimal("100.000"))
        self.assertEqual(snapshot.reason_code, "ok")
        self.assertTrue(snapshot.snapshot_valid)

    def test_ping_raises_when_platform_snapshot_table_missing(self) -> None:
        source = PostgresFundingRoundSnapshotSource(
            dsn="postgres://unused",
            platform_db_source=_FakePlatformDBSource(None),
            connection_factory=lambda: _FakeConnection(None, table_exists=False),
        )

        with self.assertRaisesRegex(ValueError, "missing platform table: funding_round_snapshots"):
            source.ping()

    def test_sqlite_snapshot_source_round_trips_snapshot(self) -> None:
        pair = Pair("BTC", "USDT")
        instrument = Instrument(
            exchange="bybit",
            base="BTC",
            quote="USDT",
            margin_asset="USDT",
            contract_multiplier=Decimal("0.001"),
            tick_size=Decimal("0.1"),
            lot_size=Decimal("0.001"),
            min_qty=Decimal("0.001"),
            max_qty=Decimal("100"),
            min_notional=Decimal("10"),
            max_leverage=50,
            funding_interval=8,
            launch_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        snapshot = FundingRoundSnapshot(
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            decision_cutoff=datetime(2025, 1, 11, 7, 59, 30, tzinfo=timezone.utc),
            exchange="bybit",
            pair=pair,
            market_state_observed_at=datetime(2025, 1, 11, 7, 59, 20, tzinfo=timezone.utc),
            orderbook_observed_at=datetime(2025, 1, 11, 7, 59, 25, tzinfo=timezone.utc),
            funding_rate_bps=Decimal("5"),
            mark_price=Decimal("100"),
            index_price=Decimal("99.5"),
            open_interest=Decimal("1000"),
            bid_price=Decimal("99.9"),
            ask_price=Decimal("100.1"),
            bid_amount=Decimal("3"),
            ask_amount=Decimal("2"),
            book_imbalance=Decimal("0.2"),
            liquidation_amount_8h=Decimal("12.5"),
            liquidation_complete=True,
            snapshot_valid=True,
            reason_code="ok",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "papertrade.sqlite3"
            source = SQLiteFundingRoundSnapshotSource(
                path=db_path,
                platform_db_source=_FakePlatformDBSource(instrument),
                open_interest_mode="mark_notional",
            )
            source.put_snapshot(snapshot)

            loaded = source.get_snapshot(
                exchange="bybit",
                pair=pair,
                funding_round=snapshot.funding_round,
            )

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.open_interest, Decimal("100.000"))
        self.assertEqual(loaded.liquidation_amount_8h, Decimal("12.5"))
        self.assertEqual(loaded.reason_code, "ok")

