from __future__ import annotations

import json
import logging
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from music_links_bot.alerts import send_admin_alert

LOGGER = logging.getLogger(__name__)
TIMEOUT_SECONDS = 8


class handler(BaseHTTPRequestHandler):
    """GET /api/health — the bot's pulse.

    Checks the Telegram API, the webhook registration and Redis, then ticks
    the publish queue via /api/webapp. Returns 503 when a critical check
    fails, so a free uptime monitor pointed here covers everything at once:
    outage detection, owner alerts, scheduled-post precision and warm
    instances. On failure the bot owner gets a Telegram DM (deduplicated,
    at most one per hour per problem).
    """

    def do_GET(self) -> None:
        checks: dict[str, dict] = {
            "telegram": _check_telegram(),
            "webhook": _check_webhook(),
            "redis": _check_redis(),
        }
        healthy = overall_ok(checks)
        queue_published = _tick_queue(self.headers.get("host"))
        # Read the queue AFTER the tick: anything still overdue means it isn't
        # draining (a repeatedly failing publish or a queue nobody is ticking).
        queue = _queue_status()

        if not healthy:
            failing = ", ".join(sorted(describe_failures(checks)))
            send_admin_alert(
                f"Health check failed: {failing}. https://{self.headers.get('host')}/api/health",
                dedup_key=f"health:{failing}",
            )
        elif queue.get("overdue"):
            send_admin_alert(
                f"Очередь не разгружается: {queue['overdue']} просроченных из "
                f"{queue['size']}. Проверь права бота и логи Vercel.",
                dedup_key="queue-stuck",
            )

        body = json.dumps(
            {
                "ok": healthy,
                "checks": checks,
                "queue": queue,
                "queue_published": queue_published,
                "ts": int(time.time()),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def overall_ok(checks: dict[str, dict]) -> bool:
    """Telegram and the webhook are critical; Redis only counts when it is
    actually configured — the bot is designed to run without it."""
    if not checks.get("telegram", {}).get("ok"):
        return False

    if not checks.get("webhook", {}).get("ok"):
        return False

    redis_check = checks.get("redis", {})
    if redis_check.get("configured") and not redis_check.get("ok"):
        return False

    return True


def describe_failures(checks: dict[str, dict]) -> list[str]:
    failures = []
    for name, check in checks.items():
        if name == "redis" and not check.get("configured"):
            continue
        if not check.get("ok"):
            failures.append(name)

    return failures


def evaluate_webhook_info(payload: object) -> tuple[bool, str]:
    """getWebhookInfo result → (healthy, detail)."""
    if not isinstance(payload, dict) or not payload.get("ok"):
        return False, "telegram api error"

    info = payload.get("result")
    if not isinstance(info, dict):
        return False, "no webhook info"

    url = str(info.get("url") or "")
    if not url.endswith("/api/telegram"):
        return False, "webhook is not registered"

    last_error = str(info.get("last_error_message") or "")
    last_error_date = int(info.get("last_error_date") or 0)
    # A delivery error within the last 15 minutes means updates are failing
    # right now, not just a historical blip.
    if last_error and time.time() - last_error_date < 900:
        return False, f"delivery failing: {last_error[:120]}"

    return True, url


def _telegram_api(method: str) -> dict | None:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        return None

    try:
        request = Request(f"https://api.telegram.org/bot{bot_token}/{method}")
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        LOGGER.warning("Health call %s failed", method, exc_info=True)
        return None


def _check_telegram() -> dict:
    payload = _telegram_api("getMe")
    if payload is None or not payload.get("ok"):
        return {"ok": False, "detail": "BOT_TOKEN missing or Telegram unreachable"}

    username = ""
    result = payload.get("result")
    if isinstance(result, dict):
        username = str(result.get("username") or "")

    return {"ok": True, "detail": f"@{username}"}


def _check_webhook() -> dict:
    payload = _telegram_api("getWebhookInfo")
    if payload is None:
        return {"ok": False, "detail": "BOT_TOKEN missing or Telegram unreachable"}

    healthy, detail = evaluate_webhook_info(payload)
    return {"ok": healthy, "detail": detail}


def _check_redis() -> dict:
    import asyncio

    from music_links_bot.kvstore import KVStore

    kv = KVStore.from_env()
    if kv is None:
        return {"ok": True, "configured": False, "detail": "not configured"}

    async def ping() -> bool:
        try:
            return await kv.set("health:ping", str(int(time.time())), ttl_seconds=300)
        finally:
            await kv.aclose()

    try:
        healthy = asyncio.run(ping())
    except Exception:
        healthy = False

    return {"ok": healthy, "configured": True, "detail": "ping" if healthy else "unreachable"}


def _queue_status(*, now: float | None = None) -> dict:
    """Surface the publish queue in the health payload: total jobs and how many
    are meaningfully overdue, so a stuck queue is visible before a post is missed."""
    import asyncio

    from music_links_bot.kvstore import KVStore
    from music_links_bot.publish_queue import QUEUE_KV_KEY

    kv = KVStore.from_env()
    if kv is None:
        return {"configured": False, "size": 0, "overdue": 0}

    async def read():
        try:
            return await kv.get_json(QUEUE_KV_KEY)
        finally:
            await kv.aclose()

    try:
        jobs = asyncio.run(read())
    except Exception:
        return {"configured": True, "size": 0, "overdue": 0, "detail": "unreachable"}

    if not isinstance(jobs, list):
        jobs = []

    return _summarize_queue_jobs(jobs, now=now)


def _summarize_queue_jobs(jobs: list, *, now: float | None = None) -> dict:
    """Ignore corrupt queue entries so monitoring itself stays available."""
    current = now if now is not None else time.time()
    overdue = 0
    valid_jobs = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        try:
            publish_at = int(job.get("publish_at") or 0)
        except (TypeError, ValueError):
            continue
        valid_jobs += 1
        if publish_at < current - 120:
            overdue += 1
    return {"configured": True, "size": valid_jobs, "overdue": overdue}


def _tick_queue(request_host: str | None) -> int:
    """Piggyback the scheduled-posts tick on every health ping, so one
    uptime monitor keeps the queue delivering on time."""
    host = (
        os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
        or os.getenv("VERCEL_URL", "").strip()
        or (request_host or "").strip()
    )
    if not host:
        return 0

    try:
        with urlopen(f"https://{host}/api/webapp", timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict):
            return int(payload.get("queue_published") or 0)
    except Exception:
        LOGGER.debug("Queue tick via health failed", exc_info=True)

    return 0
