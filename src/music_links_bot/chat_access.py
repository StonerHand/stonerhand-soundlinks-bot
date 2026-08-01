from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from telegram.error import TelegramError

from music_links_bot.bot_storage import remember_bounded

PERMISSION_CACHE_SECONDS = 300
MAX_PERMISSION_CACHE = 100


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
    if (
        isinstance(cached, tuple)
        and len(cached) == 2
        and isinstance(cached[0], (int, float))
        and cached[0] > now
    ):
        return cached[1]
    for key, value in list(cache.items()):
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or not isinstance(value[0], (int, float))
            or value[0] <= now
        ):
            cache.pop(key, None)

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

    remember_bounded(
        cache,
        cache_key,
        (now + PERMISSION_CACHE_SECONDS, result),
        max_size=MAX_PERMISSION_CACHE,
    )
    return result
