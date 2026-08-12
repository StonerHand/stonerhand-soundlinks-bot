from __future__ import annotations

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from music_links_bot import __version__
from music_links_bot.alerts import send_admin_alert
from music_links_bot.logging_config import quiet_transport_logs

LOGGER = logging.getLogger(__name__)
quiet_transport_logs()
TIMEOUT_SECONDS = 8


class handler(BaseHTTPRequestHandler):
    """GET /api/health — the bot's pulse.

    Checks the Telegram API, the webhook registration and Redis, then ticks
    the publish queue through its protected worker. Returns 503 when a critical
    check fails, so a free uptime monitor pointed here covers everything at once:
    outage detection, owner alerts, scheduled-post precision and warm
    instances. On failure the bot owner gets a Telegram DM (deduplicated,
    at most one per hour per problem).
    """

    def do_GET(self) -> None:
        # Telegram diagnostics and the independent queue worker are network
        # calls, so run them together. Read Redis afterwards to report the
        # queue state produced by this exact tick, including retries.
        with ThreadPoolExecutor(max_workers=3) as executor:
            telegram_check = executor.submit(_check_telegram)
            webhook_check = executor.submit(_check_webhook)
            telegram = telegram_check.result()
            webhook = webhook_check.result()
            # The registered Telegram webhook is the authoritative public
            # production origin even when optional Vercel hostname variables
            # are not exposed to the Python runtime.
            queue_tick = executor.submit(_tick_queue, webhook.get("detail"))
            queue_worker = queue_tick.result()
        redis, queue, metrics = _storage_snapshot()
        checks: dict[str, dict] = {
            "telegram": telegram,
            "webhook": webhook,
            "redis": redis,
            "queue_worker": queue_worker,
        }
        healthy = overall_ok(checks)
        service_healthy = overall_service_ok(checks, queue)

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
                "ok": service_healthy,
                "checks": checks,
                "queue": queue,
                "metrics": metrics,
                "queue_published": int(queue_worker.get("published") or 0),
                "release": release_info(),
                "ts": int(time.time()),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(
            HTTPStatus.OK if service_healthy else HTTPStatus.SERVICE_UNAVAILABLE
        )
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

    worker_check = checks.get("queue_worker", {})
    return not worker_check.get("configured") or bool(worker_check.get("ok"))


def overall_service_ok(checks: dict[str, dict], queue: dict) -> bool:
    """A configured queue with overdue work is a production failure too."""
    queue_ok = not queue.get("configured") or not queue.get("overdue")
    return overall_ok(checks) and queue_ok


def describe_failures(checks: dict[str, dict]) -> list[str]:
    failures = []
    for name, check in checks.items():
        if name in {"redis", "queue_worker"} and not check.get("configured"):
            continue
        if not check.get("ok"):
            failures.append(name)

    return failures


def release_info() -> dict[str, str]:
    """Identify the exact build serving traffic, not just repository main."""
    return {
        "version": __version__,
        "commit": os.getenv("VERCEL_GIT_COMMIT_SHA", "").strip()[:12],
        "environment": os.getenv("VERCEL_ENV", "local").strip() or "local",
    }


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
        # The URL is built from a fixed Telegram HTTPS origin, never user input.
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001 — health must degrade to JSON, never crash.
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


def _storage_snapshot() -> tuple[dict, dict, dict]:
    """Read Redis health, queue and metrics through one client and event loop."""
    import asyncio

    from music_links_bot.bot_runtime import METRICS_KV_KEY
    from music_links_bot.kvstore import KVStore
    from music_links_bot.publish_queue import QUEUE_KV_KEY

    kv = KVStore.from_env()
    if kv is None:
        return (
            {"ok": True, "configured": False, "detail": "not configured"},
            {"configured": False, "size": 0, "overdue": 0},
            {"configured": False},
        )

    async def read() -> tuple[bool, object, object]:
        try:
            ping, jobs, metrics = await asyncio.gather(
                kv.set("health:ping", str(int(time.time())), ttl_seconds=300),
                kv.get_json(QUEUE_KV_KEY),
                kv.get_json(METRICS_KV_KEY),
            )
            return bool(ping), jobs, metrics
        finally:
            await kv.aclose()

    try:
        ping, jobs, metrics = asyncio.run(read())
    except Exception:
        return (
            {"ok": False, "configured": True, "detail": "unreachable"},
            {"configured": True, "size": 0, "overdue": 0, "detail": "unreachable"},
            {"configured": True, "available": False},
        )

    queue = _summarize_queue_jobs(jobs if isinstance(jobs, list) else [])
    metrics_status = (
        {"configured": True, "available": True, **metrics}
        if isinstance(metrics, dict)
        else {"configured": True, "available": False}
    )
    return (
        {
            "ok": ping,
            "configured": True,
            "detail": "ping" if ping else "unreachable",
        },
        queue,
        metrics_status,
    )


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
        if publish_at <= 0:
            continue
        valid_jobs += 1
        status = str(job.get("status") or "pending")
        try:
            lease_until = int(job.get("lease_until") or 0)
        except (TypeError, ValueError):
            lease_until = 0
        actively_processing = status == "processing" and lease_until > current
        if publish_at < current - 120 and not actively_processing:
            overdue += 1
    return {"configured": True, "size": valid_jobs, "overdue": overdue}


def _tick_queue(webhook_url: object = None) -> dict[str, object]:
    """Piggyback the scheduled-posts tick on every health ping, so one
    uptime monitor keeps the queue delivering on time."""
    host = (
        os.getenv("WEBHOOK_BASE_URL", "").strip()
        or os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
        or os.getenv("VERCEL_URL", "").strip()
        or _webhook_host(webhook_url)
    )
    secret = os.getenv("CRON_SECRET", "").strip()
    if not host or not secret:
        return {
            "ok": True,
            "configured": False,
            "published": 0,
            "detail": "not configured",
        }
    host = host.removeprefix("https://").removeprefix("http://").split("/", 1)[0]

    try:
        request = Request(
            f"https://{host}/api/queue_worker",
            headers={"Authorization": f"Bearer {secret}"},
        )
        # The deployment hostname comes from Vercel environment and HTTPS is forced.
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("ok") is True:
            return {
                "ok": True,
                "configured": True,
                "published": int(payload.get("published") or 0),
                "detail": "reachable",
            }
    except Exception:
        LOGGER.debug("Queue tick via health failed", exc_info=True)

    return {
        "ok": False,
        "configured": True,
        "published": 0,
        "detail": "unreachable",
    }


def _webhook_host(value: object) -> str:
    """Accept only the public HTTPS origin returned by Telegram itself."""
    if not isinstance(value, str):
        return ""
    parsed = urlparse(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or not parsed.path.endswith("/api/telegram")
    ):
        return ""
    return parsed.netloc
