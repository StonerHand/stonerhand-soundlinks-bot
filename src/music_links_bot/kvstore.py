from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from music_links_bot.constants import HTTP_USER_AGENT

LOGGER = logging.getLogger(__name__)


class KVStore:
    """Tiny async client for the Upstash Redis REST API.

    Vercel KV exposes the same protocol, so both UPSTASH_REDIS_REST_* and
    KV_REST_API_* credentials work. Every method swallows transport errors:
    the bot must stay fully functional when Redis is down or not configured.
    """

    def __init__(self, base_url: str, token: str, *, timeout: float = 3.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": HTTP_USER_AGENT,
            },
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=httpx.Timeout(timeout, connect=2.0),
        )

    @classmethod
    def from_env(cls) -> "KVStore | None":
        base_url = (
            os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
            or os.getenv("KV_REST_API_URL", "").strip()
        )
        token = (
            os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
            or os.getenv("KV_REST_API_TOKEN", "").strip()
        )
        if not base_url or not token:
            return None

        return cls(base_url, token)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, key: str) -> str | None:
        result = await self._command(["GET", key])
        return result if isinstance(result, str) else None

    async def set(
        self,
        key: str,
        value: str,
        *,
        ttl_seconds: int | None = None,
        nx: bool = False,
    ) -> bool:
        command: list[str] = ["SET", key, value]
        if nx:
            command.append("NX")
        if ttl_seconds is not None:
            command += ["EX", str(ttl_seconds)]

        return await self._command(command) == "OK"

    async def delete(self, key: str) -> None:
        await self._command(["DEL", key])

    async def delete_if_value(self, key: str, expected_value: str) -> bool:
        """Release a lease only when it is still owned by ``expected_value``.

        A plain ``DEL`` can remove a newer owner's lock when the original lease
        expired while work was still running. The tiny Lua script keeps lock
        release atomic on Redis and makes delayed serverless invocations safe.
        """
        script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        result = await self._command(
            ["EVAL", script, "1", key, expected_value]
        )
        return result == 1

    async def mget(self, keys: list[str]) -> list[str | None]:
        if not keys:
            return []

        result = await self._command(["MGET", *keys])
        if not isinstance(result, list):
            return [None] * len(keys)

        return [value if isinstance(value, str) else None for value in result]

    async def get_json(self, key: str) -> Any | None:
        raw_value = await self.get(key)
        if raw_value is None:
            return None

        try:
            return json.loads(raw_value)
        except ValueError:
            return None

    async def set_json(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> bool:
        return await self.set(
            key,
            json.dumps(value, ensure_ascii=False),
            ttl_seconds=ttl_seconds,
        )

    async def _command(self, command: list[str]) -> Any | None:
        try:
            response = await self._client.post("/", json=command)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            LOGGER.debug("KV command failed: %s", command[0], exc_info=True)
            return None

        if isinstance(payload, dict):
            return payload.get("result")

        return None
