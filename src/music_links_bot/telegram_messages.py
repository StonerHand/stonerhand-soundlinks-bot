from __future__ import annotations

from telegram import Message
from telegram.error import TelegramError


async def delete_message_safely(message: Message) -> bool:
    try:
        await message.delete()
    except TelegramError:
        return False
    return True
