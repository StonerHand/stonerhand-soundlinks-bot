from __future__ import annotations

from typing import Any, Literal

from telegram import InlineKeyboardButton

ButtonStyle = Literal["primary", "success", "danger"]
VALID_BUTTON_STYLES = frozenset({"primary", "success", "danger"})


def button_style_kwargs(style: ButtonStyle | None) -> dict[str, str] | None:
    """Return Bot API fields while the Telegram library catches up.

    Older Telegram clients ignore the unknown ``style`` field and render the
    same button with their default theme, so styled keyboards remain backward
    compatible.
    """
    if style is None:
        return None
    if style not in VALID_BUTTON_STYLES:
        raise ValueError(f"Unsupported Telegram button style: {style}")
    return {"style": style}


def bot_button(
    text: str,
    *,
    style: ButtonStyle | None = None,
    **kwargs: Any,
) -> InlineKeyboardButton:
    """Build every bot button through one semantic styling boundary."""
    return InlineKeyboardButton(
        text=text,
        api_kwargs=button_style_kwargs(style),
        **kwargs,
    )
