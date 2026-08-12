from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

import httpx

from music_links_bot.spotify import (
    SpotifyClient,
    SpotifyLookupError,
    parse_spotify_embed,
    parse_spotify_page,
)


def _embed_html(entity: dict) -> str:
    payload = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


def _page_html(
    *,
    title: str = "Dove",
    artist: str = "Karmanjakah",
    kind: str = "music.song",
) -> str:
    return (
        '<meta property="og:title" content="' + title + '">'
        '<meta property="og:type" content="' + kind + '">'
        '<meta property="og:image" content="https://i.scdn.co/image/cover">'
        '<meta name="music:musician_description" content="' + artist + '">'
        '<meta name="music:release_date" content="2026-02-27">'
    )


class SpotifyFallbackTests(unittest.TestCase):
    def test_public_page_metadata_builds_release_without_js_state(self) -> None:
        track = parse_spotify_page(
            "https://open.spotify.com/track/abc?si=tracking",
            _page_html(),
        )

        self.assertEqual(track.artist, "Karmanjakah")
        self.assertEqual(track.title, "Dove")
        self.assertEqual(track.release_year, "2026")
        self.assertEqual(track.thumbnail_url, "https://i.scdn.co/image/cover")
        self.assertEqual(track.links, {"spotify": "https://open.spotify.com/track/abc"})

    def test_public_page_uses_description_when_artist_meta_is_missing(self) -> None:
        track = parse_spotify_page(
            "https://open.spotify.com/album/abc",
            (
                '<meta property="og:title" content="Diamond morning">'
                '<meta property="og:type" content="music.album">'
                '<meta property="og:description" '
                'content="Karmanjakah · Diamond morning · Album · 2026">'
            ),
        )

        self.assertEqual(track.artist, "Karmanjakah")
        self.assertEqual(track.kind, "album")
        self.assertEqual(track.release_format, "album")

    def test_public_page_rejects_missing_artist(self) -> None:
        with self.assertRaises(SpotifyLookupError):
            parse_spotify_page(
                "https://open.spotify.com/track/abc",
                '<meta property="og:title" content="Dove">',
            )

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


class SpotifyClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_prefers_stable_public_page_metadata(self) -> None:
        client = SpotifyClient()
        response = httpx.Response(
            200,
            text=_page_html(),
            request=httpx.Request("GET", "https://open.spotify.com/track/abc"),
        )
        client._client.get = AsyncMock(return_value=response)
        try:
            track = await client.lookup_release(
                "https://open.spotify.com/track/abc?si=tracking"
            )
        finally:
            await client.aclose()

        self.assertEqual(track.artist, "Karmanjakah")
        self.assertEqual(client._client.get.await_count, 1)

    async def test_client_falls_back_to_embed_when_page_metadata_is_incomplete(self) -> None:
        client = SpotifyClient()
        page_response = httpx.Response(
            200,
            text="<html></html>",
            request=httpx.Request("GET", "https://open.spotify.com/track/abc"),
        )
        embed_response = httpx.Response(
            200,
            text=_embed_html(
                {
                    "type": "track",
                    "name": "Dove",
                    "artists": [{"name": "Karmanjakah"}],
                }
            ),
            request=httpx.Request("GET", "https://open.spotify.com/embed/track/abc"),
        )
        client._client.get = AsyncMock(side_effect=[page_response, embed_response])
        try:
            track = await client.lookup_release("https://open.spotify.com/track/abc")
        finally:
            await client.aclose()

        self.assertEqual(track.title, "Dove")
        self.assertEqual(client._client.get.await_count, 2)
