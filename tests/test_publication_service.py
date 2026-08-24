import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from music_links_bot.publication_service import PublicationService


class PublicationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_uploaded_audio_uses_native_audio_delivery(self) -> None:
        bot = SimpleNamespace(send_audio=AsyncMock(return_value=SimpleNamespace()))
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={}),
            bot=bot,
        )
        service = PublicationService(context, channel_username="stonerhand")
        draft = {
            "item": {
                "artist": "Local artist",
                "title": "Demo",
                "links": {},
            },
            "source_audio_file_id": "telegram-audio",
            "source_audio_duration": 123,
        }

        result = await service.deliver(
            draft,
            target=7,
            channel_style=False,
        )

        self.assertIsNotNone(result)
        bot.send_audio.assert_awaited_once()
        kwargs = bot.send_audio.await_args.kwargs
        self.assertEqual(kwargs["audio"], "telegram-audio")
        self.assertEqual(kwargs["title"], "Demo")
        self.assertEqual(kwargs["performer"], "Local artist")
        self.assertEqual(kwargs["duration"], 123)

    async def test_custom_cover_is_sent_as_telegram_file_without_branding(self) -> None:
        sent = SimpleNamespace()
        bot = SimpleNamespace(send_photo=AsyncMock(return_value=sent))
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={}),
            bot=bot,
        )
        brand_enabled = Mock(return_value=True)
        build_brand = AsyncMock()
        service = PublicationService(
            context,
            channel_username="stonerhand",
            branding_hooks=(brand_enabled, build_brand, lambda _value: "", lambda: ""),
        )
        draft = {
            "item": {
                "artist": "Sleep",
                "title": "Dragonaut",
                "links": {"spotify": "https://open.spotify.com/track/abc"},
                "thumbnail_url": "https://img.example/cover.jpg",
            },
            "as_photo": True,
            "custom_cover_file_id": "telegram-cover",
        }

        result = await service.deliver(draft, target=7, channel_style=False)

        self.assertIs(result, sent)
        self.assertEqual(bot.send_photo.await_args.kwargs["photo"], "telegram-cover")
        brand_enabled.assert_not_called()
        build_brand.assert_not_awaited()

    async def test_missing_transport_result_is_not_reported_as_success(self) -> None:
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={}),
            bot=SimpleNamespace(),
        )
        service = PublicationService(context, channel_username="stonerhand")
        draft = {
            "item": {
                "artist": "Sleep",
                "title": "Dragonaut",
                "links": {},
            }
        }

        with patch.object(service, "_send", new=AsyncMock(return_value=None)):
            result = await service.deliver(
                draft,
                target=7,
                channel_style=False,
            )

        self.assertIsNone(result)

    async def test_false_transport_result_is_not_reported_as_success(self) -> None:
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={}),
            bot=SimpleNamespace(),
        )
        service = PublicationService(context, channel_username="stonerhand")
        draft = {"item": {"artist": "Sleep", "title": "Dragonaut", "links": {}}}

        with patch.object(service, "_send", new=AsyncMock(return_value=False)):
            result = await service.deliver(
                draft,
                target=7,
                channel_style=False,
            )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
