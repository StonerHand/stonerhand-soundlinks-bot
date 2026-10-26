"""How one source's lookup result becomes a card, a status and a retry offer."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from music_links_bot.models import TrackMatch
from music_links_bot.public_release import PublicReleaseRegionUnavailable
from music_links_bot.songlink import SonglinkError, SonglinkLookupError
from music_links_bot.soundcloud import SoundCloudLookupError
from music_links_bot.track_lookup import _attempt_source, _source_outcome

SPOTIFY_ALBUM = "https://open.spotify.com/album/abc"
DEEZER_ALBUM = "https://www.deezer.com/album/1"
SOUNDCLOUD = "https://soundcloud.com/artist/song"
TRACK = TrackMatch(
    artist="Victor Jones",
    title="Mad Flowers",
    links={"deezer": DEEZER_ALBUM},
    kind="album",
)


def _caused_by(error: Exception, cause: BaseException) -> Exception:
    error.__cause__ = cause
    return error


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.song.link/")
    return httpx.HTTPStatusError(
        "x", request=request, response=httpx.Response(status, request=request)
    )


def test_a_found_release_is_a_card():
    track, status, unavailable = _source_outcome(DEEZER_ALBUM, TRACK)

    assert track is TRACK
    assert (status.state, status.provider, status.label) == (
        "success",
        "songlink",
        "Victor Jones — Mad Flowers",
    )
    assert not unavailable


def test_a_fallback_card_replaces_a_songlink_failure():
    track, status, unavailable = _source_outcome(
        DEEZER_ALBUM, SonglinkError("down"), TRACK
    )

    assert track is TRACK and status.state == "success" and not unavailable


@pytest.mark.parametrize(
    ("error", "state", "retryable", "reason"),
    [
        (
            _caused_by(SonglinkLookupError("gone"), _http_error(404)),
            "not_found",
            False,
            "release_not_found",
        ),
        (
            _caused_by(
                SonglinkLookupError("blocked"), PublicReleaseRegionUnavailable()
            ),
            "unavailable",
            False,
            "region_unavailable",
        ),
        (
            _caused_by(SonglinkLookupError("busy"), _http_error(429)),
            "unavailable",
            True,
            "rate_limited",
        ),
        # No cause: Song.link simply has no such release.
        (SonglinkLookupError("unknown"), "not_found", False, "release_not_found"),
    ],
)
def test_songlink_misses_are_named_and_never_listed_as_outages(
    error, state, retryable, reason
):
    track, status, unavailable = _source_outcome(DEEZER_ALBUM, error)

    assert track is None
    assert (status.state, status.retryable, status.reason) == (state, retryable, reason)
    assert not unavailable


def test_an_unexplained_spotify_miss_can_be_retried():
    _track, status, _unavailable = _source_outcome(
        SPOTIFY_ALBUM, SonglinkLookupError("unknown")
    )

    assert (status.state, status.retryable) == ("not_found", True)


@pytest.mark.parametrize(
    "error",
    [SonglinkError("500"), TimeoutError("slow"), RuntimeError("sdk")],
)
def test_outages_are_retryable_and_listed(error):
    track, status, unavailable = _source_outcome(
        DEEZER_ALBUM, error, RuntimeError("fallback broke")
    )

    assert track is None
    assert (status.state, status.retryable) == ("unavailable", True)
    assert unavailable


def _attempt(source_url, *, songlink=None, soundcloud=None, retried=False):
    client = AsyncMock()
    client.lookup_track.side_effect = songlink
    soundcloud_client = AsyncMock()
    soundcloud_client.lookup_track.side_effect = soundcloud
    return asyncio.run(
        _attempt_source(
            client,
            soundcloud_client,
            source_url,
            remaining=1.0,
            retried=retried,
        )
    )


def test_one_attempt_returns_the_card_or_the_final_error():
    assert _attempt(DEEZER_ALBUM, songlink=[TRACK]) is TRACK
    assert isinstance(_attempt(DEEZER_ALBUM, songlink=TimeoutError()), TimeoutError)
    assert isinstance(_attempt(DEEZER_ALBUM, songlink=ValueError()), ValueError)
    # Only a Spotify release is worth asking Song.link twice about a miss.
    miss = SonglinkLookupError("miss")
    assert _attempt(DEEZER_ALBUM, songlink=miss) is miss
    assert _attempt(SPOTIFY_ALBUM, songlink=miss) is None
    assert _attempt(SPOTIFY_ALBUM, songlink=miss, retried=True) is miss
    # A provider outage gets exactly one more try.
    outage = SonglinkError("500")
    assert _attempt(DEEZER_ALBUM, songlink=outage) is None
    assert _attempt(DEEZER_ALBUM, songlink=outage, retried=True) is outage


def test_soundcloud_links_never_go_through_songlink():
    assert _attempt(SOUNDCLOUD, soundcloud=[TRACK]) is TRACK
    broken = RuntimeError("sdk")
    assert _attempt(SOUNDCLOUD, soundcloud=broken) is broken
    # A refused SoundCloud lookup still yields the link-only fallback card.
    fallback = _attempt(SOUNDCLOUD, soundcloud=SoundCloudLookupError("private"))
    assert isinstance(fallback, TrackMatch)
    assert fallback.links == {"soundcloud": SOUNDCLOUD}
