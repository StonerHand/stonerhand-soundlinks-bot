import asyncio
import json
from dataclasses import asdict
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from telegram.error import BadRequest, TimedOut
from test_bot import ContextStub
from test_release_card import sample

from music_links_bot.bot_inline import _build_inline_result
from music_links_bot.bot_lookup import _fill_release_metadata, _lookup_tracks
from music_links_bot.bot_preferences import apply_preferences
from music_links_bot.bot_runtime import UserSession
from music_links_bot.draft_model import new_track_draft, normalize_track_draft
from music_links_bot.formatter import (
    format_playlist_message,
    format_track_message,
    format_video_message,
)
from music_links_bot.i18n import language_context
from music_links_bot.models import PlaylistMatch, VideoMatch
from music_links_bot.publication_service import PublicationService
from music_links_bot.release_metadata import duration_label, metadata_url
from music_links_bot.release_preferences import (
    PresentationPreferences,
    presentation_context,
)
from music_links_bot.search import (
    SearchClient,
    _complete_album_duration,
    _extract_release_candidates,
)
from music_links_bot.spotify import (
    SpotifyClient,
    parse_spotify_embed,
    parse_spotify_page,
)

TRACK = "https://open.spotify.com/track/dig"
ALBUM = "https://open.spotify.com/album/unified"
ARTIST = "https://open.spotify.com/artist/from-this-point-on"
APPLE_ALBUM = "https://music.apple.com/us/album/unified/101"
APPLE_TRACK = APPLE_ALBUM + "?i=102"
APPLE_ARTIST = "https://music.apple.com/us/artist/from-this-point-on/103"


def run_async(test):
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))

    return run


def apple_payload():
    return {
        "results": [
            {
                "wrapperType": "collection",
                "collectionId": 101,
                "collectionName": "Unified",
                "artistName": "From This Point On",
                "collectionViewUrl": APPLE_ALBUM,
                "artistViewUrl": APPLE_ARTIST,
                "trackCount": 2,
            },
            {
                "wrapperType": "track",
                "kind": "song",
                "trackId": 102,
                "collectionId": 101,
                "trackName": "Dig",
                "artistName": "From This Point On",
                "collectionName": "Unified",
                "collectionViewUrl": APPLE_TRACK,
                "trackViewUrl": APPLE_TRACK,
                "artistViewUrl": APPLE_ARTIST,
                "trackTimeMillis": 222000,
            },
            {
                "wrapperType": "track",
                "kind": "song",
                "trackId": 104,
                "collectionId": 101,
                "trackName": "Another",
                "artistName": "From This Point On",
                "collectionName": "Unified",
                "trackViewUrl": APPLE_ALBUM + "?i=104",
                "trackTimeMillis": 178000,
            },
        ]
    }


@pytest.mark.parametrize(
    "duration,label",
    [
        (222000, "3:42"),
        (3601000, "1:00:01"),
        (213573, "3:34"),
        (0, None),
        (-1, None),
        (True, None),
        (1.2, None),
        ("unknown", None),
    ],
)
def test_duration_requires_valid_full_length(duration, label):
    assert duration_label(duration) == label


def test_caption_has_verified_links_and_duration_after_roundtrip():
    track = sample(album_url=ALBUM, artist_url=ARTIST, duration_ms=222000)
    restored = normalize_track_draft(new_track_draft(track, chat_id=7, lang="ru"))
    assert restored["item"]["duration_ms"] == 222000
    assert restored["item"]["album_url"] == ALBUM
    text = format_track_message(track)
    assert f'<a href="{ARTIST}">From This Point On</a>' in text
    assert f'💿 Из альбома «<a href="{ALBUM}">Unified</a>»' in text
    assert "Трек · 2026 · 3:42" in text
    assert text.endswith("#stonerhand #track")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://open.spotify.com.evil.test/album/a",
        "https://open.spotify.com/search/unified",
        APPLE_TRACK,
    ],
)
def test_unverified_album_links_are_never_rendered(url):
    assert metadata_url(url, "album") is None
    assert "<a href=" not in format_track_message(sample(album_url=url))


def test_apple_collection_link_does_not_reopen_selected_track():
    candidate = _extract_release_candidates(
        {"results": apple_payload()["results"][1:2]}
    )[0]
    assert candidate.album_url == APPLE_ALBUM
    assert candidate.artist_url == APPLE_ARTIST
    assert candidate.duration_ms == 222000


def test_album_duration_requires_every_unique_track_with_duration():
    payload = apple_payload()
    assert _complete_album_duration(payload, "101", 2) == 400000
    assert _complete_album_duration(payload, "101", 3) is None
    payload["results"][2]["trackId"] = 102
    assert _complete_album_duration(payload, "101", 2) is None
    payload["results"][2]["trackId"] = 104
    payload["results"][2].pop("trackTimeMillis")
    assert _complete_album_duration(payload, "101", 2) is None


@run_async
async def test_exact_apple_lookup_uses_full_album_and_caches_details():
    client = SearchClient()
    await client._client.aclose()
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=apple_payload())

    client._client = httpx.AsyncClient(
        base_url="https://itunes.apple.com", transport=httpx.MockTransport(respond)
    )
    try:
        album = await client.lookup_release_metadata(APPLE_ALBUM)
        assert (album.title, album.duration_ms, album.track_count) == (
            "Unified",
            400000,
            2,
        )
        assert (await client.lookup_release_metadata(APPLE_ALBUM)).duration_ms == 400000
        assert requests[0].url.params["entity"] == "song"
        assert len(requests) == 1
        assert (
            await client.lookup_release_metadata(APPLE_ALBUM.replace("101", "999"))
            is None
        )
    finally:
        await client.aclose()


def spotify_page(kind="song"):
    return (
        f'<meta property="og:type" content="music.{kind}">'
        '<meta property="og:title" content="Dig">'
        '<meta property="music:musician_description" content="From This Point On">'
        f'<meta property="music:musician" content="{ARTIST}">'
        f'<meta property="music:album" content="{ALBUM}">'
        '<meta property="music:duration" content="222">'
    )


def test_spotify_opengraph_duration_uses_seconds_and_verified_links():
    track = parse_spotify_page(TRACK, spotify_page())
    assert (track.duration_ms, track.album_url, track.artist_url) == (
        222000,
        ALBUM,
        ARTIST,
    )


@run_async
async def test_spotify_fetches_album_name_without_guessing_from_track_title():
    client = SpotifyClient()
    await client._client.aclose()

    def respond(request):
        body = (
            spotify_page()
            if "/track/" in request.url.path
            else spotify_page("album").replace('content="Dig"', 'content="Unified"')
        )
        return httpx.Response(200, text=body)

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        track = await client.lookup_release(TRACK)
        assert track.album_title == "Unified"
        assert track.album_url == ALBUM
    finally:
        await client.aclose()


def test_spotify_album_embed_does_not_sum_a_partial_track_list():
    entity = {
        "type": "album",
        "title": "Unified",
        "subtitle": "From This Point On",
        "duration": 0,
        "trackList": [
            {"uri": "spotify:track:one", "duration": 222000},
            {"uri": "spotify:track:two", "duration": 178000},
        ],
    }
    html = '<script id="__NEXT_DATA__">' + json.dumps({"entity": entity}) + "</script>"
    assert parse_spotify_embed(ALBUM, html, expected_count=2).duration_ms == 400000
    assert parse_spotify_embed(ALBUM, html, expected_count=3).duration_ms is None


def test_spotify_embed_recovers_original_artwork_from_visual_identity():
    entity = {
        "type": "track",
        "title": "Dig",
        "subtitle": "From This Point On",
        "visualIdentity": {"image": [{"url": "https://i.scdn.co/image/original"}]},
    }
    html = '<script id="__NEXT_DATA__">' + json.dumps({"entity": entity}) + "</script>"
    assert parse_spotify_embed(TRACK, html).thumbnail_url == (
        "https://i.scdn.co/image/original"
    )


@run_async
async def test_slow_metadata_is_cancelled_without_losing_resolved_track():
    cancelled = asyncio.Event()

    async def slow_details(source):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    client = SimpleNamespace(
        lookup_track=AsyncMock(return_value=sample()),
        lookup_release_metadata=slow_details,
    )
    search = SimpleNamespace(lookup_genre=AsyncMock(return_value=None))
    with patch("music_links_bot.bot_lookup._RELEASE_ENRICHMENT_TIMEOUT_SECONDS", 0.001):
        tracks, unavailable = await _lookup_tracks(
            client, [TRACK], search_client=search
        )
    assert len(tracks) == 1 and unavailable == []
    assert cancelled.is_set()
    assert tracks[0].duration_ms is None


@run_async
async def test_enrichment_keeps_album_edition_and_artist_link_pairs_intact():
    track = sample()
    details = sample(
        album_title="Unified (Deluxe)",
        album_url=ALBUM,
        artist="Another Artist",
        artist_url=ARTIST,
        duration_ms=222000,
    )
    client = SimpleNamespace(lookup_release_metadata=AsyncMock(return_value=details))
    await _fill_release_metadata(client, SimpleNamespace(), [track])
    assert track.album_title == "Unified"
    assert track.album_url is None
    assert track.artist_url is None
    assert track.duration_ms == 222000


@run_async
async def test_optional_apple_details_deadline_keeps_a_known_album():
    client = SearchClient()
    candidate = _extract_release_candidates(apple_payload())[0]
    client._candidate_cache.set(APPLE_ALBUM, candidate)
    cancelled = asyncio.Event()

    async def slow_details(*args, **kwargs):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    real_wait_for = asyncio.wait_for

    async def short_deadline(awaitable, timeout):
        return await real_wait_for(awaitable, timeout=0.001)

    try:
        with (
            patch.object(client, "_lookup_apple_candidate", slow_details),
            patch("music_links_bot.search.asyncio.wait_for", short_deadline),
            patch.object(
                client._musicbrainz_client,
                "lookup_spotify_release",
                AsyncMock(return_value=None),
            ),
        ):
            result = await client.lookup_release_fallback(APPLE_ALBUM)
        assert result.title == "Unified"
        assert result.duration_ms is None
        assert cancelled.is_set()
    finally:
        await client.aclose()


def test_clean_default_preserves_saved_native_setting_old_drafts_and_longreads():
    track = sample()
    assert UserSession(user_id=7).default_artwork == "clean"
    with presentation_context():
        assert new_track_draft(track, chat_id=7, lang="ru")["as_photo"]
    saved = UserSession.from_dict({"user_id": 7, "default_artwork": "native"})
    draft = new_track_draft(track, chat_id=7, lang="ru")
    apply_preferences(draft, saved)
    assert not draft["as_photo"]
    old = {"type": "track", "item": asdict(track), "as_photo": False}
    assert not normalize_track_draft(old)["as_photo"]
    draft.update(publication_mode="longread", as_photo=False)
    apply_preferences(draft, UserSession(user_id=7))
    assert not draft["as_photo"]


@run_async
async def test_inline_uses_clean_image_but_honors_native_preference():
    ctx = ContextStub()
    with patch(
        "music_links_bot.bot_lookup._lookup_tracks",
        AsyncMock(return_value=([sample()], [])),
    ):
        with presentation_context():
            result = await _build_inline_result(TRACK, ctx)
        assert (
            result.input_message_content.link_preview_options.url
            == sample().thumbnail_url
        )
        with presentation_context(PresentationPreferences(artwork="native")):
            result = await _build_inline_result(TRACK, ctx)
        assert result.input_message_content.link_preview_options.url == TRACK


@run_async
@pytest.mark.parametrize(
    "error,fallback",
    [
        (BadRequest("Failed to get HTTP URL content"), True),
        (TimedOut(), False),
        (BadRequest("BUTTON_DATA_INVALID"), False),
    ],
)
async def test_photo_failure_fallback_never_duplicates_an_uncertain_send(
    error, fallback
):
    bot = SimpleNamespace(
        send_photo=AsyncMock(side_effect=error),
        send_message=AsyncMock(return_value=SimpleNamespace()),
    )
    ctx = SimpleNamespace(application=SimpleNamespace(bot_data={}), bot=bot)
    service = PublicationService(ctx, channel_username="stonerhand")
    draft = new_track_draft(sample(), chat_id=7, lang="ru")
    await service.deliver(draft, target=7, channel_style=False)
    assert bot.send_photo.await_count == 1
    assert bot.send_message.await_count == int(fallback)


def test_soundtrack_and_other_cards_have_consistent_ru_en_metadata():
    text = format_track_message(
        sample(
            kind="album",
            release_format="soundtrack",
            artist="Various Artists",
            track_count=19,
            duration_ms=400000,
        )
    )
    assert "Various Artists" not in text
    assert "Саундтрек · 2026 · 19 треков · 6:40" in text
    with language_context("en"):
        video = format_video_message(
            VideoMatch("Recording", "Uploader", "https://youtube.com/watch?v=abc")
        )
        playlist = format_playlist_message(
            PlaylistMatch("Mix", "Apple Music", APPLE_ALBUM)
        )
    assert "📺 · <b>Recording</b>\n\nVideo · YouTube\nSource: Uploader" in video
    assert "🎛 · <b>Mix</b>\n\nPlaylist · Apple Music" in playlist
