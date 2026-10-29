"""Every test starts with Telegram capabilities (rich messages, link previews)
known to work: one test's simulated outage must not leak into the next."""

import pytest

from music_links_bot.tg.telegram_gateway import reset_capabilities


@pytest.fixture(autouse=True)
def _fresh_telegram_capabilities():
    reset_capabilities()
    yield
    reset_capabilities()
