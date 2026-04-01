from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .contracts import Pair
from .scheduler import ensure_utc
from .sources.platform_db import PlatformDBSource


BPS_MULTIPLIER = Decimal("10000")


@dataclass(frozen=True)
class FundingSpreadHistory:
    lag1_abs_spread_bps: Decimal | None
    rolling3_mean_abs_spread_bps: Decimal | None
    matched_spreads_bps: tuple[Decimal, ...]


@dataclass(frozen=True)
class FundingSpreadHistoryLoader:
    source: PlatformDBSource
    lookback_limit: int = 8
    rolling_window: int = 3

    def __post_init__(self) -> None:
        if self.lookback_limit <= 0:
            raise ValueError("lookback_limit must be positive")
        if self.rolling_window <= 0:
            raise ValueError("rolling_window must be positive")

    def load(
        self,
        *,
        pair: Pair,
        funding_round: datetime,
    ) -> FundingSpreadHistory:
        funding_round = ensure_utc(funding_round)
        bybit_history = self.source.load_funding_history(pair, "bybit", self.lookback_limit)
        bitget_history = self.source.load_funding_history(pair, "bitget", self.lookback_limit)

        bybit_by_time = {
            item.time: item
            for item in bybit_history
            if item.time < funding_round
        }
        bitget_by_time = {
            item.time: item
            for item in bitget_history
            if item.time < funding_round
        }

        matched_times = sorted(
            set(bybit_by_time).intersection(bitget_by_time),
            reverse=True,
        )
        matched_spreads = tuple(
            abs((bybit_by_time[time].funding_rate - bitget_by_time[time].funding_rate) * BPS_MULTIPLIER)
            for time in matched_times
        )

        lag1 = matched_spreads[0] if matched_spreads else None
        rolling3 = None
        if len(matched_spreads) >= self.rolling_window:
            window = matched_spreads[: self.rolling_window]
            rolling3 = sum(window, Decimal("0")) / Decimal(self.rolling_window)

        return FundingSpreadHistory(
            lag1_abs_spread_bps=lag1,
            rolling3_mean_abs_spread_bps=rolling3,
            matched_spreads_bps=matched_spreads,
        )
