from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class _CacheEntry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    """Small in-memory cache for external metadata lookups."""

    def __init__(self, *, ttl_seconds: float = 3600.0, max_size: int = 512) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_size = max(1, max_size)
        self._items: dict[str, _CacheEntry[T]] = {}

    def get(self, key: str) -> T | None:
        entry = self._items.get(key)
        if entry is None:
            return None

        if entry.expires_at <= monotonic():
            self._items.pop(key, None)
            return None

        return entry.value

    def set(self, key: str, value: T) -> None:
        self._drop_expired()
        while len(self._items) >= self._max_size:
            self._items.pop(next(iter(self._items)))

        self._items[key] = _CacheEntry(
            value=value,
            expires_at=monotonic() + self._ttl_seconds,
        )

    def _drop_expired(self) -> None:
        now = monotonic()
        expired_keys = [
            key for key, entry in self._items.items() if entry.expires_at <= now
        ]
        for key in expired_keys:
            self._items.pop(key, None)
