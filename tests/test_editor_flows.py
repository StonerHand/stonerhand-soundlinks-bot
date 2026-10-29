"""Editor flows people use every day: delete and undo, send, publish, templates."""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_release_119_state import RedisModel, ctx, draft, track

from music_links_bot.core.i18n import get_text
from music_links_bot.editor import bot_editor, editor_delivery, editor_screen
from music_links_bot.state.bot_runtime import BotRuntime

OWNER = 7


class _EditorCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.context = ctx(RedisModel())
        self.context.application.bot_data["admin_chat_id"] = OWNER
        self.runtime = BotRuntime(self.context.application.bot_data["kv_store"])
        self.context.application.bot_data["runtime"] = self.runtime
        self.draft = draft()
        self.mocks: dict[str, AsyncMock] = {}
        for name in (
            "_edit_editor_message",
            "_store_draft",
            "_try_delete_message",
            "_restore_editor_card",
            "_show_editor_delivery_success",
            "_show_duplicate_editor_post",
            "_delete_duplicate_editor_post",
            "_finish_editor_publish",
            "_handle_editor_navigation",
        ):
            self.mocks[name] = self._patch(name, AsyncMock())

    def _patch(self, name: str, value):
        """Replace a helper wherever the editor modules look it up."""
        for module in (bot_editor, editor_delivery, editor_screen):
            if hasattr(module, name):
                patcher = patch.object(module, name, new=value)
                patcher.start()
                self.addCleanup(patcher.stop)
        return value

    def _query(self, user_id: int = OWNER):
        return SimpleNamespace(
            from_user=SimpleNamespace(id=user_id, language_code="ru"),
            message=SimpleNamespace(chat_id=user_id, message_id=5),
            answer=AsyncMock(),
        )

    def _request(self, action: str, *, user_id: int = OWNER):
        return editor_screen.EditorActionRequest(
            query=self._query(user_id),
            context=self.context,
            action=action,
            draft_id="d1",
            draft=self.draft,
            lang="ru",
            track=track(),
        )

    def _edited_text(self) -> str:
        return self.mocks["_edit_editor_message"].await_args.args[3]


class DeleteAndUndoTests(_EditorCase):
    async def _act(self, action: str, query=None):
        query = query or self._query()
        handled = await bot_editor._handle_editor_lifecycle(
            query,
            self.context,
            action=action,
            draft_id="d1",
            draft=self.draft,
            lang="ru",
        )
        return handled, query

    async def test_delete_asks_first_then_removes_and_frees_the_session(self) -> None:
        session = await self.runtime.get_session(OWNER)
        session.active_draft_id = "d1"
        await self.runtime.save_session(session)

        await self._act("d")
        self.assertEqual(self._edited_text(), get_text("ru", "ed_delete_confirm"))
        self.assertNotIn("deleted_at", self.draft)

        await self._act("dc")
        self.assertIn("deleted_at", self.draft)
        self.assertEqual(self._edited_text(), get_text("ru", "ed_deleted"))
        self.assertEqual((await self.runtime.get_session(OWNER)).active_draft_id, "")

    async def test_undo_restores_the_card_in_time(self) -> None:
        self._patch("_render_track_draft", lambda *a, **k: ("card", None))
        self.draft["deleted_at"] = int(time.time())

        await self._act("du")

        self.assertNotIn("deleted_at", self.draft)
        self.assertEqual(self._edited_text(), "card")

    async def test_a_late_undo_is_refused_and_the_notice_removed(self) -> None:
        self.draft["deleted_at"] = int(time.time()) - bot_editor.DRAFT_UNDO_SECONDS - 5

        _, query = await self._act("du")

        self.assertTrue(query.answer.await_args.kwargs.get("show_alert"))
        self.mocks["_try_delete_message"].assert_awaited_once_with(query.message)
        self.assertIn("deleted_at", self.draft)

    async def test_other_actions_are_not_lifecycle(self) -> None:
        handled, _ = await self._act("m")
        self.assertFalse(handled)


class PrimaryActionTests(_EditorCase):
    async def test_only_the_owner_can_publish(self) -> None:
        publish = self._patch("_publish_draft", AsyncMock())
        request = self._request("pc", user_id=99)

        await editor_delivery._run_primary_editor_action(request)

        publish.assert_not_awaited()
        self.assertTrue(request.query.answer.await_args.kwargs.get("show_alert"))
        self.mocks["_restore_editor_card"].assert_awaited_once_with(request)

    async def test_a_repeat_post_shows_the_duplicate_instead(self) -> None:
        self._patch("_find_posted_record", AsyncMock(return_value={"id": 1}))
        publish = self._patch("_publish_draft", AsyncMock())

        await editor_delivery._run_primary_editor_action(self._request("pc"))

        publish.assert_not_awaited()
        self.mocks["_show_duplicate_editor_post"].assert_awaited_once()

    async def test_replace_publishes_again_and_removes_the_old_post(self) -> None:
        self._patch("_find_posted_record", AsyncMock(return_value={"id": 1}))
        self._patch("_publish_draft", AsyncMock(return_value=SimpleNamespace()))
        request = self._request("x")

        await editor_delivery._run_primary_editor_action(request)

        self.assertTrue(self.draft["repeat_delivery"])
        self.mocks["_finish_editor_publish"].assert_awaited_once()
        self.mocks["_delete_duplicate_editor_post"].assert_awaited_once()

    async def test_sending_to_yourself_marks_the_draft_sent(self) -> None:
        self._patch("_deliver_draft", AsyncMock(return_value=SimpleNamespace()))
        request = self._request("s", user_id=42)

        await editor_delivery._run_primary_editor_action(request)

        self.assertIn("sent_at", self.draft)
        self.mocks["_show_editor_delivery_success"].assert_awaited_once_with(request)
        self.assertFalse(request.query.answer.await_args.kwargs.get("show_alert"))

    async def test_a_failed_send_brings_the_card_back(self) -> None:
        self._patch("_deliver_draft", AsyncMock(return_value=None))
        request = self._request("s")

        await editor_delivery._run_primary_editor_action(request)

        self.assertNotIn("sent_at", self.draft)
        self.assertTrue(request.query.answer.await_args.kwargs.get("show_alert"))
        self.mocks["_restore_editor_card"].assert_awaited_once_with(request)


class NamedTemplateTests(_EditorCase):
    async def test_applying_a_template_reopens_the_templates_screen(self) -> None:
        self._patch("apply_named_preset", AsyncMock(return_value=True))

        handled = await bot_editor._handle_named_editor_template(self._request("ta1"))

        self.assertTrue(handled)
        navigation = self.mocks["_handle_editor_navigation"].await_args.kwargs
        self.assertEqual(navigation["action"], "tp")
        self.assertEqual(
            navigation["answer_text"], get_text("ru", "ed_template_applied")
        )

    async def test_a_missing_template_is_reported_as_expired(self) -> None:
        self._patch("delete_named_preset", AsyncMock(return_value=False))
        request = self._request("td2")

        await bot_editor._handle_named_editor_template(request)

        self.assertEqual(
            request.query.answer.await_args.args[0], get_text("ru", "ed_expired")
        )
        self.mocks["_handle_editor_navigation"].assert_not_awaited()

    async def test_other_actions_are_left_alone(self) -> None:
        self.assertFalse(
            await bot_editor._handle_named_editor_template(self._request("tax"))
        )


if __name__ == "__main__":
    unittest.main()
