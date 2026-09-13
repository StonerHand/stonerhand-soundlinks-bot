"""Aggregate chosen cards without retaining users, chat IDs or query text."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import time

from music_links_bot.bot_storage import remember_bounded

RESULT_TTL = 2 * 24 * 3600
STATS_TTL = 31 * 24 * 3600


def week_key():
    year, week, _ = datetime.now(timezone.utc).isocalendar()
    return f"inline-sent:v1:{year}:{week}"


async def remember_results(bot_data, results):
    async def remember(result):
        if not getattr(result, "id", None):
            return
        label = " ".join(result.title.split())[:200]
        if not label:
            return
        remember_bounded(
            bot_data.setdefault("inline_result_labels", {}),
            result.id,
            (time() + RESULT_TTL, label),
            max_size=1000,
        )
        kv = bot_data.get("kv_store")
        if kv is not None:
            await kv.set("inline-result:v1:" + result.id, label, ttl_seconds=RESULT_TTL)

    await asyncio.gather(*(remember(result) for result in results))


async def chosen_inline_result_handler(update, context):
    chosen = update.chosen_inline_result
    if chosen is None:
        return
    data = context.application.bot_data
    cached = data.get("inline_result_labels", {}).get(chosen.result_id)
    label = cached[1] if cached and cached[0] > time() else None
    kv = data.get("kv_store")
    if not label and kv is not None:
        label = await kv.get("inline-result:v1:" + chosen.result_id)
    label = label or "Карточка без сохранённого названия"
    key = week_key()
    if kv is not None:
        await kv.record_ranked_event(
            key, f"inline-event:v1:{update.update_id}", label, ttl_seconds=STATS_TTL
        )
        return
    seen = data.setdefault("inline_chosen_seen", {})
    if seen.get(update.update_id, 0) > time():
        return
    remember_bounded(seen, update.update_id, time() + 86400, max_size=2000)
    weeks = data.setdefault("inline_chosen_counts", {})
    if key not in weeks:
        remember_bounded(weeks, key, {}, max_size=5)
    counts = weeks[key]
    if label not in counts and len(counts) >= 512:
        label = "Остальные карточки"
    counts[label] = counts.get(label, 0) + 1


async def feedback_text(bot_data):
    key = week_key()
    kv = bot_data.get("kv_store")
    if kv is not None:
        entries = await kv.ranked_events(key, limit=5)
    else:
        counts = bot_data.get("inline_chosen_counts", {}).get(key, {})
        entries = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]
    if not entries:
        return "\n\nInline · на этой неделе нет событий отправки."
    return "\n\nInline · чаще отправляли на этой неделе (UTC)\n" + "\n".join(
        f"{index}. {label} — {count}" for index, (label, count) in enumerate(entries, 1)
    )
