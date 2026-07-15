import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot import ephemeral


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Captures the outgoing request and returns a canned Telegram response."""

    posts: list[dict] = []
    reply = {"ok": True, "result": {"message_id": 5}}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        type(self).posts.append({"url": url, "json": json})
        return _FakeResponse(type(self).reply)


class EphemeralFlagTests(unittest.TestCase):
    def test_flag_reads_common_truthy_values(self) -> None:
        for value in ("1", "true", "YES", "on"):
            with patch.dict(os.environ, {"EPHEMERAL_GROUP_REPLIES": value}, clear=True):
                self.assertTrue(ephemeral.ephemeral_group_replies_enabled())
        with patch.dict(os.environ, {"EPHEMERAL_GROUP_REPLIES": "0"}, clear=True):
            self.assertFalse(ephemeral.ephemeral_group_replies_enabled())
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ephemeral.ephemeral_group_replies_enabled())


class SendEphemeralTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeClient.posts = []
        _FakeClient.reply = {"ok": True, "result": {"message_id": 5}}

    def test_builds_payload_and_reports_success(self) -> None:
        class Markup:
            def to_dict(self):
                return {"inline_keyboard": []}

        with patch.object(ephemeral.httpx, "AsyncClient", _FakeClient):
            ok = asyncio.run(
                ephemeral.send_ephemeral_message(
                    "token123",
                    -100500,
                    777,
                    "готовый пост",
                    parse_mode="HTML",
                    reply_markup=Markup(),
                    reply_to_message_id=42,
                )
            )

        self.assertTrue(ok)
        sent = _FakeClient.posts[0]
        self.assertIn("/bottoken123/sendMessage", sent["url"])
        body = sent["json"]
        self.assertEqual(body["receiver_user_id"], 777)
        self.assertEqual(body["chat_id"], -100500)
        self.assertEqual(body["parse_mode"], "HTML")
        self.assertEqual(body["reply_markup"], {"inline_keyboard": []})
        self.assertEqual(body["reply_parameters"], {"message_id": 42})

    def test_missing_token_or_receiver_short_circuits(self) -> None:
        with patch.object(ephemeral.httpx, "AsyncClient", _FakeClient):
            self.assertFalse(
                asyncio.run(ephemeral.send_ephemeral_message("", 1, 2, "x"))
            )
            self.assertFalse(
                asyncio.run(ephemeral.send_ephemeral_message("t", 1, None, "x"))
            )
        self.assertEqual(_FakeClient.posts, [])

    def test_telegram_error_reports_failure(self) -> None:
        _FakeClient.reply = {"ok": False, "description": "not supported"}
        with patch.object(ephemeral.httpx, "AsyncClient", _FakeClient):
            ok = asyncio.run(ephemeral.send_ephemeral_message("t", 1, 2, "x"))
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
