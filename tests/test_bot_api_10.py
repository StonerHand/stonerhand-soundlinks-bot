"""Bot API 9.5–10.3 features: disabled buttons, local time, private group replies."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from music_links_bot.bot_app import GROUP_BOT_COMMANDS, GROUP_BOT_COMMANDS_EN
from music_links_bot.bot_menu import channel_command, help_command
from music_links_bot.bot_preferences import preferences_view
from music_links_bot.bot_runtime import UserSession
from music_links_bot.bot_ui import editor_appearance_rows
from music_links_bot.draft_model import new_track_draft
from music_links_bot.human_time import local_time_html
from music_links_bot.models import TrackMatch


def _buttons(keyboard) -> list[dict]:
    rows = keyboard if isinstance(keyboard, list) else keyboard.inline_keyboard
    return [button.to_dict() for row in rows for button in row]


def _group_update(text: str):
    message = SimpleNamespace(
        chat=SimpleNamespace(type="supergroup", id=-100),
        chat_id=-100,
        message_id=5,
        text=text,
        from_user=SimpleNamespace(id=7, language_code="ru"),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(
        message=message,
        effective_message=message,
        effective_user=message.from_user,
        effective_chat=message.chat,
    )
    context = SimpleNamespace(
        bot=SimpleNamespace(username="StonerHandBot", token="TOKEN"),
        application=SimpleNamespace(bot_data={}),
    )
    return update, context


class DisabledButtonTests(unittest.TestCase):
    def test_current_setting_is_a_disabled_button(self) -> None:
        _, keyboard = preferences_view(
            UserSession(user_id=7), lang="ru", section="language"
        )
        current = [b for b in _buttons(keyboard) if b["text"].startswith("✓ ")]

        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["disabled"], {})
        self.assertNotIn("callback_data", current[0])

    def test_current_post_look_is_disabled_and_the_other_stays_clickable(
        self,
    ) -> None:
        track = TrackMatch(artist="Sleep", title="Dopesmoker", links={})
        draft = new_track_draft(track, chat_id=7, lang="ru")
        buttons = _buttons(editor_appearance_rows("demo", draft))

        self.assertEqual(buttons[0]["disabled"], {})
        self.assertIn("callback_data", buttons[1])


class LocalTimeTests(unittest.TestCase):
    def test_moment_is_shown_in_the_reader_time_zone(self) -> None:
        html = local_time_html(1800000000, timezone_name="Europe/Moscow")

        self.assertTrue(html.startswith('<tg-time unix="1800000000" format="wdt">'))
        self.assertTrue(html.endswith("</tg-time>"))


class PrivateGroupReplyTests(unittest.IsolatedAsyncioTestCase):
    def test_group_menu_lists_only_private_commands(self) -> None:
        for commands in (GROUP_BOT_COMMANDS, GROUP_BOT_COMMANDS_EN):
            payload = [command.to_dict() for command in commands]
            self.assertEqual([item["command"] for item in payload], ["help", "channel"])
            self.assertTrue(all(item["is_ephemeral"] for item in payload))

    async def test_help_in_a_group_is_seen_only_by_the_sender(self) -> None:
        update, context = _group_update("/help")
        with patch(
            "music_links_bot.ephemeral.send_ephemeral_message",
            new=AsyncMock(return_value=True),
        ) as send:
            await help_command(update, context)

        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[1:3], (-100, 7))
        update.message.reply_text.assert_not_awaited()

    async def test_channel_check_in_a_group_is_private(self) -> None:
        update, context = _group_update("/channel")
        access = SimpleNamespace(checked=True, allowed=True, can_delete=True)
        with (
            patch(
                "music_links_bot.chat_access.check_publish_access",
                new=AsyncMock(return_value=access),
            ),
            patch(
                "music_links_bot.ephemeral.send_ephemeral_message",
                new=AsyncMock(return_value=True),
            ) as send,
        ):
            await channel_command(update, context)

        send.assert_awaited_once()
        self.assertIn("Бот может публиковать", send.await_args.args[3])
        update.message.reply_text.assert_not_awaited()

    async def test_falls_back_to_a_public_reply_when_telegram_refuses(self) -> None:
        update, context = _group_update("/channel")
        access = SimpleNamespace(checked=True, allowed=True, can_delete=True)
        with (
            patch(
                "music_links_bot.chat_access.check_publish_access",
                new=AsyncMock(return_value=access),
            ),
            patch(
                "music_links_bot.ephemeral.send_ephemeral_message",
                new=AsyncMock(return_value=False),
            ),
        ):
            await channel_command(update, context)

        update.message.reply_text.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
