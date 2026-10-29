"""/cancel ends the current input or lookup without touching the card."""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_release_119_state import RedisModel, ctx

from music_links_bot.chat.bot_menu import cancel_command
from music_links_bot.core.i18n import get_text
from music_links_bot.state.bot_runtime import BotRuntime


class CancelCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.context = ctx(RedisModel())
        self.runtime = BotRuntime(self.context.application.bot_data["kv_store"])
        self.context.application.bot_data["runtime"] = self.runtime
        self.context.bot = SimpleNamespace(delete_message=AsyncMock())
        self.message = SimpleNamespace(chat_id=7, reply_text=AsyncMock())
        self.update = SimpleNamespace(
            effective_message=self.message,
            effective_user=SimpleNamespace(id=7, language_code="ru"),
        )

    async def test_cancelling_input_removes_only_the_prompt(self) -> None:
        session = await self.runtime.get_session(7)
        session.pending_input = {
            "kind": "intro",
            "draft_id": "d1",
            "editor_chat_id": 7,
            "editor_message_id": 40,
            "prompt_message_id": 41,
            "created_at": int(time.time()),
        }
        await self.runtime.save_session(session)

        await cancel_command(self.update, self.context)

        self.context.bot.delete_message.assert_awaited_once_with(
            chat_id=7, message_id=41
        )
        self.assertFalse((await self.runtime.get_session(7)).pending_input)
        self.message.reply_text.assert_awaited_once_with(
            get_text("ru", "input_cancelled")
        )

    async def test_without_input_it_stops_a_running_lookup(self) -> None:
        self.runtime.cancel_request_durable = AsyncMock(return_value=False)

        await cancel_command(self.update, self.context)

        self.runtime.cancel_request_durable.assert_awaited_once_with(7)
        self.context.bot.delete_message.assert_not_awaited()
        self.message.reply_text.assert_awaited_once_with(
            get_text("ru", "input_nothing")
        )


if __name__ == "__main__":
    unittest.main()


class PrivacyScreenTests(unittest.IsolatedAsyncioTestCase):
    async def _tap(self, action: str, result=None):
        from unittest.mock import patch

        from music_links_bot.chat import bot_menu
        from music_links_bot.state.bot_runtime import decode_callback, encode_callback

        query = SimpleNamespace(
            from_user=SimpleNamespace(id=7, language_code="ru"),
            answer=AsyncMock(),
        )
        context = SimpleNamespace(bot=SimpleNamespace(username="StonerHandBot"))
        edit = AsyncMock()
        deleted = AsyncMock(return_value=result)
        with (
            patch.object(bot_menu, "safe_edit", new=edit),
            patch.object(bot_menu, "delete_user_data", new=deleted),
        ):
            await bot_menu.dispatch_privacy_action(
                query, context, decode_callback(encode_callback("privacy", action))
            )
        return edit.await_args.args[1], deleted

    async def test_the_first_tap_only_asks_to_confirm(self) -> None:
        text, deleted = await self._tap("confirm")

        self.assertEqual(text, get_text("ru", "privacy_confirm"))
        deleted.assert_not_awaited()

    async def test_confirmed_deletion_reports_what_was_removed(self) -> None:
        from music_links_bot.chat.privacy import DeletionResult

        text, deleted = await self._tap(
            "delete", DeletionResult(drafts=3, scheduled_posts=1, queue_available=False)
        )

        deleted.assert_awaited_once()
        self.assertIn("3", text)
        self.assertTrue(text.endswith(get_text("ru", "privacy_deleted_queue_warning")))
