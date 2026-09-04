import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.kvstore import KVStore, KVUnavailableError
from music_links_bot.search import (
    SearchClient,
    SearchLookupError,
    _extract_matching_genre,
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
                    "collectionName": "Paranoid",
                    "releaseDate": "1970-09-18T00:00:00Z",
                    "kind": "song",
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
        self.assertEqual(candidates[0].album, "Paranoid")
        self.assertEqual(candidates[0].year, "1970")
        self.assertEqual(candidates[0].kind, "song")
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

    def test_genre_requires_matching_artist_and_release(self) -> None:
        payload = {
            "results": [
                {
                    "artistName": "Donell Jones",
                    "trackName": "Knocks Me Off My Feet",
                    "primaryGenreName": "R&B/Soul",
                },
                {
                    "artistName": "Knocked Loose",
                    "trackName": "Don't Reach for Me",
                    "primaryGenreName": "Metal",
                },
            ]
        }

        self.assertEqual(
            _extract_matching_genre(
                payload,
                artist="Knocked Loose",
                title="Don’t Reach For Me",
            ),
            "Metal",
        )

    def test_genre_is_omitted_when_only_artist_or_title_matches(self) -> None:
        payload = {
            "results": [
                {
                    "artistName": "Knocked Loose",
                    "trackName": "Take Me Home",
                    "primaryGenreName": "Metal",
                },
                {
                    "artistName": "Someone Else",
                    "trackName": "Don't Reach For Me",
                    "primaryGenreName": "R&B/Soul",
                },
            ]
        }

        self.assertIsNone(
            _extract_matching_genre(
                payload,
                artist="Knocked Loose",
                title="Don't Reach For Me",
            )
        )

    def test_album_genre_can_match_collection_name(self) -> None:
        payload = {
            "results": [
                {
                    "artistName": "Black Sabbath",
                    "trackName": "War Pigs",
                    "collectionName": "Paranoid",
                    "primaryGenreName": "Heavy Metal",
                }
            ]
        }

        self.assertEqual(
            _extract_matching_genre(
                payload,
                artist="Black Sabbath",
                title="Paranoid",
            ),
            "Heavy Metal",
        )


class SearchCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_search_candidate_survives_songlink_outage(self) -> None:
        apple_url = (
            "https://music.apple.com/us/album/rickets/1099843198?i=1099843246&uo=4"
        )

        class ResponseStub:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "results": [
                        {
                            "trackViewUrl": apple_url,
                            "trackName": "Rickets",
                            "artistName": "Deftones",
                            "collectionName": "Around the Fur",
                            "artworkUrl100": (
                                "https://is1-ssl.mzstatic.com/image/"
                                "thumb/Music/100x100bb.jpg"
                            ),
                            "releaseDate": "1997-10-28T08:00:00Z",
                            "kind": "song",
                        }
                    ]
                }

        class ClientStub:
            calls = 0

            async def get(self, path: str, **kwargs):
                del path, kwargs
                self.calls += 1
                return ResponseStub()

            async def aclose(self) -> None:
                return None

        class MusicBrainzStub:
            async def lookup_spotify_release(
                self, artist: str, title: str, *, kind: str = "song"
            ) -> str:
                self.request = (artist, title, kind)
                return "https://open.spotify.com/track/7Ca5yTC81P0AtRnNKHKzwJ"

        musicbrainz = MusicBrainzStub()
        search = SearchClient(musicbrainz_client=musicbrainz)
        await search._client.aclose()
        fake = ClientStub()
        search._client = fake
        try:
            candidates = await search.search_release_candidates("Deftones — Rickets")
            track = await search.lookup_release_fallback(candidates[0].url)
        finally:
            await search.aclose()

        self.assertEqual(fake.calls, 1)
        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.artist, "Deftones")
        self.assertEqual(track.title, "Rickets")
        self.assertEqual(track.release_format, "Around the Fur")
        self.assertEqual(track.release_year, "1997")
        self.assertEqual(
            track.links,
            {
                "appleMusic": apple_url,
                "spotify": ("https://open.spotify.com/track/7Ca5yTC81P0AtRnNKHKzwJ"),
            },
        )
        self.assertEqual(
            track.page_url,
            "https://song.link/s/7Ca5yTC81P0AtRnNKHKzwJ",
        )
        self.assertEqual(
            musicbrainz.request,
            ("Deftones", "Rickets", "song"),
        )
        self.assertIn("1200x1200bb", track.thumbnail_url or "")

    async def test_direct_apple_url_repairs_empty_process_cache(self) -> None:
        apple_url = "https://music.apple.com/us/album/rickets/1099843198?i=1099843246"

        class ResponseStub:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "results": [
                        {
                            "trackViewUrl": apple_url,
                            "trackName": "Rickets",
                            "artistName": "Deftones",
                            "collectionName": "Around the Fur",
                            "kind": "song",
                        }
                    ]
                }

        class ClientStub:
            def __init__(self) -> None:
                self.path = ""
                self.params: dict[str, str] = {}

            async def get(self, path: str, **kwargs):
                self.path = path
                self.params = kwargs["params"]
                return ResponseStub()

            async def aclose(self) -> None:
                return None

        class MusicBrainzStub:
            async def lookup_spotify_release(
                self, artist: str, title: str, *, kind: str = "song"
            ) -> None:
                del artist, title, kind
                return None

        search = SearchClient(musicbrainz_client=MusicBrainzStub())
        await search._client.aclose()
        fake = ClientStub()
        search._client = fake
        try:
            track = await search.lookup_release_fallback(apple_url)
        finally:
            await search.aclose()

        self.assertIsNotNone(track)
        self.assertEqual(fake.path, "/lookup")
        self.assertEqual(fake.params["id"], "1099843246")
        self.assertEqual(track.title if track else None, "Rickets")
        self.assertEqual(track.links if track else None, {"appleMusic": apple_url})
        self.assertIsNone(track.page_url if track else "missing")

    async def test_parallel_equal_searches_share_one_request(self) -> None:
        class ResponseStub:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "results": [
                        {
                            "trackViewUrl": "https://music.apple.com/track/1",
                            "trackName": "Dragonaut",
                            "artistName": "Sleep",
                        }
                    ]
                }

        class ClientStub:
            def __init__(self) -> None:
                self.calls = 0
                self.release = asyncio.Event()

            async def get(self, *args, **kwargs):
                del args, kwargs
                self.calls += 1
                await self.release.wait()
                return ResponseStub()

            async def aclose(self) -> None:
                return None

        search = SearchClient()
        await search._client.aclose()
        fake = ClientStub()
        search._client = fake
        first = asyncio.create_task(search.search_release_candidates("Sleep Dragonaut"))
        second = asyncio.create_task(
            search.search_release_candidates(" sleep  dragonaut ")
        )
        await asyncio.sleep(0)
        fake.release.set()
        try:
            first_result, second_result = await asyncio.gather(first, second)
            self.assertEqual(fake.calls, 1)
            self.assertEqual(first_result, second_result)
        finally:
            await search.aclose()

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
    def test_required_json_write_surfaces_storage_failure(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock

        store = KVStore("https://kv.example", "token")
        store._command_or_raise = AsyncMock(side_effect=KVUnavailableError("offline"))
        try:
            with self.assertRaises(KVUnavailableError):
                asyncio.run(store.set_json_required("queue", [{"id": "1"}]))
        finally:
            asyncio.run(store.aclose())

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

    def test_mget_json_decodes_each_slot_independently(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock

        store = KVStore("https://kv.example", "token")
        store.mget = AsyncMock(return_value=['{"ok": true}', "broken", None])
        try:
            self.assertEqual(
                asyncio.run(store.mget_json(["one", "two", "three"])),
                [{"ok": True}, None, None],
            )
        finally:
            asyncio.run(store.aclose())
