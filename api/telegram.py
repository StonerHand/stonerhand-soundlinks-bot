from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
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

LOGGER = logging.getLogger(__name__)
MAX_UPDATE_BYTES = 1024 * 1024


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
            asyncio.run(_process_telegram_update(update_payload))
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


async def _process_telegram_update(update_payload: dict[str, object]) -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    application = build_application(settings)
    try:
        await application.initialize()
        update = Update.de_json(update_payload, application.bot)
        await application.process_update(update)
    finally:
        await application.shutdown()
        await close_application_resources(application)


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
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not expected_secret:
        return True

    return hmac.compare_digest(received_secret or "", expected_secret)
