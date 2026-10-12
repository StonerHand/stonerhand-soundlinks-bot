import io
import json
import os
import unittest
from email.message import Message
from types import SimpleNamespace
from unittest.mock import patch

from api import queue_worker
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

    def test_worker_uses_separate_derived_secret_when_cron_secret_is_empty(
        self,
    ) -> None:
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


class QueueWorkerMethodTests(unittest.TestCase):
    def call(self, method: str, headers: dict[str, str], body: bytes = b""):
        handler = object.__new__(queue_worker.handler)
        handler.headers = Message()
        for name, value in headers.items():
            handler.headers[name] = value
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.request_version = "HTTP/1.1"
        handler.requestline = f"{method} /api/queue_worker HTTP/1.1"
        handler.command = method
        handler.client_address = ("127.0.0.1", 0)
        handler.close_connection = True
        with (
            patch.dict(os.environ, {"CRON_SECRET": "secret"}, clear=True),
            patch.object(
                queue_worker,
                "_ensure_application",
                return_value=(None, SimpleNamespace(bot=None)),
            ),
            patch.object(queue_worker, "process_due_jobs", new=lambda context: None),
            patch.object(queue_worker, "run_on_loop", return_value=2),
        ):
            getattr(handler, f"do_{method}")()
        raw = handler.wfile.getvalue().decode()
        status = int(raw.split(" ", 2)[1])
        payload = json.loads(raw.split("\r\n\r\n", 1)[1])
        return status, payload

    def test_qstash_post_runs_the_same_authenticated_tick(self) -> None:
        body = b'{"source":"qstash"}'
        status, payload = self.call(
            "POST",
            {"authorization": "Bearer secret", "content-length": str(len(body))},
            body,
        )
        self.assertEqual((status, payload), (200, {"ok": True, "published": 2}))

    def test_post_without_secret_is_rejected(self) -> None:
        status, payload = self.call("POST", {"content-length": "0"})
        self.assertEqual(status, 401)
        self.assertFalse(payload["ok"])

    def test_get_still_works_for_vercel_cron(self) -> None:
        status, payload = self.call("GET", {"authorization": "Bearer secret"})
        self.assertEqual((status, payload["published"]), (200, 2))


if __name__ == "__main__":
    unittest.main()
