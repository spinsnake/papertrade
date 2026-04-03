from __future__ import annotations

from dataclasses import dataclass

from ..data_management.config import Settings
from ..data_streaming.sources.platform_db import PostgresPlatformDBSource, SQLitePlatformDBSource
from ..data_streaming.sources.platform_snapshots import PostgresFundingRoundSnapshotSource, SQLiteFundingRoundSnapshotSource


@dataclass(frozen=True)
class RuntimeAvailability:
    has_liquidation_source: bool
    has_model_artifacts: bool
    has_platform_db_source: bool = False
    has_platform_bridge_source: bool = False
    has_platform_snapshot_source: bool = False
    platform_source_kind: str = "none"


def has_liquidation_source(settings: Settings) -> bool:
    if settings.live_liquidation_source:
        return True
    return settings.liquidation_events_path is not None and settings.liquidation_events_path.is_file()


def has_platform_native_source(settings: Settings) -> bool:
    if not settings.platform_postgres_dsn:
        return False
    try:
        platform_db_source = PostgresPlatformDBSource(settings.platform_postgres_dsn)
        platform_db_source.ping()
        snapshot_source = PostgresFundingRoundSnapshotSource(
            dsn=settings.platform_postgres_dsn,
            platform_db_source=platform_db_source,
            open_interest_mode=settings.open_interest_mode,
        )
        snapshot_source.ping()
    except Exception:
        return False
    return True


def has_sqlite_standalone_live_source(settings: Settings) -> bool:
    if not settings.live_platform_sources or settings.platform_db_path is None:
        return False
    try:
        sqlite_source = SQLitePlatformDBSource(settings.platform_db_path)
        sqlite_source.ping()
        snapshot_source = SQLiteFundingRoundSnapshotSource(
            path=settings.platform_db_path,
            platform_db_source=sqlite_source,
            open_interest_mode=settings.open_interest_mode,
        )
        snapshot_source.ping()
    except Exception:
        return False
    return True


def has_platform_db_source(settings: Settings) -> bool:
    if has_platform_native_source(settings):
        return True
    if settings.live_platform_sources and settings.platform_db_path is not None:
        return True
    if settings.live_platform_sources:
        return True
    return settings.platform_db_path is not None and settings.platform_db_path.exists()


def has_platform_bridge_source(settings: Settings) -> bool:
    if has_platform_native_source(settings):
        return False
    if settings.live_platform_sources and settings.platform_db_path is not None:
        return True
    if settings.live_platform_sources:
        return True
    return (
        settings.market_state_snapshot_path is not None
        and settings.market_state_snapshot_path.exists()
        and settings.orderbook_snapshot_path is not None
        and settings.orderbook_snapshot_path.exists()
    )


def has_platform_snapshot_source(settings: Settings) -> bool:
    return has_platform_native_source(settings) or has_sqlite_standalone_live_source(settings)


def has_model_artifacts(settings: Settings) -> bool:
    if settings.risky_artifact_path is None or settings.safe_artifact_path is None:
        return False
    return settings.risky_artifact_path.is_file() and settings.safe_artifact_path.is_file()


def resolve_runtime_availability(
    settings: Settings,
    *,
    has_liquidation_source_override: bool | None = None,
) -> RuntimeAvailability:
    platform_native = has_platform_native_source(settings)
    sqlite_live = has_sqlite_standalone_live_source(settings)
    return RuntimeAvailability(
        has_liquidation_source=(
            has_liquidation_source(settings)
            if has_liquidation_source_override is None
            else has_liquidation_source_override
        ),
        has_model_artifacts=has_model_artifacts(settings),
        has_platform_db_source=has_platform_db_source(settings),
        has_platform_bridge_source=has_platform_bridge_source(settings),
        has_platform_snapshot_source=platform_native or sqlite_live,
        platform_source_kind=(
            "platform_postgres"
            if platform_native
            else (
                "standalone_sqlite_live"
                if settings.live_platform_sources and settings.platform_db_path is not None
                else ("exchange_rest" if settings.live_platform_sources else "local_files")
            )
        ),
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
    if availability.has_platform_snapshot_source:
        return "running", "ok"
    if not availability.has_platform_db_source:
        return "blocked", "missing_platform_db_source"
    if not availability.has_platform_bridge_source:
        return "blocked", "missing_platform_bridge_source"
    return "running", "ok"
