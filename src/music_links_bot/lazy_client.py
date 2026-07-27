from __future__ import annotations

from collections.abc import Callable
from typing import Any


class LazyAsyncClient:
    """Create a provider client only when one of its methods is first used."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._instance: Any | None = None

    @property
    def initialized(self) -> bool:
        return self._instance is not None

    def _get(self) -> Any:
        if self._instance is None:
            self._instance = self._factory()
        return self._instance

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)

    async def aclose(self) -> None:
        if self._instance is None:
            return
        close = getattr(self._instance, "aclose", None)
        if callable(close):
            await close()
