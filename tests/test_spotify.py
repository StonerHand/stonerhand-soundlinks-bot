from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

import httpx

from music_links_bot.spotify import (
    SpotifyClient,
    SpotifyLookupError,
    parse_spotify_embed,
    parse_spotify_oembed,
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
        self.assertEqual(track.page_url, "https://song.link/s/abc")

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

    def test_public_page_removes_spotify_album_seo_copy(self) -> None:
        track = parse_spotify_page(
            "https://open.spotify.com/album/abc",
            _page_html(
                title=("Czarface Meets Frankie Pulitzer - Album by CZARFACE | Spotify"),
                artist="CZARFACE",
                kind="music.album",
            ),
        )

        self.assertEqual(track.title, "Czarface Meets Frankie Pulitzer")
        self.assertEqual(track.artist, "CZARFACE")

    def test_public_page_rejects_missing_artist(self) -> None:
        with self.assertRaises(SpotifyLookupError):
            parse_spotify_page(
                "https://open.spotify.com/track/abc",
                '<meta property="og:title" content="Dove">',
            )

    def test_public_page_rejects_spotify_marketing_shell(self) -> None:
        with self.assertRaisesRegex(SpotifyLookupError, "generic public page"):
            parse_spotify_page(
                "https://open.spotify.com/album/42dcDuItUH0Ed4QU4umdq6",
                (
                    '<meta property="og:title" content="Listening is everything">'
                    '<meta property="og:type" content="website">'
                    '<meta property="og:description" content="Spotify is all the '
                    'music you’ll ever need. Listen to millions of songs.">'
                    '<meta property="og:image" content="https://open.spotifycdn.com/cdn/images/og-image.jpg">'
                ),
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
        self.assertEqual(track.page_url, "https://song.link/s/abc")
        self.assertEqual(track.thumbnail_url, "https://i.scdn.co/image/cover")

    def test_removed_release_is_not_invented(self) -> None:
        with self.assertRaises(SpotifyLookupError):
            parse_spotify_embed(
                "https://open.spotify.com/track/missing",
                _embed_html({"type": "track"}),
            )

    def test_oembed_builds_minimal_verified_spotify_card(self) -> None:
        track = parse_spotify_oembed(
            "https://open.spotify.com/track/abc?si=tracking",
            {
                "provider_name": "Spotify",
                "type": "rich",
                "title": "Never Gonna Give You Up",
                "thumbnail_url": "https://i.scdn.co/image/cover",
            },
        )

        self.assertEqual(track.title, "Never Gonna Give You Up")
        self.assertEqual(track.artist, "Spotify")
        self.assertEqual(track.links, {"spotify": "https://open.spotify.com/track/abc"})
        self.assertEqual(track.page_url, "https://song.link/s/abc")
        self.assertEqual(track.thumbnail_url, "https://i.scdn.co/image/cover")

    def test_oembed_rejects_generic_or_incomplete_metadata(self) -> None:
        for payload in (
            {"provider_name": "Other", "title": "Dove", "thumbnail_url": "https://x"},
            {
                "provider_name": "Spotify",
                "title": "Listening is everything",
                "thumbnail_url": "https://x",
            },
            {"provider_name": "Spotify", "title": "Dove"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(SpotifyLookupError):
                    parse_spotify_oembed(
                        "https://open.spotify.com/track/abc",
                        payload,
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

    async def test_client_falls_back_to_embed_when_page_metadata_is_incomplete(
        self,
    ) -> None:
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

    async def test_client_never_turns_removed_album_into_spotify_brand_card(
        self,
    ) -> None:
        client = SpotifyClient()
        generic_page = httpx.Response(
            200,
            text=(
                '<meta property="og:title" content="Listening is everything">'
                '<meta property="og:type" content="website">'
                '<meta property="og:description" content="Spotify is all the '
                'music you’ll ever need.">'
            ),
            request=httpx.Request(
                "GET",
                "https://open.spotify.com/album/42dcDuItUH0Ed4QU4umdq6",
            ),
        )
        empty_embed = httpx.Response(
            200,
            text="<html></html>",
            request=httpx.Request(
                "GET",
                "https://open.spotify.com/embed/album/42dcDuItUH0Ed4QU4umdq6",
            ),
        )
        missing_oembed = httpx.Response(
            404,
            request=httpx.Request(
                "GET",
                "https://open.spotify.com/oembed",
            ),
        )
        client._client.get = AsyncMock(
            side_effect=[generic_page, empty_embed, missing_oembed]
        )
        try:
            with self.assertRaises(SpotifyLookupError):
                await client.lookup_release(
                    "https://open.spotify.com/album/42dcDuItUH0Ed4QU4umdq6"
                )
        finally:
            await client.aclose()

        self.assertEqual(client._client.get.await_count, 3)

    async def test_client_uses_oembed_after_both_html_parsers_change(self) -> None:
        client = SpotifyClient()
        generic_page = httpx.Response(
            200,
            text='<meta property="og:type" content="website">',
            request=httpx.Request("GET", "https://open.spotify.com/track/abc"),
        )
        empty_embed = httpx.Response(
            200,
            text="<html></html>",
            request=httpx.Request(
                "GET",
                "https://open.spotify.com/embed/track/abc",
            ),
        )
        oembed = httpx.Response(
            200,
            json={
                "provider_name": "Spotify",
                "type": "rich",
                "title": "Dove",
                "thumbnail_url": "https://i.scdn.co/image/cover",
            },
            request=httpx.Request("GET", "https://open.spotify.com/oembed"),
        )
        client._client.get = AsyncMock(side_effect=[generic_page, empty_embed, oembed])
        try:
            track = await client.lookup_release(
                "https://open.spotify.com/track/abc?si=tracking"
            )
        finally:
            await client.aclose()

        self.assertEqual(track.title, "Dove")
        self.assertEqual(track.artist, "Spotify")
        self.assertEqual(track.thumbnail_url, "https://i.scdn.co/image/cover")
        self.assertEqual(client._client.get.await_count, 3)
