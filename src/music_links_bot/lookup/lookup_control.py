"""Stop one private lookup, including across warm serverless instances."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from music_links_bot.lookup.lookup_models import LookupBundle
from music_links_bot.lookup.lookup_recovery import capture_sources, completed_sources

if TYPE_CHECKING:  # bot_progress imports this module at runtime
    from music_links_bot.lookup.bot_progress import ProgressState

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
    progress: ProgressState | None = None
    # Writing this lookup to Redis, so Stop on another instance can find it.
    published: asyncio.Task | None = None

    @property
    def key(self):
        return f"lookup-control:v1:{self.chat_id}:{self.draft_id}"


class LookupStopped(Exception):
    def __init__(self, completed):
        super().__init__("Lookup stopped by its owner")
        self.completed = completed


def observe_result(source_url, item, *, field_name, provider):
    """Retain verified source results before slower siblings finish."""
    from music_links_bot.core.models import TrackMatch
    from music_links_bot.core.url_utils import direct_platform_links
    from music_links_bot.lookup.lookup_models import (
        ITEM_TYPES,
        SourceStatus,
        item_label,
    )

    sink = live_sources.get()
    if sink is None or not isinstance(item, ITEM_TYPES[field_name]):
        return
    if isinstance(item, TrackMatch):
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
    # Another instance learns about this lookup only when Stop is pressed,
    # half a second at the earliest: publishing it runs beside the lookup
    # instead of in front of it.
    if kv is not None:
        control.published = asyncio.create_task(
            kv.set(control.key, control.nonce, ttl_seconds=CONTROL_TTL)
        )
    try:
        yield control
    finally:
        current_control.reset(token)
        if registry.get(control.key) is control:
            registry.pop(control.key, None)
        if kv is not None:
            await published(control)
            await asyncio.gather(
                kv.delete_if_value(control.key, control.nonce),
                kv.delete_if_value(control.key, "stopped:" + control.nonce),
            )


async def published(control: SearchControl | None) -> None:
    """Wait until Stop can reach this lookup from any instance."""
    if control is not None and control.published is not None:
        await asyncio.gather(control.published, return_exceptions=True)


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
    """Stop from this instance sets the event; from another one, Redis.
    Nobody can press Stop before the progress line exists, so the first
    look at Redis waits half a second: fast lookups never make one."""
    kv = control.bot_data.get("kv_store")
    while not control.stopped.is_set():
        try:
            await asyncio.wait_for(control.stopped.wait(), timeout=0.5)
        except TimeoutError:
            pass
        else:
            break
        if kv is not None and await kv.get(control.key) == "stopped:" + control.nonce:
            control.stopped.set()


async def interruptible(awaitable):
    control = current_control.get()
    if control is None:
        return await awaitable
    from music_links_bot.lookup.bot_progress import _PLACEHOLDER

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
