from __future__ import annotations

import json
import unittest

from music_links_bot.spotify import SpotifyLookupError, parse_spotify_embed


def _embed_html(entity: dict) -> str:
    payload = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


class SpotifyFallbackTests(unittest.TestCase):
    def test_track_metadata_builds_spotify_only_fallback(self) -> None:
        source_url = "https://open.spotify.com/track/abc?si=tracking"

        track = parse_spotify_embed(
            source_url,
            _embed_html(
                {
                    "type": "track",
                    "name": "Heartsink",
                    "artists": [{"name": "Blood Red Shoes"}],
                    "releaseDate": {"isoString": "2010-03-15T00:00:00Z"},
                    "coverArt": {"sources": [{"url": "https://i.scdn.co/image/cover"}]},
                }
            ),
        )

        self.assertEqual(track.artist, "Blood Red Shoes")
        self.assertEqual(track.title, "Heartsink")
        self.assertEqual(track.release_year, "2010")
        self.assertEqual(track.links, {"spotify": "https://open.spotify.com/track/abc"})
        self.assertEqual(track.page_url, "https://open.spotify.com/track/abc")
        self.assertEqual(track.thumbnail_url, "https://i.scdn.co/image/cover")

    def test_removed_release_is_not_invented(self) -> None:
        with self.assertRaises(SpotifyLookupError):
            parse_spotify_embed(
                "https://open.spotify.com/track/missing",
                _embed_html({"type": "track"}),
            )
