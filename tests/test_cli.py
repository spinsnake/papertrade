from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from papertrade.contracts import FeatureSnapshot, Pair
from papertrade.cli import main

class CLITests(unittest.TestCase):
    def test_main_run_forward(self):
        with self.assertRaises(SystemExit) as cm:
            main(["run-forward"])
        self.assertEqual(cm.exception.code, 1)