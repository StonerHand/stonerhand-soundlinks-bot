from __future__ import annotations

import hashlib
import re
from html import unescape
from urllib.parse import urlparse

from telegram import InlineKeyboardMarkup

from music_links_bot.bot_ui import (
    build_delivery_success_keyboard,
    build_error_keyboard,
    build_home_text,
    build_start_keyboard,
    editor_more_rows,
    editor_rows,
)
from music_links_bot.collection_collage import collection_collage_preview_url
from music_links_bot.formatter import format_collection_message, format_track_message
from music_links_bot.i18n import get_text
from music_links_bot.keyboards import _build_collection_keyboard, _build_link_keyboard
from music_links_bot.models import TrackMatch
from music_links_bot.publication_contract import (
    RenderedPublication,
    validate_rendered_publication,
)
from music_links_bot.rich_publications import build_rich_card_html
from music_links_bot.sharing import (
    add_share_button,
    collection_result_title,
    make_channel_safe_keyboard,
)
from music_links_bot.telegram_buttons import button as InlineKeyboardButton

_TAG_RE = re.compile(r"<[^>]*>")
_DETERMINISTIC_COLLAGE_KEY = hashlib.sha256(b"public-release-smoke-fixture").hexdigest()


def build_release_smoke_report() -> dict[str, object]:
    """Render the release-critical UI matrix without network access.

    The same deterministic report is exercised in CI and exposed read-only in
    production. It catches broken platform destinations, missing artwork,
    leaked source links, partial-count drift, and invalid channel keyboards.
    """
    primary = _track(
        "Love Song - song and lyrics by Lime Garden | Spotify",
        "Lime Garden",
        spotify_id="3E4MuCjetGIkeu2N8fFHgr",
        apple_id="1780000001",
        artwork="https://images.example/lime-garden.jpg",
    )
    soundcloud = TrackMatch(
        title="Ethan Kath DJ Set — Park Live 2013",
        artist="StonerHand",
        links={
            "soundcloud": (
                "https://soundcloud.com/stoner-hand/"
                "ethan-kath-dj-set-park-live-moscow-30062013"
            )
        },
        thumbnail_url="https://images.example/park-live.jpg",
    )
    collection = [
        _track(
            "A Torinói Ló",
            "Kokomo",
            spotify_id="2eaZjrZAYZsDf1UHa0Uw0A",
            artwork="https://images.example/kokomo-1.jpg",
        ),
        _track(
            "The Lonesome Foghorn Blows",
            "Kokomo",
            spotify_id="3M7ea9TwGB5uy0cqmVQeu7",
            artwork="https://images.example/kokomo-2.jpg",
        ),
        _track(
            "1758 Times of Weird Sadness",
            "Kokomo",
            spotify_id="2Px01k5PAKhbfF8KCAKN7I",
            artwork="https://images.example/kokomo-3.jpg",
        ),
    ]

    classic_keyboard = _build_link_keyboard(
        primary.links,
        release_page_url=primary.page_url,
        release_kind=primary.kind,
    )
    classic = RenderedPublication(
        text=format_track_message(primary),
        keyboard=classic_keyboard,
        preview_url=primary.thumbnail_url,
        cover_url=primary.thumbnail_url,
        source_urls=tuple(primary.links.values()),
        content_kind="track",
        cover_expected=True,
    )
    soundcloud_card = RenderedPublication(
        text=format_track_message(soundcloud),
        keyboard=_build_link_keyboard(soundcloud.links),
        preview_url=soundcloud.thumbnail_url,
        cover_url=soundcloud.thumbnail_url,
        source_urls=tuple(soundcloud.links.values()),
        content_kind="track",
        cover_expected=True,
    )

    collection_keyboard = _build_collection_keyboard(collection)
    collection_preview = collection_collage_preview_url(
        collection,
        base_url="https://tg-bot-sh.vercel.app",
        signing_secret=_DETERMINISTIC_COLLAGE_KEY,
    )
    complete_collection = RenderedPublication(
        text=format_collection_message(
            collection,
            title=collection_result_title("ru", found=3, total=3),
        ),
        keyboard=collection_keyboard,
        preview_url=collection_preview,
        source_urls=tuple(track.links["spotify"] for track in collection),
        found_count=3,
        requested_count=3,
        content_kind="collection",
        cover_expected=True,
    )
    partial_collection = RenderedPublication(
        text=format_collection_message(
            collection,
            title=collection_result_title("ru", found=3, total=4),
        ),
        keyboard=collection_keyboard,
        preview_url=collection[0].thumbnail_url,
        source_urls=tuple(track.links["spotify"] for track in collection),
        found_count=3,
        requested_count=4,
        content_kind="collection",
        cover_expected=True,
    )

    channel_keyboard = add_share_button(
        classic_keyboard,
        share_query="sh5|t3E4MuCjetGIkeu2N8fFHgr",
        label="Поделиться",
    )
    channel = RenderedPublication(
        text=classic.text,
        keyboard=make_channel_safe_keyboard(channel_keyboard),
        preview_url=classic.preview_url,
        cover_url=classic.cover_url,
        source_urls=classic.source_urls,
        mode="channel",
        content_kind="track",
        cover_expected=True,
    )
    inline = RenderedPublication(
        text=classic.text,
        keyboard=channel_keyboard,
        preview_url=classic.preview_url,
        cover_url=classic.cover_url,
        source_urls=classic.source_urls,
        mode="inline",
        content_kind="track",
        cover_expected=True,
    )

    rich_html = build_rich_card_html(
        {"prefix": "", "quote": False},
        primary,
        hashtags="#stonerhand #track #indiepop",
        reply_markup=classic_keyboard,
    )
    rich = RenderedPublication(
        text=classic.text,
        keyboard=classic.keyboard,
        preview_url=classic.preview_url,
        cover_url=classic.cover_url,
        source_urls=classic.source_urls,
        mode="rich",
        content_kind="track",
        cover_expected=True,
    )

    cases = {
        "classic_track": _summarize(
            classic,
            extra_checks={
                "provider_copy_absent": _provider_copy_absent(classic.text),
            },
        ),
        "soundcloud_source_only": _summarize(
            soundcloud_card,
            forbidden_button_markers=("spotify",),
        ),
        "collection_complete": _summarize(complete_collection),
        "collection_partial": _summarize(partial_collection),
        "inline_share": _summarize(inline),
        "channel_keyboard": _summarize(
            channel,
            forbid_inline_switch=True,
        ),
        "rich_card": _summarize(
            rich,
            extra_checks={
                "has_media": "<figure><img " in rich_html,
                "has_buttons": "<tg-button" in rich_html,
                "provider_copy_absent": _provider_copy_absent(rich_html),
                "within_html_limit": len(rich_html) <= 30_000,
            },
        ),
    }
    ux = _build_ui_contract()
    return {
        "ok": all(bool(case["ok"]) for case in cases.values()) and bool(ux["ok"]),
        "service": "publication-release-smoke",
        "contract": 4,
        "cases": cases,
        "ux": ux,
    }


def _build_ui_contract() -> dict[str, object]:
    """Guard the small-screen navigation and editor hierarchy in production."""
    draft = {
        "lang": "ru",
        "hashtags": True,
        "quote": True,
        "preset": "clean",
        "delivery_mode": "auto",
        "platforms": ["spotify", "appleMusic"],
        "can_publish": False,
    }
    screens = {
        "home_ru": _summarize_ui_keyboard(
            build_start_keyboard(None, lang="ru", crate_count=2),
            expected_primary="＋ Создать пост",
        ),
        "home_en": _summarize_ui_keyboard(
            build_start_keyboard(None, lang="en", crate_count=2),
            expected_primary="＋ Create post",
        ),
        "first_run": _summarize_ui_keyboard(
            build_start_keyboard(
                None,
                lang="ru",
                show_example=True,
                show_tour=True,
            ),
            expected_primary="＋ Создать пост",
        ),
        "error_change_query": _summarize_ui_keyboard(
            build_error_keyboard(
                None,
                lang="ru",
                recovery="change",
                search_query="Sleep — Dopesmoker",
            ),
            expected_primary="Изменить запрос",
        ),
        "error_retry": _summarize_ui_keyboard(
            build_error_keyboard(None, lang="ru", recovery="retry"),
            expected_primary="Повторить",
        ),
        "error_platforms": _summarize_ui_keyboard(
            build_error_keyboard(None, lang="ru", recovery="platforms"),
            expected_primary="Что поддерживается",
        ),
        "error_crate": _summarize_ui_keyboard(
            build_error_keyboard(None, lang="ru", recovery="crate"),
            expected_primary="Вернуться в подборку",
        ),
        "delivery_success": _summarize_ui_keyboard(
            build_delivery_success_keyboard(
                lang="ru",
                share_query="sh5|t3E4MuCjetGIkeu2N8fFHgr",
            ),
            expected_primary="+ Создать ещё",
        ),
        "editor_actions": _summarize_ui_keyboard(
            InlineKeyboardMarkup(editor_rows("smoke", draft)),
            expected_primary="Отправить себе",
        ),
        "editor_settings": _summarize_ui_keyboard(
            InlineKeyboardMarkup(editor_more_rows("smoke", draft)),
            expected_primary="✓ Готово",
            expected_style="success",
        ),
    }
    home_text = build_home_text(
        lang="ru",
        first_visit=True,
        crate_count=2,
    )
    create_text = get_text("ru", "create_prompt")
    copy_checks = {
        "home_explains_link": "ссылку на трек" in home_text,
        "home_explains_query": "Deftones — Rickets" in home_text,
        "home_explains_collection": "несколько ссылок" in home_text,
        "home_explains_intro": "подводкой" in home_text,
        "create_explains_one_link_per_line": "каждую с новой строки" in create_text,
        "create_explains_intro": "подводкой" in create_text,
        "localized_hierarchy_matches": (
            screens["home_ru"]["rows"] == screens["home_en"]["rows"]
        ),
    }
    return {
        "ok": all(bool(screen["ok"]) for screen in screens.values())
        and all(copy_checks.values()),
        "screens": screens,
        "copy_checks": copy_checks,
    }


def _summarize_ui_keyboard(
    keyboard: InlineKeyboardMarkup,
    *,
    expected_primary: str,
    expected_style: str = "primary",
) -> dict[str, object]:
    rows = keyboard.inline_keyboard
    buttons = [button for row in rows for button in row]
    labels = [button.text for button in buttons]
    accented = [
        (button.text, button.style)
        for button in buttons
        if button.style in {"primary", "success", "danger"}
    ]
    callbacks = [
        button.callback_data for button in buttons if button.callback_data is not None
    ]
    checks = {
        "touch_friendly_rows": all(1 <= len(row) <= 2 for row in rows),
        "labels_present": all(label.strip() for label in labels),
        "labels_descriptive": all(
            any(char.isalnum() for char in label) for label in labels
        ),
        "styled_actions_have_text": all(
            any(char.isalnum() for char in label) for label, _style in accented
        ),
        "destructive_actions_are_named": all(
            style != "danger"
            or any(
                marker in label.casefold()
                for marker in ("удал", "очист", "delete", "clear", "replace", "замен")
            )
            for label, style in accented
        ),
        "callbacks_bounded": all(
            1 <= len(value.encode("utf-8")) <= 64 for value in callbacks
        ),
        "single_primary_action": accented == [(expected_primary, expected_style)],
        "mini_app_absent": all(button.web_app is None for button in buttons),
    }
    return {
        "ok": all(checks.values()),
        "rows": [len(row) for row in rows],
        "buttons": labels,
        "checks": checks,
    }


def _provider_copy_absent(value: str) -> bool:
    lowered = value.casefold()
    return "| spotify" not in lowered and "song and lyrics by" not in lowered


def _track(
    title: str,
    artist: str,
    *,
    spotify_id: str,
    artwork: str,
    apple_id: str | None = None,
) -> TrackMatch:
    links = {"spotify": f"https://open.spotify.com/track/{spotify_id}"}
    if apple_id:
        links["appleMusic"] = f"https://music.apple.com/us/song/x/{apple_id}"
    return TrackMatch(
        title=title,
        artist=artist,
        links=links,
        page_url=f"https://song.link/s/{spotify_id}",
        thumbnail_url=artwork,
    )


def _summarize(
    publication: RenderedPublication,
    *,
    forbidden_button_markers: tuple[str, ...] = (),
    forbid_inline_switch: bool = False,
    extra_checks: dict[str, bool] | None = None,
) -> dict[str, object]:
    result = validate_rendered_publication(publication)
    keyboard = publication.keyboard
    buttons = [
        item for row in (keyboard.inline_keyboard if keyboard else ()) for item in row
    ]
    labels = [button.text for button in buttons]
    destinations = [_button_destination(button) for button in buttons]
    checks = dict(extra_checks or {})
    # A single-release Songlink button is the canonical cross-platform CTA.
    # Collection rows also use Songlink, but every row represents a different
    # release and deliberately stays neutral to preserve a calm scan pattern.
    hub_buttons = (
        [
            button
            for button in buttons
            if _host(button.url) in {"song.link", "album.link", "odesli.co"}
        ]
        if publication.found_count == 1
        else []
    )
    if hub_buttons:
        checks["hub_is_primary"] = all(
            button.style == "primary" for button in hub_buttons
        )
        checks["provider_shortcuts_are_neutral"] = all(
            button.style is None
            for button in buttons
            if button.url and button not in hub_buttons
        )
    if forbidden_button_markers:
        checks["forbidden_buttons_absent"] = not any(
            marker in label.casefold()
            for marker in forbidden_button_markers
            for label in labels
        )
    if forbid_inline_switch:
        checks["channel_safe"] = not any(
            any(
                (
                    button.switch_inline_query is not None,
                    button.switch_inline_query_current_chat is not None,
                    button.switch_inline_query_chosen_chat is not None,
                )
            )
            for button in buttons
        )
    return {
        "ok": result.ready and all(checks.values()),
        "issues": list(result.blocking_codes),
        "mode": publication.mode,
        "count": [publication.found_count, publication.requested_count],
        "lines": _visible_lines(publication.text),
        "buttons": labels,
        "destinations": destinations,
        "preview_host": _host(publication.preview_url),
        "checks": checks,
    }


def _button_destination(button: InlineKeyboardButton) -> str:
    if button.url:
        return _host(button.url)
    if button.callback_data:
        return "callback"
    if any(
        (
            button.switch_inline_query is not None,
            button.switch_inline_query_current_chat is not None,
            button.switch_inline_query_chosen_chat is not None,
        )
    ):
        return "inline"
    return "other"


def _host(value: str | None) -> str:
    return (urlparse(value or "").hostname or "").removeprefix("www.")


def _visible_lines(value: str) -> list[str]:
    visible = unescape(_TAG_RE.sub("", value))
    return [line for line in visible.splitlines() if line.strip()]
