from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .contracts import EntryDecision, FeatureSnapshot, FundingRoundSnapshot, Pair
from .feature_store import FeatureBuilder
from .rules import RuleEvaluator
from .scheduler import FundingDecision, RoundScheduler
from .scoring import LogisticArtifact, compute_scores


@dataclass(frozen=True)
class SingleCycleInput:
    now_utc: datetime
    pair: Pair
    bybit_snapshot: FundingRoundSnapshot
    bitget_snapshot: FundingRoundSnapshot
    lag1_abs_spread_bps: Decimal | None
    rolling3_mean_abs_spread_bps: Decimal | None
    risky_artifact: LogisticArtifact
    safe_artifact: LogisticArtifact
    has_open_position: bool


@dataclass(frozen=True)
class SingleCycleResult:
    funding_decision: FundingDecision
    feature: FeatureSnapshot
    decision: EntryDecision


@dataclass(frozen=True)
class SingleCycleOrchestrator:
    scheduler: RoundScheduler
    feature_builder: FeatureBuilder
    rule_evaluator: RuleEvaluator

    def evaluate(self, inputs: SingleCycleInput) -> SingleCycleResult:
        funding_decision = self.scheduler.next_decision(inputs.now_utc)
        self._validate_inputs(inputs, funding_decision)
        feature = self.feature_builder.build(
            funding_round=funding_decision.funding_round,
            pair=inputs.pair,
            bybit_snapshot=inputs.bybit_snapshot,
            bitget_snapshot=inputs.bitget_snapshot,
            lag1_abs_spread_bps=inputs.lag1_abs_spread_bps,
            rolling3_mean_abs_spread_bps=inputs.rolling3_mean_abs_spread_bps,
        )
        if feature.entry_evaluable:
            feature = compute_scores(
                feature,
                risky_artifact=inputs.risky_artifact,
                safe_artifact=inputs.safe_artifact,
            )
        decision = self.rule_evaluator.evaluate_entry(
            feature,
            has_open_position=inputs.has_open_position,
        )
        return SingleCycleResult(
            funding_decision=funding_decision,
            feature=feature,
            decision=decision,
        )

    def _validate_inputs(self, inputs: SingleCycleInput, funding_decision: FundingDecision) -> None:
        if inputs.bybit_snapshot.exchange != "bybit":
            raise ValueError("bybit_snapshot.exchange must be 'bybit'")
        if inputs.bitget_snapshot.exchange != "bitget":
            raise ValueError("bitget_snapshot.exchange must be 'bitget'")
        if inputs.bybit_snapshot.pair != inputs.pair:
            raise ValueError("bybit_snapshot.pair must match input pair")
        if inputs.bitget_snapshot.pair != inputs.pair:
            raise ValueError("bitget_snapshot.pair must match input pair")
        if inputs.bybit_snapshot.funding_round != funding_decision.funding_round:
            raise ValueError("bybit_snapshot.funding_round must match scheduler funding_round")
        if inputs.bitget_snapshot.funding_round != funding_decision.funding_round:
            raise ValueError("bitget_snapshot.funding_round must match scheduler funding_round")
        if inputs.bybit_snapshot.decision_cutoff != funding_decision.decision_cutoff:
            raise ValueError("bybit_snapshot.decision_cutoff must match scheduler decision_cutoff")
        if inputs.bitget_snapshot.decision_cutoff != funding_decision.decision_cutoff:
            raise ValueError("bitget_snapshot.decision_cutoff must match scheduler decision_cutoff")


def build_default_orchestrator() -> SingleCycleOrchestrator:
    return SingleCycleOrchestrator(
        scheduler=RoundScheduler(),
        feature_builder=FeatureBuilder(),
        rule_evaluator=RuleEvaluator(),
    )


def build_artifact_backed_orchestrator(
    *,
    risky_artifact: LogisticArtifact,
    safe_artifact: LogisticArtifact,
) -> SingleCycleOrchestrator:
    return SingleCycleOrchestrator(
        scheduler=RoundScheduler(),
        feature_builder=FeatureBuilder(),
        rule_evaluator=RuleEvaluator.from_artifacts(
            risky_artifact=risky_artifact,
            safe_artifact=safe_artifact,
        ),
    )
