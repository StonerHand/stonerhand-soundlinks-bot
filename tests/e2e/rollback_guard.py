"""Allow automatic rollback only for the exact newly deployed unhealthy build."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE_URL = os.getenv("CANARY_BASE_URL", "https://tg-bot-sh.vercel.app").rstrip("/")
EXPECTED_COMMIT = os.getenv("CANARY_EXPECT_COMMIT", "").strip()


def should_rollback(payload: object, expected_commit: str) -> bool:
    if (
        not expected_commit
        or not isinstance(payload, dict)
        or payload.get("ok") is True
    ):
        return False
    release = payload.get("release")
    if not isinstance(release, dict):
        return False
    deployed_commit = str(release.get("commit") or "")
    return bool(deployed_commit and expected_commit.startswith(deployed_commit))


def fetch_health() -> object:
    request = Request(
        f"{BASE_URL}/api/health",
        headers={"User-Agent": "StonerHand-rollback-guard/1.0"},
    )
    try:
        response = urlopen(request, timeout=20)
    except HTTPError as exc:
        response = exc
    with response:
        return json.loads(response.read())


def main() -> int:
    try:
        payload = fetch_health()
    except Exception as exc:  # noqa: BLE001
        print(f"Rollback refused: health is unreadable ({type(exc).__name__})")
        return 1
    if not should_rollback(payload, EXPECTED_COMMIT):
        print("Rollback refused: failure is not tied to the expected deployment")
        return 1
    print("Rollback guard confirmed the exact unhealthy production deployment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
