from __future__ import annotations

from pathlib import Path
import unittest

from papertrade.config import Settings
from papertrade.runtime import RuntimeAvailability, preflight_status, resolve_runtime_availability


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
        settings = Settings(
            risky_artifact_path=Path("artifacts/risky.json"),
            safe_artifact_path=Path("artifacts/safe.json"),
        )
        availability = resolve_runtime_availability(settings)
        self.assertTrue(availability.has_model_artifacts)
        self.assertFalse(availability.has_liquidation_source)
