"""Expose PTB handler failures and ambiguous sends to the webhook boundary."""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass

from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ExtBot


@dataclass
class UpdateExecution:
    error: Exception | None = None
    deliveries: int = 0
    before_send: Callable[[], Awaitable[None]] | None = None


current_execution: ContextVar[UpdateExecution | None] = ContextVar(
    "update_execution", default=None
)


def begin_send(method):
    execution = current_execution.get()
    # Progress drafts and idempotent edits do not deliver a new permanent post.
    sends = method.startswith(("send", "copy", "forward")) and not method.endswith(
        "Draft"
    )
    if execution is not None and sends:
        execution.deliveries += 1
        return execution
    return None


async def protect_send(execution):
    if execution is not None and execution.before_send is not None:
        try:
            await execution.before_send()
        except BaseException:
            execution.deliveries -= 1
            raise


def reject_send(execution, error):
    if execution is not None and isinstance(error, (BadRequest, Forbidden, RetryAfter)):
        execution.deliveries -= 1


class DeliveryAwareBot(ExtBot):
    __slots__ = ()

    async def _do_post(self, endpoint, data, **kwargs):
        execution = begin_send(endpoint)
        await protect_send(execution)
        try:
            return await super()._do_post(endpoint, data, **kwargs)
        except Exception as exc:
            reject_send(execution, exc)
            raise
