from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

from .enums import PositionState, RunStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, order=True)
class Pair:
    base: str
    quote: str

    @property
    def symbol(self) -> str:
        return f"{self.base}{self.quote}"


@dataclass(frozen=True)
class Instrument:
    exchange: str
    base: str
    quote: str
    margin_asset: str
    contract_multiplier: Decimal
    tick_size: Decimal
    lot_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal
    max_leverage: int
    funding_interval: int
    launch_time: datetime

    @property
    def pair(self) -> Pair:
        return Pair(self.base, self.quote)


@dataclass(frozen=True)
class Level:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class Orderbook:
    pair: Pair
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    sequence: int
    updated_at: datetime

    def best_bid(self) -> Level | None:
        return self.bids[0] if self.bids else None

    def best_ask(self) -> Level | None:
        return self.asks[0] if self.asks else None


@dataclass(frozen=True)
class MarketState:
    pair: Pair
    index_price: Decimal
    mark_price: Decimal
    funding_rate: Decimal
    open_interest: Decimal
    base_volume: Decimal
    quote_volume: Decimal
    sequence: int
    updated_at: datetime


@dataclass(frozen=True)
class OpenInterest:
    time: datetime
    exchange: str
    base: str
    quote: str
    open_interest: Decimal

    @property
    def pair(self) -> Pair:
        return Pair(self.base, self.quote)


@dataclass(frozen=True)
class Funding:
    time: datetime
    exchange: str
    base: str
    quote: str
    funding_rate: Decimal

    @property
    def pair(self) -> Pair:
        return Pair(self.base, self.quote)


@dataclass(frozen=True)
class FundingRoundSnapshot:
    funding_round: datetime
    decision_cutoff: datetime
    exchange: str
    pair: Pair
    market_state_observed_at: datetime | None
    orderbook_observed_at: datetime | None
    funding_rate_bps: Decimal | None
    mark_price: Decimal | None
    index_price: Decimal | None
    open_interest: Decimal | None
    bid_price: Decimal | None
    ask_price: Decimal | None
    bid_amount: Decimal | None
    ask_amount: Decimal | None
    book_imbalance: Decimal | None
    liquidation_amount_8h: Decimal | None
    liquidation_complete: bool
    snapshot_valid: bool
    reason_code: str


@dataclass
class FeatureSnapshot:
    funding_round: datetime
    strategy: str
    pair: Pair
    entry_evaluable: bool
    reason_code: str
    current_abs_funding_spread_bps: Decimal | None = None
    rolling3_mean_abs_funding_spread_bps: Decimal | None = None
    lag1_current_abs_funding_spread_bps: Decimal | None = None
    bybit_premium_bps: Decimal | None = None
    bitget_futures_premium_bps: Decimal | None = None
    premium_abs_gap_bps: Decimal | None = None
    bybit_open_interest: Decimal | None = None
    bitget_open_interest: Decimal | None = None
    oi_gap: Decimal | None = None
    oi_total: Decimal | None = None
    book_imbalance_abs_gap: Decimal | None = None
    bybit_liquidation_amount_8h: Decimal | None = None
    signed_spread_bps: Decimal | None = None
    suggested_short_exchange: str | None = None
    suggested_long_exchange: str | None = None
    risky_logit: Decimal | None = None
    risky_score: Decimal | None = None
    safe_logit: Decimal | None = None
    safe_score: Decimal | None = None
    selected: bool = False

    def values_for(self, feature_order: list[str]) -> Mapping[str, Decimal]:
        values: dict[str, Decimal] = {}
        for name in feature_order:
            value = getattr(self, name)
            if value is None:
                raise KeyError(f"missing feature value: {name}")
            values[name] = value
        return values


@dataclass(frozen=True)
class EntryDecision:
    funding_round: datetime
    pair: Pair
    selected: bool
    reason_code: str
    short_exchange: str | None
    long_exchange: str | None
    safe_score: Decimal | None
    risky_score: Decimal | None
    signed_spread_bps: Decimal | None


@dataclass(frozen=True)
class PaperPositionRound:
    funding_round: datetime
    round_no: int
    bybit_funding_rate_bps: Decimal | None
    bitget_funding_rate_bps: Decimal | None
    realized_round_gross_bps: Decimal | None
    settlement_evaluable: bool
    reason_code: str


@dataclass
class PaperPosition:
    position_id: str
    run_id: str
    strategy: str
    state: PositionState
    pair: Pair
    short_exchange: str
    long_exchange: str
    entry_round: datetime
    planned_exit_round: datetime
    actual_exit_round: datetime | None
    entry_time: datetime
    exit_time: datetime | None
    entry_safe_score: Decimal
    entry_risky_score: Decimal
    entry_signed_spread_bps: Decimal
    entry_reason_code: str
    notional: Decimal
    rounds_collected: int = 0
    gross_bps: Decimal | None = None
    fee_bps: Decimal | None = None
    slippage_bps: Decimal | None = None
    net_bps: Decimal | None = None
    gross_pnl: Decimal | None = None
    fee_pnl: Decimal | None = None
    slippage_pnl: Decimal | None = None
    net_pnl: Decimal | None = None
    equity_before: Decimal = Decimal("0")
    equity_after: Decimal | None = None
    close_reason: str | None = None
    rounds: list[PaperPositionRound] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.state is PositionState.OPEN and self.close_reason is not None:
            raise ValueError("open position must not have close_reason")
        if self.state in {PositionState.CLOSED, PositionState.SETTLEMENT_ERROR} and not self.close_reason:
            raise ValueError("closed position must have close_reason")


@dataclass(frozen=True)
class PaperTrade:
    trade_id: str
    run_id: str
    position_id: str
    strategy: str
    pair: Pair
    short_exchange: str
    long_exchange: str
    entry_round: datetime
    exit_round: datetime
    entry_time: datetime
    exit_time: datetime
    rounds_held: int
    entry_safe_score: Decimal
    entry_risky_score: Decimal
    notional: Decimal
    gross_bps: Decimal
    fee_bps: Decimal
    slippage_bps: Decimal
    net_bps: Decimal
    gross_pnl: Decimal
    fee_pnl: Decimal
    slippage_pnl: Decimal
    net_pnl: Decimal
    equity_before: Decimal
    equity_after: Decimal
    close_reason: str


@dataclass
class PaperRun:
    run_id: str
    strategy: str
    runtime_mode: str
    status: RunStatus
    status_reason: str
    report_output_dir: str
    report_filename_pattern: str
    started_at: datetime
    finished_at: datetime | None
    initial_equity: Decimal
    current_equity: Decimal
    peak_equity: Decimal
    max_drawdown_pct: Decimal
    notional_pct: Decimal
    bybit_taker_fee_bps: Decimal
    bitget_taker_fee_bps: Decimal
    fee_bps: Decimal
    slippage_bps: Decimal
    decision_buffer_seconds: int
    market_state_staleness_sec: int
    orderbook_staleness_sec: int
    strict_liquidation: bool

    @classmethod
    def new(
        cls,
        *,
        run_id: str,
        strategy: str,
        runtime_mode: str,
        report_output_dir: str,
        report_filename_pattern: str,
        initial_equity: Decimal,
        notional_pct: Decimal,
        slippage_bps: Decimal,
        decision_buffer_seconds: int,
        market_state_staleness_sec: int,
        orderbook_staleness_sec: int,
        strict_liquidation: bool,
        fee_bps: Decimal | None = None,
        bybit_taker_fee_bps: Decimal | None = None,
        bitget_taker_fee_bps: Decimal | None = None,
    ) -> "PaperRun":
        resolved_bybit_taker_fee_bps, resolved_bitget_taker_fee_bps, resolved_fee_bps = _resolve_fee_configuration(
            fee_bps=fee_bps,
            bybit_taker_fee_bps=bybit_taker_fee_bps,
            bitget_taker_fee_bps=bitget_taker_fee_bps,
        )
        return cls(
            run_id=run_id,
            strategy=strategy,
            runtime_mode=runtime_mode,
            status=RunStatus.RUNNING,
            status_reason="ok",
            report_output_dir=report_output_dir,
            report_filename_pattern=report_filename_pattern,
            started_at=utc_now(),
            finished_at=None,
            initial_equity=initial_equity,
            current_equity=initial_equity,
            peak_equity=initial_equity,
            max_drawdown_pct=Decimal("0"),
            notional_pct=notional_pct,
            bybit_taker_fee_bps=resolved_bybit_taker_fee_bps,
            bitget_taker_fee_bps=resolved_bitget_taker_fee_bps,
            fee_bps=resolved_fee_bps,
            slippage_bps=slippage_bps,
            decision_buffer_seconds=decision_buffer_seconds,
            market_state_staleness_sec=market_state_staleness_sec,
            orderbook_staleness_sec=orderbook_staleness_sec,
            strict_liquidation=strict_liquidation,
        )

    def mark_blocked(self, reason: str) -> None:
        self.status = RunStatus.BLOCKED
        self.status_reason = reason
        self.finished_at = utc_now()

    def mark_failed(self, reason: str) -> None:
        self.status = RunStatus.FAILED
        self.status_reason = reason
        self.finished_at = utc_now()

    def mark_finished(self) -> None:
        self.status = RunStatus.FINISHED
        self.status_reason = "ok"
        self.finished_at = utc_now()


def _resolve_fee_configuration(
    *,
    fee_bps: Decimal | None,
    bybit_taker_fee_bps: Decimal | None,
    bitget_taker_fee_bps: Decimal | None,
) -> tuple[Decimal, Decimal, Decimal]:
    if bybit_taker_fee_bps is None and bitget_taker_fee_bps is None:
        if fee_bps is None:
            raise ValueError("fee configuration is required")
        resolved_bybit_taker_fee_bps = fee_bps / Decimal("4")
        resolved_bitget_taker_fee_bps = fee_bps / Decimal("4")
    elif bybit_taker_fee_bps is None or bitget_taker_fee_bps is None:
        raise ValueError("bybit_taker_fee_bps and bitget_taker_fee_bps must be configured together")
    else:
        resolved_bybit_taker_fee_bps = bybit_taker_fee_bps
        resolved_bitget_taker_fee_bps = bitget_taker_fee_bps

    resolved_fee_bps = (resolved_bybit_taker_fee_bps + resolved_bitget_taker_fee_bps) * Decimal("2")
    return resolved_bybit_taker_fee_bps, resolved_bitget_taker_fee_bps, resolved_fee_bps
