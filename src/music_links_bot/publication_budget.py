from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape

from music_links_bot.bot_builder import (
    MESSAGE_TEXT_LIMIT,
    PHOTO_CAPTION_LIMIT,
    fit_telegram_html,
)
from music_links_bot.telegram_text import telegram_text_length

INTRO_HARD_LIMIT = 3_000
_BLOCKQUOTE_OPEN = "<blockquote>"
_BLOCKQUOTE_CLOSE = "</blockquote>"
_BLOCKQUOTE_SUFFIX = f"{_BLOCKQUOTE_CLOSE}\n\n"
_TAG_RE = re.compile(r"<[^>]*>")


@dataclass(frozen=True, slots=True)
class IntroBudget:
    limit: int
    used: int
    truncated: bool = False


def publication_limit(draft: dict) -> int:
    return PHOTO_CAPTION_LIMIT if draft.get("as_photo") else MESSAGE_TEXT_LIMIT


def visible_length(value: str) -> int:
    return telegram_text_length(unescape(_TAG_RE.sub("", str(value or ""))))


def intro_limit_for_body(draft: dict, body_html: str) -> int:
    """Return the safe visible intro budget for this exact publication.

    Telegram applies a much smaller limit to photo captions than to regular
    messages. Keep a small markup reserve so an intro can never crowd the
    release title or hashtags out of the finished post.
    """
    total = publication_limit(draft)
    # Telegram counts visible characters after parsing entities, not the HTML
    # tag source. Reserve only the two line breaks between intro and card.
    available = total - visible_length(body_html) - 2
    return max(0, min(INTRO_HARD_LIMIT, available))


def compose_with_intro(
    draft: dict,
    *,
    prefix_html: str,
    body_html: str,
) -> tuple[str, IntroBudget]:
    if not prefix_html or not draft.get("quote"):
        return body_html, IntroBudget(
            limit=intro_limit_for_body(draft, body_html),
            used=0,
        )

    limit = intro_limit_for_body(draft, body_html)
    used = visible_length(prefix_html)
    if used <= limit:
        return prefix_html + body_html, IntroBudget(limit=limit, used=used)

    inner = _blockquote_inner(prefix_html)
    if limit <= 0:
        return body_html, IntroBudget(limit=0, used=used, truncated=bool(used))
    fitted = fit_telegram_html(inner, limit)
    prefix = f"{_BLOCKQUOTE_OPEN}{fitted}{_BLOCKQUOTE_SUFFIX}"
    return prefix + body_html, IntroBudget(
        limit=limit,
        used=used,
        truncated=True,
    )


def _blockquote_inner(prefix_html: str) -> str:
    value = str(prefix_html or "").strip()
    if value.startswith(_BLOCKQUOTE_OPEN) and value.endswith(_BLOCKQUOTE_CLOSE):
        return value[len(_BLOCKQUOTE_OPEN) : -len(_BLOCKQUOTE_CLOSE)]
    return value
