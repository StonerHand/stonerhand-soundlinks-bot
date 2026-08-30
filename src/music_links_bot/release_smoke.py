from __future__ import annotations

import hashlib
import re
from html import unescape
from urllib.parse import urlparse

from music_links_bot.collection_collage import collection_collage_preview_url
from music_links_bot.formatter import format_collection_message, format_track_message
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
        label="↗ Поделиться",
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
    return {
        "ok": all(bool(case["ok"]) for case in cases.values()),
        "service": "publication-release-smoke",
        "contract": 1,
        "cases": cases,
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
