"""Read-only contract canary for the public music providers used by the bot."""

from __future__ import annotations

import asyncio
import sys

from music_links_bot.musicbrainz import MusicBrainzClient
from music_links_bot.nts import NTSClient
from music_links_bot.playlist import PlaylistClient
from music_links_bot.soundcloud import SoundCloudClient
from music_links_bot.spotify import SpotifyClient, SpotifyLookupError
from music_links_bot.youtube import YouTubeClient

SPOTIFY_TRACK = "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
SPOTIFY_REMOVED_ALBUM = "https://open.spotify.com/album/42dcDuItUH0Ed4QU4umdq6"
SOUNDCLOUD_TRACK = (
    "https://soundcloud.com/stoner-hand/ethan-kath-dj-set-park-live-moscow-30062013"
)
YOUTUBE_VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
APPLE_PLAYLIST = (
    "https://music.apple.com/tr/playlist/"
    "anya-taylor-joy-my-lucky-playlist/pl.e245dcff90464785a675ec40e8c52abb"
)
NTS_PAGE = "https://www.nts.live/shows/guests"


async def verify() -> list[str]:
    """Return concise provider failures; an empty list means all contracts hold."""
    failures: list[str] = []
    spotify = SpotifyClient(timeout=10)
    soundcloud = SoundCloudClient(timeout=10)
    youtube = YouTubeClient(timeout=10)
    playlist = PlaylistClient(timeout=10)
    nts = NTSClient(timeout=10)
    musicbrainz = MusicBrainzClient(timeout=10)
    try:
        try:
            track = await spotify.lookup_release(SPOTIFY_TRACK)
            if (
                track.title.casefold() in {"spotify", "listening is everything"}
                or not track.thumbnail_url
                or track.links.get("spotify") != SPOTIFY_TRACK
            ):
                failures.append("spotify valid-track metadata is generic or incomplete")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"spotify valid-track lookup failed: {type(exc).__name__}")

        try:
            spotify_url = await musicbrainz.lookup_spotify_release(
                "Deftones",
                "Rickets",
            )
            if spotify_url != "https://open.spotify.com/track/7Ca5yTC81P0AtRnNKHKzwJ":
                failures.append("musicbrainz exact Spotify relation is missing")
        except Exception as exc:  # noqa: BLE001
            failures.append(
                f"musicbrainz Spotify relation lookup failed: {type(exc).__name__}"
            )

        try:
            await spotify.lookup_release(SPOTIFY_REMOVED_ALBUM)
        except SpotifyLookupError:
            pass
        except Exception as exc:  # noqa: BLE001
            failures.append(f"spotify removed-album check failed: {type(exc).__name__}")
        else:
            failures.append("spotify removed album became a false release card")

        try:
            track = await soundcloud.lookup_track(SOUNDCLOUD_TRACK)
            if track.artist != "StonerHand" or not track.thumbnail_url:
                failures.append("soundcloud metadata or artwork is incomplete")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"soundcloud lookup failed: {type(exc).__name__}")

        try:
            video = await youtube.lookup_video(YOUTUBE_VIDEO)
            if not video.title or not video.thumbnail_url:
                failures.append("youtube metadata or artwork is incomplete")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"youtube lookup failed: {type(exc).__name__}")

        try:
            apple = await playlist.lookup_playlist(APPLE_PLAYLIST)
            if apple.platform != "Apple Music" or not apple.track_urls:
                failures.append("apple playlist metadata or import is incomplete")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"apple playlist lookup failed: {type(exc).__name__}")

        try:
            radio = await nts.lookup_radio(NTS_PAGE)
            if radio.title == "NTS Radio" or radio.station != "NTS Radio":
                failures.append("NTS metadata fell back to a generic card")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"NTS lookup failed: {type(exc).__name__}")
    finally:
        await asyncio.gather(
            spotify.aclose(),
            soundcloud.aclose(),
            youtube.aclose(),
            playlist.aclose(),
            nts.aclose(),
            musicbrainz.aclose(),
        )
    return failures


def main() -> int:
    failures = asyncio.run(verify())
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(
        "Provider canary OK: Spotify, MusicBrainz, SoundCloud, YouTube, "
        "Apple Music, NTS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
