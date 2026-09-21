"""Queue lifecycle for the standalone polling entry point."""

import asyncio
import logging
from types import SimpleNamespace

from music_links_bot.bot_app import sync_application_commands
from music_links_bot.publish_queue import process_due_jobs

LOGGER = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 30


async def run_queue(application):
    context = SimpleNamespace(application=application, bot=application.bot)
    while True:
        try:
            await asyncio.wait_for(process_due_jobs(context), timeout=20)
        except Exception:
            LOGGER.exception("Polling queue tick failed; will retry")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def start_polling_services(application):
    await sync_application_commands(application)
    application.bot_data["polling_queue_task"] = asyncio.create_task(
        run_queue(application)
    )


async def stop_polling_services(application):
    task = application.bot_data.pop("polling_queue_task", None)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
