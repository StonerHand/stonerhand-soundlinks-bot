"""Read-only production smoke check used by the scheduled GitHub workflow."""

from __future__ import annotations

import json
import os
import sys
from urllib.request import Request, urlopen

BASE_URL = os.getenv("CANARY_BASE_URL", "https://tg-bot-sh.vercel.app").rstrip("/")
EXPECTED_COMMIT = os.getenv("CANARY_EXPECT_COMMIT", "").strip()
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
        failures.extend(
            f"{name} check is not healthy"
            for name in ("telegram", "webhook", "redis")
            if not (checks.get(name) or {}).get("ok")
        )
        if "application/json" not in content_type:
            failures.append("health content-type is not JSON")
        release = payload.get("release") or {}
        if not release.get("version"):
            failures.append("health release version is missing")
        deployed_commit = str(release.get("commit") or "")
        if EXPECTED_COMMIT and (
            not deployed_commit or not EXPECTED_COMMIT.startswith(deployed_commit)
        ):
            failures.append(
                f"production commit={deployed_commit or 'missing'} "
                f"expected={EXPECTED_COMMIT[:12]}"
            )
    except Exception as exc:
        failures.append(f"health request failed: {type(exc).__name__}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Production canary OK: {BASE_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
