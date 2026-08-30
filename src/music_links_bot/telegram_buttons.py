from __future__ import annotations

import os
from enum import Enum

from telegram import InlineKeyboardButton as TelegramInlineKeyboardButton


class ButtonTone(str, Enum):
    PRIMARY = "primary"
    SUCCESS = "success"
    DANGER = "danger"
    NEUTRAL = "neutral"


class ButtonIcon(str, Enum):
    """Small, stable icon vocabulary shared by every native bot screen.

    Telegram can render a custom emoji before a button label.  The IDs are
    intentionally optional: regular emoji remain the complete fallback and
    no publication depends on Premium-only presentation.
    """

    TRACK = "track"
    ALBUM = "album"
    RADIO = "radio"
    COLLECTION = "collection"
    HUB = "hub"
    EXTERNAL = "external"
    ADD = "add"
    READY = "ready"
    WARNING = "warning"
    SHARE = "share"


_ICON_FALLBACKS = {
    ButtonIcon.TRACK: "🎧",
    ButtonIcon.ALBUM: "💿",
    ButtonIcon.RADIO: "📻",
    ButtonIcon.COLLECTION: "🧺",
    ButtonIcon.HUB: "🪩",
    ButtonIcon.EXTERNAL: "↗",
    ButtonIcon.ADD: "＋",
    ButtonIcon.READY: "✓",
    ButtonIcon.WARNING: "⚠️",
    ButtonIcon.SHARE: "↗",
}


def _custom_emoji_id(icon: ButtonIcon | None) -> str | None:
    if icon is None:
        return None
    value = os.getenv(f"TELEGRAM_BUTTON_ICON_{icon.value.upper()}_ID", "").strip()
    return value if value.isdigit() else None


def icon_label(text: str, icon: ButtonIcon | None) -> str:
    """Prefix a plain label unless Telegram will draw the custom icon."""
    clean = " ".join(str(text or "").split()).strip()
    if icon is None or not clean:
        return clean
    fallback = _ICON_FALLBACKS[icon]
    if icon is ButtonIcon.ADD and clean.startswith("+"):
        clean = clean[1:].lstrip()
    for known in _ICON_FALLBACKS.values():
        if clean.startswith(known):
            clean = clean[len(known) :].lstrip()
            break
    return clean if _custom_emoji_id(icon) else f"{fallback} {clean}"


def _icon_kwargs(icon: ButtonIcon | None) -> dict:
    emoji_id = _custom_emoji_id(icon)
    return {"icon_custom_emoji_id": emoji_id} if emoji_id else {}


def _style_kwargs(tone: ButtonTone | None) -> dict:
    if tone is None or tone is ButtonTone.NEUTRAL:
        return {}
    return {"style": tone.value}


def callback_button(
    text: str,
    callback_data: str,
    *,
    tone: ButtonTone | None = None,
    icon: ButtonIcon | None = None,
) -> TelegramInlineKeyboardButton:
    return TelegramInlineKeyboardButton(
        text=icon_label(text, icon),
        callback_data=callback_data,
        **_style_kwargs(tone),
        **_icon_kwargs(icon),
    )


def url_button(
    text: str,
    url: str,
    *,
    tone: ButtonTone | None = None,
    icon: ButtonIcon | None = None,
) -> TelegramInlineKeyboardButton:
    return TelegramInlineKeyboardButton(
        text=icon_label(text, icon),
        url=url,
        **_style_kwargs(tone),
        **_icon_kwargs(icon),
    )


def current_chat_button(
    text: str,
    query: str = "",
    *,
    tone: ButtonTone | None = None,
    icon: ButtonIcon | None = None,
) -> TelegramInlineKeyboardButton:
    return TelegramInlineKeyboardButton(
        text=icon_label(text, icon),
        switch_inline_query_current_chat=query,
        **_style_kwargs(tone),
        **_icon_kwargs(icon),
    )


def share_button(
    text: str,
    query: str,
    *,
    icon: ButtonIcon | None = ButtonIcon.SHARE,
) -> TelegramInlineKeyboardButton:
    return TelegramInlineKeyboardButton(
        text=icon_label(text, icon),
        switch_inline_query=query,
        **_icon_kwargs(icon),
    )


def disabled_button(
    text: str,
    *,
    tone: ButtonTone | None = None,
    icon: ButtonIcon | None = None,
) -> TelegramInlineKeyboardButton:
    """Render a native Bot API 10.3 disabled state."""
    return TelegramInlineKeyboardButton(
        text=icon_label(text, icon),
        api_kwargs={"disabled": {}},
        **_style_kwargs(tone),
        **_icon_kwargs(icon),
    )


def button(
    text: str,
    *,
    tone: ButtonTone | None = None,
    icon: ButtonIcon | None = None,
    **kwargs,
) -> TelegramInlineKeyboardButton:
    """Validate semantic Bot API styles at the shared construction boundary."""
    native_style = kwargs.pop("style", None)
    try:
        native_tone = ButtonTone(native_style) if native_style else None
    except ValueError as exc:
        raise ValueError(f"Unknown Telegram button style: {native_style}") from exc
    if tone is not None and native_tone is not None and tone is not native_tone:
        raise ValueError("Conflicting Telegram button styles")
    tone = tone or native_tone
    kwargs.update(_style_kwargs(tone))
    kwargs.update(_icon_kwargs(icon))
    return TelegramInlineKeyboardButton(text=icon_label(text, icon), **kwargs)
