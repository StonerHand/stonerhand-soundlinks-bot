from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import MessageEntity

from music_links_bot import bot_lookup
from music_links_bot.bot import _send_track_matches
from music_links_bot.bot_lookup import (
    LookupBundle,
    SourceStatus,
    _send_youtube_result,
)
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.bot_stats import message_source_urls
from music_links_bot.models import TrackMatch


class _UnusedSoundCloud:
    async def lookup_track(self, _source_url: str) -> TrackMatch:
        raise AssertionError("SoundCloud fallback is not expected")


class BatchIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_ten_sources_can_all_start_within_provider_budget(self) -> None:
        urls = [
            f"https://open.spotify.com/track/capacity-{index}" for index in range(10)
        ]

        class Client:
            async def lookup_track(self, source_url: str) -> TrackMatch:
                await asyncio.sleep(0.01)
                return TrackMatch(
                    title=source_url.rsplit("/", 1)[-1],
                    artist="Artist",
                    links={"spotify": source_url},
                )

        with (
            patch.object(bot_lookup, "_BATCH_ITEM_TIMEOUT_SECONDS", 0.03),
            patch.object(bot_lookup, "_BATCH_PROVIDER_WORK_SECONDS", 0.07),
            patch.object(bot_lookup, "_BATCH_LOOKUP_START_INTERVAL_SECONDS", 0),
        ):
            bundle = await bot_lookup.resolve_sources(
                {
                    "songlink_client": Client(),
                    "soundcloud_client": _UnusedSoundCloud(),
                },
                urls,
            )

        self.assertEqual(bundle.item_count, 10)
        self.assertTrue(bundle.is_complete_for(urls))

    async def test_one_slow_source_does_not_cancel_completed_siblings(self) -> None:
        urls = [
            f"https://open.spotify.com/track/integrity-{index}" for index in range(10)
        ]

        class Client:
            async def lookup_track(self, source_url: str) -> TrackMatch:
                if source_url == urls[-1]:
                    await asyncio.sleep(1)
                return TrackMatch(
                    title=source_url.rsplit("/", 1)[-1],
                    artist="Artist",
                    links={"spotify": source_url},
                )

        bot_data = {
            "songlink_client": Client(),
            "soundcloud_client": _UnusedSoundCloud(),
        }
        with (
            patch.object(bot_lookup, "_BATCH_ITEM_TIMEOUT_SECONDS", 0.02),
            patch.object(bot_lookup, "_BATCH_LOOKUP_START_INTERVAL_SECONDS", 0),
        ):
            bundle = await bot_lookup.resolve_sources(bot_data, urls)

        self.assertEqual(bundle.item_count, 9)
        self.assertEqual(len(bundle.statuses), len(urls))
        self.assertEqual(
            [status.source_url for status in bundle.statuses],
            urls,
        )
        self.assertEqual(bundle.successful_source_count, 9)
        self.assertEqual(bundle.statuses[-1].state, "unavailable")
        self.assertTrue(bundle.statuses[-1].retryable)
        self.assertFalse(bundle.is_complete_for(urls))

    async def test_slow_first_sources_do_not_starve_fast_followers(self) -> None:
        urls = [f"https://open.spotify.com/track/head-{index}" for index in range(10)]

        class Client:
            async def lookup_track(self, source_url: str) -> TrackMatch:
                if source_url in urls[:2]:
                    await asyncio.sleep(1)
                return TrackMatch(
                    title=source_url.rsplit("/", 1)[-1],
                    artist="Artist",
                    links={"spotify": source_url},
                )

        with (
            patch.object(bot_lookup, "_BATCH_LOOKUP_CONCURRENCY", 2),
            patch.object(bot_lookup, "_BATCH_ITEM_TIMEOUT_SECONDS", 0.02),
            patch.object(bot_lookup, "_BATCH_LOOKUP_START_INTERVAL_SECONDS", 0),
        ):
            bundle = await bot_lookup.resolve_sources(
                {
                    "songlink_client": Client(),
                    "soundcloud_client": _UnusedSoundCloud(),
                },
                urls,
            )

        self.assertEqual(bundle.item_count, 8)
        self.assertEqual(
            [status.state for status in bundle.statuses],
            ["unavailable", "unavailable", *("success" for _ in range(8))],
        )

    async def test_open_songlink_circuit_still_allows_spotify_fallback_path(
        self,
    ) -> None:
        url = "https://open.spotify.com/track/circuit-fallback"

        class Client:
            calls = 0

            async def lookup_track(self, source_url: str) -> TrackMatch:
                self.calls += 1
                return TrackMatch(
                    title="Recovered",
                    artist="Artist",
                    links={"spotify": source_url},
                )

        runtime = BotRuntime()
        for _ in range(3):
            runtime.record_provider(
                "songlink",
                ok=False,
                latency_ms=1,
                error=TimeoutError(),
            )
        client = Client()
        bundle = await bot_lookup.resolve_sources(
            {
                "runtime": runtime,
                "songlink_client": client,
                "soundcloud_client": _UnusedSoundCloud(),
            },
            [url],
        )

        self.assertEqual(client.calls, 1)
        self.assertTrue(bundle.is_complete_for([url]))
        self.assertEqual(bundle.tracks[0].title, "Recovered")

    def test_accounting_repairs_a_missing_provider_status(self) -> None:
        urls = [
            "https://open.spotify.com/track/accounted-a",
            "https://open.spotify.com/track/accounted-b",
        ]
        bundle = LookupBundle(
            tracks=[
                TrackMatch(
                    title="A",
                    artist="Artist",
                    links={"spotify": urls[0]},
                )
            ],
            unavailable_urls=[],
            videos=[],
            radios=[],
            playlists=[],
            artists=[],
            statuses=[SourceStatus(urls[0], "songlink", "success")],
        )

        repaired = bot_lookup._ensure_source_accounting(bundle, urls)

        self.assertEqual(len(repaired.statuses), 2)
        self.assertEqual(repaired.statuses[1].state, "unavailable")
        self.assertTrue(repaired.statuses[1].retryable)
        self.assertEqual(repaired.unavailable_urls, [urls[1]])
        self.assertFalse(repaired.is_complete_for(urls))

    async def test_duplicate_tracking_variants_are_resolved_once(self) -> None:
        first = "https://open.spotify.com/track/duplicate?si=first"
        second = "https://open.spotify.com/track/duplicate?si=second"

        class Client:
            calls = 0

            async def lookup_track(self, source_url: str) -> TrackMatch:
                self.calls += 1
                return TrackMatch(
                    title="Duplicate",
                    artist="Artist",
                    links={"spotify": source_url},
                )

        client = Client()
        bundle = await bot_lookup.resolve_sources(
            {
                "songlink_client": client,
                "soundcloud_client": _UnusedSoundCloud(),
            },
            [first, second],
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(bundle.item_count, 1)
        self.assertEqual(len(bundle.statuses), 1)
        self.assertTrue(bundle.is_complete_for([first]))

    async def test_invalid_cached_partial_bundle_is_rebuilt(self) -> None:
        urls = [
            "https://open.spotify.com/track/cache-a",
            "https://open.spotify.com/track/cache-b",
        ]
        partial_payload = {
            "tracks": [
                {
                    "title": "Cached A",
                    "artist": "Artist",
                    "links": {"spotify": urls[0]},
                }
            ],
            "statuses": [
                {
                    "source_url": urls[0],
                    "provider": "songlink",
                    "state": "success",
                }
            ],
        }

        class Client:
            calls = 0

            async def lookup_track(self, source_url: str) -> TrackMatch:
                self.calls += 1
                return TrackMatch(
                    title=source_url.rsplit("/", 1)[-1],
                    artist="Fresh",
                    links={"spotify": source_url},
                )

        client = Client()
        with patch.object(
            bot_lookup,
            "get_cached_lookup",
            new=AsyncMock(return_value=partial_payload),
        ):
            bundle = await bot_lookup.resolve_sources(
                {
                    "songlink_client": client,
                    "soundcloud_client": _UnusedSoundCloud(),
                },
                urls,
            )

        self.assertEqual(client.calls, 2)
        self.assertEqual(bundle.item_count, 2)
        self.assertTrue(bundle.is_complete_for(urls))

    async def test_partial_public_collection_has_no_incomplete_share_action(
        self,
    ) -> None:
        tracks = [
            TrackMatch(
                title=f"Track {index}",
                artist="Artist",
                links={"spotify": f"https://open.spotify.com/track/share-{index}"},
            )
            for index in range(2)
        ]
        message = SimpleNamespace(
            chat=SimpleNamespace(type="group", title="Group", username=None, id=-100),
            chat_id=-100,
            from_user=None,
        )
        context = SimpleNamespace(
            bot=object(), application=SimpleNamespace(bot_data={})
        )

        with patch("music_links_bot.bot._send_track_result", new=AsyncMock()) as sender:
            await _send_track_matches(
                message,
                context,
                tracks,
                is_private=False,
                user_id=7,
                user_prefix="",
                lang="ru",
                include_channel_button=False,
                include_hashtags=True,
                requested_count=3,
                allow_share=False,
            )

        keyboard = sender.await_args.kwargs["reply_markup"]
        self.assertFalse(
            any(
                button.switch_inline_query
                for row in keyboard.inline_keyboard
                for button in row
            )
        )

    async def test_one_of_many_tracks_stays_a_partial_collection(self) -> None:
        track = TrackMatch(
            title="Only result",
            artist="Artist",
            links={"spotify": "https://open.spotify.com/track/only"},
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(type="group", title="Group", username=None, id=-100),
            chat_id=-100,
            from_user=None,
        )
        context = SimpleNamespace(
            bot=object(), application=SimpleNamespace(bot_data={})
        )

        with patch("music_links_bot.bot._send_track_result", new=AsyncMock()) as sender:
            await _send_track_matches(
                message,
                context,
                [track],
                is_private=False,
                user_id=7,
                user_prefix="",
                lang="ru",
                include_channel_button=False,
                include_hashtags=True,
                requested_count=4,
                allow_share=False,
            )

        text = sender.await_args.args[2]
        keyboard = sender.await_args.kwargs["reply_markup"]
        self.assertIn("⚠️ Подборка · 1 из 4", text)
        self.assertFalse(
            any(
                button.switch_inline_query
                for row in keyboard.inline_keyboard
                for button in row
            )
        )

    async def test_one_of_many_videos_stays_a_partial_collection(self) -> None:
        video = bot_lookup.VideoMatch(
            title="Only video",
            author="Channel",
            url="https://youtu.be/only-video",
        )
        message = SimpleNamespace(chat_id=-100)

        with patch.object(bot_lookup, "_send_track_result", new=AsyncMock()) as sender:
            await _send_youtube_result(
                object(),
                message,
                [video],
                user_prefix="",
                include_channel_button=False,
                include_hashtags=True,
                lang="ru",
                requested_count=3,
                allow_share=False,
            )

        text = sender.await_args.args[2]
        keyboard = sender.await_args.kwargs["reply_markup"]
        self.assertIn("⚠️ Подборка · 1 из 3", text)
        self.assertFalse(
            any(
                button.switch_inline_query
                for row in keyboard.inline_keyboard
                for button in row
            )
        )


class TelegramEntitySourceTests(unittest.TestCase):
    def test_hidden_text_links_are_processed_in_message_order(self) -> None:
        text = "Первый затем https://open.spotify.com/track/visible"
        hidden_url = "https://open.spotify.com/track/hidden"
        message = SimpleNamespace(
            text=text,
            caption=None,
            entities=(
                MessageEntity(
                    MessageEntity.TEXT_LINK,
                    offset=0,
                    length=6,
                    url=hidden_url,
                ),
            ),
        )

        self.assertEqual(
            message_source_urls(message),
            [hidden_url, "https://open.spotify.com/track/visible"],
        )

    def test_hidden_tracking_variant_does_not_duplicate_visible_source(self) -> None:
        visible = "https://open.spotify.com/track/same?si=visible"
        message = SimpleNamespace(
            text=visible,
            caption=None,
            entities=(
                MessageEntity(
                    MessageEntity.TEXT_LINK,
                    offset=0,
                    length=5,
                    url="https://open.spotify.com/track/same?si=hidden",
                ),
            ),
        )

        self.assertEqual(message_source_urls(message), [visible])


if __name__ == "__main__":
    unittest.main()
