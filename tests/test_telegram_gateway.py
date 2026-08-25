from __future__ import annotations

import unittest
from unittest.mock import patch

from music_links_bot.telegram_gateway import TelegramApiGateway, feature_enabled


class _Bot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def _post(self, endpoint: str, data: dict):
        self.calls.append((endpoint, data))
        return True


class TelegramGatewayTests(unittest.IsolatedAsyncioTestCase):
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
