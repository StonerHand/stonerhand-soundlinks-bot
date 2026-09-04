from __future__ import annotations

import unittest

from music_links_bot.bot import _editor_overflow_rows
from music_links_bot.bot_ui import (
    editor_more_rows as _editor_more_rows,
    editor_rows as _editor_rows,
)
from music_links_bot.editor_view import render_track_draft as _render_track_draft
from music_links_bot.models import TrackMatch


class PostEditorTests(unittest.TestCase):
    def _draft(self, **overrides: object) -> dict:
        draft = {
            "v": 1,
            "type": "track",
            "item": {
                "title": "Transitions",
                "artist": "Youth Code",
                "links": {"spotify": "https://open.spotify.com/track/1"},
                "page_url": "https://song.link/transitions",
                "release_year": None,
                "kind": "song",
                "release_format": None,
                "thumbnail_url": None,
            },
            "prefix": "",
            "hashtags": False,
            "quote": False,
            "large_preview": True,
            "chat_id": 456,
            "lang": "ru",
            "can_publish": False,
        }
        draft.update(overrides)
        return draft

    def test_editor_rows_show_toggle_states_and_actions(self) -> None:
        rows = _editor_rows("abc123", self._draft(hashtags=True))

        self.assertEqual(rows[0][0].text, "Отправить себе")
        self.assertEqual(rows[0][0].callback_data, "v2|editor|s|abc123")
        self.assertEqual(rows[1][0].text, "Изменить")
        self.assertEqual(rows[1][0].callback_data, "v2|editor|m|abc123")
        self.assertEqual(rows[1][1].text, "＋ В подборку")
        self.assertEqual(rows[1][1].callback_data, "v2|editor|c|abc123")
        more = _editor_more_rows("abc123", self._draft(hashtags=True))
        self.assertEqual(more[1][0].text, "# Хэштеги · авто")
        self.assertEqual(more[1][0].callback_data, "v2|editor|hs|abc123")

    def test_editor_rows_make_admin_publication_immediately_visible(self) -> None:
        rows = _editor_rows("abc123", self._draft(can_publish=True))

        labels = [button.text for row in rows for button in row]
        self.assertEqual(labels, ["📤 В канал", "Изменить", "＋ В подборку"])
        self.assertEqual(rows[0][0].style, "success")

    def test_editor_rows_turn_added_item_into_crate_shortcut(self) -> None:
        rows = _editor_rows(
            "abc123",
            self._draft(in_crate=True, crate_count=3),
        )

        self.assertEqual(rows[1][1].text, "В подборке · 3/10")
        self.assertEqual(rows[1][1].callback_data, "v2|crate|open")
        self.assertEqual(dict(rows[1][1].api_kwargs or {}), {})

    def test_editor_rows_keep_text_toggle_predictable(self) -> None:
        rows_without_quote = _editor_more_rows("abc123", self._draft())
        rows_with_quote = _editor_more_rows(
            "abc123",
            self._draft(prefix="<blockquote>интро</blockquote>\n", quote=True),
        )

        self.assertEqual(rows_without_quote[0][1].text, "Подводка · нет")
        self.assertEqual(rows_with_quote[0][1].text, "Подводка · есть")
        self.assertFalse(
            any(
                button.callback_data == "v2|editor|v|abc123"
                for row in rows_without_quote
                for button in row
            )
        )
        self.assertLessEqual(len(rows_without_quote), 4)

    def test_uploaded_audio_does_not_offer_irrelevant_platform_picker(self) -> None:
        rows = _editor_more_rows(
            "abc123",
            self._draft(source_audio_file_id="telegram-audio"),
        )

        self.assertEqual(rows[1][1].text, "Площадки · не нужны")
        self.assertEqual(rows[1][1].callback_data, "v2|noop|busy")

    def test_editor_offers_fast_search_correction_for_search_drafts(self) -> None:
        rows = _editor_overflow_rows(
            "abc123",
            self._draft(search_query="Sleep — Dragonaut"),
        )

        search_row = next(row for row in rows if len(row) == 2)
        self.assertEqual(search_row[0].text, "Другой релиз")
        self.assertEqual(search_row[0].callback_data, "v2|editor|a|abc123")
        self.assertEqual(search_row[1].text, "Изменить запрос")
        self.assertEqual(
            search_row[1].switch_inline_query_current_chat,
            "Sleep — Dragonaut",
        )

    def test_editor_rows_keep_one_compact_action_row(self) -> None:
        rows = _editor_rows("abc123", self._draft())

        self.assertEqual([len(row) for row in rows], [1, 2])
        self.assertEqual(rows[0][0].text, "Отправить себе")

    def test_render_track_draft_respects_toggles(self) -> None:
        draft = self._draft(
            prefix="<blockquote>интро</blockquote>\n",
            quote=True,
            hashtags=True,
        )

        text, keyboard = _render_track_draft(draft, None, draft_id="abc123")

        self.assertIn("интро", text)
        self.assertIn("#stonerhand", text)
        editor_buttons = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("v2|editor|m|abc123", editor_buttons)

        draft["quote"] = False
        draft["hashtags"] = False
        text, keyboard = _render_track_draft(draft, None, draft_id=None)

        self.assertNotIn("интро", text)
        self.assertNotIn("#stonerhand", text)
        editor_buttons = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertEqual(editor_buttons, [])

    def test_card_builder_explains_that_settings_update_the_preview(self) -> None:
        text, keyboard = _render_track_draft(
            self._draft(),
            None,
            draft_id="abc123",
            settings=True,
            show_status=True,
        )

        self.assertTrue(text.startswith("🎛 <b>Конструктор карточки</b>"))
        self.assertIn("превью обновится сразу", text)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("✓ Готово", labels)
        self.assertIn("Отправить", labels)

    def test_quick_card_is_capped_at_four_actions(self) -> None:
        draft = self._draft()
        draft["item"]["links"]["tidal"] = "https://tidal.com/track/1"

        _, keyboard = _render_track_draft(draft, None, draft_id="abc123")
        buttons = [button for row in keyboard.inline_keyboard for button in row]

        self.assertEqual(len(buttons), 5)
        self.assertEqual(buttons[0].text, "🪩 Все платформы")
        self.assertEqual(buttons[1].text, "🟢 Spotify")
        self.assertEqual(buttons[2].text, "Отправить себе")
        self.assertEqual(buttons[3].text, "Изменить")
        self.assertEqual(buttons[4].text, "＋ В подборку")


class PublicationOverrideTests(unittest.TestCase):
    def _draft(self, **overrides: object) -> dict:
        draft = {
            "v": 1,
            "type": "track",
            "item": {
                "title": "Dopesmoker",
                "artist": "Sleep",
                "links": {
                    "spotify": "https://open.spotify.com/track/1",
                    "tidal": "https://tidal.com/track/1",
                    "deezer": "https://deezer.com/track/1",
                },
                "page_url": "https://song.link/dopesmoker",
                "kind": "song",
            },
            "prefix": "",
            "hashtags": True,
            "quote": False,
            "large_preview": True,
            "chat_id": 456,
            "lang": "ru",
            "can_publish": False,
        }
        draft.update(overrides)
        return draft

    def test_legacy_custom_cta_is_not_rendered_and_heading_stays_plain(self) -> None:
        text, _ = _render_track_draft(
            self._draft(custom_cta="жми и слушай громко"), None
        )

        self.assertNotIn("жми и слушай громко", text)
        self.assertNotIn("<a href=", text)

    def test_custom_tags_replace_auto_hashtags(self) -> None:
        text, _ = _render_track_draft(
            self._draft(custom_tags=["#doom", "Sludge Metal"]), None
        )

        self.assertIn("#doom #sludgemetal", text)
        self.assertNotIn("#stonerhand", text)

    def test_empty_custom_tags_suppress_hashtags_even_on_publish_path(self) -> None:
        from music_links_bot.publication_view import resolve_draft_hashtags

        hashtags = resolve_draft_hashtags(
            self._draft(custom_tags=[]),
            TrackMatch(**self._draft()["item"]),
        )

        self.assertIsNone(hashtags)

    def test_normalize_hashtag_slugs_and_rejects_junk(self) -> None:
        from music_links_bot.text_utils import normalize_hashtag

        self.assertEqual(normalize_hashtag("#Hip-Hop!"), "#hiphop")
        self.assertEqual(normalize_hashtag("Дум метал"), "#думметал")
        self.assertIsNone(normalize_hashtag("!!!"))
        self.assertIsNone(normalize_hashtag(42))

    def test_platform_selection_filters_and_orders_buttons(self) -> None:
        _, keyboard = _render_track_draft(
            self._draft(platforms=["tidal", "spotify"]), None
        )

        urls = [
            button.url
            for row in keyboard.inline_keyboard
            for button in row
            if button.url and "song.link" not in button.url and "t.me" not in button.url
        ]
        self.assertEqual(
            urls,
            ["https://tidal.com/track/1", "https://open.spotify.com/track/1"],
        )

    def test_unknown_platform_selection_falls_back_to_default(self) -> None:
        _, keyboard = _render_track_draft(self._draft(platforms=["nope"]), None)

        urls = [
            button.url
            for row in keyboard.inline_keyboard
            for button in row
            if button.url and "song.link" not in button.url and "t.me" not in button.url
        ]
        self.assertEqual(len(urls), 1)
