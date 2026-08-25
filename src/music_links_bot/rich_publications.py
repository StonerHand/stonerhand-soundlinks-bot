from __future__ import annotations

import html
import logging
import re
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import urlparse

from telegram import InlineKeyboardMarkup, Message
from telegram.error import BadRequest, TelegramError

from music_links_bot.models import TrackMatch, VideoMatch
from music_links_bot.publication_model import MusicPublication
from music_links_bot.telegram_gateway import (
    TelegramApiGateway,
    capability_available,
    feature_enabled,
    record_capability_failure,
    record_capability_success,
)

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
MAX_RICH_MEDIA = 10
RICH_MESSAGE_CAPABILITY = "rich_messages"

BLOCK_TYPES = frozenset({"paragraph", "heading", "quote", "list", "details", "divider"})
_BLOCK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def rich_messages_enabled() -> bool:
    return feature_enabled(
        "RICH_MESSAGES_ENABLED", default=True
    ) and capability_available(RICH_MESSAGE_CAPABILITY)


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
                    raw_items[:MAX_LIST_ITEMS] if isinstance(raw_items, list) else []
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


class _RichFragmentSanitizer(HTMLParser):
    _INLINE_TAGS: ClassVar[set[str]] = {
        "b",
        "strong",
        "i",
        "em",
        "u",
        "ins",
        "s",
        "strike",
        "del",
        "code",
        "pre",
        "mark",
        "sub",
        "sup",
        "tg-spoiler",
        "blockquote",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag == "span" and attributes.get("class") == "tg-spoiler":
            tag = "tg-spoiler"
        if tag == "br":
            self.parts.append("<br>")
            return
        if tag == "a":
            url = _safe_action_url(attributes.get("href"))
            if not url:
                return
            self.parts.append(f'<a href="{html.escape(url, quote=True)}">')
            self.stack.append(tag)
            return
        if tag == "tg-emoji":
            emoji_id = str(attributes.get("emoji-id") or "")
            if not emoji_id.isdigit():
                return
            self.parts.append(f'<tg-emoji emoji-id="{emoji_id}">')
            self.stack.append(tag)
            return
        if tag not in self._INLINE_TAGS:
            return
        expandable = (
            " expandable" if tag == "blockquote" and "expandable" in attributes else ""
        )
        self.parts.append(f"<{tag}{expandable}>")
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            tag = "tg-spoiler"
        if tag in self.stack:
            while self.stack:
                current = self.stack.pop()
                self.parts.append(f"</{current}>")
                if current == tag:
                    break

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data))

    def result(self) -> str:
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        return "".join(self.parts)


def sanitize_rich_fragment(value: object) -> str:
    parser = _RichFragmentSanitizer()
    parser.feed(str(value or ""))
    parser.close()
    return parser.result().strip()


def _safe_action_url(value: object) -> str | None:
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme.casefold() in {"http", "https", "tg"} else None


def _safe_media_url(value: object) -> str | None:
    """Rich media blocks accept only direct HTTP(S) resources."""
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme.casefold() in {"http", "https"} else None


def rich_button_rows_html(
    reply_markup: InlineKeyboardMarkup | object | None,
    *,
    align: str = "center",
) -> str:
    """Move a regular inline keyboard into Rich Message content."""
    if reply_markup is None:
        return ""
    to_dict = getattr(reply_markup, "to_dict", None)
    payload = to_dict() if callable(to_dict) else reply_markup
    if not isinstance(payload, dict):
        return ""
    raw_rows = payload.get("inline_keyboard")
    if not isinstance(raw_rows, list):
        return ""

    rows: list[str] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, list):
            continue
        buttons: list[str] = []
        for raw_button in raw_row[:8]:
            if not isinstance(raw_button, dict):
                continue
            text = html.escape(str(raw_button.get("text") or "")[:64])
            if not text:
                continue
            style = str(raw_button.get("style") or "")
            style_attr = (
                f' style="{style}"' if style in {"primary", "success", "danger"} else ""
            )
            url = _safe_action_url(raw_button.get("url"))
            if url:
                buttons.append(
                    f'<tg-button type="url"{style_attr} '
                    f'url="{html.escape(url, quote=True)}">{text}</tg-button>'
                )
                continue
            callback_data = raw_button.get("callback_data")
            if isinstance(callback_data, str) and callback_data:
                callback_style = style or "link"
                buttons.append(
                    f'<tg-button type="callback_data" style="{callback_style}" '
                    f'data="{html.escape(callback_data[:64], quote=True)}">'
                    f"{text}</tg-button>"
                )
                continue
            if "disabled" in raw_button:
                buttons.append(
                    f'<tg-button type="disabled"{style_attr}>{text}</tg-button>'
                )
                continue
            copy_text = raw_button.get("copy_text")
            if isinstance(copy_text, dict) and copy_text.get("text"):
                buttons.append(
                    '<tg-button type="copy_text" '
                    f'text="{html.escape(str(copy_text["text"])[:256], quote=True)}">'
                    f"{text}</tg-button>"
                )
                continue
            for field, rich_type, attribute in (
                ("switch_inline_query", "switch_inline_query", "query"),
                (
                    "switch_inline_query_current_chat",
                    "switch_inline_query_current_chat",
                    "query",
                ),
            ):
                query = raw_button.get(field)
                if isinstance(query, str):
                    buttons.append(
                        f'<tg-button type="{rich_type}"{style_attr} '
                        f'{attribute}="{html.escape(query[:256], quote=True)}">'
                        f"{text}</tg-button>"
                    )
                    break
        if buttons:
            rows.append(
                f'<tg-button-row align="{align}">'
                + "".join(buttons)
                + "</tg-button-row>"
            )
    return "\n".join(rows)


def _media_block(publication: MusicPublication) -> str:
    media = [
        item for item in publication.media[:MAX_RICH_MEDIA] if _safe_media_url(item.url)
    ]
    if not media:
        return ""

    elements = "".join(
        f'<img src="{html.escape(item.url, quote=True)}"/>'
        if item.kind == "photo"
        else f'<video src="{html.escape(item.url, quote=True)}"></video>'
        for item in media
    )
    if len(media) == 1:
        item = media[0]
        caption = (
            f"<figcaption>{html.escape(item.caption)}</figcaption>"
            if item.caption
            else ""
        )
        return f"<figure>{elements}{caption}</figure>"
    container = "tg-collage" if len(media) <= 4 else "tg-slideshow"
    return f"<{container}>{elements}</{container}>"


def build_music_publication_html(
    publication: MusicPublication,
    *,
    reply_markup: InlineKeyboardMarkup | object | None = None,
) -> str:
    pieces = [f"<h1>{html.escape(publication.title)}</h1>"]
    if publication.lead_html:
        lead = sanitize_rich_fragment(publication.lead_html)
        if lead:
            pieces.append(lead if lead.startswith("<blockquote") else f"<p>{lead}</p>")
    media = _media_block(publication)
    if media:
        pieces.append(media)
    if publication.body_html:
        body = sanitize_rich_fragment(publication.body_html)
        if body:
            pieces.append(f"<p>{body}</p>")
    buttons = rich_button_rows_html(reply_markup)
    if buttons:
        pieces.append(buttons)
    if publication.hashtags:
        pieces.append(f"<footer>{html.escape(publication.hashtags)}</footer>")
    return _bounded_rich_html(pieces)


def build_rich_card_html(
    draft: dict,
    track: TrackMatch,
    *,
    hashtags: str | None,
    reply_markup: InlineKeyboardMarkup | object | None,
) -> str:
    publication = MusicPublication.from_track(
        track,
        lead_html=str(draft.get("prefix") or "") if draft.get("quote") else "",
        hashtags=hashtags or "",
    )
    return build_music_publication_html(publication, reply_markup=reply_markup)


def build_rich_inline_card_html(
    track: TrackMatch,
    *,
    hashtags: str | None,
    reply_markup: InlineKeyboardMarkup | object | None,
    media_id: str | None = None,
) -> str:
    """Build an inline-safe rich card.

    Inline rich results may reference only files already uploaded to Telegram.
    A remote artwork URL must therefore never leak into this payload.
    """
    title = MusicPublication.track_title(track)
    pieces = [f"<h1>{html.escape(title)}</h1>"]
    if media_id:
        safe_media_id = re.sub(r"[^A-Za-z0-9_-]", "", media_id)[:64]
        if safe_media_id:
            pieces.append(
                "<figure>"
                f'<img src="tg://photo?id={safe_media_id}"/>'
                f"<figcaption>{html.escape(title)}</figcaption>"
                "</figure>"
            )
    buttons = rich_button_rows_html(reply_markup)
    if buttons:
        pieces.append(buttons)
    if hashtags:
        pieces.append(f"<footer>{html.escape(hashtags)}</footer>")
    return _bounded_rich_html(pieces)


def build_rich_track_video_html(
    track: TrackMatch,
    video: VideoMatch,
    *,
    body_html: str,
    hashtags: str | None,
    reply_markup: InlineKeyboardMarkup | object | None,
) -> str:
    publication = MusicPublication.from_track_video(
        track,
        video,
        body_html=body_html,
        hashtags=hashtags or "",
    )
    return build_music_publication_html(publication, reply_markup=reply_markup)


def build_rich_collection_html(
    tracks: list[TrackMatch],
    *,
    title: str,
    hashtags: str | None,
    reply_markup: InlineKeyboardMarkup | object | None,
) -> str:
    media = [
        MusicPublication.from_track(track).media[0]
        for track in tracks[:MAX_RICH_MEDIA]
        if track.thumbnail_url
    ]
    items = "".join(
        f"<li><b>{html.escape(track.artist)}</b> — {html.escape(track.title)}</li>"
        for track in tracks
    )
    publication = MusicPublication(
        title=title,
        kind="collection",
        body_html="",
        media=media,
        hashtags=hashtags or "",
    )
    pieces = [f"<h1>{html.escape(publication.title)}</h1>"]
    media_html = _media_block(publication)
    if media_html:
        pieces.append(media_html)
    if items:
        pieces.append(f"<ol>{items}</ol>")
    buttons = rich_button_rows_html(reply_markup)
    if buttons:
        pieces.append(buttons)
    if publication.hashtags:
        pieces.append(f"<footer>{html.escape(publication.hashtags)}</footer>")
    return _bounded_rich_html(pieces)


def _bounded_rich_html(pieces: list[str]) -> str:
    value = "\n".join(pieces)
    if len(value) <= MAX_RICH_HTML:
        return value
    selected: list[str] = []
    continuation = "<p><i>…</i></p>"
    for piece in pieces:
        candidate = "\n".join([*selected, piece, continuation])
        if len(candidate) > MAX_RICH_HTML:
            break
        selected.append(piece)
    return "\n".join([*selected, continuation])


def build_rich_html(
    draft: dict,
    track: TrackMatch,
    *,
    hashtags: str | None,
    reply_markup: InlineKeyboardMarkup | object | None = None,
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

    buttons = rich_button_rows_html(reply_markup)
    if buttons:
        pieces.append(buttons)
    if hashtags:
        pieces.append(f"<footer>{html.escape(hashtags)}</footer>")
    return _bounded_rich_html(pieces)


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
        while (
            selected and len("\n\n".join([*selected, continuation])) > MAX_FALLBACK_TEXT
        ):
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
    reply_markup=None,
    ephemeral_message_parameters: dict[str, object] | None = None,
) -> Message | bool:
    # The caller normally observes the warm-instance capability cooldown.
    # Keeping the transport retryable lets an explicit probe recover early.
    if not feature_enabled("RICH_MESSAGES_ENABLED", default=True):
        raise BadRequest("Rich Messages are temporarily unavailable")
    gateway = TelegramApiGateway(bot=bot)
    try:
        result = await gateway.send_rich_message(
            chat_id=chat_id,
            rich_message={"html": rich_html},
            reply_markup=reply_markup,
            ephemeral_message_parameters=ephemeral_message_parameters,
        )
    except TelegramError as exc:
        record_capability_failure(
            RICH_MESSAGE_CAPABILITY,
            exc,
            unsupported=rich_api_unavailable(exc),
        )
        raise
    record_capability_success(RICH_MESSAGE_CAPABILITY)
    if isinstance(result, dict):
        return Message.de_json(result, bot)
    return bool(result)


async def edit_rich_publication(
    bot,
    *,
    chat_id: int | str,
    message_id: int,
    rich_html: str,
    reply_markup=None,
) -> Message | bool:
    gateway = TelegramApiGateway(bot=bot)
    result = await gateway.edit_rich_message(
        chat_id=chat_id,
        message_id=message_id,
        rich_message={"html": rich_html},
        reply_markup=reply_markup,
    )
    if isinstance(result, dict):
        return Message.de_json(result, bot)
    return bool(result)


async def send_rich_progress_draft(
    bot,
    *,
    chat_id: int,
    draft_id: int,
    text: str,
    can_stop: bool = True,
) -> bool:
    if not feature_enabled("RICH_DRAFTS_ENABLED", default=False):
        return False
    gateway = TelegramApiGateway(bot=bot)
    try:
        return await gateway.send_rich_draft(
            chat_id=chat_id,
            draft_id=draft_id,
            rich_message={"html": f"<tg-thinking>{html.escape(text)}</tg-thinking>"},
            can_stop=can_stop,
            keep_on_stop=True,
        )
    except TelegramError:
        LOGGER.debug("Rich progress draft unavailable", exc_info=True)
        return False


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
        "bot token is unavailable",
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
    prepared = await TelegramApiGateway(bot=bot).request(
        "savePreparedInlineMessage",
        {
            "user_id": user_id,
            "result": result,
            "allow_user_chats": True,
            "allow_bot_chats": True,
            "allow_group_chats": True,
            "allow_channel_chats": True,
        },
    )
    return prepared if isinstance(prepared, dict) else {}
