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
    _load_draft,
    _lookup_tracks,
    _publish_draft,
    _render_track_draft,
    _select_preview_url,
    _store_draft,
    build_application,
)
from music_links_bot.publication_state import (
    find_posted_date as _find_posted_date,
    mark_posted as _schedule_mark_posted,
    release_fingerprint as _release_fingerprint,
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
from music_links_bot.loop_runner import (
    run_on_loop,
    start_background_loop,
    stop_background_loop,
)
from music_links_bot.models import TrackMatch
from music_links_bot.phrases import pick_phrase
from music_links_bot.publish_queue import (
    MAX_DELAY_SECONDS,
    QueueBusyError,
    add_job,
    load_jobs,
    process_due_jobs,
    remove_job,
    reschedule_job,
)
from music_links_bot.request_guard import rate_limited, run_idempotent
from music_links_bot.search import SearchLookupError, normalize_search_query
from music_links_bot.stats import load_stats, merge_stats
from music_links_bot.studio_models import (
    MAX_CRATE_ITEMS,
    apply_draft_patch as _apply_draft_patch,
    compact_track_data as _compact_track_data,
    crate_view as _crate_view,
    top_entries as _top_entries,
    track_from_item as _track_from_item,
    upscale_artwork as _upscale_artwork,
)

from music_links_bot import studio_storage as _studio_storage

_acquire_kv_lock = _studio_storage._acquire_kv_lock
_record_history = _studio_storage._record_history
_load_history_items = _studio_storage._load_history_items
_load_crate = _studio_storage._load_crate
_save_crate = _studio_storage._save_crate
_crate_base_items = _studio_storage._crate_base_items
_crate_response = _studio_storage._crate_response

from music_links_bot.url_utils import extract_supported_urls
from music_links_bot.webapp_auth import validate_init_data
from telegram.constants import ParseMode

LOGGER = logging.getLogger(__name__)
MAX_BODY_BYTES = 64 * 1024
MAX_HISTORY_ITEMS = 10
HISTORY_TTL_SECONDS = 90 * 24 * 3600
CRATE_TTL_SECONDS = 14 * 24 * 3600
# Every event-loop run is time-bounded so one slow upstream call (Song.link,
# iTunes, Redis) can't hold the shared lock and wedge the warm instance.
ACTION_TIMEOUT_SECONDS = 25
QUEUE_TICK_TIMEOUT_SECONDS = 20
RESOLVE_RATE_LIMIT = 20
RESOLVE_RATE_WINDOW_SECONDS = 60
IDEMPOTENT_ACTIONS = frozenset(
    {
        "send",
        "publish",
        "unpublish",
        "schedule",
        "unschedule",
        "reschedule",
        "crate_add",
        "crate_remove",
        "crate_order",
        "crate_clear",
        "crate_send",
        "crate_publish",
    }
)

_STATE_LOCK = threading.Lock()
_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_THREAD: threading.Thread | None = None
_APPLICATION = None
_SETTINGS: Settings | None = None


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        # A GET doubles as a queue tick: any uptime ping (or a curious
        # browser) delivers scheduled posts whose time has come.
        published = 0
        try:
            loop, application, _settings = _ensure_application()
            context = SimpleNamespace(application=application, bot=application.bot)
            published = run_on_loop(
                loop,
                process_due_jobs(context),
                timeout=QUEUE_TICK_TIMEOUT_SECONDS,
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
            loop, application, settings = _ensure_application()
            user = validate_init_data(
                str(payload.get("init_data") or ""),
                settings.bot_token,
            )
            if user is None:
                LOGGER.info("req=%s action=%s unauthorized", req_id, action)
                self._send_json(
                    {"ok": False, "error": "unauthorized", "request_id": req_id},
                    HTTPStatus.UNAUTHORIZED,
                )
                return

            result = run_on_loop(
                loop,
                _handle_action(application, settings, user, payload),
                timeout=ACTION_TIMEOUT_SECONDS,
            )
            result.setdefault("request_id", req_id)
        except asyncio.TimeoutError:
            LOGGER.warning(
                "req=%s action=%s timed out after %.1fs",
                req_id, action, time.monotonic() - started,
            )
            self._send_json(
                {"ok": False, "error": "timeout", "retryable": True, "request_id": req_id}, HTTPStatus.GATEWAY_TIMEOUT
            )
            return
        except Exception:
            LOGGER.exception("req=%s action=%s failed", req_id, action)
            self._send_json(
                {"ok": False, "error": "internal", "retryable": True, "request_id": req_id},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
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
    global _LOOP, _LOOP_THREAD, _APPLICATION, _SETTINGS
    with _STATE_LOCK:
        if _APPLICATION is None:
            settings = Settings.from_env()
            loop, thread = start_background_loop("studio-runtime")
            try:
                application = build_application(settings)
                run_on_loop(
                    loop, application.initialize(), timeout=ACTION_TIMEOUT_SECONDS
                )
            except Exception:
                stop_background_loop(loop, thread)
                raise
            _LOOP = loop
            _LOOP_THREAD = thread
            _APPLICATION = application
            _SETTINGS = settings

    return _LOOP, _APPLICATION, _SETTINGS


async def _handle_action(application, settings: Settings, user: dict, payload: dict) -> dict:
    context = SimpleNamespace(application=application, bot=application.bot)
    action = str(payload.get("action") or "")
    body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    user_id = int(user["id"])
    is_admin = settings.admin_chat_id is not None and user_id == settings.admin_chat_id
    lang = resolve_lang(user.get("language_code"))

    if action in {"resolve", "resolve_batch"} and await rate_limited(
        context,
        scope="studio_resolve",
        subject=user_id,
        limit=RESOLVE_RATE_LIMIT,
        window_seconds=RESOLVE_RATE_WINDOW_SECONDS,
    ):
        return {"ok": False, "error": "rate_limited", "retryable": True}

    async def clear_crate() -> dict:
        await _save_crate(context, user_id, [])
        return {"ok": True, "items": []}

    handlers = {
        "resolve": lambda: _action_resolve(context, body, user_id, is_admin, lang),
        "resolve_batch": lambda: _action_resolve_batch(context, body, user_id),
        "draft": lambda: _action_draft(context, body, user_id, is_admin),
        "update": lambda: _action_update(context, body, user_id, is_admin),
        "preview": lambda: _action_preview(context, body, user_id),
        "history": lambda: _action_history(context, user_id, is_admin),
        "send": lambda: _action_deliver(context, action, body, user_id, is_admin),
        "publish": lambda: _action_deliver(context, action, body, user_id, is_admin),
        "unpublish": lambda: _action_unpublish(context, body, user_id, is_admin),
        "schedule": lambda: _action_schedule(context, body, user_id, is_admin),
        "queue": lambda: _action_queue(context, is_admin),
        "unschedule": lambda: _action_unschedule(context, body, is_admin),
        "reschedule": lambda: _action_reschedule(context, body, is_admin),
        "stats": lambda: _action_stats(context, is_admin),
        "crate": lambda: _crate_response(context, user_id),
        "crate_add": lambda: _action_crate_add(context, body, user_id),
        "crate_remove": lambda: _action_crate_remove(context, body, user_id),
        "crate_order": lambda: _action_crate_order(context, body, user_id),
        "crate_clear": clear_crate,
        "crate_send": lambda: _action_crate_deliver(
            context, action, user_id, is_admin, body
        ),
        "crate_publish": lambda: _action_crate_deliver(
            context, action, user_id, is_admin, body
        ),
    }
    execute = handlers.get(action)
    if execute is None:
        return {"ok": False, "error": "unknown_action", "retryable": False}
    if action in IDEMPOTENT_ACTIONS:
        return await run_idempotent(
            context,
            user_id=user_id,
            action=action,
            request_key=payload.get("request_id"),
            execute=execute,
        )
    return await execute()


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
            await _schedule_mark_posted(context, track)

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

    try:
        job = await add_job(context, draft, publish_at)
    except QueueBusyError:
        return {"ok": False, "error": "queue_busy", "retryable": True}
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
    try:
        removed = await remove_job(context, job_id)
    except QueueBusyError:
        return {"ok": False, "error": "queue_busy", "retryable": True}
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

    try:
        moved = await reschedule_job(context, job_id, publish_at)
    except QueueBusyError:
        return {"ok": False, "error": "queue_busy", "retryable": True}
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
            await _schedule_mark_posted(context, track)
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
