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
    return {"api_kwargs": {"style": tone.value}}


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
    api_kwargs = dict(_style_kwargs(tone).get("api_kwargs") or {})
    api_kwargs["disabled"] = {}
    return TelegramInlineKeyboardButton(text=text, api_kwargs=api_kwargs)


def button(
    text: str,
    *,
    tone: ButtonTone | None = None,
    **kwargs,
) -> TelegramInlineKeyboardButton:
    """Compatibility factory that validates semantic Bot API styles centrally."""
    api_kwargs = kwargs.pop("api_kwargs", None)
    if api_kwargs:
        style = api_kwargs.get("style")
        try:
            legacy_tone = ButtonTone(style) if style else None
        except ValueError as exc:
            raise ValueError(f"Unknown Telegram button style: {style}") from exc
        if tone is not None and legacy_tone is not None and tone is not legacy_tone:
            raise ValueError("Conflicting Telegram button styles")
        tone = tone or legacy_tone
    kwargs.update(_style_kwargs(tone))
    return TelegramInlineKeyboardButton(text=text, **kwargs)
