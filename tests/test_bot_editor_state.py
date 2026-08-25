import unittest
from types import SimpleNamespace

from music_links_bot.bot_editor_state import (
    cycle_preset,
    draft_owned_by,
    draft_status,
    remember_draft,
    remember_setting_state,
    restore_setting_state,
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
        draft = {"preset": "cover"}

        self.assertEqual(cycle_preset(draft), "longread")
        self.assertFalse(draft["as_photo"])
        self.assertTrue(draft["large_preview"])
        self.assertEqual(draft["publication_mode"], "longread")
        self.assertEqual(cycle_preset(draft), "minimal")
        self.assertFalse(draft["as_photo"])
        self.assertFalse(draft["large_preview"])
        self.assertEqual(draft["publication_mode"], "card")

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
            draft_status({"preset": "cover"}, self.track, lang="ru"),
            "Обложка · площадок: 2 · сохранено",
        )
        self.assertEqual(
            draft_status(
                {"preset": "cover", "source_audio_file_id": "audio"},
                self.track,
                lang="ru",
            ),
            "Обложка · аудио Telegram · сохранено",
        )

    def test_private_draft_rejects_another_user(self) -> None:
        self.assertTrue(draft_owned_by({"chat_id": 7}, 7))
        self.assertFalse(draft_owned_by({"chat_id": 7}, 8))
        self.assertFalse(draft_owned_by({}, 7))
        self.assertFalse(draft_owned_by({"chat_id": "7"}, 7))

    def test_setting_change_can_be_restored(self) -> None:
        draft = {"hashtags": True, "platforms": ["spotify"]}
        remember_setting_state(draft)
        expires_at = draft["undo_state"]["expires_at"]
        draft["hashtags"] = False
        draft["platforms"] = ["appleMusic"]

        self.assertTrue(restore_setting_state(draft, now=expires_at))
        self.assertTrue(draft["hashtags"])
        self.assertEqual(draft["platforms"], ["spotify"])
        self.assertFalse(restore_setting_state(draft, now=expires_at))

    def test_five_setting_changes_can_be_restored_in_order(self) -> None:
        draft = {"hashtags": True}
        for index in range(7):
            remember_setting_state(draft)
            draft["hashtags"] = bool(index % 2)
        expires_at = draft["undo_state"]["expires_at"]

        restored = [restore_setting_state(draft, now=expires_at) for _ in range(6)]

        self.assertEqual(restored, [True, True, True, True, True, False])

    def test_expired_setting_change_is_not_restored(self) -> None:
        draft = {"hashtags": True}
        remember_setting_state(draft)
        expires_at = draft["undo_state"]["expires_at"]
        draft["hashtags"] = False

        self.assertFalse(restore_setting_state(draft, now=expires_at + 1))
        self.assertFalse(draft["hashtags"])
