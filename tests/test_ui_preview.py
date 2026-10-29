"""The offline UI preview (scripts/render_ui_preview.py) still renders from the
current bot code, and every screen its template links to exists."""

import asyncio
import importlib.util
import json
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_ui_preview.py"


def _render_ui_preview():
    spec = importlib.util.spec_from_file_location("render_ui_preview", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _object_literal(html, name):
    return re.search(rf"const {name}=(\{{.*?\}});", html).group(1)


def test_the_preview_renders_every_linked_screen(tmp_path, monkeypatch):
    preview = _render_ui_preview()
    monkeypatch.setattr(preview, "OUTPUT", tmp_path)

    asyncio.run(preview.main())

    html = (tmp_path / "index.html").read_text()
    assert "__SCREEN_DATA__" not in html and "__BRAND_IMAGE__" not in html
    screens = json.loads(_object_literal(html, "screens"))
    titles = re.findall(r"(\w+):'", _object_literal(html, "titles"))
    routes = re.findall(r":'(\w+)'", _object_literal(html, "routes"))
    assert titles and routes
    assert set(titles + routes) <= set(screens)
