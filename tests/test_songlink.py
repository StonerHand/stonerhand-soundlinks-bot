import asyncio
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.models import TrackMatch
from music_links_bot.songlink import (
    SonglinkClient,
    SonglinkError,
    SonglinkLookupError,
    _is_transient_status,
)


class FakeSonglinkClient(SonglinkClient):
    def __init__(self, outcomes: dict[str, TrackMatch | Exception]) -> None:
        super().__init__(user_countries=tuple(outcomes))
        self._outcomes = outcomes
        self.calls = 0

    async def _lookup_track_for_country(self, source_url: str, user_country: str) -> TrackMatch:
        del source_url
        self.calls += 1
        outcome = self._outcomes[user_country]
        if isinstance(outcome, Exception):
            raise outcome

        return outcome


class SonglinkClientTests(unittest.TestCase):
    def test_merge_matches_combines_platform_links(self) -> None:
        client = SonglinkClient(user_countries=("RU", "US"))
        matches = [
            TrackMatch(
                title="Song",
                artist="Artist",
                links={"spotify": "https://spotify.example", "yandexMusic": "https://yandex.example"},
                page_url="https://song.link/song",
                release_format="single",
                kind="song",
            ),
            TrackMatch(
                title="Song",
                artist="Artist",
                links={"appleMusic": "https://apple.example", "youtubeMusic": "https://youtube.example"},
                page_url="https://song.link/song-us",
                release_year="2006",
                kind="song",
            ),
        ]

        merged = client._merge_matches(matches)

        self.assertEqual(
            merged.links,
            {
                "spotify": "https://spotify.example",
                "yandexMusic": "https://yandex.example",
                "appleMusic": "https://apple.example",
                "youtubeMusic": "https://youtube.example",
            },
        )
        self.assertEqual(merged.release_year, "2006")
        self.assertEqual(merged.page_url, "https://song.link/song")
        self.assertEqual(merged.release_format, "single")

    def test_extract_release_year_from_entities_uses_matching_type(self) -> None:
        client = SonglinkClient(user_countries=("US",))

        release_year = client._extract_release_year_from_entities(
            {
                "spotify:song:1": {"type": "track", "releaseDate": "1993-01-01"},
                "spotify:album:1": {"type": "album", "releaseDate": "1992-01-01"},
            },
            "song",
        )

        self.assertEqual(release_year, "1993")

    def test_extract_release_format_detects_ep_and_single(self) -> None:
        client = SonglinkClient(user_countries=("US",))

        self.assertEqual(
            client._extract_release_format({"albumType": "EP"}),
            "ep",
        )
        self.assertEqual(
            client._extract_release_format({"releaseType": "Single"}),
            "single",
        )

    def test_merge_matches_keeps_podcast_kind(self) -> None:
        client = SonglinkClient(user_countries=("US",))
        merged = client._merge_matches(
            [
                TrackMatch(
                    title="Episode",
                    artist="Podcast Show",
                    links={"spotify": "https://spotify.example/episode"},
                    kind="podcast",
                )
            ]
        )

        self.assertEqual(merged.kind, "podcast")

    def test_extract_links_keeps_soundcloud_platform(self) -> None:
        client = SonglinkClient(user_countries=("US",))

        links = client._extract_links(
            {
                "soundcloud": {"url": "https://soundcloud.com/artist/track"},
                "spotify": {"url": "https://open.spotify.com/track/1"},
            }
        )

        self.assertEqual(
            links,
            {
                "spotify": "https://open.spotify.com/track/1",
                "soundcloud": "https://soundcloud.com/artist/track",
            },
        )

    def test_extract_thumbnail_url_prefers_primary_entity(self) -> None:
        client = SonglinkClient(user_countries=("US",))

        thumbnail = client._extract_thumbnail_url(
            {"thumbnailUrl": "https://images.example/cover.jpg"},
            {},
            "song",
        )

        self.assertEqual(thumbnail, "https://images.example/cover.jpg")

    def test_extract_thumbnail_url_falls_back_to_matching_entities(self) -> None:
        client = SonglinkClient(user_countries=("US",))

        thumbnail = client._extract_thumbnail_url(
            {},
            {
                "spotify:album:1": {
                    "type": "album",
                    "thumbnailUrl": "https://images.example/album.jpg",
                },
                "spotify:song:1": {
                    "type": "track",
                    "thumbnailUrl": "https://images.example/song.jpg",
                },
            },
            "song",
        )

        self.assertEqual(thumbnail, "https://images.example/song.jpg")

    def test_merge_matches_keeps_first_thumbnail(self) -> None:
        client = SonglinkClient(user_countries=("RU", "US"))

        merged = client._merge_matches(
            [
                TrackMatch(title="Song", artist="Artist", links={}),
                TrackMatch(
                    title="Song",
                    artist="Artist",
                    links={},
                    thumbnail_url="https://images.example/cover.jpg",
                ),
            ]
        )

        self.assertEqual(merged.thumbnail_url, "https://images.example/cover.jpg")

    def test_normalize_entity_type_supports_podcast_episode_aliases(self) -> None:
        client = SonglinkClient(user_countries=("US",))

        self.assertEqual(client._normalize_entity_type("podcastEpisode"), "podcast")
        self.assertEqual(client._normalize_entity_type("episode"), "podcast")
        self.assertEqual(client._normalize_entity_type("track"), "song")

    def test_transient_status_marks_rate_limit_as_service_error(self) -> None:
        self.assertTrue(_is_transient_status(408))
        self.assertTrue(_is_transient_status(429))
        self.assertTrue(_is_transient_status(500))
        self.assertFalse(_is_transient_status(404))


class SonglinkClientAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_track_coalesces_concurrent_identical_requests(self) -> None:
        client = FakeSonglinkClient(
            {
                "US": TrackMatch(
                    title="Song",
                    artist="Artist",
                    links={
                        "spotify": "https://spotify.example",
                        "appleMusic": "https://apple.example",
                        "youtubeMusic": "https://youtube.example",
                        "deezer": "https://deezer.example",
                    },
                    kind="song",
                ),
            }
        )
        try:
            first, second = await asyncio.gather(
                client.lookup_track("https://open.spotify.com/track/1"),
                client.lookup_track("https://open.spotify.com/track/1"),
            )
        finally:
            await client.aclose()
        self.assertIs(first, second)
        self.assertEqual(client.calls, 1)

    async def test_lookup_track_skips_extra_regions_when_primary_is_complete(self) -> None:
        client = FakeSonglinkClient(
            {
                "RU": TrackMatch(
                    title="Song", artist="Artist", kind="song",
                    links={
                        "spotify": "https://spotify.example",
                        "appleMusic": "https://apple.example",
                        "youtubeMusic": "https://youtube.example",
                        "yandexMusic": "https://yandex.example",
                    },
                ),
                "US": TrackMatch(
                    title="Song", artist="Artist", kind="song",
                    links={"deezer": "https://deezer.example"},
                ),
            }
        )
        try:
            track = await client.lookup_track("https://open.spotify.com/track/1")
        finally:
            await client.aclose()
        self.assertEqual(client.calls, 1)
        self.assertNotIn("deezer", track.links)

    async def test_lookup_track_merges_country_results_in_parallel(self) -> None:
        client = FakeSonglinkClient(
            {
                "RU": TrackMatch(
                    title="Song",
                    artist="Artist",
                    links={"yandexMusic": "https://yandex.example"},
                    kind="song",
                ),
                "US": TrackMatch(
                    title="Song",
                    artist="Artist",
                    links={"spotify": "https://spotify.example"},
                    kind="song",
                ),
            }
        )

        try:
            track = await client.lookup_track("https://open.spotify.com/track/1")
        finally:
            await client.aclose()

        self.assertEqual(
            track.links,
            {
                "yandexMusic": "https://yandex.example",
                "spotify": "https://spotify.example",
            },
        )

    async def test_lookup_track_reuses_cached_result(self) -> None:
        client = FakeSonglinkClient(
            {
                "US": TrackMatch(
                    title="Song",
                    artist="Artist",
                    links={"spotify": "https://spotify.example"},
                    kind="song",
                ),
            }
        )

        try:
            first = await client.lookup_track("https://open.spotify.com/track/1")
            second = await client.lookup_track("https://open.spotify.com/track/1")
        finally:
            await client.aclose()

        self.assertIs(first, second)
        self.assertEqual(client.calls, 1)

    async def test_lookup_track_reuses_cache_across_tracking_query_variants(self) -> None:
        client = FakeSonglinkClient(
            {
                "US": TrackMatch(
                    title="Song",
                    artist="Artist",
                    links={"spotify": "https://spotify.example"},
                    kind="song",
                ),
            }
        )

        try:
            first = await client.lookup_track("https://open.spotify.com/track/1?si=one")
            second = await client.lookup_track("https://open.spotify.com/track/1?si=two")
        finally:
            await client.aclose()

        self.assertIs(first, second)
        self.assertEqual(client.calls, 1)

    async def test_lookup_track_prefers_service_error_when_all_countries_fail(self) -> None:
        client = FakeSonglinkClient(
            {
                "RU": SonglinkLookupError("not found"),
                "US": SonglinkError("service down"),
            }
        )

        try:
            with self.assertRaisesRegex(SonglinkError, "service down") as context:
                await client.lookup_track("https://open.spotify.com/track/1")
        finally:
            await client.aclose()

        self.assertNotIsInstance(context.exception, SonglinkLookupError)


if __name__ == "__main__":
    unittest.main()
