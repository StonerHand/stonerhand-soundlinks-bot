from dataclasses import asdict
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import pytest

from music_links_bot.formatter import format_track_message
from music_links_bot.i18n import language_context
from music_links_bot.models import TrackMatch
from music_links_bot.publication_budget import visible_length
from music_links_bot.publication_service import PublicationService
from music_links_bot.publication_view import build_publication_view


def sample(**overrides):
    return TrackMatch(
        **{
            "title": "Dig",
            "artist": "From This Point On",
            "release_year": "2026",
            "album_title": "Unified",
            "links": {"spotify": "https://open.spotify.com/track/dig"},
            "thumbnail_url": "https://i.scdn.co/image/cover",
            **overrides,
        }
    )


def test_agreed_track_caption_and_structural_tags():
    assert format_track_message(sample()) == (
        "🎧 · <b>Dig</b>\nFrom This Point On\n\n"
        "Трек · 2026\n💿 Из альбома «Unified»\n\n#stonerhand #track"
    )


@pytest.mark.parametrize("album", [None, "", " \n\t "])
def test_unknown_album_is_omitted_without_placeholder(album):
    text = format_track_message(sample(album_title=album, release_year=None))
    assert text == "🎧 · <b>Dig</b>\nFrom This Point On\n\nТрек\n\n#stonerhand #track"


def test_album_metadata_is_escaped_and_does_not_change_type_tags():
    text = format_track_message(sample(album_title="<b>Live & Rare</b>\nEdition"))
    assert "💿 Из альбома «&lt;b&gt;Live &amp; Rare&lt;/b&gt; Edition»" in text
    assert text.count("<b>") == 1
    assert text.endswith("#stonerhand #track")


def test_album_card_does_not_repeat_membership_and_keeps_verified_counts():
    text = format_track_message(sample(kind="album", track_count=12))
    assert text.startswith(
        "💿 · <b>Dig</b>\nFrom This Point On\n\nАльбом · 2026 · 12 треков"
    )
    assert "Из альбома" not in text
    assert text.endswith("#stonerhand #album")


def test_caption_localizes_metadata_and_rejects_unverified_year():
    with language_context("en"):
        text = format_track_message(sample(release_year="2026?"))
    assert "Track\n💿 From the album «Unified»" in text
    assert "2026" not in text


def test_long_metadata_keeps_album_line_and_tags_within_photo_caption():
    text = format_track_message(
        sample(title="🎶" * 200, artist="Я" * 250, album_title="💿" * 200)
    )
    assert visible_length(text) <= 1024
    assert "💿 Из альбома" in text
    assert text.endswith("#stonerhand #track")


def test_longread_remains_an_explicit_separate_format():
    track = sample()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
    for mode, expected in (("card", "classic"), ("longread", "auto")):
        view = build_publication_view(
            {"publication_mode": mode, "delivery_mode": "auto"},
            track,
            context=context,
            include_channel_button=False,
        )
        assert view.delivery_mode == expected


class TestNativeDelivery(IsolatedAsyncioTestCase):
    async def test_preview_and_delivery_send_same_caption_without_rich(self):
        track = sample()
        bot = SimpleNamespace(
            send_photo=AsyncMock(return_value=SimpleNamespace()),
            send_message=AsyncMock(return_value=SimpleNamespace()),
        )
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}), bot=bot)
        service = PublicationService(context, channel_username="stonerhand")
        draft = {
            "item": asdict(track),
            "as_photo": True,
            "custom_cover_file_id": "original-cover",
            "publication_mode": "card",
            "delivery_mode": "auto",
        }
        with (
            patch(
                "music_links_bot.rich_publications.rich_messages_enabled",
                return_value=True,
            ),
            patch(
                "music_links_bot.rich_publications.send_rich_publication",
                new=AsyncMock(),
            ) as rich,
        ):
            await service.preview(draft, target=7)
            await service.deliver(draft, target=7, channel_style=False)
            rich.assert_not_awaited()
        assert bot.send_photo.await_count == 2
        for call in bot.send_photo.await_args_list:
            assert call.kwargs["caption"] == format_track_message(track)
            assert call.kwargs["photo"] == "original-cover"
            assert not call.kwargs.get("show_caption_above_media", False)
            assert (
                call.kwargs["reply_markup"].inline_keyboard[0][0].text
                == "🎧 Слушать трек"
            )
        bot.send_message.assert_not_awaited()

    async def test_missing_cover_keeps_complete_classic_card_and_buttons(self):
        track = sample(thumbnail_url=None)
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace()))
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}), bot=bot)
        service = PublicationService(context, channel_username="stonerhand")
        with (
            patch(
                "music_links_bot.rich_publications.rich_messages_enabled",
                return_value=True,
            ),
            patch(
                "music_links_bot.rich_publications.send_rich_publication",
                new=AsyncMock(),
            ) as rich,
        ):
            await service.deliver(
                {"item": asdict(track)}, target=7, channel_style=False
            )
            rich.assert_not_awaited()
        kwargs = bot.send_message.await_args.kwargs
        assert kwargs["text"] == format_track_message(track)
        assert kwargs["reply_markup"] is not None

    async def test_native_preview_keeps_long_intro_and_new_metadata_in_one_message(
        self,
    ):
        track = sample()
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace()))
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}), bot=bot)
        service = PublicationService(context, channel_username="stonerhand")
        intro = "Моя подводка. " * 110
        draft = {
            "item": asdict(track),
            "prefix": f"<blockquote>{intro}</blockquote>\n\n",
            "quote": True,
            "large_preview": True,
        }
        await service.deliver(draft, target=7, channel_style=False)
        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        assert intro in kwargs["text"]
        assert kwargs["text"].endswith(format_track_message(track))
        assert kwargs["link_preview_options"].show_above_text
