import hashlib
import hmac
import json
import os
import time
import unittest
from pathlib import Path
import sys
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.bot import _webapp_url
from music_links_bot.webapp_auth import validate_init_data

BOT_TOKEN = "12345:test-token"


def _sign_init_data(params: dict[str, str]) -> str:
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(params.items())
    )
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    params = dict(params)
    params["hash"] = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(params)


class WebAppAuthTests(unittest.TestCase):
    def _valid_params(self) -> dict[str, str]:
        return {
            "auth_date": str(int(time.time())),
            "query_id": "AAE1",
            "user": json.dumps({"id": 42, "language_code": "ru"}),
        }

    def test_valid_init_data_returns_user(self) -> None:
        init_data = _sign_init_data(self._valid_params())

        user = validate_init_data(init_data, BOT_TOKEN)

        self.assertIsNotNone(user)
        self.assertEqual(user["id"], 42)

    def test_tampered_init_data_is_rejected(self) -> None:
        params = self._valid_params()
        init_data = _sign_init_data(params)
        tampered = init_data.replace("%22id%22%3A+42", "%22id%22%3A+43")

        self.assertIsNone(validate_init_data(tampered, BOT_TOKEN))

    def test_wrong_token_is_rejected(self) -> None:
        init_data = _sign_init_data(self._valid_params())

        self.assertIsNone(validate_init_data(init_data, "999:other-token"))

    def test_stale_auth_date_is_rejected(self) -> None:
        params = self._valid_params()
        params["auth_date"] = str(int(time.time()) - 100_000)
        init_data = _sign_init_data(params)

        self.assertIsNone(validate_init_data(init_data, BOT_TOKEN))

    def test_missing_hash_is_rejected(self) -> None:
        params = self._valid_params()

        self.assertIsNone(validate_init_data(urlencode(params), BOT_TOKEN))


class WebAppUrlTests(unittest.TestCase):
    def test_explicit_env_wins(self) -> None:
        with patch.dict(
            os.environ,
            {"WEBAPP_URL": "https://studio.example/app"},
            clear=True,
        ):
            self.assertEqual(_webapp_url(), "https://studio.example/app")

    def test_falls_back_to_vercel_production_domain(self) -> None:
        with patch.dict(
            os.environ,
            {"VERCEL_PROJECT_PRODUCTION_URL": "tg-bot-sh.vercel.app"},
            clear=True,
        ):
            self.assertEqual(_webapp_url(), "https://tg-bot-sh.vercel.app/app")

    def test_returns_none_without_configuration(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(_webapp_url())


if __name__ == "__main__":
    unittest.main()


class StudioApiHelperTests(unittest.TestCase):
    def test_apply_draft_patch_normalizes_everything(self) -> None:
        from api.webapp import _apply_draft_patch

        draft = {"hashtags": False, "quote": False, "large_preview": True}
        _apply_draft_patch(
            draft,
            {
                "hashtags": True,
                "cta": "  жми   сюда  ",
                "tags": ["#Doom", "stoner rock", "!!!"],
                "platforms": ["tidal", "bogus", "spotify"],
            },
        )

        self.assertTrue(draft["hashtags"])
        self.assertEqual(draft["custom_cta"], "жми сюда")
        self.assertEqual(draft["custom_tags"], ["#doom", "#stonerrock"])
        self.assertEqual(draft["platforms"], ["tidal", "spotify"])

    def test_apply_draft_patch_resets_customization(self) -> None:
        from api.webapp import _apply_draft_patch

        draft = {
            "custom_cta": "x",
            "custom_tags": ["#x"],
            "platforms": ["spotify"],
        }
        _apply_draft_patch(draft, {"cta": None, "tags": None, "platforms": []})

        self.assertNotIn("custom_cta", draft)
        self.assertNotIn("custom_tags", draft)
        self.assertNotIn("platforms", draft)

    def test_apply_draft_patch_keeps_explicit_empty_tags(self) -> None:
        from api.webapp import _apply_draft_patch

        draft = {}
        _apply_draft_patch(draft, {"tags": []})

        self.assertEqual(draft["custom_tags"], [])

    def test_upscale_artwork(self) -> None:
        from api.webapp import _upscale_artwork

        self.assertEqual(
            _upscale_artwork("https://img.example/a/100x100bb.jpg"),
            "https://img.example/a/300x300bb.jpg",
        )
        self.assertIsNone(_upscale_artwork(None))

    def test_top_entries_sorted_and_limited(self) -> None:
        from api.webapp import _top_entries

        entries = _top_entries(
            {
                "1": {"label": "a", "count": 2},
                "2": {"label": "b", "count": 9},
                "3": {"label": "c", "count": 5},
            },
            limit=2,
        )

        self.assertEqual(entries, [{"label": "b", "count": 9}, {"label": "c", "count": 5}])
        self.assertEqual(_top_entries("junk"), [])
