"""Callback routing (bot.py) and collection actions (bot_crate_handlers.py)."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from music_links_bot.chat import bot
from music_links_bot.chat.bot_crate import crate_item_key, load_crate, save_crate
from music_links_bot.chat.bot_crate_handlers import dispatch_crate_action
from music_links_bot.core.i18n import get_text
from music_links_bot.state.bot_runtime import decode_callback, encode_callback


def _query(data: str, *, user_id: int = 7, query_id: str = "q1"):
    message = SimpleNamespace(
        chat_id=user_id,
        message_id=10,
        reply_text=AsyncMock(return_value=SimpleNamespace(message_id=11)),
    )
    return SimpleNamespace(
        id=query_id,
        data=data,
        from_user=SimpleNamespace(id=user_id, language_code="ru"),
        message=message,
        answer=AsyncMock(),
    )


def _context(bot_data: dict | None = None):
    return SimpleNamespace(
        application=SimpleNamespace(bot_data={} if bot_data is None else bot_data),
        bot=SimpleNamespace(username="StonerHandBot"),
    )


class _Runtime:
    def __init__(self, *, fresh: bool = True) -> None:
        self.fresh = fresh
        self.cancel_request_durable = AsyncMock(return_value=True)

    async def claim_callback(self, callback_id: str) -> bool:
        return self.fresh


class CallbackRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def _route(self, data: str, *, runtime=None):
        query = _query(data)
        update = SimpleNamespace(callback_query=query)
        with patch.object(bot, "_runtime", return_value=runtime or _Runtime()):
            await bot.bot_callback(update, _context())
        return query

    async def test_undecodable_data_is_ignored(self) -> None:
        query = await self._route("garbage")
        query.answer.assert_not_awaited()

    async def test_unknown_action_is_answered_and_dropped(self) -> None:
        query = await self._route(encode_callback("menu", "no-such-action"))
        query.answer.assert_awaited_once_with()

    async def test_repeated_tap_is_answered_as_duplicate(self) -> None:
        query = await self._route(
            encode_callback("menu", "postfilter", "all"), runtime=_Runtime(fresh=False)
        )
        self.assertIn("уже", query.answer.await_args.args[0].casefold())

    async def test_each_scope_reaches_its_handler(self) -> None:
        for scope, action, target in (
            ("crate", "open", "_dispatch_crate_action"),
            ("editor", "sv", "_dispatch_editor_action"),
            ("menu", "postfilter", "_dispatch_menu_action"),
        ):
            self.assertIsNotNone(bot.action_spec(scope, action))
            with (
                self.subTest(scope=scope),
                patch.object(bot, target, new=AsyncMock()) as handler,
            ):
                await self._route(encode_callback(scope, action, "x"))
                handler.assert_awaited_once()

    async def test_stop_button_cancels_the_running_lookup(self) -> None:
        runtime = _Runtime()
        query = await self._route(
            encode_callback("progress", "cancel"), runtime=runtime
        )
        runtime.cancel_request_durable.assert_awaited_once_with(7)
        query.answer.assert_awaited_once()

    async def test_playlist_import_from_someone_else_is_refused(self) -> None:
        with (
            patch.object(
                bot, "_load_retry_sources", new=AsyncMock(return_value={"user_id": 99})
            ),
            patch.object(bot, "track_lookup_message", new=AsyncMock()) as lookup,
        ):
            query = await self._route(encode_callback("playlist", "import", "abc"))
        lookup.assert_not_awaited()
        self.assertTrue(query.answer.await_args.kwargs.get("show_alert"))

    async def test_playlist_import_runs_one_lookup_with_the_saved_links(self) -> None:
        seen: list[str | None] = []

        async def lookup(update, context):
            seen.append(bot._INPUT_OVERRIDE.get())

        payload = {"user_id": 7, "urls": ["https://a.example/1", "https://a.example/2"]}
        with (
            patch.object(
                bot, "_load_retry_sources", new=AsyncMock(return_value=payload)
            ),
            patch.object(bot, "_adopt_progress_message"),
            patch.object(bot, "track_lookup_message", new=lookup),
        ):
            await self._route(encode_callback("playlist", "import", "abc"))
        self.assertEqual(seen, ["https://a.example/1\nhttps://a.example/2"])
        self.assertIsNone(bot._INPUT_OVERRIDE.get())

    async def _rerun(self, data: str, **loaders):
        seen: list[tuple] = []

        async def lookup(update, context):
            from music_links_bot.lookup.lookup_recovery import completed_sources

            seen.append(
                (
                    bot._INPUT_OVERRIDE.get(),
                    bot._SEARCH_QUERY_OVERRIDE.get(),
                    bot._BYPASS_INTENT_GUARD.get(),
                    completed_sources.get(),
                )
            )

        patches = [
            patch.object(bot, name, new=AsyncMock(return_value=value))
            for name, value in loaders.items()
        ]
        with (
            patch.object(bot, "_adopt_progress_message"),
            patch.object(bot, "track_lookup_message", new=lookup),
        ):
            for item in patches:
                item.start()
            try:
                query = await self._route(data)
            finally:
                for item in patches:
                    item.stop()
        self.assertIsNone(bot._INPUT_OVERRIDE.get())
        self.assertFalse(bot._BYPASS_INTENT_GUARD.get())
        return query, seen

    async def test_search_pick_runs_the_chosen_result(self) -> None:
        payload = {
            "user_id": 7,
            "query": "kyuss",
            "urls": ["https://a/1", "https://a/2"],
        }
        _, seen = await self._rerun(
            encode_callback("select", "pick", "abc:1"), _load_search_selection=payload
        )
        self.assertEqual(seen, [("https://a/2", "kyuss", True, None)])

    async def test_search_pick_refuses_strangers_and_bad_indexes(self) -> None:
        payload = {"user_id": 99, "query": "kyuss", "urls": ["https://a/1"]}
        for raw in ("abc:0", "abc:-1", "abc:5"):
            with self.subTest(raw=raw):
                query, seen = await self._rerun(
                    encode_callback("select", "pick", raw),
                    _load_search_selection=payload,
                )
                self.assertEqual(seen, [])
                self.assertTrue(query.answer.await_args.kwargs.get("show_alert"))

    async def test_retry_after_a_failure_skips_finished_sources(self) -> None:
        payload = {"user_id": 7, "urls": ["https://a/1"], "completed": {"0": "ok"}}
        _, seen = await self._rerun(
            encode_callback("retry", "failed", "abc"), _load_retry_sources=payload
        )
        self.assertEqual(seen, [("https://a/1", None, True, {"0": "ok"})])

    async def test_retry_without_a_saved_request_is_expired(self) -> None:
        query, seen = await self._rerun(
            encode_callback("retry", "failed", "abc"), _load_retry_sources=None
        )
        self.assertEqual(seen, [])
        self.assertTrue(query.answer.await_args.kwargs.get("show_alert"))


def _entry(artist: str, title: str) -> dict:
    return {"item": {"artist": artist, "title": title, "links": {}}}


class CrateActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.context = _context()
        self.bot_data = self.context.application.bot_data
        await save_crate(
            self.bot_data,
            7,
            [_entry("Kyuss", "Green Machine"), _entry("Sleep", "Dragonaut")],
        )
        self.items = await load_crate(self.bot_data, 7)
        self.edits: list[tuple[str, object]] = []

        async def safe_edit(query, text, keyboard):
            self.edits.append((text, keyboard))

        patcher = patch(
            "music_links_bot.chat.bot_crate_handlers.safe_edit", new=safe_edit
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _act(self, action: str, payload: str = ""):
        query = _query(encode_callback("crate", action, payload))
        await dispatch_crate_action(query, self.context, decode_callback(query.data))
        return query

    async def _titles(self) -> list[str]:
        return [e["item"]["title"] for e in await load_crate(self.bot_data, 7)]

    async def test_old_positional_buttons_are_refused_safely(self) -> None:
        query = await self._act("up", "1")
        self.assertTrue(query.answer.await_args.kwargs.get("show_alert"))
        self.assertEqual(await self._titles(), ["Green Machine", "Dragonaut"])

    async def test_moving_an_item_down_reorders_the_collection(self) -> None:
        await self._act("down", crate_item_key(self.items[0]))
        self.assertEqual(await self._titles(), ["Dragonaut", "Green Machine"])
        self.assertIn("Dragonaut", self.edits[-1][0])

    async def test_removing_an_item_can_be_undone(self) -> None:
        await self._act("remove", crate_item_key(self.items[0]))
        self.assertEqual(await self._titles(), ["Dragonaut"])
        await self._act("undo")
        self.assertEqual(await self._titles(), ["Green Machine", "Dragonaut"])

    async def test_list_uses_the_published_number_style(self) -> None:
        await self._act("open")
        text = self.edits[-1][0]
        self.assertIn("<code>01</code> · <b>Kyuss</b> — Green Machine", text)
        self.assertIn("<code>02</code> · <b>Sleep</b> — Dragonaut", text)

    async def _pending(self) -> dict:
        from music_links_bot.chat.bot_menu import runtime_for

        return (await runtime_for(self.context).get_session(7)).pending_input

    def _key(self, title: str) -> str:
        from music_links_bot.core.models import TrackMatch
        from music_links_bot.state.release_preferences import release_preference_key

        entry = next(e for e in self.items if e["item"]["title"] == title)
        return release_preference_key(TrackMatch(**{"links": {}, **entry["item"]}))

    async def test_add_waits_for_links_with_a_way_back(self) -> None:
        await self._act("add")

        self.assertEqual((await self._pending())["kind"], "collection_links")
        text, keyboard = self.edits[-1]
        self.assertEqual(text, get_text("ru", "crate_links_prompt"))
        self.assertEqual(
            decode_callback(keyboard.inline_keyboard[0][0].callback_data).action,
            "open",
        )

    async def test_replacing_a_vanished_item_is_expired(self) -> None:
        query = await self._act("replace", "no-such-item")
        self.assertTrue(query.answer.await_args.kwargs.get("show_alert"))
        self.assertEqual(self.edits, [])

    async def test_note_asks_for_text_about_that_release(self) -> None:
        query = await self._act("note", self._key("Dragonaut"))

        query.message.reply_text.assert_awaited_once()
        pending = await self._pending()
        self.assertEqual(pending["kind"], "crate_note")
        self.assertEqual(pending["release_key"], self._key("Dragonaut"))

        missing = await self._act("section", "gone")
        self.assertTrue(missing.answer.await_args.kwargs.get("show_alert"))

    async def test_style_and_more_are_their_own_screens(self) -> None:
        await self._act("style")
        self.assertEqual(self.edits[-1][0], get_text("ru", "crate_style_title"))
        await self._act("more")
        self.assertEqual(self.edits[-1][0], get_text("ru", "crate_more_title"))

    async def test_clear_asks_first_then_empties_and_can_be_undone(self) -> None:
        from music_links_bot.chat.bot_crate import crate_revision

        await self._act("clear")
        self.assertEqual(self.edits[-1][0], get_text("ru", "crate_clear_confirm"))
        self.assertEqual(len(await self._titles()), 2)

        await self._act("clear_confirm", crate_revision(self.items))
        self.assertEqual(await self._titles(), [])

        await self._act("undo")
        self.assertEqual(await self._titles(), ["Green Machine", "Dragonaut"])

    async def test_rename_asks_for_a_name(self) -> None:
        query = await self._act("rename")

        self.assertEqual(
            query.message.reply_text.await_args.args[0],
            get_text("ru", "crate_name_prompt"),
        )
        self.assertEqual((await self._pending())["kind"], "crate_title")

    async def test_opening_the_crate_drops_a_half_done_input(self) -> None:
        await self._act("add")
        await self._act("open")
        self.assertEqual(await self._pending(), {})

    async def test_unknown_actions_are_only_answered(self) -> None:
        query = await self._act("teleport")
        query.answer.assert_awaited_once_with()
        self.assertEqual(self.edits, [])

    async def test_preview_shows_the_real_post_with_a_way_back(self) -> None:
        ready = [
            {
                "item": {
                    "artist": artist,
                    "title": title,
                    "links": {"spotify": f"https://open.spotify.com/track/{code}"},
                }
            }
            for artist, title, code in (
                ("Kyuss", "Green Machine", "1a"),
                ("Sleep", "Dragonaut", "2b"),
            )
        ]
        await save_crate(self.bot_data, 7, ready)

        await self._act("preview")

        text, keyboard = self.edits[-1]
        self.assertIn("Green Machine", text)
        self.assertIn("Dragonaut", text)
        last = keyboard.inline_keyboard[-1][0]
        self.assertEqual(decode_callback(last.callback_data).action, "open")
        self.assertTrue(
            any(
                button.switch_inline_query
                for row in keyboard.inline_keyboard
                for button in row
            )
        )


if __name__ == "__main__":
    unittest.main()
