import time
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.health import describe_failures, evaluate_webhook_info, overall_ok
from music_links_bot.alerts import alert_dedup_digest


class WebhookEvaluationTests(unittest.TestCase):
    def test_registered_webhook_is_healthy(self) -> None:
        healthy, detail = evaluate_webhook_info(
            {"ok": True, "result": {"url": "https://bot.example/api/telegram"}}
        )
        self.assertTrue(healthy)
        self.assertEqual(detail, "https://bot.example/api/telegram")

    def test_missing_webhook_is_unhealthy(self) -> None:
        healthy, detail = evaluate_webhook_info({"ok": True, "result": {"url": ""}})
        self.assertFalse(healthy)
        self.assertIn("not registered", detail)

    def test_recent_delivery_error_is_unhealthy(self) -> None:
        healthy, detail = evaluate_webhook_info(
            {
                "ok": True,
                "result": {
                    "url": "https://bot.example/api/telegram",
                    "last_error_message": "Wrong response",
                    "last_error_date": int(time.time()) - 60,
                },
            }
        )
        self.assertFalse(healthy)
        self.assertIn("delivery failing", detail)

    def test_old_delivery_error_is_forgiven(self) -> None:
        healthy, _ = evaluate_webhook_info(
            {
                "ok": True,
                "result": {
                    "url": "https://bot.example/api/telegram",
                    "last_error_message": "Wrong response",
                    "last_error_date": int(time.time()) - 7200,
                },
            }
        )
        self.assertTrue(healthy)

    def test_malformed_payload_is_unhealthy(self) -> None:
        self.assertFalse(evaluate_webhook_info(None)[0])
        self.assertFalse(evaluate_webhook_info({"ok": False})[0])


class OverallHealthTests(unittest.TestCase):
    def _checks(self, telegram=True, webhook=True, redis_ok=True, redis_conf=True):
        return {
            "telegram": {"ok": telegram},
            "webhook": {"ok": webhook},
            "redis": {"ok": redis_ok, "configured": redis_conf},
        }

    def test_all_green(self) -> None:
        self.assertTrue(overall_ok(self._checks()))

    def test_telegram_or_webhook_failure_is_critical(self) -> None:
        self.assertFalse(overall_ok(self._checks(telegram=False)))
        self.assertFalse(overall_ok(self._checks(webhook=False)))

    def test_unconfigured_redis_does_not_fail_health(self) -> None:
        self.assertTrue(overall_ok(self._checks(redis_ok=False, redis_conf=False)))
        self.assertFalse(overall_ok(self._checks(redis_ok=False, redis_conf=True)))

    def test_describe_failures_skips_unconfigured_redis(self) -> None:
        failures = describe_failures(self._checks(webhook=False, redis_ok=False, redis_conf=False))
        self.assertEqual(failures, ["webhook"])

    def test_queue_status_without_redis_is_empty(self) -> None:
        import os
        from unittest.mock import patch

        from api.health import _queue_status

        with patch.dict(os.environ, {}, clear=True):
            status = _queue_status()

        self.assertEqual(status, {"configured": False, "size": 0, "overdue": 0})


class AlertHelperTests(unittest.TestCase):
    def test_dedup_digest_is_stable_and_short(self) -> None:
        first = alert_dedup_digest("health:webhook")
        second = alert_dedup_digest("health:webhook")
        other = alert_dedup_digest("health:redis")

        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len(first), 16)

    def test_alert_without_credentials_is_a_noop(self) -> None:
        import os
        from unittest.mock import patch

        from music_links_bot.alerts import send_admin_alert

        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(send_admin_alert("boom"))


if __name__ == "__main__":
    unittest.main()
