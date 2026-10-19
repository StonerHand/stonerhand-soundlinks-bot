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
