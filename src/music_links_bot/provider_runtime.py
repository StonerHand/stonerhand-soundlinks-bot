from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
import hashlib
import json
import logging
from time import monotonic
from typing import Any

from music_links_bot.cache import TTLCache
from music_links_bot.kvstore import KVStore

LOGGER = logging.getLogger(__name__)
PROVIDER_TIMEOUT_SECONDS = 9.0
REQUEST_BUDGET_SECONDS = 10.0
LOOKUP_CACHE_TTL_SECONDS = 15 * 60
NEGATIVE_LOOKUP_TTL_SECONDS = 3 * 60
_LOOKUP_CACHE: TTLCache[dict[str, Any]] = TTLCache(
    ttl_seconds=LOOKUP_CACHE_TTL_SECONDS,
    max_size=512,
)
_NEGATIVE_LOOKUP_CACHE: TTLCache[dict[str, Any]] = TTLCache(
    ttl_seconds=NEGATIVE_LOOKUP_TTL_SECONDS,
    max_size=512,
)


@dataclass(slots=True)
class ProviderTask:
    name: str
    awaitable: Awaitable[Any]
    fallback: Any


@dataclass(slots=True)
class ProviderOutcome:
    name: str
    value: Any
    ok: bool
    latency_ms: int
    error: str = ""
    circuit_open: bool = False


@dataclass(slots=True)
class RequestBudget:
    """One monotonic deadline shared by every provider in a lookup."""

    deadline: float

    @classmethod
    def start(cls, seconds: float = REQUEST_BUDGET_SECONDS) -> "RequestBudget":
        return cls(deadline=monotonic() + max(0.05, seconds))

    def remaining(self) -> float:
        return max(0.0, self.deadline - monotonic())


async def run_provider_tasks(
    bot_data: dict,
    tasks: list[ProviderTask],
    *,
    timeout_seconds: float = PROVIDER_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run independent providers concurrently and keep successful partial data."""
    outcomes = await run_provider_tasks_detailed(
        bot_data,
        tasks,
        timeout_seconds=timeout_seconds,
    )
    return {name: outcome.value for name, outcome in outcomes.items()}


async def run_provider_tasks_detailed(
    bot_data: dict,
    tasks: list[ProviderTask],
    *,
    timeout_seconds: float = PROVIDER_TIMEOUT_SECONDS,
    budget_seconds: float = REQUEST_BUDGET_SECONDS,
) -> dict[str, ProviderOutcome]:
    """Run providers concurrently within one deadline.

    The return value keeps failure metadata, which lets the bot report the
    status of each submitted link and retry only transient failures.
    """
    budget = RequestBudget.start(budget_seconds)
    runtime = bot_data.get("runtime")

    async def run(task: ProviderTask) -> tuple[str, ProviderOutcome]:
        started = monotonic()
        error: BaseException | None = None
        if (
            runtime is not None
            and hasattr(runtime, "provider_available")
            and not runtime.provider_available(task.name)
        ):
            _close_awaitable(task.awaitable)
            outcome = ProviderOutcome(
                name=task.name,
                value=task.fallback,
                ok=False,
                latency_ms=0,
                error="circuit_open",
                circuit_open=True,
            )
            return task.name, outcome

        try:
            remaining = budget.remaining()
            if remaining <= 0:
                raise TimeoutError("request budget exhausted")
            value = await asyncio.wait_for(
                task.awaitable,
                timeout=min(timeout_seconds, remaining),
            )
        except (Exception, asyncio.CancelledError) as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            error = exc
            value = task.fallback
            LOGGER.warning(
                "Provider %s returned a partial fallback: %s",
                task.name,
                type(exc).__name__,
            )
        if runtime is not None and hasattr(runtime, "record_provider"):
            runtime.record_provider(
                task.name,
                ok=error is None,
                latency_ms=int((monotonic() - started) * 1000),
                error=error,
            )
        latency_ms = int((monotonic() - started) * 1000)
        return task.name, ProviderOutcome(
            name=task.name,
            value=value,
            ok=error is None,
            latency_ms=latency_ms,
            error=type(error).__name__ if error is not None else "",
        )

    pairs = await asyncio.gather(*(run(task) for task in tasks))
    return dict(pairs)


def _close_awaitable(awaitable: Awaitable[Any]) -> None:
    """Avoid an un-awaited coroutine warning when a circuit is already open."""
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()


def lookup_cache_key(source_urls: list[str]) -> str:
    canonical = json.dumps(
        list(dict.fromkeys(source_urls)),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    # Version the aggregate key whenever completeness semantics change so an
    # old partial result cannot look like a complete collection after deploy.
    return "lookup:v3:" + hashlib.sha256(canonical.encode()).hexdigest()


async def get_cached_lookup(bot_data: dict, source_urls: list[str]) -> dict | None:
    key = lookup_cache_key(source_urls)
    cached = _LOOKUP_CACHE.get(key)
    if not isinstance(cached, dict):
        cached = _NEGATIVE_LOOKUP_CACHE.get(key)
    if isinstance(cached, dict):
        _record_cache(bot_data, hit=True)
        return cached

    kv: KVStore | None = bot_data.get("kv_store")
    cached = await kv.get_json(key) if kv is not None else None
    if isinstance(cached, dict):
        cache = _NEGATIVE_LOOKUP_CACHE if cached.get("_negative") else _LOOKUP_CACHE
        cache.set(key, cached)
        _record_cache(bot_data, hit=True)
        return cached
    _record_cache(bot_data, hit=False)
    return None


async def set_cached_lookup(
    bot_data: dict,
    source_urls: list[str],
    payload: dict[str, Any],
) -> None:
    key = lookup_cache_key(source_urls)
    _LOOKUP_CACHE.set(key, payload)
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(key, payload, ttl_seconds=LOOKUP_CACHE_TTL_SECONDS)


async def set_cached_negative_lookup(
    bot_data: dict,
    source_urls: list[str],
    payload: dict[str, Any],
) -> None:
    key = lookup_cache_key(source_urls)
    cached = {**payload, "_negative": True}
    _NEGATIVE_LOOKUP_CACHE.set(key, cached)
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(key, cached, ttl_seconds=NEGATIVE_LOOKUP_TTL_SECONDS)


def _record_cache(bot_data: dict, *, hit: bool) -> None:
    runtime = bot_data.get("runtime")
    if runtime is not None and hasattr(runtime, "record_cache"):
        runtime.record_cache(hit=hit)
