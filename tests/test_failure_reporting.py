"""Any failed update is recorded for diagnostics, and a failed tap says so."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest, RetryAfter

from music_links_bot.bot import _application_error_handler
from music_links_bot.bot_runtime import BotRuntime


def _raised(error: ValueError) -> ValueError:
    """An error with a traceback, like the ones handlers raise."""
    try:
        raise error
    except ValueError as caught:
        return caught


def _handle(update, error):
    runtime = BotRuntime()
    runtime.persist_metrics = AsyncMock()
    context = SimpleNamespace(
        error=error, application=SimpleNamespace(bot_data={"runtime": runtime})
    )
    asyncio.run(_application_error_handler(update, context))
    return runtime


def test_a_broken_button_is_recorded_and_answered():
    query = SimpleNamespace(
        answer=AsyncMock(), from_user=SimpleNamespace(language_code="ru")
    )
    update = SimpleNamespace(callback_query=query)

    runtime = _handle(update, _raised(ValueError("boom")))

    failure = runtime.last_failure
    assert (failure["kind"], failure["type"]) == ("callback_query", "ValueError")
    assert "test_failure_reporting.py" not in failure["where"]
    runtime.persist_metrics.assert_awaited_once_with(force=True)
    query.answer.assert_awaited_once()
    assert query.answer.await_args.kwargs["show_alert"] is True
    assert "Не получилось" in query.answer.await_args.args[0]


def test_an_already_answered_tap_is_left_alone():
    query = SimpleNamespace(
        answer=AsyncMock(side_effect=BadRequest("Query is too old")),
        from_user=None,
    )
    runtime = _handle(SimpleNamespace(callback_query=query), _raised(ValueError()))
    assert runtime.last_failure["kind"] == "callback_query"


def test_a_broken_inline_search_offers_the_bot_instead_of_nothing():
    inline = SimpleNamespace(
        answer=AsyncMock(), from_user=SimpleNamespace(language_code="en")
    )
    runtime = _handle(SimpleNamespace(inline_query=inline), _raised(ValueError()))

    assert runtime.last_failure["kind"] == "inline_query"
    results = inline.answer.await_args.args[0]
    button = inline.answer.await_args.kwargs["button"]
    assert results == [] and "open the bot" in button.text


def test_failures_keep_the_telegram_method_and_a_short_history():
    runtime = BotRuntime()
    for index in range(7):
        error = RetryAfter(8) if index == 6 else ValueError(str(index))
        error.add_note("telegram method: sendMessage")
        runtime.record_failure(error, kind="message")

    snapshot = runtime.metrics_snapshot()
    assert len(snapshot["recent_failures"]) == 5
    assert snapshot["last_failure"] == snapshot["recent_failures"][0]
    assert snapshot["last_failure"]["type"] == "RetryAfter"
    assert snapshot["last_failure"]["method"] == "sendMessage"
    assert "Flood control" in snapshot["last_failure"]["detail"]
