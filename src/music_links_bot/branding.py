"""Optional branded frame for photo-mode posts.

Opt-in via `BRAND_PHOTO_FRAME=1`. When enabled, the artwork gets a subtle
bottom gradient with the channel label and, if `BRAND_LOGO_URL` is set, a logo
in the top-right corner — a consistent house style for photo posts. Every step
degrades gracefully: any failure (missing Pillow, a bad image, a slow fetch)
falls back to the plain artwork, so publishing never breaks because of it.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from contextlib import ExitStack

import httpx

from music_links_bot.collection_collage import _safe_source_url
from music_links_bot.constants import HTTP_USER_AGENT

LOGGER = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}
MAX_BRANDING_BYTES = 3 * 1024 * 1024
MAX_BRANDING_PIXELS = 12_000_000
MAX_COVER_SIZE = 1200
BRANDING_FETCH_SECONDS = 8.0


def photo_branding_enabled() -> bool:
    return os.getenv("BRAND_PHOTO_FRAME", "").strip().casefold() in _TRUE


def brand_label(default: str) -> str:
    return os.getenv("BRAND_LABEL", "").strip() or default


def brand_logo_url() -> str | None:
    return os.getenv("BRAND_LOGO_URL", "").strip() or None


def _font(size: int):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 — no scalable default
        return ImageFont.load_default()


def _square(img, target: int):
    width, height = img.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = img.crop((left, top, left + side, top + side))
    if side == target:
        return cropped
    with cropped:
        return cropped.resize((target, target))


def compose_cover(
    artwork_bytes: bytes,
    *,
    label: str,
    logo_bytes: bytes | None = None,
    size: int = 1080,
) -> bytes | None:
    """Pure-image compositing (no network) so it is easy to test."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    if not 32 <= size <= MAX_COVER_SIZE or len(artwork_bytes) > MAX_BRANDING_BYTES:
        return None
    try:
        with ExitStack() as resources:
            source = resources.enter_context(Image.open(io.BytesIO(artwork_bytes)))
            if source.width * source.height > MAX_BRANDING_PIXELS:
                return None
            source.thumbnail((MAX_COVER_SIZE, MAX_COVER_SIZE))
            rgb = resources.enter_context(source.convert("RGB"))
            base = resources.enter_context(_square(rgb, size))
            width, height = base.size
            overlay = resources.enter_context(
                Image.new("RGBA", (width, height), (0, 0, 0, 0))
            )
            draw = ImageDraw.Draw(overlay)
            bar_height = int(height * 0.18)
            for row in range(bar_height):
                alpha = int(190 * (row / bar_height))
                draw.line(
                    [
                        (0, height - bar_height + row),
                        (width, height - bar_height + row),
                    ],
                    fill=(0, 0, 0, alpha),
                )
            if label:
                draw.text(
                    (int(width * 0.05), height - int(bar_height * 0.60)),
                    label[:160],
                    font=_font(max(1, int(height * 0.05))),
                    fill=(255, 255, 255, 235),
                )
            rgba = resources.enter_context(base.convert("RGBA"))
            composite = resources.enter_context(Image.alpha_composite(rgba, overlay))
            composed = resources.enter_context(composite.convert("RGB"))
            if logo_bytes and len(logo_bytes) <= MAX_BRANDING_BYTES:
                try:
                    with Image.open(io.BytesIO(logo_bytes)) as logo_source:
                        if (
                            logo_source.width * logo_source.height
                            <= MAX_BRANDING_PIXELS
                        ):
                            target = max(1, int(width * 0.14))
                            logo_source.thumbnail((target, target))
                            with logo_source.convert("RGBA") as logo:
                                pad = int(width * 0.04)
                                composed.paste(
                                    logo, (width - logo.width - pad, pad), logo
                                )
                except (OSError, ValueError, Image.DecompressionBombError):
                    LOGGER.debug("Logo overlay failed")
            out = io.BytesIO()
            composed.save(out, "JPEG", quality=88)
            return out.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        LOGGER.debug("Branded cover compositing failed")
        return None


async def _fetch_bytes(client: httpx.AsyncClient, url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        # Enforce a limit on received bytes, including responses without a
        # trustworthy Content-Length. Redirects cannot change the destination.
        async with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code != 200:
                return None
            if (
                not response.headers.get("content-type", "")
                .lower()
                .startswith("image/")
            ):
                return None
            length = int(response.headers.get("content-length") or 0)
            if length < 0 or length > MAX_BRANDING_BYTES:
                return None
            body = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65_536):
                if len(body) + len(chunk) > MAX_BRANDING_BYTES:
                    return None
                body.extend(chunk)
        return bytes(body)
    except (httpx.HTTPError, ValueError):
        # Exception text can contain a signed asset URL. Do not log its query.
        LOGGER.debug("Branding asset fetch failed")
        return None


async def build_branded_cover(
    artwork_url: str | None, *, label: str, logo_url: str | None = None
) -> bytes | None:
    """Download the artwork (and logo) and return branded JPEG bytes, or None to
    signal the caller should fall back to the plain artwork URL."""
    if not artwork_url or not _safe_source_url(artwork_url):
        return None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0),
            headers={"User-Agent": HTTP_USER_AGENT},
        ) as client:
            artwork_bytes, logo_bytes = await asyncio.wait_for(
                asyncio.gather(
                    _fetch_bytes(client, artwork_url), _fetch_bytes(client, logo_url)
                ),
                timeout=BRANDING_FETCH_SECONDS,
            )
            if artwork_bytes is None:
                return None
    except (asyncio.TimeoutError, httpx.HTTPError, ValueError):
        LOGGER.debug("Branding fetch failed")
        return None

    return compose_cover(artwork_bytes, label=label, logo_bytes=logo_bytes)
