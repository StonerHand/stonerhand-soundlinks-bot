import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.request_guard import rate_limited, run_idempotent


def make_context():
    return SimpleNamespace(application=SimpleNamespace(bot_data={}))


class RequestGuardTests(unittest.TestCase):
    def test_memory_rate_limit_is_shared_by_scope_and_subject(self) -> None:
        context = make_context()

        async def scenario():
            return [
                await rate_limited(
                    context,
                    scope="resolve",
                    subject=42,
                    limit=2,
                    window_seconds=60,
                    now=100,
                )
                for _ in range(3)
            ]

        self.assertEqual(asyncio.run(scenario()), [False, False, True])

    def test_idempotent_concurrent_calls_execute_once(self) -> None:
        context = make_context()
        calls = 0

        async def execute():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return {"ok": True, "message_id": 7}

        async def scenario():
            return await asyncio.gather(
                *(
                    run_idempotent(
                        context,
                        user_id=42,
                        action="publish",
                        request_key="same-request",
                        execute=execute,
                    )
                    for _ in range(5)
                )
            )

        results = asyncio.run(scenario())
        self.assertEqual(calls, 1)
        self.assertTrue(all(result == results[0] for result in results))

    def test_missing_key_preserves_normal_repeat_behavior(self) -> None:
        context = make_context()
        calls = 0

        async def execute():
            nonlocal calls
            calls += 1
            return {"ok": True}

        async def scenario():
            await run_idempotent(
                context, user_id=1, action="send", request_key=None, execute=execute
            )
            await run_idempotent(
                context, user_id=1, action="send", request_key=None, execute=execute
            )

        asyncio.run(scenario())
        self.assertEqual(calls, 2)

    def test_retryable_result_is_not_cached(self) -> None:
        context = make_context()
        calls = 0

        async def execute():
            nonlocal calls
            calls += 1
            return {"ok": False, "error": "timeout", "retryable": True}

        async def scenario():
            for _ in range(2):
                await run_idempotent(
                    context,
                    user_id=1,
                    action="deliver",
                    request_key="retry-1",
                    execute=execute,
                )

        asyncio.run(scenario())
        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
