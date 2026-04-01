from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from papertrade.contracts import FeatureSnapshot, Pair
from papertrade.rules import RuleEvaluator
from papertrade.scoring import LogisticArtifact


class RuleEvaluatorTests(unittest.TestCase):
    def test_entry_direction_when_bybit_spread_positive(self) -> None:
        feature = FeatureSnapshot(
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            strategy="hybrid_aggressive_safe_valid",
            pair=Pair("BTC", "USDT"),
            entry_evaluable=True,
            reason_code="ok",
            safe_score=Decimal("0.9"),
            risky_score=Decimal("0.9"),
            signed_spread_bps=Decimal("8"),
        )
        decision = RuleEvaluator().evaluate_entry(feature, has_open_position=False)
        self.assertTrue(decision.selected)
        self.assertEqual(decision.short_exchange, "bybit")
        self.assertEqual(decision.long_exchange, "bitget")

    def test_entry_invalid_when_position_already_open(self) -> None:
        feature = FeatureSnapshot(
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            strategy="hybrid_aggressive_safe_valid",
            pair=Pair("BTC", "USDT"),
            entry_evaluable=True,
            reason_code="ok",
            safe_score=Decimal("0.9"),
            risky_score=Decimal("0.9"),
            signed_spread_bps=Decimal("8"),
        )
        decision = RuleEvaluator().evaluate_entry(feature, has_open_position=True)
        self.assertFalse(decision.selected)
        self.assertEqual(decision.reason_code, "position_already_open")

    def test_thresholds_can_come_from_artifacts(self) -> None:
        feature = FeatureSnapshot(
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            strategy="hybrid_aggressive_safe_valid",
            pair=Pair("BTC", "USDT"),
            entry_evaluable=True,
            reason_code="ok",
            safe_score=Decimal("0.8"),
            risky_score=Decimal("0.8"),
            signed_spread_bps=Decimal("8"),
        )
        risky_artifact = LogisticArtifact.from_dict(
            {
                "name": "risky",
                "feature_order": ["current_abs_funding_spread_bps"],
                "means": {"current_abs_funding_spread_bps": "0"},
                "stds": {"current_abs_funding_spread_bps": "1"},
                "weights": {"current_abs_funding_spread_bps": "1"},
                "bias": "0",
                "threshold": "0.5",
            }
        )
        safe_artifact = LogisticArtifact.from_dict(
            {
                "name": "safe",
                "feature_order": ["bybit_premium_bps"],
                "means": {"bybit_premium_bps": "0"},
                "stds": {"bybit_premium_bps": "1"},
                "weights": {"bybit_premium_bps": "1"},
                "bias": "0",
                "threshold": "0.9",
            }
        )

        decision = RuleEvaluator.from_artifacts(
            risky_artifact=risky_artifact,
            safe_artifact=safe_artifact,
        ).evaluate_entry(feature, has_open_position=False)

        self.assertFalse(decision.selected)
        self.assertEqual(decision.reason_code, "below_safe_threshold")
