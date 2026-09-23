"""Warm-loop HTTP pools; never share a transport between event loops."""

from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

import httpx

from music_links_bot.constants import HTTP_USER_AGENT

_CLIENTS: WeakKeyDictionary = WeakKeyDictionary()


def shared_client(purpose: str, *, timeout: float = 8.0) -> httpx.AsyncClient:
    clients = _CLIENTS.setdefault(asyncio.get_running_loop(), {})
    key = (purpose, timeout)
    if key not in clients:
        clients[key] = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=3.0),
            headers={"User-Agent": HTTP_USER_AGENT},
            follow_redirects=False,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )
    return clients[key]


async def close_shared_clients() -> None:
    clients = _CLIENTS.pop(asyncio.get_running_loop(), {})
    await asyncio.gather(
        *(client.aclose() for client in clients.values()), return_exceptions=True
    )
