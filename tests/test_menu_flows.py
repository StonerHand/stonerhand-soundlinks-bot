"""Main menu buttons: onboarding, owner stats, the post library and sections."""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_release_119_state import RedisModel, ctx

from music_links_bot import bot_menu
from music_links_bot.bot_runtime import BotRuntime, decode_callback, encode_callback
from music_links_bot.i18n import get_text

OWNER = 7


class MenuFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.context = ctx(RedisModel())
        self.context.application.bot_data["admin_chat_id"] = OWNER
        self.context.bot = SimpleNamespace(username="StonerHandBot")
        self.runtime = BotRuntime(self.context.application.bot_data["kv_store"])
        self.context.application.bot_data["runtime"] = self.runtime
        self.edits: list[tuple[str, object]] = []

        async def safe_edit(query, text, keyboard):
            self.edits.append((text, keyboard))

        for name, value in (
            ("safe_edit", safe_edit),
            ("home_view", AsyncMock(return_value=("home", None))),
            ("drafts_view", AsyncMock(return_value=("library", None))),
            ("render_search_view", AsyncMock(return_value=("search", None))),
            ("stats_text", AsyncMock(return_value="12 <posts>")),
        ):
            patcher = patch.object(bot_menu, name, new=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _query(self, user_id: int = OWNER):
        return SimpleNamespace(
            from_user=SimpleNamespace(id=user_id, language_code="ru"),
            message=SimpleNamespace(
                chat_id=user_id,
                reply_text=AsyncMock(return_value=SimpleNamespace(message_id=88)),
            ),
            answer=AsyncMock(),
        )

    async def _tap(self, action: str, payload: str = "", *, user_id: int = OWNER):
        query = self._query(user_id)
        await bot_menu.dispatch_menu_action(
            query,
            self.context,
            decode_callback(encode_callback("menu", action, payload)),
        )
        return query

    async def _session(self):
        return await self.runtime.get_session(OWNER)

    async def test_onboarding_walks_three_steps_then_goes_home(self) -> None:
        await self._tap("onboard2")
        self.assertEqual(self.edits[-1][0], get_text("ru", "onboarding_2"))

        await self._tap("onboarddone")
        self.assertEqual(self.edits[-1][0], "home")
        self.assertTrue((await self._session()).onboarding_seen)

    async def test_stats_are_only_for_the_owner_and_escaped(self) -> None:
        stranger = await self._tap("stats", user_id=99)
        self.assertTrue(stranger.answer.await_args.kwargs.get("show_alert"))
        self.assertEqual(self.edits, [])

        await self._tap("stats")
        self.assertEqual(self.edits[-1][0], "12 &lt;posts&gt;")

    async def test_library_search_prompt_waits_for_a_query(self) -> None:
        query = await self._tap("postsearch")

        query.message.reply_text.assert_awaited_once()
        pending = (await self._session()).pending_input
        self.assertEqual(pending["kind"], "library_search")
        self.assertEqual(pending["prompt_message_id"], 88)
        self.assertEqual(self.edits[-1][0], "search")

    async def test_library_filters_accept_only_known_values(self) -> None:
        await self._tap("postfilter", "published")
        self.assertEqual((await self._session()).draft_filter, "published")
        await self._tap("postfilter", "hacked")
        self.assertEqual((await self._session()).draft_filter, "published")
        self.assertEqual(self.edits[-1][0], "library")

    async def test_clearing_the_search_forgets_it(self) -> None:
        session = await self._session()
        session.draft_query = "kyuss"
        await self.runtime.save_session(session)

        await self._tap("postsearch_clear")

        self.assertEqual((await self._session()).draft_query, "")

    async def test_new_post_drops_a_half_done_input(self) -> None:
        session = await self._session()
        session.pending_input = {"kind": "intro", "created_at": int(time.time())}
        await self.runtime.save_session(session)

        await self._tap("create")

        self.assertEqual((await self._session()).pending_input, {})
        self.assertEqual(self.edits[-1][0], get_text("ru", "create_prompt"))

    async def test_sections_and_privacy_open_their_screens(self) -> None:
        await self._tap("privacy")
        self.assertEqual(self.edits[-1][0], get_text("ru", "privacy_title"))
        await self._tap("help")
        self.assertEqual(self.edits[-1][0], bot_menu.menu_text(bot_menu.MENU_HELP))
        await self._tap("unknown-section")
        self.assertEqual(self.edits[-1][0], bot_menu.menu_text(bot_menu.MENU_START))

    async def test_old_menu_buttons_still_open_the_right_screens(self) -> None:
        for data, expected in (
            (bot_menu.MENU_START, "home"),
            (bot_menu.MENU_DRAFTS, "library"),
            (bot_menu.MENU_RECENT, "search"),
            (bot_menu.MENU_HELP, bot_menu.menu_text(bot_menu.MENU_HELP)),
            ("menu:removed", "home"),
        ):
            with self.subTest(data=data):
                query = self._query()
                query.data = data
                await bot_menu.legacy_menu_callback(
                    SimpleNamespace(callback_query=query), self.context
                )
                self.assertEqual(self.edits[-1][0], expected)


class OwnerSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_counts_this_week_and_open_drafts(self) -> None:
        now = time.time()
        drafts = [
            {"published_at": now - 3600},
            {"published_at": now - 30 * 86400},
            {"item": {"title": "open draft"}},
            {"scheduled_at": now + 3600},
            {"deleted_at": now},
        ]
        session = SimpleNamespace(saved_draft_ids=["a", "b"], recent_draft_ids=["c"])
        with patch(
            "music_links_bot.bot_storage.load_drafts",
            new=AsyncMock(return_value=drafts),
        ):
            text = await bot_menu.owner_summary(
                SimpleNamespace(), session, queued=2, lang="ru"
            )

        self.assertIn("1 пост", text)
        self.assertIn("2", text)
        self.assertIn("1 черновик", text)

    async def test_a_storage_failure_hides_the_summary(self) -> None:
        session = SimpleNamespace(saved_draft_ids=["a"], recent_draft_ids=[])
        with patch(
            "music_links_bot.bot_storage.load_drafts",
            new=AsyncMock(side_effect=RuntimeError("redis down")),
        ):
            text = await bot_menu.owner_summary(
                SimpleNamespace(), session, queued=0, lang="ru"
            )

        self.assertEqual(text, "")

    async def test_queue_count_is_zero_for_guests_and_outages(self) -> None:
        from music_links_bot.publish_queue import QueueStorageError

        self.assertEqual(await bot_menu.queue_count(SimpleNamespace(), False), 0)
        with patch(
            "music_links_bot.publish_queue.load_jobs",
            new=AsyncMock(side_effect=QueueStorageError("down")),
        ):
            self.assertEqual(await bot_menu.queue_count(SimpleNamespace(), True), 0)


if __name__ == "__main__":
    unittest.main()
