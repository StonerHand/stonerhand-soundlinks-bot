from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler

from music_links_bot.errors import normalize_api_response
from music_links_bot.loop_runner import run_on_loop
from music_links_bot.webapp_auth import validate_init_data

LOGGER = logging.getLogger(__name__)


class StudioRequestHandler(BaseHTTPRequestHandler):
    """HTTP transport for the Studio API; domain actions stay in webapp.py."""

    max_body_bytes = 128 * 1024
    action_timeout_seconds = 25

    def ensure_application(self):
        raise NotImplementedError

    async def handle_action(self, application, settings, user, payload):
        raise NotImplementedError

    def do_GET(self) -> None:
        self._send_json(
            {
                "ok": True,
                "service": "StonerHand studio API",
            }
        )

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("content-length") or "0")
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > self.max_body_bytes:
            self._send_json(
                {"ok": False, "error": "bad request"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
            if not isinstance(payload, dict):
                raise ValueError
        except ValueError:
            self._send_json(
                {"ok": False, "error": "invalid json"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        req_id = secrets.token_hex(4)
        action = (
            str(payload.get("action") or "?")
            .replace("\n", " ")
            .replace("\r", " ")[:48]
        )
        started = time.monotonic()
        try:
            loop, application, settings = self.ensure_application()
            user = validate_init_data(
                str(payload.get("init_data") or ""),
                settings.bot_token,
            )
            if user is None:
                LOGGER.info("req=%s action=%s unauthorized", req_id, action)
                self._send_json(
                    {
                        "ok": False,
                        "error": "unauthorized",
                        "request_id": req_id,
                    },
                    HTTPStatus.UNAUTHORIZED,
                )
                return
            result = run_on_loop(
                loop,
                self.handle_action(application, settings, user, payload),
                timeout=self.action_timeout_seconds,
            )
            result.setdefault("request_id", req_id)
        except asyncio.TimeoutError:
            LOGGER.warning(
                "req=%s action=%s timed out after %.1fs",
                req_id,
                action,
                time.monotonic() - started,
            )
            self._send_json(
                {
                    "ok": False,
                    "error": "timeout",
                    "retryable": True,
                    "request_id": req_id,
                },
                HTTPStatus.GATEWAY_TIMEOUT,
            )
            return
        except Exception:
            LOGGER.exception("req=%s action=%s failed", req_id, action)
            self._send_json(
                {
                    "ok": False,
                    "error": "internal",
                    "retryable": True,
                    "request_id": req_id,
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        LOGGER.info(
            "req=%s action=%s ok=%s %.0fms",
            req_id,
            action,
            bool(result.get("ok")),
            (time.monotonic() - started) * 1000,
        )
        status = (
            HTTPStatus.OK
            if result.get("ok")
            else HTTPStatus.UNPROCESSABLE_ENTITY
        )
        self._send_json(result, status)

    def _send_json(
        self,
        payload: dict,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(
            normalize_api_response(payload),
            ensure_ascii=False,
        ).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
