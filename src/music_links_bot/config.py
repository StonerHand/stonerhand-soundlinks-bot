from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    bot_token: str
    songlink_api_key: str | None
    songlink_user_countries: tuple[str, ...]
    log_level: str
    admin_chat_id: int | None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        bot_token = os.getenv("BOT_TOKEN", "").strip()
        if not bot_token:
            raise RuntimeError("BOT_TOKEN is not set. Add it to your .env file.")

        songlink_api_key = os.getenv("SONGLINK_API_KEY", "").strip() or None
        songlink_user_countries = _parse_user_countries()
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        admin_chat_id_raw = os.getenv("ADMIN_CHAT_ID", "").strip()
        admin_chat_id = int(admin_chat_id_raw) if admin_chat_id_raw else None

        return cls(
            bot_token=bot_token,
            songlink_api_key=songlink_api_key,
            songlink_user_countries=songlink_user_countries,
            log_level=log_level,
            admin_chat_id=admin_chat_id,
        )


def _parse_user_countries() -> tuple[str, ...]:
    raw_value = os.getenv("SONGLINK_USER_COUNTRIES", "").strip()
    if not raw_value:
        raw_value = os.getenv("SONGLINK_USER_COUNTRY", "US").strip()

    countries = tuple(
        country.strip().upper()
        for country in raw_value.split(",")
        if country.strip()
    )

    return countries or ("US",)
