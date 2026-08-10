from types import SimpleNamespace
import unittest

from music_links_bot.bot import _handle_editor_action, _render_track_draft
from music_links_bot.bot_pipeline import delivery_kind
from music_links_bot.bot_ui import (
    build_error_keyboard,
    build_publish_confirmation,
    build_start_keyboard,
    render_crate,
)
from music_links_bot.draft_model import CURRENT_DRAFT_VERSION, new_track_draft
from music_links_bot.models import TrackMatch


def _track() -> TrackMatch:
    return TrackMatch(
        title="Dopesmoker",
        artist="Sleep",
        links={
            "spotify": "https://open.spotify.com/track/1",
            "deezer": "https://deezer.com/track/1",
        },
        page_url="https://song.link/sleep",
    )


class PublicationGoldenTests(unittest.TestCase):
    def test_compact_draft_card_has_stable_text_and_actions(self) -> None:
        draft = new_track_draft(_track(), chat_id=7, lang="ru")
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}))

        text, keyboard = _render_track_draft(
            draft, context, draft_id="draft123"
        )

        self.assertEqual(
            text,
            "🎧 · <b>Sleep</b>\nDopesmoker\n\n#stonerhand #track",
        )
        self.assertEqual(draft["v"], CURRENT_DRAFT_VERSION)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(labels[:2], ["🟢 Spotify", "🪩 Все платформы"])
        self.assertIn("🎛 Настроить", labels)

    def test_publish_confirmation_is_one_clear_primary_action(self) -> None:
        draft = new_track_draft(_track(), chat_id=7, lang="ru", can_publish=True)
        text, keyboard = build_publish_confirmation(
            "draft123", draft, _track(), target="@stonerhand", lang="ru"
        )

        self.assertIn("Готово к публикации", text)
        self.assertIn("Sleep", text)
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "Опубликовать")
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data,
            "v2|editor|pc|draft123",
        )
        self.assertEqual(keyboard.inline_keyboard[-1][0].text, "← Назад")


class EditorFlowContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_opens_confirmation_in_the_same_message(self) -> None:
        draft = new_track_draft(_track(), chat_id=7, lang="ru", can_publish=True)

        class Query:
            from_user = SimpleNamespace(id=7, language_code="ru")
            message = SimpleNamespace(chat_id=7)

            def __init__(self) -> None:
                self.edits: list[dict] = []

            async def answer(self, *args, **kwargs) -> None:
                del args, kwargs

            async def edit_message_text(self, **kwargs) -> None:
                self.edits.append(kwargs)

        query = Query()
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    "drafts": {"draft123": draft},
                    "admin_chat_id": 7,
                    "publish_chat_id": "@stonerhand",
                }
            )
        )

        await _handle_editor_action(query, context, "p", "draft123")

        self.assertEqual(len(query.edits), 1)
        self.assertIn("Готово к публикации", query.edits[0]["text"])
        keyboard = query.edits[0]["reply_markup"]
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data,
            "v2|editor|pc|draft123",
        )


class TelegramUiContractTests(unittest.TestCase):
    def test_recovery_actions_do_not_form_a_cramped_three_button_row(self) -> None:
        keyboard = build_error_keyboard(
            None,
            lang="ru",
            retryable=True,
            search_query="Sleep",
            source_url="https://open.spotify.com/track/1",
        )

        self.assertEqual([len(row) for row in keyboard.inline_keyboard], [1, 2, 1])
        self.assertEqual(keyboard.inline_keyboard[-1][0].text, "← Главное меню")

    def test_core_keyboards_have_valid_labels_and_callbacks(self) -> None:
        keyboards = [
            build_start_keyboard(None, lang="ru", crate_count=2),
            build_error_keyboard(None, lang="ru", retryable=True),
            render_crate([], lang="ru")[1],
        ]
        for keyboard in keyboards:
            for row in keyboard.inline_keyboard:
                self.assertLessEqual(len(row), 2)
                for button in row:
                    self.assertTrue(button.text.strip())
                    if button.callback_data:
                        self.assertLessEqual(len(button.callback_data.encode()), 64)

    def test_delivery_kind_is_a_single_explicit_contract(self) -> None:
        bundle = SimpleNamespace(
            item_count=1,
            content_type_count=1,
            tracks=[_track()],
            videos=[],
            radios=[],
            playlists=[],
            artists=[],
        )
        self.assertEqual(delivery_kind(bundle), "tracks")


if __name__ == "__main__":
    unittest.main()
