from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from dataclasses import asdict, dataclass, field
from math import ceil
from time import monotonic, time
from typing import Any

from music_links_bot.errors import (
    BotErrorCode as _BotErrorCode,
    BotFlowError as _BotFlowError,
)
from music_links_bot.kvstore import KVStore

# Backwards-compatible exports for existing imports and callbacks.
BotErrorCode = _BotErrorCode
BotFlowError = _BotFlowError

CALLBACK_VERSION = "v2"
CALLBACK_TTL_SECONDS = 15 * 60
ACTION_LOCK_SECONDS = 45
INTENT_TTL_SECONDS = 4
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 12
ACTIVE_REQUEST_TTL_SECONDS = 5 * 60
SESSION_TTL_SECONDS = 30 * 24 * 3600
SESSION_SCHEMA_VERSION = 4
MAX_MEMORY_SESSIONS = 500
MAX_MEMORY_KEYS = 2_000
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_SECONDS = 45
METRICS_KV_KEY = "runtime:metrics:v1"
REQUEST_LATENCY_BUCKETS_MS = (250, 500, 1_000, 2_000, 5_000, 10_000, 20_000)
LOGGER = logging.getLogger(__name__)


def detect_action(text: str, source_urls: list[str], *, is_private: bool) -> str:
    """Classify a free-form update before dispatching expensive work."""
    normalized = " ".join(text.casefold().split())
    if len(source_urls) > 1:
        return "crate"
    if source_urls:
        return "resolve"
    if is_private and normalized in {"помощь", "help", "что ты умеешь", "меню"}:
        return "help"
    return "search" if is_private and normalized else "ignore"


@dataclass(slots=True, frozen=True)
class CallbackAction:
    scope: str
    action: str
    payload: str = ""
    version: str = CALLBACK_VERSION


def encode_callback(scope: str, action: str, payload: str = "") -> str:
    parts = (CALLBACK_VERSION, scope, action, payload)
    value = "|".join(parts).rstrip("|")
    if len(value.encode("utf-8")) > 64:
        raise ValueError("Telegram callback_data exceeds 64 bytes")
    return value


def decode_callback(value: str | None) -> CallbackAction | None:
    if not value:
        return None

    parts = value.split("|")
    if len(parts) >= 3 and parts[0] == CALLBACK_VERSION:
        return CallbackAction(
            scope=parts[1],
            action=parts[2],
            payload="|".join(parts[3:]),
        )

    # Compatibility with buttons sent before callback v2 was deployed.
    if len(parts) == 3 and parts[0] == "ed":
        return CallbackAction("editor", parts[1], parts[2], version="v1")
    if value.startswith("menu:"):
        return CallbackAction("menu", value.split(":", 1)[1], version="v1")
    return None


@dataclass(slots=True)
class UserSession:
    user_id: int
    lang: str = "ru"
    onboarding_seen: bool = False
    last_query: str = ""
    last_action: dict[str, Any] = field(default_factory=dict)
    pending_input: dict[str, Any] = field(default_factory=dict)
    active_draft_id: str = ""
    recent_draft_ids: list[str] = field(default_factory=list)
    home_chat_id: int | None = None
    home_message_id: int | None = None
    updated_at: int = field(default_factory=lambda: int(time()))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> UserSession | None:
        try:
            return cls(
                user_id=int(payload["user_id"]),
                lang=str(payload.get("lang") or "ru"),
                onboarding_seen=bool(payload.get("onboarding_seen")),
                last_query=str(payload.get("last_query") or "")[:500],
                last_action=(
                    dict(payload["last_action"])
                    if isinstance(payload.get("last_action"), dict)
                    else {}
                ),
                pending_input=_normalize_pending_input(payload.get("pending_input")),
                active_draft_id=str(payload.get("active_draft_id") or "")[:32],
                recent_draft_ids=[
                    str(value)[:32]
                    for value in (
                        payload.get("recent_draft_ids")
                        if isinstance(payload.get("recent_draft_ids"), list)
                        else []
                    )[:5]
                    if value
                ],
                home_chat_id=_optional_int(payload.get("home_chat_id")),
                home_message_id=_optional_int(payload.get("home_message_id")),
                updated_at=int(payload.get("updated_at") or time()),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _normalize_pending_input(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    kind = str(value.get("kind") or "")
    if kind not in {
        "intro",
        "hashtags",
        "crate_title",
        "schedule",
        "replace_source",
        "cover",
        "template_name",
    }:
        return {}
    result: dict[str, Any] = {"kind": kind}
    draft_id = str(value.get("draft_id") or "")[:32]
    if draft_id:
        result["draft_id"] = draft_id
    for key in (
        "editor_chat_id",
        "editor_message_id",
        "prompt_message_id",
        "created_at",
    ):
        parsed = _optional_int(value.get(key))
        if parsed is not None:
            result[key] = parsed
    if kind == "replace_source":
        retry_id = str(value.get("retry_id") or "")[:64]
        source_index = _optional_int(value.get("source_index"))
        if retry_id:
            result["retry_id"] = retry_id
        if source_index is not None:
            result["source_index"] = source_index
    return result


@dataclass(slots=True)
class ProviderDiagnostic:
    provider: str
    ok: bool = True
    latency_ms: int = 0
    failures: int = 0
    successes: int = 0
    total_latency_ms: int = 0
    partials: int = 0
    timeouts: int = 0
    rate_limits: int = 0
    consecutive_failures: int = 0
    circuit_open_until: int = 0
    last_error: str = ""
    checked_at: int = 0


class BotRuntime:
    """Cross-handler state with Redis-backed safety and memory fallback."""

    def __init__(self, kv: KVStore | None = None) -> None:
        self.kv = kv
        self.sessions: dict[int, UserSession] = {}
        self.seen_callbacks: dict[str, float] = {}
        self.action_locks: dict[str, float] = {}
        self.recent_intents: dict[str, float] = {}
        self.request_windows: dict[int, tuple[int, float]] = {}
        self.request_tokens: dict[int, str] = {}
        self.active_tasks: dict[int, asyncio.Task[Any]] = {}
        self.diagnostics: dict[str, ProviderDiagnostic] = {}
        self.request_latency_buckets = dict.fromkeys(REQUEST_LATENCY_BUCKETS_MS, 0)
        self.request_latency_overflow = 0
        self.metrics: dict[str, int] = {
            "requests": 0,
            "request_errors": 0,
            "request_ms_total": 0,
            "request_ms_max": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "publications": 0,
            "publication_errors": 0,
            "rich_messages": 0,
            "rich_message_errors": 0,
            "rich_message_fallbacks": 0,
            "rate_limited": 0,
            "funnel_started": 0,
            "funnel_resolved": 0,
            "funnel_edited": 0,
            "funnel_published": 0,
        }
        self._metrics_persisted_at = 0.0

    async def get_session(self, user_id: int, *, lang: str = "ru") -> UserSession:
        cached = self.sessions.get(user_id)
        if cached is not None:
            if lang:
                cached.lang = lang
            return cached

        payload = None
        legacy_payload = None
        if self.kv is not None:
            current_key = f"session:v2:{user_id}"
            legacy_key = f"session:v1:{user_id}"
            batch_reader = getattr(self.kv, "mget_json", None)
            if callable(batch_reader):
                values = await batch_reader([current_key, legacy_key])
                if isinstance(values, list) and len(values) == 2:
                    payload, legacy_payload = values
                else:
                    payload = await self.kv.get_json(current_key)
                    legacy_payload = await self.kv.get_json(legacy_key)
            else:
                # Compatibility with lightweight storage adapters and old
                # workers during a rolling deployment.
                payload = await self.kv.get_json(current_key)
                if payload is None:
                    legacy_payload = await self.kv.get_json(legacy_key)
        if isinstance(payload, dict) and isinstance(payload.get("session"), dict):
            payload = payload["session"]
        migrated = False
        if payload is None:
            payload = legacy_payload
            migrated = isinstance(payload, dict)
        session = UserSession.from_dict(payload) if isinstance(payload, dict) else None
        if session is None:
            session = UserSession(user_id=user_id, lang=lang)
        elif lang:
            session.lang = lang
        self._cap(self.sessions, MAX_MEMORY_SESSIONS)
        self.sessions[user_id] = session
        if migrated:
            await self.save_session(session)
        return session

    async def save_session(self, session: UserSession) -> None:
        session.updated_at = int(time())
        self.sessions[session.user_id] = session
        if self.kv is not None:
            await self.kv.set_json(
                f"session:v2:{session.user_id}",
                {"v": SESSION_SCHEMA_VERSION, "session": asdict(session)},
                ttl_seconds=SESSION_TTL_SECONDS,
            )

    async def remember_action(
        self, user_id: int, *, kind: str, value: str, lang: str = "ru"
    ) -> None:
        session = await self.get_session(user_id, lang=lang)
        session.last_action = {"kind": kind, "value": value[:500]}
        if kind == "search":
            session.last_query = value[:500]
        await self.save_session(session)

    async def claim_callback(self, callback_id: str) -> bool:
        key = f"callback:v2:{callback_id}"
        if self.kv is not None:
            claimed = await self.kv.set(
                key, "1", ttl_seconds=CALLBACK_TTL_SECONDS, nx=True
            )
            if claimed:
                return True
            if await self.kv.get(key) is not None:
                return False
            # Redis is unavailable rather than occupied; memory fallback keeps
            # the current instance useful without weakening a live lease.
        now = monotonic()
        self._drop_expired(self.seen_callbacks, now)
        if callback_id in self.seen_callbacks:
            return False
        self._cap(self.seen_callbacks, MAX_MEMORY_KEYS)
        self.seen_callbacks[callback_id] = now + CALLBACK_TTL_SECONDS
        return True

    async def acquire_action(self, key: str) -> str | None:
        token = secrets.token_hex(8)
        redis_key = f"action:v1:{key}"
        if self.kv is not None:
            if await self.kv.set(
                redis_key, token, ttl_seconds=ACTION_LOCK_SECONDS, nx=True
            ):
                return token
            if await self.kv.get(redis_key) is not None:
                return None
        now = monotonic()
        self._drop_expired(self.action_locks, now)
        if key in self.action_locks:
            return None
        self._cap(self.action_locks, MAX_MEMORY_KEYS)
        self.action_locks[key] = now + ACTION_LOCK_SECONDS
        return token

    async def release_action(self, key: str, token: str) -> None:
        self.action_locks.pop(key, None)
        if self.kv is not None:
            await self.kv.delete_if_value(f"action:v1:{key}", token)

    async def claim_intent(
        self,
        user_id: int,
        *,
        kind: str,
        value: str = "",
        ttl_seconds: int = INTENT_TTL_SECONDS,
    ) -> bool:
        """Debounce equal user intents across warm instances and Redis.

        Telegram creates a new update for every tap or sent message, so update
        ID deduplication alone cannot stop an accidental double ``/start`` or
        two identical lookups. Distinct requests are never blocked.
        """
        normalized = " ".join(value.casefold().split())[:1_000]
        digest = hashlib.sha256(f"{kind}:{normalized}".encode()).hexdigest()[:24]
        key = f"{user_id}:{digest}"
        redis_key = f"intent:v1:{key}"
        ttl = max(1, int(ttl_seconds))
        now = monotonic()
        self._drop_expired(self.recent_intents, now)
        if self.kv is not None:
            if await self.kv.set(redis_key, "1", ttl_seconds=ttl, nx=True):
                self._cap(self.recent_intents, MAX_MEMORY_KEYS)
                self.recent_intents[key] = now + ttl
                return True
            if await self.kv.get(redis_key) is not None:
                return False

        if key in self.recent_intents:
            return False
        self._cap(self.recent_intents, MAX_MEMORY_KEYS)
        self.recent_intents[key] = now + ttl
        return True

    async def allow_user_request(
        self,
        user_id: int,
        *,
        max_requests: int = RATE_LIMIT_MAX_REQUESTS,
        window_seconds: int = RATE_LIMIT_WINDOW_SECONDS,
    ) -> tuple[bool, int]:
        """Apply a small per-user fixed window without storing request content."""
        limit = max(1, int(max_requests))
        window = max(1, int(window_seconds))
        wall_now = int(time())
        retry_after = window - wall_now % window
        if self.kv is not None:
            counter = await self.kv.increment_window(
                f"rate:v1:{user_id}:{wall_now // window}",
                ttl_seconds=window + 1,
            )
            if counter is not None:
                allowed = counter <= limit
                if not allowed:
                    self.metrics["rate_limited"] += 1
                return allowed, retry_after

        now = monotonic()
        count, expires_at = self.request_windows.get(user_id, (0, now + window))
        if expires_at <= now:
            count, expires_at = 0, now + window
        count += 1
        self._cap(self.request_windows, MAX_MEMORY_SESSIONS)
        self.request_windows[user_id] = (count, expires_at)
        allowed = count <= limit
        if not allowed:
            self.metrics["rate_limited"] += 1
        return allowed, max(1, int(expires_at - now))

    def register_request(self, user_id: int) -> asyncio.Task[Any] | None:
        current = asyncio.current_task()
        previous = self.active_tasks.get(user_id)
        if previous is not None and previous is not current and not previous.done():
            previous.cancel()
        if current is not None:
            self.active_tasks[user_id] = current
        return previous

    async def begin_request(self, user_id: int) -> str:
        """Register a lookup and make it the only current cross-instance request."""
        self.register_request(user_id)
        token = secrets.token_hex(12)
        self.request_tokens[user_id] = token
        if self.kv is not None:
            await self.kv.set(
                f"active-request:v1:{user_id}",
                token,
                ttl_seconds=ACTIVE_REQUEST_TTL_SECONDS,
            )
        return token

    async def request_is_current(self, user_id: int, token: str) -> bool:
        if self.kv is not None:
            stored = await self.kv.get(f"active-request:v1:{user_id}")
            if stored is not None:
                return stored == token
        return self.request_tokens.get(user_id) == token

    def finish_request(self, user_id: int) -> None:
        current = asyncio.current_task()
        if self.active_tasks.get(user_id) is current:
            self.active_tasks.pop(user_id, None)

    def cancel_request(self, user_id: int) -> bool:
        task = self.active_tasks.get(user_id)
        if task is None or task is asyncio.current_task() or task.done():
            return False
        task.cancel()
        return True

    async def cancel_request_durable(self, user_id: int) -> bool:
        cancelled = self.cancel_request(user_id)
        if self.kv is None:
            return cancelled
        key = f"active-request:v1:{user_id}"
        active = await self.kv.get(key)
        if active is None:
            return cancelled
        marked = await self.kv.set(
            key,
            f"cancelled:{secrets.token_hex(6)}",
            ttl_seconds=ACTIVE_REQUEST_TTL_SECONDS,
        )
        return cancelled or marked

    async def finish_request_durable(self, user_id: int) -> None:
        current = asyncio.current_task()
        if self.active_tasks.get(user_id) is not current:
            return
        token = self.request_tokens.pop(user_id, "")
        self.finish_request(user_id)
        if token and self.kv is not None:
            await self.kv.delete_if_value(f"active-request:v1:{user_id}", token)

    async def forget_session(self, user_id: int) -> None:
        task = self.active_tasks.get(user_id)
        current = asyncio.current_task()
        if task is not None and task is not current and not task.done():
            task.cancel()
        self.sessions.pop(user_id, None)
        self.request_windows.pop(user_id, None)
        self.request_tokens.pop(user_id, None)
        self.active_tasks.pop(user_id, None)
        if self.kv is not None:
            wall_window = int(time()) // RATE_LIMIT_WINDOW_SECONDS
            await asyncio.gather(
                self.kv.delete(f"session:v2:{user_id}"),
                self.kv.delete(f"session:v1:{user_id}"),
                self.kv.delete(f"rate:v1:{user_id}:{wall_window}"),
                self.kv.delete(f"rate:v1:{user_id}:{wall_window - 1}"),
                self.kv.delete(f"active-request:v1:{user_id}"),
            )

    def record_provider(
        self,
        provider: str,
        *,
        ok: bool,
        latency_ms: int,
        error: BaseException | None = None,
        partial: bool = False,
    ) -> None:
        diagnostic = self.diagnostics.setdefault(
            provider, ProviderDiagnostic(provider=provider)
        )
        diagnostic.ok = ok
        diagnostic.latency_ms = max(0, latency_ms)
        diagnostic.total_latency_ms += diagnostic.latency_ms
        diagnostic.checked_at = int(time())
        error_name = type(error).__name__ if error else ""
        error_key = f"{error_name} {error or ''}".casefold()
        if partial:
            diagnostic.partials += 1
        if "timeout" in error_key:
            diagnostic.timeouts += 1
        if (
            "ratelimit" in error_key
            or "too many requests" in error_key
            or "429" in error_key
        ):
            diagnostic.rate_limits += 1
        if ok:
            diagnostic.successes += 1
            diagnostic.consecutive_failures = 0
            diagnostic.circuit_open_until = 0
            diagnostic.last_error = ""
        else:
            diagnostic.failures += 1
            diagnostic.consecutive_failures += 1
            diagnostic.last_error = error_name or "unknown"
            if diagnostic.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
                diagnostic.circuit_open_until = (
                    diagnostic.checked_at + CIRCUIT_COOLDOWN_SECONDS
                )

    def provider_available(self, provider: str, *, now: int | None = None) -> bool:
        diagnostic = self.diagnostics.get(provider)
        if diagnostic is None:
            return True
        current = int(time()) if now is None else now
        return diagnostic.circuit_open_until <= current

    def provider_snapshot(self) -> list[dict[str, Any]]:
        current = int(time())
        snapshot: list[dict[str, Any]] = []
        for item in sorted(self.diagnostics.values(), key=lambda value: value.provider):
            payload = asdict(item)
            payload["circuit_open"] = item.circuit_open_until > current
            requests = item.successes + item.failures
            payload["requests"] = requests
            payload["avg_latency_ms"] = (
                item.total_latency_ms // requests if requests else 0
            )
            payload["success_rate_percent"] = (
                round(item.successes * 100 / requests, 1) if requests else 0.0
            )
            snapshot.append(payload)
        return snapshot

    def record_cache(self, *, hit: bool) -> None:
        self.metrics["cache_hits" if hit else "cache_misses"] += 1

    def record_request(self, *, latency_ms: int, ok: bool) -> None:
        latency = max(0, int(latency_ms))
        self.metrics["requests"] += 1
        self.metrics["request_ms_total"] += latency
        self.metrics["request_ms_max"] = max(
            self.metrics["request_ms_max"],
            latency,
        )
        for upper_bound in REQUEST_LATENCY_BUCKETS_MS:
            if latency <= upper_bound:
                self.request_latency_buckets[upper_bound] += 1
                break
        else:
            self.request_latency_overflow += 1
        if not ok:
            self.metrics["request_errors"] += 1

    def record_publication(self, *, ok: bool) -> None:
        self.metrics["publications"] += 1
        if not ok:
            self.metrics["publication_errors"] += 1
        else:
            self.record_funnel("published")

    def record_funnel(self, stage: str) -> None:
        key = f"funnel_{stage}"
        if key in self.metrics:
            self.metrics[key] += 1

    def record_rich_message(self, *, ok: bool, fallback: bool = False) -> None:
        """Record Rich Message delivery and automatic classic fallback."""
        self.metrics["rich_messages"] += 1
        if not ok:
            self.metrics["rich_message_errors"] += 1
        if fallback:
            self.metrics["rich_message_fallbacks"] += 1

    def metrics_snapshot(self) -> dict[str, Any]:
        snapshot = dict(self.metrics)
        requests = snapshot["requests"]
        snapshot["request_ms_avg"] = (
            snapshot["request_ms_total"] // requests if requests else 0
        )
        target = ceil(requests * 0.95)
        seen = 0
        p95 = 0
        for upper_bound in REQUEST_LATENCY_BUCKETS_MS:
            seen += self.request_latency_buckets[upper_bound]
            if target and seen >= target:
                p95 = upper_bound
                break
        if target and not p95:
            p95 = snapshot["request_ms_max"]
        snapshot["request_ms_p95"] = p95
        snapshot["request_latency_overflow"] = self.request_latency_overflow
        cache_requests = snapshot["cache_hits"] + snapshot["cache_misses"]
        snapshot["cache_hit_rate_percent"] = (
            round(snapshot["cache_hits"] * 100 / cache_requests, 1)
            if cache_requests
            else 0.0
        )
        snapshot["updated_at"] = int(time())
        snapshot["providers"] = {
            item["provider"]: {
                "requests": item["requests"],
                "success_rate_percent": item["success_rate_percent"],
                "avg_latency_ms": item["avg_latency_ms"],
                "partials": item["partials"],
                "timeouts": item["timeouts"],
                "rate_limits": item["rate_limits"],
                "consecutive_failures": item["consecutive_failures"],
                "circuit_open": item["circuit_open"],
                "last_error": item["last_error"],
                "checked_at": item["checked_at"],
            }
            for item in self.provider_snapshot()
        }
        return snapshot

    async def persist_metrics(self) -> None:
        now = monotonic()
        if self.kv is None or now - self._metrics_persisted_at < 30:
            return
        self._metrics_persisted_at = now
        try:
            await asyncio.wait_for(
                self.kv.set_json(
                    METRICS_KV_KEY,
                    self.metrics_snapshot(),
                    ttl_seconds=7 * 24 * 3600,
                ),
                timeout=0.35,
            )
        except Exception:
            # Metrics must never add visible latency to a user request.
            LOGGER.debug("Could not persist runtime metrics", exc_info=True)

    @staticmethod
    def _drop_expired(items: dict[str, float], now: float) -> None:
        for key in [key for key, expires_at in items.items() if expires_at <= now]:
            items.pop(key, None)

    @staticmethod
    def _cap(items: dict[Any, Any], max_size: int) -> None:
        while len(items) >= max_size:
            items.pop(next(iter(items)))
