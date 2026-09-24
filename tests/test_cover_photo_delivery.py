import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, TimedOut

from music_links_bot.bot_inline import _inline_article
from music_links_bot.collection_collage import branded_artwork_preview_url
from music_links_bot.keyboards import _build_link_preview_options
from music_links_bot.models import TrackMatch
from music_links_bot.publication_service import PublicationService

ENV = {
    "WEBHOOK_BASE_URL": "https://bot.example",
    "BOT_TOKEN": "test",
    "BRAND_PHOTO_FRAME": "1",
}
TRACK = TrackMatch(
    artist="Artist",
    title="Song",
    thumbnail_url="https://i.scdn.co/image/cover",
    links={"spotify": "https://open.spotify.com/track/abc"},
)


def test_generated_image_never_requests_empty_small_card():
    with patch.dict(os.environ, ENV):
        url = branded_artwork_preview_url(TRACK.thumbnail_url)
        options = _build_link_preview_options(url, prefer_large_media=False)
    assert options.prefer_large_media is True
    assert options.show_above_text is True
    assert not options.prefer_small_media


@pytest.mark.parametrize("length,kind", [(1024, "photo"), (1025, "article")])
def test_inline_caption_boundary_preserves_full_text(length, kind):
    with patch.dict(os.environ, ENV):
        result = _inline_article(
            "https://open.spotify.com/track/abc",
            title="Collection",
            description="Tracks",
            text="x" * length,
            keyboard=InlineKeyboardMarkup([]),
            preview_url=branded_artwork_preview_url(TRACK.thumbnail_url),
            thumbnail_url=TRACK.thumbnail_url,
        )
    assert result.type == kind
    actual = (
        result.caption if kind == "photo" else result.input_message_content.message_text
    )
    assert actual == "x" * length


@pytest.mark.parametrize("error", [None, BadRequest("webpage_media_empty"), TimedOut()])
def test_classic_signed_cover_uploads_bytes_and_only_safe_failure_falls_back(error):
    asyncio.run(_check_delivery(error))


async def _check_delivery(error):
    bot = SimpleNamespace(
        send_photo=AsyncMock(side_effect=error, return_value=SimpleNamespace()),
        send_message=AsyncMock(return_value=SimpleNamespace()),
    )
    context = SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data={}))
    service = PublicationService(
        context,
        channel_username="stonerhand",
        branding_hooks=(
            lambda: True,
            AsyncMock(return_value=b"branded-jpeg"),
            lambda _: "@stonerhand",
            lambda: None,
        ),
    )
    with patch.dict(os.environ, ENV):
        if isinstance(error, TimedOut):
            with pytest.raises(TimedOut):
                await service._send(
                    {"as_photo": False}, TRACK, target=1, channel_style=False
                )
        else:
            await service._send(
                {"as_photo": False}, TRACK, target=1, channel_style=False
            )
    assert bot.send_photo.await_args.kwargs["photo"] == b"branded-jpeg"
    if isinstance(error, BadRequest):
        assert bot.send_message.await_count == 1
        assert (
            bot.send_message.await_args.kwargs["link_preview_options"].url
            == TRACK.links["spotify"]
        )
    else:
        bot.send_message.assert_not_awaited()
