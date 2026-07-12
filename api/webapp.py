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
from music_links_bot.formatter import build_auto_hashtags, pick_track_emoji
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
                published = loop.run_until_complete(process_due_jobs(context))
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

        try:
            with _STATE_LOCK:
                loop, application, settings = _ensure_application()
                user = validate_init_data(
                    str(payload.get("init_data") or ""),
                    settings.bot_token,
                )
                if user is None:
                    self._send_json(
                        {"ok": False, "error": "unauthorized"},
                        HTTPStatus.UNAUTHORIZED,
                    )
                    return

                result = loop.run_until_complete(
                    _handle_action(application, settings, user, payload)
                )
        except Exception:
            LOGGER.exception("Studio request failed")
            self._send_json({"ok": False, "error": "internal"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

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


async def _handle_action(application, settings: Settings, user: dict, payload: dict) -> dict:
    context = SimpleNamespace(application=application, bot=application.bot)
    action = str(payload.get("action") or "")
    body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    user_id = int(user["id"])
    is_admin = settings.admin_chat_id is not None and user_id == settings.admin_chat_id
    lang = resolve_lang(user.get("language_code"))

    if action == "resolve":
        return await _action_resolve(context, body, user_id, is_admin, lang)

    if action == "draft":
        return await _action_draft(context, body, user_id, is_admin)

    if action == "update":
        return await _action_update(context, body, user_id, is_admin)

    if action == "history":
        return await _action_history(context, user_id, is_admin)

    if action in {"send", "publish"}:
        return await _action_deliver(context, action, body, user_id, is_admin)

    if action == "schedule":
        return await _action_schedule(context, body, user_id, is_admin)

    if action == "queue":
        return await _action_queue(context, is_admin)

    if action == "unschedule":
        return await _action_unschedule(context, body, is_admin)

    if action == "stats":
        return await _action_stats(context, is_admin)

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
        "preview": candidate_preview
        or await _lookup_track_preview(context, track),
    }
    draft_id = secrets.token_hex(8)
    await _store_draft(context, draft_id, draft)
    await _record_history(context, user_id, track, source_urls[0])
    return await _draft_response(context, draft_id, draft, is_admin)


async def _action_draft(context, body: dict, user_id: int, is_admin: bool) -> dict:
    draft_id = str(body.get("draft_id") or "")
    draft = await _load_draft(context, draft_id)
    if draft is None or draft.get("chat_id") != user_id:
        return {"ok": False, "error": "draft not found"}

    if "preview" not in draft:
        # Drafts born in the chat editor arrive without an audio preview.
        draft["preview"] = await _lookup_track_preview(
            context, TrackMatch(**draft["item"])
        )
        await _store_draft(context, draft_id, draft)

    return await _draft_response(context, draft_id, draft, is_admin)


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

        return {"ok": published, "error": None if published else "publish failed"}

    from music_links_bot.bot import _build_link_preview_options

    text, keyboard = _render_track_draft(draft, context, draft_id=None)
    try:
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
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(f"hist:{user_id}", items, ttl_seconds=HISTORY_TTL_SECONDS)


async def _load_history_items(context, user_id: int) -> list[dict]:
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        items = await kv.get_json(f"hist:{user_id}")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)][:MAX_HISTORY_ITEMS]

    histories: dict = context.application.bot_data.setdefault("webapp_history", {})
    return list(histories.get(user_id) or [])


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
    for flag in ("hashtags", "quote", "large_preview"):
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
