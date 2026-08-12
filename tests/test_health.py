import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.health import (
    describe_failures,
    evaluate_webhook_info,
    overall_ok,
    overall_service_ok,
    release_info,
)
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
    def _checks(
        self,
        telegram=True,
        webhook=True,
        redis_ok=True,
        redis_conf=True,
        worker_ok=True,
        worker_conf=True,
    ):
        return {
            "telegram": {"ok": telegram},
            "webhook": {"ok": webhook},
            "redis": {"ok": redis_ok, "configured": redis_conf},
            "queue_worker": {"ok": worker_ok, "configured": worker_conf},
        }

    def test_all_green(self) -> None:
        self.assertTrue(overall_ok(self._checks()))

    def test_telegram_or_webhook_failure_is_critical(self) -> None:
        self.assertFalse(overall_ok(self._checks(telegram=False)))
        self.assertFalse(overall_ok(self._checks(webhook=False)))

    def test_unconfigured_redis_does_not_fail_health(self) -> None:
        self.assertTrue(overall_ok(self._checks(redis_ok=False, redis_conf=False)))
        self.assertFalse(overall_ok(self._checks(redis_ok=False, redis_conf=True)))

    def test_configured_queue_worker_is_critical(self) -> None:
        self.assertFalse(overall_ok(self._checks(worker_ok=False)))
        self.assertTrue(
            overall_ok(self._checks(worker_ok=False, worker_conf=False))
        )

    def test_overdue_queue_fails_whole_service_health(self) -> None:
        self.assertTrue(
            overall_service_ok(
                self._checks(),
                {"configured": True, "overdue": 0},
            )
        )
        self.assertFalse(
            overall_service_ok(
                self._checks(),
                {"configured": True, "overdue": 1},
            )
        )

    def test_release_info_identifies_deployed_build(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(
            os.environ,
            {
                "VERCEL_GIT_COMMIT_SHA": "1234567890abcdef",
                "VERCEL_ENV": "production",
            },
            clear=True,
        ):
            release = release_info()

        self.assertEqual(release["commit"], "1234567890ab")
        self.assertEqual(release["environment"], "production")
        self.assertRegex(release["version"], r"^\d+\.\d+\.\d+$")

    def test_describe_failures_skips_unconfigured_redis(self) -> None:
        failures = describe_failures(self._checks(webhook=False, redis_ok=False, redis_conf=False))
        self.assertEqual(failures, ["webhook"])

    def test_storage_snapshot_without_redis_is_empty(self) -> None:
        import os
        from unittest.mock import patch

        from api.health import _storage_snapshot

        with patch.dict(os.environ, {}, clear=True):
            redis, queue, metrics = _storage_snapshot()

        self.assertEqual(redis["configured"], False)
        self.assertEqual(queue, {"configured": False, "size": 0, "overdue": 0})
        self.assertEqual(metrics, {"configured": False})

    def test_queue_tick_uses_protected_worker_and_trusted_host(self) -> None:
        import os
        from unittest.mock import MagicMock, patch

        from api.health import _tick_queue

        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true,"published":2}'
        with (
            patch.dict(
                os.environ,
                {
                    "VERCEL_PROJECT_PRODUCTION_URL": "bot.example",
                    "CRON_SECRET": "secret",
                },
                clear=True,
            ),
            patch("api.health.urlopen", return_value=response) as open_mock,
        ):
            result = _tick_queue("attacker.example")

        self.assertEqual(result["published"], 2)
        self.assertTrue(result["ok"])
        self.assertTrue(result["configured"])

        request = open_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://bot.example/api/queue_worker")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    def test_queue_tick_is_disabled_without_secret(self) -> None:
        import os
        from unittest.mock import patch

        from api.health import _tick_queue

        with patch.dict(
            os.environ,
            {"VERCEL_PROJECT_PRODUCTION_URL": "bot.example"},
            clear=True,
        ):
            self.assertEqual(
                _tick_queue("bot.example"),
                {
                    "ok": True,
                    "configured": False,
                    "published": 0,
                    "detail": "not configured",
                },
            )

    def test_queue_tick_failure_is_visible(self) -> None:
        import os
        from unittest.mock import patch

        from api.health import _tick_queue

        with (
            patch.dict(
                os.environ,
                {
                    "VERCEL_PROJECT_PRODUCTION_URL": "bot.example",
                    "CRON_SECRET": "secret",
                },
                clear=True,
            ),
            patch("api.health.urlopen", side_effect=TimeoutError),
        ):
            result = _tick_queue("bot.example")

        self.assertFalse(result["ok"])
        self.assertTrue(result["configured"])
        self.assertEqual(result["published"], 0)

    def test_queue_summary_skips_corrupt_jobs(self) -> None:
        from api.health import _summarize_queue_jobs

        self.assertEqual(
            _summarize_queue_jobs(
                [
                    {"publish_at": 100},
                    {"publish_at": "broken"},
                    {"status": "pending"},
                    None,
                    {"publish_at": 950},
                ],
                now=1000,
            ),
            {"configured": True, "size": 2, "overdue": 1},
        )

    def test_queue_summary_does_not_flag_an_active_processing_lease(self) -> None:
        from api.health import _summarize_queue_jobs

        self.assertEqual(
            _summarize_queue_jobs(
                [
                    {
                        "publish_at": 100,
                        "status": "processing",
                        "lease_until": 1100,
                    }
                ],
                now=1000,
            ),
            {"configured": True, "size": 1, "overdue": 0},
        )


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
