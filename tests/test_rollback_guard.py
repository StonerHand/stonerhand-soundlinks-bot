from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "e2e" / "rollback_guard.py"
SPEC = importlib.util.spec_from_file_location("rollback_guard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
rollback_guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollback_guard)


class RollbackGuardTests(unittest.TestCase):
    def test_only_exact_unhealthy_build_can_roll_back(self) -> None:
        self.assertTrue(
            rollback_guard.should_rollback(
                {"ok": False, "release": {"commit": "abcdef123456"}},
                "abcdef1234567890",
            )
        )
        self.assertFalse(
            rollback_guard.should_rollback(
                {"ok": True, "release": {"commit": "abcdef123456"}},
                "abcdef1234567890",
            )
        )
        self.assertFalse(
            rollback_guard.should_rollback(
                {"ok": False, "release": {"commit": "old000000000"}},
                "abcdef1234567890",
            )
        )

    def test_missing_release_identity_never_rolls_back(self) -> None:
        self.assertFalse(rollback_guard.should_rollback({"ok": False}, "abcdef"))
        self.assertFalse(
            rollback_guard.should_rollback(
                {"ok": False, "release": {"commit": "abcdef"}},
                "",
            )
        )
