from __future__ import annotations

from html import escape
from urllib.parse import urlparse

from telegram import MessageEntity

from music_links_bot.url_utils import strip_supported_urls_with_mapping

FORMATTING_ENTITY_TYPES = {
    MessageEntity.BOLD,
    MessageEntity.ITALIC,
    MessageEntity.UNDERLINE,
    MessageEntity.STRIKETHROUGH,
    MessageEntity.SPOILER,
    MessageEntity.CODE,
    MessageEntity.PRE,
    MessageEntity.TEXT_LINK,
    MessageEntity.TEXT_MENTION,
    MessageEntity.CUSTOM_EMOJI,
}
SAFE_LINK_SCHEMES = {"http", "https", "tg", "mailto"}


def format_user_note_html(
    text: str | None,
    entities: tuple[MessageEntity, ...] | list[MessageEntity] | None,
    *,
    max_length: int,
) -> str:
    """Preserve Telegram formatting while removing supported source URLs."""
    if not text:
        return ""

    stripped_text, source_indices = strip_supported_urls_with_mapping(text)
    if not stripped_text:
        return ""

    remapped_entities = _remap_entities(
        text,
        stripped_text,
        source_indices,
        entities or (),
    )
    shortened_text, shortened_entities = _truncate_entities(
        stripped_text,
        remapped_entities,
        max_length=max_length,
    )
    return _render_html(shortened_text, shortened_entities)


def _remap_entities(
    source_text: str,
    output_text: str,
    source_indices: tuple[int, ...],
    entities: tuple[MessageEntity, ...] | list[MessageEntity],
) -> tuple[MessageEntity, ...]:
    source_offsets = _utf16_offsets(source_text)
    output_offsets = _utf16_offsets(output_text)
    remapped: list[MessageEntity] = []

    for entity in entities:
        sanitized = _sanitize_entity(entity)
        if sanitized is None:
            continue

        entity_start = entity.offset
        entity_end = entity.offset + entity.length
        covered_output_indices = [
            output_index
            for output_index, source_index in enumerate(source_indices)
            if source_offsets[source_index] >= entity_start
            and source_offsets[source_index + 1] <= entity_end
        ]
        if not covered_output_indices:
            continue

        output_start_index = covered_output_indices[0]
        output_end_index = covered_output_indices[-1] + 1
        remapped.append(
            MessageEntity(
                type=sanitized.type,
                offset=output_offsets[output_start_index],
                length=(
                    output_offsets[output_end_index]
                    - output_offsets[output_start_index]
                ),
                url=sanitized.url,
                user=sanitized.user,
                language=sanitized.language,
                custom_emoji_id=sanitized.custom_emoji_id,
            )
        )

    return tuple(remapped)


def _truncate_entities(
    text: str,
    entities: tuple[MessageEntity, ...],
    *,
    max_length: int,
) -> tuple[str, tuple[MessageEntity, ...]]:
    if len(text) <= max_length:
        return text, entities

    visible_text = text[: max_length - 1].rstrip()
    shortened_text = visible_text + "…"
    cutoff = _utf16_length(visible_text)
    shortened_entities: list[MessageEntity] = []

    for entity in entities:
        start = entity.offset
        end = min(entity.offset + entity.length, cutoff)
        if start >= end:
            continue

        shortened_entities.append(
            MessageEntity(
                type=entity.type,
                offset=start,
                length=end - start,
                url=entity.url,
                user=entity.user,
                language=entity.language,
                custom_emoji_id=entity.custom_emoji_id,
            )
        )

    return shortened_text, tuple(shortened_entities)


def _sanitize_entity(entity: MessageEntity) -> MessageEntity | None:
    if entity.type not in FORMATTING_ENTITY_TYPES:
        return None

    if entity.type == MessageEntity.TEXT_LINK:
        if not entity.url or urlparse(entity.url).scheme.lower() not in SAFE_LINK_SCHEMES:
            return None
        safe_url = escape(entity.url, quote=True)
    else:
        safe_url = entity.url

    return MessageEntity(
        type=entity.type,
        offset=entity.offset,
        length=entity.length,
        url=safe_url,
        user=entity.user,
        language=None if entity.type == MessageEntity.PRE else entity.language,
        custom_emoji_id=entity.custom_emoji_id,
    )


def _render_html(
    text: str,
    entities: tuple[MessageEntity, ...],
    *,
    offset: int = 0,
) -> str:
    encoded_text = text.encode("utf-16-le")
    rendered = ""
    last_offset = 0
    sorted_entities = sorted(entities, key=lambda entity: entity.offset)
    nested_entities: set[MessageEntity] = set()

    for entity in sorted_entities:
        if entity in nested_entities:
            continue

        nested = tuple(
            candidate
            for candidate in sorted_entities
            if candidate != entity
            and candidate.offset >= entity.offset
            and candidate.offset + candidate.length <= entity.offset + entity.length
        )
        nested_entities.update(nested)
        entity_text = _slice_utf16(text, entity.offset - offset, entity.length)
        content = (
            _render_html(entity_text, nested, offset=entity.offset)
            if nested
            else escape(entity_text)
        )
        insert = _wrap_entity_html(entity, content)
        entity_start = entity.offset - offset
        rendered += escape(
            encoded_text[last_offset * 2 : entity_start * 2].decode("utf-16-le")
        )
        rendered += insert
        last_offset = entity_start + entity.length

    rendered += escape(encoded_text[last_offset * 2 :].decode("utf-16-le"))
    return rendered


def _wrap_entity_html(entity: MessageEntity, content: str) -> str:
    if entity.type == MessageEntity.TEXT_LINK:
        return f'<a href="{entity.url}">{content}</a>'
    if entity.type == MessageEntity.TEXT_MENTION and entity.user:
        return f'<a href="tg://user?id={entity.user.id}">{content}</a>'
    if entity.type == MessageEntity.BOLD:
        return f"<b>{content}</b>"
    if entity.type == MessageEntity.ITALIC:
        return f"<i>{content}</i>"
    if entity.type == MessageEntity.CODE:
        return f"<code>{content}</code>"
    if entity.type == MessageEntity.PRE:
        return f"<pre>{content}</pre>"
    if entity.type == MessageEntity.UNDERLINE:
        return f"<u>{content}</u>"
    if entity.type == MessageEntity.STRIKETHROUGH:
        return f"<s>{content}</s>"
    if entity.type == MessageEntity.SPOILER:
        return f'<span class="tg-spoiler">{content}</span>'
    if entity.type == MessageEntity.CUSTOM_EMOJI:
        return f'<tg-emoji emoji-id="{entity.custom_emoji_id}">{content}</tg-emoji>'
    return content


def _slice_utf16(text: str, offset: int, length: int) -> str:
    encoded = text.encode("utf-16-le")
    return encoded[offset * 2 : (offset + length) * 2].decode("utf-16-le")


def _utf16_offsets(text: str) -> list[int]:
    offsets = [0]
    current = 0
    for character in text:
        current += _utf16_length(character)
        offsets.append(current)
    return offsets


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2
