from __future__ import annotations

from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from papertrade.config import Settings
from papertrade.runtime import (
    RuntimeAvailability,
    preflight_live_source_status,
    preflight_status,
    resolve_runtime_availability,
)


class RuntimeTests(unittest.TestCase):
    def test_run_blocked_when_liquidation_source_missing(self) -> None:
        settings = Settings(strict_liquidation=True)
        availability = RuntimeAvailability(
            has_liquidation_source=False,
            has_model_artifacts=True,
        )
        status, reason = preflight_status(
            settings,
            availability,
        )
        self.assertEqual(status, "blocked")
        self.assertEqual(reason, "missing_liquidation_source")

    def test_run_blocked_when_model_artifact_missing(self) -> None:
        settings = Settings(strict_liquidation=False)
        availability = RuntimeAvailability(
            has_liquidation_source=True,
            has_model_artifacts=False,
        )
        status, reason = preflight_status(
            settings,
            availability,
        )
        self.assertEqual(status, "blocked")
        self.assertEqual(reason, "missing_model_artifact")

    def test_resolve_runtime_availability_detects_configured_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            risky_path = Path(tmpdir) / "risky.json"
            safe_path = Path(tmpdir) / "safe.json"
            risky_path.write_text("{}", encoding="utf-8")
            safe_path.write_text("{}", encoding="utf-8")

            settings = Settings(
                risky_artifact_path=risky_path,
                safe_artifact_path=safe_path,
            )
            availability = resolve_runtime_availability(settings)

        self.assertTrue(availability.has_model_artifacts)
        self.assertFalse(availability.has_liquidation_source)

    def test_resolve_runtime_availability_detects_live_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            platform_db_path = base_dir / "platform.sqlite3"
            market_state_snapshot_path = base_dir / "market_states.json"
            orderbook_snapshot_path = base_dir / "orderbooks.json"
            liquidation_events_path = base_dir / "liquidations.json"
            platform_db_path.write_text("", encoding="utf-8")
            market_state_snapshot_path.write_text("[]", encoding="utf-8")
            orderbook_snapshot_path.write_text("[]", encoding="utf-8")
            liquidation_events_path.write_text("[]", encoding="utf-8")

            availability = resolve_runtime_availability(
                Settings(
                    platform_db_path=platform_db_path,
                    market_state_snapshot_path=market_state_snapshot_path,
                    orderbook_snapshot_path=orderbook_snapshot_path,
                    liquidation_events_path=liquidation_events_path,
                )
            )

        self.assertTrue(availability.has_platform_db_source)
        self.assertTrue(availability.has_platform_bridge_source)
        self.assertTrue(availability.has_liquidation_source)

    def test_preflight_live_source_status_blocks_when_platform_db_source_missing(self) -> None:
        status, reason = preflight_live_source_status(
            RuntimeAvailability(
                has_liquidation_source=True,
                has_model_artifacts=True,
                has_platform_db_source=False,
                has_platform_bridge_source=True,
            )
        )

        self.assertEqual(status, "blocked")
        self.assertEqual(reason, "missing_platform_db_source")

    def test_resolve_runtime_availability_detects_standalone_sqlite_live_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "papertrade.sqlite3"
            settings = Settings(
                live_platform_sources=True,
                platform_db_path=db_path,
            )

            availability = resolve_runtime_availability(settings)

        self.assertTrue(availability.has_platform_db_source)
        self.assertTrue(availability.has_platform_bridge_source)
        self.assertTrue(availability.has_platform_snapshot_source)
        self.assertEqual(availability.platform_source_kind, "standalone_sqlite_live")

    def test_resolve_runtime_availability_prefers_platform_postgres_source(self) -> None:
        settings = Settings(
            platform_postgres_dsn="postgres://platform",
        )

        with patch("papertrade.runtime.PostgresPlatformDBSource.ping", return_value=None), patch(
            "papertrade.runtime.PostgresFundingRoundSnapshotSource.ping",
            return_value=None,
        ):
            availability = resolve_runtime_availability(settings)

        self.assertTrue(availability.has_platform_db_source)
        self.assertTrue(availability.has_platform_snapshot_source)
        self.assertFalse(availability.has_platform_bridge_source)
        self.assertEqual(availability.platform_source_kind, "platform_postgres")

    def test_preflight_live_source_status_runs_when_platform_snapshot_source_is_ready(self) -> None:
        status, reason = preflight_live_source_status(
            RuntimeAvailability(
                has_liquidation_source=True,
                has_model_artifacts=True,
                has_platform_db_source=True,
                has_platform_bridge_source=False,
                has_platform_snapshot_source=True,
            )
        )

        self.assertEqual(status, "running")
        self.assertEqual(reason, "ok")
