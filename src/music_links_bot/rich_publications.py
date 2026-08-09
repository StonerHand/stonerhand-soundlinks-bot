from __future__ import annotations

import html
import logging
import re
from typing import Any

from telegram import Message
from telegram.error import BadRequest, TelegramError

from music_links_bot.models import TrackMatch

LOGGER = logging.getLogger(__name__)

LONGREAD_MODE = "longread"

MAX_LONGREAD_TITLE = 140
MAX_LONGREAD_LEAD = 420
MAX_LONGREAD_BLOCKS = 24
MAX_BLOCK_TEXT = 1800
MAX_DETAILS_TITLE = 120
MAX_LIST_ITEMS = 16
MAX_LIST_ITEM = 320
MAX_LONGREAD_TEXT = 22_000
MAX_RICH_HTML = 30_000
MAX_FALLBACK_TEXT = 3_800

BLOCK_TYPES = frozenset(
    {"paragraph", "heading", "quote", "list", "details", "divider"}
)
_BLOCK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def is_longread(draft: dict) -> bool:
    return draft.get("publication_mode") == LONGREAD_MODE


def _clean_text(value: object, limit: int, *, multiline: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    if multiline:
        lines = [" ".join(line.split()) for line in value.splitlines()]
        cleaned = "\n".join(line for line in lines if line).strip()
    else:
        cleaned = " ".join(value.split()).strip()
    return cleaned[:limit]


def default_longread(
    track: TrackMatch,
    *,
    lang: str = "ru",
) -> dict:
    title = f"{track.artist} — {track.title}".strip(" —")
    del lang
    return {
        "title": title[:MAX_LONGREAD_TITLE],
        "lead": "",
        "blocks": [],
    }


def sanitize_longread(
    value: object,
    track: TrackMatch,
    *,
    lang: str = "ru",
) -> dict:
    fallback = default_longread(track, lang=lang)
    if not isinstance(value, dict):
        return fallback

    title = _clean_text(value.get("title"), MAX_LONGREAD_TITLE) or fallback["title"]
    lead = _clean_text(value.get("lead"), MAX_LONGREAD_LEAD, multiline=True)
    raw_blocks = value.get("blocks")
    blocks: list[dict] = []
    text_budget = MAX_LONGREAD_TEXT - len(title) - len(lead)

    def budgeted(value: object, limit: int, *, multiline: bool = False) -> str:
        nonlocal text_budget
        if text_budget <= 0:
            return ""
        cleaned = _clean_text(
            value,
            min(limit, text_budget),
            multiline=multiline,
        )
        text_budget -= len(cleaned)
        return cleaned

    if isinstance(raw_blocks, list):
        for index, raw in enumerate(raw_blocks[:MAX_LONGREAD_BLOCKS]):
            if text_budget <= 0:
                break
            if not isinstance(raw, dict):
                continue
            block_type = str(raw.get("type") or "")
            if block_type not in BLOCK_TYPES:
                continue
            block_id = str(raw.get("id") or f"block-{index + 1}")
            if not _BLOCK_ID_RE.fullmatch(block_id):
                block_id = f"block-{index + 1}"

            if block_type == "divider":
                blocks.append({"id": block_id, "type": block_type})
                continue
            if block_type == "list":
                raw_items = raw.get("items")
                items = []
                for entry in (
                    raw_items[:MAX_LIST_ITEMS]
                    if isinstance(raw_items, list)
                    else []
                ):
                    item = budgeted(entry, MAX_LIST_ITEM)
                    if item:
                        items.append(item)
                    if text_budget <= 0:
                        break
                if items:
                    blocks.append(
                        {
                            "id": block_id,
                            "type": block_type,
                            "items": items,
                            "ordered": bool(raw.get("ordered")),
                        }
                    )
                continue
            if block_type == "details":
                summary = budgeted(raw.get("title"), MAX_DETAILS_TITLE)
                text = budgeted(
                    raw.get("text"),
                    MAX_BLOCK_TEXT,
                    multiline=True,
                )
                if summary and text:
                    blocks.append(
                        {
                            "id": block_id,
                            "type": block_type,
                            "title": summary,
                            "text": text,
                            "open": bool(raw.get("open")),
                        }
                    )
                continue

            text = budgeted(
                raw.get("text"),
                MAX_BLOCK_TEXT,
                multiline=True,
            )
            if text:
                blocks.append(
                    {
                        "id": block_id,
                        "type": block_type,
                        "text": text,
                    }
                )

    return {"title": title, "lead": lead, "blocks": blocks}


def _lines(text: str) -> str:
    return "<br>".join(html.escape(line) for line in text.splitlines())


def build_rich_html(
    draft: dict,
    track: TrackMatch,
    *,
    hashtags: str | None,
) -> str:
    data = sanitize_longread(
        draft.get("longread"),
        track,
        lang=draft.get("lang") or "ru",
    )
    pieces = [f"<h1>{html.escape(data['title'])}</h1>"]
    if data["lead"]:
        pieces.append(f"<p><i>{_lines(data['lead'])}</i></p>")
    if track.thumbnail_url:
        pieces.append(
            "<figure>"
            f'<img src="{html.escape(track.thumbnail_url, quote=True)}"/>'
            f"<figcaption>{html.escape(track.artist)} — "
            f"{html.escape(track.title)}</figcaption>"
            "</figure>"
        )

    for block in data["blocks"]:
        block_type = block["type"]
        if block_type == "divider":
            pieces.append("<hr/>")
        elif block_type == "heading":
            pieces.append(f"<h2>{_lines(block['text'])}</h2>")
        elif block_type == "paragraph":
            pieces.append(f"<p>{_lines(block['text'])}</p>")
        elif block_type == "quote":
            pieces.append(f"<blockquote>{_lines(block['text'])}</blockquote>")
        elif block_type == "list":
            tag = "ol" if block.get("ordered") else "ul"
            items = "".join(f"<li>{html.escape(item)}</li>" for item in block["items"])
            pieces.append(f"<{tag}>{items}</{tag}>")
        elif block_type == "details":
            opened = " open" if block.get("open") else ""
            pieces.append(
                f"<details{opened}><summary>{html.escape(block['title'])}</summary>"
                f"<p>{_lines(block['text'])}</p></details>"
            )

    if hashtags:
        pieces.append(f"<footer>{html.escape(hashtags)}</footer>")
    rich_html = "\n".join(pieces)
    if len(rich_html) > MAX_RICH_HTML:
        continuation = "<p><i>…</i></p>"
        selected: list[str] = []
        for piece in pieces:
            candidate = "\n".join([*selected, piece, continuation])
            if len(candidate) > MAX_RICH_HTML:
                break
            selected.append(piece)
        rich_html = "\n".join([*selected, continuation])
    return rich_html


def build_fallback_html(
    draft: dict,
    track: TrackMatch,
    *,
    hashtags: str | None,
) -> str:
    """Render the longread with the formatting supported by older clients.

    Every piece is complete HTML, so truncation never leaves an unclosed tag.
    """
    data = sanitize_longread(
        draft.get("longread"),
        track,
        lang=draft.get("lang") or "ru",
    )
    pieces = [f"<b>{html.escape(data['title'])}</b>"]
    if data["lead"]:
        pieces.append(f"<i>{_lines(data['lead'])}</i>")
    for block in data["blocks"]:
        block_type = block["type"]
        if block_type == "divider":
            pieces.append("—")
        elif block_type == "heading":
            pieces.append(f"<b>{_lines(block['text'])}</b>")
        elif block_type == "quote":
            pieces.append(f"<blockquote>{_lines(block['text'])}</blockquote>")
        elif block_type == "list":
            marker = "1." if block.get("ordered") else "•"
            pieces.append(
                "\n".join(
                    f"{index + 1}. {html.escape(item)}"
                    if marker == "1."
                    else f"• {html.escape(item)}"
                    for index, item in enumerate(block["items"])
                )
            )
        elif block_type == "details":
            pieces.append(
                f"<b>{html.escape(block['title'])}</b>\n{_lines(block['text'])}"
            )
        else:
            pieces.append(_lines(block["text"]))
    if hashtags:
        pieces.append(html.escape(hashtags))

    selected: list[str] = []
    used = 0
    for piece in pieces:
        extra = len(piece) + (2 if selected else 0)
        if used + extra > MAX_FALLBACK_TEXT:
            break
        selected.append(piece)
        used += extra
    if len(selected) < len(pieces):
        continuation = "<i>…продолжение доступно в полной версии Telegram</i>"
        while selected and len("\n\n".join([*selected, continuation])) > MAX_FALLBACK_TEXT:
            selected.pop()
        if len(continuation) <= MAX_FALLBACK_TEXT:
            selected.append(continuation)
    return "\n\n".join(selected)


def _serialize_reply_markup(reply_markup: object) -> object:
    to_dict = getattr(reply_markup, "to_dict", None)
    return to_dict() if callable(to_dict) else reply_markup


async def send_rich_publication(
    bot,
    *,
    chat_id: int | str,
    rich_html: str,
    reply_markup,
) -> Message | bool:
    result = await bot._post(
        "sendRichMessage",
        data={
            "chat_id": chat_id,
            "rich_message": {"html": rich_html},
            "reply_markup": _serialize_reply_markup(reply_markup),
        },
    )
    if isinstance(result, dict):
        return Message.de_json(result, bot)
    return bool(result)


def rich_api_unavailable(error: BaseException) -> bool:
    if not isinstance(error, (BadRequest, TelegramError)):
        return False
    message = str(error).casefold()
    markers = (
        "method not found",
        "unknown method",
        "sendrichmessage",
        "rich message is not supported",
        "can't parse rich message",
    )
    return any(marker in message for marker in markers)


async def save_prepared_rich_publication(
    bot,
    *,
    user_id: int,
    result_id: str,
    title: str,
    description: str,
    thumbnail_url: str | None,
    rich_html: str,
    reply_markup,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "article",
        "id": result_id,
        "title": title,
        "description": description,
        "input_message_content": {"rich_message": {"html": rich_html}},
        "reply_markup": _serialize_reply_markup(reply_markup),
    }
    if thumbnail_url:
        result["thumbnail_url"] = thumbnail_url
    prepared = await bot._post(
        "savePreparedInlineMessage",
        data={
            "user_id": user_id,
            "result": result,
            "allow_user_chats": True,
            "allow_bot_chats": True,
            "allow_group_chats": True,
            "allow_channel_chats": True,
        },
    )
    return prepared if isinstance(prepared, dict) else {}
