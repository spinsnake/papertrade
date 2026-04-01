from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from .contracts import EntryDecision, PaperPosition, PaperPositionRound, PaperRun, PaperTrade, Pair
from .enums import PositionState


@dataclass
class PortfolioSimulator:
    run: PaperRun
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    trades: list[PaperTrade] = field(default_factory=list)

    @classmethod
    def from_state(
        cls,
        *,
        run: PaperRun,
        positions: list[PaperPosition],
        trades: list[PaperTrade],
    ) -> "PortfolioSimulator":
        return cls(
            run=run,
            positions={position.position_id: position for position in positions},
            trades=list(trades),
        )

    def has_open_position(self, pair: Pair) -> bool:
        return any(position.pair == pair and position.state is PositionState.OPEN for position in self.positions.values())

    def open_position(
        self,
        *,
        decision: EntryDecision,
        entry_time: datetime,
        planned_exit_round: datetime,
        entry_slippage_bps: Decimal | None = None,
    ) -> PaperPosition:
        if not decision.selected or decision.short_exchange is None or decision.long_exchange is None:
            raise ValueError("decision must be selected before opening a position")
        if planned_exit_round <= decision.funding_round:
            raise ValueError("planned_exit_round must be after entry_round")
        if any(
            position.pair == decision.pair and position.entry_round == decision.funding_round
            for position in self.positions.values()
        ):
            raise ValueError("position for pair and entry_round already exists")

        position = PaperPosition(
            position_id=str(uuid4()),
            run_id=self.run.run_id,
            strategy=self.run.strategy,
            state=PositionState.OPEN,
            pair=decision.pair,
            short_exchange=decision.short_exchange,
            long_exchange=decision.long_exchange,
            entry_round=decision.funding_round,
            planned_exit_round=planned_exit_round,
            actual_exit_round=None,
            entry_time=entry_time,
            exit_time=None,
            entry_safe_score=decision.safe_score or Decimal("0"),
            entry_risky_score=decision.risky_score or Decimal("0"),
            entry_signed_spread_bps=decision.signed_spread_bps or Decimal("0"),
            entry_reason_code="selected",
            notional=self.run.current_equity * self.run.notional_pct,
            slippage_bps=entry_slippage_bps,
            equity_before=self.run.current_equity,
        )
        self.positions[position.position_id] = position
        return position

    def settle_round(
        self,
        *,
        position_id: str,
        funding_round: datetime,
        bybit_funding_rate_bps: Decimal | None,
        bitget_funding_rate_bps: Decimal | None,
        exit_slippage_bps: Decimal | None = None,
    ) -> PaperPosition:
        position = self.positions[position_id]
        if position.state is not PositionState.OPEN:
            raise ValueError("can only settle open positions")
        self._validate_settlement_round(position, funding_round)

        if bybit_funding_rate_bps is None or bitget_funding_rate_bps is None:
            position.state = PositionState.SETTLEMENT_ERROR
            position.close_reason = "settlement_error"
            position.actual_exit_round = funding_round
            position.exit_time = funding_round
            position.rounds.append(
                PaperPositionRound(
                    funding_round=funding_round,
                    round_no=position.rounds_collected + 1,
                    bybit_funding_rate_bps=bybit_funding_rate_bps,
                    bitget_funding_rate_bps=bitget_funding_rate_bps,
                    realized_round_gross_bps=None,
                    settlement_evaluable=False,
                    reason_code="missing_settlement_funding",
                )
            )
            return position

        realized = (
            bybit_funding_rate_bps - bitget_funding_rate_bps
            if position.short_exchange == "bybit"
            else bitget_funding_rate_bps - bybit_funding_rate_bps
        )
        position.rounds.append(
            PaperPositionRound(
                funding_round=funding_round,
                round_no=position.rounds_collected + 1,
                bybit_funding_rate_bps=bybit_funding_rate_bps,
                bitget_funding_rate_bps=bitget_funding_rate_bps,
                realized_round_gross_bps=realized,
                settlement_evaluable=True,
                reason_code="settled",
            )
        )
        position.rounds_collected += 1
        if position.rounds_collected == 3:
            self._close_completed(position, funding_round, exit_slippage_bps=exit_slippage_bps)
        return position

    def _close_completed(
        self,
        position: PaperPosition,
        funding_round: datetime,
        *,
        exit_slippage_bps: Decimal | None,
    ) -> None:
        gross_bps = sum((round_.realized_round_gross_bps or Decimal("0")) for round_ in position.rounds)
        bybit_fee_bps = self.run.bybit_taker_fee_bps * Decimal("2")
        bitget_fee_bps = self.run.bitget_taker_fee_bps * Decimal("2")
        fee_bps = bybit_fee_bps + bitget_fee_bps
        entry_slippage_bps = position.slippage_bps
        fallback_phase_slippage_bps = self.run.slippage_bps / Decimal("2")
        if entry_slippage_bps is None and exit_slippage_bps is None:
            slippage_bps = self.run.slippage_bps
        elif entry_slippage_bps is None:
            slippage_bps = fallback_phase_slippage_bps + (exit_slippage_bps or Decimal("0"))
        elif exit_slippage_bps is None:
            slippage_bps = entry_slippage_bps + fallback_phase_slippage_bps
        else:
            slippage_bps = entry_slippage_bps + exit_slippage_bps
        net_bps = gross_bps - fee_bps - slippage_bps
        gross_pnl = position.notional * gross_bps / Decimal("10000")
        fee_pnl = -(position.notional * fee_bps / Decimal("10000"))
        slippage_pnl = -(position.notional * slippage_bps / Decimal("10000"))
        net_pnl = gross_pnl + fee_pnl + slippage_pnl

        position.state = PositionState.CLOSED
        position.actual_exit_round = funding_round
        position.exit_time = funding_round
        position.close_reason = "completed_three_rounds"
        position.gross_bps = gross_bps
        position.fee_bps = fee_bps
        position.slippage_bps = slippage_bps
        position.net_bps = net_bps
        position.gross_pnl = gross_pnl
        position.fee_pnl = fee_pnl
        position.slippage_pnl = slippage_pnl
        position.net_pnl = net_pnl
        position.equity_after = self.run.current_equity + net_pnl

        prior_peak = self.run.peak_equity
        self.run.current_equity = position.equity_after
        self.run.peak_equity = max(prior_peak, self.run.current_equity)
        if self.run.peak_equity > 0:
            drawdown_pct = (self.run.peak_equity - self.run.current_equity) / self.run.peak_equity * Decimal("100")
            self.run.max_drawdown_pct = max(self.run.max_drawdown_pct, drawdown_pct)

        self.trades.append(
            PaperTrade(
                trade_id=str(uuid4()),
                run_id=self.run.run_id,
                position_id=position.position_id,
                strategy=position.strategy,
                pair=position.pair,
                short_exchange=position.short_exchange,
                long_exchange=position.long_exchange,
                entry_round=position.entry_round,
                exit_round=funding_round,
                entry_time=position.entry_time,
                exit_time=funding_round,
                rounds_held=3,
                entry_safe_score=position.entry_safe_score,
                entry_risky_score=position.entry_risky_score,
                notional=position.notional,
                gross_bps=gross_bps,
                bybit_fee_bps=bybit_fee_bps,
                bitget_fee_bps=bitget_fee_bps,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                net_bps=net_bps,
                gross_pnl=gross_pnl,
                fee_pnl=fee_pnl,
                slippage_pnl=slippage_pnl,
                net_pnl=net_pnl,
                equity_before=position.equity_before,
                equity_after=position.equity_after,
                close_reason="completed_three_rounds",
            )
        )

    def _validate_settlement_round(self, position: PaperPosition, funding_round: datetime) -> None:
        if funding_round < position.entry_round:
            raise ValueError("funding_round must not be before entry_round")
        if funding_round > position.planned_exit_round:
            raise ValueError("funding_round must not be after planned_exit_round")
        if position.rounds and funding_round <= position.rounds[-1].funding_round:
            raise ValueError("funding_round must be strictly increasing")
