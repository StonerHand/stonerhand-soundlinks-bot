from __future__ import annotations

import re
import unicodedata

from telegram import (
    InlineKeyboardButton as TelegramInlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from telegram.ext import ContextTypes

from music_links_bot.constants import CHANNEL_USERNAME, PLATFORM_LABELS
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TitleMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.release_hubs import resolve_release_hub_url
from music_links_bot.release_preferences import current_presentation
from music_links_bot.release_presentation import (
    compact_release_title,
)
from music_links_bot.telegram_buttons import (
    ButtonTone,
    button as InlineKeyboardButton,
    url_button,
)
from music_links_bot.url_utils import (
    cache_key_for_url,
    is_platform_destination_url,
)

CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"
CHANNEL_BUTTON_TEXT = "🪨 Открыть канал"
DEFAULT_UI_MODE = "stonerhand"
MAX_TWO_COLUMN_BUTTON_TEXT_LENGTH = 24
# The three most used services sit in one row under the "listen" hub button.
MAX_VISIBLE_PLATFORM_BUTTONS = 3
PLATFORM_BUTTON_ICONS = {
    "spotify": "🟢",
    "appleMusic": "🍎",
    "applePodcasts": "🟣",
    "youtubeMusic": "🔴",
    "soundcloud": "🟠",
    "deezer": "🟣",
    "bandcamp": "🔵",
    "tidal": "⚫",
    "yandexMusic": "🟡",
}
DEFAULT_PLATFORM_ORDER = (
    "spotify",
    "appleMusic",
    "applePodcasts",
    "youtubeMusic",
    "soundcloud",
    "deezer",
    "tidal",
    "yandexMusic",
    "bandcamp",
)
PRIMARY_PLATFORM_ALIASES = {
    "spotify": "spotify",
    "apple": "appleMusic",
    "applemusic": "appleMusic",
    "itunes": "appleMusic",
    "applepodcasts": "applePodcasts",
    "podcasts": "applePodcasts",
    "youtube": "youtubeMusic",
    "youtubemusic": "youtubeMusic",
    "ytmusic": "youtubeMusic",
    "soundcloud": "soundcloud",
    "sc": "soundcloud",
    "deezer": "deezer",
    "bandcamp": "bandcamp",
    "tidal": "tidal",
    "yandex": "yandexMusic",
    "yandexmusic": "yandexMusic",
    "yamusic": "yandexMusic",
}


def _select_preview_url(
    links: dict[str, str],
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> str | None:
    platform_order = _get_platform_order(context)
    for platform in platform_order:
        url = links.get(platform)
        if is_platform_destination_url(platform, url):
            return url

    return None


def _build_link_preview_options(
    preview_url: str | None,
    *,
    prefer_large_media: bool = False,
) -> LinkPreviewOptions:
    if not preview_url:
        return LinkPreviewOptions(is_disabled=True)

    from music_links_bot.collection_collage import is_generated_artwork_url

    # Raw generated images have no small-card title or description.
    prefer_large_media = prefer_large_media or is_generated_artwork_url(preview_url)
    media_preferences = (
        {"prefer_large_media": True}
        if prefer_large_media
        else {"prefer_small_media": True}
    )
    return LinkPreviewOptions(
        is_disabled=False,
        url=preview_url,
        show_above_text=prefer_large_media,
        **media_preferences,
    )


def _build_link_keyboard(
    links: dict[str, str],
    *,
    prefix: str = "",
    context: ContextTypes.DEFAULT_TYPE | None = None,
    include_channel_button: bool = False,
    release_page_url: str | None = None,
    release_kind: str = "song",
    release_format: str | None = None,
    platform_selection: list[str] | None = None,
    max_visible_platforms: int | None = None,
) -> InlineKeyboardMarkup:
    release_hub_url = resolve_release_hub_url(
        release_page_url,
        links,
        release_kind=release_kind,
    )
    if platform_selection is not None:
        selected_platforms = [
            platform_key
            for platform_key in platform_selection
            if platform_key in PLATFORM_LABELS
            and is_platform_destination_url(platform_key, links.get(platform_key))
        ]
    else:
        selected_platforms = []

    has_explicit_selection = platform_selection is not None
    if has_explicit_selection:
        final_platforms = selected_platforms
    else:
        platform_order = _get_platform_order(context)
        ordered_platforms = [
            platform_key
            for platform_key in platform_order
            if platform_key in PLATFORM_LABELS
            and is_platform_destination_url(platform_key, links.get(platform_key))
        ]
        remaining_platforms = [
            platform_key
            for platform_key in PLATFORM_LABELS
            if platform_key not in ordered_platforms
            and is_platform_destination_url(platform_key, links.get(platform_key))
        ]
        final_platforms = [*ordered_platforms, *remaining_platforms]

    # Song.link remains the complete hub. Callers can use a stricter limit for
    # quick chat cards while full deliveries keep the selected services.
    if max_visible_platforms is not None:
        final_platforms = final_platforms[: max(0, max_visible_platforms)]
    elif release_hub_url and not has_explicit_selection:
        final_platforms = final_platforms[:MAX_VISIBLE_PLATFORM_BUTTONS]

    buttons: list[InlineKeyboardButton] = []
    seen_urls = {cache_key_for_url(release_hub_url)} if release_hub_url else set()
    # Three services fit one row only with short names ("Apple", "YouTube").
    short = len(final_platforms) >= 3
    for platform_key in final_platforms:
        address = cache_key_for_url(links[platform_key])
        if address in seen_urls:
            continue
        seen_urls.add(address)
        buttons.append(
            _url_button(
                text=f"{prefix}{_platform_button_label(platform_key, context, short=short)}",
                url=links[platform_key],
                # Without a release hub the first provider is the main action.
                style="primary" if not buttons and not release_hub_url else None,
            )
        )
    # The universal release hub is the canonical destination, so it comes
    # first. A single provider shortcut shares its row instead of adding a
    # second full-width bar; two or three get their own row underneath.
    rows: list[list[InlineKeyboardButton]] = []
    if release_hub_url:
        hub = _url_button(
            _release_hub_button_label(release_kind, release_format, context),
            url=release_hub_url,
            # The hub is the main action and the only accented button.
            style="primary",
        )
        if len(buttons) == 1:
            return _keyboard_with_optional_channel(
                [[hub, buttons[0]]], include_channel_button
            )
        rows.append([hub])
    rows.extend(_button_rows(buttons, per_row=3 if short else 2))

    return _keyboard_with_optional_channel(rows, include_channel_button)


PLATFORM_SHORT_LABELS = {
    "appleMusic": "Apple",
    "applePodcasts": "Podcasts",
    "youtubeMusic": "YouTube",
    "yandexMusic": "Яндекс",
}


def _platform_button_label(
    platform_key: str,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    *,
    short: bool = False,
) -> str:
    label = (
        PLATFORM_SHORT_LABELS.get(platform_key, PLATFORM_LABELS[platform_key])
        if short
        else PLATFORM_LABELS[platform_key]
    )
    if _get_ui_mode(context) == "minimal":
        return label
    return f"{PLATFORM_BUTTON_ICONS[platform_key]} {label}"


def _build_collection_keyboard(
    tracks: list[TrackMatch],
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    is_track_video_pair = len(tracks) == 2 and {track.kind for track in tracks} == {
        "song",
        "video",
    }
    available: list[tuple[int, TrackMatch, str]] = []
    for index, track in enumerate(tracks, start=1):
        destination = resolve_release_hub_url(
            track.page_url,
            track.links,
            release_kind=track.kind,
        ) or _select_preview_url(track.links)
        if not destination:
            continue
        available.append((index, track, destination))

    buttons: list[InlineKeyboardButton] = []

    for index, track, destination in available:
        if is_track_video_pair:
            text = (
                _label("btn_watch_clip")
                if track.kind == "video"
                else _label("btn_listen_song")
            )
        else:
            # The post lists "Artist — Title"; the button needs only the title,
            # which keeps it short enough for two columns.
            text = _collection_label(index, compact_release_title(track.title))
        buttons.append(
            _url_button(
                text=text,
                url=destination,
                style="primary"
                if is_track_video_pair and track.kind == "song"
                else None,
            )
        )

    return _keyboard_with_optional_channel(
        _adaptive_collection_rows(buttons), include_channel_button
    )


def _build_youtube_keyboard(
    url: str,
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    return _single_url_keyboard(
        _label("btn_watch_youtube"),
        url=url,
        style="primary",
        include_channel_button=include_channel_button,
    )


def _build_title_keyboard(
    title: TitleMatch,
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    """Netflix first; the trailer and soundtrack share the second row."""
    extras = [
        _url_button(_label(key), url=url)
        for key, url in (
            ("btn_trailer", title.trailer_url),
            ("btn_soundtrack", title.soundtrack_url),
        )
        if url
    ]
    rows = [
        [_url_button(_label("btn_watch_netflix"), url=title.watch_url, style="primary")]
    ]
    return _keyboard_with_optional_channel(
        [*rows, extras] if extras else rows, include_channel_button
    )


def _build_nts_keyboard(
    url: str,
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    from music_links_bot.url_utils import is_apple_music_radio_url

    return _single_url_keyboard(
        _label("btn_listen_apple_radio")
        if is_apple_music_radio_url(url)
        else _label("btn_open_nts"),
        url=url,
        style="primary",
        include_channel_button=include_channel_button,
    )


def _build_playlist_keyboard(
    url: str,
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    return _single_url_keyboard(
        _label("btn_open_playlist"),
        url=url,
        style="primary",
        include_channel_button=include_channel_button,
    )


def _build_artist_keyboard(
    url: str,
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    return _single_url_keyboard(
        _label("btn_open_artist"),
        url=url,
        style="primary",
        include_channel_button=include_channel_button,
    )


def _item_button(
    index: int, title: str, url: str, icon: str = ""
) -> InlineKeyboardButton:
    return _url_button(text=_collection_label(index, title, icon), url=url, style=None)


def _video_button(index: int, video: VideoMatch) -> InlineKeyboardButton:
    from music_links_bot.video_kinds import video_kind_emoji

    return _item_button(
        index, _short_video_title(video.title), video.url, video_kind_emoji(video)
    )


def _items_keyboard(
    buttons: list[InlineKeyboardButton], include_channel_button: bool
) -> InlineKeyboardMarkup:
    return _keyboard_with_optional_channel(
        _adaptive_collection_rows(buttons), include_channel_button
    )


def _build_youtube_collection_keyboard(
    videos: list[VideoMatch],
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    return _items_keyboard(
        [_video_button(index, video) for index, video in enumerate(videos, start=1)],
        include_channel_button,
    )


def _build_nts_collection_keyboard(
    radios: list[RadioMatch],
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    return _items_keyboard(
        [_item_button(i, item.title, item.url) for i, item in enumerate(radios, 1)],
        include_channel_button,
    )


def _build_playlist_collection_keyboard(
    playlists: list[PlaylistMatch],
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    return _items_keyboard(
        [_item_button(i, item.title, item.url) for i, item in enumerate(playlists, 1)],
        include_channel_button,
    )


def _build_artist_collection_keyboard(
    artists: list[ArtistMatch],
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    return _items_keyboard(
        [_item_button(i, item.title, item.url) for i, item in enumerate(artists, 1)],
        include_channel_button,
    )


def _build_track_videos_keyboard(
    track: TrackMatch,
    videos: list[VideoMatch],
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    """One "listen" button, then short named clip buttons: 🎬 Клип · 🎤 Live."""
    from music_links_bot.video_kinds import video_kind_labels

    rows: list[list[InlineKeyboardButton]] = []
    destination = resolve_release_hub_url(
        track.page_url, track.links, release_kind=track.kind
    ) or _select_preview_url(track.links)
    if destination:
        rows.append(
            [
                _url_button(
                    text=_label("btn_listen_song"), url=destination, style="primary"
                )
            ]
        )
    clips = [
        _url_button(text=label, url=video.url, style=None)
        for label, video in zip(video_kind_labels(videos), videos, strict=True)
    ]
    per_row = 3 if all(len(button.text) <= 14 for button in clips) else 2
    rows.extend(clips[i : i + per_row] for i in range(0, len(clips), per_row))
    return _keyboard_with_optional_channel(rows, include_channel_button)


def _build_mixed_collection_keyboard(
    tracks: list[TrackMatch],
    videos: list[VideoMatch],
    playlists: list[PlaylistMatch] | None = None,
    artists: list[ArtistMatch] | None = None,
    radios: list[RadioMatch] | None = None,
    *,
    include_channel_button: bool = False,
) -> InlineKeyboardMarkup:
    playlists = playlists or []
    artists = artists or []
    radios = radios or []
    if len(tracks) == 1 and videos and not playlists and not artists and not radios:
        # One song with its clips has its own "listen + 🎬 Клип" layout.
        return _build_track_videos_keyboard(
            tracks[0], videos, include_channel_button=include_channel_button
        )
    buttons: list[InlineKeyboardButton] = []
    for track in tracks:
        destination = resolve_release_hub_url(
            track.page_url,
            track.links,
            release_kind=track.kind,
        ) or _select_preview_url(track.links)
        if destination:
            buttons.append(
                _item_button(
                    len(buttons) + 1, compact_release_title(track.title), destination
                )
            )
    for item in (*playlists, *artists, *radios):
        buttons.append(_item_button(len(buttons) + 1, item.title, item.url))
    buttons.extend(_video_button(len(buttons) + 1, video) for video in videos)
    return _items_keyboard(buttons, include_channel_button)


def _should_include_channel_button(message: Message) -> bool:
    del message
    return False


def _should_include_hashtags(message: Message) -> bool:
    del message
    return True


def _build_platform_order(primary_platform: str | None) -> tuple[str, ...]:
    if not primary_platform:
        return DEFAULT_PLATFORM_ORDER

    normalized = _normalize_platform_key(primary_platform)
    if normalized is None:
        return DEFAULT_PLATFORM_ORDER

    return (
        normalized,
        *(item for item in DEFAULT_PLATFORM_ORDER if item != normalized),
    )


def _normalize_platform_key(platform: str) -> str | None:
    raw_value = platform.strip()
    if raw_value in DEFAULT_PLATFORM_ORDER:
        return raw_value

    compact_value = (
        raw_value.replace("-", "").replace("_", "").replace(" ", "").casefold()
    )
    return PRIMARY_PLATFORM_ALIASES.get(compact_value)


def _label(key: str) -> str:
    """A post button label in the reader's interface language."""
    return get_text(resolve_lang(None), key)


MAX_COLLECTION_BUTTON_TITLE = 16
_VIDEO_TITLE_NOISE = re.compile(
    r"\s*[(\[][^)\]]*\b(?:official|video|клип|audio|lyrics?|visuali[sz]er|mv|m/v)\b"
    r"[^)\]]*[)\]]",
    re.IGNORECASE,
)
# Characters that only make sense attached to what follows or precedes them.
_DANGLING = "\u200d\ufe0f\ufe0e\u20e3"


def _short_video_title(title: str) -> str:
    """ "ПОЕХАЛИ – Зарплата / POEXXXALI – Payday" → "Зарплата".

    A YouTube title repeats the artist (and sometimes a translation) that the
    post list already shows; the button keeps just the song.
    """
    first = title.split(" / ", 1)[0]
    parts = re.split(r"\s+[–—-]\s+", first, maxsplit=1)
    name = parts[1] if len(parts) == 2 and parts[1].strip() else first
    return _VIDEO_TITLE_NOISE.sub("", name).strip() or first.strip()


def _collection_label(index: int, title: str, icon: str = "") -> str:
    """ "3 · Зарплата": short enough for two buttons per row.

    The post list carries the full title, so long names end in "…".
    """
    name = " ".join(str(title or "").split())
    if len(name) > MAX_COLLECTION_BUTTON_TITLE:
        cut = name[:MAX_COLLECTION_BUTTON_TITLE]
        # Never end on half an emoji sequence or a lone accent.
        while cut and (
            cut[-1] in _DANGLING or unicodedata.category(cut[-1]) in {"Mn", "Me"}
        ):
            cut = cut[:-1]
        name = cut.rstrip(" -–—·,.:") + "…"
    label = f"{index} · {name}"
    return f"{icon} {label}" if icon else label


def _button_label(text: str) -> str:
    """Preserve the complete name; use row layout, not destructive truncation."""
    return " ".join(text.split())


_NUMBERED_LABEL = re.compile(r"^(?:(?P<icon>\S+) )?(?P<number>\d{1,2}) · ")
KEYPAD_ROW_SIZE = 5


def _number_keypad(
    buttons: list[InlineKeyboardButton],
) -> list[list[TelegramInlineKeyboardButton]] | None:
    """Collections list their titles in the post, so buttons show only numbers.

    1–5 items fit one row; 6–10 split into two even rows ("4 + 4", "5 + 5").
    Video items keep their kind icon ("🎬 3"). Returns None when a button is
    not a numbered item, e.g. the song + clip pair.
    """
    keys: list[TelegramInlineKeyboardButton] = []
    for button in buttons:
        match = _NUMBERED_LABEL.match(button.text)
        if match is None:
            return None
        icon = match.group("icon")
        label = f"{icon} {match.group('number')}" if icon else match.group("number")
        keys.append(
            TelegramInlineKeyboardButton.de_json(
                {**button.to_dict(), "text": label}, None
            )
        )
    if not keys:
        return None
    row_count = -(-len(keys) // KEYPAD_ROW_SIZE)
    per_row = -(-len(keys) // row_count)
    return [keys[i : i + per_row] for i in range(0, len(keys), per_row)]


def _adaptive_collection_rows(
    buttons: list[InlineKeyboardButton],
    *,
    layout: str | None = None,
) -> list[list[InlineKeyboardButton]]:
    layout = layout or current_presentation.get().layout
    if layout == "numbers":
        keypad = _number_keypad(buttons)
        if keypad:
            return keypad
    if layout == "column":
        return [[button] for button in buttons]
    rows: list[list[InlineKeyboardButton]] = []
    pending: InlineKeyboardButton | None = None
    for button in buttons:
        if len(button.text) <= MAX_TWO_COLUMN_BUTTON_TEXT_LENGTH:
            if pending is None:
                pending = button
            else:
                rows.append([pending, button])
                pending = None
            continue
        if pending is not None:
            rows.append([pending])
            pending = None
        rows.append([button])
    if pending is not None:
        rows.append([pending])
    return rows


def _release_hub_button_label(
    release_kind: str,
    release_format: str | None,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> str:
    lang = resolve_lang(None)
    icon = "🎧"
    label = get_text(lang, "button_listen_track")
    if release_kind == "album":
        icon = "💿"
        label = get_text(lang, "button_listen_album")
        if release_format == "ep":
            label = get_text(lang, "button_listen_ep")
        elif release_format == "single":
            label = get_text(lang, "button_listen_single")
        elif release_format == "compilation":
            label = get_text(lang, "button_listen_compilation")
        elif release_format == "soundtrack":
            label = get_text(lang, "button_listen_soundtrack")
    elif release_kind == "podcast":
        icon = "🎙️"
        label = get_text(lang, "button_listen_podcast")
    elif release_kind == "video":
        icon = "📺"
        label = get_text(lang, "button_watch_video")
    return label if _get_ui_mode(context) == "minimal" else f"{icon} {label}"


def _get_ui_mode(context: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    if context is None:
        return DEFAULT_UI_MODE

    value = context.application.bot_data.get("ui_mode", DEFAULT_UI_MODE)
    return value if value in {"stonerhand", "minimal", "editorial"} else DEFAULT_UI_MODE


def _button_rows(
    buttons: list[InlineKeyboardButton], *, per_row: int = 2
) -> list[list[InlineKeyboardButton]]:
    return [
        buttons[index : index + per_row] for index in range(0, len(buttons), per_row)
    ]


def _keyboard_with_optional_channel(
    rows: list[list[InlineKeyboardButton]],
    include_channel_button: bool,
) -> InlineKeyboardMarkup:
    keyboard_rows = [*rows]
    if include_channel_button:
        keyboard_rows.append([_channel_button()])

    return InlineKeyboardMarkup(keyboard_rows)


def _single_url_keyboard(
    text: str,
    *,
    url: str,
    style: str | None,
    include_channel_button: bool,
) -> InlineKeyboardMarkup:
    return _keyboard_with_optional_channel(
        [[_url_button(text, url=url, style=style)]],
        include_channel_button,
    )


def _channel_button() -> InlineKeyboardButton:
    return _url_button(CHANNEL_BUTTON_TEXT, url=CHANNEL_URL)


def _url_button(text: str, url: str, style: str | None = None) -> InlineKeyboardButton:
    tone = ButtonTone(style) if style else None
    return url_button(text=text, url=url, tone=tone)


def _get_platform_order(context: ContextTypes.DEFAULT_TYPE | None) -> tuple[str, ...]:
    if context is None:
        return DEFAULT_PLATFORM_ORDER

    platform_order = context.application.bot_data.get("platform_order")
    if isinstance(platform_order, tuple):
        return platform_order

    return DEFAULT_PLATFORM_ORDER
