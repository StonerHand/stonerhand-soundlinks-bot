from __future__ import annotations

import re
from typing import Final

_SPOTIFY_BRAND_SUFFIX: Final = re.compile(
    r"\s*(?:\||[-\u2013\u2014])\s*spotify\s*$",
    re.IGNORECASE,
)
_SPOTIFY_ENTITY_SUFFIX: Final = re.compile(
    r"\s+[-\u2013\u2014]\s+"
    r"(?:album|single|ep|song(?:\s+and\s+lyrics)?|playlist|podcast|show|episode)"
    r"\s+by\s+.+$",
    re.IGNORECASE,
)


def clean_spotify_metadata_title(value: object) -> str:
    """Remove Spotify branding and SEO copy from a public metadata title.

    The entity suffix is removed only when the same value ends in Spotify's
    brand marker. This keeps legitimate release titles containing words such
    as ``Album by`` untouched.
    """
    title = str(value or "").strip().strip("\u200e\u200f")
    unbranded, substitutions = _SPOTIFY_BRAND_SUFFIX.subn("", title, count=1)
    if not substitutions:
        return title

    clean = _SPOTIFY_ENTITY_SUFFIX.sub("", unbranded).strip()
    return clean or unbranded.strip()
