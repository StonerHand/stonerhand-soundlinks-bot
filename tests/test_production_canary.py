from __future__ import annotations

import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

SCRIPT = Path(__file__).parent / "e2e" / "production_canary.py"
SPEC = importlib.util.spec_from_file_location("production_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
production_canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(production_canary)


class ProductionCanaryTests(unittest.TestCase):
    @staticmethod
    def payload(*, telegram=True, webhook=True, redis=True, queue=None, worker=True):
        return {
            "ok": False,
            "checks": {
                "telegram": {"ok": telegram},
                "webhook": {"ok": webhook},
                "redis": {"ok": redis, "configured": True},
                "queue_worker": {"ok": worker, "configured": True},
            },
            "queue": queue or {"overdue": 0, "uncertain": 0},
        }

    def test_release_check_does_not_rollback_for_preexisting_queue_state(self):
        payload = self.payload(queue={"overdue": 0, "uncertain": 1})
        self.assertTrue(
            production_canary.health_response_is_acceptable(
                503, payload, release_only=True
            )
        )
        self.assertFalse(
            production_canary.health_response_is_acceptable(
                503, payload, release_only=False
            )
        )

    def test_fetch_preserves_structured_503_response(self):
        error = HTTPError(
            "https://bot.example/api/health",
            503,
            "unhealthy",
            {"content-type": "application/json"},
            io.BytesIO(b'{"ok":false}'),
        )
        with patch.object(production_canary, "urlopen", side_effect=error):
            status, body, content_type = production_canary.fetch("/api/health")

        self.assertEqual(status, 503)
        self.assertEqual(body, b'{"ok":false}')
        self.assertEqual(content_type, "application/json")

    def test_release_check_still_rejects_critical_service_failure(self):
        payload = self.payload(
            telegram=False,
            queue={"overdue": 1, "uncertain": 0},
        )
        self.assertFalse(
            production_canary.health_response_is_acceptable(
                503, payload, release_only=True
            )
        )

    def test_release_check_rejects_unexplained_unhealthy_response(self):
        payload = self.payload()
        self.assertFalse(
            production_canary.health_response_is_acceptable(
                503, payload, release_only=True
            )
        )


if __name__ == "__main__":
    unittest.main()
