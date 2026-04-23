from __future__ import annotations

import asyncio
import logging

from music_links_bot.bot import build_application
from music_links_bot.config import Settings


def main() -> None:
    # Python 3.14 no longer creates a default event loop for the main thread.
    asyncio.set_event_loop(asyncio.new_event_loop())

    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    application = build_application(settings)
    application.run_polling(allowed_updates=["message", "channel_post"])


if __name__ == "__main__":
    main()
