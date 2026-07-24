from __future__ import annotations

import asyncio
import hmac
import json
import logging
import threading
import time
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from telegram import Update

from music_links_bot.bot import build_application, close_application_resources
from music_links_bot.config import Settings
from music_links_bot.loop_runner import (
    run_on_loop,
    start_background_loop,
    stop_background_loop,
)
from music_links_bot.publish_queue import process_due_jobs

LOGGER = logging.getLogger(__name__)
MAX_UPDATE_BYTES = 1024 * 1024

# Warm serverless instances keep module state between invocations, so the
# Telegram application, its HTTP connection pools and in-memory lookup caches
# are built once per instance instead of once per update. The container is
# frozen/reclaimed by the platform, so no per-request shutdown is needed;
# a failed update disposes the cached application to start clean next time.
_STATE_LOCK = threading.Lock()
_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_THREAD: threading.Thread | None = None
_APPLICATION = None

# A single hung await must never hold the shared lock forever and wedge the
# whole warm instance, so every event-loop run is time-bounded.
PROCESS_TIMEOUT_SECONDS = 25
QUEUE_TICK_TIMEOUT_SECONDS = 20
# One bad update shouldn't cold-start the next user: only recycle the cached
# application after several consecutive failures (a genuinely broken instance).
_DISPOSE_AFTER_FAILURES = 3
_consecutive_failures = 0
_active_updates = 0
_recycle_requested = False
_FAILURE_LOCK = threading.Lock()
# Telegram re-sends an update if it doesn't get a prompt 200, so identical
# update_ids are ignored to avoid double replies / double publishes.
UPDATE_DEDUP_TTL_SECONDS = 600
_SEEN_UPDATE_IDS: "OrderedDict[int, float]" = OrderedDict()
_SEEN_UPDATE_MAX = 1024


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send_json({"ok": True, "service": "StonerHandBot webhook"})

    def do_POST(self) -> None:
        if not _is_telegram_request_authorized(
            self.headers.get("x-telegram-bot-api-secret-token")
        ):
            self._send_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN)
            return

        content_length = _read_content_length(self.headers.get("content-length"))
        if content_length is None:
            self._send_json(
                {"ok": False, "error": "invalid content length"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        if content_length <= 0:
            self._send_json({"ok": False, "error": "empty body"}, HTTPStatus.BAD_REQUEST)
            return

        if content_length > MAX_UPDATE_BYTES:
            self._send_json(
                {"ok": False, "error": "payload too large"},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return

        try:
            payload = self.rfile.read(content_length)
            update_payload = _decode_update_payload(payload)
        except (json.JSONDecodeError, ValueError):
            LOGGER.exception("Invalid Telegram update payload")
            self._send_json({"ok": False, "error": "invalid json"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            _process_telegram_update(update_payload)
        except Exception:
            LOGGER.exception("Could not process Telegram update")
            self._send_json({"ok": False}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json({"ok": True})

    def _send_json(
        self,
        payload: dict[str, object],
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _process_telegram_update(update_payload: dict[str, object]) -> None:
    loop, application = _ensure_application()
    _note_update_started()

    try:
        _process_claimed_update(loop, application, update_payload)
    finally:
        if _note_update_finished():
            LOGGER.warning("Recycling application after repeated failures")
            _dispose_application_locked()


def _process_claimed_update(loop, application, update_payload: dict[str, object]) -> None:
    update_id = update_payload.get("update_id")
    if isinstance(update_id, int) and not run_on_loop(
        loop, _claim_update(application, update_id), timeout=5
    ):
        LOGGER.info("Skipping duplicate Telegram update %s", update_id)
        return

    started = time.monotonic()
    try:
        update = Update.de_json(update_payload, application.bot)
        run_on_loop(
            loop,
            application.process_update(update),
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        if isinstance(update_id, int):
            try:
                run_on_loop(
                    loop, _release_update(application, update_id), timeout=5
                )
            except Exception:
                LOGGER.debug("Could not release update claim", exc_info=True)
        _note_failure_locked(exc)
        raise

    _note_success_locked()
    LOGGER.info(
        "update=%s processed in %.0fms", update_id, (time.monotonic() - started) * 1000
    )

    try:
        run_on_loop(
            loop,
            _run_queue_tick(application),
            timeout=QUEUE_TICK_TIMEOUT_SECONDS,
        )
    except Exception:
        LOGGER.warning("Queue tick failed", exc_info=True)


async def _claim_update(application, update_id: int) -> bool:
    """Reserve an update_id so a Telegram retry of the same update is skipped.
    Returns False when it was already claimed."""
    kv = application.bot_data.get("kv_store")
    if kv is not None:
        key = f"seen_update:{update_id}"
        if await kv.set(
            key, "1", ttl_seconds=UPDATE_DEDUP_TTL_SECONDS, nx=True
        ):
            return True
        # KVStore deliberately swallows transport errors. Distinguish a real
        # duplicate from an unavailable Redis instance so an outage cannot
        # make the webhook acknowledge and silently discard every update.
        if await kv.get(key) is not None:
            return False
        LOGGER.warning(
            "Redis update deduplication unavailable; using warm-instance fallback"
        )

    return _claim_update_in_memory(update_id)


def _claim_update_in_memory(update_id: int, *, now: float | None = None) -> bool:
    claimed_at = time.monotonic() if now is None else now
    cutoff = claimed_at - UPDATE_DEDUP_TTL_SECONDS
    while _SEEN_UPDATE_IDS:
        _oldest_id, oldest_at = next(iter(_SEEN_UPDATE_IDS.items()))
        if oldest_at > cutoff:
            break
        _SEEN_UPDATE_IDS.popitem(last=False)

    if update_id in _SEEN_UPDATE_IDS:
        return False
    _SEEN_UPDATE_IDS[update_id] = claimed_at
    while len(_SEEN_UPDATE_IDS) > _SEEN_UPDATE_MAX:
        _SEEN_UPDATE_IDS.popitem(last=False)
    return True


async def _release_update(application, update_id: int) -> None:
    kv = application.bot_data.get("kv_store")
    if kv is not None:
        await kv.delete(f"seen_update:{update_id}")
    _SEEN_UPDATE_IDS.pop(update_id, None)


def _note_success_locked() -> None:
    global _consecutive_failures
    with _FAILURE_LOCK:
        _consecutive_failures = 0


def _note_failure_locked(exc: Exception) -> None:
    global _consecutive_failures, _recycle_requested
    with _FAILURE_LOCK:
        _consecutive_failures += 1
        if _consecutive_failures >= _DISPOSE_AFTER_FAILURES:
            _recycle_requested = True
    _alert_crash_safely(exc)


def _note_update_started() -> None:
    global _active_updates
    with _FAILURE_LOCK:
        _active_updates += 1


def _note_update_finished() -> bool:
    global _active_updates, _consecutive_failures, _recycle_requested
    with _FAILURE_LOCK:
        _active_updates = max(0, _active_updates - 1)
        should_recycle = _recycle_requested and _active_updates == 0
        if should_recycle:
            _recycle_requested = False
            _consecutive_failures = 0
        return should_recycle


async def _run_queue_tick(application) -> int:
    from types import SimpleNamespace

    context = SimpleNamespace(application=application, bot=application.bot)
    return await process_due_jobs(context)


def _alert_crash_safely(exc: Exception) -> None:
    try:
        from music_links_bot.alerts import send_admin_alert

        send_admin_alert(
            f"Webhook update crashed: {type(exc).__name__}. "
            "Telegram will retry the update; check the Vercel logs.",
            dedup_key="webhook-crash",
        )
    except Exception:
        LOGGER.debug("Crash alert failed", exc_info=True)


def _ensure_application():
    global _LOOP, _LOOP_THREAD, _APPLICATION
    with _STATE_LOCK:
        if _APPLICATION is None:
            settings = Settings.from_env()
            logging.basicConfig(
                level=getattr(logging, settings.log_level, logging.INFO),
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            )
            loop, thread = start_background_loop("telegram-runtime")
            try:
                application = build_application(settings)
                run_on_loop(
                    loop, application.initialize(), timeout=PROCESS_TIMEOUT_SECONDS
                )
            except Exception:
                stop_background_loop(loop, thread)
                raise
            _LOOP = loop
            _LOOP_THREAD = thread
            _APPLICATION = application

    return _LOOP, _APPLICATION


def _dispose_application_locked() -> None:
    global _LOOP, _LOOP_THREAD, _APPLICATION
    with _STATE_LOCK:
        loop, thread, application = _LOOP, _LOOP_THREAD, _APPLICATION
        _LOOP = None
        _LOOP_THREAD = None
        _APPLICATION = None
    if loop is None or application is None:
        return

    try:
        run_on_loop(loop, application.shutdown(), timeout=10)
        run_on_loop(loop, close_application_resources(application), timeout=10)
    except Exception:
        LOGGER.warning("Could not dispose Telegram application cleanly")
    finally:
        stop_background_loop(loop, thread)


def _decode_update_payload(payload: bytes) -> dict[str, object]:
    update_payload = json.loads(payload)
    if not isinstance(update_payload, dict):
        raise ValueError("Telegram update payload must be a JSON object.")

    return update_payload


def _read_content_length(raw_value: str | None) -> int | None:
    try:
        return int(raw_value or "0")
    except ValueError:
        return None


def _is_telegram_request_authorized(received_secret: str | None) -> bool:
    from music_links_bot.webhook_secret import telegram_webhook_secret

    expected_secret = telegram_webhook_secret()
    if not expected_secret:
        # No explicit secret and no bot token to derive one from — nothing
        # meaningful to compare against (local development only).
        return True

    return hmac.compare_digest(received_secret or "", expected_secret)
