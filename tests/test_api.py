import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from api.set_webhook import (
    ALLOWED_UPDATES,
    _is_authorized,
    _resolve_webhook_url,
    _setup_secret_is_configured,
    _telegram_set_webhook_url,
    _telegram_webhook_secret,
)
import api.telegram as telegram_api
from api.telegram import (
    _decode_update_payload,
    _is_telegram_request_authorized,
    _read_content_length,
)


class VercelWebhookTests(unittest.TestCase):
    def test_decode_update_payload_accepts_json_objects(self) -> None:
        self.assertEqual(_decode_update_payload(b'{"update_id": 1}'), {"update_id": 1})

    def test_decode_update_payload_rejects_non_object_json(self) -> None:
        with self.assertRaises(ValueError):
            _decode_update_payload(b"[]")

    def test_decode_update_payload_rejects_invalid_json(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            _decode_update_payload(b"{")

    def test_read_content_length_handles_missing_and_invalid_values(self) -> None:
        self.assertEqual(_read_content_length(None), 0)
        self.assertEqual(_read_content_length("42"), 42)
        self.assertIsNone(_read_content_length("not-a-number"))

    def test_webhook_accepts_menu_button_callbacks(self) -> None:
        self.assertIn("callback_query", ALLOWED_UPDATES)

    def test_telegram_secret_is_optional_and_compared_safely(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(_is_telegram_request_authorized(None))

        with patch.dict(
            os.environ,
            {"TELEGRAM_WEBHOOK_SECRET": "telegram-secret"},
            clear=True,
        ):
            self.assertTrue(_is_telegram_request_authorized("telegram-secret"))
            self.assertFalse(_is_telegram_request_authorized("wrong"))

    def test_setup_endpoint_requires_its_own_secret(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(_setup_secret_is_configured())

        with patch.dict(
            os.environ,
            {"SET_WEBHOOK_SECRET": "setup-secret"},
            clear=True,
        ):
            self.assertTrue(_setup_secret_is_configured())
            self.assertTrue(_is_authorized("/api/set_webhook?secret=setup-secret", None))
            self.assertFalse(_is_authorized("/api/set_webhook?secret=wrong", None))

    def test_setup_endpoint_accepts_vercel_cron_bearer_secret(self) -> None:
        with patch.dict(
            os.environ,
            {"SET_WEBHOOK_SECRET": "setup-secret", "CRON_SECRET": "cron-secret"},
            clear=True,
        ):
            self.assertTrue(
                _is_authorized("/api/set_webhook", "Bearer cron-secret")
            )
            self.assertFalse(
                _is_authorized("/api/set_webhook", "Bearer wrong-secret")
            )
            self.assertFalse(_is_authorized("/api/set_webhook", None))

        with patch.dict(
            os.environ,
            {"SET_WEBHOOK_SECRET": "setup-secret"},
            clear=True,
        ):
            self.assertFalse(
                _is_authorized("/api/set_webhook", "Bearer cron-secret")
            )

    def test_set_webhook_url_includes_telegram_secret(self) -> None:
        webhook_url = _telegram_set_webhook_url(
            "bot-token",
            "https://bot.example/api/telegram",
            secret_token="telegram-secret",
        )
        query = parse_qs(urlparse(webhook_url).query)

        self.assertEqual(query["secret_token"], ["telegram-secret"])
        self.assertEqual(query["url"], ["https://bot.example/api/telegram"])

    def test_telegram_secret_rejects_invalid_characters(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_WEBHOOK_SECRET": "not valid"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                _telegram_webhook_secret()

    def test_webhook_reuses_application_across_warm_invocations(self) -> None:
        class ApplicationStub:
            def __init__(self) -> None:
                self.bot = object()
                self.initialize_calls = 0

            async def initialize(self) -> None:
                self.initialize_calls += 1

        build_calls = []

        def fake_build_application(settings):
            del settings
            application = ApplicationStub()
            build_calls.append(application)
            return application

        class SettingsStub:
            log_level = "INFO"

        telegram_api._dispose_application_locked()
        try:
            with (
                patch.object(telegram_api, "build_application", fake_build_application),
                patch.object(
                    telegram_api.Settings,
                    "from_env",
                    classmethod(lambda cls: SettingsStub()),
                ),
            ):
                first_loop, first_app = telegram_api._ensure_application()
                second_loop, second_app = telegram_api._ensure_application()

                self.assertIs(first_app, second_app)
                self.assertIs(first_loop, second_loop)
                self.assertEqual(len(build_calls), 1)
                self.assertEqual(first_app.initialize_calls, 1)
        finally:
            telegram_api._dispose_application_locked()

    def test_resolve_webhook_url_prefers_configured_base_url(self) -> None:
        with patch.dict(
            os.environ,
            {"WEBHOOK_BASE_URL": "https://soundlinks.example/custom/path"},
            clear=True,
        ):
            self.assertEqual(
                _resolve_webhook_url("forged.example"),
                "https://soundlinks.example/api/telegram",
            )


if __name__ == "__main__":
    unittest.main()
