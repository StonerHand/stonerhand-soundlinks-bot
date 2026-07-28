from __future__ import annotations

from enum import Enum
from typing import Any


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


_API_ERROR_CODES = {
    "bad request": "invalid_input",
    "invalid json": "invalid_input",
    "empty query": "invalid_input",
    "need urls": "invalid_input",
    "bad index": "invalid_input",
    "bad order": "invalid_input",
    "bad time": "invalid_input",
    "not found": "release_not_found",
    "draft not found": "draft_expired",
    "job not found": "draft_expired",
    "request_in_progress": "action_busy",
    "queue_busy": "action_busy",
    "duplicate": "action_duplicate",
    "admin only": "permission_denied",
    "unauthorized": "permission_denied",
    "send failed": "delivery_failed",
    "publish failed": "delivery_failed",
    "delete failed": "delivery_failed",
    "share unavailable": "delivery_failed",
    "timeout": "provider_unavailable",
    "network": "provider_unavailable",
    "internal": "provider_unavailable",
    "rate_limited": "rate_limited",
    "crate full": "crate_full",
    "need more tracks": "need_more_tracks",
}

_RETRYABLE_CODES = {
    "action_busy",
    "delivery_failed",
    "provider_unavailable",
    "rate_limited",
}


def normalize_api_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach a stable error contract without breaking legacy clients.

    ``error`` stays intact for backwards compatibility. New clients can use
    ``error_code`` and ``retryable`` consistently across every API action.
    """
    if payload.get("ok"):
        return payload
    normalized = dict(payload)
    legacy = str(normalized.get("error") or "internal")
    code = _API_ERROR_CODES.get(legacy, legacy.replace(" ", "_"))
    normalized["error_code"] = code
    normalized.setdefault("retryable", code in _RETRYABLE_CODES)
    return normalized
