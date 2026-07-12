from __future__ import annotations

import asyncio
import hmac
import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from telegram import Update

from music_links_bot.bot import build_application, close_application_resources
from music_links_bot.config import Settings
from music_links_bot.publish_queue import process_due_jobs

LOGGER = logging.getLogger(__name__)
MAX_UPDATE_BYTES = 1024 * 1024

# Warm serverless instances keep module state between invocations, so the
# Telegram application, its HTTP connection pools and in-memory lookup caches
# are built once per instance instead of once per update. The container is
# frozen/reclaimed by the platform, so no per-request shutdown is needed;
# a failed update disposes the cached application to start clean next time.
_STATE_LOCK = threading.Lock()
_LOOP: asyncio.AbstractEventLoop | None = None
_APPLICATION = None


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send_json({"ok": True, "service": "StonerHandBot webhook"})

    def do_POST(self) -> None:
        if not _is_telegram_request_authorized(
            self.headers.get("x-telegram-bot-api-secret-token")
        ):
            self._send_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN)
            return

        content_length = _read_content_length(self.headers.get("content-length"))
        if content_length is None:
            self._send_json(
                {"ok": False, "error": "invalid content length"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        if content_length <= 0:
            self._send_json({"ok": False, "error": "empty body"}, HTTPStatus.BAD_REQUEST)
            return

        if content_length > MAX_UPDATE_BYTES:
            self._send_json(
                {"ok": False, "error": "payload too large"},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return

        try:
            payload = self.rfile.read(content_length)
            update_payload = _decode_update_payload(payload)
        except (json.JSONDecodeError, ValueError):
            LOGGER.exception("Invalid Telegram update payload")
            self._send_json({"ok": False, "error": "invalid json"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            _process_telegram_update(update_payload)
        except Exception:
            LOGGER.exception("Could not process Telegram update")
            self._send_json({"ok": False}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json({"ok": True})

    def _send_json(
        self,
        payload: dict[str, object],
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _process_telegram_update(update_payload: dict[str, object]) -> None:
    with _STATE_LOCK:
        loop, application = _ensure_application()
        update = Update.de_json(update_payload, application.bot)
        try:
            loop.run_until_complete(application.process_update(update))
        except Exception:
            _dispose_application_locked()
            raise

        # Opportunistic queue tick: every incoming update also delivers
        # scheduled posts whose time has come.
        try:
            loop.run_until_complete(_run_queue_tick(application))
        except Exception:
            LOGGER.warning("Queue tick failed", exc_info=True)


async def _run_queue_tick(application) -> int:
    from types import SimpleNamespace

    context = SimpleNamespace(application=application, bot=application.bot)
    return await process_due_jobs(context)


def _ensure_application():
    global _LOOP, _APPLICATION
    if _APPLICATION is None:
        settings = Settings.from_env()
        logging.basicConfig(
            level=getattr(logging, settings.log_level, logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        application = build_application(settings)
        loop.run_until_complete(application.initialize())
        _LOOP = loop
        _APPLICATION = application

    return _LOOP, _APPLICATION


def _dispose_application_locked() -> None:
    global _LOOP, _APPLICATION
    loop, application = _LOOP, _APPLICATION
    _LOOP = None
    _APPLICATION = None
    if loop is None or application is None:
        return

    try:
        loop.run_until_complete(application.shutdown())
        loop.run_until_complete(close_application_resources(application))
    except Exception:
        LOGGER.warning("Could not dispose Telegram application cleanly")
    finally:
        loop.close()


def _decode_update_payload(payload: bytes) -> dict[str, object]:
    update_payload = json.loads(payload)
    if not isinstance(update_payload, dict):
        raise ValueError("Telegram update payload must be a JSON object.")

    return update_payload


def _read_content_length(raw_value: str | None) -> int | None:
    try:
        return int(raw_value or "0")
    except ValueError:
        return None


def _is_telegram_request_authorized(received_secret: str | None) -> bool:
    from music_links_bot.webhook_secret import telegram_webhook_secret

    expected_secret = telegram_webhook_secret()
    if not expected_secret:
        # No explicit secret and no bot token to derive one from — nothing
        # meaningful to compare against (local development only).
        return True

    return hmac.compare_digest(received_secret or "", expected_secret)
