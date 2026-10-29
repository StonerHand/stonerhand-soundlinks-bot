"""Posts with several videos, or a song with its clips, as one tidy post."""

import asyncio
import io
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from music_links_bot.cards.video_kinds import video_kind, video_kind_labels
from music_links_bot.core.models import TrackMatch, VideoMatch

ENV = {"WEBHOOK_BASE_URL": "https://bot.example", "BOT_TOKEN": "1:x"}


def clip(title: str, vid: str = "a") -> VideoMatch:
    return VideoMatch(
        title=title,
        author="Sleep",
        url=f"https://www.youtube.com/watch?v={vid}",
        thumbnail_url=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
    )


TRACK = TrackMatch(
    artist="Sleep",
    title="Dragonaut",
    thumbnail_url="https://i.scdn.co/image/cover",
    links={"spotify": "https://open.spotify.com/track/abc"},
)


@pytest.mark.parametrize(
    "title,kind",
    [
        ("Sleep - Dragonaut (Official Music Video)", "clip"),
        ("Sleep – Dragonaut [Official Video]", "clip"),
        ("Sleep - Dragonaut (Official Lyric Video)", "lyric"),
        ("Sleep - Dragonaut (Live at Roadburn 2012)", "live"),
        ("Sleep — Dragonaut | KEXP", "live"),
        ("Sleep - Dragonaut (Acoustic)", "acoustic"),
        ("Sleep - Dragonaut (Official Visualizer)", "visualizer"),
        ("Sleep - Dragonaut (Official Audio)", "audio"),
        ("Сон — Драгонавт (клип)", "clip"),
        ("Sleep - Dragonaut", "video"),
    ],
)
def test_video_kind_reads_the_title(title, kind):
    assert video_kind(clip(title)) == kind


def test_duplicate_kinds_get_numbers():
    labels = video_kind_labels(
        [clip("A (Official Video)"), clip("B (Live)"), clip("C (Live)")]
    )
    assert labels == ["🎬 Клип", "🎤 Live 1", "🎤 Live 2"]


def test_song_with_clips_is_one_post_with_named_buttons():
    from music_links_bot.cards.formatter import format_mixed_collection_message
    from music_links_bot.cards.keyboards import _build_mixed_collection_keyboard

    videos = [
        clip("Dragonaut (Official Video)", "a"),
        clip("Dragonaut (Live at Roadburn)", "b"),
        clip("Dragonaut (Lyric Video)", "c"),
    ]
    text = format_mixed_collection_message([TRACK], videos)
    assert text.startswith("<b>Песня + 3 видео</b>")
    assert "🎬 · <b>Dragonaut (Official Video)</b>" in text
    assert "🎤 · <b>Dragonaut (Live at Roadburn)</b>" in text

    rows = _build_mixed_collection_keyboard([TRACK], videos).inline_keyboard
    assert [b.text for b in rows[0]] == ["🎧 Слушать песню"]
    assert rows[0][0].style == "primary"
    assert [b.text for b in rows[1]] == ["🎬 Клип", "🎤 Live", "📝 Lyric video"]
    assert [b.url for b in rows[1]] == [v.url for v in videos]


def test_video_collage_url_is_signed_with_its_mode():
    from music_links_bot.artwork.collection_collage import (
        MIX_MODE,
        VIDEO_MODE,
        decode_collage_payload,
        video_collage_preview_url,
    )

    with patch.dict(os.environ, ENV):
        mixed = video_collage_preview_url([clip("A", "a")], track=TRACK)
        only = video_collage_preview_url([clip("A", "a"), clip("B", "b")])
        assert video_collage_preview_url([clip("A", "a")]) is None  # one frame
    for url, mode in ((mixed, MIX_MODE), (only, VIDEO_MODE)):
        query = parse_qs(urlparse(url).query)
        assert query["m"] == [mode]
        payload, signature = query["p"][0], query["s"][0]
        assert decode_collage_payload(
            payload, signature, signing_secret="1:x", mode=mode
        )
        # The mode is covered by the signature: it cannot be swapped.
        other = VIDEO_MODE if mode == MIX_MODE else MIX_MODE
        assert (
            decode_collage_payload(payload, signature, signing_secret="1:x", mode=other)
            is None
        )


def _jpeg(size, color):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def test_collage_trims_letterbox_and_badges_video_frames():
    from music_links_bot.artwork.collection_collage import compose_collection_collage

    cover = _jpeg((600, 600), (200, 40, 40))
    # A 4:3 YouTube thumbnail: black bars around a green 16:9 frame.
    frame = Image.new("RGB", (480, 360), (0, 0, 0))
    frame.paste((40, 200, 40), (0, 45, 480, 315))
    raw = io.BytesIO()
    frame.save(raw, "JPEG")
    collage = compose_collection_collage(
        [cover, raw.getvalue()], size=400, gap=0, play=[False, True]
    )
    with Image.open(io.BytesIO(collage)) as image:
        rgb = image.convert("RGB")
        # Right half is the video tile: its centre carries the white ▶ badge,
        # and its top edge is the green frame, not a black bar.
        assert min(rgb.getpixel((300, 200))) > 200
        top = rgb.getpixel((300, 5))
        assert top[1] > 150 and top[0] < 100
        # The cover tile stays clean.
        left = rgb.getpixel((100, 200))
        assert left[0] > 150 and left[1] < 80


def test_song_with_clips_goes_out_as_one_post_with_the_collage():
    from music_links_bot.lookup.lookup_delivery import send_mixed_result

    send_track_result = AsyncMock()
    send_pair = AsyncMock(return_value=True)
    with patch.dict(os.environ, ENV):
        asyncio.run(
            send_mixed_result(
                SimpleNamespace(),
                SimpleNamespace(),
                [TRACK],
                [clip("Dragonaut (Official Video)", "a"), clip("Live", "b")],
                [],
                [],
                [],
                send_track_result=send_track_result,
                send_track_video_pair_result=send_pair,
                user_prefix="",
                include_channel_button=False,
                include_hashtags=True,
                context=SimpleNamespace(application=SimpleNamespace(bot_data={})),
                lang="ru",
            )
        )
    send_pair.assert_not_awaited()
    kwargs = send_track_result.await_args.kwargs
    assert "/api/collage?" in kwargs["preview_url"]
    assert "m=m" in kwargs["preview_url"]
    labels = [b.text for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert labels[:3] == ["🎧 Слушать песню", "🎬 Клип", "🎤 Live"]


def test_several_videos_show_a_frame_collage_instead_of_one_player():
    from music_links_bot.lookup.lookup_delivery import send_youtube_result

    send_track_result = AsyncMock()
    with patch.dict(os.environ, ENV):
        asyncio.run(
            send_youtube_result(
                SimpleNamespace(),
                SimpleNamespace(),
                [clip("A (Official Video)", "a"), clip("B (Live)", "b")],
                send_track_result=send_track_result,
                user_prefix="",
                include_channel_button=False,
                include_hashtags=True,
                lang="ru",
            )
        )
    kwargs = send_track_result.await_args.kwargs
    assert "m=v" in kwargs["preview_url"]
    labels = [b.text for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert labels[0].startswith("🎬 1 · ") and labels[1].startswith("🎤 2 · ")


def test_collage_endpoint_draws_play_badges_for_the_signed_mode():
    from api.collage import handler
    from music_links_bot.artwork.collection_collage import video_collage_preview_url

    cover = _jpeg((300, 300), (200, 40, 40))
    frame = _jpeg((480, 270), (40, 40, 200))
    with patch.dict(os.environ, ENV):
        url = video_collage_preview_url([clip("A", "a")], track=TRACK)

        class Request:
            path = urlparse(url).path + "?" + urlparse(url).query

            def __init__(self):
                self.headers = {}
                self.wfile = io.BytesIO()

            def send_response(self, status):
                self.status = status

            def send_header(self, name, value):
                pass

            def end_headers(self):
                pass

            def send_error(self, status):
                raise AssertionError(status)

        request = Request()
        with patch(
            "api.collage._fetch_artwork",
            side_effect=lambda source: cover if "scdn" in source else frame,
        ):
            handler.do_GET(request)
    assert request.status == 200
    with Image.open(io.BytesIO(request.wfile.getvalue())) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        # Cover (left) without a badge, video frame (right) with a white ▶.
        assert min(rgb.getpixel((width * 3 // 4, height // 2))) > 200
        assert rgb.getpixel((width // 4, height // 2))[0] > 150


def test_several_songs_and_clips_share_one_collage_with_badges_only_on_frames():
    from music_links_bot.artwork.collection_collage import (
        collage_play_flags,
        decode_collage_payload,
        media_collage_preview_url,
    )
    from music_links_bot.lookup.lookup_delivery import send_mixed_result

    second = TrackMatch(
        artist="The Growlers",
        title="City Club",
        thumbnail_url="https://i.scdn.co/image/cover2",
        links={"spotify": "https://open.spotify.com/track/def"},
    )
    videos = [clip("Monotonia (Official Video)", "a"), clip("Love Test", "b")]
    with patch.dict(os.environ, ENV):
        url = media_collage_preview_url([TRACK, second], videos)
        query = parse_qs(urlparse(url).query)
        assert query["m"] == ["b0011"]
        assert collage_play_flags("b0011", 4) == [False, False, True, True]
        assert decode_collage_payload(
            query["p"][0], query["s"][0], signing_secret="1:x", mode="b0011"
        )
        # A forged bit string does not pass the signature.
        assert (
            decode_collage_payload(
                query["p"][0], query["s"][0], signing_secret="1:x", mode="b1111"
            )
            is None
        )

        send_track_result = AsyncMock()
        asyncio.run(
            send_mixed_result(
                SimpleNamespace(),
                SimpleNamespace(),
                [TRACK, second],
                videos,
                [],
                [],
                [],
                send_track_result=send_track_result,
                send_track_video_pair_result=AsyncMock(),
                user_prefix="",
                include_channel_button=False,
                include_hashtags=True,
                context=SimpleNamespace(application=SimpleNamespace(bot_data={})),
                lang="ru",
            )
        )
    kwargs = send_track_result.await_args.kwargs
    assert "m=b0011" in kwargs["preview_url"]
    labels = [b.text for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert any(label.startswith("🎬 3 · ") for label in labels)


def test_collage_with_only_songs_never_uses_the_media_mode():
    from music_links_bot.artwork.collection_collage import media_collage_preview_url

    with patch.dict(os.environ, ENV):
        assert media_collage_preview_url([TRACK, TRACK], []) is None


def test_six_songs_and_clips_still_get_a_collage_with_frames():
    """Six songs used to fill every tile, so the mixed collage was dropped."""
    from music_links_bot.artwork.collection_collage import media_collage_preview_url

    songs = [
        TrackMatch(
            artist="POEXXXALI",
            title=f"Song {index}",
            thumbnail_url=f"https://i.scdn.co/image/cover{index}",
            links={"spotify": f"https://open.spotify.com/track/{index}"},
        )
        for index in range(6)
    ]
    videos = [clip(f"Clip {index}", f"v{index}") for index in range(4)]
    with patch.dict(os.environ, ENV):
        url = media_collage_preview_url(songs, videos)
    assert url is not None
    query = parse_qs(urlparse(url).query)
    assert query["m"] == ["b000011"]


def test_video_kinds_and_pair_heading_are_translated():
    from music_links_bot.cards.formatter import (
        format_track_videos_message,
        format_video_message,
    )
    from music_links_bot.core.i18n import preferred_language

    token = preferred_language.set("en")
    try:
        text = format_track_videos_message(TRACK, [clip("Song (Official Video)", "a")])
        single = format_video_message(clip("Song (Official Video)", "a"))
    finally:
        preferred_language.reset(token)
    assert text.startswith("<b>Song + music video</b>")
    assert "🎬 Music video · YouTube" in single
