from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from music_links_bot.bot_crate import clear_crate, load_crate
from music_links_bot.bot_history import clear_history
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.bot_storage import delete_draft
from music_links_bot.channel_templates import clear_channel_template
from music_links_bot.constants import STATS_KV_KEY
from music_links_bot.inline_storage import clear_inline_history
from music_links_bot.publication_presets import clear_presets
from music_links_bot.publish_queue import (
    QueueBusyError,
    QueueStorageError,
    remove_user_jobs,
)
from music_links_bot.stats import remove_identity


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

    from music_links_bot.durable_state import delete_value
    from music_links_bot.user_state import invalidate_previous_requests, owned_keys

    kv = bot_data.get("kv_store")
    await invalidate_previous_requests(kv, user_id)
    indexed_keys = await owned_keys(kv, user_id)
    session = await runtime.get_session(user_id)
    crate = await load_crate(bot_data, user_id)
    draft_ids = {
        str(value)
        for value in [
            session.active_draft_id,
            *session.recent_draft_ids,
            *session.saved_draft_ids,
        ]
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

    draft_ids.update(
        key.removeprefix("draft:") for key in indexed_keys if key.startswith("draft:")
    )
    batch_delete = getattr(kv, "delete_many_required", None)
    if batch_delete is not None:
        await batch_delete(sorted(indexed_keys))
    else:
        for key in indexed_keys:
            await delete_value(kv, key)
    if kv is not None:
        await delete_value(kv, f"user-keys:v1:{user_id}")

    for draft_id in draft_ids:
        if f"draft:{draft_id}" in indexed_keys:
            bot_data.setdefault("drafts", {}).pop(draft_id, None)
        else:
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

    from music_links_bot.durable_state import delete_value, read_json

    kv = bot_data.get("kv_store")
    receipt_index = (
        await read_json(kv, f"receipt-index:v1:{user_id}")
        if kv
        else bot_data.get("receipt_indexes", {}).get(user_id)
    )
    for key in receipt_index if isinstance(receipt_index, (list, dict)) else []:
        if isinstance(key, str) and re.fullmatch(
            r"manual-delivery:v1:[A-Za-z0-9_-]{1,64}:[0-9a-f]{16}", key
        ):
            if kv:
                await delete_value(kv, key)
            bot_data.get("delivery_receipts", {}).pop(key, None)
    if kv:
        await delete_value(kv, f"receipt-index:v1:{user_id}")
    bot_data.get("receipt_indexes", {}).pop(user_id, None)
    await runtime.forget_session(user_id)
    return DeletionResult(
        drafts=len(draft_ids),
        scheduled_posts=scheduled_posts,
        queue_available=queue_available,
    )


async def _clear_transient_memory(context, user_id: int) -> None:
    from music_links_bot.durable_state import delete_value

    bot_data = context.application.bot_data
    kv = bot_data.get("kv_store")
    for memory_key, redis_prefix in (
        ("search_selections", "selection:v1"),
        ("retry_sources", "retry:v1"),
        ("input_choices", "input-choice:v1"),
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
                await delete_value(kv, f"{redis_prefix}:{state_id}")


async def _remove_stats_identity(context, user_id: int) -> None:
    # Local stats are used only outside serverless or as an ephemeral fallback.
    await asyncio.to_thread(remove_identity, user_id)
    kv = context.application.bot_data.get("kv_store")
    if kv is None:
        return
    from music_links_bot.state_mutations import mutate_json

    def remove(payload):
        changed = dict(payload) if isinstance(payload, dict) else {}
        for key in ("users", "chats"):
            values = changed.get(key)
            if isinstance(values, dict):
                values = dict(values)
                values.pop(str(user_id), None)
                changed[key] = values
        return changed

    await mutate_json(kv, STATS_KV_KEY, remove, ttl_seconds=10 * 365 * 86400)
