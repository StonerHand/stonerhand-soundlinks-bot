from __future__ import annotations

import ast
from pathlib import Path

from music_links_bot.i18n import STRINGS, validate_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_locales_have_matching_placeholders() -> None:
    assert validate_catalog() == ()


def test_literal_translation_keys_exist() -> None:
    missing: set[str] = set()
    for path in (ROOT / "src" / "music_links_bot").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "get_text":
                continue
            if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
                continue
            key = node.args[1].value
            if isinstance(key, str) and key not in STRINGS:
                missing.add(key)
    assert missing == set()
