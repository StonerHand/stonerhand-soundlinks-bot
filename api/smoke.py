from __future__ import annotations

import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from music_links_bot.http_json import send_json
from music_links_bot.release_smoke import build_release_smoke_report


class handler(BaseHTTPRequestHandler):
    """GET /api/smoke — deterministic end-to-end publication contract."""

    def do_GET(self) -> None:
        report = build_release_smoke_report()
        send_json(
            self,
            report,
            HTTPStatus.OK if report["ok"] else HTTPStatus.SERVICE_UNAVAILABLE,
        )
