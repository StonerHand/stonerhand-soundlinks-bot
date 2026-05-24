from __future__ import annotations

import asyncio
import json
import logging
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


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send_json({"ok": True, "service": "StonerHandBot webhook"})

    def do_POST(self) -> None:
        content_length = int(self.headers.get("content-length", "0"))
        if content_length <= 0:
            self._send_json({"ok": False, "error": "empty body"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            payload = self.rfile.read(content_length)
            asyncio.run(_process_telegram_update(payload))
        except json.JSONDecodeError:
            LOGGER.exception("Invalid Telegram update payload")
            self._send_json({"ok": False, "error": "invalid json"}, HTTPStatus.BAD_REQUEST)
            return
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
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


async def _process_telegram_update(payload: bytes) -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    application = build_application(settings)
    try:
        await application.initialize()
        update = Update.de_json(json.loads(payload), application.bot)
        await application.process_update(update)
    finally:
        await application.shutdown()
        await close_application_resources(application)
