from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from papertrade.trading_logic.contracts import FeatureSnapshot, Pair
from papertrade.trading_logic.scoring import LogisticArtifact, compute_scores, load_artifact_pair


class ScoringTests(unittest.TestCase):
    def test_compute_scores_populates_feature_snapshot(self) -> None:
        feature = FeatureSnapshot(
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
            strategy="hybrid_aggressive_safe_valid",
            pair=Pair("BTC", "USDT"),
            entry_evaluable=True,
            reason_code="ok",
            current_abs_funding_spread_bps=Decimal("2"),
            rolling3_mean_abs_funding_spread_bps=Decimal("1"),
            lag1_current_abs_funding_spread_bps=Decimal("1.5"),
            bybit_premium_bps=Decimal("1"),
            premium_abs_gap_bps=Decimal("2"),
            bitget_futures_premium_bps=Decimal("0.5"),
            bybit_open_interest=Decimal("100"),
            oi_gap=Decimal("10"),
            oi_total=Decimal("200"),
            book_imbalance_abs_gap=Decimal("0.4"),
            bybit_liquidation_amount_8h=Decimal("0"),
        )
        risky = LogisticArtifact.from_dict(
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
        safe = LogisticArtifact.from_dict(
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
                    "bybit_liquidation_amount_8h": "1",
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
        scored = compute_scores(feature, risky_artifact=risky, safe_artifact=safe)
        self.assertIsNotNone(scored.risky_score)
        self.assertIsNotNone(scored.safe_score)
        self.assertIsNotNone(scored.risky_logit)
        self.assertIsNotNone(scored.safe_logit)

    def test_load_artifact_pair_reads_json_files(self) -> None:
        risky_payload = {
            "name": "risky",
            "feature_order": ["current_abs_funding_spread_bps"],
            "means": {"current_abs_funding_spread_bps": "0"},
            "stds": {"current_abs_funding_spread_bps": "1"},
            "weights": {"current_abs_funding_spread_bps": "1"},
            "bias": "0",
            "threshold": "0.2",
        }
        safe_payload = {
            "name": "safe",
            "feature_order": ["bybit_premium_bps"],
            "means": {"bybit_premium_bps": "0"},
            "stds": {"bybit_premium_bps": "1"},
            "weights": {"bybit_premium_bps": "1"},
            "bias": "0",
            "threshold": "0.3",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            risky_path = Path(tmpdir) / "risky.json"
            safe_path = Path(tmpdir) / "safe.json"
            risky_path.write_text(json.dumps(risky_payload), encoding="utf-8")
            safe_path.write_text(json.dumps(safe_payload), encoding="utf-8")

            risky, safe = load_artifact_pair(
                risky_artifact_path=risky_path,
                safe_artifact_path=safe_path,
            )

        self.assertEqual(risky.name, "risky")
        self.assertEqual(risky.threshold, Decimal("0.2"))
        self.assertEqual(safe.name, "safe")
        self.assertEqual(safe.threshold, Decimal("0.3"))

