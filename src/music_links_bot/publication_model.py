from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from music_links_bot.formatter import release_details
from music_links_bot.i18n import resolve_lang
from music_links_bot.models import TrackMatch, VideoMatch
from music_links_bot.release_presentation import compact_release_title


@dataclass(slots=True, frozen=True)
class PublicationMedia:
    kind: str
    url: str
    caption: str = ""


@dataclass(slots=True)
class MusicPublication:
    """Transport-neutral representation of a finished music post."""

    title: str
    kind: str = "track"
    lead_html: str = ""
    body_html: str = ""
    media: list[PublicationMedia] = field(default_factory=list)
    hashtags: str = ""

    @classmethod
    def from_track(
        cls,
        track: TrackMatch,
        *,
        lead_html: str = "",
        hashtags: str = "",
    ) -> MusicPublication:
        media = (
            [PublicationMedia("photo", track.thumbnail_url, cls.track_title(track))]
            if track.thumbnail_url
            else []
        )
        return cls(
            title=cls.track_title(track),
            kind=track.kind,
            lead_html=lead_html,
            body_html=cls.track_details(track),
            media=media,
            hashtags=hashtags,
        )

    @classmethod
    def from_track_video(
        cls,
        track: TrackMatch,
        video: VideoMatch,
        *,
        body_html: str = "",
        hashtags: str = "",
    ) -> MusicPublication:
        media: list[PublicationMedia] = []
        if track.thumbnail_url:
            media.append(
                PublicationMedia("photo", track.thumbnail_url, cls.track_title(track))
            )
        if video.thumbnail_url:
            media.append(PublicationMedia("photo", video.thumbnail_url, video.title))
        return cls(
            title="Песня + клип",
            kind="track_video",
            body_html=body_html,
            media=media,
            hashtags=hashtags,
        )

    @staticmethod
    def track_title(track: TrackMatch) -> str:
        if track.kind == "video" or track.artist.strip().casefold() in {
            "various artists",
            "various",
            "разные исполнители",
        }:
            return compact_release_title(track.title)
        return " — ".join(
            part.strip()
            for part in (track.artist, compact_release_title(track.title))
            if part.strip()
        )

    @staticmethod
    def track_details(track: TrackMatch) -> str:
        if track.kind == "video":
            label = "Source" if resolve_lang(None) == "en" else "Источник"
            return f"<i>{label}: {escape(track.artist)}</i>" if track.artist else ""
        details = release_details(track)
        return f"<i>{escape(details)}</i>" if details else ""
