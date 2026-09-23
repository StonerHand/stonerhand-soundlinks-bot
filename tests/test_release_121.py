from __future__ import annotations

import asyncio
from dataclasses import asdict
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx

from music_links_bot import branding
from music_links_bot.bot_queue import render_queue
from music_links_bot.collection_plan import build_collection_plan, collection_issues
from music_links_bot.models import TrackMatch
from music_links_bot.operation_metrics import latency_summary, record_duration
from music_links_bot.provider_errors import provider_failure_reason
from music_links_bot.public_release import (
    PublicReleaseError,
    PublicReleaseRegionUnavailable,
)
from music_links_bot.publication_service import PublicationService
from music_links_bot.shared_http import close_shared_clients, shared_client


def track():
    return TrackMatch(
        artist="Sleep",
        title="Dopesmoker",
        links={"spotify": "https://open.spotify.com/track/1"},
        thumbnail_url="https://i.scdn.co/image/1",
    )


class Release121AsyncTests(IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await close_shared_clients()

    async def test_cover_singleflight_cache_and_style_invalidation(self):
        with patch.object(
            branding, "_build_branded_cover", new=AsyncMock(return_value=b"jpeg")
        ) as build:
            results = await asyncio.gather(
                *(
                    branding.build_branded_cover(track().thumbnail_url, label="A")
                    for _ in range(4)
                )
            )
            self.assertEqual(results, [b"jpeg"] * 4)
            build.assert_awaited_once()
            await branding.build_branded_cover(track().thumbnail_url, label="A")
            build.assert_awaited_once()
            await branding.build_branded_cover(track().thumbnail_url, label="B")
            await branding.build_branded_cover(
                track().thumbnail_url,
                label="B",
                logo_url="https://example.com/logo.png",
            )
            self.assertEqual(build.await_count, 3)

    async def test_failed_cover_is_not_cached(self):
        with patch.object(
            branding, "_build_branded_cover", new=AsyncMock(side_effect=[None, b"jpeg"])
        ) as build:
            self.assertIsNone(
                await branding.build_branded_cover(track().thumbnail_url, label="A")
            )
            self.assertEqual(
                await branding.build_branded_cover(track().thumbnail_url, label="A"),
                b"jpeg",
            )
            self.assertEqual(build.await_count, 2)

    async def test_cancelled_waiter_does_not_cancel_shared_cover(self):
        started, finish = asyncio.Event(), asyncio.Event()

        async def compose(*args, **kwargs):
            started.set()
            await finish.wait()
            return b"jpeg"

        with patch.object(branding, "_build_branded_cover", side_effect=compose):
            first = asyncio.create_task(
                branding.build_branded_cover(track().thumbnail_url, label="A")
            )
            await started.wait()
            second = asyncio.create_task(
                branding.build_branded_cover(track().thumbnail_url, label="A")
            )
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            finish.set()
            self.assertEqual(await second, b"jpeg")

    async def test_branded_photo_reuses_telegram_file_and_keeps_plain_fallback_separate(
        self,
    ):
        photo = SimpleNamespace(photo=[SimpleNamespace(file_id="branded-file")])
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={}),
            bot=SimpleNamespace(send_photo=AsyncMock(return_value=photo)),
        )
        builder = AsyncMock(return_value=b"branded")
        service = PublicationService(
            context,
            channel_username="stonerhand",
            branding_hooks=(
                lambda: True,
                builder,
                lambda default: default,
                lambda: None,
            ),
        )
        for _ in range(2):
            await service._send_photo(
                {},
                track(),
                target=1,
                cover=track().thumbnail_url,
                text="Post",
                keyboard=None,
            )
        builder.assert_awaited_once()
        self.assertEqual(
            context.bot.send_photo.await_args.kwargs["photo"], "branded-file"
        )
        context.application.bot_data.clear()
        builder.return_value = None
        for _ in range(2):
            await service._send_photo(
                {},
                track(),
                target=1,
                cover=track().thumbnail_url,
                text="Post",
                keyboard=None,
            )
        self.assertEqual(builder.await_count, 3)

    async def test_photo_file_cache_expires_in_memory(self):
        from music_links_bot.telegram_media_cache import (
            get_cached_file_id,
            remember_photo_file_id,
            MEDIA_CACHE_TTL_SECONDS,
        )

        context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
        photo = SimpleNamespace(photo=[SimpleNamespace(file_id="file")])
        with patch(
            "music_links_bot.telegram_media_cache.time.monotonic", return_value=100
        ):
            await remember_photo_file_id(context, "cover", photo)
            self.assertEqual(await get_cached_file_id(context, "cover"), "file")
        with patch(
            "music_links_bot.telegram_media_cache.time.monotonic",
            return_value=101 + MEDIA_CACHE_TTL_SECONDS,
        ):
            self.assertIsNone(await get_cached_file_id(context, "cover"))

    async def test_http_pool_reuses_connections_and_closes_on_shutdown(self):
        client = shared_client("branding")
        self.assertIs(client, shared_client("branding"))
        self.assertIsNot(client, shared_client("telegram"))
        await close_shared_clients()
        self.assertTrue(client.is_closed)
        self.assertIsNot(client, shared_client("branding"))

    async def test_queue_explains_delay_and_uncertainty_without_silent_retry(self):
        job = {
            "id": "abc",
            "publish_at": 2000,
            "scheduled_for": 1000,
            "status": "uncertain",
            "attempts": 1,
            "last_failure": "delivery_unknown",
            "draft": {"item": asdict(track())},
        }
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
        with (
            patch(
                "music_links_bot.bot_queue.load_jobs", new=AsyncMock(return_value=[job])
            ),
            patch("music_links_bot.bot_queue.time.time", return_value=2200),
        ):
            text, keyboard = await render_queue(context, lang="ru")
        self.assertIn("20 мин", text)
        self.assertIn("проверь канал", text)
        self.assertIn("1", text)
        self.assertTrue(
            any(
                "retry" in (b.callback_data or "")
                for row in keyboard.inline_keyboard
                for b in row
            )
        )


def test_collection_preflight_identifies_positions_without_mutation():
    first = asdict(track())
    broken = {"title": "", "artist": "A", "links": {}}
    items = [{"item": first}, {"item": dict(first)}, {"item": broken}]
    issues = collection_issues(items)
    assert any(i.index == 2 and i.code == "duplicate" for i in issues)
    assert any(i.index == 3 and i.code == "metadata" and i.blocking for i in issues)
    assert len(items) == 3


def test_collection_plan_keeps_order_intro_and_escapes_titles():
    tracks = [
        track(),
        TrackMatch(
            artist="B",
            title="<second>",
            links={"spotify": "https://open.spotify.com/track/2"},
        ),
    ]
    with patch(
        "music_links_bot.collection_plan.collection_collage_preview_url",
        return_value="https://example.com/collage",
    ):
        plan = build_collection_plan(tracks, title="Collection", intro_html="My intro")
    assert "My intro" in plan.text and "&lt;second&gt;" in plan.text
    assert plan.source_urls == tuple(t.links["spotify"] for t in tracks)
    assert plan.preview_url == "https://example.com/collage"


def test_provider_reasons_follow_cause_without_leaking_errors():
    for cause, expected in [
        (PublicReleaseRegionUnavailable("region"), "region_unavailable"),
        (
            PublicReleaseError("Incomplete release title or artist"),
            "metadata_incomplete",
        ),
        (httpx.ConnectTimeout("secret URL"), "timeout"),
    ]:
        wrapper = RuntimeError("upstream wrapper")
        wrapper.__cause__ = cause
        assert provider_failure_reason(wrapper) == expected
    for status, expected in [(404, "release_not_found"), (429, "rate_limited")]:
        response = httpx.Response(
            status, request=httpx.Request("GET", "https://example.com")
        )
        assert (
            provider_failure_reason(
                httpx.HTTPStatusError(
                    "error", request=response.request, response=response
                )
            )
            == expected
        )


def test_metrics_bound_samples_and_report_tail_latency():
    data = {}
    for value in range(1000):
        record_duration(data, "lookup", value)
    metrics = latency_summary(data)["lookup"]
    assert metrics == {"samples": 200, "p50_ms": 899, "p95_ms": 989}
