import unittest
from pathlib import Path
import sys
from unittest.mock import AsyncMock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.playlist import PlaylistClient, PlaylistLookupError


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

