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

    def has_open_position(self, pair: Pair) -> bool:
        return any(position.pair == pair and position.state is PositionState.OPEN for position in self.positions.values())

    def open_position(
        self,
        *,
        decision: EntryDecision,
        entry_time: datetime,
        planned_exit_round: datetime,
    ) -> PaperPosition:
        if not decision.selected or decision.short_exchange is None or decision.long_exchange is None:
            raise ValueError("decision must be selected before opening a position")

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
    ) -> PaperPosition:
        position = self.positions[position_id]
        if position.state is not PositionState.OPEN:
            raise ValueError("can only settle open positions")

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
            self._close_completed(position, funding_round)
        return position

    def _close_completed(self, position: PaperPosition, funding_round: datetime) -> None:
        gross_bps = sum((round_.realized_round_gross_bps or Decimal("0")) for round_ in position.rounds)
        fee_bps = self.run.fee_bps
        slippage_bps = self.run.slippage_bps
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

        self.run.current_equity = position.equity_after
        self.run.peak_equity = max(self.run.peak_equity, self.run.current_equity)

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
