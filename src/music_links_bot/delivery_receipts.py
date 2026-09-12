"""Durable manual-send intents: uncertain deliveries are never blindly retried."""

from __future__ import annotations

import hashlib
import time

from music_links_bot.durable_state import read_json
from music_links_bot.state_mutations import mutate_json

RECEIPT_TTL_SECONDS = 90 * 24 * 3600


class DeliveryBlockedError(RuntimeError):
    def __init__(self, receipt):
        super().__init__("Manual delivery already attempted")
        self.receipt = receipt


def receipt_key(draft_id, target):
    digest = hashlib.sha256(str(target).encode()).hexdigest()[:16]
    return f"manual-delivery:v1:{draft_id}:{digest}"


async def begin_delivery(context, draft, target):
    draft_id = draft.get("editor_draft_id")
    if not draft_id:
        return None
    key = receipt_key(draft_id, target)
    retry = draft.pop("repeat_delivery", False)

    def begin(previous):
        if (
            previous
            and previous.get("status") in {"sending", "uncertain", "sent"}
            and not retry
        ):
            raise DeliveryBlockedError(previous)
        if retry == "reviewed" and previous and previous.get("status") == "sent":
            raise DeliveryBlockedError(previous)
        # A retry confirmed by the owner can never interrupt an active send.
        if (
            previous
            and previous.get("status") == "sending"
            and previous.get("started_at", 0) + 60 > time.time()
        ):
            raise DeliveryBlockedError(previous)
        return {
            "status": "sending",
            "started_at": int(time.time()),
            "target": target,
            "attempt": int((previous or {}).get("attempt") or 0) + 1,
        }

    kv = context.application.bot_data.get("kv_store")
    owner = draft.get("chat_id")
    if isinstance(owner, int) and owner > 0:

        def index(payload):
            now = int(time.time())
            values = (
                payload
                if isinstance(payload, dict)
                else {
                    value: now + RECEIPT_TTL_SECONDS
                    for value in payload
                    if isinstance(value, str)
                }
                if isinstance(payload, list)
                else {}
            )
            return {
                **{
                    name: expiry
                    for name, expiry in values.items()
                    if isinstance(expiry, (int, float)) and expiry > now
                },
                key: now + RECEIPT_TTL_SECONDS,
            }

        if kv:
            await mutate_json(
                kv, f"receipt-index:v1:{owner}", index, ttl_seconds=RECEIPT_TTL_SECONDS
            )
        else:
            context.application.bot_data.setdefault("receipt_indexes", {})[owner] = (
                index(
                    context.application.bot_data.get("receipt_indexes", {}).get(owner)
                )
            )
    if kv:
        receipt = await mutate_json(kv, key, begin, ttl_seconds=RECEIPT_TTL_SECONDS)
    else:
        receipts = context.application.bot_data.setdefault("delivery_receipts", {})
        receipt = begin(receipts.get(key))
        from music_links_bot.bot_storage import remember_bounded

        remember_bounded(receipts, key, receipt, max_size=600)
    return key, receipt


async def finish_delivery(context, intent, *, sent, confirmed_not_sent):
    if intent is None:
        return
    key, expected = intent

    def finish(current):
        if current is None or current.get("attempt") != expected["attempt"]:
            return current
        return {
            **current,
            "status": "sent"
            if sent
            else "failed"
            if confirmed_not_sent
            else "uncertain",
            "message_id": getattr(sent, "message_id", None),
            "finished_at": int(time.time()),
        }

    kv = context.application.bot_data.get("kv_store")
    if kv:
        await mutate_json(kv, key, finish, ttl_seconds=RECEIPT_TTL_SECONDS)
    else:
        receipts = context.application.bot_data.setdefault("delivery_receipts", {})
        receipts[key] = finish(receipts.get(key))


async def load_delivery(context, draft_id, target):
    key = receipt_key(draft_id, target)
    kv = context.application.bot_data.get("kv_store")
    return (
        await read_json(kv, key)
        if kv
        else context.application.bot_data.get("delivery_receipts", {}).get(key)
    )
