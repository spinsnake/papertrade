from __future__ import annotations

from unittest.mock import patch
import unittest

from papertrade.cli import main


class CLITests(unittest.TestCase):
    def test_main_run_forward_returns_blocked_exit_code(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            exit_code = main(["run-forward"])
        self.assertEqual(exit_code, 2)
