"""Imports inside functions only run when a button is tapped, so check them all."""

import ast
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _project_imports():
    for path in sorted(
        [*ROOT.glob("src/music_links_bot/*.py"), *ROOT.glob("api/*.py")]
    ):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "music_links_bot"
            ):
                yield path.relative_to(ROOT), node


def _resolves(module_name: str, name: str) -> bool:
    if hasattr(importlib.import_module(module_name), name):
        return True
    try:  # ``from music_links_bot import bot`` names a submodule
        importlib.import_module(f"{module_name}.{name}")
    except ImportError:
        return False
    return True


def test_every_project_import_resolves() -> None:
    missing = [
        f"{path}:{node.lineno} {node.module}.{alias.name}"
        for path, node in _project_imports()
        for alias in node.names
        if not _resolves(str(node.module), alias.name)
    ]

    assert missing == []


def _module_aliases(tree: ast.AST) -> dict[str, str]:
    """Local names bound to whole project modules, e.g. ``bot_lookup``."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "music_links_bot":
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"music_links_bot.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("music_links_bot.") and alias.asname:
                    aliases[alias.asname] = alias.name
    return aliases


def test_every_module_attribute_resolves() -> None:
    """``bot_lookup._lookup_tracks`` breaks just like a stale import would."""
    missing = []
    for path in sorted(
        [*ROOT.glob("src/music_links_bot/*.py"), *ROOT.glob("api/*.py")]
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _module_aliases(tree)
        missing.extend(
            f"{path.relative_to(ROOT)}:{node.lineno} {node.value.id}.{node.attr}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
            and not hasattr(importlib.import_module(aliases[node.value.id]), node.attr)
        )

    assert missing == []
