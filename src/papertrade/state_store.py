from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .contracts import FeatureSnapshot, Pair, PaperPosition, PaperPositionRound, PaperRun, PaperTrade
from .enums import PositionState, RunStatus


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: object) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _dec(value: object | None) -> Decimal | None:
    if value in {None, ""}:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _bool(value: object) -> bool:
    return bool(int(value)) if isinstance(value, int) else bool(value)


class SQLiteStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def save_run(self, run: PaperRun) -> None:
        query = """
            INSERT INTO paper_runs (
                run_id, strategy, runtime_mode, status, status_reason, report_output_dir,
                report_filename_pattern, started_at, finished_at, initial_equity, current_equity,
                peak_equity, max_drawdown_pct, notional_pct, bybit_taker_fee_bps, bitget_taker_fee_bps, fee_bps, slippage_bps,
                decision_buffer_seconds, market_state_staleness_sec, orderbook_staleness_sec,
                strict_liquidation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                strategy = excluded.strategy,
                runtime_mode = excluded.runtime_mode,
                status = excluded.status,
                status_reason = excluded.status_reason,
                report_output_dir = excluded.report_output_dir,
                report_filename_pattern = excluded.report_filename_pattern,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                initial_equity = excluded.initial_equity,
                current_equity = excluded.current_equity,
                peak_equity = excluded.peak_equity,
                max_drawdown_pct = excluded.max_drawdown_pct,
                notional_pct = excluded.notional_pct,
                bybit_taker_fee_bps = excluded.bybit_taker_fee_bps,
                bitget_taker_fee_bps = excluded.bitget_taker_fee_bps,
                fee_bps = excluded.fee_bps,
                slippage_bps = excluded.slippage_bps,
                decision_buffer_seconds = excluded.decision_buffer_seconds,
                market_state_staleness_sec = excluded.market_state_staleness_sec,
                orderbook_staleness_sec = excluded.orderbook_staleness_sec,
                strict_liquidation = excluded.strict_liquidation
        """
        values = (
            run.run_id,
            run.strategy,
            run.runtime_mode,
            run.status.value,
            run.status_reason,
            run.report_output_dir,
            run.report_filename_pattern,
            _dt(run.started_at),
            _dt(run.finished_at),
            str(run.initial_equity),
            str(run.current_equity),
            str(run.peak_equity),
            str(run.max_drawdown_pct),
            str(run.notional_pct),
            str(run.bybit_taker_fee_bps),
            str(run.bitget_taker_fee_bps),
            str(run.fee_bps),
            str(run.slippage_bps),
            run.decision_buffer_seconds,
            run.market_state_staleness_sec,
            run.orderbook_staleness_sec,
            int(run.strict_liquidation),
        )
        with closing(self._connect()) as connection:
            connection.execute(query, values)
            connection.commit()

    def load_run(self, run_id: str) -> PaperRun | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM paper_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return self._run_from_row(row)

    def load_latest_resumable_run(self, *, strategy: str, runtime_mode: str) -> PaperRun | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM paper_runs
                WHERE strategy = ? AND runtime_mode = ? AND status IN ('running', 'failed')
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (strategy, runtime_mode),
            ).fetchone()
        if row is None:
            return None
        return self._run_from_row(row)

    def replace_feature_snapshots(self, features: Iterable[FeatureSnapshot]) -> None:
        rows = list(features)
        if not rows:
            return
        query = """
            INSERT INTO feature_snapshots (
                funding_round, strategy, base, quote, symbol, entry_evaluable, reason_code,
                current_abs_funding_spread_bps, rolling3_mean_abs_funding_spread_bps,
                lag1_current_abs_funding_spread_bps, bybit_premium_bps, bitget_futures_premium_bps,
                premium_abs_gap_bps, bybit_open_interest, bitget_open_interest, oi_gap, oi_total,
                book_imbalance_abs_gap, bybit_liquidation_amount_8h, signed_spread_bps,
                suggested_short_exchange, suggested_long_exchange, risky_logit, risky_score,
                safe_logit, safe_score, selected
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(strategy, symbol, funding_round) DO UPDATE SET
                entry_evaluable = excluded.entry_evaluable,
                reason_code = excluded.reason_code,
                current_abs_funding_spread_bps = excluded.current_abs_funding_spread_bps,
                rolling3_mean_abs_funding_spread_bps = excluded.rolling3_mean_abs_funding_spread_bps,
                lag1_current_abs_funding_spread_bps = excluded.lag1_current_abs_funding_spread_bps,
                bybit_premium_bps = excluded.bybit_premium_bps,
                bitget_futures_premium_bps = excluded.bitget_futures_premium_bps,
                premium_abs_gap_bps = excluded.premium_abs_gap_bps,
                bybit_open_interest = excluded.bybit_open_interest,
                bitget_open_interest = excluded.bitget_open_interest,
                oi_gap = excluded.oi_gap,
                oi_total = excluded.oi_total,
                book_imbalance_abs_gap = excluded.book_imbalance_abs_gap,
                bybit_liquidation_amount_8h = excluded.bybit_liquidation_amount_8h,
                signed_spread_bps = excluded.signed_spread_bps,
                suggested_short_exchange = excluded.suggested_short_exchange,
                suggested_long_exchange = excluded.suggested_long_exchange,
                risky_logit = excluded.risky_logit,
                risky_score = excluded.risky_score,
                safe_logit = excluded.safe_logit,
                safe_score = excluded.safe_score,
                selected = excluded.selected
        """
        values = [
            (
                _dt(feature.funding_round),
                feature.strategy,
                feature.pair.base,
                feature.pair.quote,
                feature.pair.symbol,
                int(feature.entry_evaluable),
                feature.reason_code,
                _str_or_none(feature.current_abs_funding_spread_bps),
                _str_or_none(feature.rolling3_mean_abs_funding_spread_bps),
                _str_or_none(feature.lag1_current_abs_funding_spread_bps),
                _str_or_none(feature.bybit_premium_bps),
                _str_or_none(feature.bitget_futures_premium_bps),
                _str_or_none(feature.premium_abs_gap_bps),
                _str_or_none(feature.bybit_open_interest),
                _str_or_none(feature.bitget_open_interest),
                _str_or_none(feature.oi_gap),
                _str_or_none(feature.oi_total),
                _str_or_none(feature.book_imbalance_abs_gap),
                _str_or_none(feature.bybit_liquidation_amount_8h),
                _str_or_none(feature.signed_spread_bps),
                feature.suggested_short_exchange,
                feature.suggested_long_exchange,
                _str_or_none(feature.risky_logit),
                _str_or_none(feature.risky_score),
                _str_or_none(feature.safe_logit),
                _str_or_none(feature.safe_score),
                int(feature.selected),
            )
            for feature in rows
        ]
        with closing(self._connect()) as connection:
            connection.executemany(query, values)
            connection.commit()

    def replace_portfolio_state(
        self,
        *,
        run_id: str,
        positions: Iterable[PaperPosition],
        trades: Iterable[PaperTrade],
    ) -> None:
        positions_list = list(positions)
        trades_list = list(trades)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                DELETE FROM paper_position_rounds
                WHERE position_id IN (SELECT position_id FROM paper_positions WHERE run_id = ?)
                """,
                (run_id,),
            )
            connection.execute("DELETE FROM paper_positions WHERE run_id = ?", (run_id,))
            connection.execute("DELETE FROM paper_trades WHERE run_id = ?", (run_id,))

            for position in positions_list:
                connection.execute(
                    """
                    INSERT INTO paper_positions (
                        position_id, run_id, strategy, state, base, quote, symbol, short_exchange,
                        long_exchange, entry_round, planned_exit_round, actual_exit_round, entry_time,
                        exit_time, entry_safe_score, entry_risky_score, entry_signed_spread_bps,
                        entry_reason_code, notional, rounds_collected, gross_bps, fee_bps, slippage_bps,
                        net_bps, gross_pnl, fee_pnl, slippage_pnl, net_pnl, equity_before, equity_after,
                        close_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        position.position_id,
                        position.run_id,
                        position.strategy,
                        position.state.value,
                        position.pair.base,
                        position.pair.quote,
                        position.pair.symbol,
                        position.short_exchange,
                        position.long_exchange,
                        _dt(position.entry_round),
                        _dt(position.planned_exit_round),
                        _dt(position.actual_exit_round),
                        _dt(position.entry_time),
                        _dt(position.exit_time),
                        str(position.entry_safe_score),
                        str(position.entry_risky_score),
                        str(position.entry_signed_spread_bps),
                        position.entry_reason_code,
                        str(position.notional),
                        position.rounds_collected,
                        _str_or_none(position.gross_bps),
                        _str_or_none(position.fee_bps),
                        _str_or_none(position.slippage_bps),
                        _str_or_none(position.net_bps),
                        _str_or_none(position.gross_pnl),
                        _str_or_none(position.fee_pnl),
                        _str_or_none(position.slippage_pnl),
                        _str_or_none(position.net_pnl),
                        str(position.equity_before),
                        _str_or_none(position.equity_after),
                        position.close_reason,
                    ),
                )
                for round_ in position.rounds:
                    connection.execute(
                        """
                        INSERT INTO paper_position_rounds (
                            position_id, funding_round, round_no, bybit_funding_rate_bps,
                            bitget_funding_rate_bps, realized_round_gross_bps, settlement_evaluable,
                            reason_code
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            position.position_id,
                            _dt(round_.funding_round),
                            round_.round_no,
                            _str_or_none(round_.bybit_funding_rate_bps),
                            _str_or_none(round_.bitget_funding_rate_bps),
                            _str_or_none(round_.realized_round_gross_bps),
                            int(round_.settlement_evaluable),
                            round_.reason_code,
                        ),
                    )

            for trade in trades_list:
                connection.execute(
                    """
                    INSERT INTO paper_trades (
                        trade_id, run_id, position_id, strategy, base, quote, symbol,
                        short_exchange, long_exchange, entry_round, exit_round, entry_time,
                        exit_time, rounds_held, entry_safe_score, entry_risky_score, notional,
                        gross_bps, fee_bps, slippage_bps, net_bps, gross_pnl, fee_pnl,
                        slippage_pnl, net_pnl, equity_before, equity_after, close_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade.trade_id,
                        trade.run_id,
                        trade.position_id,
                        trade.strategy,
                        trade.pair.base,
                        trade.pair.quote,
                        trade.pair.symbol,
                        trade.short_exchange,
                        trade.long_exchange,
                        _dt(trade.entry_round),
                        _dt(trade.exit_round),
                        _dt(trade.entry_time),
                        _dt(trade.exit_time),
                        trade.rounds_held,
                        str(trade.entry_safe_score),
                        str(trade.entry_risky_score),
                        str(trade.notional),
                        str(trade.gross_bps),
                        str(trade.fee_bps),
                        str(trade.slippage_bps),
                        str(trade.net_bps),
                        str(trade.gross_pnl),
                        str(trade.fee_pnl),
                        str(trade.slippage_pnl),
                        str(trade.net_pnl),
                        str(trade.equity_before),
                        str(trade.equity_after),
                        trade.close_reason,
                    ),
                )
            connection.commit()

    def load_positions(self, run_id: str) -> list[PaperPosition]:
        with closing(self._connect()) as connection:
            position_rows = connection.execute(
                "SELECT * FROM paper_positions WHERE run_id = ? ORDER BY entry_round ASC, position_id ASC",
                (run_id,),
            ).fetchall()
            round_rows = connection.execute(
                """
                SELECT *
                FROM paper_position_rounds
                WHERE position_id IN (SELECT position_id FROM paper_positions WHERE run_id = ?)
                ORDER BY funding_round ASC
                """,
                (run_id,),
            ).fetchall()

        rounds_by_position: dict[str, list[PaperPositionRound]] = {}
        for row in round_rows:
            rounds_by_position.setdefault(str(row["position_id"]), []).append(
                PaperPositionRound(
                    funding_round=_parse_dt(row["funding_round"]),
                    round_no=int(row["round_no"]),
                    bybit_funding_rate_bps=_dec(row["bybit_funding_rate_bps"]),
                    bitget_funding_rate_bps=_dec(row["bitget_funding_rate_bps"]),
                    realized_round_gross_bps=_dec(row["realized_round_gross_bps"]),
                    settlement_evaluable=_bool(row["settlement_evaluable"]),
                    reason_code=str(row["reason_code"]),
                )
            )

        positions: list[PaperPosition] = []
        for row in position_rows:
            positions.append(
                PaperPosition(
                    position_id=str(row["position_id"]),
                    run_id=str(row["run_id"]),
                    strategy=str(row["strategy"]),
                    state=PositionState(str(row["state"])),
                    pair=Pair(base=str(row["base"]), quote=str(row["quote"])),
                    short_exchange=str(row["short_exchange"]),
                    long_exchange=str(row["long_exchange"]),
                    entry_round=_parse_dt(row["entry_round"]),
                    planned_exit_round=_parse_dt(row["planned_exit_round"]),
                    actual_exit_round=_parse_dt(row["actual_exit_round"]),
                    entry_time=_parse_dt(row["entry_time"]),
                    exit_time=_parse_dt(row["exit_time"]),
                    entry_safe_score=_dec(row["entry_safe_score"]) or Decimal("0"),
                    entry_risky_score=_dec(row["entry_risky_score"]) or Decimal("0"),
                    entry_signed_spread_bps=_dec(row["entry_signed_spread_bps"]) or Decimal("0"),
                    entry_reason_code=str(row["entry_reason_code"]),
                    notional=_dec(row["notional"]) or Decimal("0"),
                    rounds_collected=int(row["rounds_collected"]),
                    gross_bps=_dec(row["gross_bps"]),
                    fee_bps=_dec(row["fee_bps"]),
                    slippage_bps=_dec(row["slippage_bps"]),
                    net_bps=_dec(row["net_bps"]),
                    gross_pnl=_dec(row["gross_pnl"]),
                    fee_pnl=_dec(row["fee_pnl"]),
                    slippage_pnl=_dec(row["slippage_pnl"]),
                    net_pnl=_dec(row["net_pnl"]),
                    equity_before=_dec(row["equity_before"]) or Decimal("0"),
                    equity_after=_dec(row["equity_after"]),
                    close_reason=str(row["close_reason"]) if row["close_reason"] is not None else None,
                    rounds=rounds_by_position.get(str(row["position_id"]), []),
                )
            )
        return positions

    def load_trades(self, run_id: str) -> list[PaperTrade]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM paper_trades WHERE run_id = ? ORDER BY entry_round ASC, trade_id ASC",
                (run_id,),
            ).fetchall()
        trades: list[PaperTrade] = []
        for row in rows:
            trades.append(
                PaperTrade(
                    trade_id=str(row["trade_id"]),
                    run_id=str(row["run_id"]),
                    position_id=str(row["position_id"]),
                    strategy=str(row["strategy"]),
                    pair=Pair(base=str(row["base"]), quote=str(row["quote"])),
                    short_exchange=str(row["short_exchange"]),
                    long_exchange=str(row["long_exchange"]),
                    entry_round=_parse_dt(row["entry_round"]),
                    exit_round=_parse_dt(row["exit_round"]),
                    entry_time=_parse_dt(row["entry_time"]),
                    exit_time=_parse_dt(row["exit_time"]),
                    rounds_held=int(row["rounds_held"]),
                    entry_safe_score=_dec(row["entry_safe_score"]) or Decimal("0"),
                    entry_risky_score=_dec(row["entry_risky_score"]) or Decimal("0"),
                    notional=_dec(row["notional"]) or Decimal("0"),
                    gross_bps=_dec(row["gross_bps"]) or Decimal("0"),
                    fee_bps=_dec(row["fee_bps"]) or Decimal("0"),
                    slippage_bps=_dec(row["slippage_bps"]) or Decimal("0"),
                    net_bps=_dec(row["net_bps"]) or Decimal("0"),
                    gross_pnl=_dec(row["gross_pnl"]) or Decimal("0"),
                    fee_pnl=_dec(row["fee_pnl"]) or Decimal("0"),
                    slippage_pnl=_dec(row["slippage_pnl"]) or Decimal("0"),
                    net_pnl=_dec(row["net_pnl"]) or Decimal("0"),
                    equity_before=_dec(row["equity_before"]) or Decimal("0"),
                    equity_after=_dec(row["equity_after"]) or Decimal("0"),
                    close_reason=str(row["close_reason"]),
                )
            )
        return trades

    def record_report(self, *, run_id: str, as_of_round: datetime, report_type: str, report_path: Path) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO paper_reports (run_id, as_of_round, report_type, report_path, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, as_of_round, report_type) DO UPDATE SET
                    report_path = excluded.report_path,
                    created_at = excluded.created_at
                """,
                (run_id, _dt(as_of_round), report_type, str(report_path), _dt(datetime.now(timezone.utc))),
            )
            connection.commit()

    def _migrate(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_runs (
                    run_id TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL,
                    runtime_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    status_reason TEXT NOT NULL,
                    report_output_dir TEXT NOT NULL,
                    report_filename_pattern TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NULL,
                    initial_equity TEXT NOT NULL,
                    current_equity TEXT NOT NULL,
                    peak_equity TEXT NOT NULL,
                    max_drawdown_pct TEXT NOT NULL,
                    notional_pct TEXT NOT NULL,
                    bybit_taker_fee_bps TEXT NULL,
                    bitget_taker_fee_bps TEXT NULL,
                    fee_bps TEXT NOT NULL,
                    slippage_bps TEXT NOT NULL,
                    decision_buffer_seconds INTEGER NOT NULL,
                    market_state_staleness_sec INTEGER NOT NULL,
                    orderbook_staleness_sec INTEGER NOT NULL,
                    strict_liquidation INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS feature_snapshots (
                    funding_round TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    entry_evaluable INTEGER NOT NULL,
                    reason_code TEXT NOT NULL,
                    current_abs_funding_spread_bps TEXT NULL,
                    rolling3_mean_abs_funding_spread_bps TEXT NULL,
                    lag1_current_abs_funding_spread_bps TEXT NULL,
                    bybit_premium_bps TEXT NULL,
                    bitget_futures_premium_bps TEXT NULL,
                    premium_abs_gap_bps TEXT NULL,
                    bybit_open_interest TEXT NULL,
                    bitget_open_interest TEXT NULL,
                    oi_gap TEXT NULL,
                    oi_total TEXT NULL,
                    book_imbalance_abs_gap TEXT NULL,
                    bybit_liquidation_amount_8h TEXT NULL,
                    signed_spread_bps TEXT NULL,
                    suggested_short_exchange TEXT NULL,
                    suggested_long_exchange TEXT NULL,
                    risky_logit TEXT NULL,
                    risky_score TEXT NULL,
                    safe_logit TEXT NULL,
                    safe_score TEXT NULL,
                    selected INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (strategy, symbol, funding_round)
                );

                CREATE TABLE IF NOT EXISTS paper_positions (
                    position_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    state TEXT NOT NULL,
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    short_exchange TEXT NOT NULL,
                    long_exchange TEXT NOT NULL,
                    entry_round TEXT NOT NULL,
                    planned_exit_round TEXT NOT NULL,
                    actual_exit_round TEXT NULL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NULL,
                    entry_safe_score TEXT NOT NULL,
                    entry_risky_score TEXT NOT NULL,
                    entry_signed_spread_bps TEXT NOT NULL,
                    entry_reason_code TEXT NOT NULL,
                    notional TEXT NOT NULL,
                    rounds_collected INTEGER NOT NULL DEFAULT 0,
                    gross_bps TEXT NULL,
                    fee_bps TEXT NULL,
                    slippage_bps TEXT NULL,
                    net_bps TEXT NULL,
                    gross_pnl TEXT NULL,
                    fee_pnl TEXT NULL,
                    slippage_pnl TEXT NULL,
                    net_pnl TEXT NULL,
                    equity_before TEXT NOT NULL,
                    equity_after TEXT NULL,
                    close_reason TEXT NULL,
                    CHECK (
                        (state = 'open' AND close_reason IS NULL)
                        OR (state IN ('closed', 'settlement_error') AND close_reason IS NOT NULL)
                    )
                );

                CREATE TABLE IF NOT EXISTS paper_position_rounds (
                    position_id TEXT NOT NULL,
                    funding_round TEXT NOT NULL,
                    round_no INTEGER NOT NULL,
                    bybit_funding_rate_bps TEXT NULL,
                    bitget_funding_rate_bps TEXT NULL,
                    realized_round_gross_bps TEXT NULL,
                    settlement_evaluable INTEGER NOT NULL,
                    reason_code TEXT NOT NULL,
                    PRIMARY KEY (position_id, funding_round)
                );

                CREATE TABLE IF NOT EXISTS paper_trades (
                    trade_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    position_id TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    base TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    short_exchange TEXT NOT NULL,
                    long_exchange TEXT NOT NULL,
                    entry_round TEXT NOT NULL,
                    exit_round TEXT NOT NULL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    rounds_held INTEGER NOT NULL,
                    entry_safe_score TEXT NOT NULL,
                    entry_risky_score TEXT NOT NULL,
                    notional TEXT NOT NULL,
                    gross_bps TEXT NOT NULL,
                    fee_bps TEXT NOT NULL,
                    slippage_bps TEXT NOT NULL,
                    net_bps TEXT NOT NULL,
                    gross_pnl TEXT NOT NULL,
                    fee_pnl TEXT NOT NULL,
                    slippage_pnl TEXT NOT NULL,
                    net_pnl TEXT NOT NULL,
                    equity_before TEXT NOT NULL,
                    equity_after TEXT NOT NULL,
                    close_reason TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_reports (
                    run_id TEXT NOT NULL,
                    as_of_round TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    report_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, as_of_round, report_type)
                );

                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                """
            )
            self._ensure_column(connection, "paper_runs", "bybit_taker_fee_bps", "TEXT NULL")
            self._ensure_column(connection, "paper_runs", "bitget_taker_fee_bps", "TEXT NULL")
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _run_from_row(self, row: sqlite3.Row) -> PaperRun:
        legacy_fee_bps = _dec(row["fee_bps"]) or Decimal("0")
        bybit_taker_fee_bps = _dec(row["bybit_taker_fee_bps"]) if "bybit_taker_fee_bps" in row.keys() else None
        bitget_taker_fee_bps = _dec(row["bitget_taker_fee_bps"]) if "bitget_taker_fee_bps" in row.keys() else None
        if bybit_taker_fee_bps is None and bitget_taker_fee_bps is None:
            bybit_taker_fee_bps = legacy_fee_bps / Decimal("4")
            bitget_taker_fee_bps = legacy_fee_bps / Decimal("4")
        elif bybit_taker_fee_bps is None or bitget_taker_fee_bps is None:
            fallback_taker_fee_bps = legacy_fee_bps / Decimal("4")
            bybit_taker_fee_bps = bybit_taker_fee_bps or fallback_taker_fee_bps
            bitget_taker_fee_bps = bitget_taker_fee_bps or fallback_taker_fee_bps

        return PaperRun(
            run_id=str(row["run_id"]),
            strategy=str(row["strategy"]),
            runtime_mode=str(row["runtime_mode"]),
            status=RunStatus(str(row["status"])),
            status_reason=str(row["status_reason"]),
            report_output_dir=str(row["report_output_dir"]),
            report_filename_pattern=str(row["report_filename_pattern"]),
            started_at=_parse_dt(row["started_at"]),
            finished_at=_parse_dt(row["finished_at"]),
            initial_equity=_dec(row["initial_equity"]) or Decimal("0"),
            current_equity=_dec(row["current_equity"]) or Decimal("0"),
            peak_equity=_dec(row["peak_equity"]) or Decimal("0"),
            max_drawdown_pct=_dec(row["max_drawdown_pct"]) or Decimal("0"),
            notional_pct=_dec(row["notional_pct"]) or Decimal("0"),
            bybit_taker_fee_bps=bybit_taker_fee_bps,
            bitget_taker_fee_bps=bitget_taker_fee_bps,
            fee_bps=(bybit_taker_fee_bps + bitget_taker_fee_bps) * Decimal("2"),
            slippage_bps=_dec(row["slippage_bps"]) or Decimal("0"),
            decision_buffer_seconds=int(row["decision_buffer_seconds"]),
            market_state_staleness_sec=int(row["market_state_staleness_sec"]),
            orderbook_staleness_sec=int(row["orderbook_staleness_sec"]),
            strict_liquidation=_bool(row["strict_liquidation"]),
        )

    def _ensure_column(self, connection: sqlite3.Connection, table_name: str, column_name: str, column_definition: str) -> None:
        existing_columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in existing_columns:
            return
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def _str_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
