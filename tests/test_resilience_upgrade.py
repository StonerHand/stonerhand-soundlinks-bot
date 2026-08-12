from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest

from music_links_bot.bot import (
    _duplicate_post_keyboard,
    _send_partial_lookup_status,
)
from music_links_bot.bot_lookup import LookupBundle, SourceStatus
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.bot_storage import load_retry_sources
from music_links_bot.chat_access import check_publish_access
from music_links_bot.models import TrackMatch
from music_links_bot.inline_storage import (
    load_cached_search,
    load_inline_history,
    remember_inline_urls,
    store_cached_search,
)
from music_links_bot.provider_registry import DEFAULT_PROVIDER_REGISTRY
from music_links_bot.provider_runtime import (
    ProviderTask,
    run_provider_tasks_detailed,
)
from music_links_bot.publication_state import (
    find_posted_record,
    mark_posted,
)


class ProviderResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_circuit_opens_after_three_failures_and_skips_next_call(self) -> None:
        runtime = BotRuntime()
        bot_data = {"runtime": runtime}

        async def fail():
            raise TimeoutError

        for _ in range(3):
            await run_provider_tasks_detailed(
                bot_data,
                [ProviderTask("songlink", fail(), [])],
            )

        executed = False

        async def should_not_run():
            nonlocal executed
            executed = True
            return ["unexpected"]

        outcome = await run_provider_tasks_detailed(
            bot_data,
            [ProviderTask("songlink", should_not_run(), [])],
        )

        self.assertFalse(executed)
        self.assertTrue(outcome["songlink"].circuit_open)
        self.assertEqual(outcome["songlink"].value, [])

    async def test_shared_budget_bounds_all_concurrent_providers(self) -> None:
        async def slow():
            await asyncio.sleep(1)
            return "late"

        started = asyncio.get_running_loop().time()
        outcomes = await run_provider_tasks_detailed(
            {},
            [
                ProviderTask("a", slow(), "a-fallback"),
                ProviderTask("b", slow(), "b-fallback"),
            ],
            timeout_seconds=1,
            budget_seconds=0.03,
        )
        elapsed = asyncio.get_running_loop().time() - started

        self.assertLess(elapsed, 0.2)
        self.assertEqual(outcomes["a"].value, "a-fallback")
        self.assertEqual(outcomes["b"].value, "b-fallback")

    def test_registry_routes_urls_without_handler_conditionals(self) -> None:
        grouped = DEFAULT_PROVIDER_REGISTRY.group(
            [
                "https://open.spotify.com/artist/a",
                "https://open.spotify.com/playlist/p",
                "https://youtu.be/video",
                "https://www.nts.live/shows/test",
                "https://open.spotify.com/track/t",
            ]
        )

        self.assertEqual(len(grouped["artists"]), 1)
        self.assertEqual(len(grouped["playlists"]), 1)
        self.assertEqual(len(grouped["youtube"]), 1)
        self.assertEqual(len(grouped["nts"]), 1)
        self.assertEqual(len(grouped["songlink"]), 1)


class _MemoryKV:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    async def set_json(self, key, value, **kwargs):
        del kwargs
        self.values[key] = value
        return True

    async def get_json(self, key):
        value = self.values.get(key)
        return value if isinstance(value, (dict, list)) else None

    async def get(self, key):
        import json

        value = self.values.get(key)
        return json.dumps(value) if value is not None else None


class PublicationStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_record_keeps_old_post_link(self) -> None:
        kv = _MemoryKV()
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"kv_store": kv})
        )
        track = TrackMatch(
            artist="Sleep",
            title="Dragonaut",
            links={"spotify": "https://open.spotify.com/x"},
        )
        message = SimpleNamespace(message_id=42)

        await mark_posted(
            context,
            track,
            message=message,
            target="@stonerhand",
        )
        record = await find_posted_record(context, track)

        self.assertEqual(record["message_id"], 42)
        self.assertEqual(record["url"], "https://t.me/stonerhand/42")

    def test_duplicate_menu_offers_repeat_replace_and_old_post(self) -> None:
        keyboard = _duplicate_post_keyboard(
            "draft1",
            {
                "message_id": 42,
                "url": "https://t.me/stonerhand/42",
            },
            lang="ru",
        )
        labels = [
            button.text
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertIn("Опубликовать снова", labels)
        self.assertIn("Заменить старый пост", labels)
        self.assertIn("Открыть старый пост", labels)
        self.assertIn("Отмена", labels)


class InlineStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_cache_and_personal_history_survive_cold_memory(self) -> None:
        kv = _MemoryKV()
        warm = {"kv_store": kv}
        urls = [
            "https://open.spotify.com/track/a",
            "https://open.spotify.com/track/b",
        ]
        await store_cached_search(warm, "Sleep Dragonaut", urls)
        await remember_inline_urls(warm, 7, urls)

        cold = {"kv_store": kv}
        self.assertEqual(
            await load_cached_search(cold, "Sleep Dragonaut"),
            urls,
        )
        self.assertEqual(await load_inline_history(cold, 7), urls)


class PartialBatchJourneyTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_button_contains_only_failed_sources(self) -> None:
        class Message:
            chat = SimpleNamespace(type="private")

            def __init__(self) -> None:
                self.sent = []

            async def reply_text(self, text, **kwargs):
                self.sent.append((text, kwargs))

        message = Message()
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={}),
        )
        bundle = LookupBundle(
            tracks=[],
            unavailable_urls=["https://open.spotify.com/track/b"],
            videos=[],
            radios=[],
            playlists=[],
            artists=[],
            statuses=[
                SourceStatus(
                    "https://open.spotify.com/track/a",
                    "songlink",
                    "success",
                    label="Sleep — Dragonaut",
                ),
                SourceStatus(
                    "https://open.spotify.com/track/b",
                    "songlink",
                    "unavailable",
                    retryable=True,
                ),
                SourceStatus(
                    "https://open.spotify.com/track/c",
                    "songlink",
                    "not_found",
                ),
            ],
        )

        await _send_partial_lookup_status(
            message,
            context,
            bundle,
            user_id=7,
            lang="ru",
        )

        self.assertEqual(len(message.sent), 1)
        keyboard = message.sent[0][1]["reply_markup"]
        callback = keyboard.inline_keyboard[0][0].callback_data
        retry_id = callback.rsplit("|", 1)[-1]
        stored = await load_retry_sources(context, retry_id)
        self.assertEqual(
            stored["urls"],
            ["https://open.spotify.com/track/b"],
        )

    async def test_retryable_not_found_is_labeled_as_unrecognized(self) -> None:
        class Message:
            chat = SimpleNamespace(type="private")

            def __init__(self) -> None:
                self.sent = []

            async def reply_text(self, text, **kwargs):
                self.sent.append((text, kwargs))

        message = Message()
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
        bundle = LookupBundle(
            tracks=[],
            unavailable_urls=[],
            videos=[],
            radios=[],
            playlists=[],
            artists=[],
            statuses=[
                SourceStatus(
                    "https://open.spotify.com/track/a",
                    "songlink",
                    "not_found",
                    retryable=True,
                )
            ],
        )

        await _send_partial_lookup_status(
            message,
            context,
            bundle,
            user_id=7,
            lang="ru",
        )

        self.assertIn("не удалось распознать", message.sent[0][0])
        self.assertNotIn("сервис временно недоступен", message.sent[0][0])
        self.assertIsNotNone(message.sent[0][1]["reply_markup"])


class PermissionPreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_corrupt_warm_permission_cache_is_ignored(self) -> None:
        class Bot:
            id = 99

            async def get_chat_member(self, **kwargs):
                del kwargs
                return SimpleNamespace(status="creator")

        context = SimpleNamespace(
            bot=Bot(),
            application=SimpleNamespace(
                bot_data={"publish_access_cache": {"@stonerhand": ("bad", None)}}
            ),
        )

        access = await check_publish_access(context, "@stonerhand")

        self.assertTrue(access.allowed)

    async def test_missing_channel_post_right_is_reported_before_send(self) -> None:
        class Bot:
            id = 99

            async def get_chat_member(self, **kwargs):
                del kwargs
                return SimpleNamespace(
                    status="administrator",
                    can_post_messages=False,
                    can_delete_messages=False,
                )

        context = SimpleNamespace(
            bot=Bot(),
            application=SimpleNamespace(bot_data={}),
        )

        access = await check_publish_access(context, "@stonerhand")

        self.assertFalse(access.allowed)
        self.assertIn("право публиковать", access.detail)


if __name__ == "__main__":
    unittest.main()
