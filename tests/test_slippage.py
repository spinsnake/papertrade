from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import unittest

from papertrade.contracts import EntryDecision, FundingRoundSnapshot, Instrument, Pair
from papertrade.slippage import estimate_entry_slippage_bps, estimate_exit_slippage_bps


def make_snapshot(*, exchange: str, pair: Pair) -> FundingRoundSnapshot:
    return FundingRoundSnapshot(
        funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
        decision_cutoff=datetime(2025, 1, 11, 7, 59, 30, tzinfo=timezone.utc),
        exchange=exchange,
        pair=pair,
        market_state_observed_at=datetime(2025, 1, 11, 7, 59, 20, tzinfo=timezone.utc),
        orderbook_observed_at=datetime(2025, 1, 11, 7, 59, 25, tzinfo=timezone.utc),
        funding_rate_bps=Decimal("5"),
        mark_price=Decimal("100"),
        index_price=Decimal("100"),
        open_interest=Decimal("1000"),
        bid_price=Decimal("99.99"),
        ask_price=Decimal("100.01"),
        bid_amount=Decimal("10"),
        ask_amount=Decimal("10"),
        book_imbalance=Decimal("0"),
        liquidation_amount_8h=Decimal("0"),
        liquidation_complete=True,
        snapshot_valid=True,
        reason_code="ok",
    )


def make_instrument(*, exchange: str, pair: Pair) -> Instrument:
    return Instrument(
        exchange=exchange,
        base=pair.base,
        quote=pair.quote,
        margin_asset=pair.quote,
        contract_multiplier=Decimal("1"),
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        max_qty=Decimal("1000"),
        min_notional=Decimal("10"),
        max_leverage=50,
        funding_interval=8,
        launch_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


class _FakePlatformDBSource:
    def __init__(self, instruments: dict[tuple[str, str], Instrument]) -> None:
        self.instruments = instruments

    def get_instrument(self, pair: Pair, exchange: str) -> Instrument | None:
        return self.instruments.get((exchange, pair.symbol))


class SlippageTests(unittest.TestCase):
    def test_top_of_book_entry_slippage_uses_spread_and_size(self) -> None:
        pair = Pair("BTC", "USDT")
        bybit_snapshot = make_snapshot(exchange="bybit", pair=pair)
        bitget_snapshot = make_snapshot(exchange="bitget", pair=pair)
        db_source = _FakePlatformDBSource(
            {
                ("bybit", pair.symbol): make_instrument(exchange="bybit", pair=pair),
                ("bitget", pair.symbol): make_instrument(exchange="bitget", pair=pair),
            }
        )
        decision = EntryDecision(
            funding_round=bybit_snapshot.funding_round,
            pair=pair,
            selected=True,
            reason_code="selected",
            short_exchange="bybit",
            long_exchange="bitget",
            safe_score=Decimal("0.7"),
            risky_score=Decimal("0.8"),
            signed_spread_bps=Decimal("5"),
        )

        slippage_bps = estimate_entry_slippage_bps(
            decision=decision,
            notional=Decimal("100"),
            bybit_snapshot=bybit_snapshot,
            bitget_snapshot=bitget_snapshot,
            platform_db_source=db_source,
            model="top_of_book",
            fallback_total_bps=Decimal("4"),
        )

        self.assertEqual(slippage_bps, Decimal("2.00000"))

    def test_top_of_book_entry_slippage_falls_back_when_book_data_is_missing(self) -> None:
        pair = Pair("BTC", "USDT")
        bybit_snapshot = make_snapshot(exchange="bybit", pair=pair)
        bitget_snapshot = make_snapshot(exchange="bitget", pair=pair)
        bitget_snapshot = replace(bitget_snapshot, ask_amount=None)
        decision = EntryDecision(
            funding_round=bybit_snapshot.funding_round,
            pair=pair,
            selected=True,
            reason_code="selected",
            short_exchange="bybit",
            long_exchange="bitget",
            safe_score=Decimal("0.7"),
            risky_score=Decimal("0.8"),
            signed_spread_bps=Decimal("5"),
        )

        slippage_bps = estimate_entry_slippage_bps(
            decision=decision,
            notional=Decimal("100"),
            bybit_snapshot=bybit_snapshot,
            bitget_snapshot=bitget_snapshot,
            platform_db_source=_FakePlatformDBSource({}),
            model="top_of_book",
            fallback_total_bps=Decimal("4"),
        )

        self.assertEqual(slippage_bps, Decimal("2"))

    def test_top_of_book_exit_slippage_respects_direction(self) -> None:
        from papertrade.contracts import PaperPosition
        from papertrade.enums import PositionState

        pair = Pair("BTC", "USDT")
        bybit_snapshot = make_snapshot(exchange="bybit", pair=pair)
        bitget_snapshot = make_snapshot(exchange="bitget", pair=pair)
        db_source = _FakePlatformDBSource(
            {
                ("bybit", pair.symbol): make_instrument(exchange="bybit", pair=pair),
                ("bitget", pair.symbol): make_instrument(exchange="bitget", pair=pair),
            }
        )
        position = PaperPosition(
            position_id="p1",
            run_id="run1",
            strategy="hybrid_aggressive_safe_valid",
            state=PositionState.OPEN,
            pair=pair,
            short_exchange="bybit",
            long_exchange="bitget",
            entry_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            planned_exit_round=datetime(2025, 1, 12, 0, 0, tzinfo=timezone.utc),
            actual_exit_round=None,
            entry_time=datetime(2025, 1, 11, 7, 59, tzinfo=timezone.utc),
            exit_time=None,
            entry_safe_score=Decimal("0.7"),
            entry_risky_score=Decimal("0.8"),
            entry_signed_spread_bps=Decimal("5"),
            entry_reason_code="selected",
            notional=Decimal("100"),
        )

        slippage_bps = estimate_exit_slippage_bps(
            position=position,
            bybit_snapshot=bybit_snapshot,
            bitget_snapshot=bitget_snapshot,
            platform_db_source=db_source,
            model="top_of_book",
            fallback_total_bps=Decimal("4"),
        )

        self.assertEqual(slippage_bps, Decimal("2.00000"))
