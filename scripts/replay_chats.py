"""Replay real chats on the fully built bot and print what it sent.

Real providers over the network, a fake Telegram transport and a fakeredis
Upstash. Every scenario is one realistic update; the output is the Bot API
calls it produced, so a change in how messages are sent, edited or deleted is
seen before it ships (CLAUDE.md, "Checks before a PR").

    .venv/bin/python scripts/replay_chats.py                    # every scenario
    .venv/bin/python scripts/replay_chats.py channel_spotify group_yt --full
    .venv/bin/python scripts/replay_chats.py spotify --timeline --redis-ms 25
    .venv/bin/python scripts/replay_chats.py publish_flow

--full prints whole texts, buttons and previews; --timeline adds every Redis
command and provider request with its start and end in milliseconds;
--redis-ms gives each Redis command a network delay; --refuse-player makes
Telegram reject YouTube's player preview, as it does on a bad day.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT)]

import httpx
from telegram import Update
from telegram.request import BaseRequest
from test_audit_reliability import RedisREST

from music_links_bot.chat.bot_app import build_application
from music_links_bot.core.config import Settings

ADMIN = 456
# Never the real store: the replay runs on its own in-memory Redis.
REAL_STORE_VARIABLES = (
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN",
    "KV_REST_API_URL",
    "KV_REST_API_TOKEN",
)
GROUP = {"id": -100555, "type": "supergroup", "title": "G"}
CHANNEL = {
    "id": -100777,
    "type": "channel",
    "title": "StonerHand",
    "username": "stonerhand",
}
SPOTIFY = "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy"
DEEZER = "https://www.deezer.com/album/1067379601"
YOUTUBE = "https://www.youtube.com/watch?v=j7K6FC_psGc"
SETUP_CALLS = {
    "getMe",
    "setMyCommands",
    "setChatMenuButton",
    "setMyDescription",
    "setMyShortDescription",
    "setMyName",
}
ADMIN_RIGHTS = {
    "status": "administrator",
    "user": {"id": 1, "is_bot": True, "first_name": "B"},
    "can_be_edited": False,
    "is_anonymous": False,
    "can_manage_chat": True,
    "can_delete_messages": True,
    "can_manage_video_chats": True,
    "can_restrict_members": True,
    "can_promote_members": False,
    "can_change_info": True,
    "can_invite_users": True,
    "can_post_stories": False,
    "can_edit_stories": False,
    "can_delete_stories": False,
    "can_post_messages": True,
    "can_edit_messages": True,
}


class Replay:
    """What one update did: Bot API calls, and a timeline of everything."""

    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options
        self.calls: list[dict] = []
        self.timeline: list[tuple[int, int, str, str]] = []
        self.started = time.monotonic()
        self.next_message_id = 5000
        self.logs = io.StringIO()

    def reset(self) -> None:
        self.calls.clear()
        self.timeline.clear()
        self.logs.seek(0)
        self.logs.truncate()
        self.started = time.monotonic()

    def now(self) -> int:
        return round((time.monotonic() - self.started) * 1000)

    def mark(self, begin: int, kind: str, detail: str) -> None:
        self.timeline.append((begin, self.now(), kind, detail))


def _loads(value):
    return json.loads(value) if isinstance(value, str) else value


class FakeTelegram(BaseRequest):
    def __init__(self, replay: Replay) -> None:
        self.replay = replay

    @property
    def read_timeout(self):
        return 5.0

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def do_request(self, url, method, request_data=None, **_kwargs):
        replay = self.replay
        api = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        preview = _loads(params.get("link_preview_options")) or {}
        replay.mark(replay.now(), "TG", api)
        replay.calls.append(
            {
                "api": api,
                "chat": params.get("chat_id"),
                "text": str(params.get("text") or params.get("caption") or ""),
                "markup": _loads(params.get("reply_markup")) or {},
                "preview": preview,
            }
        )
        if (
            replay.options.refuse_player
            and api in {"sendMessage", "editMessageText"}
            and "youtube.com" in str(preview.get("url", ""))
        ):
            refusal = {
                "ok": False,
                "error_code": 400,
                "description": "Bad Request: wrong web page url",
            }
            return 400, json.dumps(refusal).encode()
        if api == "getMe":
            result: object = {
                "id": 1,
                "is_bot": True,
                "first_name": "B",
                "username": "StonerHandBot",
            }
        elif api == "getChatMember":
            result = ADMIN_RIGHTS
        elif api.startswith(("send", "edit", "copy")):
            replay.next_message_id += 1
            result = {
                "message_id": replay.next_message_id,
                "date": int(time.time()),
                "chat": {
                    "id": params.get("chat_id", 1),
                    "type": "private",
                    "first_name": "A",
                },
                "text": "x",
            }
        else:
            result = True
        return 200, json.dumps({"ok": True, "result": result}).encode()


def _observe_redis(store: RedisREST, replay: Replay) -> None:
    respond = store.respond

    async def observed(request):
        command = json.loads(request.content)
        begin = replay.now()
        if replay.options.redis_ms:
            await asyncio.sleep(replay.options.redis_ms / 1000)
        try:
            return await respond(request)
        finally:
            detail = str(command[1]) if len(command) > 1 else ""
            if command[0] in {"EVAL", "EVALSHA"}:
                count = int(command[2])
                keys = ",".join(map(str, command[3 : 3 + count]))
                script = " ".join(str(command[1]).split())[60:140]
                detail = f"keys={keys[:70]} | {script}"
            replay.mark(begin, command[0], detail[:200])

    store._client = httpx.AsyncClient(
        base_url="https://redis.test", transport=httpx.MockTransport(observed)
    )


def _observed_http(replay: Replay):
    send = httpx.AsyncClient.send

    async def observed(self, request, **kwargs):
        if request.url.host == "redis.test":
            return await send(self, request, **kwargs)
        begin = replay.now()
        status: object = "ERR"
        try:
            response = await send(self, request, **kwargs)
            status = response.status_code
            return response
        finally:
            replay.mark(
                begin, "HTTP", f"{status} {request.method} {str(request.url)[:150]}"
            )

    return patch.object(httpx.AsyncClient, "send", observed)


def _user(user_id: int = ADMIN) -> dict:
    return {
        "id": user_id,
        "is_bot": False,
        "first_name": "Artem",
        "username": "artem",
        "language_code": "ru",
    }


_MESSAGE_ID = [100]
_UPDATE_ID = [1]


def _message(chat: dict, text: str, **extra) -> dict:
    entities = []
    if text.startswith("/"):
        entities.append(
            {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
        )
    start = text.find("http")
    while start >= 0:
        end = text.find(" ", start)
        end = len(text) if end < 0 else end
        entities.append({"type": "url", "offset": start, "length": end - start})
        start = text.find("http", end)
    _MESSAGE_ID[0] += 1
    return {
        "message_id": _MESSAGE_ID[0],
        "date": int(time.time()),
        "chat": chat,
        "text": text,
        "entities": entities,
        **extra,
    }


def private(text: str) -> dict:
    chat = {"id": ADMIN, "type": "private", "first_name": "Artem"}
    return {"message": _message(chat, text, **{"from": _user()})}


def group(text: str) -> dict:
    return {"message": _message(GROUP, text, **{"from": _user(999)})}


def discussion_forward(text: str) -> dict:
    """A channel post as it arrives in the linked discussion group."""
    sender = {"id": -100777, "type": "channel", "title": "StonerHand"}
    telegram = {"id": 777000, "is_bot": False, "first_name": "Telegram"}
    return {
        "message": _message(
            GROUP,
            text,
            sender_chat=sender,
            is_automatic_forward=True,
            **{"from": telegram},
        )
    }


def channel(text: str) -> dict:
    sender = {"id": -100777, "type": "channel", "title": "StonerHand"}
    return {"channel_post": _message(CHANNEL, text, sender_chat=sender)}


def inline(query: str) -> dict:
    return {
        "inline_query": {
            "id": str(time.time()),
            "from": _user(),
            "query": query,
            "offset": "",
            "chat_type": "private",
        }
    }


def tap(data: str, message_id: int) -> dict:
    return {
        "callback_query": {
            "id": str(time.time()),
            "from": _user(),
            "chat_instance": "1",
            "data": data,
            "message": {
                "message_id": message_id,
                "date": int(time.time()),
                "chat": {"id": ADMIN, "type": "private", "first_name": "Artem"},
                "from": {"id": 1, "is_bot": True, "first_name": "B"},
                "text": "x",
            },
        }
    }


SCENARIOS = {
    "start": lambda: private("/start"),
    "yt": lambda: private("https://www.youtube.com/watch?v=E3mSkI9uskw"),
    "spotify": lambda: private(f"Классика {SPOTIFY}"),
    "collection": lambda: private(f"{SPOTIFY} {DEEZER}"),
    "search": lambda: private("Sleep — Dragonaut"),
    "netflix": lambda: private("https://www.netflix.com/title/81054853"),
    "status": lambda: private("/status"),
    "group_yt": lambda: group(YOUTUBE),
    "forward_yt": lambda: discussion_forward(YOUTUBE),
    "channel_spotify": lambda: channel(SPOTIFY),
    "channel_yt": lambda: channel(YOUTUBE),
    "channel_collection": lambda: channel(f"Пара альбомов {SPOTIFY} {DEEZER}"),
    "inline_yt": lambda: inline("https://www.youtube.com/watch?v=E3mSkI9uskw"),
}


async def run(app, replay: Replay, name: str, payload: dict) -> list[dict]:
    replay.reset()
    _UPDATE_ID[0] += 1
    update = Update.de_json({"update_id": _UPDATE_ID[0], **payload}, app.bot)
    try:
        await asyncio.wait_for(app.process_update(update), 40)
    except Exception as exc:  # noqa: BLE001 — a replay reports, it does not stop.
        print(f"!! {name}: {type(exc).__name__} {exc}")
    elapsed = replay.now()
    # Work started beside the reply (cache writes, cleanup) lands here.
    await asyncio.sleep(0.3)
    redis = sum(
        1 for *_times, kind, _detail in replay.timeline if kind not in {"TG", "HTTP"}
    )
    print(f"== {name} ({elapsed} ms, redis={redis})")
    if replay.options.timeline:
        for begin, end, kind, detail in replay.timeline:
            print(f"   {begin:5}-{end:5} {kind:8} {detail}")
    for call in replay.calls:
        if call["api"] in SETUP_CALLS:
            continue
        limit = 400 if replay.options.full else 60
        text = call["text"][:limit].replace("\n", " | ")
        print(f"   {call['api']:22} chat={call['chat']!s:>9} {text}")
        if replay.options.full and call["api"].startswith(("send", "edit")):
            for row in call["markup"].get("inline_keyboard", []):
                print("      [" + "] [".join(b.get("text", "") for b in row) + "]")
            if call["preview"]:
                above = "above" if call["preview"].get("show_above_text") else ""
                print("      preview:", call["preview"].get("url"), above)
    for line in replay.logs.getvalue().splitlines():
        if line.startswith(("ERROR", "WARNING")):
            print("   LOG", line[:180])
    return list(replay.calls)


def _button(calls: list[dict], wanted) -> dict:
    for call in reversed(calls):
        for row in call["markup"].get("inline_keyboard", []):
            for button in row:
                if "callback_data" in button and wanted(button):
                    return button
    raise LookupError("the expected button was not sent")


async def publish_flow(app, replay: Replay) -> None:
    """A link becomes a draft, the draft is published to the channel."""
    calls = await run(app, replay, "draft", private(SPOTIFY))
    publish = _button(calls, lambda button: "Опубликовать" in button["text"])
    calls = await run(
        app,
        replay,
        "tap publish",
        tap(publish["callback_data"], replay.next_message_id),
    )
    confirm = _button(calls, lambda _button: True)
    await run(
        app,
        replay,
        "tap confirm",
        tap(confirm["callback_data"], replay.next_message_id),
    )


async def main(options: argparse.Namespace) -> None:
    replay = Replay(options)
    logging.basicConfig(
        level=logging.WARNING,
        stream=replay.logs,
        format="%(levelname)s %(name)s %(message)s",
    )
    store = RedisREST()
    _observe_redis(store, replay)

    async def refuse_raw(self, method, data):
        from telegram.error import BadRequest

        replay.calls.append(
            {
                "api": f"RAW:{method}",
                "chat": data.get("chat_id"),
                "text": "",
                "markup": {},
                "preview": {},
            }
        )
        raise BadRequest("not in replay")

    with ExitStack() as stack:
        environment = stack.enter_context(patch.dict(os.environ))
        for name in REAL_STORE_VARIABLES:
            environment.pop(name, None)
        environment.update(WEBHOOK_BASE_URL="https://bot.example", BOT_TOKEN="1:fake")
        stack.enter_context(_observed_http(replay))
        stack.enter_context(
            patch(
                "music_links_bot.state.kvstore.KVStore.from_env",
                classmethod(lambda cls: store),
            )
        )
        # Raw Bot API methods the library does not know (ephemeral messages):
        # refused, so the bot takes its ordinary public path.
        stack.enter_context(
            patch(
                "music_links_bot.tg.telegram_gateway.TelegramApiGateway.request",
                refuse_raw,
            )
        )
        app = build_application(
            Settings(
                bot_token="1:fake",
                songlink_api_key=None,
                songlink_user_countries=("US",),
                log_level="INFO",
                admin_chat_id=ADMIN,
                primary_platform=None,
                ui_mode="stonerhand",
            )
        )
        app.bot._request = (FakeTelegram(replay), FakeTelegram(replay))
        await app.initialize()
        try:
            for name in options.scenarios or list(SCENARIOS):
                if name == "publish_flow":
                    await publish_flow(app, replay)
                else:
                    await run(app, replay, name, SCENARIOS[name]())
        finally:
            await app.shutdown()


def parse_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "scenarios",
        nargs="*",
        choices=[*SCENARIOS, "publish_flow", []],
        help="default: every scenario except publish_flow",
    )
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--timeline", action="store_true")
    parser.add_argument("--redis-ms", type=float, default=0.0)
    parser.add_argument("--refuse-player", action="store_true")
    return parser.parse_args(arguments)


if __name__ == "__main__":
    asyncio.run(main(parse_arguments()))
