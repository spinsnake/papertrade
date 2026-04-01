from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from papertrade.contracts import Level, MarketState, Orderbook, Pair
from papertrade.scheduler import FundingDecision
from papertrade.snapshot_collector import SnapshotCollector
from papertrade.sources.platform_bridge import InMemoryPlatformBridge


class FakeLiquidationSource:
    def __init__(self, amount: Decimal) -> None:
        self.amount = amount

    def sum_bybit_liquidation_usd(self, pair: Pair, start: datetime, end: datetime) -> Decimal:
        return self.amount


def make_market_state(*, pair: Pair, updated_at: datetime) -> MarketState:
    return MarketState(
        pair=pair,
        index_price=Decimal("100"),
        mark_price=Decimal("101"),
        funding_rate=Decimal("0.0005"),
        open_interest=Decimal("1000"),
        base_volume=Decimal("0"),
        quote_volume=Decimal("0"),
        sequence=1,
        updated_at=updated_at,
    )


def make_orderbook(*, pair: Pair, updated_at: datetime) -> Orderbook:
    return Orderbook(
        pair=pair,
        bids=(Level(price=Decimal("100"), size=Decimal("3")),),
        asks=(Level(price=Decimal("101"), size=Decimal("1")),),
        sequence=1,
        updated_at=updated_at,
    )


class SnapshotCollectorTests(unittest.TestCase):
    def test_collect_snapshot_returns_valid_snapshot_when_bridge_data_is_fresh(self) -> None:
        pair = Pair("BTC", "USDT")
        decision = FundingDecision(
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            decision_cutoff=datetime(2025, 1, 11, 7, 59, 30, tzinfo=timezone.utc),
        )
        bridge = InMemoryPlatformBridge()
        bridge.put_market_state(
            "bybit",
            make_market_state(pair=pair, updated_at=datetime(2025, 1, 11, 7, 59, 20, tzinfo=timezone.utc)),
        )
        bridge.put_orderbook(
            "bybit",
            make_orderbook(pair=pair, updated_at=datetime(2025, 1, 11, 7, 59, 25, tzinfo=timezone.utc)),
        )

        collector = SnapshotCollector(
            bridge=bridge,
            liquidation_source=FakeLiquidationSource(Decimal("250")),
            market_state_staleness_seconds=120,
            orderbook_staleness_seconds=15,
        )

        snapshot = collector.collect_snapshot(
            exchange="bybit",
            pair=pair,
            funding_decision=decision,
        )

        self.assertTrue(snapshot.snapshot_valid)
        self.assertEqual(snapshot.reason_code, "ok")
        self.assertEqual(snapshot.funding_rate_bps, Decimal("5"))
        self.assertEqual(snapshot.mark_price, Decimal("101"))
        self.assertEqual(snapshot.index_price, Decimal("100"))
        self.assertEqual(snapshot.open_interest, Decimal("1000"))
        self.assertEqual(snapshot.bid_price, Decimal("100"))
        self.assertEqual(snapshot.ask_price, Decimal("101"))
        self.assertEqual(snapshot.bid_amount, Decimal("3"))
        self.assertEqual(snapshot.ask_amount, Decimal("1"))
        self.assertEqual(snapshot.book_imbalance, Decimal("0.5"))
        self.assertEqual(snapshot.liquidation_amount_8h, Decimal("250"))
        self.assertTrue(snapshot.liquidation_complete)

    def test_collect_snapshot_marks_missing_market_state_invalid(self) -> None:
        pair = Pair("BTC", "USDT")
        decision = FundingDecision(
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            decision_cutoff=datetime(2025, 1, 11, 7, 59, 30, tzinfo=timezone.utc),
        )
        bridge = InMemoryPlatformBridge()
        bridge.put_orderbook(
            "bybit",
            make_orderbook(pair=pair, updated_at=datetime(2025, 1, 11, 7, 59, 25, tzinfo=timezone.utc)),
        )
        collector = SnapshotCollector(bridge=bridge)

        snapshot = collector.collect_snapshot(
            exchange="bybit",
            pair=pair,
            funding_decision=decision,
        )

        self.assertFalse(snapshot.snapshot_valid)
        self.assertEqual(snapshot.reason_code, "missing_market_state")
        self.assertIsNone(snapshot.funding_rate_bps)

    def test_collect_snapshot_marks_stale_orderbook_invalid(self) -> None:
        pair = Pair("BTC", "USDT")
        decision = FundingDecision(
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            decision_cutoff=datetime(2025, 1, 11, 7, 59, 30, tzinfo=timezone.utc),
        )
        bridge = InMemoryPlatformBridge()
        bridge.put_market_state(
            "bybit",
            make_market_state(pair=pair, updated_at=datetime(2025, 1, 11, 7, 59, 20, tzinfo=timezone.utc)),
        )
        bridge.put_orderbook(
            "bybit",
            make_orderbook(pair=pair, updated_at=datetime(2025, 1, 11, 7, 59, 0, tzinfo=timezone.utc)),
        )
        collector = SnapshotCollector(
            bridge=bridge,
            orderbook_staleness_seconds=15,
        )

        snapshot = collector.collect_snapshot(
            exchange="bybit",
            pair=pair,
            funding_decision=decision,
        )

        self.assertFalse(snapshot.snapshot_valid)
        self.assertEqual(snapshot.reason_code, "orderbook_stale")

    def test_collect_snapshot_marks_after_cutoff_market_state_invalid(self) -> None:
        pair = Pair("BTC", "USDT")
        decision = FundingDecision(
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            decision_cutoff=datetime(2025, 1, 11, 7, 59, 30, tzinfo=timezone.utc),
        )
        bridge = InMemoryPlatformBridge()
        bridge.put_market_state(
            "bybit",
            make_market_state(pair=pair, updated_at=datetime(2025, 1, 11, 7, 59, 40, tzinfo=timezone.utc)),
        )
        bridge.put_orderbook(
            "bybit",
            make_orderbook(pair=pair, updated_at=datetime(2025, 1, 11, 7, 59, 25, tzinfo=timezone.utc)),
        )
        collector = SnapshotCollector(bridge=bridge)

        snapshot = collector.collect_snapshot(
            exchange="bybit",
            pair=pair,
            funding_decision=decision,
        )

        self.assertFalse(snapshot.snapshot_valid)
        self.assertEqual(snapshot.reason_code, "market_state_after_cutoff")

    def test_collect_snapshot_flags_missing_bybit_liquidation_source_as_incomplete(self) -> None:
        pair = Pair("BTC", "USDT")
        decision = FundingDecision(
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            decision_cutoff=datetime(2025, 1, 11, 7, 59, 30, tzinfo=timezone.utc),
        )
        bridge = InMemoryPlatformBridge()
        bridge.put_market_state(
            "bybit",
            make_market_state(pair=pair, updated_at=datetime(2025, 1, 11, 7, 59, 20, tzinfo=timezone.utc)),
        )
        bridge.put_orderbook(
            "bybit",
            make_orderbook(pair=pair, updated_at=datetime(2025, 1, 11, 7, 59, 25, tzinfo=timezone.utc)),
        )
        collector = SnapshotCollector(bridge=bridge)

        snapshot = collector.collect_snapshot(
            exchange="bybit",
            pair=pair,
            funding_decision=decision,
        )

        self.assertTrue(snapshot.snapshot_valid)
        self.assertIsNone(snapshot.liquidation_amount_8h)
        self.assertFalse(snapshot.liquidation_complete)

    def test_collect_pair_snapshots_returns_bybit_and_bitget_snapshots(self) -> None:
        pair = Pair("BTC", "USDT")
        decision = FundingDecision(
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            decision_cutoff=datetime(2025, 1, 11, 7, 59, 30, tzinfo=timezone.utc),
        )
        bridge = InMemoryPlatformBridge()
        for exchange in ("bybit", "bitget"):
            bridge.put_market_state(
                exchange,
                make_market_state(pair=pair, updated_at=datetime(2025, 1, 11, 7, 59, 20, tzinfo=timezone.utc)),
            )
            bridge.put_orderbook(
                exchange,
                make_orderbook(pair=pair, updated_at=datetime(2025, 1, 11, 7, 59, 25, tzinfo=timezone.utc)),
            )

        collector = SnapshotCollector(
            bridge=bridge,
            liquidation_source=FakeLiquidationSource(Decimal("10")),
        )

        bybit_snapshot, bitget_snapshot = collector.collect_pair_snapshots(
            pair=pair,
            funding_decision=decision,
        )

        self.assertEqual(bybit_snapshot.exchange, "bybit")
        self.assertEqual(bitget_snapshot.exchange, "bitget")
        self.assertTrue(bybit_snapshot.snapshot_valid)
        self.assertTrue(bitget_snapshot.snapshot_valid)
        self.assertEqual(bybit_snapshot.liquidation_amount_8h, Decimal("10"))
        self.assertEqual(bitget_snapshot.liquidation_amount_8h, Decimal("0"))
        self.assertTrue(bitget_snapshot.liquidation_complete)
