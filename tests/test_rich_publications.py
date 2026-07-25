from __future__ import annotations

import unittest

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from music_links_bot.models import TrackMatch
from music_links_bot.rich_publications import (
    MAX_FALLBACK_TEXT,
    MAX_LONGREAD_BLOCKS,
    MAX_RICH_HTML,
    apply_publication_patch,
    build_fallback_html,
    build_rich_html,
    longread_view,
    rich_api_unavailable,
    sanitize_longread,
    save_prepared_rich_publication,
    send_rich_publication,
)


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

    def test_patch_and_presenter_default_to_card_but_preserve_longread(self) -> None:
        draft = {
            "item": _track().__dict__ if hasattr(_track(), "__dict__") else {
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
            "lang": "ru",
        }
        apply_publication_patch(
            draft,
            {
                "publication_mode": "longread",
                "longread": {
                    "title": "Большой материал",
                    "lead": "Лид",
                    "blocks": [{"id": "q", "type": "quote", "text": "Цитата"}],
                },
            },
        )

        view = longread_view(draft, _track(), cta="Слушать")

        self.assertEqual(view["mode"], "longread")
        self.assertEqual(view["longread"]["blocks"][0]["type"], "quote")

    def test_rich_html_escapes_user_text_and_renders_telegram_blocks(self) -> None:
        draft = {
            "publication_mode": "longread",
            "longread": {
                "title": "Sleep & <Dopesmoker>",
                "lead": "Loud",
                "blocks": [
                    {"id": "h", "type": "heading", "text": "Context"},
                    {"id": "p", "type": "paragraph", "text": "<script>alert(1)</script>"},
                    {"id": "q", "type": "quote", "text": "Turn it up"},
                    {"id": "l", "type": "list", "items": ["One", "Two"], "ordered": True},
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
            cta=None,
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
            cta=None,
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
            cta=None,
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
        self.assertEqual(data["reply_markup"]["inline_keyboard"][0][0]["text"], "Spotify")

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
