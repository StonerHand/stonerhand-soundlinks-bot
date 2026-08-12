from types import SimpleNamespace
import unittest

from music_links_bot.bot_crate import load_crate
from music_links_bot.bot_progress import adopt_progress_message, update_progress
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.channel_templates import load_channel_template
from music_links_bot.draft_model import CURRENT_DRAFT_VERSION, normalize_track_draft


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


class StateMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_v1_is_read_and_written_as_v2(self) -> None:
        kv = KVStub({"session:v1:7": {"user_id": 7, "last_query": "Sleep"}})
        runtime = BotRuntime(kv)

        session = await runtime.get_session(7)

        self.assertEqual(session.last_query, "Sleep")
        self.assertTrue(any(key == "session:v2:7" for key, _ in kv.writes))

    async def test_crate_v1_is_read_and_written_as_v2(self) -> None:
        item = {"draft_id": "d1", "item": {"artist": "Sleep", "title": "Holy Mountain"}}
        kv = KVStub({"bot-crate:v1:7": [item]})

        crate = await load_crate({"kv_store": kv}, 7)

        self.assertEqual(crate, [item])
        key, payload = kv.writes[-1]
        self.assertEqual(key, "bot-crate:v2:7")
        self.assertEqual(payload["v"], 2)

    async def test_template_v1_is_read_and_written_as_v2(self) -> None:
        import hashlib

        digest = hashlib.sha256(b"@stonerhand").hexdigest()[:20]
        kv = KVStub({f"channel:template:v1:{digest}": {"hashtags": False}})
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"kv_store": kv})
        )

        template = await load_channel_template(context, "@stonerhand")

        self.assertEqual(template, {"hashtags": False})
        self.assertTrue(any(key.startswith("channel:template:v2:") for key, _ in kv.writes))

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


class ProgressContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_never_regresses_or_repeats_a_stage(self) -> None:
        class Message:
            chat_id = 7

            def __init__(self) -> None:
                self.edits: list[str] = []

            async def edit_text(self, text: str) -> None:
                self.edits.append(text)

        message = Message()
        adopt_progress_message(message)
        await update_progress("ru", "progress_links")
        await update_progress("ru", "progress_search")
        await update_progress("ru", "progress_links")
        await update_progress("ru", "progress_card")

        self.assertEqual(len(message.edits), 2)
        self.assertTrue(message.edits[0].startswith("2/3"))
        self.assertTrue(message.edits[1].startswith("3/3"))


if __name__ == "__main__":
    unittest.main()
