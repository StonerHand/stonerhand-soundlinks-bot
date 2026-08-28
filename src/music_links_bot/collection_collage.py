from __future__ import annotations

import base64
import hashlib
import hmac
import io
import ipaddress
import json
import os
from urllib.parse import urlencode, urlparse

from music_links_bot.models import TrackMatch

COLLAGE_VERSION = "v1"
MIN_COLLAGE_ITEMS = 2
MAX_COLLAGE_ITEMS = 4
MAX_SOURCE_URL_LENGTH = 2_048
MAX_PAYLOAD_LENGTH = 12_000


def collection_collage_preview_url(
    tracks: list[TrackMatch],
    *,
    base_url: str | None = None,
    signing_secret: str | None = None,
) -> str | None:
    """Build a signed public image URL for a 2–4-cover classic preview."""
    if not MIN_COLLAGE_ITEMS <= len(tracks) <= MAX_COLLAGE_ITEMS:
        return None

    artwork_urls = [
        track.thumbnail_url.strip()
        for track in tracks
        if track.thumbnail_url and _safe_source_url(track.thumbnail_url.strip())
    ]
    if len(artwork_urls) < MIN_COLLAGE_ITEMS:
        return None
    if len(set(artwork_urls)) < MIN_COLLAGE_ITEMS:
        return None

    public_origin = _public_origin(base_url)
    secret = (signing_secret or os.getenv("BOT_TOKEN", "")).strip()
    if not public_origin or not secret:
        return None

    payload = _encode_payload(artwork_urls)
    signature = _signature(payload, secret)
    query = urlencode({"p": payload, "s": signature})
    return f"{public_origin}/api/collage?{query}"


def decode_collage_payload(
    payload: str,
    signature: str,
    *,
    signing_secret: str,
) -> list[str] | None:
    """Verify a collage request and return only safe HTTPS artwork URLs."""
    if not signing_secret or not payload or len(payload) > MAX_PAYLOAD_LENGTH:
        return None
    if not hmac.compare_digest(signature, _signature(payload, signing_secret)):
        return None

    try:
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding)
        value = json.loads(decoded)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None

    if not isinstance(value, list):
        return None
    urls = [str(url).strip() for url in value]
    if not MIN_COLLAGE_ITEMS <= len(urls) <= MAX_COLLAGE_ITEMS:
        return None
    if len(set(urls)) < MIN_COLLAGE_ITEMS:
        return None
    return urls if all(_safe_source_url(url) for url in urls) else None


def compose_collection_collage(
    artwork_images: list[bytes],
    *,
    size: int = 1_200,
    gap: int = 10,
) -> bytes | None:
    """Compose downloaded artwork into a deterministic square JPEG."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None

    images = []
    for raw in artwork_images[:MAX_COLLAGE_ITEMS]:
        try:
            image = Image.open(io.BytesIO(raw))
            if image.width * image.height > 40_000_000:
                continue
            image.load()
            images.append(ImageOps.exif_transpose(image))
        except (OSError, TypeError, ValueError, Image.DecompressionBombError):
            continue
    if len(images) < MIN_COLLAGE_ITEMS:
        return None

    try:
        canvas = Image.new("RGB", (size, size), (18, 18, 20))
        for image, box in zip(
            images, _layout_boxes(len(images), size, gap), strict=True
        ):
            left, top, right, bottom = box
            target_size = (right - left, bottom - top)
            fitted = ImageOps.fit(
                image.convert("RGBA"),
                target_size,
                method=Image.Resampling.LANCZOS,
            )
            tile = Image.new("RGB", target_size, (18, 18, 20))
            tile.paste(fitted, mask=fitted.getchannel("A"))
            canvas.paste(tile, (left, top))

        output = io.BytesIO()
        canvas.save(output, "JPEG", quality=88, optimize=True)
        return output.getvalue()
    except (OSError, TypeError, ValueError):
        return None


def _layout_boxes(count: int, size: int, gap: int) -> list[tuple[int, int, int, int]]:
    middle = size // 2
    if count == 2:
        return [(0, 0, middle - gap // 2, size), (middle + gap // 2, 0, size, size)]
    if count == 3:
        return [
            (0, 0, middle - gap // 2, size),
            (middle + gap // 2, 0, size, middle - gap // 2),
            (middle + gap // 2, middle + gap // 2, size, size),
        ]
    return [
        (0, 0, middle - gap // 2, middle - gap // 2),
        (middle + gap // 2, 0, size, middle - gap // 2),
        (0, middle + gap // 2, middle - gap // 2, size),
        (middle + gap // 2, middle + gap // 2, size, size),
    ]


def _encode_payload(urls: list[str]) -> str:
    encoded = json.dumps(urls, ensure_ascii=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")


def _signature(payload: str, secret: str) -> str:
    message = f"{COLLAGE_VERSION}:{payload}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()[:32]


def _public_origin(explicit: str | None) -> str | None:
    raw = (
        (explicit or "").strip()
        or os.getenv("WEBHOOK_BASE_URL", "").strip()
        or os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
        or os.getenv("VERCEL_URL", "").strip()
    )
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        return None
    return f"https://{parsed.netloc}"


def _safe_source_url(value: str) -> bool:
    if not value or len(value) > MAX_SOURCE_URL_LENGTH:
        return False
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or hostname == "localhost"
        or hostname.endswith((".local", ".internal"))
    ):
        return False
    try:
        return ipaddress.ip_address(hostname).is_global
    except ValueError:
        return True
