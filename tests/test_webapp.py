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


class _CrateBotStub:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.photos: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)

    async def send_photo(self, **kwargs):
        self.photos.append(kwargs)


def _crate_context():
    from types import SimpleNamespace

    application = SimpleNamespace(bot_data={"drafts": {}}, bot=_CrateBotStub())
    return SimpleNamespace(application=application, bot=application.bot)


def _crate_track(title: str) -> dict:
    return {
        "artist": "Sleep",
        "title": title,
        "links": {"spotify": f"https://open.spotify.com/track/{title}"},
        "page_url": f"https://song.link/{title}",
        "kind": "song",
        "thumbnail_url": "https://img.example/a.jpg",
    }


class CrateApiTests(unittest.TestCase):
    def _add(self, context, title: str) -> dict:
        import asyncio
        from api.webapp import _action_crate_add

        draft_id = f"d-{title}"
        context.application.bot_data["drafts"][draft_id] = {
            "type": "track",
            "item": _crate_track(title),
            "chat_id": 7,
        }
        return asyncio.run(_action_crate_add(context, {"draft_id": draft_id}, 7))

    def test_crate_add_dedupes_and_lists(self) -> None:
        context = _crate_context()

        first = self._add(context, "Dopesmoker")
        again = self._add(context, "Dopesmoker")
        second = self._add(context, "Dragonaut")

        self.assertEqual(first["count"], 1)
        self.assertEqual(again["count"], 1)
        self.assertEqual(second["count"], 2)
        self.assertEqual(second["items"][1]["title"], "Dragonaut")

    def test_crate_reorder_and_remove(self) -> None:
        import asyncio
        from api.webapp import _action_crate_order, _action_crate_remove

        context = _crate_context()
        self._add(context, "One")
        self._add(context, "Two")

        reordered = asyncio.run(_action_crate_order(context, {"indices": [1, 0]}, 7))
        self.assertEqual(reordered["items"][0]["title"], "Two")

        bad = asyncio.run(_action_crate_order(context, {"indices": [0, 0]}, 7))
        self.assertFalse(bad["ok"])

        removed = asyncio.run(_action_crate_remove(context, {"index": 0}, 7))
        self.assertEqual(removed["count"], 1)
        self.assertEqual(removed["items"][0]["title"], "One")

    def test_crate_deliver_needs_two_tracks_then_sends_collection(self) -> None:
        import asyncio
        from api.webapp import _action_crate_deliver

        context = _crate_context()
        self._add(context, "One")

        too_few = asyncio.run(_action_crate_deliver(context, "crate_send", 7, False))
        self.assertEqual(too_few["error"], "need more tracks")

        self._add(context, "Two")
        sent = asyncio.run(_action_crate_deliver(context, "crate_send", 7, False))
        self.assertTrue(sent["ok"])
        self.assertEqual(len(context.bot.sent), 1)
        self.assertIn("1.", context.bot.sent[0]["text"])
        self.assertIn("2.", context.bot.sent[0]["text"])

    def test_crate_publish_is_admin_only_and_clears_crate(self) -> None:
        import asyncio
        from api.webapp import _action_crate_deliver, _load_crate

        context = _crate_context()
        self._add(context, "One")
        self._add(context, "Two")

        denied = asyncio.run(_action_crate_deliver(context, "crate_publish", 7, False))
        self.assertEqual(denied["error"], "admin only")

        published = asyncio.run(_action_crate_deliver(context, "crate_publish", 7, True))
        self.assertTrue(published["ok"])
        self.assertEqual(context.bot.sent[0]["chat_id"], "@stonerhand")
        self.assertEqual(asyncio.run(_load_crate(context, 7)), [])

    def test_crate_add_accepts_client_item_without_draft(self) -> None:
        import asyncio
        from api.webapp import _action_crate_add

        context = _crate_context()
        body = {"item": _crate_track("Dopesmoker"), "items": []}
        first = asyncio.run(_action_crate_add(context, body, 7))
        self.assertEqual(first["count"], 1)
        self.assertEqual(first["items"][0]["title"], "Dopesmoker")
        # the response carries a resendable payload so the client can persist it
        self.assertEqual(first["items"][0]["data"]["artist"], "Sleep")

    def test_crate_deliver_uses_client_items_when_store_empty(self) -> None:
        # The exact regression: on serverless the server store can be empty
        # (another warm instance), so delivery must trust the client's list and
        # send every track — not just the last one.
        import asyncio
        from api.webapp import _action_crate_deliver, _load_crate

        context = _crate_context()
        self.assertEqual(asyncio.run(_load_crate(context, 7)), [])

        body = {"items": [_crate_track("One"), _crate_track("Two"), _crate_track("Three")]}
        sent = asyncio.run(_action_crate_deliver(context, "crate_send", 7, False, body))
        self.assertTrue(sent["ok"])
        self.assertEqual(len(context.bot.sent), 1)
        text = context.bot.sent[0]["text"]
        self.assertIn("1.", text)
        self.assertIn("2.", text)
        self.assertIn("3.", text)
        self.assertIn("One", text)
        self.assertIn("Two", text)
        self.assertIn("Three", text)

    def test_crate_rejects_non_http_button_url(self) -> None:
        from api.webapp import _compact_track_data

        malicious = _compact_track_data(
            {"artist": "X", "title": "Y", "page_url": "javascript:alert(1)", "links": {}}
        )
        self.assertIsNone(malicious["page_url"])

        with_fallback = _compact_track_data(
            {
                "artist": "X",
                "title": "Y",
                "page_url": "tg://evil",
                "links": {"spotify": "https://open.spotify.com/ok"},
            }
        )
        self.assertEqual(with_fallback["page_url"], "https://open.spotify.com/ok")

    def test_crate_deliver_client_items_deduped_and_need_two(self) -> None:
        import asyncio
        from api.webapp import _action_crate_deliver

        context = _crate_context()
        # a single unique track (duplicate collapsed) is not enough to deliver
        body = {"items": [_crate_track("Solo"), _crate_track("Solo")]}
        too_few = asyncio.run(_action_crate_deliver(context, "crate_send", 7, False, body))
        self.assertEqual(too_few["error"], "need more tracks")


class PreviewAndRateLimitTests(unittest.TestCase):
    def test_action_preview_looks_up_lazily(self) -> None:
        import asyncio
        from api.webapp import _action_preview

        class _Search:
            async def lookup_preview(self, artist, title):
                return "https://audio.example/p.mp3"

        context = _crate_context()
        context.application.bot_data["search_client"] = _Search()
        context.application.bot_data["drafts"]["d1"] = {
            "type": "track",
            "item": _crate_track("Dopesmoker"),
            "chat_id": 7,
            "preview": None,
            "preview_pending": True,
        }

        res = asyncio.run(_action_preview(context, {"draft_id": "d1"}, 7))
        self.assertTrue(res["ok"])
        self.assertEqual(res["preview"], "https://audio.example/p.mp3")

    def test_resolve_batch_builds_crate_from_multiple_links(self) -> None:
        import asyncio
        from api.webapp import _action_resolve_batch
        from music_links_bot.models import TrackMatch

        class _Songlink:
            async def lookup_track(self, url):
                name = url.rsplit("/", 1)[-1]
                return TrackMatch(
                    title=name, artist="Sleep", links={"spotify": url},
                    page_url="https://song.link/" + name,
                    thumbnail_url="https://img.example/x.jpg", kind="song",
                )

        context = _crate_context()
        context.application.bot_data["songlink_client"] = _Songlink()
        context.application.bot_data["soundcloud_client"] = None
        body = {"query": "https://open.spotify.com/track/aaa https://open.spotify.com/track/bbb"}

        res = asyncio.run(_action_resolve_batch(context, body, 7))
        self.assertTrue(res["ok"])
        self.assertEqual(res["count"], 2)
        self.assertEqual(sorted(item["title"] for item in res["items"]), ["aaa", "bbb"])
        # each item carries a resendable payload for the crate
        self.assertTrue(all(item.get("data") for item in res["items"]))

    def test_resolve_batch_needs_two_urls(self) -> None:
        import asyncio
        from api.webapp import _action_resolve_batch

        context = _crate_context()
        res = asyncio.run(
            _action_resolve_batch(context, {"query": "https://open.spotify.com/track/aaa"}, 7)
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "need urls")

    def test_resolve_rate_limiter_trips_then_recovers(self) -> None:
        from api import webapp

        webapp._resolve_calls.clear()
        uid = 999001
        results = [
            webapp._resolve_rate_limited(uid, now=1000.0)
            for _ in range(webapp.RESOLVE_RATE_LIMIT + 3)
        ]
        self.assertFalse(any(results[: webapp.RESOLVE_RATE_LIMIT]))
        self.assertTrue(all(results[webapp.RESOLVE_RATE_LIMIT :]))
        # once the window slides, the user is allowed again
        later = 1000.0 + webapp.RESOLVE_RATE_WINDOW_SECONDS + 1
        self.assertFalse(webapp._resolve_rate_limited(uid, now=later))


class PhotoPostTests(unittest.TestCase):
    def test_publish_draft_as_photo_uses_send_photo(self) -> None:
        import asyncio
        from music_links_bot.bot import _publish_draft

        context = _crate_context()
        draft = {
            "type": "track",
            "item": _crate_track("Dopesmoker"),
            "chat_id": 7,
            "hashtags": True,
            "as_photo": True,
        }

        self.assertTrue(asyncio.run(_publish_draft(context, draft)))
        self.assertEqual(len(context.bot.photos), 1)
        self.assertEqual(context.bot.photos[0]["photo"], "https://img.example/a.jpg")
        self.assertIn("Dopesmoker", context.bot.photos[0]["caption"])
        self.assertEqual(context.bot.sent, [])

    def test_publish_draft_without_artwork_falls_back_to_text(self) -> None:
        import asyncio
        from music_links_bot.bot import _publish_draft

        context = _crate_context()
        item = _crate_track("Dopesmoker")
        item["thumbnail_url"] = None
        draft = {"type": "track", "item": item, "chat_id": 7, "as_photo": True}

        self.assertTrue(asyncio.run(_publish_draft(context, draft)))
        self.assertEqual(context.bot.photos, [])
        self.assertEqual(len(context.bot.sent), 1)


class UnpublishTests(unittest.TestCase):
    def test_unpublish_deletes_channel_message(self) -> None:
        import asyncio
        from api.webapp import _action_unpublish

        class _Bot(_CrateBotStub):
            def __init__(self):
                super().__init__()
                self.deleted = []

            async def delete_message(self, **kwargs):
                self.deleted.append(kwargs)

        from types import SimpleNamespace

        bot = _Bot()
        application = SimpleNamespace(bot_data={"drafts": {}}, bot=bot)
        context = SimpleNamespace(application=application, bot=bot)
        application.bot_data["drafts"]["d1"] = {
            "type": "track",
            "item": _crate_track("Dopesmoker"),
            "chat_id": 7,
        }

        denied = asyncio.run(
            _action_unpublish(context, {"draft_id": "d1", "message_id": 5}, 7, False)
        )
        self.assertEqual(denied["error"], "admin only")

        ok = asyncio.run(
            _action_unpublish(context, {"draft_id": "d1", "message_id": 5}, 7, True)
        )
        self.assertTrue(ok["ok"])
        self.assertEqual(bot.deleted, [{"chat_id": "@stonerhand", "message_id": 5}])

        bad = asyncio.run(
            _action_unpublish(context, {"draft_id": "d1", "message_id": "x"}, 7, True)
        )
        self.assertEqual(bad["error"], "bad message")
