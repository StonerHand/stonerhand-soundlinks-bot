"""Stop one private lookup, including across warm serverless instances."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace

from music_links_bot.lookup_models import LookupBundle
from music_links_bot.lookup_recovery import capture_sources, completed_sources

CONTROL_TTL = 90
current_control: ContextVar[SearchControl | None] = ContextVar(
    "search_control", default=None
)
live_sources: ContextVar[dict | None] = ContextVar("live_lookup_sources", default=None)


@dataclass
class SearchControl:
    chat_id: int
    draft_id: int
    bot_data: dict
    nonce: str = field(default_factory=lambda: secrets.token_hex(12))
    stopped: asyncio.Event = field(default_factory=asyncio.Event)
    completed: dict = field(default_factory=dict)
    progress: object = None

    @property
    def key(self):
        return f"lookup-control:v1:{self.chat_id}:{self.draft_id}"


class LookupStopped(Exception):
    def __init__(self, completed):
        super().__init__("Lookup stopped by its owner")
        self.completed = completed


def observe_result(source_url, item, *, field_name, provider):
    """Retain verified source results before slower siblings finish."""
    from music_links_bot.lookup_models import SourceStatus, item_label
    from music_links_bot.models import (
        ArtistMatch,
        PlaylistMatch,
        RadioMatch,
        TrackMatch,
        VideoMatch,
    )
    from music_links_bot.url_utils import direct_platform_links

    expected = {
        "tracks": TrackMatch,
        "videos": VideoMatch,
        "radios": RadioMatch,
        "playlists": PlaylistMatch,
        "artists": ArtistMatch,
    }
    sink = live_sources.get()
    if sink is None or not isinstance(item, expected[field_name]):
        return
    if field_name == "tracks":
        links = direct_platform_links(item.links)
        if not links:
            return
        item = replace(item, links=links)
    bundle = LookupBundle([], [], [], [], [], [])
    getattr(bundle, field_name).append(item)
    bundle.statuses = [
        SourceStatus(source_url, provider, "success", label=item_label(item))
    ]
    sink.update(capture_sources(bundle))


async def observe_source(awaitable, source_url, *, field_name, provider):
    item = await awaitable
    observe_result(source_url, item, field_name=field_name, provider=provider)
    return item


@asynccontextmanager
async def search_control(bot_data, message):
    if not getattr(message, "message_id", None):
        yield None
        return
    control = SearchControl(message.chat_id, message.message_id, bot_data)
    control.completed.update(completed_sources.get() or {})
    registry = bot_data.setdefault("lookup_controls", {})
    registry[control.key] = control
    kv = bot_data.get("kv_store")
    token = current_control.set(control)
    try:
        if kv is not None:
            await kv.set(control.key, control.nonce, ttl_seconds=CONTROL_TTL)
        yield control
    finally:
        current_control.reset(token)
        if registry.get(control.key) is control:
            registry.pop(control.key, None)
        if kv is not None:
            await kv.delete_if_value(control.key, control.nonce)
            await kv.delete_if_value(control.key, "stopped:" + control.nonce)


async def stop_lookup(bot_data, *, chat_id, draft_id):
    """Only an existing exact draft can be stopped; stale buttons do nothing."""
    if not isinstance(chat_id, int) or chat_id <= 0:
        return False
    if not isinstance(draft_id, int) or draft_id <= 0:
        return False
    key = f"lookup-control:v1:{chat_id}:{draft_id}"
    control = bot_data.get("lookup_controls", {}).get(key)
    if control is not None:
        control.stopped.set()
    kv = bot_data.get("kv_store")
    marked = False
    if kv is not None:
        active = await kv.get(key)
        if active and not active.startswith("stopped:"):
            marked = await kv.compare_set_required(
                key, active, "stopped:" + active, ttl_seconds=CONTROL_TTL
            )
    return control is not None or marked


async def _wait_for_stop(control):
    kv = control.bot_data.get("kv_store")
    while not control.stopped.is_set():
        if kv is not None and await kv.get(control.key) == "stopped:" + control.nonce:
            control.stopped.set()
            break
        try:
            await asyncio.wait_for(control.stopped.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass


async def interruptible(awaitable):
    control = current_control.get()
    if control is None:
        return await awaitable
    from music_links_bot.bot_progress import _PLACEHOLDER

    async def work():
        try:
            return await awaitable
        finally:
            control.progress = _PLACEHOLDER.get()

    worker = asyncio.create_task(work())
    watcher = asyncio.create_task(_wait_for_stop(control))
    try:
        await asyncio.wait((worker, watcher), return_when=asyncio.FIRST_COMPLETED)
        if watcher.done():
            await watcher
        if control.stopped.is_set():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            raise LookupStopped(dict(control.completed))
        return await worker
    finally:
        for task in (worker, watcher):
            if not task.done():
                task.cancel()
        await asyncio.gather(worker, watcher, return_exceptions=True)
        _PLACEHOLDER.set(control.progress)
