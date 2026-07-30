from __future__ import annotations

import asyncio
from html import escape
from time import time

from telegram.constants import ParseMode
from telegram.error import TelegramError

from music_links_bot.bot_runtime import METRICS_KV_KEY
from music_links_bot.chat_access import check_publish_access
from music_links_bot.publish_queue import QueueStorageError, load_jobs
from music_links_bot.stats import format_stats_message, load_stats, merge_stats

STATS_KV_KEY = "stats:v1"


async def id_command(update, context) -> None:
    del context
    message = update.effective_message
    if message is not None:
        await message.reply_text(f"Chat ID: {message.chat_id}")


async def stats_command(update, context) -> None:
    message = update.effective_message
    if message is None:
        return
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    include_private = (
        admin_chat_id is not None and message.chat_id == admin_chat_id
    )
    await message.reply_text(
        await stats_text(context, include_private=include_private)
    )


async def stats_text(context, *, include_private: bool) -> str:
    stats_data = load_stats()
    kv = context.application.bot_data.get("kv_store")
    if kv is not None:
        stats_data = merge_stats(stats_data, await kv.get_json(STATS_KV_KEY))

    text = format_stats_message(stats_data, include_private=include_private)
    if not include_private:
        return text

    runtime = context.application.bot_data.get("runtime")
    if runtime is None:
        return text
    metrics = runtime.metrics_snapshot()
    text += (
        "\n\nRuntime\n"
        f"Запросы: {metrics['requests']} · "
        f"среднее: {metrics['request_ms_avg']} ms · "
        f"кэш: {metrics['cache_hits']}/{metrics['cache_misses']}"
    )
    diagnostics = runtime.provider_snapshot()
    if diagnostics:
        lines = ["", "Провайдеры"]
        for item in diagnostics:
            marker = (
                "⛔"
                if item.get("circuit_open")
                else "✅" if item["ok"] else "⚠️"
            )
            lines.append(
                f"{marker} {item['provider']} · {item['latency_ms']} ms"
                + (
                    f" · {item['last_error']}"
                    if item["last_error"]
                    else ""
                )
            )
        text += "\n".join(lines)
    return text


async def status_command(update, context) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    if admin_chat_id is None or user.id != admin_chat_id:
        await message.reply_text("Эта диагностика доступна только владельцу бота.")
        return

    text = await build_status_text(context)
    await message.reply_text(text, parse_mode=ParseMode.HTML)


async def build_status_text(context) -> str:
    bot_data = context.application.bot_data
    target = bot_data.get("publish_chat_id") or "@stonerhand"
    runtime = bot_data.get("runtime")
    kv = bot_data.get("kv_store")

    webhook_ok = False
    webhook_detail = "не проверен"
    try:
        info = await asyncio.wait_for(context.bot.get_webhook_info(), timeout=3)
        webhook_ok = bool(getattr(info, "url", ""))
        pending = int(getattr(info, "pending_update_count", 0) or 0)
        webhook_detail = f"очередь обновлений: {pending}"
        last_error = getattr(info, "last_error_message", None)
        if last_error:
            webhook_detail += f", ошибка: {last_error}"
            webhook_ok = False
    except (TelegramError, TimeoutError, AttributeError) as exc:
        webhook_detail = type(exc).__name__

    redis_ok = kv is not None
    if kv is not None:
        try:
            redis_ok = bool(
                await asyncio.wait_for(
                    kv.set(
                        "status:ping",
                        str(int(time())),
                        ttl_seconds=120,
                    ),
                    timeout=1,
                )
            )
        except TimeoutError:
            redis_ok = False

    access = await check_publish_access(context, target)
    try:
        jobs = await load_jobs(context)
        queue_ok = True
        queue_detail = None
    except QueueStorageError:
        jobs = []
        queue_ok = False
        queue_detail = "Redis недоступен"
    overdue = sum(
        int(job.get("publish_at") or 0) < int(time()) - 120
        for job in jobs
        if isinstance(job, dict)
    )

    metrics = runtime.metrics_snapshot() if runtime is not None else {}
    if kv is not None:
        persisted = await kv.get_json(METRICS_KV_KEY)
        if not metrics.get("requests") and isinstance(persisted, dict):
            metrics = persisted

    lines = [
        "<b>Состояние StonerHandBot</b>",
        "",
        _line("Telegram webhook", webhook_ok, webhook_detail),
        _line("Redis", redis_ok, "подключён" if kv is not None else "не подключён"),
        _line("Публикация в канал", access.allowed, access.detail),
        _line(
            "Очередь",
            queue_ok and overdue == 0,
            queue_detail or f"{len(jobs)} задач, просрочено: {overdue}",
        ),
    ]

    if metrics:
        lines.extend(
            [
                "",
                "<b>Последний процесс</b>",
                (
                    f"Запросы: <code>{int(metrics.get('requests') or 0)}</code> · "
                    f"среднее: <code>{int(metrics.get('request_ms_avg') or 0)} ms</code>"
                ),
                (
                    f"Кэш: <code>{int(metrics.get('cache_hits') or 0)}</code> попаданий · "
                    f"<code>{int(metrics.get('cache_misses') or 0)}</code> промахов"
                ),
                (
                    f"Публикации: <code>{int(metrics.get('publications') or 0)}</code> · "
                    f"ошибки: <code>{int(metrics.get('publication_errors') or 0)}</code>"
                ),
            ]
        )

    diagnostics = runtime.provider_snapshot() if runtime is not None else []
    if diagnostics:
        lines.extend(["", "<b>Провайдеры</b>"])
        for item in diagnostics:
            marker = "⛔" if item.get("circuit_open") else (
                "✅" if item.get("ok") else "⚠️"
            )
            detail = f"{item.get('latency_ms', 0)} ms"
            if item.get("last_error"):
                detail += f", {item['last_error']}"
            lines.append(
                f"{marker} {escape(str(item['provider']))} · <code>{escape(detail)}</code>"
            )

    last_error = bot_data.get("last_error")
    if isinstance(last_error, dict):
        lines.extend(
            [
                "",
                "<b>Последняя внутренняя ошибка</b>",
                f"<code>{escape(str(last_error.get('type') or 'unknown'))}</code>",
            ]
        )
    return "\n".join(lines)


def _line(label: str, ok: bool, detail: str) -> str:
    marker = "✅" if ok else "⚠️"
    return f"{marker} <b>{escape(label)}</b> · {escape(detail)}"
