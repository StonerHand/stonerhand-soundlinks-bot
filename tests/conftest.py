"""Every test starts with Telegram capabilities (rich messages, link previews)
known to work: one test's simulated outage must not leak into the next.
No test downloads a real cover: a photo post asks for one in the background."""

from unittest.mock import AsyncMock, patch

import pytest

from music_links_bot.tg.telegram_gateway import reset_capabilities


@pytest.fixture(autouse=True)
def _fresh_telegram_capabilities():
    reset_capabilities()
    yield
    reset_capabilities()


@pytest.fixture(autouse=True)
def _no_real_cover_downloads():
    """Tests of the download itself call it directly or patch it again."""
    with patch(
        "music_links_bot.artwork.branding._fetch_bytes", AsyncMock(return_value=None)
    ):
        yield
