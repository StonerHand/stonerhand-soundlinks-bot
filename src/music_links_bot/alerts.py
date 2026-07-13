from __future__ import annotations

import hashlib
import logging
import os

import httpx

from music_links_bot.constants import HTTP_USER_AGENT

LOGGER = logging.getLogger(__name__)
ALERT_DEDUP_TTL_SECONDS = 3600


def send_admin_alert(text: str, *, dedup_key: str | None = None) -> bool:
    """Best-effort DM to the bot owner about an operational problem.

    Deduplicated via Redis for an hour so a flapping check does not flood
    the chat (without Redis every call alerts — better noisy than silent).
    Never raises: alerting must not break the caller.
    """
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    admin_chat_id = os.getenv("ADMIN_CHAT_ID", "").strip()
    if not bot_token or not admin_chat_id:
        return False

    if not _acquire_dedup_slot(alert_dedup_digest(dedup_key or text)):
        return False

    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": admin_chat_id, "text": f"🚨 {text}"[:4000]},
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=8.0,
        )
        payload = response.json()
        return bool(isinstance(payload, dict) and payload.get("ok"))
    except Exception:
        LOGGER.warning("Admin alert failed", exc_info=True)
        return False


def alert_dedup_digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _acquire_dedup_slot(digest: str) -> bool:
    base_url = (
        os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
        or os.getenv("KV_REST_API_URL", "").strip()
    )
    token = (
        os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
        or os.getenv("KV_REST_API_TOKEN", "").strip()
    )
    if not base_url or not token:
        return True

    try:
        response = httpx.post(
            base_url.rstrip("/") + "/",
            json=["SET", f"alert:{digest}", "1", "NX", "EX", str(ALERT_DEDUP_TTL_SECONDS)],
            headers={"Authorization": f"Bearer {token}", "User-Agent": HTTP_USER_AGENT},
            timeout=4.0,
        )
        payload = response.json()
        return isinstance(payload, dict) and payload.get("result") == "OK"
    except Exception:
        return True
