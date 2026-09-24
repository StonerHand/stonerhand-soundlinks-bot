import asyncio
import io
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from api.collage import handler
from music_links_bot.bot_inline import _build_inline_result
from music_links_bot.collection_collage import (
    branded_artwork_preview_url,
    decode_collage_payload,
)
from music_links_bot.collection_plan import build_collection_plan
from music_links_bot.models import TrackMatch

ENV = {
    "BOT_TOKEN": "test-signing-secret",
    "WEBHOOK_BASE_URL": "https://bot.example",
    "BRAND_PHOTO_FRAME": "1",
    "BRAND_LABEL": "@stonerhand",
}


def track(index=0, same=False):
    return TrackMatch(
        title=f"Track {index}",
        artist="Artist",
        links={"spotify": f"https://open.spotify.com/track/{index}"},
        thumbnail_url=f"https://i.scdn.co/image/{0 if same else index}",
    )


def decoded(url):
    query = parse_qs(urlparse(url).query)
    return decode_collage_payload(
        query["p"][0], query["s"][0], signing_secret=ENV["BOT_TOKEN"], allow_single=True
    )


@pytest.mark.parametrize(
    "count,same,expected", [(2, False, 2), (6, False, 6), (10, False, 6), (4, True, 1)]
)
def test_collection_preview_always_routes_available_cover_through_signature(
    count, same, expected
):
    with patch.dict(os.environ, ENV):
        plan = build_collection_plan(
            [track(i, same) for i in range(count)], title="Collection"
        )
    assert urlparse(plan.preview_url).path == "/api/collage"
    assert len(decoded(plan.preview_url)) == expected
    assert len(plan.source_urls) == count


def test_single_inline_uses_branded_preview_and_preserves_buttons():
    async def run():
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={"songlink_client": object(), "soundcloud_client": object()}
            ),
            bot=SimpleNamespace(username="Bot"),
        )
        with (
            patch.dict(os.environ, ENV),
            patch(
                "music_links_bot.bot_inline.bot_lookup._lookup_tracks",
                new=AsyncMock(return_value=([track()], [])),
            ),
        ):
            result = await _build_inline_result(track().links["spotify"], context)
        url = result.input_message_content.link_preview_options.url
        assert decoded(url) == [track().thumbnail_url]
        assert result.reply_markup.inline_keyboard

    asyncio.run(run())


@pytest.mark.parametrize("count", [1, 6])
def test_signed_endpoint_draws_signature_on_single_and_collection(count):
    source = io.BytesIO()
    Image.new("RGB", (300, 300), (80, 60, 90)).save(source, "PNG")
    with patch.dict(os.environ, ENV):
        url = (
            branded_artwork_preview_url(track().thumbnail_url)
            if count == 1
            else build_collection_plan(
                [track(i) for i in range(count)], title="Collection"
            ).preview_url
        )

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
        with patch("api.collage._fetch_artwork", return_value=source.getvalue()):
            handler.do_GET(request)
    assert request.status == 200
    with Image.open(io.BytesIO(request.wfile.getvalue())) as image:
        assert image.size == (1200, 1200)
        footer = image.crop((40, 1050, 500, 1190))
        assert sum(1 for r, g, b in footer.getdata() if min(r, g, b) > 180) > 300


def test_signature_cannot_turn_endpoint_into_arbitrary_image_proxy():
    with patch.dict(os.environ, ENV):
        assert branded_artwork_preview_url("https://127.0.0.1/private") is None
        url = branded_artwork_preview_url(track().thumbnail_url)
    query = parse_qs(urlparse(url).query)
    assert (
        decode_collage_payload(
            query["p"][0], "wrong", signing_secret=ENV["BOT_TOKEN"], allow_single=True
        )
        is None
    )
    assert (
        decode_collage_payload(
            query["p"][0], query["s"][0], signing_secret=ENV["BOT_TOKEN"]
        )
        is None
    )
