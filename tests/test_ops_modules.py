"""Owner diagnostics, admin alerts and Spotify artist cards."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from music_links_bot import alerts, bot_admin
from music_links_bot.artist import ArtistClient, ArtistLookupError

ARTIST_URL = "https://open.spotify.com/artist/4Z8W4fKeB5YxbusRsdQVPb"
METRICS = {
    "requests": 12,
    "request_ms_avg": 40,
    "cache_hits": 5,
    "cache_misses": 7,
    "publications": 3,
    "publication_errors": 1,
    "rich_messages": 2,
    "rich_message_fallbacks": 0,
    "funnel_started": 9,
    "funnel_resolved": 8,
    "funnel_edited": 4,
    "funnel_published": 3,
    "rate_limited": 0,
}
PROVIDER = {
    "provider": "songlink<x>",
    "ok": False,
    "circuit_open": False,
    "avg_latency_ms": 900,
    "success_rate_percent": 80,
    "requests": 10,
    "partials": 2,
    "timeouts": 1,
    "rate_limits": 0,
    "last_error": "ReadTimeout",
}


class _KV:
    def __init__(self, *, set_ok: bool = True) -> None:
        self.set_ok = set_ok

    async def set(self, key, value, *, ttl_seconds) -> bool:
        return self.set_ok

    async def get_json(self, key):
        return None

    async def ranked_events(self, key, *, limit):
        return []


def _context(**bot_data):
    webhook = SimpleNamespace(
        url="https://bot.example/api/telegram",
        pending_update_count=2,
        last_error_message=None,
    )
    runtime = SimpleNamespace(
        metrics_snapshot=lambda: dict(METRICS),
        provider_snapshot=lambda: [dict(PROVIDER)],
    )
    return SimpleNamespace(
        application=SimpleNamespace(
            bot_data={"runtime": runtime, "kv_store": _KV(), **bot_data}
        ),
        bot=SimpleNamespace(get_webhook_info=AsyncMock(return_value=webhook)),
    )


def _update(chat_id: int = 1, user_id: int = 1):
    message = SimpleNamespace(chat_id=chat_id, reply_text=AsyncMock())
    return SimpleNamespace(
        effective_message=message, effective_user=SimpleNamespace(id=user_id)
    )


class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_is_only_for_the_owner(self) -> None:
        update = _update(user_id=5)
        await bot_admin.status_command(update, _context(admin_chat_id=1))

        reply = update.effective_message.reply_text.await_args.args[0]
        self.assertIn("только владельцу", reply)

    async def test_status_summarises_every_subsystem_safely(self) -> None:
        jobs = [{"publish_at": 1}, {"publish_at": 9_999_999_999}]
        with patch.object(bot_admin, "load_jobs", new=AsyncMock(return_value=jobs)):
            text = await bot_admin.build_status_text(
                _context(last_error={"type": "<Boom>"})
            )

        self.assertIn("✅ <b>Telegram webhook</b> · очередь обновлений: 2", text)
        self.assertIn("✅ <b>Redis</b>", text)
        self.assertIn("⚠️ <b>Очередь</b> · 2 задач, просрочено: 1", text)
        self.assertIn("Запросы: <code>12</code>", text)
        self.assertIn("⚠️ songlink&lt;x&gt;", text)
        self.assertIn("<code>&lt;Boom&gt;</code>", text)

    async def test_status_shows_what_telegram_said_about_the_last_error(self) -> None:
        with patch.object(bot_admin, "load_jobs", new=AsyncMock(return_value=[])):
            text = await bot_admin.build_status_text(
                _context(
                    last_error={"type": "BadRequest", "detail": "Bad Request: <x>"}
                )
            )

        self.assertIn(
            "<code>BadRequest</code>\n<code>Bad Request: &lt;x&gt;</code>", text
        )

    async def test_status_reports_a_broken_queue_and_webhook(self) -> None:
        context = _context(kv_store=_KV(set_ok=False))
        context.bot.get_webhook_info.return_value.last_error_message = "Bad Gateway"
        with patch.object(
            bot_admin,
            "load_jobs",
            new=AsyncMock(side_effect=bot_admin.QueueStorageError("down")),
        ):
            text = await bot_admin.build_status_text(context)

        self.assertIn("⚠️ <b>Telegram webhook</b>", text)
        self.assertIn("ошибка: Bad Gateway", text)
        self.assertIn("⚠️ <b>Redis</b>", text)
        self.assertIn("Redis недоступен", text)

    async def test_private_stats_add_runtime_and_providers(self) -> None:
        text = await bot_admin.stats_text(_context(), include_private=True)

        self.assertIn("Воронка: 9 → 8 → 4 → 3", text)
        self.assertIn("⚠️ songlink<x>", text)
        self.assertIn("ReadTimeout", text)

    async def test_public_stats_hide_runtime_details(self) -> None:
        text = await bot_admin.stats_text(_context(), include_private=False)
        self.assertNotIn("Runtime", text)


ALERT_ENV = {"BOT_TOKEN": "t", "ADMIN_CHAT_ID": "1"}


class AlertTests(unittest.TestCase):
    def test_alerts_need_a_token_and_an_owner_chat(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("httpx.post") as post:
            self.assertFalse(alerts.send_admin_alert("down"))
        post.assert_not_called()

    def test_without_redis_every_alert_is_sent(self) -> None:
        response = MagicMock(json=MagicMock(return_value={"ok": True}))
        with (
            patch.dict(os.environ, ALERT_ENV, clear=True),
            patch("httpx.post", return_value=response) as post,
        ):
            self.assertTrue(alerts.send_admin_alert("x" * 5000))
        sent = post.call_args.kwargs["json"]["text"]
        self.assertTrue(sent.startswith("🚨 "))
        self.assertEqual(len(sent), 4000)

    def test_a_repeated_alert_is_suppressed_for_an_hour(self) -> None:
        env = {**ALERT_ENV, "KV_REST_API_URL": "https://kv", "KV_REST_API_TOKEN": "k"}
        taken = MagicMock(json=MagicMock(return_value={"result": None}))
        with (
            patch.dict(os.environ, env, clear=True),
            patch("httpx.post", return_value=taken) as post,
        ):
            self.assertFalse(alerts.send_admin_alert("down", dedup_key="queue"))
        self.assertEqual(post.call_count, 1)
        self.assertIn("NX", post.call_args.kwargs["json"])

    def test_a_failing_telegram_call_never_raises(self) -> None:
        with (
            patch.dict(os.environ, ALERT_ENV, clear=True),
            patch("httpx.post", side_effect=httpx.ConnectError("offline")),
        ):
            self.assertFalse(alerts.send_admin_alert("down"))


class ArtistClientTests(unittest.IsolatedAsyncioTestCase):
    async def _client(self, handler) -> ArtistClient:
        client = ArtistClient()
        await client.aclose()
        client._client = httpx.AsyncClient(
            base_url="https://open.spotify.com", transport=httpx.MockTransport(handler)
        )
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_artist_card_is_fetched_once_and_cached(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"title": "Kyuss"})

        client = await self._client(handler)
        first = await client.lookup_artist(ARTIST_URL)
        second = await client.lookup_artist(ARTIST_URL)

        self.assertEqual((first.title, first.platform), ("Kyuss", "Spotify"))
        self.assertIs(first, second)
        self.assertEqual(len(calls), 1)

    async def test_bad_urls_and_bad_answers_raise_a_lookup_error(self) -> None:
        client = await self._client(lambda request: httpx.Response(200, json=[1]))
        with self.assertRaises(ArtistLookupError):
            await client.lookup_artist("https://example.com/artist/1")
        with self.assertRaises(ArtistLookupError):
            await client.lookup_artist(ARTIST_URL)

        broken = await self._client(lambda request: httpx.Response(503))
        with self.assertRaises(ArtistLookupError):
            await broken.lookup_artist(ARTIST_URL)


if __name__ == "__main__":
    unittest.main()


class SoundCloudClientTests(unittest.IsolatedAsyncioTestCase):
    URL = "https://soundcloud.com/stoner-hand/ethan-kath-dj-set"

    async def _client(self, handler):
        from music_links_bot.soundcloud import SoundCloudClient

        client = SoundCloudClient()
        await client.aclose()
        client._client = httpx.AsyncClient(
            base_url="https://soundcloud.com", transport=httpx.MockTransport(handler)
        )
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_oembed_card_is_split_and_cached(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                200,
                json={
                    "title": "Ethan Kath DJ set by StonerHand",
                    "author_name": "StonerHand",
                    "thumbnail_url": "https://i1.sndcdn.com/artworks-1.jpg",
                },
            )

        client = await self._client(handler)
        track = await client.lookup_track(self.URL)
        again = await client.lookup_track(self.URL)

        self.assertIs(track, again)
        self.assertEqual(
            (track.artist, track.title), ("StonerHand", "Ethan Kath DJ set")
        )
        self.assertEqual(track.links, {"soundcloud": self.URL})
        self.assertEqual(len(calls), 1)

    async def test_bad_answers_and_foreign_links_are_lookup_errors(self) -> None:
        from music_links_bot.soundcloud import SoundCloudLookupError

        broken = await self._client(lambda request: httpx.Response(500))
        for url in ("https://example.com/track", self.URL):
            with self.subTest(url=url), self.assertRaises(SoundCloudLookupError):
                await broken.lookup_track(url)

    def test_titles_without_an_author_are_guessed_both_ways(self) -> None:
        from music_links_bot.soundcloud import parse_soundcloud_metadata

        by = parse_soundcloud_metadata(self.URL, {"title": "Song by Band"})
        dash = parse_soundcloud_metadata(self.URL, {"title": "Band - Song"})

        self.assertEqual((by.artist, by.title), ("Band", "Song"))
        self.assertEqual((dash.artist, dash.title), ("Band", "Song"))
        self.assertIsNone(by.thumbnail_url)
