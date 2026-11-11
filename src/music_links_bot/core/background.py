"""Work that must not hold a card back: it runs beside the reply."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

LOGGER = logging.getLogger(__name__)
_TASKS_KEY = "background_tasks"
UPDATE_GRACE_SECONDS = 5.0
_update_tasks: ContextVar[list[asyncio.Task[Any]] | None] = ContextVar(
    "update_background_tasks", default=None
)


def run_behind(bot_data: dict, work: Coroutine[Any, Any, Any], *, what: str) -> None:
    """Start ``work`` without waiting for it; a failure is logged, not raised.

    The set keeps every task referenced until it is done, and closing the
    application waits for the ones still running (finish_background).
    """
    pending: set[asyncio.Task[Any]] = bot_data.setdefault(_TASKS_KEY, set())
    task = asyncio.create_task(work)
    pending.add(task)
    of_this_update = _update_tasks.get()
    if of_this_update is not None:
        of_this_update.append(task)

    def done(finished: asyncio.Task[Any]) -> None:
        pending.discard(finished)
        if not finished.cancelled() and finished.exception() is not None:
            LOGGER.warning("%s failed: %s", what, type(finished.exception()).__name__)

    task.add_done_callback(done)


@asynccontextmanager
async def background_finished(
    grace: float = UPDATE_GRACE_SECONDS,
) -> AsyncIterator[None]:
    """What one update started with run_behind lands before that update ends.

    A serverless instance may be frozen the moment it answers. A request cut
    in half there would resume only with the next update, and whoever needed
    its answer would wait on a dead connection.
    """
    started: list[asyncio.Task[Any]] = []
    token = _update_tasks.set(started)
    try:
        yield
    finally:
        _update_tasks.reset(token)
        unfinished = [task for task in started if not task.done()]
        if unfinished:
            await asyncio.wait(unfinished, timeout=grace)


async def finish_background(bot_data: dict) -> None:
    """Let the work started with run_behind land."""
    pending = list(bot_data.get(_TASKS_KEY, ()))
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def quiet(task: asyncio.Task[Any]) -> None:
    """Done-callback for a task that may end with nobody waiting for it: its
    failure is read here instead of being reported as never retrieved."""
    if not task.cancelled():
        task.exception()
