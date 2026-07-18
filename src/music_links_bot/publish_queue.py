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
# A scheduled post that fails to deliver is retried with growing backoff
# before it is finally dropped, so a transient Telegram/network hiccup never
# silently loses a post.
MAX_JOB_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (120, 600, 1800)


async def _acquire_lock(kv: KVStore, *, tries: int = 6, delay: float = 0.15) -> bool:
    import asyncio

    for attempt in range(tries):
        if await kv.set(QUEUE_LOCK_KEY, "1", ttl_seconds=QUEUE_LOCK_TTL_SECONDS, nx=True):
            return True
        if attempt < tries - 1:
            await asyncio.sleep(delay)
    return False


async def _locked_mutate(context, mutate):
    """Run a load→modify→save cycle under the cross-instance queue lock so
    concurrent schedule/cancel calls can't clobber each other. Falls back to an
    unlocked cycle when Redis is absent (single instance — no race to guard)."""
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is None:
        jobs = await load_jobs(context)
        result, new_jobs = mutate(jobs)
        await save_jobs(context, new_jobs)
        return result

    locked = await _acquire_lock(kv)
    try:
        jobs = await load_jobs(context)
        result, new_jobs = mutate(jobs)
        await save_jobs(context, new_jobs)
        return result
    finally:
        if locked:
            await kv.delete(QUEUE_LOCK_KEY)


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
    job = {
        "id": secrets.token_hex(6),
        "publish_at": int(publish_at),
        "created_at": int(time.time()),
        "draft": draft,
    }

    def mutate(jobs: list[dict]):
        merged = [*jobs, job][-MAX_QUEUE_JOBS:]
        merged.sort(key=lambda item: int(item.get("publish_at") or 0))
        return job, merged

    return await _locked_mutate(context, mutate)


async def remove_job(context, job_id: str) -> bool:
    def mutate(jobs: list[dict]):
        remaining = [job for job in jobs if job.get("id") != job_id]
        return len(remaining) != len(jobs), remaining

    return await _locked_mutate(context, mutate)


async def reschedule_job(context, job_id: str, publish_at: int) -> bool:
    def mutate(jobs: list[dict]):
        found = False
        for job in jobs:
            if job.get("id") == job_id:
                job["publish_at"] = int(publish_at)
                found = True
                break

        if found:
            jobs = sorted(jobs, key=lambda item: int(item.get("publish_at") or 0))
        return found, jobs

    return await _locked_mutate(context, mutate)


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
    lock_held = False
    if kv is not None:
        # Cross-instance guard: only one instance drains the queue at a time.
        lock_held = await kv.set(
            QUEUE_LOCK_KEY,
            str(now_ts),
            ttl_seconds=QUEUE_LOCK_TTL_SECONDS,
            nx=True,
        )
        if not lock_held:
            return 0

        # Re-read under the lock: another instance may have already drained.
        jobs = await load_jobs(context)
        due_ids = {
            str(job.get("id"))
            for job in jobs
            if int(job.get("publish_at") or 0) <= now_ts
        }
        if not due_ids:
            await kv.delete(QUEUE_LOCK_KEY)
            return 0

    try:
        # Claim the due jobs (remove them so no other tick re-sends them), then
        # publish. A job that fails to deliver is put BACK with a backoff and an
        # attempt counter instead of being dropped — a transient failure must
        # never silently lose a scheduled post.
        due_jobs = [job for job in jobs if str(job.get("id")) in due_ids]
        remaining = [job for job in jobs if str(job.get("id")) not in due_ids]
        await save_jobs(context, remaining)

        published = 0
        requeue: list[dict] = []
        for job in due_jobs:
            draft = job.get("draft")
            if not isinstance(draft, dict) or not isinstance(draft.get("item"), dict):
                continue  # unrecoverable — drop malformed job

            delivered = False
            try:
                delivered = await _publish_draft(context, draft)
            except Exception:
                LOGGER.exception("Scheduled publish crashed for job %s", job.get("id"))

            if delivered:
                published += 1
                _schedule_mark_posted(context, TrackMatch(**draft["item"]))
                continue

            attempts = int(job.get("attempts") or 0) + 1
            if attempts >= MAX_JOB_ATTEMPTS:
                await _alert_job_failure(context, draft)
            else:
                job["attempts"] = attempts
                backoff = RETRY_BACKOFF_SECONDS[
                    min(attempts, len(RETRY_BACKOFF_SECONDS)) - 1
                ]
                job["publish_at"] = now_ts + backoff
                requeue.append(job)
    finally:
        if lock_held and kv is not None:
            await kv.delete(QUEUE_LOCK_KEY)

    if requeue:
        # Merge the retries back under the lock so a schedule that landed
        # meanwhile is preserved.
        def mutate(current: list[dict]):
            merged = [*current, *requeue][-MAX_QUEUE_JOBS:]
            merged.sort(key=lambda item: int(item.get("publish_at") or 0))
            return None, merged

        await _locked_mutate(context, mutate)

    return published


async def _alert_job_failure(context, draft: dict) -> None:
    """A dropped scheduled post must never fail silently — DM the owner."""
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    if not admin_chat_id:
        return

    item = draft.get("item") or {}
    label = f"{item.get('artist') or '?'} - {item.get('title') or '?'}"
    try:
        await context.bot.send_message(
            chat_id=admin_chat_id,
            text=(
                f"🚨 Отложенный пост не ушёл после {MAX_JOB_ATTEMPTS} попыток и снят "
                f"с очереди: {label}. Проверь права бота в канале и запланируй заново."
            ),
        )
    except Exception:
        LOGGER.debug("Queue failure alert failed", exc_info=True)
