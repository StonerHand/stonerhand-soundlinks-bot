import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.kvstore import KVStore
from music_links_bot.search import _extract_release_url, normalize_search_query


class SearchQueryTests(unittest.TestCase):
    def test_normalize_collapses_whitespace_and_trims(self) -> None:
        self.assertEqual(
            normalize_search_query("  black   sabbath\nparanoid "),
            "black sabbath paranoid",
        )

    def test_normalize_rejects_short_and_command_queries(self) -> None:
        self.assertIsNone(normalize_search_query("a"))
        self.assertIsNone(normalize_search_query("/start"))

    def test_normalize_caps_query_length(self) -> None:
        normalized = normalize_search_query("x" * 500)
        self.assertIsNotNone(normalized)
        self.assertLessEqual(len(normalized), 120)

    def test_extract_release_url_prefers_track_url(self) -> None:
        payload = {
            "results": [
                {"collectionViewUrl": "https://music.apple.com/album/1"},
                {"trackViewUrl": "https://music.apple.com/track/2"},
            ]
        }

        self.assertEqual(
            _extract_release_url(payload),
            "https://music.apple.com/album/1",
        )

    def test_extract_release_url_handles_malformed_payloads(self) -> None:
        self.assertIsNone(_extract_release_url(None))
        self.assertIsNone(_extract_release_url({"results": "nope"}))
        self.assertIsNone(_extract_release_url({"results": [{"trackViewUrl": 5}]}))


class KVStoreTests(unittest.TestCase):
    def test_from_env_returns_none_without_credentials(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(KVStore.from_env())

    def test_from_env_accepts_vercel_kv_aliases(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(
            os.environ,
            {
                "KV_REST_API_URL": "https://kv.example",
                "KV_REST_API_TOKEN": "token",
            },
            clear=True,
        ):
            store = KVStore.from_env()
            self.assertIsNotNone(store)


if __name__ == "__main__":
    unittest.main()
