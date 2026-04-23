import os
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.config import Settings


class ConfigTests(unittest.TestCase):
    def test_from_env_parses_admin_chat_id(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BOT_TOKEN": "token",
                "SONGLINK_USER_COUNTRIES": "us, de",
                "ADMIN_CHAT_ID": "12345",
            },
            clear=False,
        ):
            settings = Settings.from_env()

        self.assertEqual(settings.bot_token, "token")
        self.assertEqual(settings.songlink_user_countries, ("US", "DE"))
        self.assertEqual(settings.admin_chat_id, 12345)

    def test_from_env_ignores_invalid_admin_chat_id(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BOT_TOKEN": "token",
                "ADMIN_CHAT_ID": "not-a-number",
            },
            clear=False,
        ):
            settings = Settings.from_env()

        self.assertIsNone(settings.admin_chat_id)


if __name__ == "__main__":
    unittest.main()
