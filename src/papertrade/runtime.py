from __future__ import annotations

from .config import Settings


def preflight_status(
    settings: Settings,
    *,
    has_liquidation_source: bool,
    has_model_artifacts: bool,
) -> tuple[str, str]:
    if settings.strict_liquidation and not has_liquidation_source:
        return "blocked", "missing_liquidation_source"
    if not has_model_artifacts:
        return "blocked", "missing_model_artifact"
    return "running", "ok"
