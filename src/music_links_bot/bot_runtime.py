from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from enum import Enum
import secrets
from time import monotonic, time
from typing import Any

from music_links_bot.kvstore import KVStore

CALLBACK_VERSION = "v2"
CALLBACK_TTL_SECONDS = 15 * 60
ACTION_LOCK_SECONDS = 45
SESSION_TTL_SECONDS = 30 * 24 * 3600
MAX_MEMORY_SESSIONS = 500
MAX_MEMORY_KEYS = 2_000


class BotErrorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    SEARCH_NOT_FOUND = "search_not_found"
    RELEASE_NOT_FOUND = "release_not_found"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    DRAFT_EXPIRED = "draft_expired"
    ACTION_BUSY = "action_busy"
    ACTION_DUPLICATE = "action_duplicate"
    PERMISSION_DENIED = "permission_denied"
    DELIVERY_FAILED = "delivery_failed"


class BotFlowError(RuntimeError):
    def __init__(
        self,
        code: BotErrorCode,
        *,
        detail: str = "",
        retryable: bool = False,
        provider: str | None = None,
    ) -> None:
        super().__init__(detail or code.value)
        self.code = code
        self.detail = detail
        self.retryable = retryable
        self.provider = provider


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


@dataclass(slots=True)
class ProviderDiagnostic:
    provider: str
    ok: bool = True
    latency_ms: int = 0
    failures: int = 0
    last_error: str = ""
    checked_at: int = 0


class BotRuntime:
    """Cross-handler state with Redis-backed safety and memory fallback."""

    def __init__(self, kv: KVStore | None = None) -> None:
        self.kv = kv
        self.sessions: dict[int, UserSession] = {}
        self.seen_callbacks: dict[str, float] = {}
        self.action_locks: dict[str, float] = {}
        self.active_tasks: dict[int, asyncio.Task[Any]] = {}
        self.diagnostics: dict[str, ProviderDiagnostic] = {}

    async def get_session(self, user_id: int, *, lang: str = "ru") -> UserSession:
        cached = self.sessions.get(user_id)
        if cached is not None:
            if lang:
                cached.lang = lang
            return cached

        payload = await self.kv.get_json(f"session:v1:{user_id}") if self.kv else None
        session = UserSession.from_dict(payload) if isinstance(payload, dict) else None
        if session is None:
            session = UserSession(user_id=user_id, lang=lang)
        elif lang:
            session.lang = lang
        self._cap(self.sessions, MAX_MEMORY_SESSIONS)
        self.sessions[user_id] = session
        return session

    async def save_session(self, session: UserSession) -> None:
        session.updated_at = int(time())
        self.sessions[session.user_id] = session
        if self.kv is not None:
            await self.kv.set_json(
                f"session:v1:{session.user_id}",
                asdict(session),
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

    def register_request(self, user_id: int) -> asyncio.Task[Any] | None:
        current = asyncio.current_task()
        previous = self.active_tasks.get(user_id)
        if previous is not None and previous is not current and not previous.done():
            previous.cancel()
        if current is not None:
            self.active_tasks[user_id] = current
        return previous

    def finish_request(self, user_id: int) -> None:
        current = asyncio.current_task()
        if self.active_tasks.get(user_id) is current:
            self.active_tasks.pop(user_id, None)

    def record_provider(
        self,
        provider: str,
        *,
        ok: bool,
        latency_ms: int,
        error: BaseException | None = None,
    ) -> None:
        diagnostic = self.diagnostics.setdefault(
            provider, ProviderDiagnostic(provider=provider)
        )
        diagnostic.ok = ok
        diagnostic.latency_ms = max(0, latency_ms)
        diagnostic.checked_at = int(time())
        if ok:
            diagnostic.last_error = ""
        else:
            diagnostic.failures += 1
            diagnostic.last_error = type(error).__name__ if error else "unknown"

    def provider_snapshot(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in sorted(self.diagnostics.values(), key=lambda x: x.provider)]

    @staticmethod
    def _drop_expired(items: dict[str, float], now: float) -> None:
        for key in [key for key, expires_at in items.items() if expires_at <= now]:
            items.pop(key, None)

    @staticmethod
    def _cap(items: dict[Any, Any], max_size: int) -> None:
        while len(items) >= max_size:
            items.pop(next(iter(items)))
