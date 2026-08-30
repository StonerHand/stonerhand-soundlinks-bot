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
    # A canary must report every failure as a concise non-zero result instead
    # of losing the diagnostic in a traceback.
    except Exception as exc:  # noqa: BLE001
        failures.append(f"health request failed: {type(exc).__name__}")

    try:
        status, raw, content_type = fetch("/api/collage?health=1")
        payload = json.loads(raw)
        if status != 200 or not payload.get("ok"):
            failures.append(f"collage status={status} ok={payload.get('ok')}")
        if payload.get("service") != "collection-collage":
            failures.append("collage service identity is invalid")
        if payload.get("layouts") != [2, 3, 4]:
            failures.append("collage layouts are incomplete")
        if "application/json" not in content_type:
            failures.append("collage content-type is not JSON")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"collage request failed: {type(exc).__name__}")

    try:
        status, raw, content_type = fetch("/api/smoke")
        payload = json.loads(raw)
        if status != 200 or not payload.get("ok"):
            failures.append(f"publication smoke status={status} ok={payload.get('ok')}")
        if payload.get("service") != "publication-release-smoke":
            failures.append("publication smoke service identity is invalid")
        if payload.get("contract") != 2:
            failures.append("publication smoke contract is outdated")
        cases = payload.get("cases") or {}
        expected_cases = {
            "classic_track",
            "soundcloud_source_only",
            "collection_complete",
            "collection_partial",
            "inline_share",
            "channel_keyboard",
            "rich_card",
        }
        if set(cases) != expected_cases:
            failures.append("publication smoke matrix is incomplete")
        failures.extend(
            f"publication smoke case {name} failed"
            for name, case in cases.items()
            if not (case or {}).get("ok")
        )
        ux = payload.get("ux") or {}
        if not ux.get("ok"):
            failures.append("navigation and editor UX smoke failed")
        if set(ux.get("screens") or {}) != {
            "home_ru",
            "home_en",
            "editor_actions",
            "editor_settings",
        }:
            failures.append("navigation and editor UX matrix is incomplete")
        if "application/json" not in content_type:
            failures.append("publication smoke content-type is not JSON")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"publication smoke request failed: {type(exc).__name__}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Production canary OK: {BASE_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
