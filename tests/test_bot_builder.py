from datetime import datetime, timezone
from dataclasses import asdict
import unittest

from music_links_bot.bot_builder import (
    BuilderScreen,
    active_card_label,
    apply_custom_tags,
    apply_intro_text,
    builder_screen,
    fit_telegram_html,
    format_schedule_datetime,
    normalize_crate_title,
    parse_schedule_datetime,
    remove_tags,
    schedule_timestamp,
    select_all_platforms,
    select_preset,
    selected_platforms,
    toggle_platform,
    use_auto_tags,
)
from music_links_bot.bot_runtime import UserSession
from music_links_bot.bot_ui import (
    build_create_keyboard,
    build_start_keyboard,
    editor_hashtag_rows,
    editor_platform_rows,
    editor_style_rows,
)
from music_links_bot.models import TrackMatch


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
        keyboard = build_start_keyboard("StonerHandBot", lang="ru")
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
        self.assertEqual(keyboard.inline_keyboard[1][0].text, "↩ Deftones — Rickets")
        self.assertEqual(
            active_card_label({"item": {"artist": "A", "title": "B"}}, "fallback"),
            "A — B",
        )

    def test_explicit_style_platform_intro_and_tag_flow(self) -> None:
        self.assertEqual(builder_screen("zs"), BuilderScreen.STYLE)
        self.assertEqual(select_preset(self.draft, 0), "minimal")
        self.assertEqual(
            selected_platforms(self.draft, self.track, self.order),
            ["spotify", "appleMusic", "tidal"],
        )
        toggle_platform(self.draft, self.track, self.order, 1)
        self.assertEqual(self.draft["platforms"], ["spotify", "tidal"])
        select_all_platforms(self.draft, self.track, self.order)
        self.assertEqual(self.draft["platforms"], ["spotify", "appleMusic", "tidal"])

        intro = apply_intro_text(self.draft, "Первая строка\nВторая <строка>")
        self.assertIn("\n", intro)
        self.assertIn("&lt;строка&gt;", self.draft["prefix"])
        tags = apply_custom_tags(self.draft, "#Rock #new-music rock #трек")
        self.assertEqual(tags, ["#rock", "#newmusic", "#трек"])
        remove_tags(self.draft)
        self.assertFalse(self.draft["hashtags"])
        none_rows = editor_hashtag_rows("abc", self.draft)
        self.assertNotIn("✓", none_rows[1][0].text)
        self.assertTrue(none_rows[2][0].text.startswith("✓"))
        use_auto_tags(self.draft)
        self.assertTrue(self.draft["hashtags"])
        self.assertNotIn("custom_tags", self.draft)

    def test_selector_keyboards_are_explicit_and_reversible(self) -> None:
        style_rows = editor_style_rows("abc", self.draft)
        self.assertEqual(style_rows[0][0].callback_data, "v2|editor|z0|abc")
        platform_rows = editor_platform_rows("abc", self.draft, self.track, self.order)
        self.assertEqual(platform_rows[0][0].callback_data, "v2|editor|l0|abc")
        tag_rows = editor_hashtag_rows("abc", self.draft)
        self.assertEqual(tag_rows[-1][0].callback_data, "v2|editor|m|abc")

    def test_schedule_and_telegram_limits_are_deterministic(self) -> None:
        now = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(schedule_timestamp("q1", now=now), int(now.timestamp()) + 3600)
        evening = schedule_timestamp(
            "qe",
            now=datetime(2026, 8, 10, 19, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            evening, int(datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc).timestamp())
        )
        local_now = datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc)
        custom = parse_schedule_datetime("15.08 19:30", now=local_now)
        self.assertEqual(
            format_schedule_datetime(custom or 0, timezone_name="UTC"),
            "15.08 · 19:30",
        )
        limited = fit_telegram_html("<b>" + "<&" * 5000 + "</b>", 1024)
        self.assertLessEqual(len(limited), 1024)
        self.assertTrue(limited.endswith("…"))

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
