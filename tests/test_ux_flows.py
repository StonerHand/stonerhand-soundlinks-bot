"""User-facing flows added in the UX redesign."""

import asyncio
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from music_links_bot.human_time import human_datetime, parse_human_datetime

MSK = ZoneInfo("Europe/Moscow")
# Wednesday 12 August 2026, 10:00 Moscow time.
NOW = datetime(2026, 8, 12, 10, 0, tzinfo=MSK).timestamp()


def at(day: int, hour: int, minute: int = 0, month: int = 8) -> float:
    return datetime(2026, month, day, hour, minute, tzinfo=MSK).timestamp()


@pytest.mark.parametrize(
    "moment,expected",
    [
        (at(12, 20), "сегодня 20:00"),
        (at(13, 12), "завтра 12:00"),
        (at(11, 9), "вчера 09:00"),
        (at(14, 21), "пт 21:00"),
        (at(25, 18), "25.08 18:00"),
    ],
)
def test_human_datetime_speaks_like_a_person(moment, expected):
    assert human_datetime(moment, timezone_name="Europe/Moscow", now=NOW) == expected


def test_human_datetime_in_english():
    assert (
        human_datetime(at(13, 12), timezone_name="Europe/Moscow", lang="en", now=NOW)
        == "tomorrow 12:00"
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("21:00", at(12, 21)),
        ("9:30", at(13, 9, 30)),  # already passed today → tomorrow
        ("завтра 18:30", at(13, 18, 30)),
        ("Завтра в 18:30", at(13, 18, 30)),
        ("сегодня 23:15", at(12, 23, 15)),
        ("пт 21:00", at(14, 21)),
        ("в пятницу 21:00", at(14, 21)),
        ("ср 09:00", at(19, 9)),  # this Wednesday already passed → next week
        ("fri 21:00", at(14, 21)),
        ("15.08 19:30", at(15, 19, 30)),
        ("через 2 часа", NOW + 2 * 3600),
        ("через час", NOW + 3600),
        ("через 30 минут", NOW + 1800),
        ("in 3 hours", NOW + 3 * 3600),
    ],
)
def test_parse_human_datetime_understands_natural_phrases(text, expected):
    assert parse_human_datetime(text, timezone_name="Europe/Moscow", now=NOW) == (
        expected
    )


@pytest.mark.parametrize(
    "text",
    ["", "когда-нибудь", "25:00", "сегодня 09:00", "31.02 10:00", "через 0 часов"],
)
def test_parse_human_datetime_rejects_nonsense_and_the_past(text):
    assert parse_human_datetime(text, timezone_name="Europe/Moscow", now=NOW) is None


def test_schedule_input_accepts_natural_time_but_keeps_the_horizon():
    from music_links_bot.bot_builder import parse_schedule_datetime

    now = datetime.fromtimestamp(NOW, MSK)
    assert parse_schedule_datetime("завтра 18:30", now=now) == int(at(13, 18, 30))
    assert parse_schedule_datetime("через 400 дней", now=now) is None


class FakeQuery:
    def __init__(self, user_id=7):
        self.from_user = SimpleNamespace(id=user_id, language_code="ru")
        self.message = SimpleNamespace(chat_id=user_id)
        self.answers = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)


def _published_draft(*, published_at):
    from music_links_bot.draft_model import new_track_draft
    from music_links_bot.models import TrackMatch

    draft = new_track_draft(
        TrackMatch(
            artist="Sleep",
            title="Dragonaut",
            links={"spotify": "https://open.spotify.com/track/abc"},
        ),
        chat_id=7,
        lang="ru",
        can_publish=True,
    )
    draft.update(
        published_at=published_at,
        published_message_id=55,
        published_target="@stonerhand",
    )
    return draft


def _context(draft):
    return SimpleNamespace(
        bot=SimpleNamespace(delete_message=AsyncMock(), username="StonerHandBot"),
        application=SimpleNamespace(
            bot_data={"drafts": {"d1": draft}, "admin_chat_id": 7}
        ),
    )


def test_undo_publish_deletes_the_post_and_restores_the_draft():
    from music_links_bot.bot import _handle_editor_action

    draft = _published_draft(published_at=int(time.time()) - 30)
    context = _context(draft)
    query = FakeQuery()
    asyncio.run(_handle_editor_action(query, context, "un", "d1"))

    context.bot.delete_message.assert_awaited_once_with(
        chat_id="@stonerhand", message_id=55
    )
    stored = context.application.bot_data["drafts"]["d1"]
    assert "published_at" not in stored
    assert "Публикация отменена" in query.answers[-1][0]
    assert query.edits[-1]["text"].startswith("📝 <b>Черновик</b>")


def test_undo_publish_refuses_after_two_minutes():
    from music_links_bot.bot import _handle_editor_action

    draft = _published_draft(published_at=int(time.time()) - 600)
    context = _context(draft)
    query = FakeQuery()
    asyncio.run(_handle_editor_action(query, context, "un", "d1"))

    context.bot.delete_message.assert_not_awaited()
    assert query.answers[-1][1].get("show_alert") is True
    assert "первые 2 минуты" in query.answers[-1][0]


def _inline_update(query_text, user_id=7):
    inline = SimpleNamespace(
        query=query_text,
        from_user=SimpleNamespace(id=user_id, language_code="ru"),
        chat_type="private",
        answer=AsyncMock(),
    )
    return SimpleNamespace(inline_query=inline), inline


def test_share_sends_the_exact_edited_post_to_its_owner():
    from music_links_bot.bot_inline import inline_query_handler
    from music_links_bot.bot_storage import store_draft

    draft = _published_draft(published_at=None)
    draft.update(prefix="<b>Моя подводка</b>\n", quote=True, hashtags=False)
    context = _context({})
    context.application.bot_data["drafts"] = {}
    asyncio.run(store_draft(context, "abcdef0123456789", draft))
    update, inline = _inline_update("post:abcdef0123456789")
    asyncio.run(inline_query_handler(update, context))

    results = inline.answer.await_args.args[0]
    assert len(results) == 1
    text = results[0].input_message_content.message_text
    assert "Моя подводка" in text
    assert "#stonerhand" not in text
    assert inline.answer.await_args.kwargs["is_personal"] is True


def test_share_never_exposes_someone_elses_draft():
    from music_links_bot.bot_inline import inline_query_handler
    from music_links_bot.bot_storage import store_draft

    draft = _published_draft(published_at=None)
    context = _context({})
    context.application.bot_data["drafts"] = {}
    asyncio.run(store_draft(context, "abcdef0123456789", draft))
    update, inline = _inline_update("post:abcdef0123456789", user_id=8)
    asyncio.run(inline_query_handler(update, context))

    assert inline.answer.await_args.args[0] == []


def _crate_items(*, broken=False):
    links = {} if broken else {"spotify": "https://open.spotify.com/track/abc"}
    return [
        {"item": {"artist": "Sleep", "title": "Dragonaut", "links": links}},
        {
            "item": {
                "artist": "Kyuss",
                "title": "Gardenia",
                "links": {"spotify": "https://open.spotify.com/track/def"},
            }
        },
    ]


def test_collection_has_one_clear_main_action_for_each_role():
    from music_links_bot.bot_ui import render_crate

    _, owner = render_crate(
        _crate_items(), lang="ru", can_publish=True, share_query="sh5|x"
    )
    owner_labels = [b.text for row in owner.inline_keyboard for b in row]
    assert "📣 Опубликовать подборку" in owner_labels
    primary = [
        b.text for row in owner.inline_keyboard for b in row if b.style == "primary"
    ]
    assert primary == ["📣 Опубликовать подборку"]

    _, guest = render_crate(_crate_items(), lang="ru", share_query="sh5|x")
    primary = [
        b.text for row in guest.inline_keyboard for b in row if b.style == "primary"
    ]
    assert primary == ["↗️ Поделиться подборкой"]


def test_collection_warnings_are_grouped_and_point_to_the_fix():
    from music_links_bot.bot_ui import render_crate

    text, keyboard = render_crate(_crate_items(broken=True), lang="ru")
    assert "⚠️ Нет ссылки или данных: №1 — замени." in text
    assert "ℹ️ Без обложки: №1, №2 — коллаж соберётся из остальных." in text
    fix = next(
        b for row in keyboard.inline_keyboard for b in row if b.text.startswith("⚠️")
    )
    assert fix.text == "⚠️ Исправить №1"
    assert fix.callback_data.startswith("v2|crate|select|")


def test_owner_publishes_the_collection_to_the_channel():
    import os
    from unittest.mock import patch

    from music_links_bot.bot_crate import crate_revision
    from music_links_bot.bot_crate_handlers import _publish_crate

    items = _crate_items()
    sent = SimpleNamespace(message_id=77)
    context = SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock(return_value=sent)),
        application=SimpleNamespace(
            bot_data={"admin_chat_id": 7, "bot_crates": {7: items}}
        ),
    )
    query = FakeQuery()
    with (
        patch.dict(os.environ, {"BOT_TOKEN": "1:x"}),
        patch(
            "music_links_bot.bot_crate_handlers.load_crate",
            new=AsyncMock(return_value=items),
        ),
        patch("music_links_bot.bot_crate_handlers.safe_edit", new=AsyncMock()) as edit,
    ):
        asyncio.run(
            _publish_crate(
                query,
                context,
                user_id=7,
                lang="ru",
                title="",
                revision=crate_revision(items),
            )
        )
    kwargs = context.bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == "@stonerhand"
    assert "Dragonaut" in kwargs["text"] and "Gardenia" in kwargs["text"]
    assert "Подборка опубликована" in edit.await_args.args[1]


def test_only_the_owner_can_publish_a_collection():
    from music_links_bot.bot_crate_handlers import _publish_crate

    context = SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock()),
        application=SimpleNamespace(bot_data={"admin_chat_id": 1}),
    )
    query = FakeQuery()
    asyncio.run(
        _publish_crate(query, context, user_id=7, lang="ru", title="", revision="x")
    )
    context.bot.send_message.assert_not_awaited()
    assert query.answers[-1][1].get("show_alert") is True


def test_settings_are_one_level_and_owner_rows_only_for_the_owner():
    from music_links_bot.bot_preferences import preferences_view
    from music_links_bot.bot_runtime import UserSession

    session = UserSession(user_id=7, quick_publish=True)
    _, guest = preferences_view(session, lang="ru")
    guest_labels = [b.text for row in guest.inline_keyboard for b in row]
    assert guest_labels[:4] == [
        "🌐 Язык · Как в Telegram",
        "🎨 Вид новых постов · Как в прошлый раз",
        "# Теги · Как в прошлый раз",
        "🎶 Подборки · Одна колонка",
    ]
    assert not any("Подпись" in label for label in guest_labels)

    _, owner = preferences_view(session, lang="ru", is_admin=True)
    owner_labels = [b.text for row in owner.inline_keyboard for b in row]
    assert "⚡ Быстрая публикация · вкл" in owner_labels
    assert any(label.startswith("✍️ Подпись на обложке · ") for label in owner_labels)
    # The retired "compact" look is never offered again.
    _, look = preferences_view(session, lang="ru", section="appearance")
    assert "Компактно" not in " ".join(
        b.text for row in look.inline_keyboard for b in row
    )


def test_owner_cover_label_travels_signed_to_the_image_function():
    import os
    from unittest.mock import patch
    from urllib.parse import parse_qs, urlparse

    from music_links_bot.collection_collage import (
        branded_artwork_preview_url,
        decode_collage_payload,
    )
    from music_links_bot.cover_style import brand_label, set_brand_label_override

    env = {"WEBHOOK_BASE_URL": "https://bot.example", "BOT_TOKEN": "1:x"}
    try:
        with patch.dict(os.environ, env):
            set_brand_label_override("@my_label")
            assert brand_label() == "@my_label"
            url = branded_artwork_preview_url("https://i.scdn.co/image/cover")
            query = parse_qs(urlparse(url).query)
            assert query["l"] == ["@my_label"]
            payload, signature = query["p"][0], query["s"][0]
            assert decode_collage_payload(
                payload,
                signature,
                signing_secret="1:x",
                allow_single=True,
                label="@my_label",
            )
            # A forged label is rejected: it is covered by the signature.
            assert (
                decode_collage_payload(
                    payload,
                    signature,
                    signing_secret="1:x",
                    allow_single=True,
                    label="@forged",
                )
                is None
            )
    finally:
        set_brand_label_override(None)
    assert brand_label() == "@stonerhand"


def test_quick_publish_posts_right_away_with_undo():
    from unittest.mock import patch

    from music_links_bot.bot_quick_publish import try_quick_publish
    from music_links_bot.bot_runtime import BotRuntime

    draft = _published_draft(published_at=None)
    for key in ("published_at", "published_message_id", "published_target"):
        draft.pop(key)
    runtime = BotRuntime()
    session = asyncio.run(runtime.get_session(7))
    session.quick_publish = True
    asyncio.run(runtime.save_session(session))
    context = _context({})
    context.application.bot_data.update(runtime=runtime, drafts={})
    message = SimpleNamespace(reply_text=AsyncMock())
    sent = SimpleNamespace(message_id=91, link="https://t.me/stonerhand/91")
    from music_links_bot.models import TrackMatch

    with (
        patch("music_links_bot.bot._publish_draft", new=AsyncMock(return_value=sent)),
        patch(
            "music_links_bot.bot._find_posted_record", new=AsyncMock(return_value=None)
        ),
        patch("music_links_bot.bot._schedule_mark_posted", new=AsyncMock()),
    ):
        published = asyncio.run(
            try_quick_publish(
                message,
                context,
                draft_id="q1",
                draft=draft,
                track=TrackMatch(**draft["item"]),
                user_id=7,
            )
        )
    assert published is True
    assert draft["published_message_id"] == 91
    labels = [
        b.text
        for row in message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard
        for b in row
    ]
    assert "↩️ Отменить" in labels and "🔗 Открыть пост" in labels


def test_quick_publish_never_reposts_a_release_silently():
    from unittest.mock import patch

    from music_links_bot.bot_quick_publish import try_quick_publish
    from music_links_bot.bot_runtime import BotRuntime
    from music_links_bot.models import TrackMatch

    draft = _published_draft(published_at=None)
    runtime = BotRuntime()
    session = asyncio.run(runtime.get_session(7))
    session.quick_publish = True
    asyncio.run(runtime.save_session(session))
    context = _context({})
    context.application.bot_data.update(runtime=runtime)
    publish = AsyncMock()
    with (
        patch("music_links_bot.bot._publish_draft", new=publish),
        patch(
            "music_links_bot.bot._find_posted_record",
            new=AsyncMock(return_value={"date": "01.01.2026"}),
        ),
    ):
        result = asyncio.run(
            try_quick_publish(
                SimpleNamespace(reply_text=AsyncMock()),
                context,
                draft_id="q1",
                draft=draft,
                track=TrackMatch(**draft["item"]),
                user_id=7,
            )
        )
    assert result is False
    publish.assert_not_awaited()


def test_channel_check_explains_missing_rights_in_plain_words():
    from music_links_bot.bot_menu import channel_command

    member = SimpleNamespace(
        status="administrator", can_post_messages=True, can_delete_messages=False
    )
    bot = SimpleNamespace(id=1, get_chat_member=AsyncMock(return_value=member))
    context = SimpleNamespace(
        bot=bot, application=SimpleNamespace(bot_data={"admin_chat_id": 7})
    )
    message = SimpleNamespace(
        chat=SimpleNamespace(type="private"), chat_id=7, reply_text=AsyncMock()
    )
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=7, language_code="ru"),
    )
    asyncio.run(channel_command(update, context))
    text = message.reply_text.await_args.args[0]
    assert "✅ Бот может публиковать посты" in text
    assert "❌ Бот не может удалять сообщения" in text
    assert "/channel ещё раз" in text


def test_edit_in_bot_link_opens_a_private_draft_of_that_release():
    from unittest.mock import patch

    from telegram import InlineKeyboardMarkup

    from music_links_bot.models import TrackMatch
    from music_links_bot.release_panel import (
        add_release_panel,
        edit_in_bot_url,
        start_release_panel,
    )

    track = TrackMatch(
        artist="Sleep",
        title="Dragonaut",
        links={"spotify": "https://open.spotify.com/track/abc"},
    )
    context = SimpleNamespace(
        bot=SimpleNamespace(username="StonerHandBot"),
        application=SimpleNamespace(bot_data={}),
        args=[],
    )
    keyboard = asyncio.run(
        add_release_panel(InlineKeyboardMarkup([]), context, track, inline=True)
    )
    token = keyboard.inline_keyboard[-1][0].url.split("start=release_", 1)[1]
    assert edit_in_bot_url(context, token).endswith(f"?start=edit_{token}")

    context.args = [f"edit_{token}"]
    update = SimpleNamespace(
        effective_message=SimpleNamespace(chat=SimpleNamespace(type="private")),
        effective_user=SimpleNamespace(id=7, language_code="ru"),
    )
    with patch("music_links_bot.bot._send_track_draft", new=AsyncMock()) as send:
        assert asyncio.run(start_release_panel(update, context)) is True
    assert send.await_args.args[2].title == "Dragonaut"
    assert send.await_args.kwargs["user_id"] == 7
