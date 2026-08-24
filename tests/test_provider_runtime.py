import asyncio
import unittest
from unittest.mock import patch

from music_links_bot import bot_lookup
from music_links_bot.bot_lookup import LookupBundle
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.models import VideoMatch
from music_links_bot.provider_runtime import (
    ProviderOutcome,
    ProviderTask,
    get_cached_lookup,
    lookup_cache_key,
    run_provider_tasks,
    set_cached_lookup,
    set_cached_negative_lookup,
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

    async def test_task_specific_timeout_can_preserve_longer_batch_work(self) -> None:
        async def slightly_slow():
            await asyncio.sleep(0.01)
            return "complete"

        result = await run_provider_tasks(
            {},
            [
                ProviderTask(
                    "batch",
                    slightly_slow(),
                    "fallback",
                    timeout_seconds=0.05,
                )
            ],
            timeout_seconds=0.001,
        )

        self.assertEqual(result["batch"], "complete")

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

    async def test_lookup_cache_ignores_tracking_query_variants(self) -> None:
        first = ["https://open.spotify.com/track/abc?si=one&utm_source=telegram"]
        second = ["https://open.spotify.com/track/abc?si=two"]
        payload = {"tracks": [{"title": "Dragonaut"}]}

        await set_cached_lookup({}, first, payload)

        self.assertEqual(lookup_cache_key(first), lookup_cache_key(second))
        self.assertEqual(await get_cached_lookup({}, second), payload)

    async def test_custom_client_bundles_do_not_share_process_cache(self) -> None:
        urls = ["https://open.spotify.com/track/cache-isolation"]
        first = {"songlink_client": object()}
        second = {"songlink_client": object()}

        await set_cached_lookup(first, urls, {"tracks": [{"title": "First"}]})

        self.assertIsNone(await get_cached_lookup(second, urls))
        self.assertEqual(
            await get_cached_lookup(first, urls),
            {"tracks": [{"title": "First"}]},
        )

    async def test_provider_statuses_match_urls_not_shortened_list_positions(
        self,
    ) -> None:
        urls = [
            "https://youtu.be/first",
            "https://youtu.be/missing",
            "https://youtu.be/third",
        ]
        videos = [
            VideoMatch("First", "A", urls[0]),
            VideoMatch("Third", "C", urls[2]),
        ]
        outcome = ProviderOutcome("youtube", videos, True, 1)

        statuses = bot_lookup._provider_statuses(
            "youtube", urls, videos, {"youtube": outcome}
        )

        self.assertEqual(
            [status.state for status in statuses],
            ["success", "not_found", "success"],
        )
        self.assertEqual(statuses[2].label, "C — Third")

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
