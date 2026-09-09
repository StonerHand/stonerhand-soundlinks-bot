from __future__ import annotations

import re
from typing import Final

_SPOTIFY_BRAND_SUFFIX: Final = re.compile(
    r"\s*(?:\||[-\u2013\u2014])\s*spotify\s*$",
    re.IGNORECASE,
)
_SPOTIFY_ENTITY_SUFFIX: Final = re.compile(
    r"\s+[-\u2013\u2014]\s+"
    r"(?:compilation|soundtrack|album|single|ep|song(?:\s+and\s+lyrics)?|playlist|podcast|show|episode)"
    r"\s+by\s+.+$",
    re.IGNORECASE,
)


def clean_spotify_metadata_title(
    value: object, *, artist: str = "", spotify_source: bool = False
) -> str:
    """Remove Spotify branding and SEO copy from a public metadata title.

    The entity suffix is removed only when the same value ends in Spotify's
    brand marker. This keeps legitimate release titles containing words such
    as ``Album by`` untouched.
    """
    title = str(value or "").strip().strip("\u200e\u200f")
    unbranded, substitutions = _SPOTIFY_BRAND_SUFFIX.subn("", title, count=1)
    if not substitutions:
        if spotify_source and artist:
            return re.sub(
                r"\s+[-–—]\s+(?:compilation|soundtrack) by " + re.escape(artist) + r"$",
                "",
                title,
                flags=re.I,
            ).strip()
        return title

    clean = _SPOTIFY_ENTITY_SUFFIX.sub("", unbranded).strip()
    return clean or unbranded.strip()


def infer_release_format(title: str, *metadata: object) -> str | None:
    """Prefer typed provider fields; accept only explicit soundtrack title markers."""
    if re.search(
        r"\b(?:original (?:motion picture|television|game) soundtrack|original soundtrack)\b",
        title,
        re.I,
    ):
        return "soundtrack"
    for value in metadata:
        clean = str(value or "").strip().casefold()
        if clean in {"ep", "single", "compilation", "soundtrack"}:
            return clean
    if re.search(r"\s[-–—]\scompilation by .+\|\sSpotify$", title, re.I):
        return "compilation"
    match = re.search(r"(?:\s[-–—]\s|\()(EP|Single)(?:\)|$)", title, re.I)
    return (
        match.group(1).lower()
        if match
        else "album"
        if any(str(value).strip().lower() == "album" for value in metadata)
        else None
    )


def positive_track_count(value: object) -> int | None:
    if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
        return None
    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return count if 0 < count <= 9999 else None
