from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from .contracts import FeatureSnapshot


def d(value: str | float | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def sigmoid(value: Decimal) -> Decimal:
    as_float = float(value)
    return Decimal(str(1.0 / (1.0 + math.exp(-as_float))))


@dataclass(frozen=True)
class LogisticArtifact:
    name: str
    feature_order: tuple[str, ...]
    means: Mapping[str, Decimal]
    stds: Mapping[str, Decimal]
    weights: Mapping[str, Decimal]
    bias: Decimal
    threshold: Decimal

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "LogisticArtifact":
        return cls(
            name=str(payload["name"]),
            feature_order=tuple(str(item) for item in payload["feature_order"]),
            means={str(k): d(v) for k, v in dict(payload["means"]).items()},
            stds={str(k): d(v) for k, v in dict(payload["stds"]).items()},
            weights={str(k): d(v) for k, v in dict(payload["weights"]).items()},
            bias=d(payload["bias"]),
            threshold=d(payload["threshold"]),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "LogisticArtifact":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(payload)

    def compute(self, features: Mapping[str, Decimal]) -> tuple[Decimal, Decimal]:
        logit = self.bias
        for name in self.feature_order:
            value = features[name]
            z = (value - self.means[name]) / self.stds[name]
            logit += self.weights[name] * z
        return logit, sigmoid(logit)


def compute_scores(
    feature: FeatureSnapshot,
    *,
    risky_artifact: LogisticArtifact,
    safe_artifact: LogisticArtifact,
) -> FeatureSnapshot:
    risky_logit, risky_score = risky_artifact.compute(feature.values_for(list(risky_artifact.feature_order)))
    safe_logit, safe_score = safe_artifact.compute(feature.values_for(list(safe_artifact.feature_order)))
    feature.risky_logit = risky_logit
    feature.risky_score = risky_score
    feature.safe_logit = safe_logit
    feature.safe_score = safe_score
    return feature
