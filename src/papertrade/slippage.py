from __future__ import annotations

from decimal import Decimal

from .contracts import EntryDecision, FundingRoundSnapshot, Instrument, PaperPosition
from .sources.platform_db import PlatformDBSource


BPS_MULTIPLIER = Decimal("10000")
HALF = Decimal("0.5")
ONE = Decimal("1")
ZERO = Decimal("0")


def estimate_entry_slippage_bps(
    *,
    decision: EntryDecision,
    notional: Decimal,
    bybit_snapshot: FundingRoundSnapshot,
    bitget_snapshot: FundingRoundSnapshot,
    platform_db_source: PlatformDBSource,
    model: str,
    fallback_total_bps: Decimal,
) -> Decimal:
    if not decision.selected or decision.short_exchange is None or decision.long_exchange is None:
        return _phase_fallback_bps(fallback_total_bps)
    return _estimate_phase_slippage_bps(
        short_exchange=decision.short_exchange,
        long_exchange=decision.long_exchange,
        short_side="sell",
        long_side="buy",
        notional=notional,
        bybit_snapshot=bybit_snapshot,
        bitget_snapshot=bitget_snapshot,
        platform_db_source=platform_db_source,
        model=model,
        fallback_total_bps=fallback_total_bps,
    )


def estimate_exit_slippage_bps(
    *,
    position: PaperPosition,
    bybit_snapshot: FundingRoundSnapshot,
    bitget_snapshot: FundingRoundSnapshot,
    platform_db_source: PlatformDBSource,
    model: str,
    fallback_total_bps: Decimal,
) -> Decimal:
    return _estimate_phase_slippage_bps(
        short_exchange=position.short_exchange,
        long_exchange=position.long_exchange,
        short_side="buy",
        long_side="sell",
        notional=position.notional,
        bybit_snapshot=bybit_snapshot,
        bitget_snapshot=bitget_snapshot,
        platform_db_source=platform_db_source,
        model=model,
        fallback_total_bps=fallback_total_bps,
    )


def _estimate_phase_slippage_bps(
    *,
    short_exchange: str,
    long_exchange: str,
    short_side: str,
    long_side: str,
    notional: Decimal,
    bybit_snapshot: FundingRoundSnapshot,
    bitget_snapshot: FundingRoundSnapshot,
    platform_db_source: PlatformDBSource,
    model: str,
    fallback_total_bps: Decimal,
) -> Decimal:
    if model == "fixed_bps":
        return _phase_fallback_bps(fallback_total_bps)
    if model != "top_of_book":
        raise ValueError(f"unsupported slippage model: {model}")

    snapshots = {
        "bybit": bybit_snapshot,
        "bitget": bitget_snapshot,
    }
    try:
        short_snapshot = snapshots[short_exchange]
        long_snapshot = snapshots[long_exchange]
    except KeyError:
        return _phase_fallback_bps(fallback_total_bps)

    short_instrument = platform_db_source.get_instrument(short_snapshot.pair, short_exchange)
    long_instrument = platform_db_source.get_instrument(long_snapshot.pair, long_exchange)

    short_leg = _estimate_leg_slippage_bps(
        snapshot=short_snapshot,
        instrument=short_instrument,
        side=short_side,
        notional=notional,
    )
    long_leg = _estimate_leg_slippage_bps(
        snapshot=long_snapshot,
        instrument=long_instrument,
        side=long_side,
        notional=notional,
    )
    if short_leg is None or long_leg is None:
        return _phase_fallback_bps(fallback_total_bps)
    return short_leg + long_leg


def _estimate_leg_slippage_bps(
    *,
    snapshot: FundingRoundSnapshot,
    instrument: Instrument | None,
    side: str,
    notional: Decimal,
) -> Decimal | None:
    bid_price = snapshot.bid_price
    ask_price = snapshot.ask_price
    if bid_price is None or ask_price is None:
        return None
    if bid_price <= 0 or ask_price <= 0 or ask_price < bid_price:
        return None

    mid_price = (bid_price + ask_price) * HALF
    if mid_price <= 0:
        return None
    spread_bps = (ask_price - bid_price) / mid_price * BPS_MULTIPLIER
    half_spread_bps = spread_bps * HALF

    if side == "buy":
        level_price = ask_price
        level_amount = snapshot.ask_amount
    elif side == "sell":
        level_price = bid_price
        level_amount = snapshot.bid_amount
    else:
        raise ValueError(f"unsupported side: {side}")

    if level_amount is None or level_amount <= 0 or level_price <= 0:
        return None

    contract_multiplier = (
        instrument.contract_multiplier
        if instrument is not None and instrument.contract_multiplier > 0
        else ONE
    )
    top_level_notional = level_amount * contract_multiplier * level_price
    if top_level_notional <= 0:
        return None

    participation = notional / top_level_notional
    extra_levels = max(participation - ONE, ZERO)
    return half_spread_bps + spread_bps * extra_levels


def _phase_fallback_bps(fallback_total_bps: Decimal) -> Decimal:
    return fallback_total_bps * HALF
