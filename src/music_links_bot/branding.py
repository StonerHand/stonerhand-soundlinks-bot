"""Optional branded frame for photo-mode posts.

Opt-in via `BRAND_PHOTO_FRAME=1`. When enabled, the artwork gets a subtle
bottom gradient with the channel label and, if `BRAND_LOGO_URL` is set, a logo
in the top-right corner — a consistent house style for photo posts. Every step
degrades gracefully: any failure (missing Pillow, a bad image, a slow fetch)
falls back to the plain artwork, so publishing never breaks because of it.
"""

from __future__ import annotations

import io
import logging
import os

import httpx

from music_links_bot.constants import HTTP_USER_AGENT

LOGGER = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


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
    img = img.crop((left, top, left + side, top + side))
    if side != target:
        img = img.resize((target, target))
    return img


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
    except Exception:
        return None

    try:
        base = _square(Image.open(io.BytesIO(artwork_bytes)).convert("RGB"), size)
        width, height = base.size

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        bar_height = int(height * 0.18)
        for row in range(bar_height):
            alpha = int(190 * (row / bar_height))
            draw.line(
                [(0, height - bar_height + row), (width, height - bar_height + row)],
                fill=(0, 0, 0, alpha),
            )
        if label:
            font = _font(int(height * 0.05))
            draw.text(
                (int(width * 0.05), height - int(bar_height * 0.60)),
                label,
                font=font,
                fill=(255, 255, 255, 235),
            )

        composed = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

        if logo_bytes:
            try:
                logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
                target = int(width * 0.14)
                logo.thumbnail((target, target))
                pad = int(width * 0.04)
                composed.paste(logo, (width - logo.width - pad, pad), logo)
            except Exception:
                LOGGER.debug("Logo overlay failed", exc_info=True)

        out = io.BytesIO()
        composed.save(out, "JPEG", quality=88)
        return out.getvalue()
    except Exception:
        LOGGER.debug("Branded cover compositing failed", exc_info=True)
        return None


async def _fetch_bytes(client: httpx.AsyncClient, url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.content
    except Exception:
        LOGGER.debug("Branding asset fetch failed: %s", url, exc_info=True)
        return None


async def build_branded_cover(
    artwork_url: str | None, *, label: str, logo_url: str | None = None
) -> bytes | None:
    """Download the artwork (and logo) and return branded JPEG bytes, or None to
    signal the caller should fall back to the plain artwork URL."""
    if not artwork_url:
        return None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0),
            headers={"User-Agent": HTTP_USER_AGENT},
        ) as client:
            artwork_bytes = await _fetch_bytes(client, artwork_url)
            if artwork_bytes is None:
                return None
            logo_bytes = await _fetch_bytes(client, logo_url)
    except Exception:
        LOGGER.debug("Branding fetch failed", exc_info=True)
        return None

    return compose_cover(artwork_bytes, label=label, logo_bytes=logo_bytes)
