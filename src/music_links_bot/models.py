from __future__ import annotations

from dataclasses import dataclass, field

from music_links_bot.metadata_cleaning import clean_spotify_metadata_title


@dataclass(slots=True)
class TrackMatch:
    title: str
    artist: str
    links: dict[str, str]
    page_url: str | None = None
    release_year: str | None = None
    kind: str = "song"
    release_format: str | None = None
    thumbnail_url: str | None = None
    genre: str | None = None

    def __post_init__(self) -> None:
        # Spotify's public metadata sometimes returns an SEO page title such
        # as "Release - Album by Artist | Spotify". Keep that provider copy
        # out of every downstream surface, including restored legacy drafts.
        self.title = clean_spotify_metadata_title(self.title)


@dataclass(slots=True)
class VideoMatch:
    title: str
    author: str
    url: str
    thumbnail_url: str | None = None


@dataclass(slots=True)
class RadioMatch:
    title: str
    station: str
    url: str


@dataclass(slots=True)
class PlaylistMatch:
    title: str
    platform: str
    url: str
    track_urls: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ArtistMatch:
    title: str
    platform: str
    url: str
