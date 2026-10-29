"""Text typed in answer to a prompt: every branch ends in a clear reply."""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_release_119_state import RedisModel, ctx, draft

from music_links_bot.core.i18n import get_text
from music_links_bot.editor import bot_pending
from music_links_bot.state.bot_crate import save_crate
from music_links_bot.state.bot_runtime import BotRuntime
from music_links_bot.state.bot_storage import store_draft

USER = 7


class PendingInputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.context = ctx(RedisModel())
        self.context.application.bot_data["admin_chat_id"] = USER
        self.context.bot = SimpleNamespace(delete_message=AsyncMock())
        self.runtime = BotRuntime(self.context.application.bot_data["kv_store"])
        self.context.application.bot_data["runtime"] = self.runtime
        self.restore = patch.object(
            bot_pending, "_restore_crate_screen", new=AsyncMock()
        )
        self.restored = self.restore.start()
        self.addCleanup(self.restore.stop)

    async def _type(self, text: str, **pending) -> tuple[bool, SimpleNamespace]:
        session = await self.runtime.get_session(USER)
        session.pending_input = {
            "created_at": int(time.time()),
            "prompt_message_id": 41,
            **pending,
        }
        await self.runtime.save_session(session)
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            chat_id=USER,
            message_id=50,
            text=text,
            caption=None,
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=USER, language_code="ru"),
        )
        handled = await bot_pending.consume_pending_input(
            update, self.context, retry_lookup=AsyncMock()
        )
        return handled, message

    async def _pending_left(self) -> dict:
        return (await self.runtime.get_session(USER)).pending_input

    def _reply(self, message) -> str:
        return message.reply_text.await_args.args[0]

    async def test_an_expired_prompt_lets_the_text_through(self) -> None:
        handled, message = await self._type("hello", kind="intro", created_at=1)

        self.assertFalse(handled)
        message.reply_text.assert_not_awaited()
        self.assertEqual(await self._pending_left(), {})

    async def test_an_empty_message_keeps_waiting(self) -> None:
        handled, _ = await self._type("   ", kind="intro", draft_id="d1")

        self.assertTrue(handled)
        self.assertTrue(await self._pending_left())

    async def test_draft_inputs_refuse_missing_foreign_deleted_and_stale(self) -> None:
        own = draft()
        foreign = {**draft(), "chat_id": 99}
        gone = {**draft(), "deleted_at": 1}
        await store_draft(self.context, "own", own)
        await store_draft(self.context, "foreign", foreign)
        await store_draft(self.context, "gone", gone)
        cases = (
            ({"draft_id": "missing"}, "ed_expired"),
            ({"draft_id": "foreign"}, "ed_owner_only"),
            ({"draft_id": "gone"}, "ed_deleted_recovery"),
            ({"draft_id": "own", "draft_revision": 999}, "state_conflict"),
        )
        for pending, key in cases:
            with self.subTest(key=key):
                handled, message = await self._type(
                    "Новый текст", kind="intro", **pending
                )

                self.assertTrue(handled)
                self.assertEqual(self._reply(message), get_text("ru", key))
                self.assertEqual(await self._pending_left(), {})

    async def test_crate_note_is_saved_and_the_crate_comes_back(self) -> None:
        from music_links_bot.core.models import TrackMatch
        from music_links_bot.core.release_preferences import release_preference_key

        item = {"artist": "Sleep", "title": "Dragonaut"}
        await save_crate(self.context.application.bot_data, USER, [{"item": item}])
        key = release_preference_key(TrackMatch(links={}, **item))

        handled, _ = await self._type(
            "  Тяжело   и медленно ", kind="crate_note", release_key=key
        )

        self.assertTrue(handled)
        annotations = (await self.runtime.get_session(USER)).collection_annotations
        self.assertEqual(annotations[key]["note"], "Тяжело и медленно")
        self.restored.assert_awaited_once()
        self.context.bot.delete_message.assert_awaited_once_with(
            chat_id=USER, message_id=41
        )

    async def test_a_note_for_a_removed_release_is_expired(self) -> None:
        handled, message = await self._type("x", kind="crate_note", release_key="gone")

        self.assertTrue(handled)
        self.assertEqual(self._reply(message), get_text("ru", "ed_expired"))

    async def test_crate_title_is_saved(self) -> None:
        with patch.object(bot_pending, "save_crate_title", new=AsyncMock()) as save:
            await self._type("  Лето   2026 ", kind="crate_title")

        self.assertEqual(save.await_args.args[2], "Лето 2026")
        self.restored.assert_awaited_once()

    async def test_only_the_owner_changes_the_cover_signature(self) -> None:
        with patch(
            "music_links_bot.artwork.brand_settings.save_brand_label", new=AsyncMock()
        ) as save:
            self.context.application.bot_data["admin_chat_id"] = 99
            handled, message = await self._type("@night", kind="brand_label")

        self.assertTrue(handled)
        save.assert_not_awaited()
        message.reply_text.assert_not_awaited()

    async def test_library_search_remembers_the_query(self) -> None:
        with patch(
            "music_links_bot.chat.bot_menu.drafts_view",
            new=AsyncMock(return_value=("Мои посты", None)),
        ):
            await self._type("kyuss", kind="library_search")

        self.assertEqual((await self.runtime.get_session(USER)).draft_query, "kyuss")

    async def test_an_unknown_kind_is_dropped(self) -> None:
        handled, _ = await self._type("x", kind="mystery")

        self.assertFalse(handled)
        self.assertEqual(await self._pending_left(), {})


if __name__ == "__main__":
    unittest.main()
