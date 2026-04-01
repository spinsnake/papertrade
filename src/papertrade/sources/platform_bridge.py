from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import MarketState, Orderbook, Pair


@dataclass
class InMemoryPlatformBridge:
    market_states: dict[tuple[str, Pair], MarketState] = field(default_factory=dict)
    orderbooks: dict[tuple[str, Pair], Orderbook] = field(default_factory=dict)

    def put_market_state(self, exchange: str, state: MarketState) -> None:
        self.market_states[(exchange, state.pair)] = state

    def put_orderbook(self, exchange: str, orderbook: Orderbook) -> None:
        self.orderbooks[(exchange, orderbook.pair)] = orderbook

    def get_market_state(self, exchange: str, pair: Pair) -> MarketState | None:
        return self.market_states.get((exchange, pair))

    def get_orderbook(self, exchange: str, pair: Pair) -> Orderbook | None:
        return self.orderbooks.get((exchange, pair))
