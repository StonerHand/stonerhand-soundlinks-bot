import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.cache import TTLCache


class TTLCacheTests(unittest.TestCase):
    def test_get_returns_cached_value_before_ttl_expires(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl_seconds=10)

        cache.set("key", "value")

        self.assertEqual(cache.get("key"), "value")

    def test_get_drops_expired_value(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl_seconds=0)

        cache.set("key", "value")

        self.assertIsNone(cache.get("key"))

    def test_set_evicts_oldest_value_when_cache_is_full(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl_seconds=10, max_size=1)

        cache.set("first", "1")
        cache.set("second", "2")

        self.assertIsNone(cache.get("first"))
        self.assertEqual(cache.get("second"), "2")


if __name__ == "__main__":
    unittest.main()
