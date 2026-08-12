from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

from api.telegram import _ensure_application
from music_links_bot.loop_runner import run_on_loop
from music_links_bot.publish_queue import process_due_jobs

LOGGER = logging.getLogger(__name__)
QUEUE_TICK_TIMEOUT_SECONDS = 20


def is_authorized(authorization_header: str | None) -> bool:
    secret = os.getenv("CRON_SECRET", "").strip()
    if not secret:
        return False
    return hmac.compare_digest(
        (authorization_header or "").strip(),
        f"Bearer {secret}",
    )


class handler(BaseHTTPRequestHandler):
    """Dedicated durable-queue tick for Vercel Cron and manual recovery."""

    def do_GET(self) -> None:
        if not is_authorized(self.headers.get("authorization")):
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
        self.end_headers()
        self.wfile.write(body)
