import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.loop_runner import (
    run_on_loop,
    start_background_loop,
    stop_background_loop,
)


class LoopRunnerTests(unittest.TestCase):
    def test_two_request_threads_can_await_concurrently(self) -> None:
        loop, thread = start_background_loop("test-runtime")
        async def make_state():
            return {"active": 0, "both_started": asyncio.Event()}

        state = run_on_loop(loop, make_state(), timeout=1)

        async def job(value: int) -> int:
            state["active"] += 1
            if state["active"] == 2:
                state["both_started"].set()
            await asyncio.wait_for(state["both_started"].wait(), timeout=1)
            return value

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(run_on_loop, loop, job(1), timeout=2)
                second = pool.submit(run_on_loop, loop, job(2), timeout=2)
                self.assertEqual({first.result(), second.result()}, {1, 2})
        finally:
            stop_background_loop(loop, thread)


if __name__ == "__main__":
    unittest.main()
