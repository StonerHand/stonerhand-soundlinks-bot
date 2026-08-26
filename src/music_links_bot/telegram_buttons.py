from __future__ import annotations

from enum import Enum

from telegram import InlineKeyboardButton as TelegramInlineKeyboardButton


class ButtonTone(str, Enum):
    PRIMARY = "primary"
    SUCCESS = "success"
    DANGER = "danger"
    NEUTRAL = "neutral"


def _style_kwargs(tone: ButtonTone | None) -> dict:
    if tone is None or tone is ButtonTone.NEUTRAL:
        return {}
    return {"style": tone.value}


def callback_button(
    text: str,
    callback_data: str,
    *,
    tone: ButtonTone | None = None,
) -> TelegramInlineKeyboardButton:
    return TelegramInlineKeyboardButton(
        text=text,
        callback_data=callback_data,
        **_style_kwargs(tone),
    )


def url_button(
    text: str,
    url: str,
    *,
    tone: ButtonTone | None = None,
) -> TelegramInlineKeyboardButton:
    return TelegramInlineKeyboardButton(text=text, url=url, **_style_kwargs(tone))


def current_chat_button(
    text: str,
    query: str = "",
    *,
    tone: ButtonTone | None = None,
) -> TelegramInlineKeyboardButton:
    return TelegramInlineKeyboardButton(
        text=text,
        switch_inline_query_current_chat=query,
        **_style_kwargs(tone),
    )


def share_button(text: str, query: str) -> TelegramInlineKeyboardButton:
    return TelegramInlineKeyboardButton(text=text, switch_inline_query=query)


def disabled_button(
    text: str,
    *,
    tone: ButtonTone | None = None,
) -> TelegramInlineKeyboardButton:
    """Render a native Bot API 10.3 disabled state."""
    return TelegramInlineKeyboardButton(
        text=text,
        api_kwargs={"disabled": {}},
        **_style_kwargs(tone),
    )


def button(
    text: str,
    *,
    tone: ButtonTone | None = None,
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
    return TelegramInlineKeyboardButton(text=text, **kwargs)
