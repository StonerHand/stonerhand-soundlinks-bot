from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from music_links_bot.collection_collage import (
    compose_collection_collage,
    decode_collage_payload,
)
from music_links_bot.constants import HTTP_USER_AGENT

MAX_ARTWORK_BYTES = 6 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 6


class handler(BaseHTTPRequestHandler):
    """GET /api/collage — signed, cached artwork for classic Telegram cards."""

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        urls = decode_collage_payload(
            query.get("p", [""])[0],
            query.get("s", [""])[0],
            signing_secret=os.getenv("BOT_TOKEN", "").strip(),
        )
        if urls is None:
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        with ThreadPoolExecutor(max_workers=len(urls)) as executor:
            images = [image for image in executor.map(_fetch_artwork, urls) if image]
        collage = compose_collection_collage(images)
        if collage is None:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("location", urls[0])
            self.send_header("cache-control", "public, max-age=300")
            self.end_headers()
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "image/jpeg")
        self.send_header("content-length", str(len(collage)))
        self.send_header("cache-control", "public, max-age=2592000, immutable")
        self.send_header("x-content-type-options", "nosniff")
        self.end_headers()
        self.wfile.write(collage)


def _fetch_artwork(url: str) -> bytes | None:
    try:
        # Redirects stay disabled so a signed public provider URL cannot pivot
        # the server-side fetch to a different destination.
        with httpx.stream(
            "GET",
            url,
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as response:
            if response.status_code != HTTPStatus.OK:
                return None
            content_type = str(response.headers.get("content-type") or "")
            if not content_type.casefold().startswith("image/"):
                return None
            content_length = int(response.headers.get("content-length") or 0)
            if content_length > MAX_ARTWORK_BYTES:
                return None
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_ARTWORK_BYTES:
                    return None
    except (httpx.HTTPError, TypeError, ValueError):
        return None
    return bytes(body)
