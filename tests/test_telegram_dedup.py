import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import telegram as tg


class UpdateDedupTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
