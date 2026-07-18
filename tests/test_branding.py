import io
import os
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.branding import (
    brand_label,
    compose_cover,
    photo_branding_enabled,
)


def _png_bytes(color=(80, 60, 90), size=(300, 300)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class BrandingTests(unittest.TestCase):
    def test_toggle_and_label_from_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(photo_branding_enabled())
            self.assertEqual(brand_label("@stonerhand"), "@stonerhand")
        with patch.dict(os.environ, {"BRAND_PHOTO_FRAME": "1", "BRAND_LABEL": "My Channel"}):
            self.assertTrue(photo_branding_enabled())
            self.assertEqual(brand_label("@stonerhand"), "My Channel")

    def test_compose_cover_returns_square_jpeg(self) -> None:
        from PIL import Image

        out = compose_cover(_png_bytes(size=(400, 300)), label="@stonerhand", size=512)
        self.assertIsNotNone(out)
        img = Image.open(io.BytesIO(out))
        self.assertEqual(img.format, "JPEG")
        self.assertEqual(img.size, (512, 512))

    def test_compose_cover_with_logo(self) -> None:
        out = compose_cover(
            _png_bytes(), label="стонерхенд", logo_bytes=_png_bytes((255, 120, 0), (64, 64)), size=512
        )
        self.assertIsNotNone(out)

    def test_compose_cover_bad_bytes_returns_none(self) -> None:
        self.assertIsNone(compose_cover(b"not an image", label="x"))


class BrandingPublishTests(unittest.TestCase):
    def test_publish_draft_uses_branded_bytes_when_enabled(self) -> None:
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from music_links_bot import bot

        class _Bot:
            def __init__(self):
                self.photos = []

            async def send_photo(self, **kwargs):
                self.photos.append(kwargs)
                return SimpleNamespace(message_id=1)

        bot_stub = _Bot()
        application = SimpleNamespace(bot_data={}, bot=bot_stub)
        context = SimpleNamespace(application=application, bot=bot_stub)
        draft = {
            "type": "track",
            "item": {
                "artist": "Sleep",
                "title": "Dopesmoker",
                "links": {"spotify": "https://open.spotify.com/x"},
                "page_url": "https://song.link/x",
                "thumbnail_url": "https://img.example/a.jpg",
            },
            "chat_id": 7,
            "as_photo": True,
            "hashtags": True,
        }

        with patch.object(bot, "photo_branding_enabled", return_value=True), patch.object(
            bot, "build_branded_cover", new=AsyncMock(return_value=b"BRANDEDJPEG")
        ):
            asyncio.run(bot._publish_draft(context, draft))

        self.assertEqual(len(bot_stub.photos), 1)
        self.assertEqual(bot_stub.photos[0]["photo"], b"BRANDEDJPEG")


if __name__ == "__main__":
    unittest.main()
