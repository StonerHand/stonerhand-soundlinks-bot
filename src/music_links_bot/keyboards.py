from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message
from telegram.ext import ContextTypes

from music_links_bot.constants import PLATFORM_BUTTON_STYLES, PLATFORM_LABELS
from music_links_bot.models import ArtistMatch, PlaylistMatch, RadioMatch, TrackMatch, VideoMatch

CHANNEL_USERNAME = "stonerhand"
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"
CHANNEL_BUTTON_TEXT = "🪨 Открыть канал"
DEFAULT_UI_MODE = "stonerhand"
MAX_BUTTON_TEXT_LENGTH = 64
SPOTIFY_SEARCH_URL = "https://open.spotify.com/search/"
DEFAULT_PLATFORM_ORDER = (
    "spotify", "appleMusic", "applePodcasts", "youtubeMusic",
    "soundcloud", "deezer", "tidal", "yandexMusic",
)
PRIMARY_PLATFORM_ALIASES = {
    "spotify": "spotify", "apple": "appleMusic", "applemusic": "appleMusic",
    "itunes": "appleMusic", "applepodcasts": "applePodcasts", "podcasts": "applePodcasts",
    "youtube": "youtubeMusic", "youtubemusic": "youtubeMusic", "ytmusic": "youtubeMusic",
    "soundcloud": "soundcloud", "sc": "soundcloud", "deezer": "deezer", "tidal": "tidal",
    "yandex": "yandexMusic", "yandexmusic": "yandexMusic", "yamusic": "yandexMusic",
}

def _select_preview_url(
    links: dict[str, str],
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> str | None:
    platform_order = _get_platform_order(context)
    for platform in platform_order:
        url = links.get(platform)
        if url and not url.startswith(SPOTIFY_SEARCH_URL):
            return url

    return None



def _build_link_preview_options(
    preview_url: str | None,
    *,
    prefer_large_media: bool = False,
) -> LinkPreviewOptions:
    if not preview_url:
        return LinkPreviewOptions(is_disabled=True)

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
    include_channel_button: bool = True,
    release_page_url: str | None = None,
    release_kind: str = "song",
    release_format: str | None = None,
    platform_selection: list[str] | None = None,
) -> InlineKeyboardMarkup:
    if platform_selection is not None:
        selected_platforms = [
            platform_key
            for platform_key in platform_selection
            if links.get(platform_key) and platform_key in PLATFORM_LABELS
        ]
    else:
        selected_platforms = []

    if selected_platforms:
        final_platforms = selected_platforms
    else:
        platform_order = _get_platform_order(context)
        ordered_platforms = [
            platform_key
            for platform_key in platform_order
            if links.get(platform_key) and platform_key in PLATFORM_LABELS
        ]
        remaining_platforms = [
            platform_key
            for platform_key in PLATFORM_LABELS
            if platform_key not in ordered_platforms and links.get(platform_key)
        ]
        final_platforms = [*ordered_platforms, *remaining_platforms]

    buttons = [
        _url_button(
            text=f"{prefix}{_platform_button_label(platform_key, context)}",
            url=links[platform_key],
            style=PLATFORM_BUTTON_STYLES.get(platform_key),
        )
        for platform_key in final_platforms
    ]
    rows = _button_rows(buttons)
    if release_page_url:
        rows.append(
            [
                _url_button(
                    _release_hub_button_label(release_kind, release_format, context),
                    url=release_page_url,
                    style="danger",
                )
            ]
        )

    return _keyboard_with_optional_channel(rows, include_channel_button)


def _platform_button_label(
    platform_key: str,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> str:
    label = PLATFORM_LABELS[platform_key]
    if _get_ui_mode(context) != "minimal":
        return label

    parts = label.split(maxsplit=1)
    return parts[1] if len(parts) == 2 else label


def _build_collection_keyboard(
    tracks: list[TrackMatch],
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []

    for index, track in enumerate(tracks, start=1):
        destination = track.page_url or _select_preview_url(track.links)
        if not destination:
            continue

        buttons.append(
            _url_button(
                text=_shorten_button_text(
                    f"{_track_button_icon(track)} {index}. {track.artist} - {track.title}"
                ),
                url=destination,
                style="primary",
            )
        )

    return _keyboard_with_optional_channel(_button_rows(buttons), include_channel_button)


def _build_youtube_keyboard(
    url: str,
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    return _single_url_keyboard(
        "📺 Смотреть на YouTube",
        url=url,
        style="danger",
        include_channel_button=include_channel_button,
    )


def _build_nts_keyboard(
    url: str,
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    return _single_url_keyboard(
        "📡 Открыть на NTS",
        url=url,
        style="primary",
        include_channel_button=include_channel_button,
    )


def _build_playlist_keyboard(
    url: str,
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    return _single_url_keyboard(
        "🎛 Открыть плейлист",
        url=url,
        style="primary",
        include_channel_button=include_channel_button,
    )


def _build_artist_keyboard(
    url: str,
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    return _single_url_keyboard(
        "🧬 Открыть артиста",
        url=url,
        style="primary",
        include_channel_button=include_channel_button,
    )


def _build_youtube_collection_keyboard(
    videos: list[VideoMatch],
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for index, video in enumerate(videos, start=1):
        buttons.append(
            _url_button(
                text=_shorten_button_text(f"📺 {index}. {video.title}"),
                url=video.url,
                style="danger",
            )
        )

    return _keyboard_with_optional_channel(_button_rows(buttons), include_channel_button)


def _build_nts_collection_keyboard(
    radios: list[RadioMatch],
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for index, radio in enumerate(radios, start=1):
        buttons.append(
            _url_button(
                text=_shorten_button_text(f"📡 {index}. {radio.title}"),
                url=radio.url,
                style="primary",
            )
        )

    return _keyboard_with_optional_channel(_button_rows(buttons), include_channel_button)


def _build_playlist_collection_keyboard(
    playlists: list[PlaylistMatch],
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for index, playlist in enumerate(playlists, start=1):
        buttons.append(
            _url_button(
                text=_shorten_button_text(f"🎛 {index}. {playlist.title}"),
                url=playlist.url,
                style="primary",
            )
        )

    return _keyboard_with_optional_channel(_button_rows(buttons), include_channel_button)


def _build_artist_collection_keyboard(
    artists: list[ArtistMatch],
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for index, artist in enumerate(artists, start=1):
        buttons.append(
            _url_button(
                text=_shorten_button_text(f"🧬 {index}. {artist.title}"),
                url=artist.url,
                style="primary",
            )
        )

    return _keyboard_with_optional_channel(_button_rows(buttons), include_channel_button)


def _build_mixed_collection_keyboard(
    tracks: list[TrackMatch],
    videos: list[VideoMatch],
    playlists: list[PlaylistMatch] | None = None,
    artists: list[ArtistMatch] | None = None,
    radios: list[RadioMatch] | None = None,
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    playlists = playlists or []
    artists = artists or []
    radios = radios or []
    buttons: list[InlineKeyboardButton] = []
    index = 1

    for track in tracks:
        destination = track.page_url or _select_preview_url(track.links)
        if not destination:
            continue

        buttons.append(
            _url_button(
                text=_shorten_button_text(
                    f"{_track_button_icon(track)} {index}. {track.artist} - {track.title}"
                ),
                url=destination,
                style="primary",
            )
        )
        index += 1

    for playlist in playlists:
        buttons.append(
            _url_button(
                text=_shorten_button_text(f"🎛 {index}. {playlist.title}"),
                url=playlist.url,
                style="primary",
            )
        )
        index += 1

    for artist in artists:
        buttons.append(
            _url_button(
                text=_shorten_button_text(f"🧬 {index}. {artist.title}"),
                url=artist.url,
                style="primary",
            )
        )
        index += 1

    for radio in radios:
        buttons.append(
            _url_button(
                text=_shorten_button_text(f"📡 {index}. {radio.title}"),
                url=radio.url,
                style="primary",
            )
        )
        index += 1

    for video in videos:
        buttons.append(
            _url_button(
                text=_shorten_button_text(f"📺 {index}. {video.title}"),
                url=video.url,
                style="danger",
            )
        )
        index += 1

    return _keyboard_with_optional_channel(_button_rows(buttons), include_channel_button)


def _should_include_channel_button(message: Message) -> bool:
    username = message.chat.username
    return not (
        message.chat.type == "channel"
        and username is not None
        and username.casefold() == CHANNEL_USERNAME
    )


def _should_include_hashtags(message: Message) -> bool:
    return message.chat.type != "private"


def _build_platform_order(primary_platform: str | None) -> tuple[str, ...]:
    if not primary_platform:
        return DEFAULT_PLATFORM_ORDER

    normalized = _normalize_platform_key(primary_platform)
    if normalized is None:
        return DEFAULT_PLATFORM_ORDER

    return (normalized, *(item for item in DEFAULT_PLATFORM_ORDER if item != normalized))


def _normalize_platform_key(platform: str) -> str | None:
    raw_value = platform.strip()
    if raw_value in DEFAULT_PLATFORM_ORDER:
        return raw_value

    compact_value = (
        raw_value.replace("-", "")
        .replace("_", "")
        .replace(" ", "")
        .casefold()
    )
    return PRIMARY_PLATFORM_ALIASES.get(compact_value)


def _shorten_button_text(text: str) -> str:
    if len(text) <= MAX_BUTTON_TEXT_LENGTH:
        return text

    return text[: MAX_BUTTON_TEXT_LENGTH - 1].rstrip() + "…"


def _track_button_icon(track: TrackMatch) -> str:
    if track.kind == "album":
        return "💿"

    if track.kind == "podcast":
        return "🎙️"

    return "🎧"


def _release_hub_button_label(
    release_kind: str,
    release_format: str | None,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> str:
    ui_mode = _get_ui_mode(context)

    if ui_mode == "minimal":
        if release_kind == "album":
            return "Весь EP" if release_format == "ep" else "Весь релиз"

        if release_kind == "podcast":
            return "Все площадки"

        return "Все платформы"

    if ui_mode == "editorial":
        if release_kind == "album":
            return "💿 слушать EP" if release_format == "ep" else "💿 слушать целиком"

        if release_kind == "podcast":
            return "🎙 открыть выпуск"

        return "🪩 открыть все"

    if release_kind == "album":
        if release_format == "ep":
            return "💿 Весь EP"

        return "💿 Весь релиз"

    if release_kind == "podcast":
        return "🎙 Все площадки"

    return "🪩 Все платформы"


def _get_ui_mode(context: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    if context is None:
        return DEFAULT_UI_MODE

    value = context.application.bot_data.get("ui_mode", DEFAULT_UI_MODE)
    return value if value in {"stonerhand", "minimal", "editorial"} else DEFAULT_UI_MODE


def _button_rows(buttons: list[InlineKeyboardButton]) -> list[list[InlineKeyboardButton]]:
    return [buttons[index : index + 2] for index in range(0, len(buttons), 2)]


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
    style: str,
    include_channel_button: bool,
) -> InlineKeyboardMarkup:
    return _keyboard_with_optional_channel(
        [[_url_button(text, url=url, style=style)]],
        include_channel_button,
    )


def _channel_button() -> InlineKeyboardButton:
    return _url_button(CHANNEL_BUTTON_TEXT, url=CHANNEL_URL, style="primary")


def _url_button(text: str, url: str, style: str | None = None) -> InlineKeyboardButton:
    # Keep compatibility while python-telegram-bot catches up with newer Bot API fields.
    api_kwargs = {"style": style} if style else None
    return InlineKeyboardButton(text=text, url=url, api_kwargs=api_kwargs)


def _get_platform_order(context: ContextTypes.DEFAULT_TYPE | None) -> tuple[str, ...]:
    if context is None:
        return DEFAULT_PLATFORM_ORDER

    platform_order = context.application.bot_data.get("platform_order")
    if isinstance(platform_order, tuple):
        return platform_order

    return DEFAULT_PLATFORM_ORDER
