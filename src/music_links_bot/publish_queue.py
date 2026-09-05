from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Callable
from typing import Any

from music_links_bot.draft_model import prepare_publication_draft
from music_links_bot.kvstore import KVStore, KVUnavailableError

LOGGER = logging.getLogger(__name__)

QUEUE_KV_KEY = "queue:v1"
QUEUE_TICK_KV_KEY = "queue:last-tick:v1"
QUEUE_LOCK_KEY = "queue:lock"
QUEUE_LOCK_TTL_SECONDS = 30
QUEUE_MEMORY_KEY = "publish_queue"
QUEUE_MEMORY_LOCK_KEY = "publish_queue_lock"
MAX_QUEUE_JOBS = 50
MAX_JOB_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (120, 600, 1800)
PROCESSING_LEASE_SECONDS = 90
MAX_JOBS_PER_TICK = 3
JOB_PENDING = "pending"
JOB_PROCESSING = "processing"
JOB_DELIVERING = "delivering"
JOB_UNCERTAIN = "uncertain"


class QueueBusyError(RuntimeError):
    """Raised when a concurrent queue mutation still owns the Redis lease."""


class QueueFullError(QueueBusyError):
    """Raised instead of silently evicting an existing scheduled post."""


class QueueStorageError(RuntimeError):
    """Raised when a durable queue read or write cannot be confirmed."""


async def _acquire_lock(
    kv: KVStore, *, tries: int = 6, delay: float = 0.15
) -> str | None:
    owner = secrets.token_hex(12)
    setter = getattr(kv, "set_required", None)
    if setter is None:
        setter = kv.set
    for attempt in range(tries):
        if await setter(
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
    if normalized.get("status") not in {
        JOB_PENDING,
        JOB_PROCESSING,
        JOB_DELIVERING,
        JOB_UNCERTAIN,
    }:
        normalized["status"] = JOB_PENDING
    if normalized["status"] == JOB_PENDING:
        normalized.pop("lease_owner", None)
        normalized.pop("lease_until", None)
        normalized.pop("delivery_started_at", None)
        normalized.pop("uncertain_at", None)
    return normalized


def _sort_jobs(jobs: list[dict]) -> list[dict]:
    return sorted(jobs, key=lambda item: int(item.get("publish_at") or 0))


def _draft_chat_id(job: dict) -> int | None:
    draft = job.get("draft")
    if not isinstance(draft, dict):
        return None
    try:
        return int(draft.get("chat_id"))
    except (TypeError, ValueError):
        return None


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

    try:
        lock_owner = await _acquire_lock(kv)
    except KVUnavailableError as exc:
        raise QueueStorageError("publish queue storage is unavailable") from exc
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
        try:
            required_get = getattr(kv, "get_json_required", None)
            jobs = (
                await required_get(QUEUE_KV_KEY)
                if required_get is not None
                else await kv.get_json(QUEUE_KV_KEY)
            )
        except KVUnavailableError as exc:
            raise QueueStorageError("could not read the publish queue") from exc
        if isinstance(jobs, list):
            cleaned = [
                normalized
                for job in jobs
                if isinstance(job, dict)
                if (normalized := _normalize_job(job)) is not None
            ]
            context.application.bot_data[QUEUE_MEMORY_KEY] = cleaned
            return cleaned
        if jobs is None:
            context.application.bot_data[QUEUE_MEMORY_KEY] = []
            return []
        if jobs is not None:
            raise QueueStorageError("publish queue data is malformed")

    jobs = context.application.bot_data.get(QUEUE_MEMORY_KEY) or []
    return [
        normalized
        for job in jobs
        if isinstance(job, dict)
        if (normalized := _normalize_job(job)) is not None
    ]


async def save_jobs(context, jobs: list[dict]) -> None:
    normalized = [job for job in (_normalize_job(item) for item in jobs) if job]
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        try:
            required_set = getattr(kv, "set_json_required", None)
            if required_set is not None:
                await required_set(QUEUE_KV_KEY, normalized)
            elif not await kv.set_json(QUEUE_KV_KEY, normalized):
                raise KVUnavailableError("Redis did not confirm the write")
        except KVUnavailableError as exc:
            raise QueueStorageError("could not save the publish queue") from exc
    context.application.bot_data[QUEUE_MEMORY_KEY] = normalized


async def add_job(context, draft: dict, publish_at: int) -> dict:
    prepared = prepare_publication_draft(draft)
    if prepared is None:
        raise ValueError("invalid publication draft")
    job = {
        "id": secrets.token_hex(6),
        "status": JOB_PENDING,
        "publish_at": int(publish_at),
        "created_at": int(time.time()),
        "attempts": 0,
        "draft": prepared.data,
    }

    def mutate(jobs: list[dict]):
        if len(jobs) >= MAX_QUEUE_JOBS:
            # A full queue must be visible to the user. Silently deleting the
            # oldest scheduled publication is data loss, even if it is pending.
            raise QueueFullError("publish queue is full")
        return job, _sort_jobs([*jobs, job])

    return await _locked_mutate(context, mutate)


async def remove_job(context, job_id: str) -> bool:
    def mutate(jobs: list[dict]):
        if any(
            job.get("id") == job_id
            and job.get("status") in {JOB_PROCESSING, JOB_DELIVERING}
            for job in jobs
        ):
            raise QueueBusyError("Publication is already being sent")
        remaining = [job for job in jobs if job.get("id") != job_id]
        return len(remaining) != len(jobs), remaining

    return await _locked_mutate(context, mutate)


async def remove_user_jobs(context, user_id: int) -> int:
    """Delete scheduled drafts created in the user's private chat."""

    def mutate(jobs: list[dict]):
        if any(
            job.get("status") in {JOB_PROCESSING, JOB_DELIVERING}
            and _draft_chat_id(job) == user_id
            for job in jobs
        ):
            # Never report an already-running publication as deleted. The
            # privacy flow can retry once delivery reaches a durable state.
            raise QueueBusyError("A user publication is already being sent")
        remaining: list[dict] = []
        removed = 0
        for job in jobs:
            if _draft_chat_id(job) == user_id:
                removed += 1
            else:
                remaining.append(job)
        return removed, remaining

    return await _locked_mutate(context, mutate)


async def reschedule_job(
    context, job_id: str, publish_at: int, *, only_uncertain: bool = False
) -> bool:
    def mutate(jobs: list[dict]):
        found = False
        updated: list[dict] = []
        for job in jobs:
            if (
                job.get("id") != job_id
                or job.get("status") in {JOB_PROCESSING, JOB_DELIVERING}
                or (only_uncertain and job.get("status") != JOB_UNCERTAIN)
            ):
                updated.append(job)
                continue
            changed = dict(job)
            changed.update(status=JOB_PENDING, publish_at=int(publish_at))
            changed.pop("lease_owner", None)
            changed.pop("lease_until", None)
            changed.pop("delivery_started_at", None)
            changed.pop("uncertain_at", None)
            updated.append(changed)
            found = True
        return found, _sort_jobs(updated)

    return await _locked_mutate(context, mutate)


async def _mark_delivery_started(
    context,
    *,
    job_id: str,
    owner: str,
    now: int,
) -> bool:
    """Durably cross the point after which an automatic retry is unsafe."""

    def mutate(jobs: list[dict]):
        started = False
        updated: list[dict] = []
        for job in jobs:
            if (
                job.get("id") == job_id
                and job.get("lease_owner") == owner
                and job.get("status") == JOB_PROCESSING
            ):
                changed = dict(job)
                changed.update(
                    status=JOB_DELIVERING,
                    delivery_started_at=now,
                )
                updated.append(changed)
                started = True
            else:
                updated.append(job)
        return started, updated

    return await _locked_mutate(context, mutate)


async def _recover_uncertain_jobs(context, *, now: int) -> list[dict]:
    """Quarantine expired in-flight deliveries instead of sending them twice."""

    def mutate(jobs: list[dict]):
        recovered: list[dict] = []
        updated: list[dict] = []
        for job in jobs:
            lease_expired = int(job.get("lease_until") or 0) <= now
            if job.get("status") != JOB_DELIVERING or not lease_expired:
                updated.append(job)
                continue
            changed = dict(job)
            changed.update(status=JOB_UNCERTAIN, uncertain_at=now)
            changed.pop("lease_owner", None)
            changed.pop("lease_until", None)
            updated.append(changed)
            recovered.append(changed)
        return recovered, updated

    return await _locked_mutate(context, mutate)


async def _claim_due_jobs(
    context,
    *,
    now: int,
    owner: str,
    limit: int = 1,
) -> list[dict]:
    """Lease a bounded number of due jobs without removing them."""

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
            if not claimable or len(claimed) >= max(1, limit):
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
    confirmed_not_sent: bool = False,
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

            if job.get("status") == JOB_DELIVERING and not confirmed_not_sent:
                uncertain = dict(job)
                uncertain.update(status=JOB_UNCERTAIN, uncertain_at=now)
                uncertain.pop("lease_owner", None)
                uncertain.pop("lease_until", None)
                updated.append(uncertain)
                outcome = "uncertain"
                failed_draft = (
                    job.get("draft") if isinstance(job.get("draft"), dict) else None
                )
                continue

            attempts = int(job.get("attempts") or 0) + 1
            if attempts >= MAX_JOB_ATTEMPTS:
                outcome = "exhausted"
                failed_draft = (
                    job.get("draft") if isinstance(job.get("draft"), dict) else None
                )
                continue

            retry = dict(job)
            retry.update(
                status=JOB_PENDING,
                attempts=attempts,
                publish_at=now
                + RETRY_BACKOFF_SECONDS[min(attempts, len(RETRY_BACKOFF_SECONDS)) - 1],
            )
            retry.pop("lease_owner", None)
            retry.pop("lease_until", None)
            updated.append(retry)
            outcome = "retry"
        return (outcome, failed_draft), _sort_jobs(updated)

    return await _locked_mutate(context, mutate)


async def process_due_jobs(context, *, now: int | None = None) -> int:
    """Lease, publish and finalize every due job.

    A crash before delivery starts leaves a reclaimable ``processing`` lease.
    Once a Telegram request starts, an expired job is quarantined as
    ``uncertain`` and requires an explicit administrator retry, preventing a
    blind duplicate when Telegram accepted a request before the worker died.
    """
    from music_links_bot.publication_service import PublicationService
    from music_links_bot.publication_state import mark_posted

    fixed_now = int(now) if now is not None else None

    def current_time() -> int:
        return fixed_now if fixed_now is not None else int(time.time())

    started_at = current_time()
    kv = context.application.bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(
            QUEUE_TICK_KV_KEY, {"started_at": started_at}, ttl_seconds=86400
        )
    owner = secrets.token_hex(12)
    published = 0
    try:
        recovered = await _recover_uncertain_jobs(context, now=started_at)
    except (QueueBusyError, QueueStorageError):
        recovered = []
    for job in recovered:
        await _alert_uncertain_job(context, job.get("draft"))
    for _ in range(MAX_JOBS_PER_TICK):
        try:
            claimed = await _claim_due_jobs(
                context,
                now=current_time(),
                owner=owner,
                limit=1,
            )
        except (QueueBusyError, QueueStorageError):
            break
        if not claimed:
            break
        job = claimed[0]
        draft = job.get("draft")
        prepared = prepare_publication_draft(draft)
        valid = prepared is not None
        delivered = None
        service = None
        if prepared is not None:
            draft = prepared.data
            try:
                started = await _mark_delivery_started(
                    context,
                    job_id=str(job.get("id")),
                    owner=owner,
                    now=current_time(),
                )
                if started:
                    service = PublicationService(
                        context,
                        channel_username="stonerhand",
                    )
                    delivered = await service.publish(draft, notify_failure=False)
            except Exception:
                LOGGER.exception("Scheduled publish crashed for job %s", job.get("id"))

        try:
            outcome, failed_draft = await _finish_job(
                context,
                job_id=str(job.get("id")),
                owner=owner,
                delivered=bool(delivered),
                now=current_time(),
                confirmed_not_sent=service is not None and service.confirmed_not_sent,
            )
        except (QueueBusyError, QueueStorageError):
            LOGGER.warning(
                "Could not finalize queue job %s; lease will recover it", job.get("id")
            )
            continue

        if outcome == "published" and valid:
            published += 1
            target = (
                context.application.bot_data.get("publish_chat_id") or "@stonerhand"
            )
            await mark_posted(
                context,
                prepared.track,
                message=delivered,
                target=target,
            )
        elif outcome == "exhausted" and failed_draft is not None:
            await _alert_job_failure(context, failed_draft)
        elif outcome == "uncertain":
            await _alert_uncertain_job(context, failed_draft)

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


async def _alert_uncertain_job(context, draft: object) -> None:
    """Surface an ambiguous Telegram outcome without risking an automatic duplicate."""
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    if not admin_chat_id:
        return
    item = draft.get("item") if isinstance(draft, dict) else None
    item = item if isinstance(item, dict) else {}
    label = f"{item.get('artist') or '?'} — {item.get('title') or '?'}"
    try:
        await context.bot.send_message(
            chat_id=admin_chat_id,
            text=(
                "⚠️ Не удалось подтвердить результат отложенной публикации: "
                f"{label}. Автоповтор остановлен, чтобы не создать дубль. "
                "Проверь канал и повтори задачу вручную в очереди, если поста нет."
            ),
        )
    except Exception:
        LOGGER.debug("Uncertain queue alert failed", exc_info=True)
