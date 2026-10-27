"""A one-video card previews its own frame: 16:9, ▶, the signature, and the
sharpest frame YouTube has."""

import io
import os
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from PIL import Image

from music_links_bot.collection_collage import (
    FRAME_SIZE,
    VIDEO_MODE,
    branded_video_frame_url,
    decode_collage_payload,
)
from music_links_bot.models import VideoMatch
from music_links_bot.youtube import video_preview_url

ENV = {"WEBHOOK_BASE_URL": "https://bot.example", "BOT_TOKEN": "1:x"}
VIDEO = "https://www.youtube.com/watch?v=E3mSkI9uskw"
HQ = "https://i.ytimg.com/vi/E3mSkI9uskw/hqdefault.jpg"
MAXRES = "https://i.ytimg.com/vi/E3mSkI9uskw/maxresdefault.jpg"


def _jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "JPEG")
    return out.getvalue()


def _letterboxed_frame() -> bytes:
    """YouTube's 4:3 thumbnail: black bars around a green 16:9 frame."""
    image = Image.new("RGB", (480, 360), (0, 0, 0))
    image.paste((40, 200, 40), (0, 45, 480, 315))
    return _jpeg(image)


def test_a_video_card_previews_its_signed_frame():
    video = VideoMatch(title="iOS 27.2", author="ProTech", url=VIDEO, thumbnail_url=HQ)
    with patch.dict(os.environ, ENV):
        preview = video_preview_url(video)
        url = branded_video_frame_url(HQ)

    assert preview == url and preview.startswith("https://bot.example/api/collage?")
    query = parse_qs(urlparse(url).query)
    assert query["m"] == [VIDEO_MODE]
    assert decode_collage_payload(
        query["p"][0],
        query["s"][0],
        signing_secret="1:x",
        allow_single=True,
        mode=VIDEO_MODE,
    ) == [HQ]
    # Without branding the card keeps YouTube's plain still.
    with patch.dict(os.environ, {**ENV, "BRAND_PHOTO_FRAME": "0"}):
        assert video_preview_url(video) == HQ


def test_the_endpoint_draws_a_wide_frame_with_play_and_no_bars():
    from api.collage import handler

    with patch.dict(os.environ, ENV):
        url = branded_video_frame_url(HQ)

        class Request:
            path = f"{urlparse(url).path}?{urlparse(url).query}"

            def __init__(self):
                self.headers: dict[str, str] = {}
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
        with patch("api.collage._fetch_sharpest", return_value=_letterboxed_frame()):
            handler.do_GET(request)

    assert request.status == 200
    with Image.open(io.BytesIO(request.wfile.getvalue())) as image:
        rgb = image.convert("RGB")
        assert rgb.size == FRAME_SIZE
        top = rgb.getpixel((20, 5))
        assert top[1] > 150 and top[0] < 100  # the frame, not a black bar
        assert min(rgb.getpixel((FRAME_SIZE[0] // 2, FRAME_SIZE[1] // 2))) > 200


def test_the_sharpest_youtube_frame_is_fetched_first():
    from api.collage import _fetch_sharpest

    calls: list[str] = []

    def fetch(url):
        calls.append(url)
        return b"maxres" if url == MAXRES else b"hq"

    with patch("api.collage._fetch_artwork", side_effect=fetch):
        assert _fetch_sharpest(HQ) == b"maxres"
    assert calls == [MAXRES]

    calls.clear()
    with patch(
        "api.collage._fetch_artwork",
        side_effect=lambda url: calls.append(url) or (None if url == MAXRES else b"hq"),
    ):
        # Older videos have no 1280×720 frame: the 480×360 one is used.
        assert _fetch_sharpest(HQ) == b"hq"
    assert calls == [MAXRES, HQ]

    calls.clear()
    other = "https://i.scdn.co/image/cover"
    with patch(
        "api.collage._fetch_artwork", side_effect=lambda url: calls.append(url) or b"x"
    ):
        assert _fetch_sharpest(other) == b"x"
    assert calls == [other]
