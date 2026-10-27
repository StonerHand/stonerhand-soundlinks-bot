"""A YouTube card always arrives: without its preview if Telegram refuses the
preview, and a broken lookup says so instead of freezing the progress line."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from telegram import LinkPreviewOptions
from telegram.error import BadRequest, TimedOut

from music_links_bot.lookup_transport import _send_card

VIDEO = "https://www.youtube.com/watch?v=j7K6FC_psGc"
STILL = "https://i.ytimg.com/vi/j7K6FC_psGc/hqdefault.jpg"
PREVIEW = LinkPreviewOptions(is_disabled=False, url=VIDEO, prefer_large_media=True)


def test_a_refused_preview_still_delivers_the_card_bare():
    send = AsyncMock(side_effect=[BadRequest("Wrong web page url"), "sent"])

    assert (
        asyncio.run(_send_card(send, link_preview_options=PREVIEW, text="card"))
        == "sent"
    )
    first, second = send.await_args_list
    assert first.kwargs["link_preview_options"] is PREVIEW
    assert second.kwargs["link_preview_options"].is_disabled
    assert second.kwargs["text"] == "card"


def test_a_slow_player_gets_more_time_then_the_still_image():
    send = AsyncMock(side_effect=[TimedOut(), "sent"])

    sent = asyncio.run(
        _send_card(
            send, link_preview_options=PREVIEW, fallback_preview_url=STILL, text="c"
        )
    )

    assert sent == "sent"
    player, still = send.await_args_list
    # Telegram builds the player before answering: longer than the 5 s default.
    assert player.kwargs["read_timeout"] > 5
    assert player.kwargs["link_preview_options"].url == VIDEO
    assert still.kwargs["link_preview_options"].url == STILL
    assert still.kwargs["link_preview_options"].prefer_large_media


def test_when_no_preview_works_the_card_still_goes_out():
    send = AsyncMock(side_effect=[TimedOut(), BadRequest("Wrong file"), "sent"])

    sent = asyncio.run(
        _send_card(
            send, link_preview_options=PREVIEW, fallback_preview_url=STILL, text="c"
        )
    )

    assert sent == "sent"
    assert send.await_args_list[-1].kwargs["link_preview_options"].is_disabled
    assert "read_timeout" not in send.await_args_list[-1].kwargs


def test_a_card_refused_without_preview_is_a_real_error():
    bare = LinkPreviewOptions(is_disabled=True)
    send = AsyncMock(side_effect=BadRequest("Message is too long"))
    with pytest.raises(BadRequest):
        asyncio.run(_send_card(send, link_preview_options=bare, text="card"))
    assert send.await_count == 1

    # The bare retry failing too means the preview was not the problem.
    send = AsyncMock(side_effect=BadRequest("Can't parse entities"))
    with pytest.raises(BadRequest):
        asyncio.run(_send_card(send, link_preview_options=PREVIEW, text="card"))
    assert send.await_count == 2


def _lookup(message, context):
    from test_bot import UpdateStub

    from music_links_bot.bot_lookup_flow import track_lookup_message

    with patch("music_links_bot.bot_stats.record_matches"):
        asyncio.run(track_lookup_message(UpdateStub(message), context))


def test_a_youtube_card_arrives_even_when_telegram_refuses_its_player():
    from test_bot import ContextStub, PrivateMessageStub

    from music_links_bot.models import VideoMatch

    class Message(PrivateMessageStub):
        text = f"Вышел из спячки {VIDEO}"

        async def reply_text(self, text, **kwargs):
            options = kwargs.get("link_preview_options")
            if options is not None and options.url == VIDEO:
                raise BadRequest("Wrong web page url")
            return await super().reply_text(text, **kwargs)

    youtube = AsyncMock()
    youtube.lookup_video.return_value = VideoMatch(
        title="Dead Man's Bones – Lost In The Night (Official Video)",
        author="Dead Man's Bones",
        url=VIDEO,
        thumbnail_url=STILL,
    )
    message = Message()
    # Telegram refuses the progress edit with the player as well.
    message.reply_edit_error = BadRequest("Wrong web page url")
    _lookup(message, ContextStub(youtube_client=youtube))

    live = [reply for reply in message.replies if reply != "<deleted>"]
    assert len(live) == 1
    assert "Lost In The Night" in message.replies[-1]
    # The video's own still replaces the player.
    assert message.reply_kwargs[-1]["link_preview_options"].url == STILL


def test_a_broken_lookup_says_so_and_offers_retry():
    from test_bot import ContextStub, PrivateMessageStub

    class Message(PrivateMessageStub):
        text = VIDEO

    message = Message()
    with (
        patch(
            "music_links_bot.bot_lookup_flow._deliver_lookup_bundle",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        pytest.raises(RuntimeError),
    ):
        _lookup(message, ContextStub())

    assert message.replies[-1].startswith("<b>⚠️ Не получилось собрать пост</b>")
    buttons = [
        button.callback_data
        for row in message.reply_kwargs[-1]["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "v2|retry|last" in buttons
