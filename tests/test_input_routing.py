"""A link sent mid-edit asks "new post, add to collection or keep editing"."""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_release_119_state import RedisModel, ctx

from music_links_bot import bot_lookup_flow
from music_links_bot.bot_runtime import BotRuntime, decode_callback, encode_callback
from music_links_bot.input_routing import (
    collection_input,
    dispatch_input_action,
    guard_input,
)

LINK = "https://open.spotify.com/track/new"


def _message():
    return SimpleNamespace(
        chat=SimpleNamespace(type="private"),
        chat_id=7,
        message_id=3,
        reply_text=AsyncMock(return_value=SimpleNamespace(message_id=4)),
    )


def _query(data: str, *, user_id: int = 7):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id, language_code="ru"),
        message=_message(),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )


class InputRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.context = ctx(RedisModel())
        self.runtime = BotRuntime(self.context.application.bot_data["kv_store"])
        self.context.application.bot_data["runtime"] = self.runtime

    async def _pending(self, **pending) -> None:
        session = await self.runtime.get_session(7)
        session.pending_input = {"created_at": int(time.time()), **pending}
        await self.runtime.save_session(session)

    async def _guard(self, text: str = LINK):
        message = _message()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=7, language_code="ru"),
            effective_message=message,
        )
        return await guard_input(update, self.context, text=text), message

    async def _choice_id(self) -> str:
        await self._pending(kind="intro", draft_id="d")
        handled, message = await self._guard()
        self.assertTrue(handled)
        markup = message.reply_text.await_args.kwargs["reply_markup"]
        return decode_callback(markup.inline_keyboard[0][0].callback_data).payload

    async def _tap(self, action: str, choice_id: str, *, user_id: int = 7):
        query = _query(encode_callback("input", action, choice_id), user_id=user_id)
        await dispatch_input_action(query, self.context, decode_callback(query.data))
        return query

    async def test_replace_needs_exactly_one_link(self) -> None:
        await self._pending(kind="collection_replace", release_key="k")
        handled, message = await self._guard(f"{LINK} {LINK}2")

        self.assertTrue(handled)
        message.reply_text.assert_awaited_once()
        self.assertTrue((await self.runtime.get_session(7)).pending_input)

    async def test_an_expired_prompt_lets_the_link_through(self) -> None:
        await self._pending(kind="intro", created_at=1)
        handled, message = await self._guard()

        self.assertFalse(handled)
        message.reply_text.assert_not_awaited()

    async def test_keep_editing_closes_the_choice_once(self) -> None:
        choice_id = await self._choice_id()

        with patch("music_links_bot.bot_menu.safe_edit", new=AsyncMock()) as edit:
            await self._tap("back", choice_id)
            again = await self._tap("back", choice_id)

        edit.assert_awaited_once()
        self.assertTrue(again.answer.await_args.kwargs.get("show_alert"))
        self.assertTrue((await self.runtime.get_session(7)).pending_input)

    async def test_add_to_collection_runs_the_lookup_in_collection_mode(self) -> None:
        choice_id = await self._choice_id()
        seen: list[tuple[str | None, str]] = []

        async def lookup(update, context):
            seen.append((bot_lookup_flow._INPUT_OVERRIDE.get(), collection_input.get()))

        with patch.object(bot_lookup_flow, "track_lookup_message", new=lookup):
            await self._tap("add", choice_id)

        self.assertEqual(seen, [(LINK, "add")])
        self.assertEqual(collection_input.get(), "")
        self.assertFalse((await self.runtime.get_session(7)).pending_input)

    async def test_someone_elses_choice_is_refused(self) -> None:
        choice_id = await self._choice_id()

        with patch.object(
            bot_lookup_flow, "track_lookup_message", new=AsyncMock()
        ) as lookup:
            query = await self._tap("new", choice_id, user_id=8)

        lookup.assert_not_awaited()
        self.assertTrue(query.answer.await_args.kwargs.get("show_alert"))

    async def test_forged_buttons_are_ignored(self) -> None:
        query = await self._tap("new", "../etc")
        query.answer.assert_awaited_once_with()

    async def test_the_cancel_button_on_a_prompt_ends_the_input(self) -> None:
        from music_links_bot.i18n import get_text
        from music_links_bot.input_routing import input_prompt_markup

        await self._pending(kind="intro", draft_id="d")
        markup = input_prompt_markup("ru")
        query = _query(markup.inline_keyboard[0][0].callback_data)
        query.message.delete = AsyncMock()

        await dispatch_input_action(query, self.context, decode_callback(query.data))

        self.assertEqual(markup.api_kwargs, {"force_reply": True})
        self.assertFalse((await self.runtime.get_session(7)).pending_input)
        query.message.delete.assert_awaited_once()
        query.answer.assert_awaited_once_with(get_text("ru", "input_cancelled"))


if __name__ == "__main__":
    unittest.main()
