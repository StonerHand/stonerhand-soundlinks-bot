"""Re-sending a post whose delivery Telegram never confirmed."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from music_links_bot.bot_runtime import decode_callback
from music_links_bot.bot_workspace import handle_workspace_action

OWNER = 1


def _request(action: str, *, user_id: int = OWNER):
    return SimpleNamespace(
        action=action,
        draft={},
        lang="ru",
        user_id=user_id,
        draft_id="d1",
        track=None,
        query=SimpleNamespace(answer=AsyncMock()),
        context=SimpleNamespace(
            application=SimpleNamespace(
                bot_data={"admin_chat_id": OWNER, "publish_chat_id": -100}
            )
        ),
    )


class DeliveryRetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.receipts: dict[object, dict] = {}

        async def load_delivery(context, draft_id, destination):
            return self.receipts.get(destination)

        self.edit = AsyncMock()
        self.run = AsyncMock()
        for target, new in (
            ("music_links_bot.delivery_receipts.load_delivery", load_delivery),
            ("music_links_bot.editor_screen._edit_editor_message", self.edit),
            ("music_links_bot.bot_editor._run_locked_editor_action", self.run),
        ):
            patcher = patch(target, new=new)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _retry_actions(self) -> list[str]:
        markup = self.edit.await_args.args[4]
        return [
            decode_callback(row[0].callback_data).action
            for row in markup.inline_keyboard
        ]

    async def test_review_offers_only_unconfirmed_destinations(self) -> None:
        self.receipts = {-100: {"status": "uncertain"}, OWNER: {"status": "sent"}}

        self.assertTrue(await handle_workspace_action(_request("retry_review")))

        self.assertEqual(self._retry_actions(), ["retry_channel", "b"])

    async def test_non_owners_never_see_the_channel_retry(self) -> None:
        self.receipts = {-100: {"status": "uncertain"}, 5: {"status": "sending"}}

        await handle_workspace_action(_request("retry_review", user_id=5))

        self.assertEqual(self._retry_actions(), ["retry_self", "b"])

    async def test_confirmed_retry_republishes_once_reviewed(self) -> None:
        self.receipts = {-100: {"status": "uncertain"}}
        request = _request("retry_channel")

        await handle_workspace_action(request)

        self.run.assert_awaited_once_with(request)
        self.assertEqual(request.action, "pc")
        self.assertEqual(request.draft["repeat_delivery"], "reviewed")

    async def test_a_delivered_post_is_not_sent_twice(self) -> None:
        self.receipts = {OWNER: {"status": "sent"}}
        request = _request("retry_self")

        await handle_workspace_action(request)

        self.run.assert_not_awaited()
        self.assertTrue(request.query.answer.await_args.kwargs.get("show_alert"))

    async def test_only_the_owner_can_retry_the_channel(self) -> None:
        self.receipts = {-100: {"status": "uncertain"}}
        request = _request("retry_channel", user_id=5)

        await handle_workspace_action(request)

        self.run.assert_not_awaited()
        self.assertTrue(request.query.answer.await_args.kwargs.get("show_alert"))

    async def test_other_actions_are_left_to_the_editor(self) -> None:
        self.assertFalse(await handle_workspace_action(_request("zz")))


if __name__ == "__main__":
    unittest.main()
