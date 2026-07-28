import asyncio
import unittest

from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.provider_runtime import (
    ProviderTask,
    get_cached_lookup,
    lookup_cache_key,
    run_provider_tasks,
    set_cached_lookup,
)


class ProviderRuntimeTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_lookup_cache_uses_memory_without_redis(self) -> None:
        urls = ["https://example.test/b", "https://example.test/a"]
        payload = {"tracks": [{"title": "Dragonaut"}]}

        await set_cached_lookup({}, urls, payload)

        self.assertEqual(await get_cached_lookup({}, list(reversed(urls))), payload)
        self.assertEqual(
            lookup_cache_key(urls),
            lookup_cache_key(list(reversed(urls))),
        )


if __name__ == "__main__":
    unittest.main()
