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

    async def _lookup_track_for_country(self, source_url: str, user_country: str) -> TrackMatch:
        del source_url
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

    async def test_lookup_track_prefers_service_error_when_all_countries_fail(self) -> None:
        client = FakeSonglinkClient(
            {
                "RU": SonglinkLookupError("not found"),
                "US": SonglinkError("service down"),
            }
        )

        try:
            with self.assertRaises(SonglinkError):
                await client.lookup_track("https://open.spotify.com/track/1")
        finally:
            await client.aclose()


if __name__ == "__main__":
    unittest.main()
