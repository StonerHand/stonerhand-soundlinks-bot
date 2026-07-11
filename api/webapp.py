from __future__ import annotations

import asyncio
import json
import logging
import threading
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
    _find_posted_date,
    _load_draft,
    _lookup_tracks,
    _publish_draft,
    _render_track_draft,
    _schedule_mark_posted,
    _select_preview_url,
    _store_draft,
    build_application,
)
from music_links_bot.config import Settings
from music_links_bot.constants import PLATFORM_BUTTON_STYLES, PLATFORM_LABELS
from music_links_bot.formatter import build_auto_hashtags, pick_track_emoji
from music_links_bot.i18n import resolve_lang
from music_links_bot.models import TrackMatch
from music_links_bot.phrases import pick_phrase
from music_links_bot.search import SearchLookupError, normalize_search_query
from music_links_bot.url_utils import extract_supported_urls
from music_links_bot.webapp_auth import validate_init_data
from telegram.constants import ParseMode

LOGGER = logging.getLogger(__name__)
MAX_BODY_BYTES = 64 * 1024

_STATE_LOCK = threading.Lock()
_LOOP: asyncio.AbstractEventLoop | None = None
_APPLICATION = None
_SETTINGS: Settings | None = None


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send_json({"ok": True, "service": "StonerHand studio API"})

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

    if action in {"send", "publish"}:
        return await _action_deliver(context, action, body, user_id, is_admin)

    return {"ok": False, "error": "unknown action"}


async def _action_resolve(context, body: dict, user_id: int, is_admin: bool, lang: str) -> dict:
    query = str(body.get("query") or "").strip()
    bot_data = context.application.bot_data
    source_urls = extract_supported_urls(query)[:1]
    if not source_urls:
        search_query = normalize_search_query(query)
        if search_query is None:
            return {"ok": False, "error": "empty query"}

        try:
            source_urls = [
                await bot_data["search_client"].search_release_url(search_query)
            ]
        except SearchLookupError:
            return {"ok": False, "error": "not found"}

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
    }
    draft_id = secrets.token_hex(8)
    await _store_draft(context, draft_id, draft)
    return _draft_response(draft_id, draft, is_admin)


async def _action_draft(context, body: dict, user_id: int, is_admin: bool) -> dict:
    draft_id = str(body.get("draft_id") or "")
    draft = await _load_draft(context, draft_id)
    if draft is None or draft.get("chat_id") != user_id:
        return {"ok": False, "error": "draft not found"}

    return _draft_response(draft_id, draft, is_admin)


async def _action_deliver(context, action: str, body: dict, user_id: int, is_admin: bool) -> dict:
    draft_id = str(body.get("draft_id") or "")
    draft = await _load_draft(context, draft_id)
    if draft is None or draft.get("chat_id") != user_id:
        return {"ok": False, "error": "draft not found"}

    for flag in ("hashtags", "quote", "large_preview"):
        if isinstance(body.get(flag), bool):
            draft[flag] = body[flag]

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


def _draft_response(draft_id: str, draft: dict, is_admin: bool) -> dict:
    track = TrackMatch(**draft["item"])
    cta_key = {"album": "album_cta", "podcast": "podcast_cta"}.get(track.kind, "track_cta")
    platforms = [
        {
            "key": platform_key,
            "label": PLATFORM_LABELS[platform_key],
            "url": track.links[platform_key],
            "style": PLATFORM_BUTTON_STYLES.get(platform_key, "primary"),
        }
        for platform_key in PLATFORM_LABELS
        if track.links.get(platform_key)
    ]
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
            "cta": pick_phrase(cta_key, f"{track.artist}:{track.title}:{track.kind}"),
            "hashtags": build_auto_hashtags(track),
            "platforms": platforms,
        },
    }
