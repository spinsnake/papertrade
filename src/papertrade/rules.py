from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .contracts import EntryDecision, FeatureSnapshot
from .scoring import LogisticArtifact


SAFE_THRESHOLD = Decimal("0.151704")
RISKY_THRESHOLD = Decimal("0.2071180075")


def direction_from_spread(signed_spread_bps: Decimal) -> tuple[str, str]:
    if signed_spread_bps >= 0:
        return "bybit", "bitget"
    return "bitget", "bybit"


@dataclass(frozen=True)
class RuleEvaluator:
    safe_threshold: Decimal = SAFE_THRESHOLD
    risky_threshold: Decimal = RISKY_THRESHOLD

    @classmethod
    def from_artifacts(
        cls,
        *,
        risky_artifact: LogisticArtifact,
        safe_artifact: LogisticArtifact,
    ) -> "RuleEvaluator":
        return cls(
            safe_threshold=safe_artifact.threshold,
            risky_threshold=risky_artifact.threshold,
        )

    def evaluate_entry(self, feature: FeatureSnapshot, has_open_position: bool) -> EntryDecision:
        if has_open_position:
            return self._decision(feature, False, "position_already_open", None, None)
        if not feature.entry_evaluable:
            return self._decision(feature, False, feature.reason_code, None, None)
        if feature.safe_score is None or feature.risky_score is None or feature.signed_spread_bps is None:
            return self._decision(feature, False, "missing_score", None, None)

        safe_ok = feature.safe_score >= self.safe_threshold
        risky_ok = feature.risky_score >= self.risky_threshold
        if safe_ok and risky_ok:
            short_exchange, long_exchange = direction_from_spread(feature.signed_spread_bps)
            return self._decision(feature, True, "selected", short_exchange, long_exchange)
        if safe_ok:
            return self._decision(feature, False, "below_risky_threshold", None, None)
        if risky_ok:
            return self._decision(feature, False, "below_safe_threshold", None, None)
        return self._decision(feature, False, "below_both_threshold", None, None)

    def _decision(
        self,
        feature: FeatureSnapshot,
        selected: bool,
        reason_code: str,
        short_exchange: str | None,
        long_exchange: str | None,
    ) -> EntryDecision:
        feature.reason_code = reason_code
        feature.selected = selected
        feature.suggested_short_exchange = short_exchange
        feature.suggested_long_exchange = long_exchange
        return EntryDecision(
            funding_round=feature.funding_round,
            pair=feature.pair,
            selected=selected,
            reason_code=reason_code,
            short_exchange=short_exchange,
            long_exchange=long_exchange,
            safe_score=feature.safe_score,
            risky_score=feature.risky_score,
            signed_spread_bps=feature.signed_spread_bps,
        )
