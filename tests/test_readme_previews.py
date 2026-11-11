"""The README screens are drawn from the bot's real output and stay current."""

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "readme_previews.py"


def _previews():
    spec = importlib.util.spec_from_file_location("readme_previews", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Its dataclass looks the module up by name while the class is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_screens_show_what_the_bot_sends(tmp_path):
    previews = _previews()
    previews.main(["--html", str(tmp_path)])

    draft = previews.draft_card()
    # The main action leads, and a plain draft has no header of its own.
    assert draft.rows[0] == [("📣 Опубликовать", True)]
    assert "Черновик" not in draft.text
    post = previews.channel_post()
    assert post.rows[0] == [("💿 Слушать альбом", True)]
    assert len(post.rows[1]) == 3
    assert "Kyuss — Gardenia" in (tmp_path / "collection.html").read_text("utf-8")
    for screen in (build() for build in previews.SCREENS.values()):
        assert (previews.ART / screen.art).is_file()


def test_the_pictures_were_drawn_from_the_current_bot():
    previews = _previews()
    recorded = json.loads(previews.RECORD.read_text(encoding="utf-8"))
    assert recorded == previews.fingerprints(), (
        "The bot's cards changed. Run: python scripts/readme_previews.py"
    )
    for name in previews.SCREENS:
        assert (previews.ASSETS / f"{name}.png").is_file()
