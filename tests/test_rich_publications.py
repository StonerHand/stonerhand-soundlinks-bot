from __future__ import annotations

import unittest

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from music_links_bot.models import TrackMatch, VideoMatch
from music_links_bot.rich_publications import (
    MAX_FALLBACK_TEXT,
    MAX_LONGREAD_BLOCKS,
    MAX_RICH_HTML,
    build_fallback_html,
    build_rich_card_html,
    build_rich_collection_html,
    build_rich_html,
    build_rich_inline_card_html,
    build_rich_track_video_html,
    default_longread,
    rich_api_unavailable,
    rich_button_rows_html,
    sanitize_longread,
    sanitize_rich_fragment,
    save_prepared_rich_publication,
    send_rich_publication,
)
from music_links_bot.telegram_gateway import reset_capabilities


def _track() -> TrackMatch:
    return TrackMatch(
        artist="Sleep",
        title="Dopesmoker",
        links={"spotify": "https://open.spotify.com/track/x"},
        page_url="https://song.link/x",
        release_year="1999",
        kind="song",
        release_format="Single",
        thumbnail_url="https://img.example/cover?a=1&b=2",
        genre="Stoner Metal",
    )


class RichPublicationModelTests(unittest.TestCase):
    def test_card_embeds_cover_platform_buttons_and_hashtags(self) -> None:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Spotify",
                        url="https://open.spotify.com/track/x",
                        style="success",
                    )
                ]
            ]
        )

        result = build_rich_card_html(
            {"quote": True, "prefix": "<blockquote>Тяжело &amp; красиво</blockquote>"},
            _track(),
            hashtags="#stonerhand #track",
            reply_markup=keyboard,
        )

        self.assertIn("<h1>Sleep — Dopesmoker</h1>", result)
        self.assertIn("<img src=", result)
        self.assertIn('type="url" style="success"', result)
        self.assertIn("<footer>#stonerhand #track</footer>", result)

    def test_inline_card_never_embeds_remote_artwork(self) -> None:
        result = build_rich_inline_card_html(
            _track(),
            hashtags="#stonerhand #track",
            reply_markup=None,
        )

        self.assertIn("<h1>Sleep — Dopesmoker</h1>", result)
        self.assertNotIn("https://img.example", result)
        self.assertNotIn("<img", result)

    def test_inline_card_can_reference_cached_telegram_artwork(self) -> None:
        result = build_rich_inline_card_html(
            _track(),
            hashtags=None,
            reply_markup=None,
            media_id="cover",
        )

        self.assertIn('src="tg://photo?id=cover"', result)

    def test_track_video_and_collection_use_native_media_groups(self) -> None:
        video = VideoMatch(
            title="Dopesmoker live",
            author="Sleep",
            url="https://youtube.com/watch?v=x",
            thumbnail_url="https://img.example/video.jpg",
        )
        pair = build_rich_track_video_html(
            _track(),
            video,
            body_html="Песня и клип",
            hashtags="#track #video",
            reply_markup=None,
        )
        collection = build_rich_collection_html(
            [_track(), _track()],
            title="Подборка · 2 релиза",
            hashtags="#collection",
            reply_markup=None,
        )

        self.assertIn("<tg-collage>", pair)
        self.assertIn("<tg-collage>", collection)
        self.assertIn("<ol>", collection)

    def test_rich_collection_groups_artist_and_hides_remaster_suffixes(self) -> None:
        first = _track()
        first.artist = "Blur"
        first.title = "There's No Other Way - 2012 Remaster"
        second = _track()
        second.artist = "blur"
        second.title = "Fool (Remastered 2012)"

        collection = build_rich_collection_html(
            [first, second],
            title="Подборка · 2 релиза",
            hashtags="#collection",
            reply_markup=None,
        )

        self.assertIn("<h1>Подборка · 2 релиза</h1>", collection)
        self.assertIn("<p><b>Blur</b></p>", collection)
        self.assertIn(
            "<ol><li>There&#x27;s No Other Way</li><li>Fool</li></ol>",
            collection,
        )
        self.assertNotIn("Remaster", collection)

    def test_rich_fragment_drops_scripts_and_unsafe_links(self) -> None:
        result = sanitize_rich_fragment(
            '<b>ok</b><script>alert(1)</script><a href="javascript:x">bad</a>'
        )

        self.assertEqual(result, "<b>ok</b>alert(1)bad")

    def test_rich_media_rejects_non_http_sources(self) -> None:
        track = _track()
        track.thumbnail_url = "tg://user?id=7"

        result = build_rich_card_html({}, track, hashtags=None, reply_markup=None)

        self.assertNotIn("<img", result)

    def test_regular_keyboard_converts_to_rich_button_rows(self) -> None:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Назад", callback_data="v2|menu|start")]]
        )

        result = rich_button_rows_html(keyboard)

        self.assertIn('type="callback_data" style="link"', result)
        self.assertIn('data="v2|menu|start"', result)

    def test_rich_keyboard_drops_invalid_actions_instead_of_truncating(self) -> None:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Слишком длинный запрос",
                        switch_inline_query="x" * 257,
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Слишком длинный callback",
                        callback_data="я" * 33,
                    )
                ],
            ]
        )

        result = rich_button_rows_html(keyboard)

        self.assertNotIn("Слишком длинный запрос", result)
        self.assertNotIn("Слишком длинный callback", result)
        self.assertNotIn("x" * 256, result)

    def test_default_longread_does_not_repeat_release_metadata(self) -> None:
        self.assertEqual(
            default_longread(_track()),
            {
                "title": "Sleep — Dopesmoker",
                "lead": "",
                "blocks": [],
            },
        )

    def test_sanitizer_keeps_supported_blocks_and_applies_total_budget(self) -> None:
        value = {
            "title": "  Sleep   <script>  ",
            "lead": "  heavy\n  and slow ",
            "blocks": [
                {"id": f"p-{index}", "type": "paragraph", "text": "x" * 1800}
                for index in range(40)
            ]
            + [{"type": "script", "text": "ignored"}],
        }

        result = sanitize_longread(value, _track())

        self.assertEqual(result["title"], "Sleep <script>")
        self.assertLessEqual(len(result["blocks"]), MAX_LONGREAD_BLOCKS)
        self.assertLessEqual(
            sum(len(block.get("text", "")) for block in result["blocks"]),
            22_000,
        )
        self.assertTrue(all(block["type"] == "paragraph" for block in result["blocks"]))

    def test_rich_html_escapes_user_text_and_renders_telegram_blocks(self) -> None:
        draft = {
            "publication_mode": "longread",
            "longread": {
                "title": "Sleep & <Dopesmoker>",
                "lead": "Loud",
                "blocks": [
                    {"id": "h", "type": "heading", "text": "Context"},
                    {
                        "id": "p",
                        "type": "paragraph",
                        "text": "<script>alert(1)</script>",
                    },
                    {"id": "q", "type": "quote", "text": "Turn it up"},
                    {
                        "id": "l",
                        "type": "list",
                        "items": ["One", "Two"],
                        "ordered": True,
                    },
                    {
                        "id": "d",
                        "type": "details",
                        "title": "Credits",
                        "text": "Produced by …",
                    },
                    {"id": "hr", "type": "divider"},
                ],
            },
        }

        result = build_rich_html(
            draft,
            _track(),
            hashtags="#stonerhand #doom",
        )

        self.assertIn("<h1>Sleep &amp; &lt;Dopesmoker&gt;</h1>", result)
        self.assertIn("<figure>", result)
        self.assertIn("<blockquote>Turn it up</blockquote>", result)
        self.assertIn("<ol><li>One</li><li>Two</li></ol>", result)
        self.assertIn("<details>", result)
        self.assertIn("<footer>#stonerhand #doom</footer>", result)
        self.assertNotIn("<script>", result)
        self.assertLessEqual(len(result), MAX_RICH_HTML)

    def test_fallback_is_bounded_and_never_cuts_an_html_piece(self) -> None:
        draft = {
            "publication_mode": "longread",
            "longread": {
                "title": "Long",
                "blocks": [
                    {"id": f"p-{index}", "type": "paragraph", "text": "текст " * 250}
                    for index in range(12)
                ],
            },
        }

        result = build_fallback_html(
            draft,
            _track(),
            hashtags="#stonerhand",
        )

        self.assertLessEqual(len(result), MAX_FALLBACK_TEXT)
        self.assertIn("продолжение", result)

    def test_rich_html_stays_bounded_after_entity_expansion(self) -> None:
        draft = {
            "publication_mode": "longread",
            "longread": {
                "title": "Entity stress",
                "blocks": [
                    {"id": f"p-{index}", "type": "paragraph", "text": "<&>" * 600}
                    for index in range(20)
                ],
            },
        }

        result = build_rich_html(
            draft,
            _track(),
            hashtags="#stonerhand",
        )

        self.assertLessEqual(len(result), MAX_RICH_HTML)
        self.assertIn("&lt;&amp;&gt;", result)
        self.assertTrue(result.endswith("<p><i>…</i></p>"))

    def test_unavailable_detection_is_narrow(self) -> None:
        self.assertTrue(rich_api_unavailable(BadRequest("Method not found")))
        self.assertFalse(rich_api_unavailable(BadRequest("chat not found")))


class _RawBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def _post(self, endpoint: str, data: dict):
        self.calls.append((endpoint, data))
        if endpoint == "savePreparedInlineMessage":
            return {"id": "prepared-rich", "expiration_date": 123}
        return True


class RichPublicationTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        reset_capabilities()

    async def test_send_rich_message_keeps_keyboard(self) -> None:
        bot = _RawBot()
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Spotify", url="https://open.spotify.com")]]
        )

        sent = await send_rich_publication(
            bot,
            chat_id="@stonerhand",
            rich_html="<h1>Test</h1>",
            reply_markup=keyboard,
        )

        self.assertTrue(sent)
        endpoint, data = bot.calls[0]
        self.assertEqual(endpoint, "sendRichMessage")
        self.assertEqual(data["chat_id"], "@stonerhand")
        self.assertEqual(data["rich_message"], {"html": "<h1>Test</h1>"})
        self.assertEqual(
            data["reply_markup"]["inline_keyboard"][0][0]["text"], "Spotify"
        )

    async def test_prepared_rich_message_uses_native_share_contract(self) -> None:
        bot = _RawBot()

        prepared = await save_prepared_rich_publication(
            bot,
            user_id=7,
            result_id="rich-1",
            title="Sleep — Dopesmoker",
            description="Longread",
            thumbnail_url=None,
            rich_html="<h1>Sleep</h1>",
            reply_markup=InlineKeyboardMarkup([]),
        )

        self.assertEqual(prepared["id"], "prepared-rich")
        endpoint, data = bot.calls[0]
        self.assertEqual(endpoint, "savePreparedInlineMessage")
        self.assertEqual(
            data["result"]["input_message_content"],
            {"rich_message": {"html": "<h1>Sleep</h1>"}},
        )
        self.assertTrue(data["allow_channel_chats"])

    async def test_bot_delivery_falls_back_to_regular_html(self) -> None:
        from types import SimpleNamespace

        from music_links_bot.bot import _deliver_draft

        class FallbackBot(_RawBot):
            def __init__(self) -> None:
                super().__init__()
                self.messages: list[dict] = []

            async def _post(self, endpoint: str, data: dict):
                self.calls.append((endpoint, data))
                raise BadRequest("Method not found")

            async def send_message(self, **kwargs):
                self.messages.append(kwargs)
                return SimpleNamespace(message_id=11)

        bot = FallbackBot()
        context = SimpleNamespace(
            bot=bot,
            application=SimpleNamespace(bot_data={}),
        )
        draft = {
            "item": {
                "artist": "Sleep",
                "title": "Dopesmoker",
                "links": {"spotify": "https://open.spotify.com/track/x"},
                "page_url": "https://song.link/x",
                "release_year": "1999",
                "kind": "song",
                "release_format": "Single",
                "thumbnail_url": "https://img.example/cover",
                "genre": "Stoner Metal",
            },
            "publication_mode": "longread",
            "longread": {
                "title": "Большой материал",
                "blocks": [{"id": "p", "type": "paragraph", "text": "Текст"}],
            },
            "hashtags": True,
        }

        sent = await _deliver_draft(
            context,
            draft,
            target=7,
            channel_style=False,
        )

        self.assertEqual(sent.message_id, 11)
        self.assertEqual(bot.calls[0][0], "sendRichMessage")
        self.assertEqual(len(bot.messages), 1)
        self.assertIn("<b>Большой материал</b>", bot.messages[0]["text"])
        self.assertIsNotNone(bot.messages[0]["reply_markup"])
