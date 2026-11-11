"""The replay script stays runnable: its updates parse and a scenario plays."""

import asyncio
import importlib.util
import os
from pathlib import Path

from telegram import Update

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay_chats.py"


def _replay():
    spec = importlib.util.spec_from_file_location("replay_chats", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_scenario_is_an_update_telegram_could_send():
    replay = _replay()
    for index, (name, build) in enumerate(replay.SCENARIOS.items()):
        update = Update.de_json({"update_id": index, **build()}, None)
        assert update.effective_chat or update.inline_query, name
    forward = replay.SCENARIOS["forward_yt"]()["message"]
    assert forward["from"]["id"] == 777000 and forward["is_automatic_forward"]
    assert replay.SCENARIOS["group_yt"]()["message"]["from"]["id"] > 0


def test_a_scenario_plays_on_the_full_app_and_leaves_no_trace(capsys):
    replay = _replay()
    before = dict(os.environ)

    asyncio.run(replay.main(replay.parse_arguments(["start", "--full"])))

    printed = capsys.readouterr().out
    assert "== start" in printed
    assert "sendMessage" in printed and "[➕ Новый пост]" in printed
    assert dict(os.environ) == before
