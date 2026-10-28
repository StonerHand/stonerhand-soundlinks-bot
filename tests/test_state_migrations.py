import unittest

from music_links_bot.bot_progress import adopt_progress_message, update_progress
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.draft_model import (
    CURRENT_DRAFT_VERSION,
    normalize_track_draft,
    prepare_publication_draft,
)
from music_links_bot.models import TrackMatch


class KVStub:
    def __init__(self, values: dict) -> None:
        self.values = values
        self.writes: list[tuple[str, object]] = []

    async def get_json(self, key: str):
        return self.values.get(key)

    async def set_json(self, key: str, value, *, ttl_seconds: int):
        del ttl_seconds
        self.writes.append((key, value))
        self.values[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class StateMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_complete_collection_survives_runtime_restart(self) -> None:
        kv = KVStub({})
        urls = [
            "https://open.spotify.com/track/first?si=tracking",
            "https://open.spotify.com/track/second?si=tracking",
        ]
        first_runtime = BotRuntime(kv)
        await first_runtime.remember_collection(7, urls=urls, lang="ru")

        second_runtime = BotRuntime(kv)
        session = await second_runtime.get_session(7)

        self.assertEqual(
            session.last_collection_urls,
            [
                "https://open.spotify.com/track/first",
                "https://open.spotify.com/track/second",
            ],
        )

    async def test_stale_runtime_cannot_erase_durable_collection_state(self) -> None:
        kv = KVStub({})
        stale_runtime = BotRuntime(kv)
        await stale_runtime.get_session(7)

        writer_runtime = BotRuntime(kv)
        urls = [
            "https://open.spotify.com/track/first?si=tracking",
            "https://open.spotify.com/track/second?si=tracking",
        ]
        await writer_runtime.remember_collection(7, urls=urls, lang="ru")

        # This instance cached the session before the collection existed. Its
        # later action must not erase the independent complete snapshot.
        await stale_runtime.remember_action(
            7,
            kind="search",
            value="later action from a stale worker",
            lang="ru",
        )

        reader_runtime = BotRuntime(kv)
        self.assertEqual(
            await reader_runtime.get_collection(7, lang="ru"),
            [
                "https://open.spotify.com/track/first",
                "https://open.spotify.com/track/second",
            ],
        )

    async def test_forget_session_deletes_durable_collection_state(self) -> None:
        kv = KVStub({})
        runtime = BotRuntime(kv)
        await runtime.remember_collection(
            7,
            urls=[
                "https://open.spotify.com/track/first",
                "https://open.spotify.com/track/second",
            ],
            lang="ru",
        )

        await runtime.forget_session(7)

        self.assertNotIn("collection:v1:7", kv.values)
        self.assertEqual(await runtime.get_collection(7, lang="ru"), [])

    def test_legacy_draft_gets_safe_defaults(self) -> None:
        draft = normalize_track_draft(
            {
                "v": 1,
                "type": "track",
                "item": {"artist": "Sleep", "title": "Dragonaut", "links": {}},
                "chat_id": 7,
            }
        )

        self.assertIsNotNone(draft)
        assert draft is not None
        self.assertEqual(draft["v"], CURRENT_DRAFT_VERSION)
        self.assertEqual(draft["preset"], "cover")
        self.assertTrue(draft["hashtags"])

    def test_corrupt_optional_draft_metrics_are_repaired(self) -> None:
        draft = normalize_track_draft(
            {
                "v": 3,
                "type": "track",
                "item": {"artist": "Sleep", "title": "Dragonaut", "links": {}},
                "chat_id": 7,
                "created_at": "broken",
                "intro_length": "broken",
                "intro_limit": object(),
            }
        )

        self.assertIsNotNone(draft)
        assert draft is not None
        self.assertEqual(draft["intro_length"], 0)
        self.assertEqual(draft["intro_limit"], 0)
        self.assertGreater(draft["created_at"], 0)

    def test_durable_item_is_sanitized_for_strict_track_model(self) -> None:
        draft = normalize_track_draft(
            {
                "v": 3,
                "type": "track",
                "chat_id": 7,
                "item": {
                    "artist": "Sleep",
                    "title": "Dragonaut",
                    "release_year": 1992,
                    "links": {
                        "Spotify": "https://open.spotify.com/track/abc",
                        "legacy_search": "https://open.spotify.com/search/Sleep%20Dragonaut",
                        "unsafe": "javascript:alert(1)",
                    },
                    "unknown_future_field": "must not break old workers",
                },
            }
        )

        self.assertIsNotNone(draft)
        assert draft is not None
        self.assertNotIn("unknown_future_field", draft["item"])
        self.assertEqual(draft["item"]["release_year"], "1992")
        self.assertEqual(
            draft["item"]["links"],
            {"spotify": "https://open.spotify.com/track/abc"},
        )
        self.assertEqual(TrackMatch(**draft["item"]).title, "Dragonaut")

    def test_legacy_delivery_payload_becomes_a_strict_snapshot(self) -> None:
        prepared = prepare_publication_draft(
            {
                "item": {
                    "artist": "Sleep",
                    "title": "Dragonaut",
                    "links": {"spotify": "https://open.spotify.com/track/abc"},
                    "future_field": "ignored",
                },
                "delivery_mode": "classic",
            }
        )

        self.assertIsNotNone(prepared)
        assert prepared is not None
        self.assertEqual(prepared.track.title, "Dragonaut")
        self.assertNotIn("future_field", prepared.data["item"])
        self.assertEqual(prepared.data["delivery_mode"], "classic")


class ProgressContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_never_regresses_or_repeats_a_stage(self) -> None:
        class Message:
            chat_id = 7

            def __init__(self) -> None:
                self.edits: list[str] = []

            async def edit_text(self, text: str, **kwargs) -> None:
                self.edits.append(text)

        message = Message()
        adopt_progress_message(message)
        await update_progress("ru", "progress_links")
        await update_progress("ru", "progress_search")
        await update_progress("ru", "progress_links")
        await update_progress("ru", "progress_batch", done=2, total=2)

        self.assertEqual(len(message.edits), 2)
        self.assertTrue(message.edits[0].startswith("🔎 "))
        self.assertTrue(message.edits[1].startswith("🔎 Ссылки · 2/2"))


if __name__ == "__main__":
    unittest.main()
