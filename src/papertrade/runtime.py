from __future__ import annotations

from dataclasses import dataclass

from .config import Settings


@dataclass(frozen=True)
class RuntimeAvailability:
    has_liquidation_source: bool
    has_model_artifacts: bool


def has_liquidation_source(settings: Settings) -> bool:
    return False


def has_model_artifacts(settings: Settings) -> bool:
    if settings.risky_artifact_path is None or settings.safe_artifact_path is None:
        return False
    return settings.risky_artifact_path.is_file() and settings.safe_artifact_path.is_file()


def resolve_runtime_availability(settings: Settings) -> RuntimeAvailability:
    return RuntimeAvailability(
        has_liquidation_source=has_liquidation_source(settings),
        has_model_artifacts=has_model_artifacts(settings),
    )


def preflight_status(
    settings: Settings,
    availability: RuntimeAvailability,
) -> tuple[str, str]:
    if settings.strict_liquidation and not availability.has_liquidation_source:
        return "blocked", "missing_liquidation_source"
    if not availability.has_model_artifacts:
        return "blocked", "missing_model_artifact"
    return "running", "ok"
