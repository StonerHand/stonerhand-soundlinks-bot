from __future__ import annotations

from enum import Enum


class BotErrorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    SEARCH_NOT_FOUND = "search_not_found"
    RELEASE_NOT_FOUND = "release_not_found"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"
    LIMIT_EXCEEDED = "limit_exceeded"


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
