import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from html import unescape

from music_links_bot.chat.bot_ui import (
    build_create_keyboard,
    build_start_keyboard,
    editor_hashtag_rows,
)
from music_links_bot.core.models import TrackMatch
from music_links_bot.editor.bot_builder import (
    BuilderScreen,
    active_card_label,
    builder_screen,
    normalize_crate_title,
    parse_custom_tags,
    parse_schedule_datetime,
    remove_tags,
    schedule_timestamp,
    select_all_platforms,
    select_preset,
    selected_platforms,
    toggle_platform,
    use_auto_tags,
)
from music_links_bot.state.bot_runtime import UserSession
from music_links_bot.tg.telegram_text import fit_telegram_html, telegram_text_length


class BuilderJourneyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.track = TrackMatch(
            artist="Deftones",
            title="Rickets",
            links={
                "spotify": "https://open.spotify.com/track/1",
                "appleMusic": "https://music.apple.com/song/1",
                "tidal": "https://tidal.com/track/1",
            },
            page_url="https://song.link/1",
        )
        self.order = ["spotify", "appleMusic", "tidal", "deezer"]
        self.draft = {
            "type": "track",
            "item": asdict(self.track),
            "lang": "ru",
            "preset": "cover",
            "hashtags": True,
        }

    def test_home_opens_native_create_screen(self) -> None:
        keyboard = build_start_keyboard("StonerHandBot", lang="ru", first_visit=True)
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data,
            "v2|menu|create",
        )
        create = build_create_keyboard(lang="ru")
        self.assertEqual(create.inline_keyboard[-1][0].callback_data, "v2|menu|start")

    def test_named_card_return_is_compact(self) -> None:
        keyboard = build_start_keyboard(
            "StonerHandBot",
            lang="ru",
            active_draft_id="abc",
            active_draft_label="Deftones — Rickets",
        )
        self.assertEqual(
            keyboard.inline_keyboard[0][0].text, "📝 Продолжить: Deftones — Rickets"
        )
        self.assertEqual(
            active_card_label({"item": {"artist": "A", "title": "B"}}, "fallback"),
            "A — B",
        )

    def test_explicit_style_platform_intro_and_tag_flow(self) -> None:
        # Style lives on the single "Вид" screen; old callbacks still open it.
        self.assertEqual(builder_screen("zs"), BuilderScreen.APPEARANCE)
        self.assertEqual(select_preset(self.draft, 0), "minimal")
        self.assertEqual(
            selected_platforms(self.draft, self.track, self.order),
            ["spotify", "appleMusic", "tidal"],
        )
        toggle_platform(self.draft, self.track, self.order, 1)
        self.assertEqual(self.draft["platforms"], ["spotify", "tidal"])
        select_all_platforms(self.draft, self.track, self.order)
        self.assertEqual(self.draft["platforms"], ["spotify", "appleMusic", "tidal"])

        tags = parse_custom_tags("#Rock #new-music rock #трек")
        self.assertEqual(tags, ["#rock", "#newmusic", "#трек"])
        remove_tags(self.draft)
        self.assertFalse(self.draft["hashtags"])
        none_rows = editor_hashtag_rows("abc", self.draft)
        by_action = {
            button.callback_data.split("|")[2]: button
            for row in none_rows
            for button in row
        }
        self.assertNotIn("✓", by_action["hi"].text)
        # With tags off, the one-tap way back is "auto tags" on the same screen.
        self.assertIn("ha", by_action)
        self.assertFalse(
            any(button.text.startswith("✓") for row in none_rows for button in row)
        )
        use_auto_tags(self.draft)
        self.assertTrue(self.draft["hashtags"])
        self.assertNotIn("custom_tags", self.draft)

    def test_platform_selector_hides_a_mislabeled_destination(self) -> None:
        track = TrackMatch(
            artist="Artist",
            title="Track",
            links={"appleMusic": "https://open.spotify.com/track/wrong"},
        )
        self.assertEqual(selected_platforms({}, track, ["appleMusic"]), [])

    def test_schedule_and_telegram_limits_are_deterministic(self) -> None:
        now = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(schedule_timestamp("q1", now=now), int(now.timestamp()) + 3600)
        evening = schedule_timestamp(
            "qe",
            timezone_name="UTC",
            now=datetime(2026, 8, 10, 19, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            evening, int(datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc).timestamp())
        )
        moscow_evening = schedule_timestamp(
            "qe",
            timezone_name="Europe/Moscow",
            now=datetime(2026, 8, 10, 19, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            moscow_evening,
            int(datetime(2026, 8, 11, 17, 0, tzinfo=timezone.utc).timestamp()),
        )
        local_now = datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc)
        custom = parse_schedule_datetime(
            "15.08 19:30", now=local_now, timezone_name="UTC"
        )
        self.assertEqual(
            custom, int(datetime(2026, 8, 15, 19, 30, tzinfo=timezone.utc).timestamp())
        )
        limited = fit_telegram_html("<b>" + "<&" * 5000 + "</b>", 1024)
        self.assertLessEqual(telegram_text_length(unescape(limited)), 1024)
        self.assertTrue(limited.endswith("…"))

    def test_telegram_html_limit_uses_rendered_utf16_length(self) -> None:
        formatted = "<b>" + "🎧" * 10 + "</b>"
        self.assertEqual(fit_telegram_html(formatted, 20), formatted)

        # Cutting keeps the formatting and closes the open tag.
        limited = fit_telegram_html("<b>" + "🎧" * 11 + "</b>", 20)
        visible = limited.removeprefix("<b>").removesuffix("</b>")
        self.assertLessEqual(telegram_text_length(visible), 20)
        self.assertTrue(limited.startswith("<b>"))
        self.assertTrue(limited.endswith("…</b>"))

        malformed = fit_telegram_html("<b>Sleep — Dragonaut", 100)
        self.assertNotIn("<b>", malformed)
        self.assertEqual(malformed, "Sleep — Dragonaut")

    def test_custom_schedule_is_bounded_to_operational_queue_window(self) -> None:
        now = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)

        self.assertIsNotNone(parse_schedule_datetime("01.09.2026 12:00", now=now))
        self.assertIsNone(parse_schedule_datetime("01.12.2026 12:00", now=now))

    def test_session_keeps_native_input_state(self) -> None:
        session = UserSession.from_dict(
            {
                "user_id": 17,
                "pending_input": {"kind": "intro", "draft_id": "abc"},
            }
        )
        self.assertIsNotNone(session)
        self.assertEqual(session.pending_input["kind"], "intro")

    def test_collection_name_is_clean_and_bounded(self) -> None:
        title = normalize_crate_title("  Ночной    сет  " + "x" * 100)
        self.assertTrue(title.startswith("Ночной сет"))
        self.assertLessEqual(len(title), 72)


if __name__ == "__main__":
    unittest.main()
