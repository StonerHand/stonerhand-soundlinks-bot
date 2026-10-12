from __future__ import annotations

import asyncio
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

from api.telegram import _ensure_application
from music_links_bot.loop_runner import run_on_loop
from music_links_bot.publish_queue import QueueStorageError, process_due_jobs
from music_links_bot.qstash_auth import verify_qstash_signature
from music_links_bot.webhook_secret import queue_worker_secret, secrets_match

LOGGER = logging.getLogger(__name__)
QUEUE_TICK_TIMEOUT_SECONDS = 20
QUEUE_WORKER_PATH = "/api/queue_worker"


def is_authorized(authorization_header: str | None) -> bool:
    secret = queue_worker_secret()
    if not secret:
        return False
    return secrets_match(
        (authorization_header or "").strip(),
        f"Bearer {secret}",
    )


class handler(BaseHTTPRequestHandler):
    """Dedicated durable-queue tick for Vercel Cron and manual recovery."""

    def do_GET(self) -> None:
        self._tick(authorized=is_authorized(self.headers.get("authorization")))

    def do_POST(self) -> None:
        # Upstash QStash schedules call with POST. The tick has no input; the
        # body is read only to check the signature that covers it.
        try:
            length = min(int(self.headers.get("content-length") or 0), 65_536)
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else b""
        authorized = is_authorized(
            self.headers.get("authorization")
        ) or verify_qstash_signature(
            self.headers.get("upstash-signature"),
            body,
            expected_path=QUEUE_WORKER_PATH,
        )
        self._tick(authorized=authorized)

    def _tick(self, *, authorized: bool) -> None:
        if not authorized:
            self._send_json(
                {"ok": False, "error": "unauthorized"},
                HTTPStatus.UNAUTHORIZED,
            )
            return

        try:
            loop, application = _ensure_application()
            context = SimpleNamespace(application=application, bot=application.bot)
            published = run_on_loop(
                loop,
                process_due_jobs(context),
                timeout=QUEUE_TICK_TIMEOUT_SECONDS,
            )
        except QueueStorageError:
            self._send_json(
                {"ok": False, "error": "storage unavailable", "retryable": True},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        except asyncio.TimeoutError:
            self._send_json(
                {"ok": False, "error": "timeout", "retryable": True},
                HTTPStatus.GATEWAY_TIMEOUT,
            )
            return
        except Exception:
            LOGGER.exception("Dedicated queue worker failed")
            self._send_json(
                {"ok": False, "error": "internal", "retryable": True},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        self._send_json({"ok": True, "published": int(published)})

    def _send_json(
        self,
        payload: dict,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("x-content-type-options", "nosniff")
        self.end_headers()
        self.wfile.write(body)
