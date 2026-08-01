import unittest
from types import SimpleNamespace

from music_links_bot.bot_editor_state import (
    cycle_preset,
    draft_owned_by,
    draft_status,
    remember_draft,
    toggle_platform_selection,
)
from music_links_bot.models import TrackMatch


class BotEditorStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.track = TrackMatch(
            title="Dragonaut",
            artist="Sleep",
            links={
                "spotify": "https://open.spotify.com/track/1",
                "appleMusic": "https://music.apple.com/song/1",
            },
        )

    def test_preset_cycle_updates_delivery_flags(self) -> None:
        draft = {"preset": "clean"}

        self.assertEqual(cycle_preset(draft), "editorial")
        self.assertFalse(draft["as_photo"])
        self.assertFalse(draft["large_preview"])
        self.assertEqual(cycle_preset(draft), "poster")
        self.assertTrue(draft["as_photo"])
        self.assertTrue(draft["large_preview"])

    def test_platform_toggle_switches_between_compact_and_all(self) -> None:
        draft = {}
        order = ("spotify", "appleMusic", "tidal")

        toggle_platform_selection(draft, self.track, order)
        self.assertEqual(draft["platforms"], ["spotify", "appleMusic"])
        toggle_platform_selection(draft, self.track, order)
        self.assertNotIn("platforms", draft)

    def test_status_and_recent_drafts_stay_bounded(self) -> None:
        session = SimpleNamespace(active_draft_id="", recent_draft_ids=[])
        for index in range(7):
            remember_draft(session, str(index))

        self.assertEqual(session.active_draft_id, "6")
        self.assertEqual(session.recent_draft_ids, ["6", "5", "4", "3", "2"])
        self.assertEqual(
            draft_status({"preset": "clean"}, self.track, lang="ru"),
            "Черновик · Чисто · 1 серв. · сохранено",
        )

    def test_private_draft_rejects_another_user(self) -> None:
        self.assertTrue(draft_owned_by({"chat_id": 7}, 7))
        self.assertFalse(draft_owned_by({"chat_id": 7}, 8))
