"""A result faster than a second shows no progress line; a slow one shows it
and turns it into the card; a line sent as the result lands removes itself."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from music_links_bot.core.models import VideoMatch
from music_links_bot.lookup.bot_progress import (
    settle_progress,
    start_progress,
    take_progress,
)

VIDEO = "https://www.youtube.com/watch?v=E3mSkI9uskw"


class _Video:
    def __init__(self, wait: float) -> None:
        self.wait = wait

    async def lookup_video(self, url):
        await asyncio.sleep(self.wait)
        return VideoMatch(title="iOS 27.2", author="ProTech", url=url)


def _lookup(wait: float, delay: float = 0.05):
    from test_bot import ContextStub, PrivateMessageStub, UpdateStub

    from music_links_bot.lookup.bot_lookup_flow import track_lookup_message

    class Message(PrivateMessageStub):
        text = VIDEO

    message = Message()
    with (
        patch("music_links_bot.lookup.bot_lookup_flow.PROGRESS_DELAY_SECONDS", delay),
        patch("music_links_bot.lookup.bot_stats.record_post"),
    ):
        asyncio.run(
            track_lookup_message(
                UpdateStub(message), ContextStub(youtube_client=_Video(wait))
            )
        )
    return message


def test_a_fast_result_shows_no_progress_line_at_all():
    message = _lookup(wait=0)

    assert len(message.replies) == 1
    assert "iOS 27.2" in message.replies[0]
    assert not any("🔎" in reply for reply in message.replies)


def test_a_slow_result_shows_progress_and_turns_it_into_the_card():
    message = _lookup(wait=0.3)

    # One message: the progress line, edited into the card.
    assert len(message.replies) == 1
    assert "iOS 27.2" in message.replies[0]


def _incoming(sent):
    return SimpleNamespace(
        chat_id=7,
        message_id=11,
        chat=SimpleNamespace(type="private"),
        reply_text=AsyncMock(side_effect=sent),
    )


def test_a_line_sent_as_the_result_lands_removes_itself():
    async def scenario():
        landed = SimpleNamespace(delete=AsyncMock())
        sending = asyncio.Event()

        async def slow_send(*_args, **_kwargs):
            sending.set()
            await asyncio.sleep(0.05)
            return landed

        message = _incoming(slow_send)
        await start_progress(message, delay=0.01, key="progress_links")
        await sending.wait()
        # The result is ready while the line is on its way.
        assert take_progress(7) is None
        await asyncio.sleep(0.1)
        return message, landed

    message, landed = asyncio.run(scenario())

    message.reply_text.assert_awaited_once()
    landed.delete.assert_awaited_once()


def test_a_request_that_ends_never_shows_its_waiting_line():
    async def scenario():
        message = _incoming([SimpleNamespace(delete=AsyncMock())])
        await start_progress(message, delay=0.05, key="progress_links")
        settle_progress()
        await asyncio.sleep(0.1)
        return message

    message = asyncio.run(scenario())

    message.reply_text.assert_not_awaited()
