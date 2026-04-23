from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TrackMatch:
    title: str
    artist: str
    links: dict[str, str]
    page_url: str | None = None
    release_year: str | None = None
    kind: str = "song"
    release_format: str | None = None
