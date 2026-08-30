import ast
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import MessageEntity

from music_links_bot.bot import (
    _consume_pending_input,
    _dispatch_menu_action,
    _draft_intro_limit,
    _handle_editor_action,
    _render_track_draft,
)
from music_links_bot.bot_actions import action_spec
from music_links_bot.bot_builder import apply_intro_html
from music_links_bot.bot_pipeline import delivery_kind
from music_links_bot.bot_runtime import BotRuntime, CallbackAction
from music_links_bot.bot_storage import store_retry_sources
from music_links_bot.bot_ui import (
    build_error_keyboard,
    build_publish_confirmation,
    build_start_keyboard,
    render_crate,
)
from music_links_bot.draft_model import CURRENT_DRAFT_VERSION, new_track_draft
from music_links_bot.models import TrackMatch
from music_links_bot.publication_view import build_publication_view


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
        self.assertIn("Изменить", labels)

    def test_editor_card_snapshots_are_stable(self) -> None:
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
        snapshots = Path(__file__).parent / "snapshots"
        for settings, filename in (
            (False, "editor_card_ru.json"),
            (True, "editor_settings_ru.json"),
        ):
            draft = new_track_draft(_track(), chat_id=7, lang="ru")
            text, keyboard = _render_track_draft(
                draft,
                context,
                draft_id="draft123",
                settings=settings,
                show_status=settings,
            )
            actual = {
                "text": text,
                "rows": [
                    [
                        [
                            button.text,
                            button.callback_data,
                            button.url,
                            button.style,
                        ]
                        for button in row
                    ]
                    for row in keyboard.inline_keyboard
                ],
            }
            expected = json.loads((snapshots / filename).read_text(encoding="utf-8"))
            self.assertEqual(actual, expected)

    def test_intro_budget_depends_on_publication_format(self) -> None:
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
        draft = new_track_draft(_track(), chat_id=7, lang="ru")
        message_limit = _draft_intro_limit(draft, context)
        draft["as_photo"] = True
        caption_limit = _draft_intro_limit(draft, context)

        self.assertGreater(message_limit, caption_limit)
        self.assertLessEqual(caption_limit, 1024)

    def test_formatted_intro_stays_formatted_when_it_fits(self) -> None:
        draft = new_track_draft(_track(), chat_id=7, lang="ru")
        apply_intro_html(
            draft,
            "<b>Slowdive</b> и <i>Outbreak</i>",
            visible_length=22,
            max_length=900,
        )
        view = build_publication_view(
            draft,
            _track(),
            context=SimpleNamespace(application=SimpleNamespace(bot_data={})),
            include_channel_button=False,
        )

        self.assertIn("<b>Slowdive</b>", view.text)
        self.assertIn("<i>Outbreak</i>", view.text)
        self.assertFalse(view.intro.truncated)

    def test_publication_plan_freezes_delivery_decisions(self) -> None:
        draft = new_track_draft(_track(), chat_id=7, lang="ru")
        draft.update(
            {
                "custom_cover_file_id": "telegram-cover",
                "source_audio_file_id": "telegram-audio",
                "as_photo": True,
                "large_preview": False,
                "delivery_mode": "classic",
            }
        )

        view = build_publication_view(
            draft,
            _track(),
            context=SimpleNamespace(application=SimpleNamespace(bot_data={})),
            include_channel_button=False,
        )

        self.assertEqual(view.cover, "telegram-cover")
        self.assertEqual(view.source_audio_file_id, "telegram-audio")
        self.assertTrue(view.as_photo)
        self.assertFalse(view.prefer_large_preview)
        self.assertEqual(view.delivery_mode, "classic")

    def test_publish_confirmation_is_one_clear_primary_action(self) -> None:
        draft = new_track_draft(_track(), chat_id=7, lang="ru", can_publish=True)
        text, keyboard = build_publish_confirmation(
            "draft123", draft, _track(), target="@stonerhand", lang="ru"
        )

        self.assertIn("Готово к публикации", text)
        self.assertIn("Sleep", text)
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "✓ Опубликовать")
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

    async def test_native_intro_reply_preserves_telegram_formatting(self) -> None:
        draft = new_track_draft(_track(), chat_id=7, lang="ru")
        runtime = BotRuntime()
        session = await runtime.get_session(7)
        session.pending_input = {
            "kind": "intro",
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
            text="Slowdive и Outbreak",
            caption=None,
            entities=(MessageEntity(MessageEntity.BOLD, 0, 8),),
            caption_entities=(),
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=7, language_code="ru"),
        )
        context = SimpleNamespace(
            bot=SimpleNamespace(
                delete_message=AsyncMock(),
                edit_message_text=AsyncMock(),
            ),
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
        self.assertIn("<b>Slowdive</b>", stored["prefix"])
        context.bot.edit_message_text.assert_awaited_once()
        message.reply_text.assert_not_awaited()

    async def test_failed_batch_source_can_be_replaced_in_place(self) -> None:
        runtime = BotRuntime()
        context = SimpleNamespace(
            bot=SimpleNamespace(delete_message=AsyncMock()),
            application=SimpleNamespace(bot_data={"runtime": runtime}),
        )
        retry_id = await store_retry_sources(
            context,
            user_id=7,
            urls=[
                "https://open.spotify.com/track/first",
                "https://open.spotify.com/track/broken",
            ],
        )
        session = await runtime.get_session(7)
        session.pending_input = {
            "kind": "replace_source",
            "retry_id": retry_id,
            "source_index": 2,
            "prompt_message_id": 11,
            "created_at": int(time.time()),
        }
        await runtime.save_session(session)
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            chat_id=7,
            text="https://open.spotify.com/track/replacement",
            caption=None,
            entities=(),
            caption_entities=(),
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=7, language_code="ru"),
        )
        captured: list[str] = []

        async def capture_lookup(_update, _context) -> None:
            from music_links_bot.bot import _INPUT_OVERRIDE

            captured.append(str(_INPUT_OVERRIDE.get() or ""))

        with patch("music_links_bot.bot.track_lookup_message", capture_lookup):
            self.assertTrue(await _consume_pending_input(update, context))

        self.assertEqual(
            captured,
            [
                (
                    "https://open.spotify.com/track/first\n"
                    "https://open.spotify.com/track/replacement"
                )
            ],
        )
        context.bot.delete_message.assert_awaited_once()
        self.assertEqual((await runtime.get_session(7)).pending_input, {})

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

        self.assertEqual([len(row) for row in keyboard.inline_keyboard], [1, 1])
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "Повторить")
        self.assertEqual(keyboard.inline_keyboard[-1][0].text, "← Главное меню")

    def test_recovery_action_changes_with_error_context(self) -> None:
        cases = {
            "change": "Изменить запрос",
            "platforms": "Что поддерживается",
            "crate": "Вернуться в подборку",
        }
        for recovery, expected in cases.items():
            keyboard = build_error_keyboard(
                None,
                lang="ru",
                search_query="Sleep — Dopesmoker",
                recovery=recovery,
            )
            self.assertEqual(keyboard.inline_keyboard[0][0].text, expected)
            self.assertEqual([len(row) for row in keyboard.inline_keyboard], [1, 1])

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

    def test_current_callback_buttons_have_registered_actions(self) -> None:
        missing: list[tuple[str, int, str, str]] = []
        source_root = Path(__file__).resolve().parents[1] / "src" / "music_links_bot"
        for path in source_root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "encode_callback"
                    and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[1], ast.Constant)
                ):
                    continue
                scope = str(node.args[0].value)
                action = str(node.args[1].value)
                if action_spec(scope, action) is None:
                    missing.append((path.name, node.lineno, scope, action))
        self.assertEqual(missing, [])

    def test_collection_controls_are_touch_friendly(self) -> None:
        items = [
            {"item": {"artist": "Artist", "title": f"Track {index}"}}
            for index in range(1, 11)
        ]
        keyboard = render_crate(items, lang="ru")[1]
        self.assertTrue(all(len(row) <= 2 for row in keyboard.inline_keyboard))

    def test_both_languages_have_complete_builder_keyboards(self) -> None:
        for lang in ("ru", "en"):
            keyboard = build_start_keyboard(None, lang=lang, crate_count=2)
            for row in keyboard.inline_keyboard:
                self.assertTrue(all(button.text.strip() for button in row))

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
        bundle.tracks = []
        bundle.videos = [SimpleNamespace(title="Live")]
        self.assertEqual(delivery_kind(bundle), "videos")
        bundle.tracks = [_track()]
        bundle.content_type_count = 2
        bundle.item_count = 2
        self.assertEqual(delivery_kind(bundle), "mixed")
        bundle.item_count = 0
        self.assertEqual(delivery_kind(bundle), "empty")


if __name__ == "__main__":
    unittest.main()
