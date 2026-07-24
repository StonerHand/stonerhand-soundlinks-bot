import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import telegram as tg


class UpdateDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        tg._SEEN_UPDATE_IDS.clear()

    def _app(self) -> SimpleNamespace:
        return SimpleNamespace(bot_data={})

    def test_duplicate_update_is_skipped(self) -> None:
        app = self._app()

        async def scenario():
            first = await tg._claim_update(app, 90001)
            second = await tg._claim_update(app, 90001)
            return first, second

        first, second = asyncio.run(scenario())
        self.assertTrue(first)
        self.assertFalse(second)  # Telegram retry of the same update is ignored

    def test_released_update_can_be_reprocessed(self) -> None:
        app = self._app()

        async def scenario():
            claimed = await tg._claim_update(app, 90002)
            # a failed update releases its claim so Telegram's retry reprocesses
            await tg._release_update(app, 90002)
            reclaimed = await tg._claim_update(app, 90002)
            return claimed, reclaimed

        claimed, reclaimed = asyncio.run(scenario())
        self.assertTrue(claimed)
        self.assertTrue(reclaimed)

    def test_redis_outage_falls_back_instead_of_dropping_update(self) -> None:
        class UnavailableKV:
            async def set(self, *_args, **_kwargs):
                return False

            async def get(self, _key):
                return None

        app = SimpleNamespace(bot_data={"kv_store": UnavailableKV()})

        first = asyncio.run(tg._claim_update(app, 90003))
        second = asyncio.run(tg._claim_update(app, 90003))

        self.assertTrue(first)
        self.assertFalse(second)

    def test_in_memory_claim_expires_after_dedup_ttl(self) -> None:
        self.assertTrue(tg._claim_update_in_memory(90004, now=1000))
        self.assertFalse(tg._claim_update_in_memory(90004, now=1001))
        self.assertTrue(
            tg._claim_update_in_memory(
                90004,
                now=1000 + tg.UPDATE_DEDUP_TTL_SECONDS + 1,
            )
        )


if __name__ == "__main__":
    unittest.main()
