import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.playlist import (
    MAX_PLAYLIST_IMPORT_TRACKS,
    PlaylistClient,
    PlaylistLookupError,
    _extract_apple_track_urls,
    _extract_spotify_track_urls,
)


class PlaylistClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_apple_music_playlist_uses_public_page_metadata(self) -> None:
        source_url = (
            "https://music.apple.com/tr/playlist/anya-taylor-joy-my-lucky-playlist/"
            "pl.e245dcff90464785a675ec40e8c52abb"
        )
        response = httpx.Response(
            200,
            text=(
                '<meta property="og:title" '
                'content="Anya Taylor-Joy: My Lucky Playlist on Apple Music">'
            ),
            request=httpx.Request("GET", source_url),
        )
        client = PlaylistClient()
        client._client.get = AsyncMock(return_value=response)
        self.addAsyncCleanup(client.aclose)

        playlist = await client.lookup_playlist(source_url)

        self.assertEqual(playlist.title, "Anya Taylor-Joy: My Lucky Playlist")
        self.assertEqual(playlist.platform, "Apple Music")
        self.assertEqual(playlist.url, source_url)
        client._client.get.assert_awaited_once_with(source_url)

    async def test_apple_music_document_title_is_a_safe_fallback(self) -> None:
        source_url = "https://music.apple.com/us/playlist/test/pl.abc"
        response = httpx.Response(
            200,
            text="<title>\u200eTest Mix - Playlist - Apple Music</title>",
            request=httpx.Request("GET", source_url),
        )
        client = PlaylistClient()
        client._client.get = AsyncMock(return_value=response)
        self.addAsyncCleanup(client.aclose)

        playlist = await client.lookup_playlist(source_url)

        self.assertEqual(playlist.title, "Test Mix")

    async def test_non_playlist_apple_music_url_is_rejected(self) -> None:
        client = PlaylistClient()
        self.addAsyncCleanup(client.aclose)

        with self.assertRaises(PlaylistLookupError):
            await client.lookup_playlist(
                "https://music.apple.com/us/album/test/123?i=456"
            )

    async def test_slow_spotify_import_keeps_playlist_metadata(self) -> None:
        source_url = "https://open.spotify.com/playlist/1234567890"
        metadata = httpx.Response(
            200,
            json={"title": "Fast metadata"},
            request=httpx.Request("GET", "https://open.spotify.com/oembed"),
        )

        async def get(_url: str, **kwargs):
            if kwargs.get("params"):
                return metadata
            await asyncio.sleep(1)

        client = PlaylistClient()
        client._client.get = AsyncMock(side_effect=get)
        self.addAsyncCleanup(client.aclose)

        with patch(
            "music_links_bot.playlist.PLAYLIST_IMPORT_TIMEOUT_SECONDS",
            0.001,
        ):
            playlist = await client.lookup_playlist(source_url)

        self.assertEqual(playlist.title, "Fast metadata")
        self.assertEqual(playlist.track_urls, [])

    def test_spotify_page_tracks_are_unique_and_bounded(self) -> None:
        ids = [f"trackid{index:04d}" for index in range(MAX_PLAYLIST_IMPORT_TRACKS + 3)]
        page = " ".join(
            [f'"spotify:track:{track_id}"' for track_id in ids]
            + [f'"https:\\/\\/open.spotify.com\\/track\\/{ids[0]}"']
        )

        urls = _extract_spotify_track_urls(page)

        self.assertEqual(len(urls), MAX_PLAYLIST_IMPORT_TRACKS)
        self.assertEqual(urls[0], f"https://open.spotify.com/track/{ids[0]}")
        self.assertEqual(len(urls), len(set(urls)))

    def test_apple_page_tracks_are_unescaped_and_unique(self) -> None:
        first = "https://music.apple.com/us/album/example/123?i=456"
        second = "https://music.apple.com/us/album/example/123?foo=1&amp;i=789"

        urls = _extract_apple_track_urls(f'"{first}" "{first}" "{second}"')

        self.assertEqual(urls, [first, second.replace("&amp;", "&")])
