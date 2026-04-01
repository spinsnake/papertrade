from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from .contracts import FundingRoundSnapshot, MarketState, Orderbook, Pair
from .scheduler import FundingDecision
from .sources.liquidation import LiquidationSource
from .sources.platform_bridge import InMemoryPlatformBridge


BPS_MULTIPLIER = Decimal("10000")


@dataclass(frozen=True)
class SnapshotCollector:
    bridge: InMemoryPlatformBridge
    liquidation_source: LiquidationSource | None = None
    market_state_staleness_seconds: int = 120
    orderbook_staleness_seconds: int = 15

    def __post_init__(self) -> None:
        if self.market_state_staleness_seconds <= 0:
            raise ValueError("market_state_staleness_seconds must be positive")
        if self.orderbook_staleness_seconds <= 0:
            raise ValueError("orderbook_staleness_seconds must be positive")

    def collect_snapshot(
        self,
        *,
        exchange: str,
        pair: Pair,
        funding_decision: FundingDecision,
    ) -> FundingRoundSnapshot:
        market_state = self.bridge.get_market_state(exchange, pair)
        orderbook = self.bridge.get_orderbook(exchange, pair)
        market_reason = self._market_state_reason(market_state, funding_decision)
        orderbook_reason = self._orderbook_reason(orderbook, funding_decision)
        liquidation_amount, liquidation_complete = self._load_liquidation(
            exchange=exchange,
            pair=pair,
            funding_decision=funding_decision,
        )
        best_bid = orderbook.best_bid() if orderbook is not None else None
        best_ask = orderbook.best_ask() if orderbook is not None else None

        snapshot_valid = market_reason is None and orderbook_reason is None
        reason_code = market_reason or orderbook_reason or "ok"

        funding_rate_bps = None
        mark_price = None
        index_price = None
        open_interest = None
        market_state_observed_at = None
        if market_state is not None:
            funding_rate_bps = market_state.funding_rate * BPS_MULTIPLIER
            mark_price = market_state.mark_price
            index_price = market_state.index_price
            open_interest = market_state.open_interest
            market_state_observed_at = market_state.updated_at

        bid_price = None
        ask_price = None
        bid_amount = None
        ask_amount = None
        orderbook_observed_at = None
        book_imbalance = None
        if orderbook is not None:
            orderbook_observed_at = orderbook.updated_at
            if best_bid is not None:
                bid_price = best_bid.price
                bid_amount = best_bid.size
            if best_ask is not None:
                ask_price = best_ask.price
                ask_amount = best_ask.size
            if best_bid is not None and best_ask is not None:
                total_size = best_bid.size + best_ask.size
                if total_size > 0:
                    book_imbalance = (best_bid.size - best_ask.size) / total_size

        return FundingRoundSnapshot(
            funding_round=funding_decision.funding_round,
            decision_cutoff=funding_decision.decision_cutoff,
            exchange=exchange,
            pair=pair,
            market_state_observed_at=market_state_observed_at,
            orderbook_observed_at=orderbook_observed_at,
            funding_rate_bps=funding_rate_bps,
            mark_price=mark_price,
            index_price=index_price,
            open_interest=open_interest,
            bid_price=bid_price,
            ask_price=ask_price,
            bid_amount=bid_amount,
            ask_amount=ask_amount,
            book_imbalance=book_imbalance,
            liquidation_amount_8h=liquidation_amount,
            liquidation_complete=liquidation_complete,
            snapshot_valid=snapshot_valid,
            reason_code=reason_code,
        )

    def collect_pair_snapshots(
        self,
        *,
        pair: Pair,
        funding_decision: FundingDecision,
    ) -> tuple[FundingRoundSnapshot, FundingRoundSnapshot]:
        return (
            self.collect_snapshot(
                exchange="bybit",
                pair=pair,
                funding_decision=funding_decision,
            ),
            self.collect_snapshot(
                exchange="bitget",
                pair=pair,
                funding_decision=funding_decision,
            ),
        )

    def _market_state_reason(
        self,
        market_state: MarketState | None,
        funding_decision: FundingDecision,
    ) -> str | None:
        if market_state is None:
            return "missing_market_state"
        if market_state.updated_at > funding_decision.decision_cutoff:
            return "market_state_after_cutoff"
        staleness = funding_decision.decision_cutoff - market_state.updated_at
        if staleness > timedelta(seconds=self.market_state_staleness_seconds):
            return "market_state_stale"
        return None

    def _orderbook_reason(
        self,
        orderbook: Orderbook | None,
        funding_decision: FundingDecision,
    ) -> str | None:
        if orderbook is None:
            return "missing_orderbook"
        if orderbook.best_bid() is None or orderbook.best_ask() is None:
            return "empty_orderbook"
        if orderbook.updated_at > funding_decision.decision_cutoff:
            return "orderbook_after_cutoff"
        staleness = funding_decision.decision_cutoff - orderbook.updated_at
        if staleness > timedelta(seconds=self.orderbook_staleness_seconds):
            return "orderbook_stale"
        return None

    def _load_liquidation(
        self,
        *,
        exchange: str,
        pair: Pair,
        funding_decision: FundingDecision,
    ) -> tuple[Decimal | None, bool]:
        if exchange != "bybit":
            return Decimal("0"), True
        if self.liquidation_source is None:
            return None, False

        liquidation_start = funding_decision.funding_round - timedelta(hours=8)
        liquidation_end = funding_decision.funding_round
        try:
            amount = self.liquidation_source.sum_bybit_liquidation_usd(
                pair,
                liquidation_start,
                liquidation_end,
            )
        except Exception:
            return None, False
        return amount, True
