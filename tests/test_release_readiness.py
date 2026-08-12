from pathlib import Path
import unittest

import music_links_bot

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


class ReleaseReadinessTests(unittest.TestCase):
    def test_version_is_consistent_and_changelog_exists(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        version = project["project"]["version"]
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertEqual(version, music_links_bot.__version__)
        self.assertIn(f"## {version}", changelog)

    def test_public_docs_describe_the_telegram_only_product(self) -> None:
        docs = "\n".join(
            (ROOT / name).read_text(encoding="utf-8")
            for name in ("README.md", "README.ru.md", "ARCHITECTURE.ru.md")
        ).casefold()

        self.assertIn("telegram", docs)
        self.assertNotIn("mini app", docs)
        self.assertNotIn("webapp", docs)


if __name__ == "__main__":
    unittest.main()
