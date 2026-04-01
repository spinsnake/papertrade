from __future__ import annotations

from dataclasses import dataclass

from .config import Settings


@dataclass(frozen=True)
class RuntimeAvailability:
    has_liquidation_source: bool
    has_model_artifacts: bool
    has_platform_db_source: bool = False
    has_platform_bridge_source: bool = False


def has_liquidation_source(settings: Settings) -> bool:
    return settings.liquidation_events_path is not None and settings.liquidation_events_path.is_file()


def has_platform_db_source(settings: Settings) -> bool:
    if settings.live_platform_sources:
        return True
    return settings.platform_db_path is not None and settings.platform_db_path.is_file()


def has_platform_bridge_source(settings: Settings) -> bool:
    if settings.live_platform_sources:
        return True
    return (
        settings.market_state_snapshot_path is not None
        and settings.market_state_snapshot_path.is_file()
        and settings.orderbook_snapshot_path is not None
        and settings.orderbook_snapshot_path.is_file()
    )


def has_model_artifacts(settings: Settings) -> bool:
    if settings.risky_artifact_path is None or settings.safe_artifact_path is None:
        return False
    return settings.risky_artifact_path.is_file() and settings.safe_artifact_path.is_file()


def resolve_runtime_availability(
    settings: Settings,
    *,
    has_liquidation_source_override: bool | None = None,
) -> RuntimeAvailability:
    return RuntimeAvailability(
        has_liquidation_source=(
            has_liquidation_source(settings)
            if has_liquidation_source_override is None
            else has_liquidation_source_override
        ),
        has_model_artifacts=has_model_artifacts(settings),
        has_platform_db_source=has_platform_db_source(settings),
        has_platform_bridge_source=has_platform_bridge_source(settings),
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


def preflight_live_source_status(availability: RuntimeAvailability) -> tuple[str, str]:
    if not availability.has_platform_db_source:
        return "blocked", "missing_platform_db_source"
    if not availability.has_platform_bridge_source:
        return "blocked", "missing_platform_bridge_source"
    return "running", "ok"
