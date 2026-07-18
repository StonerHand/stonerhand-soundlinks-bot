from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import secrets
import sys
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from music_links_bot.bot import (
    CHANNEL_USERNAME,
    DRAFT_TTL_SECONDS,
    STATS_KV_KEY,
    _find_posted_date,
    _load_draft,
    _lookup_tracks,
    _publish_draft,
    _release_fingerprint,
    _render_track_draft,
    _schedule_mark_posted,
    _select_preview_url,
    _store_draft,
    build_application,
    normalize_hashtag,
)
from music_links_bot.config import Settings
from music_links_bot.constants import PLATFORM_BUTTON_STYLES, PLATFORM_LABELS
from music_links_bot.formatter import (
    build_auto_hashtags,
    format_collection_message,
    pick_track_emoji,
)
from music_links_bot.i18n import resolve_lang
from music_links_bot.kvstore import KVStore
from music_links_bot.models import TrackMatch
from music_links_bot.phrases import pick_phrase
from music_links_bot.publish_queue import (
    MAX_DELAY_SECONDS,
    add_job,
    load_jobs,
    process_due_jobs,
    remove_job,
    reschedule_job,
)
from music_links_bot.search import SearchLookupError, normalize_search_query
from music_links_bot.stats import load_stats, merge_stats
from music_links_bot.url_utils import extract_supported_urls
from music_links_bot.webapp_auth import validate_init_data
from telegram.constants import ParseMode

LOGGER = logging.getLogger(__name__)
MAX_BODY_BYTES = 64 * 1024
MAX_HISTORY_ITEMS = 10
HISTORY_TTL_SECONDS = 90 * 24 * 3600
MAX_CUSTOM_CTA_LENGTH = 200
MAX_CUSTOM_TAGS = 8
MAX_CRATE_ITEMS = 10
CRATE_TTL_SECONDS = 14 * 24 * 3600
# Every event-loop run is time-bounded so one slow upstream call (Song.link,
# iTunes, Redis) can't hold the shared lock and wedge the warm instance.
ACTION_TIMEOUT_SECONDS = 25
QUEUE_TICK_TIMEOUT_SECONDS = 20
# A cheap per-instance guard against a single user hammering the external
# search/resolve APIs. Generous enough that normal use never trips it.
RESOLVE_RATE_LIMIT = 20
RESOLVE_RATE_WINDOW_SECONDS = 60
_resolve_calls: dict[int, list[float]] = {}

_STATE_LOCK = threading.Lock()
_LOOP: asyncio.AbstractEventLoop | None = None
_APPLICATION = None
_SETTINGS: Settings | None = None


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        # A GET doubles as a queue tick: any uptime ping (or a curious
        # browser) delivers scheduled posts whose time has come.
        published = 0
        try:
            with _STATE_LOCK:
                loop, application, _settings = _ensure_application()
                context = SimpleNamespace(application=application, bot=application.bot)
                published = loop.run_until_complete(
                    asyncio.wait_for(
                        process_due_jobs(context), timeout=QUEUE_TICK_TIMEOUT_SECONDS
                    )
                )
        except Exception:
            LOGGER.exception("Queue tick failed")

        self._send_json(
            {"ok": True, "service": "StonerHand studio API", "queue_published": published}
        )

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("content-length") or "0")
        except ValueError:
            content_length = 0

        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            self._send_json({"ok": False, "error": "bad request"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
            if not isinstance(payload, dict):
                raise ValueError
        except ValueError:
            self._send_json({"ok": False, "error": "invalid json"}, HTTPStatus.BAD_REQUEST)
            return

        req_id = secrets.token_hex(4)
        # Sanitize before logging so a crafted action string can't forge log
        # lines (control chars) or flood them (length).
        action = str(payload.get("action") or "?").replace("\n", " ").replace("\r", " ")[:48]
        started = time.monotonic()
        try:
            with _STATE_LOCK:
                loop, application, settings = _ensure_application()
                user = validate_init_data(
                    str(payload.get("init_data") or ""),
                    settings.bot_token,
                )
                if user is None:
                    LOGGER.info("req=%s action=%s unauthorized", req_id, action)
                    self._send_json(
                        {"ok": False, "error": "unauthorized"},
                        HTTPStatus.UNAUTHORIZED,
                    )
                    return

                result = loop.run_until_complete(
                    asyncio.wait_for(
                        _handle_action(application, settings, user, payload),
                        timeout=ACTION_TIMEOUT_SECONDS,
                    )
                )
        except asyncio.TimeoutError:
            LOGGER.warning(
                "req=%s action=%s timed out after %.1fs",
                req_id, action, time.monotonic() - started,
            )
            self._send_json(
                {"ok": False, "error": "timeout"}, HTTPStatus.GATEWAY_TIMEOUT
            )
            return
        except Exception:
            LOGGER.exception("req=%s action=%s failed", req_id, action)
            self._send_json({"ok": False, "error": "internal"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        LOGGER.info(
            "req=%s action=%s ok=%s %.0fms",
            req_id, action, bool(result.get("ok")), (time.monotonic() - started) * 1000,
        )
        status = HTTPStatus.OK if result.get("ok") else HTTPStatus.UNPROCESSABLE_ENTITY
        self._send_json(result, status)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _ensure_application():
    global _LOOP, _APPLICATION, _SETTINGS
    if _APPLICATION is None:
        settings = Settings.from_env()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        application = build_application(settings)
        loop.run_until_complete(application.initialize())
        _LOOP = loop
        _APPLICATION = application
        _SETTINGS = settings

    return _LOOP, _APPLICATION, _SETTINGS


def _resolve_rate_limited(user_id: int, *, now: float | None = None) -> bool:
    current = now if now is not None else time.time()
    calls = [t for t in _resolve_calls.get(user_id, []) if current - t < RESOLVE_RATE_WINDOW_SECONDS]
    if len(calls) >= RESOLVE_RATE_LIMIT:
        _resolve_calls[user_id] = calls
        return True

    calls.append(current)
    _resolve_calls[user_id] = calls
    if len(_resolve_calls) > 5000:  # bound memory on a long-lived warm instance
        for uid in list(_resolve_calls):
            if all(current - t >= RESOLVE_RATE_WINDOW_SECONDS for t in _resolve_calls[uid]):
                _resolve_calls.pop(uid, None)
    return False


async def _handle_action(application, settings: Settings, user: dict, payload: dict) -> dict:
    context = SimpleNamespace(application=application, bot=application.bot)
    action = str(payload.get("action") or "")
    body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    user_id = int(user["id"])
    is_admin = settings.admin_chat_id is not None and user_id == settings.admin_chat_id
    lang = resolve_lang(user.get("language_code"))

    if action == "resolve":
        if _resolve_rate_limited(user_id):
            return {"ok": False, "error": "rate_limited"}
        return await _action_resolve(context, body, user_id, is_admin, lang)

    if action == "resolve_batch":
        if _resolve_rate_limited(user_id):
            return {"ok": False, "error": "rate_limited"}
        return await _action_resolve_batch(context, body, user_id)

    if action == "draft":
        return await _action_draft(context, body, user_id, is_admin)

    if action == "update":
        return await _action_update(context, body, user_id, is_admin)

    if action == "preview":
        return await _action_preview(context, body, user_id)

    if action == "history":
        return await _action_history(context, user_id, is_admin)

    if action in {"send", "publish"}:
        return await _action_deliver(context, action, body, user_id, is_admin)

    if action == "unpublish":
        return await _action_unpublish(context, body, user_id, is_admin)

    if action == "schedule":
        return await _action_schedule(context, body, user_id, is_admin)

    if action == "queue":
        return await _action_queue(context, is_admin)

    if action == "unschedule":
        return await _action_unschedule(context, body, is_admin)

    if action == "reschedule":
        return await _action_reschedule(context, body, is_admin)

    if action == "stats":
        return await _action_stats(context, is_admin)

    if action == "crate":
        return await _crate_response(context, user_id)

    if action == "crate_add":
        return await _action_crate_add(context, body, user_id)

    if action == "crate_remove":
        return await _action_crate_remove(context, body, user_id)

    if action == "crate_order":
        return await _action_crate_order(context, body, user_id)

    if action == "crate_clear":
        await _save_crate(context, user_id, [])
        return {"ok": True, "items": []}

    if action in {"crate_send", "crate_publish"}:
        return await _action_crate_deliver(context, action, user_id, is_admin, body)

    return {"ok": False, "error": "unknown action"}


async def _action_resolve(context, body: dict, user_id: int, is_admin: bool, lang: str) -> dict:
    query = str(body.get("query") or "").strip()
    bot_data = context.application.bot_data
    candidate_preview: str | None = None
    source_urls = extract_supported_urls(query)[:1]
    if not source_urls:
        search_query = normalize_search_query(query)
        if search_query is None:
            return {"ok": False, "error": "empty query"}

        try:
            candidates = await bot_data["search_client"].search_release_candidates(
                search_query
            )
        except SearchLookupError:
            return {"ok": False, "error": "not found"}

        if len(candidates) > 1 and not body.get("pick"):
            return {
                "ok": True,
                "candidates": [
                    {
                        "url": candidate.url,
                        "title": candidate.title,
                        "artist": candidate.artist,
                        "artwork": _upscale_artwork(candidate.artwork_url),
                        "preview": candidate.preview_url,
                    }
                    for candidate in candidates
                ],
            }

        source_urls = [candidates[0].url]
        candidate_preview = candidates[0].preview_url

    tracks, _unavailable = await _lookup_tracks(
        bot_data["songlink_client"],
        source_urls,
        soundcloud_client=bot_data["soundcloud_client"],
        search_client=bot_data.get("search_client"),
    )
    tracks = [track for track in tracks if track.links]
    if not tracks:
        return {"ok": False, "error": "not found"}

    track = tracks[0]
    draft = {
        "v": 1,
        "type": "track",
        "item": asdict(track),
        "prefix": "",
        "hashtags": False,
        "quote": False,
        "large_preview": True,
        "chat_id": user_id,
        "lang": lang,
        "can_publish": is_admin,
        # Preview lookup is deferred: the card renders immediately and the
        # client asks for the audio via the "preview" action only if needed,
        # so search no longer waits on an extra iTunes round-trip.
        "preview": candidate_preview,
    }
    if candidate_preview is None and track.kind == "song":
        draft["preview_pending"] = True
    draft_id = secrets.token_hex(8)
    await _store_draft(context, draft_id, draft)
    await _record_history(context, user_id, track, source_urls[0])
    return await _draft_response(context, draft_id, draft, is_admin)


async def _action_resolve_batch(context, body: dict, user_id: int) -> dict:
    """Resolve several dropped links at once into a ready-made crate — paste a
    handful of URLs and the Studio assembles the collection for you."""
    query = str(body.get("query") or "")
    source_urls = extract_supported_urls(query)[:MAX_CRATE_ITEMS]
    if len(source_urls) < 2:
        return {"ok": False, "error": "need urls"}

    bot_data = context.application.bot_data
    tracks, _unavailable = await _lookup_tracks(
        bot_data["songlink_client"],
        source_urls,
        soundcloud_client=bot_data["soundcloud_client"],
        search_client=bot_data.get("search_client"),
    )
    tracks = [track for track in tracks if track.links]
    if not tracks:
        return {"ok": False, "error": "not found"}

    items: list[dict] = []
    seen: set[str] = set()
    for track in tracks:
        compact = _compact_track_data(asdict(track))
        fingerprint = _release_fingerprint(compact["artist"], compact["title"])
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        items.append(compact)

    return _crate_view(items)


async def _action_draft(context, body: dict, user_id: int, is_admin: bool) -> dict:
    draft_id = str(body.get("draft_id") or "")
    draft = await _load_draft(context, draft_id)
    if draft is None or draft.get("chat_id") != user_id:
        return {"ok": False, "error": "draft not found"}

    if "preview" not in draft:
        # Drafts born in the chat editor arrive without an audio preview; fetch
        # it lazily via the "preview" action instead of blocking this response.
        draft["preview"] = None
        if TrackMatch(**draft["item"]).kind == "song":
            draft["preview_pending"] = True
        await _store_draft(context, draft_id, draft)

    return await _draft_response(context, draft_id, draft, is_admin)


async def _action_preview(context, body: dict, user_id: int) -> dict:
    """On-demand audio-preview lookup: the card is already on screen, so this
    keeps the initial resolve fast and only pays for iTunes when the user has a
    track that might be playable."""
    draft_id = str(body.get("draft_id") or "")
    draft = await _load_draft(context, draft_id)
    if draft is None or draft.get("chat_id") != user_id:
        return {"ok": False, "error": "draft not found"}

    preview = draft.get("preview")
    if not preview and draft.get("preview_pending"):
        preview = await _lookup_track_preview(context, TrackMatch(**draft["item"]))
        draft["preview"] = preview
        draft["preview_pending"] = False
        await _store_draft(context, draft_id, draft)

    return {"ok": True, "preview": preview or None}


async def _action_update(context, body: dict, user_id: int, is_admin: bool) -> dict:
    draft_id = str(body.get("draft_id") or "")
    draft = await _load_draft(context, draft_id)
    if draft is None or draft.get("chat_id") != user_id:
        return {"ok": False, "error": "draft not found"}

    _apply_draft_patch(draft, body)
    await _store_draft(context, draft_id, draft)
    return await _draft_response(context, draft_id, draft, is_admin)


async def _action_deliver(context, action: str, body: dict, user_id: int, is_admin: bool) -> dict:
    draft_id = str(body.get("draft_id") or "")
    draft = await _load_draft(context, draft_id)
    if draft is None or draft.get("chat_id") != user_id:
        return {"ok": False, "error": "draft not found"}

    _apply_draft_patch(draft, body)
    await _store_draft(context, draft_id, draft)
    track = TrackMatch(**draft["item"])

    if action == "publish":
        if not is_admin:
            return {"ok": False, "error": "admin only"}

        if not body.get("force"):
            posted_date = await _find_posted_date(context, track)
            if posted_date:
                return {"ok": False, "error": "duplicate", "posted_date": posted_date}

        published = await _publish_draft(context, draft)
        if published:
            _schedule_mark_posted(context, track)

        return {
            "ok": bool(published),
            "error": None if published else "publish failed",
            "message_id": getattr(published, "message_id", None),
        }

    from music_links_bot.bot import _build_link_preview_options

    text, keyboard = _render_track_draft(draft, context, draft_id=None)
    try:
        if draft.get("as_photo") and track.thumbnail_url:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=track.thumbnail_url,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.HTML,
                link_preview_options=_build_link_preview_options(
                    _select_preview_url(track.links, context) or track.thumbnail_url,
                    prefer_large_media=bool(draft.get("large_preview")),
                ),
                reply_markup=keyboard,
            )
    except Exception:
        LOGGER.exception("Studio send failed")
        return {"ok": False, "error": "send failed"}

    return {"ok": True}


async def _action_unpublish(context, body: dict, user_id: int, is_admin: bool) -> dict:
    """The 5-second "undo" after publishing: deletes the channel post and
    clears the posted-fingerprint so the duplicate guard forgets it."""
    if not is_admin:
        return {"ok": False, "error": "admin only"}

    draft_id = str(body.get("draft_id") or "")
    draft = await _load_draft(context, draft_id)
    if draft is None or draft.get("chat_id") != user_id:
        return {"ok": False, "error": "draft not found"}

    try:
        message_id = int(body.get("message_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad message"}

    target = context.application.bot_data.get("publish_chat_id") or f"@{CHANNEL_USERNAME}"
    try:
        await context.bot.delete_message(chat_id=target, message_id=message_id)
    except Exception:
        LOGGER.warning("Undo delete failed", exc_info=True)
        return {"ok": False, "error": "delete failed"}

    track = TrackMatch(**draft["item"])
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        await kv.delete(_release_fingerprint(track.artist, track.title))

    return {"ok": True}


async def _action_schedule(context, body: dict, user_id: int, is_admin: bool) -> dict:
    if not is_admin:
        return {"ok": False, "error": "admin only"}

    draft_id = str(body.get("draft_id") or "")
    draft = await _load_draft(context, draft_id)
    if draft is None or draft.get("chat_id") != user_id:
        return {"ok": False, "error": "draft not found"}

    try:
        publish_at = int(body.get("at") or 0)
    except (TypeError, ValueError):
        publish_at = 0

    now_ts = int(time.time())
    if publish_at <= now_ts or publish_at > now_ts + MAX_DELAY_SECONDS:
        return {"ok": False, "error": "bad time"}

    _apply_draft_patch(draft, body)
    await _store_draft(context, draft_id, draft)
    track = TrackMatch(**draft["item"])
    if not body.get("force"):
        posted_date = await _find_posted_date(context, track)
        if posted_date:
            return {"ok": False, "error": "duplicate", "posted_date": posted_date}

    job = await add_job(context, draft, publish_at)
    return {"ok": True, "job_id": job["id"], "publish_at": job["publish_at"]}


async def _action_queue(context, is_admin: bool) -> dict:
    if not is_admin:
        return {"ok": False, "error": "admin only"}

    jobs = await load_jobs(context)
    items = []
    for job in jobs:
        draft = job.get("draft")
        if not isinstance(draft, dict) or not isinstance(draft.get("item"), dict):
            continue

        track = TrackMatch(**draft["item"])
        items.append(
            {
                "id": job.get("id"),
                "publish_at": int(job.get("publish_at") or 0),
                "artist": track.artist,
                "title": track.title,
                "emoji": pick_track_emoji(track),
                "artwork": track.thumbnail_url,
            }
        )

    return {"ok": True, "items": items}


async def _action_unschedule(context, body: dict, is_admin: bool) -> dict:
    if not is_admin:
        return {"ok": False, "error": "admin only"}

    job_id = str(body.get("job_id") or "")
    removed = await remove_job(context, job_id)
    return {"ok": removed, "error": None if removed else "job not found"}


async def _action_reschedule(context, body: dict, is_admin: bool) -> dict:
    if not is_admin:
        return {"ok": False, "error": "admin only"}

    job_id = str(body.get("job_id") or "")
    try:
        publish_at = int(body.get("at") or 0)
    except (TypeError, ValueError):
        publish_at = 0

    now_ts = int(time.time())
    if publish_at <= now_ts or publish_at > now_ts + MAX_DELAY_SECONDS:
        return {"ok": False, "error": "bad time"}

    moved = await reschedule_job(context, job_id, publish_at)
    return {
        "ok": moved,
        "error": None if moved else "job not found",
        "publish_at": publish_at if moved else None,
    }


async def _action_stats(context, is_admin: bool) -> dict:
    if not is_admin:
        return {"ok": False, "error": "admin only"}

    stats_data = load_stats()
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        stats_data = merge_stats(stats_data, await kv.get_json(STATS_KV_KEY))

    return {
        "ok": True,
        "stats": {
            "posts": stats_data.get("posts", 0),
            "song": stats_data.get("song", 0),
            "album": stats_data.get("album", 0),
            "podcast": stats_data.get("podcast", 0),
            "videos": stats_data.get("videos", 0),
            "radios": stats_data.get("radios", 0),
            "playlists": stats_data.get("playlists", 0),
            "artists": stats_data.get("artists", 0),
            "collections": stats_data.get("collections", 0),
            "top_users": _top_entries(stats_data.get("users")),
            "top_chats": _top_entries(stats_data.get("chats")),
        },
    }


async def _action_history(context, user_id: int, is_admin: bool) -> dict:
    items = await _load_history_items(context, user_id)
    posted_dates: list[str | None] = [None] * len(items)
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None and items:
        keys = [
            _release_fingerprint(str(item.get("artist") or ""), str(item.get("title") or ""))
            for item in items
        ]
        posted_dates = await kv.mget(keys)

    return {
        "ok": True,
        "is_admin": is_admin,
        "items": [
            {**item, "posted": posted_dates[index]}
            for index, item in enumerate(items)
        ],
    }


async def _acquire_kv_lock(
    kv: KVStore, key: str, *, tries: int = 5, delay: float = 0.1, ttl: int = 10
) -> bool:
    for attempt in range(tries):
        if await kv.set(key, "1", ttl_seconds=ttl, nx=True):
            return True
        if attempt < tries - 1:
            await asyncio.sleep(delay)
    return False


async def _record_history(context, user_id: int, track: TrackMatch, source_url: str) -> None:
    entry = {
        "artist": track.artist,
        "title": track.title,
        "kind": track.kind,
        "emoji": pick_track_emoji(track),
        "artwork": track.thumbnail_url,
        "source_url": source_url,
        "ts": int(time.time()),
    }
    fingerprint = _release_fingerprint(track.artist, track.title)
    kv: KVStore | None = context.application.bot_data.get("kv_store")

    # Guard the load→modify→save against concurrent requests from the same user
    # racing on the shared Redis key (fallback: unlocked, single-instance memory).
    lock_key = f"hist:lock:{user_id}"
    locked = await _acquire_kv_lock(kv, lock_key) if kv is not None else False
    try:
        items = await _load_history_items(context, user_id)
        items = [
            item
            for item in items
            if _release_fingerprint(str(item.get("artist") or ""), str(item.get("title") or ""))
            != fingerprint
        ]
        items = [entry, *items][:MAX_HISTORY_ITEMS]

        histories: dict = context.application.bot_data.setdefault("webapp_history", {})
        histories[user_id] = items
        if kv is not None:
            await kv.set_json(f"hist:{user_id}", items, ttl_seconds=HISTORY_TTL_SECONDS)
    finally:
        if locked:
            await kv.delete(lock_key)


async def _load_history_items(context, user_id: int) -> list[dict]:
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        items = await kv.get_json(f"hist:{user_id}")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)][:MAX_HISTORY_ITEMS]

    histories: dict = context.application.bot_data.setdefault("webapp_history", {})
    return list(histories.get(user_id) or [])


# The crate lives on the client: the Mini App keeps the authoritative list in
# CloudStorage and sends it with every request. The server still mirrors it into
# KV / instance memory as a convenience, but never depends on that copy being
# complete — which is what made collections lose every track but the last one on
# serverless (each warm instance saw only its own slice of memory).
_CRATE_ITEM_KEYS = (
    "title",
    "artist",
    "kind",
    "release_format",
    "genre",
    "page_url",
    "release_year",
    "thumbnail_url",
)


def _is_web_url(value: object) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _compact_track_data(item: dict) -> dict:
    """Shrink a track dict to the handful of fields a collection post needs.

    Small enough that a full crate fits in a single CloudStorage value, so the
    client can persist and resend it without chunking.
    """
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    # Only http(s) URLs may become inline-button destinations — never trust a
    # client-supplied scheme (defense-in-depth; Telegram also rejects the rest).
    page_url = item.get("page_url")
    if not _is_web_url(page_url):
        page_url = None
    if not page_url:
        for value in links.values():
            if _is_web_url(value):
                page_url = value
                break

    return {
        "title": str(item.get("title") or ""),
        "artist": str(item.get("artist") or ""),
        "kind": str(item.get("kind") or "song"),
        "release_format": item.get("release_format") or None,
        "genre": item.get("genre") or None,
        "page_url": page_url or None,
        "release_year": item.get("release_year") or None,
        "thumbnail_url": item.get("thumbnail_url") or None,
    }


def _track_from_item(item: dict) -> TrackMatch:
    return TrackMatch(
        title=str(item.get("title") or ""),
        artist=str(item.get("artist") or ""),
        links=item.get("links") if isinstance(item.get("links"), dict) else {},
        page_url=item.get("page_url"),
        release_year=item.get("release_year"),
        kind=str(item.get("kind") or "song"),
        release_format=item.get("release_format"),
        thumbnail_url=item.get("thumbnail_url"),
        genre=item.get("genre"),
    )


def _coerce_crate_items(raw: object) -> list[dict]:
    """Validate a client-provided crate list into deduped, capped track dicts."""
    items: list[dict] = []
    if not isinstance(raw, list):
        return items

    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        compact = _compact_track_data(entry)
        if not (compact["artist"] or compact["title"]):
            continue
        fingerprint = _release_fingerprint(compact["artist"], compact["title"])
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        items.append(compact)
        if len(items) >= MAX_CRATE_ITEMS:
            break

    return items


def _crate_view(items: list[dict]) -> dict:
    views = []
    for item in items:
        compact = _compact_track_data(item)
        views.append(
            {
                "artist": compact["artist"],
                "title": compact["title"],
                "emoji": pick_track_emoji(_track_from_item(compact)),
                "artwork": compact["thumbnail_url"],
                "data": compact,
            }
        )

    return {"ok": True, "count": len(items), "max": MAX_CRATE_ITEMS, "items": views}


async def _load_crate(context, user_id: int) -> list[dict]:
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        items = await kv.get_json(f"crate:{user_id}")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)][:MAX_CRATE_ITEMS]

    crates: dict = context.application.bot_data.setdefault("webapp_crate", {})
    return list(crates.get(user_id) or [])


async def _save_crate(context, user_id: int, items: list[dict]) -> None:
    crates: dict = context.application.bot_data.setdefault("webapp_crate", {})
    crates[user_id] = items
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(f"crate:{user_id}", items, ttl_seconds=CRATE_TTL_SECONDS)


async def _crate_base_items(context, body: dict, user_id: int) -> list[dict]:
    """The authoritative crate for a request: the client's list when it sent one,
    otherwise the server-side mirror (Redis / instance memory)."""
    if "items" in body:
        return _coerce_crate_items(body.get("items"))
    return [_compact_track_data(item) for item in await _load_crate(context, user_id)]


async def _crate_response(context, user_id: int) -> dict:
    items = [_compact_track_data(item) for item in await _load_crate(context, user_id)]
    return _crate_view(items)


async def _action_crate_add(context, body: dict, user_id: int) -> dict:
    raw_item = body.get("item")
    if isinstance(raw_item, dict):
        new_item = _compact_track_data(raw_item)
    else:
        draft_id = str(body.get("draft_id") or "")
        draft = await _load_draft(context, draft_id)
        if draft is None or draft.get("chat_id") != user_id:
            return {"ok": False, "error": "draft not found"}
        new_item = _compact_track_data(draft["item"])

    if not (new_item["artist"] or new_item["title"]):
        return {"ok": False, "error": "draft not found"}

    items = await _crate_base_items(context, body, user_id)
    fingerprint = _release_fingerprint(new_item["artist"], new_item["title"])
    if any(
        _release_fingerprint(item["artist"], item["title"]) == fingerprint
        for item in items
    ):
        await _save_crate(context, user_id, items)
        return _crate_view(items)

    if len(items) >= MAX_CRATE_ITEMS:
        return {"ok": False, "error": "crate full"}

    items = [*items, new_item]
    await _save_crate(context, user_id, items)
    return _crate_view(items)


async def _action_crate_remove(context, body: dict, user_id: int) -> dict:
    try:
        index = int(body.get("index"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad index"}

    items = await _crate_base_items(context, body, user_id)
    if not 0 <= index < len(items):
        return {"ok": False, "error": "bad index"}

    items.pop(index)
    await _save_crate(context, user_id, items)
    return _crate_view(items)


async def _action_crate_order(context, body: dict, user_id: int) -> dict:
    indices = body.get("indices")
    items = await _crate_base_items(context, body, user_id)
    if (
        not isinstance(indices, list)
        or sorted(index for index in indices if isinstance(index, int))
        != list(range(len(items)))
    ):
        return {"ok": False, "error": "bad order"}

    items = [items[index] for index in indices]
    await _save_crate(context, user_id, items)
    return _crate_view(items)


async def _action_crate_deliver(
    context, action: str, user_id: int, is_admin: bool, body: dict | None = None
) -> dict:
    from music_links_bot.bot import _build_collection_keyboard, _build_link_preview_options

    if action == "crate_publish" and not is_admin:
        return {"ok": False, "error": "admin only"}

    items = await _crate_base_items(context, body or {}, user_id)
    if len(items) < 2:
        return {"ok": False, "error": "need more tracks"}

    tracks = [_track_from_item(item) for item in items]
    text = format_collection_message(tracks, include_hashtags=True)

    if action == "crate_publish":
        target = context.application.bot_data.get("publish_chat_id") or f"@{CHANNEL_USERNAME}"
        include_channel_button = str(target).lstrip("@").casefold() != CHANNEL_USERNAME
    else:
        target = user_id
        include_channel_button = True

    keyboard = _build_collection_keyboard(
        tracks, include_channel_button=include_channel_button
    )
    try:
        await context.bot.send_message(
            chat_id=target,
            text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=_build_link_preview_options(
                _select_preview_url(tracks[0].links, context) or tracks[0].thumbnail_url,
                prefer_large_media=True,
            ),
            reply_markup=keyboard,
        )
    except Exception:
        LOGGER.exception("Crate deliver failed")
        return {"ok": False, "error": "send failed"}

    if action == "crate_publish":
        for track in tracks:
            _schedule_mark_posted(context, track)
        await _save_crate(context, user_id, [])
    else:
        # keep the server mirror in step with what was just sent
        await _save_crate(context, user_id, items)

    return {"ok": True}


async def _lookup_track_preview(context, track: TrackMatch) -> str | None:
    if track.kind != "song":
        return None

    search_client = context.application.bot_data.get("search_client")
    if search_client is None:
        return None

    try:
        return await search_client.lookup_preview(track.artist, track.title)
    except Exception:
        LOGGER.debug("Preview lookup crashed", exc_info=True)
        return None


def _apply_draft_patch(draft: dict, body: dict) -> None:
    for flag in ("hashtags", "quote", "large_preview", "as_photo"):
        if isinstance(body.get(flag), bool):
            draft[flag] = body[flag]

    if "cta" in body:
        cta = body.get("cta")
        if isinstance(cta, str) and cta.strip():
            draft["custom_cta"] = " ".join(cta.split())[:MAX_CUSTOM_CTA_LENGTH]
        else:
            draft.pop("custom_cta", None)

    if "tags" in body:
        tags = body.get("tags")
        if isinstance(tags, list):
            draft["custom_tags"] = [
                tag
                for tag in (normalize_hashtag(value) for value in tags[:MAX_CUSTOM_TAGS])
                if tag
            ]
        else:
            draft.pop("custom_tags", None)

    if "platforms" in body:
        platforms = body.get("platforms")
        selection = [
            key
            for key in (platforms if isinstance(platforms, list) else [])
            if isinstance(key, str) and key in PLATFORM_LABELS
        ]
        if selection:
            draft["platforms"] = selection
        else:
            draft.pop("platforms", None)


async def _draft_response(context, draft_id: str, draft: dict, is_admin: bool) -> dict:
    track = TrackMatch(**draft["item"])
    cta_key = {"album": "album_cta", "podcast": "podcast_cta"}.get(track.kind, "track_cta")
    custom_cta = draft.get("custom_cta")
    custom_tags = draft.get("custom_tags")

    available = [key for key in PLATFORM_LABELS if track.links.get(key)]
    selection = [
        key
        for key in (draft.get("platforms") or [])
        if isinstance(key, str) and key in available
    ]
    if selection:
        ordered = [*selection, *(key for key in available if key not in selection)]
        enabled = set(selection)
    else:
        ordered = available
        enabled = set(available)

    platforms = [
        {
            "key": platform_key,
            "label": PLATFORM_LABELS[platform_key],
            "url": track.links[platform_key],
            "style": PLATFORM_BUTTON_STYLES.get(platform_key, "primary"),
            "enabled": platform_key in enabled,
        }
        for platform_key in ordered
    ]

    auto_hashtags = build_auto_hashtags(track)
    if isinstance(custom_tags, list):
        hashtags = " ".join(custom_tags)
    else:
        hashtags = auto_hashtags

    return {
        "ok": True,
        "draft_id": draft_id,
        "ttl": DRAFT_TTL_SECONDS,
        "flags": {
            "hashtags": bool(draft.get("hashtags")),
            "quote": bool(draft.get("quote")),
            "large_preview": bool(draft.get("large_preview")),
            "as_photo": bool(draft.get("as_photo")),
            "has_prefix": bool(draft.get("prefix")),
        },
        "can_publish": bool(is_admin and draft.get("can_publish", True)),
        "release": {
            "artist": track.artist,
            "title": track.title,
            "kind": track.kind,
            "emoji": pick_track_emoji(track),
            "year": track.release_year,
            "genre": track.genre,
            "artwork": track.thumbnail_url,
            "page_url": track.page_url,
            "preview": draft.get("preview"),
            "preview_pending": bool(draft.get("preview_pending")),
            "cta": custom_cta
            or pick_phrase(cta_key, f"{track.artist}:{track.title}:{track.kind}"),
            "cta_custom": bool(custom_cta),
            "hashtags": hashtags,
            "auto_hashtags": auto_hashtags,
            "tags_custom": isinstance(custom_tags, list),
            "platforms": platforms,
        },
    }


def _top_entries(value: object, *, limit: int = 8) -> list[dict]:
    if not isinstance(value, dict):
        return []

    entries = [entry for entry in value.values() if isinstance(entry, dict)]
    entries.sort(key=lambda item: int(item.get("count") or 0), reverse=True)
    return [
        {"label": str(entry.get("label") or "?"), "count": int(entry.get("count") or 0)}
        for entry in entries[:limit]
    ]


def _upscale_artwork(url: str | None) -> str | None:
    if not url:
        return None

    return url.replace("100x100", "300x300").replace("60x60", "300x300")
