from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass
from datetime import timedelta
from time import monotonic
from typing import Any

import httpx
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.warnings import PTBDeprecationWarning

from music_links_bot.constants import HTTP_USER_AGENT

LOGGER = logging.getLogger(__name__)
TELEGRAM_API_BASE = "https://api.telegram.org"
CAPABILITY_COOLDOWN_SECONDS = 5 * 60


@dataclass(slots=True)
class CapabilityState:
    failures: int = 0
    blocked_until: float = 0.0


_CAPABILITIES: dict[str, CapabilityState] = {}
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _telegram_api_error(status_code: int, payload: object) -> TelegramError:
    """Preserve definitive Bot API rejections for safe retry decisions."""
    description = "Telegram API request failed"
    if isinstance(payload, dict):
        description = str(payload.get("description") or description)
    if status_code == 400:
        return BadRequest(description)
    if status_code == 403:
        return Forbidden(description)
    if status_code == 429:
        parameters = payload.get("parameters") if isinstance(payload, dict) else None
        retry_after = (
            parameters.get("retry_after") if isinstance(parameters, dict) else 1
        )
        try:
            delay = max(1, int(retry_after))
        except (TypeError, ValueError):
            delay = 1
        # PTB 22.x warns inside the constructor while it transitions this
        # field from int to timedelta. We already pass the forward-compatible
        # shape and keep that library-only compatibility warning out of logs.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", PTBDeprecationWarning)
            return RetryAfter(timedelta(seconds=delay))
    return TelegramError(description)


def feature_enabled(name: str, *, default: bool = True) -> bool:
    """Read a boolean feature flag with one global emergency kill switch."""
    if name != "BOT_SAFE_MODE":
        safe_mode = os.getenv("BOT_SAFE_MODE", "").strip().casefold()
        if safe_mode in _TRUE_VALUES:
            return False
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in _TRUE_VALUES


def capability_available(name: str) -> bool:
    state = _CAPABILITIES.get(name)
    return state is None or state.blocked_until <= monotonic()


def record_capability_success(name: str) -> None:
    _CAPABILITIES.pop(name, None)


def record_capability_failure(
    name: str,
    error: BaseException,
    *,
    unsupported: bool = False,
) -> None:
    state = _CAPABILITIES.setdefault(name, CapabilityState())
    state.failures += 1
    if unsupported or state.failures >= 3:
        state.blocked_until = monotonic() + CAPABILITY_COOLDOWN_SECONDS
        LOGGER.info(
            "Telegram capability temporarily disabled capability=%s error=%s",
            name,
            type(error).__name__,
        )


def reset_capabilities() -> None:
    """Clear warm-instance capability state. Primarily useful for tests."""
    _CAPABILITIES.clear()


def serialize(value: object | None) -> object | None:
    if value is None:
        return None
    to_dict = getattr(value, "to_dict", None)
    return to_dict() if callable(to_dict) else value


class TelegramApiGateway:
    """One compatibility boundary for Bot API methods newer than PTB.

    The installed python-telegram-bot release may not yet expose typed wrappers
    for the newest Bot API. Keeping the raw transport here means the rest of
    the application never depends on private library details.
    """

    def __init__(
        self,
        *,
        bot: object | None = None,
        token: str | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.bot = bot
        self.token = token or str(getattr(bot, "token", "") or "")
        self.timeout = timeout

    async def request(self, method: str, data: dict[str, object]) -> Any:
        post = getattr(self.bot, "_post", None)
        if callable(post):
            return await post(method, data=data)
        if not self.token:
            raise BadRequest("Telegram bot token is unavailable")

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=3.0),
            headers={"User-Agent": HTTP_USER_AGENT},
        ) as client:
            response = await client.post(
                f"{TELEGRAM_API_BASE}/bot{self.token}/{method}",
                json=data,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramError("Telegram returned invalid JSON") from exc
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise _telegram_api_error(response.status_code, payload)
        return payload.get("result")

    async def send_rich_message(
        self,
        *,
        chat_id: int | str,
        rich_message: dict[str, object],
        reply_markup: object | None = None,
        ephemeral_message_parameters: dict[str, object] | None = None,
    ) -> Any:
        data: dict[str, object] = {
            "chat_id": chat_id,
            "rich_message": rich_message,
        }
        if reply_markup is not None:
            data["reply_markup"] = serialize(reply_markup)
        if ephemeral_message_parameters:
            data["ephemeral_message_parameters"] = ephemeral_message_parameters
        return await self.request("sendRichMessage", data)

    async def edit_rich_message(
        self,
        *,
        chat_id: int | str,
        message_id: int,
        rich_message: dict[str, object],
        reply_markup: object | None = None,
    ) -> Any:
        data: dict[str, object] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "rich_message": rich_message,
        }
        if reply_markup is not None:
            data["reply_markup"] = serialize(reply_markup)
        return await self.request("editMessageText", data)

    async def send_rich_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        rich_message: dict[str, object],
        can_stop: bool = False,
        keep_on_stop: bool = False,
    ) -> bool:
        result = await self.request(
            "sendRichMessageDraft",
            {
                "chat_id": chat_id,
                "draft_id": draft_id,
                "rich_message": rich_message,
                "can_stop": can_stop,
                "keep_on_stop": keep_on_stop,
            },
        )
        return bool(result)

    async def send_ephemeral_message(
        self,
        *,
        chat_id: int | str,
        receiver_user_id: int,
        text: str,
        callback_query_id: str | None = None,
        replace_callback_query_message: bool = False,
        parse_mode: object | None = None,
        reply_markup: object | None = None,
        link_preview_options: object | None = None,
        reply_to_message_id: int | None = None,
    ) -> bool:
        ephemeral_parameters: dict[str, object] = {
            "receiver_user_id": int(receiver_user_id),
        }
        if callback_query_id:
            ephemeral_parameters["callback_query_id"] = callback_query_id
            if replace_callback_query_message:
                ephemeral_parameters["replace_callback_query_message"] = True

        data: dict[str, object] = {
            "chat_id": chat_id,
            "text": text,
            "ephemeral_message_parameters": ephemeral_parameters,
        }
        if parse_mode is not None:
            data["parse_mode"] = str(parse_mode)
        if reply_markup is not None:
            data["reply_markup"] = serialize(reply_markup)
        if link_preview_options is not None:
            data["link_preview_options"] = serialize(link_preview_options)
        if reply_to_message_id:
            data["reply_parameters"] = {"message_id": reply_to_message_id}
        return bool(await self.request("sendMessage", data))
