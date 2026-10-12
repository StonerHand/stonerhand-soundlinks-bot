"""Verify Upstash QStash request signatures without extra dependencies.

QStash signs every delivery with an HS256 JWT in ``Upstash-Signature``. The
Vercel integration injects the current and next signing keys, so a schedule
needs no hand-copied secret header. Both keys are accepted to survive rotation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlparse

_CLOCK_SKEW_SECONDS = 60


def qstash_signing_keys() -> list[str]:
    return [
        key
        for key in (
            os.getenv("QSTASH_CURRENT_SIGNING_KEY", "").strip(),
            os.getenv("QSTASH_NEXT_SIGNING_KEY", "").strip(),
        )
        if key
    ]


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def verify_qstash_signature(
    signature: str | None,
    body: bytes,
    *,
    expected_path: str,
    keys: list[str] | None = None,
    now: float | None = None,
) -> bool:
    """True only for a fresh QStash delivery of this exact body to this path."""
    keys = qstash_signing_keys() if keys is None else keys
    if not signature or not keys:
        return False
    parts = signature.split(".")
    if len(parts) != 3:
        return False
    header_b64, claims_b64, signature_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(claims_b64))
        received = _b64url_decode(signature_b64)
    except (ValueError, TypeError):
        return False
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        return False
    signing_input = f"{header_b64}.{claims_b64}".encode()
    if not any(
        hmac.compare_digest(
            hmac.new(key.encode(), signing_input, hashlib.sha256).digest(), received
        )
        for key in keys
    ):
        return False
    if not isinstance(claims, dict) or claims.get("iss") != "Upstash":
        return False
    current = time.time() if now is None else now
    expires, not_before = claims.get("exp"), claims.get("nbf")
    if not isinstance(expires, (int, float)) or current > expires + _CLOCK_SKEW_SECONDS:
        return False
    if (
        isinstance(not_before, (int, float))
        and current < not_before - _CLOCK_SKEW_SECONDS
    ):
        return False
    # A signature minted for another endpoint must not be replayable here;
    # only the path is pinned so preview and custom domains keep working.
    if urlparse(str(claims.get("sub") or "")).path.rstrip("/") != expected_path:
        return False
    expected_body = _b64url(hashlib.sha256(body).digest())
    return hmac.compare_digest(str(claims.get("body") or "").rstrip("="), expected_body)
