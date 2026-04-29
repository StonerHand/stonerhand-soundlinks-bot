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


@dataclass(slots=True)
class VideoMatch:
    title: str
    author: str
    url: str


@dataclass(slots=True)
class PlaylistMatch:
    title: str
    platform: str
    url: str
