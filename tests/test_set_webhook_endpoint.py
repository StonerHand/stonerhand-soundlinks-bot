"""The deploy hook that points Telegram at the webhook, end to end."""

import io
import json
import os
import unittest
from http import HTTPStatus
from unittest.mock import patch
from urllib.error import URLError

from api import set_webhook

TOKEN = "123456:TEST-token-for-unit-tests-only"
ENV = {
    "BOT_TOKEN": TOKEN,
    "SET_WEBHOOK_SECRET": "setup-secret",
    "WEBHOOK_BASE_URL": "https://bot.example",
}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _call(path: str = "/api/set_webhook?secret=setup-secret", headers=None):
    request = set_webhook.handler.__new__(set_webhook.handler)
    request.path = path
    request.headers = headers or {}
    sent: list[tuple[dict, int]] = []
    request._send_json = lambda payload, status=HTTPStatus.OK: sent.append(
        (payload, status)
    )
    request.do_GET()
    return sent[-1]


class SetWebhookEndpointTests(unittest.TestCase):
    def test_without_its_secret_the_endpoint_refuses_to_run(self) -> None:
        with patch.dict(os.environ, {"BOT_TOKEN": TOKEN}, clear=True):
            payload, status = _call()

        self.assertEqual(status, HTTPStatus.SERVICE_UNAVAILABLE)
        self.assertFalse(payload["ok"])

    def test_a_wrong_secret_is_forbidden(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            payload, status = _call("/api/set_webhook?secret=wrong")

        self.assertEqual((payload, status), ({"ok": False, "error": "forbidden"}, 403))

    def test_success_registers_webhook_commands_and_menu(self) -> None:
        answer = _Response(json.dumps({"ok": True, "result": True}).encode())
        with (
            patch.dict(os.environ, ENV, clear=True),
            patch.object(set_webhook, "urlopen", return_value=answer) as opened,
            patch.object(set_webhook, "_sync_commands", return_value={"ok": True}),
            patch.object(set_webhook, "_sync_menu_button", return_value={"ok": True}),
        ):
            payload, status = _call()

        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["webhook_url"], "https://bot.example/api/telegram")
        self.assertIn("api.telegram.org", opened.call_args.args[0])

    def test_a_failure_is_structured_and_never_leaks_the_token(self) -> None:
        with (
            patch.dict(os.environ, ENV, clear=True),
            patch.object(set_webhook, "urlopen", side_effect=URLError(TOKEN)),
            self.assertLogs(set_webhook.LOGGER, "ERROR"),
        ):
            payload, status = _call()

        self.assertEqual(status, HTTPStatus.INTERNAL_SERVER_ERROR)
        self.assertEqual(payload, {"ok": False, "error": "webhook setup failed"})
        self.assertNotIn(TOKEN, json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
