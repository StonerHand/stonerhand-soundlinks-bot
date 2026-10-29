"""The package map in docs/ARCHITECTURE.ru.md matches the real imports."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "package_map.py"


def _package_map():
    spec = importlib.util.spec_from_file_location("package_map", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_package_sits_on_a_layer():
    package_map = _package_map()
    on_layers = {name for row in package_map.layers() for name in row}
    assert on_layers == set(package_map.package_imports())


def test_the_documented_map_is_up_to_date():
    package_map = _package_map()
    text = package_map.DOC.read_text(encoding="utf-8")
    assert package_map.current_block(text) == package_map.render(), (
        "Run: python scripts/package_map.py --write"
    )
