from __future__ import annotations

import asyncio
from dataclasses import dataclass

from music_links_bot.bot_crate import clear_crate, load_crate
from music_links_bot.bot_history import clear_history
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.bot_storage import delete_draft
from music_links_bot.channel_templates import clear_channel_template
from music_links_bot.inline_storage import clear_inline_history
from music_links_bot.publication_presets import clear_presets
from music_links_bot.publish_queue import (
    QueueBusyError,
    QueueStorageError,
    remove_user_jobs,
)
from music_links_bot.stats import remove_identity

STATS_KV_KEY = "stats:v1"


@dataclass(slots=True, frozen=True)
class DeletionResult:
    drafts: int
    scheduled_posts: int
    queue_available: bool


async def delete_user_data(context, user_id: int) -> DeletionResult:
    """Delete addressable user state while preserving anonymous totals."""
    bot_data = context.application.bot_data
    runtime = bot_data.get("runtime")
    if not isinstance(runtime, BotRuntime):
        runtime = BotRuntime(bot_data.get("kv_store"))
        bot_data["runtime"] = runtime

    session = await runtime.get_session(user_id)
    crate = await load_crate(bot_data, user_id)
    draft_ids = {
        str(value)
        for value in [session.active_draft_id, *session.recent_draft_ids]
        if value
    }
    draft_ids.update(
        str(entry.get("draft_id"))
        for entry in crate
        if isinstance(entry, dict) and entry.get("draft_id")
    )
    for draft_id, draft in list(bot_data.setdefault("drafts", {}).items()):
        if isinstance(draft, dict) and int(draft.get("chat_id") or 0) == user_id:
            draft_ids.add(str(draft_id))

    for draft_id in draft_ids:
        await delete_draft(context, draft_id)

    await asyncio.gather(
        clear_crate(bot_data, user_id),
        clear_history(context, user_id),
        clear_inline_history(bot_data, user_id),
        clear_channel_template(context, f"user:{user_id}"),
        clear_presets(context, user_id),
    )
    await _clear_transient_memory(context, user_id)
    await _remove_stats_identity(context, user_id)

    queue_available = True
    try:
        scheduled_posts = await remove_user_jobs(context, user_id)
    except (QueueBusyError, QueueStorageError):
        queue_available = False
        scheduled_posts = 0

    await runtime.forget_session(user_id)
    return DeletionResult(
        drafts=len(draft_ids),
        scheduled_posts=scheduled_posts,
        queue_available=queue_available,
    )


async def _clear_transient_memory(context, user_id: int) -> None:
    bot_data = context.application.bot_data
    kv = bot_data.get("kv_store")
    for memory_key, redis_prefix in (
        ("search_selections", "selection:v1"),
        ("retry_sources", "retry:v1"),
    ):
        items = bot_data.setdefault(memory_key, {})
        owned = [
            str(state_id)
            for state_id, payload in list(items.items())
            if isinstance(payload, dict) and int(payload.get("user_id") or 0) == user_id
        ]
        for state_id in owned:
            items.pop(state_id, None)
            if kv is not None:
                await kv.delete(f"{redis_prefix}:{state_id}")


async def _remove_stats_identity(context, user_id: int) -> None:
    # Local stats are used only outside serverless or as an ephemeral fallback.
    await asyncio.to_thread(remove_identity, user_id)
    kv = context.application.bot_data.get("kv_store")
    if kv is None:
        return
    payload = await kv.get_json(STATS_KV_KEY)
    if not isinstance(payload, dict):
        return
    changed = dict(payload)
    for key in ("users", "chats"):
        values = changed.get(key)
        if isinstance(values, dict):
            values = dict(values)
            values.pop(str(user_id), None)
            changed[key] = values
    await kv.set_json(STATS_KV_KEY, changed)
