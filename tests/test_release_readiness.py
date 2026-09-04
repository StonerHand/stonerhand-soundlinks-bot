import json
import unittest
from pathlib import Path

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

    def test_public_tree_contains_only_product_assets(self) -> None:
        self.assertFalse((ROOT / "skills").exists())
        self.assertFalse((ROOT / ".dockerignore").exists())
        self.assertIn("data/*.json", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    def test_package_metadata_is_release_ready(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]

        self.assertEqual(project["license"], "MIT")
        self.assertEqual(
            project["urls"]["Repository"],
            "https://github.com/StonerHand/stonerhand-soundlinks-bot",
        )
        self.assertEqual(
            metadata["tool"]["setuptools"]["package-data"]["music_links_bot"],
            ["assets/*.gif", "locales/*.json"],
        )
        self.assertTrue((ROOT / "src/music_links_bot/locales/catalog.json").is_file())

    def test_vercel_routes_builds_and_crons_stay_aligned(self) -> None:
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        builds = {entry["src"] for entry in config["builds"]}
        destinations = {entry["dest"] for entry in config["routes"]}
        route_paths = {entry["src"] for entry in config["routes"]}

        self.assertEqual(builds, destinations)
        self.assertTrue(all((ROOT / path).is_file() for path in builds))
        self.assertTrue(
            all(entry["path"] in route_paths for entry in config.get("crons", []))
        )

    def test_ci_enforces_complete_release_gate(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn('python-version: ["3.10", "3.11", "3.12"]', workflow)
        self.assertIn("python -m pytest -q", workflow)
        self.assertIn("python -m ruff check src api tests", workflow)
        self.assertIn("python -m ruff format --check src api tests", workflow)
        self.assertIn("python -m bandit -q -r src api -x tests", workflow)
        self.assertIn("python -m pip_audit", workflow)

    def test_production_canary_has_guarded_instant_rollback(self) -> None:
        workflow = (ROOT / ".github/workflows/production-canary.yml").read_text(
            encoding="utf-8"
        )
        canary = (ROOT / "tests/e2e/production_canary.py").read_text(encoding="utf-8")

        self.assertIn("rollback_guard.py", workflow)
        self.assertIn("vercel@59.5.0 rollback", workflow)
        self.assertIn("VERCEL_TOKEN", workflow)
        self.assertIn("/api/collage?health=1", canary)
        self.assertIn('"collection-collage"', canary)
        self.assertIn('fetch("/api/smoke")', canary)
        self.assertIn('"publication-release-smoke"', canary)

    def test_public_provider_contracts_have_a_scheduled_canary(self) -> None:
        workflow = (ROOT / ".github/workflows/provider-canary.yml").read_text(
            encoding="utf-8"
        )
        script = (ROOT / "tests/e2e/provider_canary.py").read_text(encoding="utf-8")

        self.assertIn('cron: "17 */6 * * *"', workflow)
        self.assertIn("python tests/e2e/provider_canary.py", workflow)
        for provider in (
            "Spotify",
            "MusicBrainz",
            "SoundCloud",
            "YouTube",
            "Apple Music",
            "NTS",
        ):
            self.assertIn(provider, script)


if __name__ == "__main__":
    unittest.main()
