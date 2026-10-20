"""One request per key: concurrent callers share the task already running."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")
Tasks = dict[str, "asyncio.Task[Any]"]


async def shared(
    inflight: Tasks, key: str, start: Callable[[], Coroutine[Any, Any, T]]
) -> T:
    pending = inflight.get(key)
    if pending is not None:
        return await asyncio.shield(pending)
    task = asyncio.create_task(start())
    inflight[key] = task
    task.add_done_callback(lambda done: forget(inflight, key, done))
    try:
        return await asyncio.shield(task)
    finally:
        if task.done():
            forget(inflight, key, task)


def forget(inflight: Tasks, key: str, task: asyncio.Task[Any]) -> None:
    """Drop a finished task even if its waiter timed out."""
    if inflight.get(key) is task:
        inflight.pop(key, None)
    if task.done() and not task.cancelled():
        # Reading the exception keeps a cancelled waiter from leaving a
        # "Task exception was never retrieved" warning behind.
        task.exception()


async def cancel_all(inflight: Tasks) -> None:
    pending = list(inflight.values())
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    inflight.clear()
