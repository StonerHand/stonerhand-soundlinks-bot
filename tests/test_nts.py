import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.nts import build_nts_fallback, parse_nts_metadata


class NTSTests(unittest.TestCase):
    def test_parse_nts_metadata_uses_open_graph_title(self) -> None:
        radio = parse_nts_metadata(
            "https://www.nts.live/shows/example",
            """
            <html>
              <head>
                <meta property="og:title" content="Dark Energy w/ Guest | NTS">
                <meta property="og:site_name" content="NTS">
              </head>
            </html>
            """,
        )

        self.assertEqual(radio.title, "Dark Energy w/ Guest")
        self.assertEqual(radio.station, "NTS Radio")
        self.assertEqual(radio.url, "https://www.nts.live/shows/example")

    def test_parse_nts_metadata_falls_back_to_title_tag(self) -> None:
        radio = parse_nts_metadata(
            "https://nts.live/episodes/example",
            "<title>NTS Radio | Guest Mix - NTS Radio</title>",
        )

        self.assertEqual(radio.title, "Guest Mix")
        self.assertEqual(radio.station, "NTS Radio")

    def test_build_nts_fallback_keeps_original_url(self) -> None:
        radio = build_nts_fallback("https://www.nts.live/shows/example")

        self.assertIsNotNone(radio)
        assert radio is not None
        self.assertEqual(radio.title, "NTS Radio")
        self.assertEqual(radio.station, "NTS Radio")
        self.assertEqual(radio.url, "https://www.nts.live/shows/example")

    def test_build_nts_fallback_ignores_other_hosts(self) -> None:
        self.assertIsNone(build_nts_fallback("https://example.com/shows/example"))


if __name__ == "__main__":
    unittest.main()
