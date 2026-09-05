from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from telegram import InlineKeyboardMarkup

from music_links_bot.bot_builder import MESSAGE_TEXT_LIMIT, PHOTO_CAPTION_LIMIT
from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.publication_budget import visible_length
from music_links_bot.release_hubs import is_universal_release_url
from music_links_bot.url_utils import (
    extract_supported_urls,
    is_direct_platform_url,
    is_platform_destination_url,
)

MAX_INLINE_BUTTONS = 100
MAX_INLINE_BUTTONS_PER_ROW = 8
MAX_CALLBACK_DATA_BYTES = 64
MAX_INLINE_QUERY_LENGTH = 256
_CAPTION_MODES = frozenset({"audio", "photo"})
_UNIVERSAL_LABEL_MARKERS = (
    "all platforms",
    "all services",
    "all stores",
    "все площадки",
    "все платформы",
    "весь релиз",
    "слушать целиком",
    "открыть все",
    "открыть выпуск",
)


@dataclass(frozen=True, slots=True)
class RenderedPublication:
    """A transport-neutral contract for every finished Telegram post.

    Producers may render Classic, Rich, inline, channel, photo, or audio
    output differently, but the user-visible text, destinations, counts, and
    artwork guarantees are checked through this one model before delivery.
    """

    text: str
    keyboard: InlineKeyboardMarkup | None = None
    preview_url: str | None = None
    cover_url: str | None = None
    source_urls: tuple[str, ...] = ()
    found_count: int = 1
    requested_count: int = 1
    mode: str = "classic"
    content_kind: str = "track"
    cover_expected: bool = False

    @property
    def text_limit(self) -> int:
        return (
            PHOTO_CAPTION_LIMIT if self.mode in _CAPTION_MODES else MESSAGE_TEXT_LIMIT
        )


@dataclass(frozen=True, slots=True)
class ContractIssue:
    code: str
    detail: str = ""
    blocking: bool = True


@dataclass(frozen=True, slots=True)
class ContractResult:
    issues: tuple[ContractIssue, ...]

    @property
    def ready(self) -> bool:
        return not any(issue.blocking for issue in self.issues)

    @property
    def blocking_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues if issue.blocking)


class PublicationContractError(ValueError):
    def __init__(self, result: ContractResult) -> None:
        self.result = result
        super().__init__(
            "Invalid rendered publication: " + ", ".join(result.blocking_codes)
        )


def validate_rendered_publication(
    publication: RenderedPublication,
) -> ContractResult:
    issues: list[ContractIssue] = []
    text = str(publication.text or "")
    if not text.strip():
        issues.append(ContractIssue("empty_text"))
    elif visible_length(text) > publication.text_limit:
        issues.append(
            ContractIssue(
                "text_limit",
                f"{visible_length(text)}>{publication.text_limit}",
            )
        )

    leaked_urls = extract_supported_urls(text)
    if leaked_urls:
        issues.append(
            ContractIssue(
                "visible_source_url",
                ", ".join(leaked_urls[:3]),
            )
        )

    found = publication.found_count
    requested = publication.requested_count
    if found < 1 or requested < found:
        issues.append(ContractIssue("invalid_item_count", f"{found}/{requested}"))
    elif requested > found:
        normalized = text.casefold()
        exact_count = f"{found} из {requested}"
        english_count = f"{found} of {requested}"
        if exact_count not in normalized and english_count not in normalized:
            issues.append(
                ContractIssue("missing_partial_count", f"{found}/{requested}")
            )

    if publication.cover_expected and not (
        publication.cover_url or publication.preview_url
    ):
        issues.append(ContractIssue("missing_artwork"))

    if publication.preview_url and not _safe_http_url(publication.preview_url):
        issues.append(ContractIssue("unsafe_media_url", "preview_url"))
    # A cover may also be a Telegram file_id. Validate only actual URL-shaped
    # references and leave opaque Telegram media identifiers intact.
    if (
        publication.cover_url
        and "://" in publication.cover_url
        and not _safe_http_url(publication.cover_url)
    ):
        issues.append(ContractIssue("unsafe_media_url", "cover_url"))

    issues.extend(
        ContractIssue("invalid_source_url", source_url[:120])
        for source_url in publication.source_urls
        if not is_direct_platform_url(source_url)
    )

    issues.extend(_keyboard_issues(publication.keyboard))
    return ContractResult(tuple(issues))


def require_valid_publication(
    publication: RenderedPublication,
) -> RenderedPublication:
    result = validate_rendered_publication(publication)
    if not result.ready:
        raise PublicationContractError(result)
    return publication


def _keyboard_issues(
    keyboard: InlineKeyboardMarkup | None,
) -> list[ContractIssue]:
    if keyboard is None:
        return []

    issues: list[ContractIssue] = []
    rows = keyboard.inline_keyboard
    button_count = sum(len(row) for row in rows)
    if button_count > MAX_INLINE_BUTTONS:
        issues.append(ContractIssue("too_many_buttons", str(button_count)))

    for row_index, row in enumerate(rows):
        if len(row) > MAX_INLINE_BUTTONS_PER_ROW:
            issues.append(ContractIssue("too_many_buttons_in_row", str(row_index)))
        for button_index, button in enumerate(row):
            location = f"{row_index}:{button_index}"
            label = str(button.text or "")
            if not label.strip():
                issues.append(ContractIssue("invalid_button_text", location))

            callback_data = getattr(button, "callback_data", None)
            if callback_data is not None and not (
                1 <= len(str(callback_data).encode("utf-8")) <= MAX_CALLBACK_DATA_BYTES
            ):
                issues.append(ContractIssue("invalid_callback_data", location))

            for field in (
                "switch_inline_query",
                "switch_inline_query_current_chat",
                "switch_inline_query_chosen_chat",
            ):
                query = getattr(button, field, None)
                if query is None:
                    continue
                query_text = str(query)
                if len(query_text) > MAX_INLINE_QUERY_LENGTH:
                    issues.append(ContractIssue("invalid_inline_query", location))
                if len(extract_supported_urls(query_text)) > 1:
                    issues.append(
                        ContractIssue("raw_collection_inline_query", location)
                    )

            url = getattr(button, "url", None)
            if url:
                if not _safe_http_url(url):
                    issues.append(ContractIssue("invalid_button_url", location))
                elif _is_universal_label(label) and not is_universal_release_url(url):
                    issues.append(ContractIssue("universal_button_mismatch", location))
                else:
                    platform_key = _platform_key_for_label(label)
                    if platform_key and not is_platform_destination_url(
                        platform_key, url
                    ):
                        issues.append(
                            ContractIssue("platform_button_mismatch", location)
                        )
    return issues


def _safe_http_url(value: str) -> bool:
    if not is_direct_platform_url(value):
        return False
    try:
        return urlparse(str(value)).scheme == "https"
    except ValueError:
        return False


def _is_universal_label(label: str) -> bool:
    normalized = " ".join(label.casefold().split())
    return any(marker in normalized for marker in _UNIVERSAL_LABEL_MARKERS)


def _platform_key_for_label(label: str) -> str | None:
    normalized = " ".join(label.casefold().split())
    for platform_key, platform_label in PLATFORM_LABELS.items():
        provider_name = platform_label.split(maxsplit=1)[-1].casefold()
        if normalized in {platform_label.casefold(), provider_name}:
            return platform_key
    return None
