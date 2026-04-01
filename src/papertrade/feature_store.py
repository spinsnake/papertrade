from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .contracts import FeatureSnapshot, FundingRoundSnapshot, Pair


def _premium_bps(mark_price: Decimal, index_price: Decimal) -> Decimal:
    if index_price <= 0:
        raise ValueError("index_price must be positive")
    return (mark_price - index_price) / index_price * Decimal("10000")


@dataclass(frozen=True)
class FeatureBuilder:
    strategy: str = "hybrid_aggressive_safe_valid"

    def build(
        self,
        *,
        funding_round,
        pair: Pair,
        bybit_snapshot: FundingRoundSnapshot,
        bitget_snapshot: FundingRoundSnapshot,
        lag1_abs_spread_bps: Decimal | None,
        rolling3_mean_abs_spread_bps: Decimal | None,
    ) -> FeatureSnapshot:
        if not bybit_snapshot.snapshot_valid:
            return FeatureSnapshot(funding_round, self.strategy, pair, False, bybit_snapshot.reason_code)
        if not bitget_snapshot.snapshot_valid:
            return FeatureSnapshot(funding_round, self.strategy, pair, False, bitget_snapshot.reason_code)

        required = (
            bybit_snapshot.funding_rate_bps,
            bitget_snapshot.funding_rate_bps,
            bybit_snapshot.mark_price,
            bitget_snapshot.mark_price,
            bybit_snapshot.index_price,
            bitget_snapshot.index_price,
            bybit_snapshot.open_interest,
            bitget_snapshot.open_interest,
            bybit_snapshot.bid_amount,
            bitget_snapshot.bid_amount,
            bybit_snapshot.ask_amount,
            bitget_snapshot.ask_amount,
            bybit_snapshot.book_imbalance,
            bitget_snapshot.book_imbalance,
        )
        if any(value is None for value in required):
            return FeatureSnapshot(funding_round, self.strategy, pair, False, "missing_market_data")
        if lag1_abs_spread_bps is None or rolling3_mean_abs_spread_bps is None:
            return FeatureSnapshot(funding_round, self.strategy, pair, False, "missing_lag_history")

        assert bybit_snapshot.funding_rate_bps is not None
        assert bitget_snapshot.funding_rate_bps is not None
        assert bybit_snapshot.mark_price is not None
        assert bitget_snapshot.mark_price is not None
        assert bybit_snapshot.index_price is not None
        assert bitget_snapshot.index_price is not None
        assert bybit_snapshot.open_interest is not None
        assert bitget_snapshot.open_interest is not None
        assert bybit_snapshot.book_imbalance is not None
        assert bitget_snapshot.book_imbalance is not None

        signed_spread_bps = bybit_snapshot.funding_rate_bps - bitget_snapshot.funding_rate_bps
        bybit_premium = _premium_bps(bybit_snapshot.mark_price, bybit_snapshot.index_price)
        bitget_premium = _premium_bps(bitget_snapshot.mark_price, bitget_snapshot.index_price)
        return FeatureSnapshot(
            funding_round=funding_round,
            strategy=self.strategy,
            pair=pair,
            entry_evaluable=True,
            reason_code="ok",
            current_abs_funding_spread_bps=abs(signed_spread_bps),
            rolling3_mean_abs_funding_spread_bps=rolling3_mean_abs_spread_bps,
            lag1_current_abs_funding_spread_bps=lag1_abs_spread_bps,
            bybit_premium_bps=bybit_premium,
            bitget_futures_premium_bps=bitget_premium,
            premium_abs_gap_bps=abs(bybit_premium - bitget_premium),
            bybit_open_interest=bybit_snapshot.open_interest,
            bitget_open_interest=bitget_snapshot.open_interest,
            oi_gap=bybit_snapshot.open_interest - bitget_snapshot.open_interest,
            oi_total=bybit_snapshot.open_interest + bitget_snapshot.open_interest,
            book_imbalance_abs_gap=abs(bybit_snapshot.book_imbalance - bitget_snapshot.book_imbalance),
            bybit_liquidation_amount_8h=bybit_snapshot.liquidation_amount_8h or Decimal("0"),
            signed_spread_bps=signed_spread_bps,
        )
