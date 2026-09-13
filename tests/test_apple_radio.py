import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from test_bot import ContextStub, PrivateMessageStub, UpdateStub

from music_links_bot.apple_radio import (
    AppleRadioClient,
    AppleRadioLookupError,
    parse_apple_radio,
)
from music_links_bot.bot import track_lookup_message
from music_links_bot.bot_inline import _build_inline_result
from music_links_bot.bot_lookup import resolve_sources
from music_links_bot.formatter import format_radio_message
from music_links_bot.provider_registry import DEFAULT_PROVIDER_REGISTRY
from music_links_bot.url_utils import is_apple_music_radio_url

URL = "https://music.apple.com/tr/curator/the-alligator-hour/993270307"
# The public page's actual title metadata; no episode descriptions are copied.
HTML = """<html><head><title>‎The Alligator Hour - Radio Show - Apple Music</title>
<meta property="og:title" content="The Alligator Hour on Apple Music"></head></html>"""


class AppleRadioTests(unittest.IsolatedAsyncioTestCase):
    def test_curator_link_is_routed_away_from_track_matching(self):
        self.assertEqual(DEFAULT_PROVIDER_REGISTRY.provider_for(URL), "apple_radio")
        self.assertFalse(
            is_apple_music_radio_url(
                "https://music.apple.com.evil.test/tr/curator/x/123"
            )
        )
        self.assertFalse(
            is_apple_music_radio_url("https://music.apple.com/tr/album/x/123")
        )

    def test_exact_user_page_has_clean_radio_title_and_tags(self):
        radio = parse_apple_radio(URL, HTML)
        self.assertEqual(radio.title, "The Alligator Hour")
        self.assertEqual(radio.url, URL)
        text = format_radio_message(radio)
        self.assertIn("📻 · <b>The Alligator Hour</b>", text)
        self.assertIn("Радиошоу · Apple Music", text)
        self.assertIn("#stonerhand #radio", text)
        self.assertNotIn("#track", text)

    def test_other_curators_are_not_mislabeled_as_radio_from_recommendations(self):
        with self.assertRaises(AppleRadioLookupError):
            parse_apple_radio(
                URL, "<title>Editor - Apple Music</title><p>Recommended Radio Show</p>"
            )

    async def test_metadata_fetch_and_cache_preserve_original_region(self):
        calls = []

        def respond(request):
            calls.append(request)
            return httpx.Response(200, text=HTML)

        client = AppleRadioClient()
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            self.assertEqual((await client.lookup_radio(URL)).url, URL)
            self.assertEqual(
                (await client.lookup_radio(URL)).title, "The Alligator Hour"
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].url.params["l"], "en")
        finally:
            await client.aclose()

    async def test_off_domain_redirect_is_never_followed(self):
        seen = []

        def respond(request):
            seen.append(str(request.url))
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

        client = AppleRadioClient()
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            with self.assertRaises(AppleRadioLookupError):
                await client.lookup_radio(URL)
            self.assertEqual(len(seen), 1)
        finally:
            await client.aclose()

    async def test_private_inline_and_batch_use_radio_not_songlink(self):
        ctx = ContextStub()
        songlink = AsyncMock(side_effect=AssertionError("radio must not use Songlink"))
        ctx.application.bot_data.update(
            songlink_client=SimpleNamespace(lookup_track=songlink),
            apple_radio_client=SimpleNamespace(
                lookup_radio=AsyncMock(return_value=parse_apple_radio(URL, HTML))
            ),
            lookup_cache_namespace=self.id(),
        )
        bundle = await resolve_sources(ctx.application.bot_data, [URL])
        self.assertEqual(len(bundle.radios), 1)
        self.assertTrue(bundle.is_complete_for([URL]))
        inline = await _build_inline_result(URL, ctx)
        self.assertIn("The Alligator Hour", inline.input_message_content.message_text)
        self.assertEqual(inline.reply_markup.inline_keyboard[0][0].url, URL)
        self.assertIn("Apple Music", inline.reply_markup.inline_keyboard[0][0].text)
        msg = PrivateMessageStub()
        msg.text, msg.message_id = URL, 123
        await track_lookup_message(UpdateStub(msg), ctx)
        self.assertIn("The Alligator Hour", msg.replies[-1])
        songlink.assert_not_awaited()
