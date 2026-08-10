from types import SimpleNamespace
import time
import unittest
from unittest.mock import AsyncMock

from music_links_bot.bot import (
    _dispatch_menu_action,
    _handle_editor_action,
    _consume_pending_input,
    _render_track_draft,
)
from music_links_bot.bot_runtime import CallbackAction
from music_links_bot.bot_runtime import BotRuntime
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

        text, keyboard = _render_track_draft(draft, context, draft_id="draft123")

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
    async def test_native_hashtag_reply_updates_the_active_card(self) -> None:
        draft = new_track_draft(_track(), chat_id=7, lang="ru")
        runtime = BotRuntime()
        session = await runtime.get_session(7)
        session.pending_input = {
            "kind": "hashtags",
            "draft_id": "draft123",
            "editor_chat_id": 7,
            "editor_message_id": 10,
            "prompt_message_id": 11,
            "created_at": int(time.time()),
        }
        await runtime.save_session(session)
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            chat_id=7,
            text="#doom #stonerrock",
            caption=None,
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=7, language_code="ru"),
        )
        context = SimpleNamespace(
            bot=SimpleNamespace(delete_message=AsyncMock()),
            application=SimpleNamespace(
                bot_data={
                    "drafts": {"draft123": draft},
                    "runtime": runtime,
                    "platform_order": ("spotify", "deezer"),
                }
            ),
        )

        self.assertTrue(await _consume_pending_input(update, context))
        stored = context.application.bot_data["drafts"]["draft123"]
        self.assertEqual(stored["custom_tags"], ["#doom", "#stonerrock"])
        self.assertEqual((await runtime.get_session(7)).pending_input, {})
        message.reply_text.assert_awaited_once()

    async def test_native_create_and_explicit_style_are_one_tap_flows(self) -> None:
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
            bot=SimpleNamespace(username="StonerHandBot"),
            application=SimpleNamespace(
                bot_data={
                    "drafts": {},
                    "platform_order": ("spotify", "deezer"),
                }
            ),
        )
        await _dispatch_menu_action(query, context, CallbackAction("menu", "create"))
        self.assertIn("Новая карточка", query.edits[-1]["text"])
        self.assertEqual(
            query.edits[-1]["reply_markup"].inline_keyboard[-1][0].callback_data,
            "v2|menu|start",
        )

        draft = new_track_draft(_track(), chat_id=7, lang="ru")
        context.application.bot_data["drafts"]["draft123"] = draft
        await _handle_editor_action(query, context, "z0", "draft123")
        self.assertEqual(
            context.application.bot_data["drafts"]["draft123"]["preset"],
            "minimal",
        )
        callbacks = [
            button.callback_data
            for row in query.edits[-1]["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("v2|editor|z0|draft123", callbacks)

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
