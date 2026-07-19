import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.kvstore import KVStore
from music_links_bot.search import (
    SearchClient,
    SearchLookupError,
    _extract_release_candidates,
    normalize_search_query,
)


class SearchQueryTests(unittest.TestCase):
    def test_normalize_collapses_whitespace_and_trims(self) -> None:
        self.assertEqual(
            normalize_search_query("  black   sabbath\nparanoid "),
            "black sabbath paranoid",
        )

    def test_normalize_rejects_short_and_command_queries(self) -> None:
        self.assertIsNone(normalize_search_query("a"))
        self.assertIsNone(normalize_search_query("/start"))

    def test_normalize_caps_query_length(self) -> None:
        normalized = normalize_search_query("x" * 500)
        self.assertIsNotNone(normalized)
        self.assertLessEqual(len(normalized), 120)

    def test_extract_release_candidates_prefer_first_result(self) -> None:
        payload = {
            "results": [
                {"collectionViewUrl": "https://music.apple.com/album/1"},
                {"trackViewUrl": "https://music.apple.com/track/2"},
            ]
        }

        candidates = _extract_release_candidates(payload)
        self.assertEqual(candidates[0].url, "https://music.apple.com/album/1")

    def test_extract_release_candidates_dedupes_and_caps(self) -> None:
        payload = {
            "results": [
                {
                    "trackViewUrl": "https://music.apple.com/track/1",
                    "trackName": "Paranoid",
                    "artistName": "Black Sabbath",
                    "artworkUrl100": "https://images.example/1.jpg",
                },
                {"trackViewUrl": "https://music.apple.com/track/1"},
                {"trackViewUrl": "https://music.apple.com/track/2"},
                {"trackViewUrl": "https://music.apple.com/track/3"},
                {"trackViewUrl": "https://music.apple.com/track/4"},
            ]
        }

        candidates = _extract_release_candidates(payload)

        self.assertEqual(len(candidates), 3)
        self.assertEqual(candidates[0].title, "Paranoid")
        self.assertEqual(candidates[0].artist, "Black Sabbath")
        self.assertEqual(candidates[0].artwork_url, "https://images.example/1.jpg")
        self.assertEqual(
            [candidate.url for candidate in candidates],
            [
                "https://music.apple.com/track/1",
                "https://music.apple.com/track/2",
                "https://music.apple.com/track/3",
            ],
        )

    def test_extract_release_candidates_handle_malformed_payloads(self) -> None:
        self.assertEqual(_extract_release_candidates(None), [])
        self.assertEqual(_extract_release_candidates({"results": "nope"}), [])
        self.assertEqual(
            _extract_release_candidates({"results": [{"trackViewUrl": 5}]}),
            [],
        )


class SearchCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_miss_is_not_requested_twice(self) -> None:
        class ResponseStub:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"results": []}

        class ClientStub:
            calls = 0

            async def get(self, *args, **kwargs):
                del args, kwargs
                self.calls += 1
                return ResponseStub()

            async def aclose(self) -> None:
                return None

        search = SearchClient()
        await search._client.aclose()
        fake = ClientStub()
        search._client = fake
        try:
            with self.assertRaises(SearchLookupError):
                await search.search_release_candidates("nothing here")
            with self.assertRaises(SearchLookupError):
                await search.search_release_candidates("nothing here")
            self.assertEqual(fake.calls, 1)
        finally:
            await search.aclose()


class KVStoreTests(unittest.TestCase):
    def test_from_env_returns_none_without_credentials(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(KVStore.from_env())

    def test_from_env_accepts_vercel_kv_aliases(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(
            os.environ,
            {
                "KV_REST_API_URL": "https://kv.example",
                "KV_REST_API_TOKEN": "token",
            },
            clear=True,
        ):
            store = KVStore.from_env()
            self.assertIsNotNone(store)


if __name__ == "__main__":
    unittest.main()


class PreviewExtractionTests(unittest.TestCase):
    def test_candidates_carry_preview_url(self) -> None:
        from music_links_bot.search import _extract_preview_url

        payload = {
            "results": [
                {
                    "trackViewUrl": "https://music.apple.com/track/1",
                    "trackName": "Paranoid",
                    "artistName": "Black Sabbath",
                    "previewUrl": "https://audio.example/p.m4a",
                }
            ]
        }

        candidates = _extract_release_candidates(payload)
        self.assertEqual(candidates[0].preview_url, "https://audio.example/p.m4a")
        self.assertEqual(_extract_preview_url(payload), "https://audio.example/p.m4a")

    def test_preview_url_ignores_non_http_values(self) -> None:
        from music_links_bot.search import _extract_preview_url

        payload = {"results": [{"previewUrl": 42}, {"previewUrl": "ftp://x"}]}
        self.assertIsNone(_extract_preview_url(payload))


class KVStoreShapeTests(unittest.TestCase):
    def test_increment_window_sets_ttl_atomically(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock

        store = KVStore("https://kv.example", "token")
        store._command = AsyncMock(return_value=3)
        try:
            self.assertEqual(
                asyncio.run(store.increment_window("rate:key", ttl_seconds=62)), 3
            )
            command = store._command.await_args.args[0]
            self.assertEqual(command[0], "EVAL")
            self.assertEqual(command[-2:], ["rate:key", "62"])
        finally:
            asyncio.run(store.aclose())

    def test_delete_if_value_uses_atomic_compare_and_delete(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock

        store = KVStore("https://kv.example", "token")
        store._command = AsyncMock(return_value=1)
        try:
            self.assertTrue(asyncio.run(store.delete_if_value("lock", "owner")))
            command = store._command.await_args.args[0]
            self.assertEqual(command[0], "EVAL")
            self.assertEqual(command[-2:], ["lock", "owner"])
        finally:
            asyncio.run(store.aclose())

    def test_mget_with_no_keys_returns_empty_list(self) -> None:
        import asyncio

        store = KVStore("https://kv.example", "token")
        try:
            self.assertEqual(asyncio.run(store.mget([])), [])
        finally:
            asyncio.run(store.aclose())
