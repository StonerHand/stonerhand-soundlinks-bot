import os
import unittest
from unittest.mock import patch

from api.queue_worker import is_authorized
from music_links_bot.webhook_secret import queue_worker_secret


class QueueWorkerAuthTests(unittest.TestCase):
    def test_worker_requires_cron_bearer_secret(self) -> None:
        with patch.dict(os.environ, {"CRON_SECRET": "secret"}, clear=True):
            self.assertTrue(is_authorized("Bearer secret"))
            self.assertFalse(is_authorized("Bearer wrong"))
            self.assertFalse(is_authorized(None))

    def test_worker_is_closed_when_secret_is_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_authorized(None))

    def test_worker_uses_separate_derived_secret_when_cron_secret_is_empty(self) -> None:
        with patch.dict(
            os.environ,
            {"BOT_TOKEN": "123456:test", "CRON_SECRET": ""},
            clear=True,
        ):
            derived = queue_worker_secret()
            self.assertTrue(derived)
            self.assertTrue(is_authorized(f"Bearer {derived}"))
            self.assertFalse(is_authorized("Bearer wrong"))

    def test_explicit_cron_secret_wins_over_derived_secret(self) -> None:
        with patch.dict(
            os.environ,
            {"BOT_TOKEN": "123456:test", "CRON_SECRET": "explicit"},
            clear=True,
        ):
            self.assertEqual(queue_worker_secret(), "explicit")
            self.assertTrue(is_authorized("Bearer explicit"))


if __name__ == "__main__":
    unittest.main()
