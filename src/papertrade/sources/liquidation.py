from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from ..contracts import Pair


class LiquidationSource(Protocol):
    def sum_bybit_liquidation_usd(self, pair: Pair, start: datetime, end: datetime) -> Decimal:
        ...
