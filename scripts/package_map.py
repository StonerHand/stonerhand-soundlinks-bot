"""Draw the package layers for docs/ARCHITECTURE.ru.md from the real imports.

The layer order comes from the import-linter contract in pyproject.toml, the
arrows and the table from the imports in src/. Run with ``--write`` after
moving code between packages; tests/test_package_map.py fails while the
document is out of date.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "music_links_bot"
DOC = ROOT / "docs" / "ARCHITECTURE.ru.md"
START = "<!-- package-map:start (scripts/package_map.py --write) -->"
END = "<!-- package-map:end -->"


def layers() -> list[list[str]]:
    """Top to bottom; packages on one layer share a row."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    (contract,) = project["tool"]["importlinter"]["contracts"]
    return [
        [name.strip() for name in row.replace("|", ":").split(":")]
        for row in contract["layers"]
    ]


def package_imports() -> dict[str, set[str]]:
    """Which other packages each package imports from, at any depth."""
    uses: dict[str, set[str]] = {}
    for path in sorted(PACKAGE.glob("*/*.py")):
        own = path.parent.name
        found = uses.setdefault(own, set())
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts[0] == "music_links_bot" and len(parts) > 1:
                    found.add(parts[1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[0] == "music_links_bot" and len(parts) > 1:
                        found.add(parts[1])
        found.discard(own)
    return uses


def render() -> str:
    rows = layers()
    rank = {name: index for index, row in enumerate(rows) for name in row}
    uses = package_imports()
    chart = ["```mermaid", "flowchart TB"]
    tops: list[str] = []
    bottoms: list[str] = []
    for index, row in enumerate(rows):
        if len(row) == 1:
            chart.append(f"  {row[0]}")
            tops.append(row[0])
            bottoms.append(row[0])
            continue
        group = f"layer{index}"
        chart.append(f'  subgraph {group}["{" · ".join(row)}"]')
        chart.append("    direction LR")
        chart.extend(f"    {name}" for name in row)
        chart.append("  end")
        tops.append(group)
        bottoms.append(group)
    chart.extend(
        f"  {upper} --> {lower}"
        for upper, lower in zip(bottoms, tops[1:], strict=False)
    )
    chart.append("```")
    table = ["| Раздел | Опирается на |", "|---|---|"]
    for row in rows:
        for name in row:
            used = sorted(uses.get(name, ()), key=lambda other: (-rank[other], other))
            listed = ", ".join(f"`{other}`" for other in used) or "—"
            table.append(f"| `{name}` | {listed} |")
    return "\n".join([START, "", *chart, "", *table, "", END])


def current_block(text: str) -> str:
    start = text.index(START)
    return text[start : text.index(END, start) + len(END)]


def main(argv: list[str]) -> int:
    text = DOC.read_text(encoding="utf-8")
    fresh = render()
    if "--write" in argv:
        DOC.write_text(text.replace(current_block(text), fresh), encoding="utf-8")
        return 0
    print(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
