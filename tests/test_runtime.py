from __future__ import annotations

import unittest

from papertrade.config import Settings
from papertrade.runtime import preflight_status


class RuntimeTests(unittest.TestCase):
    def test_run_blocked_when_liquidation_source_missing(self) -> None:
        settings = Settings(strict_liquidation=True)
        status, reason = preflight_status(
            settings,
            has_liquidation_source=False,
            has_model_artifacts=True,
        )
        self.assertEqual(status, "blocked")
        self.assertEqual(reason, "missing_liquidation_source")

    def test_run_blocked_when_model_artifact_missing(self) -> None:
        settings = Settings(strict_liquidation=False)
        status, reason = preflight_status(
            settings,
            has_liquidation_source=True,
            has_model_artifacts=False,
        )
        self.assertEqual(status, "blocked")
        self.assertEqual(reason, "missing_model_artifact")
