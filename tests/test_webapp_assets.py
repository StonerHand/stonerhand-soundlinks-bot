from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebAppAssetTests(unittest.TestCase):
    def test_page_loads_split_assets(self) -> None:
        html = (ROOT / "webapp" / "index.html").read_text()
        self.assertIn('href="/webapp/styles.css"', html)
        self.assertIn('src="/webapp/app.js"', html)
        self.assertNotIn("<style>", html)

    def test_mobile_and_accessibility_contracts_are_kept(self) -> None:
        html = (ROOT / "webapp" / "index.html").read_text()
        css = (ROOT / "webapp" / "styles.css").read_text()
        self.assertNotIn("user-scalable=no", html)
        self.assertIn('role="dialog"', html)
        self.assertIn('aria-label="Основная навигация"', html)
        self.assertIn("height: 100dvh", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("min-height: 48px", css)


if __name__ == "__main__":
    unittest.main()
