from __future__ import annotations

import io
import json
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
_HTTP_CLIENT = httpx.Client(
    headers={"User-Agent": HTTP_USER_AGENT},
    timeout=FETCH_TIMEOUT_SECONDS,
    follow_redirects=False,
    limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
)


class handler(BaseHTTPRequestHandler):
    """GET /api/collage — signed, cached artwork for classic Telegram cards."""

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        if query.get("health") == ["1"]:
            self._send_health()
            return

        signature = query.get("s", [""])[0]
        urls = decode_collage_payload(
            query.get("p", [""])[0],
            signature,
            signing_secret=os.getenv("BOT_TOKEN", "").strip(),
        )
        if urls is None:
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        etag = f'"collage-{signature}"'
        if self.headers.get("if-none-match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("etag", etag)
            self.send_header("cache-control", "public, max-age=2592000, immutable")
            self.end_headers()
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
        self.send_header("etag", etag)
        self.send_header("x-content-type-options", "nosniff")
        self.end_headers()
        self.wfile.write(collage)

    def _send_health(self) -> None:
        payload = _collage_health_payload()
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(
            HTTPStatus.OK if payload["ok"] else HTTPStatus.SERVICE_UNAVAILABLE
        )
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("x-content-type-options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def _collage_health_payload() -> dict[str, object]:
    """Exercise the deployed Pillow decoder, layout and JPEG encoder."""
    try:
        from PIL import Image

        source = io.BytesIO()
        Image.new("RGB", (4, 4), (18, 18, 20)).save(source, "PNG")
        sample = source.getvalue()
        rendered = compose_collection_collage([sample, sample], size=32, gap=2)
        renderer = f"Pillow {Image.__version__}"
    except (ImportError, OSError, TypeError, ValueError):
        rendered = None
        renderer = "unavailable"
    return {
        "ok": rendered is not None,
        "service": "collection-collage",
        "layouts": [2, 3, 4],
        "renderer": renderer,
        "max_artwork_bytes": MAX_ARTWORK_BYTES,
    }


def _fetch_artwork(url: str) -> bytes | None:
    try:
        # Redirects stay disabled so a signed public provider URL cannot pivot
        # the server-side fetch to a different destination.
        with _HTTP_CLIENT.stream(
            "GET",
            url,
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
