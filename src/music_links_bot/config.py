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
    primary_platform: str | None
    ui_mode: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        bot_token = os.getenv("BOT_TOKEN", "").strip()
        if not bot_token:
            raise RuntimeError("BOT_TOKEN is not set. Add it to environment variables.")

        songlink_api_key = os.getenv("SONGLINK_API_KEY", "").strip() or None
        songlink_user_countries = _parse_user_countries()
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        admin_chat_id = _parse_optional_int("ADMIN_CHAT_ID")

        return cls(
            bot_token=bot_token,
            songlink_api_key=songlink_api_key,
            songlink_user_countries=songlink_user_countries,
            log_level=log_level,
            admin_chat_id=admin_chat_id,
            primary_platform=_parse_primary_platform(),
            ui_mode=_parse_ui_mode(),
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


def _parse_optional_int(env_name: str) -> int | None:
    raw_value = os.getenv(env_name, "").strip()
    if not raw_value:
        return None

    try:
        return int(raw_value)
    except ValueError:
        return None


def _parse_primary_platform() -> str | None:
    raw_value = os.getenv("PRIMARY_PLATFORM", "").strip()
    return raw_value or None


def _parse_ui_mode() -> str:
    raw_value = os.getenv("BOT_UI_MODE", "stonerhand").strip().casefold()
    return raw_value if raw_value in {"stonerhand", "minimal", "editorial"} else "stonerhand"
