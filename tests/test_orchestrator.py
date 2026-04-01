from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from papertrade.contracts import FundingRoundSnapshot, Pair
from papertrade.orchestrator import SingleCycleInput, build_default_orchestrator
from papertrade.scoring import LogisticArtifact


def make_risky_artifact() -> LogisticArtifact:
    return LogisticArtifact.from_dict(
        {
            "name": "risky",
            "feature_order": [
                "current_abs_funding_spread_bps",
                "rolling3_mean_abs_funding_spread_bps",
                "lag1_current_abs_funding_spread_bps",
            ],
            "means": {
                "current_abs_funding_spread_bps": "0",
                "rolling3_mean_abs_funding_spread_bps": "0",
                "lag1_current_abs_funding_spread_bps": "0",
            },
            "stds": {
                "current_abs_funding_spread_bps": "1",
                "rolling3_mean_abs_funding_spread_bps": "1",
                "lag1_current_abs_funding_spread_bps": "1",
            },
            "weights": {
                "current_abs_funding_spread_bps": "1",
                "rolling3_mean_abs_funding_spread_bps": "1",
                "lag1_current_abs_funding_spread_bps": "1",
            },
            "bias": "0",
            "threshold": "0.5",
        }
    )


def make_safe_artifact() -> LogisticArtifact:
    return LogisticArtifact.from_dict(
        {
            "name": "safe",
            "feature_order": [
                "bybit_premium_bps",
                "premium_abs_gap_bps",
                "bitget_futures_premium_bps",
                "bybit_open_interest",
                "oi_gap",
                "oi_total",
                "book_imbalance_abs_gap",
                "bybit_liquidation_amount_8h",
            ],
            "means": {
                "bybit_premium_bps": "0",
                "premium_abs_gap_bps": "0",
                "bitget_futures_premium_bps": "0",
                "bybit_open_interest": "0",
                "oi_gap": "0",
                "oi_total": "0",
                "book_imbalance_abs_gap": "0",
                "bybit_liquidation_amount_8h": "0",
            },
            "stds": {
                "bybit_premium_bps": "1",
                "premium_abs_gap_bps": "1",
                "bitget_futures_premium_bps": "1",
                "bybit_open_interest": "100",
                "oi_gap": "10",
                "oi_total": "100",
                "book_imbalance_abs_gap": "1",
                "bybit_liquidation_amount_8h": "1",
            },
            "weights": {
                "bybit_premium_bps": "1",
                "premium_abs_gap_bps": "1",
                "bitget_futures_premium_bps": "1",
                "bybit_open_interest": "1",
                "oi_gap": "1",
                "oi_total": "1",
                "book_imbalance_abs_gap": "1",
                "bybit_liquidation_amount_8h": "1",
            },
            "bias": "0",
            "threshold": "0.5",
        }
    )


def make_snapshot(
    exchange: str,
    *,
    pair: Pair | None = None,
    funding_round: datetime | None = None,
    decision_cutoff: datetime | None = None,
    funding_rate_bps: str,
    mark_price: str,
    open_interest: str,
    book_imbalance: str,
) -> FundingRoundSnapshot:
    if pair is None:
        pair = Pair("BTC", "USDT")
    if funding_round is None:
        funding_round = datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc)
    if decision_cutoff is None:
        decision_cutoff = datetime(2025, 1, 11, 7, 59, 30, tzinfo=timezone.utc)
    return FundingRoundSnapshot(
        funding_round=funding_round,
        decision_cutoff=decision_cutoff,
        exchange=exchange,
        pair=pair,
        market_state_observed_at=funding_round,
        orderbook_observed_at=funding_round,
        funding_rate_bps=Decimal(funding_rate_bps),
        mark_price=Decimal(mark_price),
        index_price=Decimal("100"),
        open_interest=Decimal(open_interest),
        bid_price=Decimal("100"),
        ask_price=Decimal("101"),
        bid_amount=Decimal("1"),
        ask_amount=Decimal("1"),
        book_imbalance=Decimal(book_imbalance),
        liquidation_amount_8h=Decimal("0"),
        liquidation_complete=True,
        snapshot_valid=True,
        reason_code="ok",
    )


def make_input(**overrides: object) -> SingleCycleInput:
    pair = overrides.pop("pair", Pair("BTC", "USDT"))
    bybit_snapshot = overrides.pop(
        "bybit_snapshot",
        make_snapshot(
            "bybit",
            pair=pair,
            funding_rate_bps="5",
            mark_price="101",
            open_interest="100",
            book_imbalance="0.2",
        ),
    )
    bitget_snapshot = overrides.pop(
        "bitget_snapshot",
        make_snapshot(
            "bitget",
            pair=pair,
            funding_rate_bps="2",
            mark_price="100.5",
            open_interest="90",
            book_imbalance="0.1",
        ),
    )
    data: dict[str, object] = {
        "now_utc": datetime(2025, 1, 11, 7, 0, tzinfo=timezone.utc),
        "pair": pair,
        "bybit_snapshot": bybit_snapshot,
        "bitget_snapshot": bitget_snapshot,
        "lag1_abs_spread_bps": Decimal("1"),
        "rolling3_mean_abs_spread_bps": Decimal("1"),
        "risky_artifact": make_risky_artifact(),
        "safe_artifact": make_safe_artifact(),
        "has_open_position": False,
    }
    data.update(overrides)
    return SingleCycleInput(**data)


class OrchestratorTests(unittest.TestCase):
    def test_evaluate_scores_and_returns_selected_decision(self) -> None:
        result = build_default_orchestrator().evaluate(make_input())

        self.assertTrue(result.feature.entry_evaluable)
        self.assertIsNotNone(result.feature.safe_score)
        self.assertIsNotNone(result.feature.risky_score)
        self.assertTrue(result.decision.selected)
        self.assertEqual(result.decision.reason_code, "selected")

    def test_evaluate_skips_scoring_when_feature_not_evaluable(self) -> None:
        result = build_default_orchestrator().evaluate(
            make_input(lag1_abs_spread_bps=None)
        )

        self.assertFalse(result.feature.entry_evaluable)
        self.assertEqual(result.feature.reason_code, "missing_lag_history")
        self.assertIsNone(result.feature.safe_score)
        self.assertIsNone(result.feature.risky_score)
        self.assertFalse(result.decision.selected)
        self.assertEqual(result.decision.reason_code, "missing_lag_history")

    def test_evaluate_returns_position_already_open_when_position_exists(self) -> None:
        result = build_default_orchestrator().evaluate(
            make_input(has_open_position=True)
        )

        self.assertFalse(result.decision.selected)
        self.assertEqual(result.decision.reason_code, "position_already_open")

    def test_evaluate_rejects_pair_mismatch(self) -> None:
        result_pair = Pair("BTC", "USDT")
        snapshot_pair = Pair("ETH", "USDT")

        with self.assertRaisesRegex(ValueError, "bybit_snapshot.pair must match input pair"):
            build_default_orchestrator().evaluate(
                make_input(
                    pair=result_pair,
                    bybit_snapshot=make_snapshot(
                        "bybit",
                        pair=snapshot_pair,
                        funding_rate_bps="5",
                        mark_price="101",
                        open_interest="100",
                        book_imbalance="0.2",
                    ),
                    bitget_snapshot=make_snapshot(
                        "bitget",
                        pair=snapshot_pair,
                        funding_rate_bps="2",
                        mark_price="100.5",
                        open_interest="90",
                        book_imbalance="0.1",
                    ),
                )
            )

    def test_evaluate_rejects_exchange_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "bybit_snapshot.exchange must be 'bybit'"):
            build_default_orchestrator().evaluate(
                make_input(
                    bybit_snapshot=make_snapshot(
                        "bitget",
                        funding_rate_bps="5",
                        mark_price="101",
                        open_interest="100",
                        book_imbalance="0.2",
                    ),
                )
            )

    def test_evaluate_rejects_round_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "bybit_snapshot.funding_round must match scheduler funding_round"):
            build_default_orchestrator().evaluate(
                make_input(
                    bybit_snapshot=make_snapshot(
                        "bybit",
                        funding_round=datetime(2025, 1, 10, 16, 0, tzinfo=timezone.utc),
                        decision_cutoff=datetime(2025, 1, 10, 15, 59, 30, tzinfo=timezone.utc),
                        funding_rate_bps="5",
                        mark_price="101",
                        open_interest="100",
                        book_imbalance="0.2",
                    ),
                )
            )

    def test_evaluate_rejects_decision_cutoff_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "bybit_snapshot.decision_cutoff must match scheduler decision_cutoff"):
            build_default_orchestrator().evaluate(
                make_input(
                    bybit_snapshot=make_snapshot(
                        "bybit",
                        decision_cutoff=datetime(2025, 1, 11, 7, 59, 0, tzinfo=timezone.utc),
                        funding_rate_bps="5",
                        mark_price="101",
                        open_interest="100",
                        book_imbalance="0.2",
                    ),
                )
            )
