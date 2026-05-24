from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from music_links_bot.config import Settings


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            settings = Settings.from_env()
            host = self.headers.get("host", "").strip()
            if not host:
                self._send_json(
                    {"ok": False, "error": "host header is missing"},
                    HTTPStatus.BAD_REQUEST,
                )
                return

            webhook_url = f"https://{host}/api/telegram"
            telegram_url = _telegram_set_webhook_url(settings.bot_token, webhook_url)
            with urlopen(telegram_url, timeout=20) as response:
                telegram_payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self._send_json(
                {"ok": False, "error": str(exc)},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        self._send_json(
            {
                "ok": bool(telegram_payload.get("ok")),
                "webhook_url": webhook_url,
                "telegram": telegram_payload,
            }
        )

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


def _telegram_set_webhook_url(bot_token: str, webhook_url: str) -> str:
    query = urlencode(
        {
            "url": webhook_url,
            "allowed_updates": json.dumps(["message", "channel_post"]),
            "drop_pending_updates": "true",
        }
    )
    return f"https://api.telegram.org/bot{bot_token}/setWebhook?{query}"
