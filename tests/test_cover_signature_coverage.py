"""Every surface that shows release artwork shows it with the cover signature."""

import asyncio
import dataclasses
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from music_links_bot.core.draft_model import new_track_draft
from music_links_bot.core.models import TrackMatch
from music_links_bot.core.release_presentation import apply_preset
from music_links_bot.publishing.publication_model import MusicPublication
from music_links_bot.publishing.publication_service import PublicationService
from music_links_bot.publishing.publication_view import editor_preview_url

ENV = {
    "WEBHOOK_BASE_URL": "https://bot.example",
    "BOT_TOKEN": "1:test",
    "BRAND_PHOTO_FRAME": "1",
}
TRACK = TrackMatch(
    artist="Sleep",
    title="Dragonaut",
    thumbnail_url="https://i.scdn.co/image/cover",
    links={"spotify": "https://open.spotify.com/track/abc"},
)


def signed(url: str | None) -> bool:
    return bool(url) and "/api/collage?" in str(url)


async def publish(draft):
    bot = SimpleNamespace(
        send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1)),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)),
    )
    context = SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data={}))
    service = PublicationService(
        context,
        channel_username="stonerhand",
        branding_hooks=(
            lambda: True,
            AsyncMock(return_value=b"BRANDED"),
            lambda _: "@stonerhand",
            lambda: None,
        ),
    )
    await service.publish(draft)
    return bot


@pytest.mark.parametrize("preset", ["minimal", "cover", "longread"])
@pytest.mark.parametrize("kind", ["song", "album", "podcast", "video"])
def test_every_preset_and_kind_keeps_the_signature_even_with_long_text(preset, kind):
    track = dataclasses.replace(TRACK, kind=kind)
    with patch.dict(os.environ, ENV):
        for intro in ("", "Длинная подводка. " * 70):
            draft = new_track_draft(track, chat_id=7, lang="ru", prefix=intro)
            apply_preset(draft, preset)
            bot = asyncio.run(publish(draft))
            if bot.send_photo.await_count:
                assert bot.send_photo.await_args.kwargs["photo"] == b"BRANDED"
            else:
                options = bot.send_message.await_args.kwargs["link_preview_options"]
                assert signed(options.url), (kind, preset, len(intro))


def test_rejected_artwork_still_falls_back_to_the_native_preview():
    from telegram.error import BadRequest

    async def run():
        bot = SimpleNamespace(
            send_photo=AsyncMock(side_effect=BadRequest("webpage_media_empty")),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)),
        )
        context = SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data={}))
        service = PublicationService(
            context,
            channel_username="stonerhand",
            branding_hooks=(
                lambda: True,
                AsyncMock(return_value=b"BRANDED"),
                lambda _: "@stonerhand",
                lambda: None,
            ),
        )
        await service.publish(new_track_draft(TRACK, chat_id=7, lang="ru"))
        return bot

    with patch.dict(os.environ, ENV):
        bot = asyncio.run(run())
    options = bot.send_message.await_args.kwargs["link_preview_options"]
    assert options.url == "https://open.spotify.com/track/abc"


def test_editor_card_previews_the_signed_cover_it_will_publish():
    draft = new_track_draft(TRACK, chat_id=7, lang="ru")
    with patch.dict(os.environ, ENV):
        assert signed(editor_preview_url(draft, TRACK))
        draft["custom_cover_file_id"] = "AgACustom"
        # A Telegram file cannot be shown as a link preview.
        assert editor_preview_url(draft, TRACK) == TRACK.links["spotify"]


def test_editor_card_falls_back_when_branding_is_off():
    draft = new_track_draft(TRACK, chat_id=7, lang="ru")
    with patch.dict(os.environ, {**ENV, "BRAND_PHOTO_FRAME": "0"}):
        assert editor_preview_url(draft, TRACK) == TRACK.links["spotify"]


def test_rich_and_song_clip_media_use_the_signed_cover():
    from music_links_bot.core.models import VideoMatch

    video = VideoMatch(
        title="Clip",
        author="Sleep",
        url="https://www.youtube.com/watch?v=abc",
        thumbnail_url="https://i.ytimg.com/vi/abc/hq.jpg",
    )
    with patch.dict(os.environ, ENV):
        single = MusicPublication.from_track(TRACK)
        pair = MusicPublication.from_track_video(TRACK, video)
    assert signed(single.media[0].url)
    assert signed(pair.media[0].url)
    # The clip keeps its own YouTube frame.
    assert pair.media[1].url == video.thumbnail_url


def test_song_clip_album_uploads_the_signed_cover():
    from music_links_bot.core.models import VideoMatch
    from music_links_bot.lookup import mixed_post

    bot = SimpleNamespace(
        send_media_group=AsyncMock(return_value=[object(), object()]),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)),
    )
    video = VideoMatch(
        title="Clip",
        author="Sleep",
        url="https://www.youtube.com/watch?v=abc",
        thumbnail_url="https://i.ytimg.com/vi/abc/hq.jpg",
    )
    with (
        patch.dict(os.environ, ENV),
        patch.object(mixed_post, "rich_messages_enabled", return_value=False),
    ):
        asyncio.run(
            mixed_post.send_track_video_album(
                bot,
                chat_id=7,
                track=TRACK,
                video_title=video.title,
                video_url=video.url,
                video_thumbnail_url=video.thumbnail_url,
                caption="Song",
                reply_markup=None,
            )
        )
    media = bot.send_media_group.await_args.kwargs["media"]
    assert signed(media[0].media)
    assert media[1].media == video.thumbnail_url


def test_group_link_card_uses_the_signed_cover():
    from test_bot import ContextStub, ReplaceableMessageStub, UpdateStub

    from music_links_bot.lookup.bot_lookup_flow import (
        track_lookup_message,
    )

    class Songlink:
        async def lookup_track(self, url):
            return TRACK

        async def lookup_release_metadata(self, url):
            return TRACK

    context = ContextStub(songlink_client=Songlink())
    message = ReplaceableMessageStub()
    message.text = "https://open.spotify.com/track/abc"
    with patch.dict(os.environ, ENV):
        asyncio.run(track_lookup_message(UpdateStub(message), context))
    previews = [
        kwargs["link_preview_options"].url
        for kwargs in [*context.bot.sent_messages, *message.reply_kwargs]
        if kwargs.get("link_preview_options") is not None
    ]
    assert previews and all(signed(url) for url in previews)
