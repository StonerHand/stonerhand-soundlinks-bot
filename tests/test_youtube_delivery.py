"""A YouTube card always arrives: it previews the video's frame (Telegram cannot
build a YouTube page preview in time), survives flood control, falls back to a
plainer preview, and a broken lookup says so instead of freezing the progress
line."""

import asyncio
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram import LinkPreviewOptions
from telegram.error import BadRequest, RetryAfter, TimedOut

from music_links_bot.lookup_transport import _send_card
from music_links_bot.models import VideoMatch
from music_links_bot.youtube import video_frame_url, video_preview_url, video_still_url

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


def test_a_slow_preview_edit_is_repeated_with_the_still_image():
    send = AsyncMock(side_effect=[TimedOut(), "sent"])

    sent = asyncio.run(
        _send_card(
            send,
            link_preview_options=PREVIEW,
            fallback_preview_url=STILL,
            idempotent=True,
            text="c",
        )
    )

    assert sent == "sent"
    player, still = send.await_args_list
    assert player.kwargs["read_timeout"] > 5
    assert player.kwargs["link_preview_options"].url == VIDEO
    assert still.kwargs["link_preview_options"].url == STILL
    assert still.kwargs["link_preview_options"].prefer_large_media


def test_a_new_message_is_never_sent_twice_after_a_timeout():
    """It may already be in the chat: a second send would be a duplicate."""
    send = AsyncMock(side_effect=[TimedOut(), "sent"])

    with pytest.raises(TimedOut):
        asyncio.run(
            _send_card(
                send, link_preview_options=PREVIEW, fallback_preview_url=STILL, text="c"
            )
        )

    assert send.await_count == 1
    # Telegram gets longer for a send, since it cannot be repeated.
    assert send.await_args.kwargs["read_timeout"] >= 12


def test_when_no_preview_works_the_card_still_goes_out():
    send = AsyncMock(side_effect=[TimedOut(), BadRequest("Wrong file"), "sent"])

    sent = asyncio.run(
        _send_card(
            send,
            link_preview_options=PREVIEW,
            fallback_preview_url=STILL,
            idempotent=True,
            text="c",
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

    with patch("music_links_bot.bot_stats.record_post"):
        asyncio.run(track_lookup_message(UpdateStub(message), context))


def test_video_cards_try_the_player_first_and_pause_it_after_a_failure():
    from music_links_bot.telegram_gateway import (
        link_preview_capability,
        record_capability_failure,
    )

    video = VideoMatch(title="Clip", author="A", url=VIDEO, thumbnail_url=STILL)
    # YouTube's own preview: title, description and the inline player.
    assert video_preview_url(video) == VIDEO
    # Telegram could not build it: the next cards use the frame for a while.
    record_capability_failure(
        link_preview_capability(VIDEO), TimedOut(), unsupported=True
    )
    assert video_preview_url(video) == STILL
    # One switch turns the player off for good.
    with patch.dict(os.environ, {"YOUTUBE_PLAYER_PREVIEW_ENABLED": "0"}):
        from music_links_bot.telegram_gateway import reset_capabilities

        reset_capabilities()
        assert video_preview_url(video) == STILL


def test_every_youtube_host_shares_one_player_state():
    from music_links_bot.telegram_gateway import link_preview_capability

    keys = {
        link_preview_capability(url)
        for url in (
            VIDEO,
            "https://youtu.be/j7K6FC_psGc",
            "https://m.youtube.com/watch?v=j7K6FC_psGc",
            "https://music.youtube.com/watch?v=j7K6FC_psGc",
        )
    }
    assert keys == {"link_preview:youtube.com"}


def test_the_frame_comes_from_the_video_id_when_youtube_sent_no_still():
    bare = VideoMatch(title="YouTube video", author="YouTube", url=VIDEO)
    assert video_still_url(bare) == STILL
    assert video_frame_url(bare) == STILL
    unknown = VideoMatch(
        title="x", author="y", url="https://www.youtube.com/watch?v=bad"
    )
    assert video_frame_url(unknown) == unknown.url


def test_a_player_telegram_refuses_falls_back_to_the_frame():
    from test_bot import ContextStub, PrivateMessageStub

    from music_links_bot.telegram_gateway import (
        capability_available,
        link_preview_capability,
    )

    class Message(PrivateMessageStub):
        text = f"Вышел из спячки {VIDEO}"

        async def reply_text(self, text, **kwargs):
            options = kwargs.get("link_preview_options")
            if options is not None and options.url == VIDEO:
                raise BadRequest("Wrong web page url")  # refused: nothing sent
            return await super().reply_text(text, **kwargs)

    youtube = AsyncMock()
    youtube.lookup_video.return_value = VideoMatch(
        title="Dead Man's Bones – Lost In The Night (Official Video)",
        author="Dead Man's Bones",
        url=VIDEO,
        thumbnail_url=STILL,
    )
    message = Message()
    # The progress line cannot be edited into the card here.
    message.reply_edit_error = BadRequest("Message can't be edited")
    _lookup(message, ContextStub(youtube_client=youtube))

    live = [reply for reply in message.replies if reply != "<deleted>"]
    assert len(live) == 1
    assert "Lost In The Night" in message.replies[-1]
    options = message.reply_kwargs[-1]["link_preview_options"]
    assert options.url == STILL and options.prefer_large_media
    buttons = [
        button.url
        for row in message.reply_kwargs[-1]["reply_markup"].inline_keyboard
        for button in row
        if button.url
    ]
    assert VIDEO in buttons
    # The next YouTube cards skip the player for a while.
    assert not capability_available(link_preview_capability(VIDEO))


def test_a_progress_line_stuck_on_the_player_becomes_the_frame_card_in_place():
    """A timed-out edit may already be the card: the same message is edited
    again with the still. Nothing is deleted and no second card appears."""
    from test_bot import ContextStub, PrivateMessageStub

    from music_links_bot.telegram_gateway import (
        capability_available,
        link_preview_capability,
    )

    class ProgressLine:
        def __init__(self, owner, index):
            self.chat_id, self.message_id = owner.chat_id, 1000 + index
            self.owner, self.index = owner, index

        async def edit_text(self, text, **kwargs):
            options = kwargs.get("link_preview_options")
            if options is not None and options.url == VIDEO:
                raise TimedOut()  # Telegram is stuck building the player
            self.owner.replies[self.index] = text
            self.owner.reply_kwargs[self.index] = kwargs
            return self

        async def delete(self):
            raise AssertionError("the progress line must not be deleted")

    class Message(PrivateMessageStub):
        text = VIDEO

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)
            self.reply_kwargs.append(kwargs)
            return ProgressLine(self, len(self.replies) - 1)

    youtube = AsyncMock()
    youtube.lookup_video.return_value = VideoMatch(
        title="Danzig - Mother 93 Live", author="Danzig", url=VIDEO, thumbnail_url=STILL
    )
    message = Message()
    # A slow lookup: the progress line is shown at once.
    with patch("music_links_bot.bot_lookup_flow.PROGRESS_DELAY_SECONDS", 0):
        _lookup(message, ContextStub(youtube_client=youtube))

    assert len(message.replies) == 1  # the progress line, now the card
    assert "Mother 93 Live" in message.replies[0]
    assert message.reply_kwargs[0]["link_preview_options"].url == STILL
    assert not capability_available(link_preview_capability(VIDEO))


def test_an_edit_that_already_landed_counts_as_the_card():
    from music_links_bot.lookup_transport import reply_with_track

    progress = SimpleNamespace(
        edit_text=AsyncMock(side_effect=BadRequest("Message is not modified"))
    )
    message = SimpleNamespace(chat_id=7, reply_text=AsyncMock())
    with patch("music_links_bot.lookup_transport.take_progress", return_value=progress):
        sent = asyncio.run(
            reply_with_track(
                message,
                "<b>Card</b>",
                preview_url=None,
                reply_markup=None,
                content_kind="video",
                source_urls=(VIDEO,),
            )
        )

    assert sent is progress
    message.reply_text.assert_not_awaited()


def test_short_flood_control_is_waited_out_once():
    send = AsyncMock(side_effect=[RetryAfter(timedelta(seconds=3)), "sent"])
    with patch(
        "music_links_bot.lookup_transport.asyncio.sleep", new=AsyncMock()
    ) as sleep:
        sent = asyncio.run(_send_card(send, link_preview_options=PREVIEW, text="c"))

    assert sent == "sent"
    sleep.assert_awaited_once_with(3.0)
    assert send.await_count == 2


def test_long_flood_control_is_not_waited_out():
    send = AsyncMock(side_effect=RetryAfter(timedelta(seconds=60)))
    with pytest.raises(RetryAfter):
        asyncio.run(_send_card(send, link_preview_options=PREVIEW, text="c"))
    assert send.await_count == 1


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
