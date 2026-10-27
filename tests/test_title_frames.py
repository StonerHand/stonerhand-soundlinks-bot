"""Film and series stills keep their 16:9 shape and get the cover signature."""

import asyncio
import io
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from PIL import Image

from music_links_bot.collection_collage import (
    FRAME_MODE,
    FRAME_SIZE,
    MAX_ARTWORK_BYTES,
    VIDEO_MODE,
    _safe_source_url,
    branded_frame_preview_url,
    compose_frame,
    decode_collage_payload,
)
from music_links_bot.models import TitleMatch

ENV = {"WEBHOOK_BASE_URL": "https://bot.example", "BOT_TOKEN": "1:x"}
HERO = "https://occ-0-1.1.nflxso.net/dnm/api/v6/x/hero.jpg?r=dab"
DISNEY = "https://disney.images.edge.bamgrid.com/ripcut-delivery/v2/x.jpeg"
APPLE = "https://is1-ssl.mzstatic.com/image/thumb/abc/1200x675.jpg"


def _jpeg(size, color) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_streaming_stills_come_only_from_the_services_own_hosts():
    for url in (HERO, DISNEY, APPLE):
        assert _safe_source_url(url)
    for url in (
        "https://nflxso.net.evil.example/x.jpg",
        "https://evilnflxso.net/x.jpg",
        "https://bamgrid.com/x.jpg",
        "http://occ-0-1.1.nflxso.net/x.jpg",
    ):
        assert not _safe_source_url(url)


def test_frame_url_is_signed_with_the_frame_mode():
    with patch.dict(os.environ, ENV):
        url = branded_frame_preview_url(HERO)
    assert url and url.startswith("https://bot.example/api/collage?")
    query = _query(url)
    assert query["m"] == [FRAME_MODE]
    payload, signature = query["p"][0], query["s"][0]
    assert decode_collage_payload(
        payload, signature, signing_secret="1:x", allow_single=True, mode=FRAME_MODE
    ) == [HERO]
    # The mode is signed: the same still cannot be asked for as a square cover.
    assert (
        decode_collage_payload(
            payload, signature, signing_secret="1:x", allow_single=True
        )
        is None
    )


def test_frame_url_needs_branding_and_a_known_still():
    with patch.dict(os.environ, {**ENV, "BRAND_PHOTO_FRAME": "0"}):
        assert branded_frame_preview_url(HERO) is None
    with patch.dict(os.environ, ENV):
        assert branded_frame_preview_url(None) is None
        assert branded_frame_preview_url("https://images.example/x.jpg") is None


def test_a_wide_still_keeps_its_shape_and_gets_the_footer():
    still = _jpeg((1920, 1080), (40, 120, 220))
    with Image.open(io.BytesIO(compose_frame(still, label="@stonerhand"))) as image:
        rgb = image.convert("RGB")
        assert rgb.size == FRAME_SIZE
        top = rgb.getpixel((FRAME_SIZE[0] - 20, 20))
        footer = rgb.getpixel((FRAME_SIZE[0] - 20, FRAME_SIZE[1] - 5))
        assert top[2] > 180
        assert footer[2] < top[2] - 80  # the dark signature gradient
        # The label is drawn in white over the footer's left side.
        label_box = rgb.crop((40, FRAME_SIZE[1] - 110, 400, FRAME_SIZE[1] - 20))
        assert label_box.convert("L").getextrema()[1] > 200


def test_a_square_or_tall_still_is_cropped_to_the_screen_shape():
    for size in ((800, 800), (600, 900)):
        with Image.open(io.BytesIO(compose_frame(_jpeg(size, (90, 90, 90))))) as image:
            assert image.size == FRAME_SIZE


def test_broken_or_oversized_stills_are_refused():
    assert compose_frame(b"not an image") is None
    assert compose_frame(b"x" * (MAX_ARTWORK_BYTES + 1)) is None
    with patch("music_links_bot.collection_collage.MAX_ARTWORK_PIXELS", 100):
        assert compose_frame(_jpeg((20, 20), (1, 2, 3))) is None


class _Request:
    def __init__(self, url: str) -> None:
        parsed = urlparse(url)
        self.path = f"{parsed.path}?{parsed.query}"
        self.headers: dict[str, str] = {}
        self.wfile = io.BytesIO()
        self.status = None

    def send_response(self, status) -> None:
        self.status = status

    def send_header(self, name, value) -> None:
        self.headers[name] = value

    def end_headers(self) -> None:
        pass

    def send_error(self, status) -> None:
        raise AssertionError(status)


def _serve(url: str, fetch) -> Image.Image:
    from api.collage import handler

    request = _Request(url)
    with patch("api.collage._fetch_artwork", side_effect=fetch):
        handler.do_GET(request)
    assert request.status == 200
    with Image.open(io.BytesIO(request.wfile.getvalue())) as image:
        return image.convert("RGB")


def test_the_endpoint_serves_a_signed_wide_still():
    with patch.dict(os.environ, ENV):
        url = branded_frame_preview_url(HERO)
        image = _serve(url, lambda _source: _jpeg((1920, 1080), (200, 40, 40)))
    assert image.size == FRAME_SIZE


def test_an_unreadable_still_falls_back_to_the_original_image():
    from api.collage import handler

    with patch.dict(os.environ, ENV):
        request = _Request(branded_frame_preview_url(HERO))
        with patch("api.collage._fetch_artwork", return_value=b"not an image"):
            handler.do_GET(request)
    assert request.status == 302
    assert request.headers["location"] == HERO


def test_a_video_collage_that_lost_frames_stays_a_square_cover():
    """Only a one-video card is a wide frame; a collage whose other frames
    failed to download is still the usual square signed cover."""
    from music_links_bot.collection_collage import video_collage_preview_url
    from music_links_bot.models import VideoMatch

    videos = [
        VideoMatch(
            title=name,
            author="Sleep",
            url=f"https://www.youtube.com/watch?v={name}",
            thumbnail_url=f"https://i.ytimg.com/vi/{name}/hqdefault.jpg",
        )
        for name in ("a", "b")
    ]
    with patch.dict(os.environ, ENV):
        url = video_collage_preview_url(videos)
        assert _query(url)["m"] == [VIDEO_MODE]
        # One of the two frames failed to download.
        image = _serve(
            url,
            lambda source: (
                _jpeg((480, 270), (40, 40, 200)) if "/a/" in source else None
            ),
        )
    assert image.size == (1200, 1200)


def _title() -> TitleMatch:
    return TitleMatch(
        title="Cyberpunk: Edgerunners",
        url="https://www.netflix.com/id-en/title/81054853",
        watch_url="https://www.netflix.com/title/81054853",
        image_url=HERO,
    )


def _send_card(env: dict[str, str]) -> str:
    from music_links_bot.lookup_delivery import send_title_result

    send = AsyncMock()
    with patch.dict(os.environ, env):
        asyncio.run(
            send_title_result(
                SimpleNamespace(username="StonerHandBot"),
                SimpleNamespace(),
                [_title()],
                send_track_result=send,
                user_prefix="",
                include_channel_button=False,
                include_hashtags=True,
                lang="ru",
            )
        )
    return send.await_args.kwargs["preview_url"]


def test_a_title_card_previews_the_signed_still():
    preview = _send_card(ENV)
    assert preview.startswith("https://bot.example/api/collage?")
    assert _query(preview)["m"] == [FRAME_MODE]
    # Without branding the card falls back to the plain still.
    assert _send_card({**ENV, "BRAND_PHOTO_FRAME": "0"}) == HERO


def test_a_shared_card_previews_the_signed_still_and_lists_the_plain_one():
    from test_bot import ContextStub
    from test_titles import SERIES_URL, _NetflixStub

    from music_links_bot.bot_inline import _build_inline_result

    context = ContextStub()
    context.application.bot_data["title_client"] = _NetflixStub()
    with patch.dict(os.environ, ENV):
        result = asyncio.run(_build_inline_result(SERIES_URL, context))

    assert result is not None
    assert result.thumbnail_url == HERO
    preview = result.input_message_content.link_preview_options.url
    assert _query(preview)["m"] == [FRAME_MODE]
