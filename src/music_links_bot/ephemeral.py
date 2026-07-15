from __future__ import annotations

import logging
import os

import httpx

from music_links_bot.constants import HTTP_USER_AGENT

LOGGER = logging.getLogger(__name__)
TELEGRAM_API_BASE = "https://api.telegram.org"


def ephemeral_group_replies_enabled() -> bool:
    """Opt-in flag for invisible (ephemeral) replies in groups.

    Off by default: the feature rides very new Bot API surface, so it only
    activates when the operator sets EPHEMERAL_GROUP_REPLIES and Telegram
    actually supports it for the bot. When it can't deliver, the caller falls
    back to the normal public reply.
    """
    return os.getenv("EPHEMERAL_GROUP_REPLIES", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def send_ephemeral_message(
    bot_token: str | None,
    chat_id: int | str,
    receiver_user_id: int | None,
    text: str,
    *,
    parse_mode: object | None = None,
    reply_markup: object | None = None,
    link_preview_options: object | None = None,
    reply_to_message_id: int | None = None,
    timeout: float = 8.0,
) -> bool:
    """Reply in a group so only `receiver_user_id` sees it — Telegram's
    "invisible messages". Called over raw HTTP so it works regardless of the
    installed python-telegram-bot version; never raises and returns False when
    the feature is unavailable, so callers can fall back to a public reply.
    """
    if not bot_token or not receiver_user_id:
        return False

    payload: dict[str, object] = {
        "chat_id": chat_id,
        "receiver_user_id": receiver_user_id,
        "text": text,
    }
    if parse_mode is not None:
        payload["parse_mode"] = str(parse_mode)
    if reply_markup is not None:
        payload["reply_markup"] = _as_dict(reply_markup)
    if link_preview_options is not None:
        payload["link_preview_options"] = _as_dict(link_preview_options)
    if reply_to_message_id:
        payload["reply_parameters"] = {"message_id": reply_to_message_id}

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=3.0),
            headers={"User-Agent": HTTP_USER_AGENT},
        ) as client:
            response = await client.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage",
                json=payload,
            )
            data = response.json()
        return bool(isinstance(data, dict) and data.get("ok"))
    except Exception:
        LOGGER.debug("Ephemeral send failed", exc_info=True)
        return False


def _as_dict(value: object) -> object:
    to_dict = getattr(value, "to_dict", None)
    return to_dict() if callable(to_dict) else value
