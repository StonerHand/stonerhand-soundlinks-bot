from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebAppAssetTests(unittest.TestCase):
    def test_page_loads_split_assets(self) -> None:
        html = (ROOT / "webapp" / "index.html").read_text()
        self.assertIn('href="/webapp/styles.css"', html)
        self.assertIn('type="module" src="/webapp/app.js"', html)
        self.assertNotIn("<style>", html)

    def test_modules_and_security_headers_are_deployed(self) -> None:
        import json

        config = json.loads((ROOT / "vercel.json").read_text())
        build_sources = {item["src"] for item in config["builds"]}
        route_sources = {item["src"] for item in config["routes"]}
        self.assertIn("webapp/api-client.js", build_sources)
        self.assertIn("webapp/cloud-storage.js", build_sources)
        self.assertIn("/webapp/api-client.js", route_sources)
        app_route = next(item for item in config["routes"] if item["src"] == "/app")
        self.assertIn("Content-Security-Policy", app_route["headers"])
        self.assertIn("frame-ancestors", app_route["headers"]["Content-Security-Policy"])

    def test_mobile_and_accessibility_contracts_are_kept(self) -> None:
        html = (ROOT / "webapp" / "index.html").read_text()
        css = (ROOT / "webapp" / "styles.css").read_text()
        self.assertNotIn("user-scalable=no", html)
        self.assertIn('role="dialog"', html)
        self.assertIn('aria-label="Основная навигация"', html)
        self.assertIn("height: 100dvh", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("min-height: 48px", css)

    def test_editorial_redesign_contracts_are_present(self) -> None:
        html = (ROOT / "webapp" / "index.html").read_text()
        css = (ROOT / "webapp" / "styles.css").read_text()
        js = (ROOT / "webapp" / "app.js").read_text()
        for element_id in (
            "home-title",
            "search-go",
            "paste-btn",
            "q-inline",
            "result-readiness",
            "format-preview",
            "crate-cover",
            "create-tab",
            "publish-sheet",
            "success-screen",
            "cp-vinyl",
            "coach-skip",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertNotIn('data-tab="stats"', html)
        self.assertIn("@media (max-width:360px)", css)
        self.assertIn("bindSwipe", js)
        self.assertIn("showSuccess", js)

    def test_html_ids_are_unique(self) -> None:
        import re

        html = (ROOT / "webapp" / "index.html").read_text()
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
