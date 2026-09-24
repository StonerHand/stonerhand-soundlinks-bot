"""Shared cover signature for single releases and collection previews."""

from __future__ import annotations

import hashlib
import os
from contextlib import ExitStack

_TRUE = {"1", "true", "yes", "on"}


def photo_branding_enabled() -> bool:
    return os.getenv("BRAND_PHOTO_FRAME", "1").strip().casefold() in _TRUE


def brand_label(default: str = "@stonerhand") -> str:
    return os.getenv("BRAND_LABEL", "").strip() or default


def signature_cache_key() -> str:
    value = f"signature-v2:{photo_branding_enabled()}:{brand_label()}"
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _font(size: int):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 — no scalable default
        return ImageFont.load_default()


def apply_cover_signature(image, *, label: str):
    """Return a new RGB image; preserve the source dimensions and pixels above the footer."""
    from PIL import Image, ImageDraw

    with ExitStack() as resources:
        width, height = image.size
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
        rgba = resources.enter_context(image.convert("RGBA"))
        composite = resources.enter_context(Image.alpha_composite(rgba, overlay))
        return composite.convert("RGB")
