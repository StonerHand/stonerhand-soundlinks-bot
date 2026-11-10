"""Work that must not hold a card back: it runs beside the reply."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

LOGGER = logging.getLogger(__name__)
_TASKS_KEY = "background_tasks"


def run_behind(bot_data: dict, work: Coroutine[Any, Any, Any], *, what: str) -> None:
    """Start ``work`` without waiting for it; a failure is logged, not raised.

    The set keeps every task referenced until it is done, and closing the
    application waits for the ones still running (finish_background).
    """
    pending: set[asyncio.Task[Any]] = bot_data.setdefault(_TASKS_KEY, set())
    task = asyncio.create_task(work)
    pending.add(task)

    def done(finished: asyncio.Task[Any]) -> None:
        pending.discard(finished)
        if not finished.cancelled() and finished.exception() is not None:
            LOGGER.warning("%s failed: %s", what, type(finished.exception()).__name__)

    task.add_done_callback(done)


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
