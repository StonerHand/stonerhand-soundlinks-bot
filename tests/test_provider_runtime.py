import asyncio
import unittest
from unittest.mock import patch

from music_links_bot import bot_lookup
from music_links_bot.bot_lookup import LookupBundle
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.provider_runtime import (
    ProviderTask,
    get_cached_lookup,
    lookup_cache_key,
    run_provider_tasks,
    set_cached_negative_lookup,
    set_cached_lookup,
)


class ProviderRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_equal_batches_share_one_lookup(self) -> None:
        calls = 0
        release = asyncio.Event()

        async def resolve(_bot_data, _source_urls):
            nonlocal calls
            calls += 1
            await release.wait()
            return LookupBundle([], [], [], [], [], [])

        bot_data: dict = {}
        urls = ["https://example.test/unique-singleflight"]
        with patch.object(bot_lookup, "_resolve_sources_uncached", resolve):
            first = asyncio.create_task(bot_lookup.resolve_sources(bot_data, urls))
            second = asyncio.create_task(bot_lookup.resolve_sources(bot_data, urls))
            await asyncio.sleep(0)
            release.set()
            first_result, second_result = await asyncio.gather(first, second)

        self.assertEqual(calls, 1)
        self.assertIs(first_result, second_result)
        self.assertEqual(bot_data["lookup_inflight"], {})

    async def test_failed_provider_keeps_successful_partial_result(self) -> None:
        async def ok():
            return ["track"]

        async def broken():
            raise TimeoutError

        runtime = BotRuntime()
        results = await run_provider_tasks(
            {"runtime": runtime},
            [
                ProviderTask("music", ok(), []),
                ProviderTask("video", broken(), []),
            ],
        )

        self.assertEqual(results, {"music": ["track"], "video": []})
        snapshot = {item["provider"]: item for item in runtime.provider_snapshot()}
        self.assertTrue(snapshot["music"]["ok"])
        self.assertFalse(snapshot["video"]["ok"])

    async def test_provider_timeout_returns_fallback(self) -> None:
        async def slow():
            await asyncio.sleep(0.05)
            return "late"

        result = await run_provider_tasks(
            {},
            [ProviderTask("slow", slow(), "fallback")],
            timeout_seconds=0.001,
        )
        self.assertEqual(result["slow"], "fallback")

    async def test_lookup_cache_preserves_source_order(self) -> None:
        urls = ["https://example.test/b", "https://example.test/a"]
        payload = {"tracks": [{"title": "Dragonaut"}]}

        await set_cached_lookup({}, urls, payload)

        self.assertEqual(await get_cached_lookup({}, urls), payload)
        self.assertIsNone(await get_cached_lookup({}, list(reversed(urls))))
        self.assertNotEqual(
            lookup_cache_key(urls),
            lookup_cache_key(list(reversed(urls))),
        )

    async def test_negative_lookup_cache_is_short_lived_and_explicit(self) -> None:
        urls = ["https://example.test/not-found-negative"]
        await set_cached_negative_lookup(
            {}, urls, {"statuses": [{"state": "not_found"}]}
        )

        cached = await get_cached_lookup({}, urls)

        self.assertIsNotNone(cached)
        self.assertTrue(cached["_negative"])


if __name__ == "__main__":
    unittest.main()
