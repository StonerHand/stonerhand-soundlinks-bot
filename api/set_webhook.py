from __future__ import annotations

import hmac
import json
import logging
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from music_links_bot.bot import (
    BOT_DESCRIPTIONS,
    BOT_SHORT_DESCRIPTIONS,
    PUBLIC_BOT_COMMANDS,
)
from music_links_bot.config import Settings

ALLOWED_UPDATES = ("message", "channel_post", "callback_query", "inline_query")
LOGGER = logging.getLogger(__name__)
WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            if not _setup_secret_is_configured():
                self._send_json(
                    {"ok": False, "error": "SET_WEBHOOK_SECRET is not configured"},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return

            if not _is_authorized(self.path, self.headers.get("authorization")):
                self._send_json(
                    {"ok": False, "error": "forbidden"},
                    HTTPStatus.FORBIDDEN,
                )
                return

            settings = Settings.from_env()
            webhook_url = _resolve_webhook_url(self.headers.get("host"))
            telegram_url = _telegram_set_webhook_url(
                settings.bot_token,
                webhook_url,
                secret_token=_telegram_webhook_secret(),
            )
            with urlopen(telegram_url, timeout=20) as response:
                telegram_payload = json.loads(response.read().decode("utf-8"))

            commands_payload = _sync_commands(settings.bot_token)
            _sync_menu_button(
                settings.bot_token,
                urlparse(webhook_url).netloc,
            )
        except Exception as exc:
            LOGGER.error("Webhook setup failed: %s", type(exc).__name__)
            self._send_json(
                {"ok": False, "error": "webhook setup failed"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        self._send_json(
            {
                "ok": bool(telegram_payload.get("ok")),
                "webhook_url": webhook_url,
                "telegram": telegram_payload,
                "commands": commands_payload,
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


def _telegram_set_webhook_url(
    bot_token: str,
    webhook_url: str,
    *,
    secret_token: str | None = None,
) -> str:
    params = {
        "url": webhook_url,
        "allowed_updates": json.dumps(ALLOWED_UPDATES),
        "drop_pending_updates": "true",
    }
    if secret_token:
        params["secret_token"] = secret_token

    query = urlencode(params)
    return f"https://api.telegram.org/bot{bot_token}/setWebhook?{query}"


def _telegram_set_commands_url(bot_token: str) -> str:
    commands = [
        {"command": command.command, "description": command.description}
        for command in PUBLIC_BOT_COMMANDS
    ]
    query = urlencode({"commands": json.dumps(commands, ensure_ascii=False)})
    return f"https://api.telegram.org/bot{bot_token}/setMyCommands?{query}"


def _sync_commands(bot_token: str) -> dict[str, object]:
    try:
        commands_url = _telegram_set_commands_url(bot_token)
        with urlopen(commands_url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))

        _sync_descriptions(bot_token)
        return payload if isinstance(payload, dict) else {"ok": False}
    except Exception as exc:
        LOGGER.error("Command sync failed: %s", type(exc).__name__)
        return {"ok": False, "error": "command sync failed"}


def _sync_menu_button(bot_token: str, host: str | None) -> None:
    webapp_url = os.getenv("WEBAPP_URL", "").strip()
    if not webapp_url and host:
        webapp_url = f"https://{host}/app"

    if not webapp_url:
        return

    menu_button = json.dumps(
        {"type": "web_app", "text": "Студия", "web_app": {"url": webapp_url}},
        ensure_ascii=False,
    )
    query = urlencode({"menu_button": menu_button})
    url = f"https://api.telegram.org/bot{bot_token}/setChatMenuButton?{query}"
    try:
        with urlopen(url, timeout=20):
            pass
    except Exception as exc:
        LOGGER.error("Menu button sync failed: %s", type(exc).__name__)


def _sync_descriptions(bot_token: str) -> None:
    calls = [
        ("setMyDescription", "description", BOT_DESCRIPTIONS),
        ("setMyShortDescription", "short_description", BOT_SHORT_DESCRIPTIONS),
    ]
    for method, field, texts in calls:
        for language_code, text in texts.items():
            params = {field: text}
            if language_code:
                params["language_code"] = language_code

            query = urlencode(params)
            url = f"https://api.telegram.org/bot{bot_token}/{method}?{query}"
            try:
                with urlopen(url, timeout=20):
                    pass
            except Exception as exc:
                LOGGER.error("%s sync failed: %s", method, type(exc).__name__)


def _is_authorized(path: str, authorization_header: str | None) -> bool:
    expected_secret = os.getenv("SET_WEBHOOK_SECRET", "").strip()
    query = parse_qs(urlparse(path).query)
    if hmac.compare_digest(query.get("secret", [""])[0], expected_secret):
        return True

    return _is_authorized_cron_request(authorization_header)


def _is_authorized_cron_request(authorization_header: str | None) -> bool:
    cron_secret = os.getenv("CRON_SECRET", "").strip()
    if not cron_secret:
        return False

    received = (authorization_header or "").strip()
    return hmac.compare_digest(received, f"Bearer {cron_secret}")


def _setup_secret_is_configured() -> bool:
    return bool(os.getenv("SET_WEBHOOK_SECRET", "").strip())


def _telegram_webhook_secret() -> str | None:
    from music_links_bot.webhook_secret import telegram_webhook_secret

    secret = telegram_webhook_secret()
    if not secret:
        return None

    if not WEBHOOK_SECRET_RE.fullmatch(secret):
        raise ValueError("TELEGRAM_WEBHOOK_SECRET has an invalid format")

    return secret


def _resolve_webhook_url(request_host: str | None) -> str:
    raw_base_url = (
        os.getenv("WEBHOOK_BASE_URL", "").strip()
        or os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
        or os.getenv("VERCEL_URL", "").strip()
        or (request_host or "").strip()
    )
    if not raw_base_url:
        raise ValueError("Webhook host is not configured")

    if "://" not in raw_base_url:
        raw_base_url = f"https://{raw_base_url}"

    parsed = urlparse(raw_base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        raise ValueError("Webhook base URL must be a public HTTPS URL")

    return f"{parsed.scheme}://{parsed.netloc}/api/telegram"
