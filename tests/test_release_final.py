import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from telegram import InlineQuery, Update, User
from telegram.ext import Application

from music_links_bot.bot_crate import add_to_crate, load_crate, save_crate
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.bot_storage import delete_draft, load_draft, store_draft
from music_links_bot.draft_model import new_track_draft
from music_links_bot.durable_state import state_scope
from music_links_bot.kvstore import KVStore, KVUnavailableError
from music_links_bot.models import TrackMatch


class SharedStore:
    """Independent workers share serialized values, as with the Redis API."""

    def __init__(self):
        self.values = {}
        self.available = True

    async def get(self, key):
        return self.values.get(key) if self.available else None

    async def set(self, key, value, *, nx=False, **kwargs):
        if not self.available or (nx and key in self.values):
            return False
        self.values[key] = value
        return True

    async def get_json(self, key):
        value = await self.get(key)
        return json.loads(value) if value is not None else None

    async def set_json(self, key, value, **kwargs):
        return await self.set(key, json.dumps(value), **kwargs)

    async def get_json_required(self, key):
        if not self.available:
            raise KVUnavailableError("offline")
        return await self.get_json(key)

    async def delete(self, key):
        if self.available:
            self.values.pop(key, None)


def context(kv):
    return SimpleNamespace(application=SimpleNamespace(bot_data={"kv_store": kv}))


def draft():
    return new_track_draft(
        TrackMatch(
            title="Track",
            artist="Artist",
            links={"spotify": "https://open.spotify.com/track/abc"},
        ),
        chat_id=7,
        lang="ru",
    )


class FinalReleaseStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_crate_does_not_claim_an_eleventh_release_was_added(self):
        from music_links_bot.bot import _add_editor_item_to_crate

        ctx = context(None)
        entries = [
            {"draft_id": str(index), "item": {"title": str(index)}}
            for index in range(10)
        ]
        await save_crate(ctx.application.bot_data, 7, entries)
        request = SimpleNamespace(
            context=ctx,
            user_id=7,
            draft_id="new",
            draft=draft(),
            query=SimpleNamespace(answer=AsyncMock()),
            lang="ru",
        )
        with patch("music_links_bot.bot._restore_editor_card", new_callable=AsyncMock):
            await _add_editor_item_to_crate(request)
        self.assertFalse(request.draft.get("in_crate"))
        self.assertEqual(await load_crate(ctx.application.bot_data, 7), entries)
        self.assertIn("10 позиций", request.query.answer.await_args.args[0])
        self.assertTrue(request.query.answer.await_args.kwargs["show_alert"])

    async def test_storage_failure_answers_inline_query_without_stale_results(self):
        from music_links_bot.bot import _application_error_handler

        query = InlineQuery(
            "q", User(7, "Owner", False, language_code="ru"), "query", ""
        )
        ctx = context(None)
        ctx.error = KVUnavailableError("offline")
        with patch.object(InlineQuery, "answer", new_callable=AsyncMock) as answer:
            await _application_error_handler(Update(1, inline_query=query), ctx)
        self.assertEqual(answer.await_args.args, ([],))
        self.assertEqual(answer.await_args.kwargs["cache_time"], 0)
        self.assertTrue(answer.await_args.kwargs["is_personal"])
        self.assertIn("Временный сбой", answer.await_args.kwargs["button"].text)

    async def test_session_cache_is_limited_to_one_update(self):
        kv = SharedStore()
        runtime = BotRuntime(kv)
        with state_scope():
            session = await runtime.get_session(7)
            session.last_query = "Unsaved in-flight input"
            self.assertIs(await runtime.get_session(7), session)
            other = BotRuntime(kv)
            external = await other.get_session(7)
            external.default_hashtags = "off"
            await other.save_session(external)
            self.assertEqual(
                (await runtime.get_session(7)).last_query, session.last_query
            )
        with state_scope():
            fresh = await runtime.get_session(7)
            self.assertEqual(fresh.default_hashtags, "off")
            self.assertEqual(fresh.last_query, "")

    async def test_outage_does_not_restore_a_cached_draft(self):
        kv = SharedStore()
        worker = context(kv)
        await store_draft(worker, "card", draft())
        kv.available = False
        with self.assertRaises(KVUnavailableError):
            await load_draft(worker, "card")

    async def test_failed_initial_session_read_does_not_run_the_action(self):
        from music_links_bot.bot_preferences import LocalizedApplication

        kv = SharedStore()
        kv.available = False
        app = (
            Application.builder()
            .application_class(LocalizedApplication)
            .token("test")
            .build()
        )
        app.bot_data["runtime"] = BotRuntime(kv)
        update = Update(
            1,
            inline_query=InlineQuery("q", User(7, "Owner", False), "query", ""),
        )
        with (
            patch.object(
                Application, "process_update", new_callable=AsyncMock
            ) as dispatch,
            patch.object(Application, "process_error", new_callable=AsyncMock) as error,
        ):
            await app.process_update(update)
        dispatch.assert_not_awaited()
        self.assertIsInstance(error.await_args.kwargs["error"], KVUnavailableError)

    async def test_untrusted_artwork_does_not_start_an_http_request(self):
        from music_links_bot.branding import build_branded_cover

        for url in (
            "http://127.0.0.1/cover",
            "https://internal.local/cover",
            "https://evil.example/cover",
            "https://i.scdn.co.evil.example/cover",
        ):
            with (
                self.subTest(url=url),
                patch("music_links_bot.branding.httpx.AsyncClient") as client,
            ):
                self.assertIsNone(await build_branded_cover(url, label="test"))
                client.assert_not_called()

    async def test_required_redis_reads_and_deletes_surface_transport_errors(self):
        store = KVStore("https://redis.example", "test")
        await store._client.aclose()
        store._client = httpx.AsyncClient(
            base_url="https://redis.example",
            transport=httpx.MockTransport(lambda _: httpx.Response(503)),
        )
        try:
            for operation in (
                lambda: store.get_required("key"),
                lambda: store.mget_json_required(["key"]),
                lambda: store.delete_required("key"),
            ):
                with self.assertRaises(KVUnavailableError):
                    await operation()
        finally:
            await store.aclose()

    async def test_warm_worker_reads_latest_draft_and_does_not_revive_deleted_one(self):
        kv = SharedStore()
        first, second = context(kv), context(kv)
        await store_draft(first, "card", draft())
        await load_draft(second, "card")
        changed = await load_draft(first, "card")
        changed["prefix"] = "Новая подводка"
        await store_draft(first, "card", changed)
        self.assertEqual((await load_draft(second, "card"))["prefix"], "Новая подводка")
        await delete_draft(first, "card")
        self.assertIsNone(await load_draft(second, "card"))

    async def test_warm_session_keeps_preferences_saved_by_another_worker(self):
        kv = SharedStore()
        first, second = BotRuntime(kv), BotRuntime(kv)
        await first.get_session(7)
        session = await second.get_session(7)
        session.preferred_lang = "en"
        await second.save_session(session)
        session = await first.get_session(7)
        session.default_hashtags = "off"
        await first.save_session(session)
        saved = await second.get_session(7)
        self.assertEqual((saved.preferred_lang, saved.default_hashtags), ("en", "off"))

    async def test_warm_crate_addition_preserves_other_workers_entries(self):
        kv = SharedStore()
        first, second = {"kv_store": kv}, {"kv_store": kv}
        await load_crate(first, 7)
        await add_to_crate(second, 7, draft_id="one", item={"title": "One"})
        await add_to_crate(first, 7, draft_id="two", item={"title": "Two"})
        self.assertEqual(
            [entry["draft_id"] for entry in await load_crate(second, 7)], ["one", "two"]
        )

    async def test_outage_never_grants_a_local_publication_lock(self):
        kv = SharedStore()
        runtime = BotRuntime(kv)
        kv.available = False
        self.assertIsNone(await runtime.acquire_action("7:publish:card"))

    async def test_durable_writes_do_not_report_success_during_outage(self):
        kv = SharedStore()
        runtime = BotRuntime(kv)
        session = await runtime.get_session(7)
        kv.available = False
        for operation in (
            lambda: store_draft(context(kv), "card", draft()),
            lambda: runtime.save_session(session),
            lambda: save_crate({"kv_store": kv}, 7, []),
        ):
            with self.assertRaises(KVUnavailableError):
                await operation()
