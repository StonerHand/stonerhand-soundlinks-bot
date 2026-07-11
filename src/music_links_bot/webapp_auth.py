from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_INIT_DATA_AGE_SECONDS = 24 * 3600


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = MAX_INIT_DATA_AGE_SECONDS,
    now: float | None = None,
) -> dict | None:
    """Validates Telegram Mini App initData and returns the user dict.

    Implements the official algorithm: the data-check string is every field
    except `hash`, sorted and newline-joined, signed with
    HMAC-SHA256(key=HMAC-SHA256("WebAppData", bot_token)). Returns None for
    tampered, unsigned or stale payloads.
    """
    if not init_data or not bot_token:
        return None

    params = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = params.pop("hash", "")
    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(params.items())
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256)
    expected_hash = hmac.new(
        secret_key.digest(),
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    try:
        auth_date = int(params.get("auth_date", "0"))
    except ValueError:
        return None

    current_time = now if now is not None else time.time()
    if auth_date <= 0 or current_time - auth_date > max_age_seconds:
        return None

    try:
        user = json.loads(params.get("user", ""))
    except ValueError:
        return None

    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        return None

    return user
