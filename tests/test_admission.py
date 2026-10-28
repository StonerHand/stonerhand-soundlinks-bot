"""Admission runs its independent Redis calls together, yet a newer link still
cancels the lookup that is still running for the same person."""

import asyncio
from unittest.mock import patch

from music_links_bot.models import VideoMatch

FIRST = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
SECOND = "https://www.youtube.com/watch?v=bbbbbbbbbbb"


class _SlowFirstVideo:
    async def lookup_video(self, url):
        if url == FIRST:
            await asyncio.Event().wait()  # never answers
        return VideoMatch(title="Second video", author="A", url=url)


async def _both():
    from test_bot import ContextStub, PrivateMessageStub, UpdateStub

    from music_links_bot.bot_lookup_flow import track_lookup_message

    class First(PrivateMessageStub):
        text = FIRST

    class Second(PrivateMessageStub):
        text = SECOND

    context = ContextStub(youtube_client=_SlowFirstVideo())
    first, second = First(), Second()
    with patch("music_links_bot.bot_stats.record_post"):
        running = asyncio.create_task(track_lookup_message(UpdateStub(first), context))
        await asyncio.sleep(0.05)
        await track_lookup_message(UpdateStub(second), context)
        # The first lookup was cancelled, not left waiting forever.
        await asyncio.wait_for(running, timeout=2)
    return first, second, context


def test_a_newer_link_cancels_the_lookup_still_running():
    first, second, context = asyncio.run(_both())

    assert any("Second video" in reply for reply in second.replies)
    assert not any("Second video" in reply for reply in first.replies)
    assert context.application.bot_data["runtime"].active_tasks == {}
