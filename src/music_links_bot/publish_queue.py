from __future__ import annotations

import logging
import secrets
import time

from music_links_bot.kvstore import KVStore

LOGGER = logging.getLogger(__name__)

QUEUE_KV_KEY = "queue:v1"
QUEUE_LOCK_KEY = "queue:lock"
QUEUE_LOCK_TTL_SECONDS = 30
QUEUE_MEMORY_KEY = "publish_queue"
MAX_QUEUE_JOBS = 50
MAX_DELAY_SECONDS = 90 * 24 * 3600


async def load_jobs(context) -> list[dict]:
    """The queue lives in Redis so any instance can deliver it; the in-memory
    copy keeps scheduling usable on setups without Redis (single instance)."""
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        jobs = await kv.get_json(QUEUE_KV_KEY)
        if isinstance(jobs, list):
            cleaned = [job for job in jobs if isinstance(job, dict) and job.get("id")]
            context.application.bot_data[QUEUE_MEMORY_KEY] = cleaned
            return cleaned

    return list(context.application.bot_data.get(QUEUE_MEMORY_KEY) or [])


async def save_jobs(context, jobs: list[dict]) -> None:
    context.application.bot_data[QUEUE_MEMORY_KEY] = jobs
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(QUEUE_KV_KEY, jobs)


async def add_job(context, draft: dict, publish_at: int) -> dict:
    jobs = await load_jobs(context)
    job = {
        "id": secrets.token_hex(6),
        "publish_at": int(publish_at),
        "created_at": int(time.time()),
        "draft": draft,
    }
    jobs = [*jobs, job][-MAX_QUEUE_JOBS:]
    jobs.sort(key=lambda item: int(item.get("publish_at") or 0))
    await save_jobs(context, jobs)
    return job


async def remove_job(context, job_id: str) -> bool:
    jobs = await load_jobs(context)
    remaining = [job for job in jobs if job.get("id") != job_id]
    if len(remaining) == len(jobs):
        return False

    await save_jobs(context, remaining)
    return True


async def process_due_jobs(context, *, now: int | None = None) -> int:
    """Publishes every job whose time has come. Called opportunistically on
    each webhook update and on pings of the Studio API, so delivery precision
    follows bot activity (or an external uptime ping)."""
    from music_links_bot.bot import _publish_draft, _schedule_mark_posted
    from music_links_bot.models import TrackMatch

    now_ts = int(now if now is not None else time.time())
    jobs = await load_jobs(context)
    due_ids = {
        str(job.get("id"))
        for job in jobs
        if int(job.get("publish_at") or 0) <= now_ts
    }
    if not due_ids:
        return 0

    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        # Cross-instance guard: only one instance drains the queue at a time.
        acquired = await kv.set(
            QUEUE_LOCK_KEY,
            str(now_ts),
            ttl_seconds=QUEUE_LOCK_TTL_SECONDS,
            nx=True,
        )
        if not acquired:
            return 0

        # Re-read under the lock: another instance may have already drained.
        jobs = await load_jobs(context)
        due_ids = {
            str(job.get("id"))
            for job in jobs
            if int(job.get("publish_at") or 0) <= now_ts
        }
        if not due_ids:
            return 0

    remaining = [job for job in jobs if str(job.get("id")) not in due_ids]
    await save_jobs(context, remaining)

    published = 0
    for job in jobs:
        if str(job.get("id")) not in due_ids:
            continue

        draft = job.get("draft")
        if not isinstance(draft, dict) or not isinstance(draft.get("item"), dict):
            continue

        try:
            if await _publish_draft(context, draft):
                published += 1
                _schedule_mark_posted(context, TrackMatch(**draft["item"]))
        except Exception:
            LOGGER.exception("Scheduled publish failed for job %s", job.get("id"))

    return published
