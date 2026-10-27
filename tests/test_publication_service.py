import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from telegram.error import BadRequest

from music_links_bot.draft_model import prepare_publication_draft
from music_links_bot.models import TrackMatch
from music_links_bot.publication_service import PublicationService


class PublicationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_cover_publication_uses_branded_photo_without_details(self):
        bot = SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace()))
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}), bot=bot)
        brand = AsyncMock(return_value=b"branded-cover")
        service = PublicationService(
            context,
            channel_username="stonerhand",
            branding_hooks=(lambda: True, brand, lambda value: value, lambda: None),
        )
        draft = {
            "item": {
                "artist": "Castle Rat",
                "title": "SIREN",
                "kind": "song",
                "links": {"spotify": "https://open.spotify.com/track/abc"},
                "thumbnail_url": "https://img.example/cover.jpg",
            },
            "preset": "cover",
            "as_photo": False,
        }
        for target in (7, "@stonerhand"):
            with self.subTest(target=target):
                result = await service._send(
                    prepare_publication_draft(draft).data,
                    TrackMatch(**draft["item"]),
                    target=target,
                )
                self.assertIsNotNone(result)
                payload = bot.send_photo.await_args.kwargs
                self.assertEqual(payload["photo"], b"branded-cover")
                self.assertIn("SIREN", payload["caption"])
                self.assertTrue(
                    all(
                        button.url and not button.callback_data
                        for row in payload["reply_markup"].inline_keyboard
                        for button in row
                    )
                )
        self.assertEqual(brand.await_args.kwargs["label"], "@stonerhand")

    async def test_clean_preview_uses_delivery_pipeline_without_side_effects(
        self,
    ) -> None:
        runtime = SimpleNamespace(
            record_publication=Mock(),
            persist_metrics=AsyncMock(),
        )
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"runtime": runtime}),
            bot=SimpleNamespace(),
        )
        service = PublicationService(context, channel_username="stonerhand")
        draft = {
            "item": {
                "artist": "Sleep",
                "title": "Dragonaut",
                "kind": "song",
                "links": {"spotify": "https://open.spotify.com/track/abc"},
            },
            "delivery_mode": "classic",
        }
        sent = SimpleNamespace(message_id=77)

        with patch.object(service, "_send", new=AsyncMock(return_value=sent)) as send:
            result = await service.preview(draft, target=7)

        self.assertIs(result, sent)
        self.assertEqual(send.await_args.kwargs["target"], 7)
        self.assertFalse(send.await_args.kwargs["include_channel_button"])
        self.assertFalse(send.await_args.kwargs["record_metrics"])
        runtime.record_publication.assert_not_called()
        runtime.persist_metrics.assert_not_awaited()

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
        draft = {
            "item": {
                "artist": "Sleep",
                "title": "Dragonaut",
                "links": {"spotify": "https://open.spotify.com/track/abc"},
            }
        }

        with patch.object(service, "_send", new=AsyncMock(return_value=False)):
            result = await service.deliver(
                draft,
                target=7,
                channel_style=False,
            )

        self.assertIsNone(result)

    async def test_retry_safety_state_is_reset_for_every_delivery(self) -> None:
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={}),
            bot=SimpleNamespace(),
        )
        service = PublicationService(context, channel_username="stonerhand")
        draft = {
            "item": {
                "artist": "Sleep",
                "title": "Dragonaut",
                "links": {"spotify": "https://open.spotify.com/track/abc"},
            }
        }

        with patch.object(
            service,
            "_send",
            new=AsyncMock(side_effect=[SimpleNamespace(), BadRequest("rejected")]),
        ):
            first = await service.deliver(
                draft, target=7, channel_style=False, notify_failure=False
            )
            self.assertIsNotNone(first)
            self.assertFalse(service.confirmed_not_sent)

            second = await service.deliver(
                draft, target=7, channel_style=False, notify_failure=False
            )

        self.assertIsNone(second)
        self.assertTrue(service.confirmed_not_sent)

    async def test_channel_delivery_respects_hashtags_disabled_in_editor(self) -> None:
        sent = SimpleNamespace()
        bot = SimpleNamespace(send_message=AsyncMock(return_value=sent))
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={}),
            bot=bot,
        )
        service = PublicationService(context, channel_username="stonerhand")
        draft = {
            "item": {
                "artist": "Knocked Loose",
                "title": "Don't Reach For Me",
                "kind": "song",
                "links": {"spotify": "https://open.spotify.com/track/abc"},
            },
            "hashtags": False,
            "delivery_mode": "classic",
        }

        result = await service._send(
            draft,
            TrackMatch(**draft["item"]),
            target="@stonerhand",
        )

        self.assertIs(result, sent)
        text = bot.send_message.await_args.kwargs["text"]
        self.assertNotIn("#stonerhand", text)
        self.assertNotIn("#track", text)


if __name__ == "__main__":
    unittest.main()


class LongIntroTests(unittest.IsolatedAsyncioTestCase):
    """A long formatted note keeps every character and its formatting."""

    def _draft(self, note: str) -> dict:
        return {
            "item": {
                "artist": "Sleep",
                "title": "Dopesmoker",
                "kind": "song",
                "links": {"spotify": "https://open.spotify.com/track/abc"},
                "thumbnail_url": "https://img.example/cover.jpg",
            },
            "preset": "cover",
            "as_photo": True,
            "quote": True,
            "prefix": f"<blockquote>{note}</blockquote>\n\n",
        }

    async def _send(self, draft: dict):
        bot = SimpleNamespace(
            send_photo=AsyncMock(return_value=SimpleNamespace()),
            send_message=AsyncMock(return_value=SimpleNamespace()),
        )
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}), bot=bot)
        service = PublicationService(context, channel_username="stonerhand")
        await service._send(
            prepare_publication_draft(draft).data,
            TrackMatch(**draft["item"]),
            target=7,
        )
        return bot

    async def test_long_note_becomes_a_message_with_the_cover_above(self) -> None:
        note = "<b>Жирный</b> и <i>курсив</i> " + "слово " * 400
        bot = await self._send(self._draft(note))

        bot.send_photo.assert_not_awaited()
        payload = bot.send_message.await_args.kwargs
        self.assertIn("<b>Жирный</b> и <i>курсив</i>", payload["text"])
        self.assertIn("Dopesmoker", payload["text"])
        self.assertTrue(payload["link_preview_options"].show_above_text)

    async def test_short_note_stays_a_photo_post(self) -> None:
        bot = await self._send(self._draft("<b>Коротко</b>"))

        bot.send_message.assert_not_awaited()
        self.assertIn("<b>Коротко</b>", bot.send_photo.await_args.kwargs["caption"])
