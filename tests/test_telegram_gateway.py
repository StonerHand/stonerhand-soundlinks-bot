from __future__ import annotations

import unittest
from datetime import timedelta
from unittest.mock import patch

from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from music_links_bot.telegram_gateway import (
    TelegramApiGateway,
    _telegram_api_error,
    feature_enabled,
)


class _Bot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def _post(self, endpoint: str, data: dict):
        self.calls.append((endpoint, data))
        return True


class TelegramGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_gateway_preserves_definitive_api_rejections(self) -> None:
        self.assertIsInstance(
            _telegram_api_error(400, {"description": "bad"}), BadRequest
        )
        self.assertIsInstance(
            _telegram_api_error(403, {"description": "forbidden"}), Forbidden
        )
        limited = _telegram_api_error(
            429,
            {"description": "slow down", "parameters": {"retry_after": 7}},
        )
        self.assertIsInstance(limited, RetryAfter)
        self.assertEqual(limited._retry_after, timedelta(seconds=7))

    async def test_raw_gateway_keeps_server_failures_ambiguous(self) -> None:
        error = _telegram_api_error(502, {"description": "upstream failed"})

        self.assertIs(type(error), TelegramError)
        self.assertIn("upstream failed", str(error))

    async def test_safe_mode_disables_optional_capabilities(self) -> None:
        with patch.dict(
            "os.environ",
            {"BOT_SAFE_MODE": "1", "RICH_MESSAGES_ENABLED": "1"},
            clear=True,
        ):
            self.assertFalse(feature_enabled("RICH_MESSAGES_ENABLED"))
            self.assertTrue(feature_enabled("BOT_SAFE_MODE", default=False))

    async def test_ephemeral_parameters_use_bot_api_10_3_shape(self) -> None:
        bot = _Bot()
        gateway = TelegramApiGateway(bot=bot)

        sent = await gateway.send_ephemeral_message(
            chat_id=-1001,
            receiver_user_id=7,
            callback_query_id="callback-1",
            replace_callback_query_message=True,
            text="Готово",
        )

        self.assertTrue(sent)
        method, payload = bot.calls[0]
        self.assertEqual(method, "sendMessage")
        self.assertEqual(
            payload["ephemeral_message_parameters"],
            {
                "receiver_user_id": 7,
                "callback_query_id": "callback-1",
                "replace_callback_query_message": True,
            },
        )

    async def test_rich_message_can_be_edited_in_place(self) -> None:
        bot = _Bot()
        gateway = TelegramApiGateway(bot=bot)

        edited = await gateway.edit_rich_message(
            chat_id="@channel",
            message_id=42,
            rich_message={"html": "<h1>Новое</h1>"},
        )

        self.assertTrue(edited)
        method, payload = bot.calls[0]
        self.assertEqual(method, "editMessageText")
        self.assertEqual(payload["message_id"], 42)
        self.assertEqual(payload["rich_message"]["html"], "<h1>Новое</h1>")


if __name__ == "__main__":
    unittest.main()
