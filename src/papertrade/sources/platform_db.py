from __future__ import annotations

from typing import Protocol, Sequence

from ..contracts import Funding, Instrument, OpenInterest, Pair


class PlatformDBSource(Protocol):
    def list_instruments(self) -> Sequence[Instrument]:
        ...

    def list_pairs(self) -> Sequence[Pair]:
        ...

    def load_funding_history(self, pair: Pair, exchange: str, limit: int) -> Sequence[Funding]:
        ...

    def load_open_interest_history(self, pair: Pair, exchange: str, limit: int) -> Sequence[OpenInterest]:
        ...
