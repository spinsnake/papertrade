from __future__ import annotations

from datetime import datetime, timezone
import math
from decimal import Decimal
from pathlib import Path
import unittest

from papertrade.trading_logic.contracts import FeatureSnapshot, Pair
from papertrade.trading_logic.rules import RuleEvaluator
from papertrade.trading_logic.scoring import compute_scores, load_artifact_pair


ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts"


def _feature_snapshot(**overrides) -> FeatureSnapshot:
    payload = {
        "funding_round": datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
        "strategy": "hybrid_aggressive_safe_valid",
        "pair": Pair("BTC", "USDT"),
        "entry_evaluable": True,
        "reason_code": "ok",
        "current_abs_funding_spread_bps": Decimal("0.970875"),
        "rolling3_mean_abs_funding_spread_bps": Decimal("0.923620"),
        "lag1_current_abs_funding_spread_bps": Decimal("0.928912"),
        "bybit_premium_bps": Decimal("4.048322"),
        "bitget_futures_premium_bps": Decimal("-3.530992"),
        "premium_abs_gap_bps": Decimal("15.913475"),
        "bybit_open_interest": Decimal("298776104.842857"),
        "bitget_open_interest": Decimal("77387309.393428"),
        "oi_gap": Decimal("221516152.646429"),
        "oi_total": Decimal("376036057.039286"),
        "book_imbalance_abs_gap": Decimal("0.788573"),
        "bybit_liquidation_amount_8h": Decimal("33502.832143"),
        "signed_spread_bps": Decimal("0.970875"),
    }
    payload.update(overrides)
    return FeatureSnapshot(**payload)


def _sigmoid(value: Decimal) -> Decimal:
    return Decimal(str(1.0 / (1.0 + math.exp(-float(value)))))


class ResearchArtifactTests(unittest.TestCase):
    def test_artifacts_match_documented_mean_point_scores(self) -> None:
        risky_artifact, safe_artifact = load_artifact_pair(
            risky_artifact_path=ARTIFACT_DIR / "risky.json",
            safe_artifact_path=ARTIFACT_DIR / "safe.json",
        )
        feature = _feature_snapshot()

        result = compute_scores(feature, risky_artifact=risky_artifact, safe_artifact=safe_artifact)

        expected_risky = _sigmoid(Decimal("-5.092596"))
        expected_safe = _sigmoid(Decimal("-1.734095"))
        self.assertAlmostEqual(float(result.risky_score), float(expected_risky), places=12)
        self.assertAlmostEqual(float(result.safe_score), float(expected_safe), places=12)
        self.assertAlmostEqual(float(result.risky_score), 0.006104559860958465, places=12)
        self.assertAlmostEqual(float(result.safe_score), 0.15006453349073862, places=12)

    def test_artifacts_select_documented_high_conviction_vector(self) -> None:
        risky_artifact, safe_artifact = load_artifact_pair(
            risky_artifact_path=ARTIFACT_DIR / "risky.json",
            safe_artifact_path=ARTIFACT_DIR / "safe.json",
        )
        feature = _feature_snapshot(
            current_abs_funding_spread_bps=Decimal("11.090448"),
            rolling3_mean_abs_funding_spread_bps=Decimal("10.487482"),
            lag1_current_abs_funding_spread_bps=Decimal("10.849963"),
            bybit_premium_bps=Decimal("-3.1922400"),
            premium_abs_gap_bps=Decimal("24.5078774"),
            bitget_futures_premium_bps=Decimal("-16.3966744"),
            bybit_open_interest=Decimal("26523681.4694962"),
            oi_gap=Decimal("10571629.4200830"),
            oi_total=Decimal("40669363.0377364"),
            book_imbalance_abs_gap=Decimal("1.0025078"),
            bybit_liquidation_amount_8h=Decimal("8079.9006702"),
            signed_spread_bps=Decimal("11.090448"),
        )

        scored = compute_scores(feature, risky_artifact=risky_artifact, safe_artifact=safe_artifact)
        decision = RuleEvaluator.from_artifacts(
            risky_artifact=risky_artifact,
            safe_artifact=safe_artifact,
        ).evaluate_entry(scored, has_open_position=False)

        expected_risky_logit = Decimal("-5.092596") + Decimal("3") * (
            Decimal("1.213350") + Decimal("0.216117") + Decimal("0.375313")
        )
        expected_safe_logit = (
            Decimal("-1.734095")
            + Decimal("0.4") * (
                Decimal("3.314778")
                + Decimal("3.289779")
                + Decimal("2.326097")
                + Decimal("0.055848")
                + Decimal("0.135742")
                + Decimal("0.005294")
                + Decimal("1.915364")
                + Decimal("1.972222")
            )
        )

        self.assertAlmostEqual(float(scored.risky_logit), float(expected_risky_logit), places=12)
        self.assertAlmostEqual(float(scored.safe_logit), float(expected_safe_logit), places=12)
        self.assertAlmostEqual(float(scored.risky_score), 0.5797492194147379, places=12)
        self.assertAlmostEqual(float(scored.safe_score), 0.9698791718189802, places=12)
        self.assertTrue(decision.selected)
        self.assertEqual(decision.reason_code, "selected")
        self.assertEqual(decision.short_exchange, "bybit")
        self.assertEqual(decision.long_exchange, "bitget")

