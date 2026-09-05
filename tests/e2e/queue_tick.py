"""Authenticated queue tick. No redirects and no publication payload in logs."""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def tick(base_url: str, secret: str) -> int:
    origin = urlparse(base_url)
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username is not None
        or origin.password is not None
        or origin.port not in {None, 443}
        or origin.path not in {"", "/"}
        or origin.query
        or origin.fragment
        or not secret.strip()
    ):
        raise ValueError("A public HTTPS origin and queue secret are required")
    request = Request(
        base_url.rstrip("/") + "/api/queue_worker",
        headers={"Authorization": f"Bearer {secret.strip()}"},
    )
    with build_opener(NoRedirects).open(request, timeout=30) as response:  # nosec B310
        payload = json.loads(response.read(16_384))
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("Queue worker rejected the tick")
    published = payload.get("published")
    if not isinstance(published, int) or isinstance(published, bool) or published < 0:
        raise ValueError("Invalid queue worker result")
    return published


def main() -> int:
    try:
        count = tick(
            os.getenv("QUEUE_BASE_URL", "https://tg-bot-sh.vercel.app"),
            os.getenv("CRON_SECRET", ""),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Queue tick failed: {type(exc).__name__}")
        return 1
    print(f"Queue tick OK: published={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
