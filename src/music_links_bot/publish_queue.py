from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Callable
from typing import Any

from music_links_bot.kvstore import KVStore

LOGGER = logging.getLogger(__name__)

QUEUE_KV_KEY = "queue:v1"
QUEUE_LOCK_KEY = "queue:lock"
QUEUE_LOCK_TTL_SECONDS = 30
QUEUE_MEMORY_KEY = "publish_queue"
QUEUE_MEMORY_LOCK_KEY = "publish_queue_lock"
MAX_QUEUE_JOBS = 50
MAX_DELAY_SECONDS = 90 * 24 * 3600
MAX_JOB_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (120, 600, 1800)
PROCESSING_LEASE_SECONDS = 90
JOB_PENDING = "pending"
JOB_PROCESSING = "processing"


class QueueBusyError(RuntimeError):
    """Raised when a concurrent queue mutation still owns the Redis lease."""


async def _acquire_lock(
    kv: KVStore, *, tries: int = 6, delay: float = 0.15
) -> str | None:
    owner = secrets.token_hex(12)
    for attempt in range(tries):
        if await kv.set(
            QUEUE_LOCK_KEY,
            owner,
            ttl_seconds=QUEUE_LOCK_TTL_SECONDS,
            nx=True,
        ):
            return owner
        if attempt < tries - 1:
            await asyncio.sleep(delay)
    return None


async def _release_lock(kv: KVStore, owner: str) -> None:
    await kv.delete_if_value(QUEUE_LOCK_KEY, owner)


def _normalize_job(job: dict) -> dict | None:
    if not job.get("id"):
        return None
    normalized = dict(job)
    if normalized.get("status") not in {JOB_PENDING, JOB_PROCESSING}:
        normalized["status"] = JOB_PENDING
    if normalized["status"] == JOB_PENDING:
        normalized.pop("lease_owner", None)
        normalized.pop("lease_until", None)
    return normalized


def _sort_jobs(jobs: list[dict]) -> list[dict]:
    return sorted(jobs, key=lambda item: int(item.get("publish_at") or 0))


async def _locked_mutate(
    context,
    mutate: Callable[[list[dict]], tuple[Any, list[dict]]],
):
    """Atomically perform a queue load→modify→save cycle.

    Redis-backed instances use a cross-instance lease. Local/polling setups use
    an asyncio lock so concurrent callbacks cannot clobber the in-memory list.
    """
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is None:
        lock = context.application.bot_data.get(QUEUE_MEMORY_LOCK_KEY)
        if lock is None:
            lock = asyncio.Lock()
            context.application.bot_data[QUEUE_MEMORY_LOCK_KEY] = lock
        async with lock:
            jobs = await load_jobs(context)
            result, new_jobs = mutate(jobs)
            await save_jobs(context, new_jobs)
            return result

    lock_owner = await _acquire_lock(kv)
    if lock_owner is None:
        raise QueueBusyError("publish queue is busy")
    try:
        jobs = await load_jobs(context)
        result, new_jobs = mutate(jobs)
        await save_jobs(context, new_jobs)
        return result
    finally:
        await _release_lock(kv, lock_owner)


async def load_jobs(context) -> list[dict]:
    """Load normalized queue jobs from Redis or the local fallback."""
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        jobs = await kv.get_json(QUEUE_KV_KEY)
        if isinstance(jobs, list):
            cleaned = [
                normalized
                for job in jobs
                if isinstance(job, dict)
                if (normalized := _normalize_job(job)) is not None
            ]
            context.application.bot_data[QUEUE_MEMORY_KEY] = cleaned
            return cleaned

    jobs = context.application.bot_data.get(QUEUE_MEMORY_KEY) or []
    return [
        normalized
        for job in jobs
        if isinstance(job, dict)
        if (normalized := _normalize_job(job)) is not None
    ]


async def save_jobs(context, jobs: list[dict]) -> None:
    normalized = [job for job in (_normalize_job(item) for item in jobs) if job]
    context.application.bot_data[QUEUE_MEMORY_KEY] = normalized
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(QUEUE_KV_KEY, normalized)


async def add_job(context, draft: dict, publish_at: int) -> dict:
    job = {
        "id": secrets.token_hex(6),
        "status": JOB_PENDING,
        "publish_at": int(publish_at),
        "created_at": int(time.time()),
        "attempts": 0,
        "draft": draft,
    }

    def mutate(jobs: list[dict]):
        # Never evict an in-flight job when applying the queue cap.
        if len(jobs) >= MAX_QUEUE_JOBS:
            pending = [item for item in jobs if item.get("status") == JOB_PENDING]
            if pending:
                oldest = min(pending, key=lambda item: int(item.get("created_at") or 0))
                jobs = [item for item in jobs if item.get("id") != oldest.get("id")]
            else:
                raise QueueBusyError("all queue slots are processing")
        return job, _sort_jobs([*jobs, job])

    return await _locked_mutate(context, mutate)


async def remove_job(context, job_id: str) -> bool:
    def mutate(jobs: list[dict]):
        remaining = [job for job in jobs if job.get("id") != job_id]
        return len(remaining) != len(jobs), remaining

    return await _locked_mutate(context, mutate)


async def reschedule_job(context, job_id: str, publish_at: int) -> bool:
    def mutate(jobs: list[dict]):
        found = False
        updated: list[dict] = []
        for job in jobs:
            if job.get("id") != job_id:
                updated.append(job)
                continue
            changed = dict(job)
            changed.update(status=JOB_PENDING, publish_at=int(publish_at))
            changed.pop("lease_owner", None)
            changed.pop("lease_until", None)
            updated.append(changed)
            found = True
        return found, _sort_jobs(updated)

    return await _locked_mutate(context, mutate)


async def _claim_due_jobs(context, *, now: int, owner: str) -> list[dict]:
    """Lease due jobs without removing them from durable storage."""

    def mutate(jobs: list[dict]):
        claimed: list[dict] = []
        updated: list[dict] = []
        for job in jobs:
            status = job.get("status") or JOB_PENDING
            due = int(job.get("publish_at") or 0) <= now
            lease_expired = int(job.get("lease_until") or 0) <= now
            claimable = due and (
                status == JOB_PENDING or (status == JOB_PROCESSING and lease_expired)
            )
            if not claimable:
                updated.append(job)
                continue
            leased = dict(job)
            leased.update(
                status=JOB_PROCESSING,
                lease_owner=owner,
                lease_until=now + PROCESSING_LEASE_SECONDS,
            )
            updated.append(leased)
            claimed.append(dict(leased))
        return claimed, updated

    return await _locked_mutate(context, mutate)


async def _finish_job(
    context,
    *,
    job_id: str,
    owner: str,
    delivered: bool,
    now: int,
) -> tuple[str, dict | None]:
    """Commit the result only if this worker still owns the job lease."""

    def mutate(jobs: list[dict]):
        updated: list[dict] = []
        outcome = "stale"
        failed_draft: dict | None = None
        for job in jobs:
            if job.get("id") != job_id or job.get("lease_owner") != owner:
                updated.append(job)
                continue
            if delivered:
                outcome = "published"
                continue

            attempts = int(job.get("attempts") or 0) + 1
            if attempts >= MAX_JOB_ATTEMPTS:
                outcome = "exhausted"
                failed_draft = job.get("draft") if isinstance(job.get("draft"), dict) else None
                continue

            retry = dict(job)
            retry.update(
                status=JOB_PENDING,
                attempts=attempts,
                publish_at=now + RETRY_BACKOFF_SECONDS[
                    min(attempts, len(RETRY_BACKOFF_SECONDS)) - 1
                ],
            )
            retry.pop("lease_owner", None)
            retry.pop("lease_until", None)
            updated.append(retry)
            outcome = "retry"
        return (outcome, failed_draft), _sort_jobs(updated)

    return await _locked_mutate(context, mutate)


async def process_due_jobs(context, *, now: int | None = None) -> int:
    """Lease, publish and finalize every due job.

    A process crash leaves the job in ``processing`` instead of deleting it;
    another worker can safely reclaim it when ``lease_until`` expires.
    """
    from music_links_bot.bot import _publish_draft, _schedule_mark_posted
    from music_links_bot.models import TrackMatch

    now_ts = int(now if now is not None else time.time())
    owner = secrets.token_hex(12)
    try:
        claimed = await _claim_due_jobs(context, now=now_ts, owner=owner)
    except QueueBusyError:
        return 0

    published = 0
    for job in claimed:
        draft = job.get("draft")
        valid = isinstance(draft, dict) and isinstance(draft.get("item"), dict)
        delivered = False
        if valid:
            try:
                delivered = await _publish_draft(context, draft)
            except Exception:
                LOGGER.exception("Scheduled publish crashed for job %s", job.get("id"))

        try:
            outcome, failed_draft = await _finish_job(
                context,
                job_id=str(job.get("id")),
                owner=owner,
                delivered=bool(delivered),
                now=now_ts,
            )
        except QueueBusyError:
            LOGGER.warning("Could not finalize queue job %s; lease will recover it", job.get("id"))
            continue

        if outcome == "published" and valid:
            published += 1
            await _schedule_mark_posted(context, TrackMatch(**draft["item"]))
        elif outcome == "exhausted" and failed_draft is not None:
            await _alert_job_failure(context, failed_draft)

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
