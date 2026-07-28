from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from telegram.error import TelegramError

PERMISSION_CACHE_SECONDS = 300


@dataclass(slots=True, frozen=True)
class PublishAccess:
    allowed: bool
    can_delete: bool
    detail: str = ""
    checked: bool = True


async def check_publish_access(context, target: int | str) -> PublishAccess:
    """Preflight channel rights and cache the result for a warm instance."""
    bot = context.bot
    if not hasattr(bot, "get_chat_member"):
        return PublishAccess(True, False, "not supported by transport", checked=False)

    cache: dict = context.application.bot_data.setdefault("publish_access_cache", {})
    cache_key = str(target)
    now = monotonic()
    cached = cache.get(cache_key)
    if isinstance(cached, tuple) and len(cached) == 2 and cached[0] > now:
        return cached[1]

    try:
        member = await bot.get_chat_member(chat_id=target, user_id=bot.id)
        status = str(getattr(member, "status", "") or "")
        can_post = status == "creator" or bool(
            getattr(member, "can_post_messages", False)
        )
        can_delete = status == "creator" or bool(
            getattr(member, "can_delete_messages", False)
        )
        result = PublishAccess(
            allowed=can_post,
            can_delete=can_delete,
            detail=(
                "ok"
                if can_post
                else "боту не выдано право публиковать сообщения"
            ),
        )
    except TelegramError as exc:
        result = PublishAccess(
            False,
            False,
            f"{type(exc).__name__}: {str(exc)[:160]}",
        )
    except Exception as exc:
        # Test transports and old Telegram client stubs may expose only part
        # of the Bot API. Do not block a working send on an unknown preflight.
        result = PublishAccess(
            True,
            False,
            f"preflight unavailable: {type(exc).__name__}",
            checked=False,
        )

    cache[cache_key] = (now + PERMISSION_CACHE_SECONDS, result)
    return result

