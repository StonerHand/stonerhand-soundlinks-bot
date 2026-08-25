from __future__ import annotations

import unittest

from music_links_bot.release_hubs import (
    canonical_release_hub_url,
    is_universal_release_url,
    resolve_release_hub_url,
)


class ReleaseHubTests(unittest.TestCase):
    def test_spotify_track_maps_to_songlink(self) -> None:
        self.assertEqual(
            canonical_release_hub_url(
                "https://open.spotify.com/track/0SOUQwfAlpvurIBdPurgrd?si=tracking"
            ),
            "https://song.link/s/0SOUQwfAlpvurIBdPurgrd",
        )

    def test_spotify_album_maps_to_albumlink(self) -> None:
        self.assertEqual(
            canonical_release_hub_url(
                "https://open.spotify.com/album/4m2880jivSbbyEGAKfITCa",
                release_kind="album",
            ),
            "https://album.link/s/4m2880jivSbbyEGAKfITCa",
        )

    def test_spotify_podcast_maps_to_podslink(self) -> None:
        self.assertEqual(
            canonical_release_hub_url("https://open.spotify.com/show/abc?si=tracking"),
            "https://pods.link/s/abc",
        )

    def test_apple_track_maps_to_songlink(self) -> None:
        self.assertEqual(
            canonical_release_hub_url(
                "https://music.apple.com/us/album/example/123?i=456"
            ),
            "https://song.link/i/456",
        )

    def test_existing_odesli_page_is_preserved(self) -> None:
        self.assertTrue(is_universal_release_url("https://song.link/s/track"))
        self.assertEqual(
            resolve_release_hub_url(
                "https://song.link/s/track?utm_source=telegram",
                {"spotify": "https://open.spotify.com/track/track"},
            ),
            "https://song.link/s/track",
        )

    def test_stale_spotify_page_url_is_repaired_from_links(self) -> None:
        self.assertEqual(
            resolve_release_hub_url(
                "https://open.spotify.com/track/track?si=old",
                {"spotify": "https://open.spotify.com/track/track?si=new"},
            ),
            "https://song.link/s/track",
        )

    def test_unsupported_source_does_not_create_broken_nested_url(self) -> None:
        self.assertIsNone(
            canonical_release_hub_url("https://soundcloud.com/artist/track")
        )
