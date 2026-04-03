from __future__ import annotations

from decimal import Decimal

from .contracts import Instrument


SUPPORTED_OPEN_INTEREST_MODES = {"raw", "mark_notional"}


def normalize_open_interest(
    raw_open_interest: Decimal,
    *,
    instrument: Instrument | None,
    mark_price: Decimal | None,
    mode: str,
) -> Decimal:
    if mode not in SUPPORTED_OPEN_INTEREST_MODES:
        raise ValueError(f"unsupported open interest mode: {mode}")
    if mode == "raw":
        return raw_open_interest
    if instrument is None:
        raise ValueError("instrument is required for mark_notional open interest mode")
    if mark_price is None:
        raise ValueError("mark_price is required for mark_notional open interest mode")
    return raw_open_interest * instrument.contract_multiplier * mark_price
