"""Render a local, offline review from the actual Telegram text and keyboards."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardMarkup

from music_links_bot.bot_preferences import preferences_view
from music_links_bot.bot_recent import render_drafts_view, render_recent_view
from music_links_bot.bot_runtime import UserSession
from music_links_bot.bot_ui import (
    build_create_keyboard,
    build_error_keyboard,
    build_home_text,
    build_publish_confirmation,
    build_start_keyboard,
    editor_appearance_rows,
    editor_delivery_rows,
    editor_hashtag_rows,
    editor_intro_rows,
    editor_overflow_rows,
    editor_platform_rows,
    editor_schedule_rows,
    editor_style_rows,
    editor_text_rows,
    editor_tools_rows,
    render_crate,
)
from music_links_bot.draft_model import new_track_draft
from music_links_bot.editor_view import render_track_draft
from music_links_bot.i18n import get_text
from music_links_bot.models import TrackMatch

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/ui-preview"


def screen(text, keyboard, *, art=False):
    return {
        "text": text,
        "art": art,
        "rows": [
            [
                {
                    "label": b.text,
                    "action": b.callback_data
                    or (
                        "sample"
                        if b.switch_inline_query_current_chat is not None
                        else "external"
                    ),
                    "style": b.style or "neutral",
                }
                for b in row
            ]
            for row in keyboard.inline_keyboard
        ],
    }


async def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    track = TrackMatch(
        artist="Sleep",
        title="Dopesmoker",
        links={
            "spotify": "https://open.spotify.com/track/example",
            "appleMusic": "https://music.apple.com/us/album/example/1",
        },
        page_url="https://song.link/example",
    )
    context = SimpleNamespace(
        application=SimpleNamespace(
            bot_data={"admin_chat_id": 7, "timezone_name": "Europe/Moscow"}
        )
    )
    draft = new_track_draft(track, chat_id=7, lang="ru", can_publish=True)
    draft["prefix"] = "<blockquote>Медленно, тяжело, на повторе.</blockquote>\n\n"
    draft["quote"] = True
    screens = {
        "welcome": screen(
            build_home_text(lang="ru", first_visit=True),
            build_start_keyboard(None, lang="ru", show_example=True),
            art=True,
        ),
        "home": screen(
            build_home_text(lang="ru", first_name="Артём"),
            build_start_keyboard(
                None,
                lang="ru",
                crate_count=3,
                is_admin=True,
                active_draft_id="demo",
                active_draft_label="Sleep — Dopesmoker",
            ),
        ),
        "create": screen(
            get_text("ru", "create_prompt"), build_create_keyboard(lang="ru")
        ),
        "card": screen(*render_track_draft(draft, context, draft_id="demo")),
        "editor": screen(
            *render_track_draft(draft, context, draft_id="demo", settings=True)
        ),
        "send": screen(
            get_text("ru", "ed_actions_title"),
            InlineKeyboardMarkup(editor_overflow_rows("demo", draft)),
        ),
        "confirm": screen(
            *build_publish_confirmation(
                "demo", draft, track, target="@stonerhand", lang="ru"
            )
        ),
        "schedule": screen(
            get_text("ru", "schedule_title")
            + "\n\nSleep — Dopesmoker\n\n"
            + get_text("ru", "schedule_timezone").format(zone="Europe/Moscow"),
            InlineKeyboardMarkup(
                editor_schedule_rows(
                    "demo",
                    draft,
                    now=datetime(2026, 9, 8, 14, 0, tzinfo=ZoneInfo("Europe/Moscow")),
                )
            ),
        ),
        "settings": screen(*preferences_view(UserSession(user_id=7), lang="ru")),
        "error": screen(
            "<b>Релиз пока не найден</b>\n\nЗапрос: Sleep — Dopesmoker\nПопробуй уточнить название или пришли ссылку.",
            build_error_keyboard(
                None, lang="ru", recovery="change", search_query="Sleep — Dopesmoker"
            ),
        ),
    }
    for name, key, builder in (
        ("appearance", "ed_appearance_title", editor_appearance_rows),
        ("text", "ed_text_title", editor_text_rows),
        ("style", "ed_style_title", editor_style_rows),
        ("format", "ed_delivery_title", editor_delivery_rows),
        ("intro", "ed_intro_title", editor_intro_rows),
        ("tags", "ed_hashtags_title", editor_hashtag_rows),
        ("tools", "ed_tools_title", editor_tools_rows),
    ):
        screens[name] = screen(
            get_text("ru", key), InlineKeyboardMarkup(builder("demo", draft))
        )
    screens["platforms"] = screen(
        get_text("ru", "ed_platforms_title"),
        InlineKeyboardMarkup(
            editor_platform_rows("demo", draft, track, ["spotify", "appleMusic"])
        ),
    )
    for section in ("language", "appearance", "tags"):
        screens["pref_" + section] = screen(
            *preferences_view(UserSession(user_id=7), lang="ru", section=section)
        )
    screens["published"] = {
        "text": "<b>Пост опубликован</b>\n\nSleep — Dopesmoker\n\nКанал: <b>@stonerhand</b>\n08.09 · 14:00",
        "art": False,
        "rows": [
            [{"label": "Открыть пост", "action": "external", "style": "success"}],
            [
                {
                    "label": get_text("ru", "ed_create_more"),
                    "action": "v2|menu|create",
                    "style": "neutral",
                }
            ],
        ],
    }
    screens["preview"] = screen(*render_track_draft(draft, context))
    screens["sent"] = {
        **screens["published"],
        "text": "<b>" + get_text("ru", "ed_sent") + "</b>\n\nSleep — Dopesmoker",
        "rows": screens["published"]["rows"][1:],
    }
    demo_drafts = {}
    for index in range(8):
        item = new_track_draft(track, chat_id=7, lang="ru")
        item["item"]["title"] = (
            "Dopesmoker"
            if index == 0
            else f"Live session {index} — A Very Long Release Title for a Narrow Screen"
        )
        demo_drafts[str(index)] = item
    context.application.bot_data["bot_history"] = {
        7: [
            {**item["item"], "source_url": "https://song.link/example"}
            for item in demo_drafts.values()
        ]
    }

    async def load(_context, draft_id):
        return demo_drafts.get(draft_id)

    for page in (0, 1):
        screens[f"recent{page}"] = screen(
            *await render_recent_view(context, user_id=7, lang="ru", page=page)
        )
        screens[f"drafts{page}"] = screen(
            *await render_drafts_view(
                context,
                user_id=7,
                lang="ru",
                draft_ids=list(demo_drafts),
                load_draft=load,
                page=page,
            )
        )
    items = [
        {"item": {"artist": artist, "title": title}}
        for artist, title in (
            ("Sleep", "Dopesmoker"),
            ("Kyuss", "Green Machine"),
            ("Deftones", "Rickets"),
        )
    ]
    screens["collection"] = screen(
        *render_crate(items, lang="ru", title="Тяжёлый вечер")
    )
    source = (ROOT / "scripts/ui_preview.html").read_text()
    source = source.replace(
        "__SCREEN_DATA__", json.dumps(screens, ensure_ascii=False).replace("</", "<\\/")
    )
    source = source.replace(
        "__BRAND_IMAGE__",
        base64.b64encode(
            (ROOT / "src/music_links_bot/assets/brandmark.png").read_bytes()
        ).decode(),
    )
    (OUTPUT / "index.html").write_text(source)
    print(OUTPUT / "index.html")


if __name__ == "__main__":
    asyncio.run(main())
