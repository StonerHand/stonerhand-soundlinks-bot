"""Classify provider failures without exposing upstream messages or URLs."""

from __future__ import annotations

import httpx

from music_links_bot.public_release import (
    PublicReleaseError,
    PublicReleaseRegionUnavailable,
)


def provider_failure_reason(error: BaseException) -> str:
    seen: set[int] = set()
    reason = "provider_unavailable"
    while id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, PublicReleaseRegionUnavailable):
            return "region_unavailable"
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            if status in {404, 410}:
                return "release_not_found"
            if status == 429:
                return "rate_limited"
        if isinstance(error, (TimeoutError, httpx.TimeoutException)):
            return "timeout"
        if isinstance(error, PublicReleaseError):
            reason = (
                "metadata_incomplete"
                if error.__cause__ is None
                else "provider_unavailable"
            )
        name = type(error).__name__.casefold()
        if "ratelimit" in name:
            return "rate_limited"
        if "timeout" in name:
            return "timeout"
        cause = error.__cause__
        if cause is None:
            break
        error = cause
    return reason
