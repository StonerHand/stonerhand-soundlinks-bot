"""Fail CI when package metadata and production pins drift apart."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 support
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def _requirement_pins() -> set[str]:
    return {
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def main() -> int:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    metadata_pins = set(project["project"]["dependencies"])
    requirement_pins = _requirement_pins()
    if metadata_pins != requirement_pins:
        missing = sorted(requirement_pins - metadata_pins)
        extra = sorted(metadata_pins - requirement_pins)
        raise SystemExit(
            "Dependency pins differ between requirements.txt and pyproject.toml: "
            f"missing={missing}, extra={extra}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
