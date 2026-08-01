"""Read-only production smoke check used by the scheduled GitHub workflow."""

from __future__ import annotations

import json
import os
import sys
from urllib.request import Request, urlopen

BASE_URL = os.getenv("CANARY_BASE_URL", "https://tg-bot-sh.vercel.app").rstrip("/")
TIMEOUT_SECONDS = 20


def fetch(path: str) -> tuple[int, bytes, str]:
    request = Request(
        BASE_URL + path,
        headers={"User-Agent": "StonerHand-production-canary/1.0"},
    )
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return (
            int(response.status),
            response.read(),
            response.headers.get("content-type", ""),
        )


def main() -> int:
    failures: list[str] = []
    try:
        status, raw, content_type = fetch("/api/health")
        payload = json.loads(raw)
        if status != 200 or not payload.get("ok"):
            failures.append(f"health status={status} ok={payload.get('ok')}")
        checks = payload.get("checks") or {}
        for name in ("telegram", "webhook", "redis"):
            if not (checks.get(name) or {}).get("ok"):
                failures.append(f"{name} check is not healthy")
        if "application/json" not in content_type:
            failures.append("health content-type is not JSON")
    except Exception as exc:
        failures.append(f"health request failed: {type(exc).__name__}")

    try:
        status, raw, content_type = fetch("/app")
        html = raw.decode("utf-8", errors="replace")
        if status != 200:
            failures.append(f"app status={status}")
        if "text/html" not in content_type:
            failures.append("app content-type is not HTML")
        if "StonerHand" not in html or "/webapp/app.js" not in html:
            failures.append("app shell is incomplete")
    except Exception as exc:
        failures.append(f"app request failed: {type(exc).__name__}")

    for path, expected_type, marker in (
        ("/webapp/app.js", "javascript", "prepare_share"),
        ("/webapp/styles.css", "text/css", "height: 100dvh"),
        ("/webapp/studio-shell.css", "text/css", ".brand-lockup"),
    ):
        try:
            status, raw, content_type = fetch(path)
            text = raw.decode("utf-8", errors="replace")
            if status != 200:
                failures.append(f"asset {path} status={status}")
            if expected_type not in content_type:
                failures.append(f"asset {path} content-type={content_type}")
            if marker not in text:
                failures.append(f"asset {path} is incomplete")
        except Exception as exc:
            failures.append(f"asset {path} failed: {type(exc).__name__}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Production canary OK: {BASE_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
