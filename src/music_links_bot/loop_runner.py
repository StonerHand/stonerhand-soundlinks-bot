from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


def start_background_loop(name: str) -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run() -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()

    thread = threading.Thread(target=run, name=name, daemon=True)
    thread.start()
    ready.wait(timeout=5)
    if not thread.is_alive():
        raise RuntimeError(f"background event loop {name} did not start")
    return loop, thread


def run_on_loop(
    loop: asyncio.AbstractEventLoop,
    awaitable: Awaitable[T],
    *,
    timeout: float,
) -> T:
    future = asyncio.run_coroutine_threadsafe(awaitable, loop)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise asyncio.TimeoutError from exc


def stop_background_loop(
    loop: asyncio.AbstractEventLoop | None,
    thread: threading.Thread | None,
) -> None:
    if loop is None or thread is None:
        return
    if loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
