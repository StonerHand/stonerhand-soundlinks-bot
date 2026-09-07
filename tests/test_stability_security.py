from __future__ import annotations

import asyncio
import io
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from PIL import Image
from telegram.error import BadRequest, NetworkError

from api.queue_worker import is_authorized
from api.set_webhook import _is_authorized
from api.telegram import _is_telegram_request_authorized
from music_links_bot.bot import (
    EditorActionRequest,
    _handle_editor_action,
    _run_locked_editor_action,
)
from music_links_bot.bot_pending import consume_pending_input
from music_links_bot.bot_queue import dispatch_queue_action, render_queue
from music_links_bot.bot_runtime import BotRuntime, CallbackAction
from music_links_bot.branding import _fetch_bytes, build_branded_cover, compose_cover
from music_links_bot.chat_access import check_publish_access
from music_links_bot.collection_collage import decode_collage_payload
from music_links_bot.draft_model import new_track_draft
from music_links_bot.models import TrackMatch
from music_links_bot.webhook_secret import secrets_match


def _draft():
    return new_track_draft(
        TrackMatch(
            artist="Sleep",
            title="Dragonaut",
            links={
                "spotify": "https://open.spotify.com/track/abc",
            },
        ),
        chat_id=7,
        lang="ru",
    )


def _context(**data):
    return SimpleNamespace(application=SimpleNamespace(bot_data=data))


def _query():
    return SimpleNamespace(
        from_user=SimpleNamespace(id=7, language_code="ru"),
        message=SimpleNamespace(chat_id=7),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )


class CredentialSafetyTests(unittest.TestCase):
    def test_malformed_credentials_are_rejected_without_crashing(self):
        env = {
            "BOT_TOKEN": "test",
            "TELEGRAM_WEBHOOK_SECRET": "secret",
            "SET_WEBHOOK_SECRET": "secret",
            "CRON_SECRET": "secret",
        }
        with patch.dict(os.environ, env, clear=True):
            for value in ("☃", "секрет", "\ud800", "", None):
                with self.subTest(value=value):
                    self.assertFalse(secrets_match(value, "secret"))
                    self.assertFalse(_is_telegram_request_authorized(value))
                    self.assertFalse(is_authorized(value))
            self.assertFalse(_is_authorized("/api/set_webhook?secret=%E2%98%83", None))
            self.assertTrue(_is_authorized("/api/set_webhook?secret=secret", None))
            self.assertTrue(is_authorized("Bearer secret"))
            self.assertTrue(_is_telegram_request_authorized("secret"))

    def test_missing_setup_secret_never_authenticates_empty_query(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(_is_authorized("/api/set_webhook", None))

    def test_unicode_collage_signature_is_an_invalid_request(self):
        self.assertIsNone(decode_collage_payload("W10", "☃", signing_secret="secret"))


class BrandingSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_limit_stops_before_reading_the_entire_response(self):
        class Stream(httpx.AsyncByteStream):
            read = 0
            closed = False

            async def __aiter__(self):
                for _ in range(100):
                    self.read += 1
                    yield b"x" * 65_536

            async def aclose(self):
                self.closed = True

        stream = Stream()
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "image/jpeg"},
                stream=stream,
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with patch("music_links_bot.branding.MAX_BRANDING_BYTES", 100_000):
                result = await _fetch_bytes(client, "https://images.example/cover")
        self.assertIsNone(result)
        self.assertLessEqual(stream.read, 2)
        self.assertTrue(stream.closed)

    async def test_invalid_or_redirected_assets_are_not_downloaded(self):
        for status, headers in (
            (302, {"location": "http://127.0.0.1/private"}),
            (200, {"content-type": "text/html"}),
            (200, {"content-type": "image/jpeg", "content-length": "invalid"}),
        ):
            with self.subTest(status=status, headers=headers):
                calls = []

                def response(request, calls=calls, status=status, headers=headers):
                    calls.append(str(request.url))
                    return httpx.Response(status, headers=headers, content=b"x")

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(response)
                ) as client:
                    self.assertIsNone(
                        await _fetch_bytes(client, "https://images.example/a")
                    )
                self.assertEqual(len(calls), 1)

    async def test_slow_assets_are_cancelled_within_the_total_budget(self):
        finished = []

        async def slow_fetch(*_args):
            try:
                await asyncio.Event().wait()
            finally:
                finished.append(True)

        with (
            patch("music_links_bot.branding._fetch_bytes", side_effect=slow_fetch),
            patch("music_links_bot.branding.BRANDING_FETCH_SECONDS", 0.01),
        ):
            self.assertIsNone(
                await build_branded_cover("https://images.example/a", label="test")
            )
        self.assertEqual(len(finished), 2)

    async def test_valid_image_response_is_preserved(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, headers={"content-type": "image/png"}, content=b"image"
                )
            )
        ) as client:
            self.assertEqual(
                await _fetch_bytes(client, "https://images.example/a"), b"image"
            )

    def test_huge_image_is_rejected_before_decoding(self):
        source = Mock(width=4000, height=4000)
        manager = Mock(
            __enter__=Mock(return_value=source), __exit__=Mock(return_value=False)
        )
        with patch("PIL.Image.open", return_value=manager):
            self.assertIsNone(compose_cover(b"image", label="test"))
        source.thumbnail.assert_not_called()
        source.convert.assert_not_called()

    def test_bad_logo_keeps_valid_cover_and_invalid_sizes_are_rejected(self):
        buffer = io.BytesIO()
        with Image.new("RGB", (100, 100), (30, 40, 50)) as image:
            image.save(buffer, "PNG")
        result = compose_cover(
            buffer.getvalue(), label="test", logo_bytes=b"invalid", size=64
        )
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(image.size, (64, 64))
        for size in (0, -1, 1201):
            self.assertIsNone(compose_cover(buffer.getvalue(), label="test", size=size))


class EditorSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_draft_rejects_every_action_except_restore(self):
        draft = _draft()
        draft["deleted_at"] = int(time.time())
        context = _context(drafts={"d1": draft})
        for action in ("b", "z0", "s", "pc", "pv", "qi"):
            query = _query()
            await _handle_editor_action(query, context, action, "d1")
            self.assertTrue(query.answer.await_args.kwargs["show_alert"])
            query.edit_message_text.assert_not_awaited()
        with patch(
            "music_links_bot.bot._handle_editor_lifecycle", AsyncMock(return_value=True)
        ) as restore:
            await _handle_editor_action(_query(), context, "du", "d1")
        restore.assert_awaited_once()

    async def test_ownerless_callback_cannot_edit_a_draft(self):
        context = _context(drafts={"d1": _draft()})
        query = _query()
        query.from_user = None
        await _handle_editor_action(query, context, "z0", "d1")
        query.edit_message_text.assert_not_awaited()
        self.assertTrue(query.answer.await_args.kwargs["show_alert"])

    async def test_deleted_draft_rejects_a_reply_to_an_old_input_prompt(self):
        draft = _draft()
        draft["deleted_at"] = int(time.time())
        runtime = BotRuntime()
        session = await runtime.get_session(7)
        session.pending_input = {
            "kind": "intro",
            "draft_id": "d1",
            "created_at": int(time.time()),
        }
        context = _context(drafts={"d1": draft}, runtime=runtime)
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            chat_id=7,
            text="new intro",
            caption=None,
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=7, language_code="ru"),
        )
        self.assertTrue(
            await consume_pending_input(update, context, retry_lookup=AsyncMock())
        )
        self.assertEqual(session.pending_input, {})
        self.assertEqual(context.application.bot_data["drafts"]["d1"]["prefix"], "")

    async def test_publish_and_replace_cannot_run_at_the_same_time(self):
        context = _context(runtime=BotRuntime())
        entered = asyncio.Event()
        release = asyncio.Event()

        async def send(request):
            entered.set()
            await release.wait()

        requests = [
            EditorActionRequest(
                _query(),
                context,
                action,
                "d1",
                _draft(),
                "ru",
                TrackMatch(**_draft()["item"]),
            )
            for action in ("pc", "x")
        ]
        with (
            patch("music_links_bot.bot._show_action_busy", AsyncMock()),
            patch(
                "music_links_bot.bot._run_primary_editor_action",
                AsyncMock(side_effect=send),
            ) as sender,
        ):
            first = asyncio.create_task(_run_locked_editor_action(requests[0]))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                await _run_locked_editor_action(requests[1])
                self.assertEqual(sender.await_count, 1)
            finally:
                release.set()
                await first

    async def test_cancelled_busy_indicator_releases_the_action_lock(self):
        runtime = BotRuntime()
        request = EditorActionRequest(
            _query(),
            _context(runtime=runtime),
            "pc",
            "d1",
            _draft(),
            "ru",
            TrackMatch(**_draft()["item"]),
        )
        with patch(
            "music_links_bot.bot._show_action_busy",
            AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await _run_locked_editor_action(request)
        self.assertIsNotNone(await runtime.acquire_action("7:publish:d1"))

    async def test_expired_owner_cannot_release_a_new_action_lock(self):
        runtime = BotRuntime()
        with patch("music_links_bot.bot_runtime.monotonic", return_value=100):
            old = await runtime.acquire_action("publish")
        with patch("music_links_bot.bot_runtime.monotonic", return_value=1000):
            new = await runtime.acquire_action("publish")
            self.assertIsNotNone(new)
            await runtime.release_action("publish", old)
            self.assertIsNone(await runtime.acquire_action("publish"))
            await runtime.release_action("publish", new)
            self.assertIsNotNone(await runtime.acquire_action("publish"))

    async def test_full_lock_table_does_not_evict_an_active_publication(self):
        runtime = BotRuntime()
        with patch("music_links_bot.bot_runtime.MAX_MEMORY_KEYS", 1):
            token = await runtime.acquire_action("first")
            self.assertIsNone(await runtime.acquire_action("second"))
            self.assertIsNone(await runtime.acquire_action("first"))
            await runtime.release_action("first", token)
            self.assertIsNotNone(await runtime.acquire_action("second"))

    async def test_permission_lookup_recovers_immediately_after_network_error(self):
        context = _context()
        context.bot = SimpleNamespace(
            id=7,
            get_chat_member=AsyncMock(
                side_effect=[
                    NetworkError("temporary"),
                    SimpleNamespace(status="administrator", can_post_messages=True),
                ]
            ),
        )
        self.assertFalse((await check_publish_access(context, "@channel")).allowed)
        self.assertTrue((await check_publish_access(context, "@channel")).allowed)
        self.assertTrue((await check_publish_access(context, "@channel")).allowed)
        self.assertEqual(context.bot.get_chat_member.await_count, 2)


class QueueInteractionTests(unittest.IsolatedAsyncioTestCase):
    def context(self, status="uncertain"):
        return _context(
            admin_chat_id=7,
            publish_queue=[
                {
                    "id": "job1",
                    "status": status,
                    "publish_at": 1800000000,
                    "draft": _draft(),
                }
            ],
        )

    async def test_retry_requires_confirmation_and_is_not_repeatable(self):
        context = self.context()
        query = _query()
        await dispatch_queue_action(
            query, context, CallbackAction("queue", "retry", "0:job1")
        )
        self.assertEqual(
            context.application.bot_data["publish_queue"][0]["status"], "uncertain"
        )
        self.assertIn(
            "Сначала проверь канал", query.edit_message_text.await_args.kwargs["text"]
        )
        await dispatch_queue_action(
            query, context, CallbackAction("queue", "retry_confirm", "0:job1")
        )
        self.assertEqual(
            context.application.bot_data["publish_queue"][0]["status"], "pending"
        )
        with patch("music_links_bot.bot_queue.time.time", return_value=42):
            await dispatch_queue_action(
                query, context, CallbackAction("queue", "retry_confirm", "0:job1")
            )
        self.assertNotEqual(
            context.application.bot_data["publish_queue"][0]["publish_at"], 42
        )

    async def test_cancel_only_removes_job_after_confirmation(self):
        context = self.context("pending")
        query = _query()
        await dispatch_queue_action(
            query, context, CallbackAction("queue", "cancel", "0:job1")
        )
        self.assertEqual(len(context.application.bot_data["publish_queue"]), 1)
        await dispatch_queue_action(
            query, context, CallbackAction("queue", "cancel_confirm", "0:job1")
        )
        self.assertEqual(context.application.bot_data["publish_queue"], [])

    async def test_non_admin_cannot_confirm_a_queue_action(self):
        context = self.context()
        query = _query()
        query.from_user.id = 8
        await dispatch_queue_action(
            query, context, CallbackAction("queue", "retry_confirm", "0:job1")
        )
        self.assertEqual(
            context.application.bot_data["publish_queue"][0]["status"], "uncertain"
        )
        query.edit_message_text.assert_not_awaited()

    async def test_active_delivery_is_shown_without_cancel_button(self):
        for status in ("processing", "delivering"):
            text, keyboard = await render_queue(self.context(status), lang="ru")
            self.assertIn("Отправляется", text)
            self.assertFalse(
                any(
                    "cancel" in (button.callback_data or "")
                    for row in keyboard.inline_keyboard
                    for button in row
                )
            )

    async def test_middle_queue_page_has_at_most_two_buttons_per_row(self):
        context = self.context()
        job = context.application.bot_data["publish_queue"][0]
        context.application.bot_data["publish_queue"] = [
            dict(job, id=f"job{i}") for i in range(24)
        ]
        for lang in ("ru", "en"):
            _, keyboard = await render_queue(context, lang=lang, page=1)
            self.assertTrue(all(len(row) <= 2 for row in keyboard.inline_keyboard))

    async def test_refresh_of_unchanged_queue_is_not_an_error(self):
        query = _query()
        query.edit_message_text.side_effect = BadRequest("Message is not modified")
        await dispatch_queue_action(
            query, self.context(), CallbackAction("queue", "open")
        )
        query.edit_message_text.side_effect = BadRequest("Message cannot be edited")
        with self.assertRaises(BadRequest):
            await dispatch_queue_action(
                query, self.context(), CallbackAction("queue", "open")
            )
