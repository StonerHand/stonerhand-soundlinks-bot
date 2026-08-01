import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from music_links_bot.publication_service import PublicationService


class PublicationServiceTests(unittest.IsolatedAsyncioTestCase):
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
