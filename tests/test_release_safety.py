from __future__ import annotations

import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from api.health import _storage_snapshot, handler, overall_service_ok
from music_links_bot.collection_collage import compose_collection_collage
from music_links_bot.draft_model import normalize_track_draft
from music_links_bot.release_hubs import is_universal_release_url
from music_links_bot.url_utils import (
    apple_music_url_type,
    apple_podcasts_url_type,
    cache_key_for_url,
    direct_platform_links,
    is_nts_url,
    is_platform_destination_url,
    is_soundcloud_url,
    is_supported_music_url,
    is_youtube_video_url,
    spotify_url_type,
)


class ReleaseSafetyTests(unittest.TestCase):
    def test_health_request_uses_only_read_only_telegram_methods(self):
        target = SimpleNamespace(
            send_response=Mock(),
            send_header=Mock(),
            end_headers=Mock(),
            wfile=io.BytesIO(),
        )
        api = Mock(
            return_value={
                "ok": True,
                "result": {"url": "https://bot.example/api/telegram"},
            }
        )
        with (
            patch("api.health._telegram_api", api),
            patch(
                "api.health._storage_snapshot",
                return_value=(
                    {"ok": True, "configured": False},
                    {"configured": False},
                    {},
                ),
            ),
        ):
            handler.do_GET(target)
        self.assertEqual(
            {call.args[0] for call in api.call_args_list}, {"getMe", "getWebhookInfo"}
        )
        self.assertEqual(len(api.call_args_list), 2)
        self.assertTrue(json.loads(target.wfile.getvalue())["ok"])

    def test_storage_health_uses_ping_not_write(self):
        store = SimpleNamespace(
            ping=AsyncMock(return_value=True),
            get_json_required=AsyncMock(return_value=[]),
            get_json=AsyncMock(return_value=None),
            aclose=AsyncMock(),
        )
        with patch("music_links_bot.kvstore.KVStore.from_env", return_value=store):
            redis, queue, _ = _storage_snapshot()
        self.assertTrue(redis["ok"])
        self.assertFalse(queue["worker_stale"])
        store.aclose.assert_awaited_once()
        store.ping.assert_awaited_once()

    def test_corrupt_queue_is_not_reported_as_empty_and_healthy(self):
        store = SimpleNamespace(
            ping=AsyncMock(return_value=True),
            get_json_required=AsyncMock(return_value={"not": "a queue"}),
            get_json=AsyncMock(return_value=None),
            aclose=AsyncMock(),
        )
        with patch("music_links_bot.kvstore.KVStore.from_env", return_value=store):
            redis, _, _ = _storage_snapshot()
        self.assertFalse(redis["ok"])

    def test_ambiguous_delivery_requires_attention_even_without_overdue_jobs(self):
        checks = {"telegram": {"ok": True}, "webhook": {"ok": True}}
        self.assertFalse(
            overall_service_ok(
                checks, {"configured": True, "overdue": 0, "uncertain": 1}
            )
        )

    def test_provider_aliases_survive_but_wrong_hosts_do_not(self):
        self.assertEqual(
            direct_platform_links(
                {
                    "Spotify": "https://open.spotify.com/track/abc",
                    "Apple Music": "https://open.spotify.com/track/wrong",
                }
            ),
            {"spotify": "https://open.spotify.com/track/abc"},
        )

    def test_malformed_urls_cannot_crash_provider_validation(self):
        for url in (
            "https://[broken",
            "https://open.spotify.com:invalid/track/a",
            "https://open.spotify.com/%73earch/test",
            "https://evil@open.spotify.com/track/a",
            "https://open.spotify.com/track/line\nbreak",
            "https://open.spotify.com\\@evil.example/a",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_platform_destination_url("spotify", url))
                self.assertFalse(is_supported_music_url(url))
                self.assertFalse(is_youtube_video_url(url))
                self.assertFalse(is_soundcloud_url(url))
                self.assertFalse(is_nts_url(url))
                self.assertIsNone(spotify_url_type(url))
                self.assertIsNone(apple_music_url_type(url))
                self.assertIsNone(apple_podcasts_url_type(url))
                self.assertIsInstance(cache_key_for_url(url), str)

    def test_universal_button_requires_safe_https_destination(self):
        for url in (
            "javascript://song.link/a",
            "http://song.link/a",
            "https://evil@song.link/a",
            "https://[broken",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_universal_release_url(url))

    def test_corrupt_durable_media_url_is_discarded(self):
        draft = normalize_track_draft(
            {
                "type": "track",
                "item": {
                    "artist": "Artist",
                    "title": "Title",
                    "thumbnail_url": "https://[broken",
                    "links": {},
                },
            }
        )
        self.assertIsNotNone(draft)
        self.assertNotIn("thumbnail_url", draft["item"])

    def test_collage_rejects_oversized_canvas_and_bad_gap(self):
        for size, gap in ((1201, 10), (0, 0), (32, 100), (100, -1)):
            self.assertIsNone(compose_collection_collage([], size=size, gap=gap))

    def test_collage_signature_rejects_untrusted_artwork_host(self):
        from music_links_bot.collection_collage import collection_collage_preview_url
        from music_links_bot.models import TrackMatch

        tracks = [
            TrackMatch(
                artist="Artist",
                title=str(index),
                links={},
                thumbnail_url=f"https://attacker.example/{index}.jpg",
            )
            for index in range(2)
        ]
        self.assertIsNone(
            collection_collage_preview_url(
                tracks,
                base_url="https://bot.example",
                signing_secret="secret",
            )
        )

    def test_collage_rejects_excessive_pixels_before_decoding(self):
        source = Mock(width=4000, height=4000)
        manager = Mock(
            __enter__=Mock(return_value=source), __exit__=Mock(return_value=False)
        )
        with patch("PIL.Image.open", return_value=manager):
            self.assertIsNone(compose_collection_collage([b"image", b"image"]))
        source.thumbnail.assert_not_called()
        source.load.assert_not_called()

    def test_collage_limits_total_bytes_before_opening_any_image(self):
        with (
            patch("music_links_bot.collection_collage.MAX_TOTAL_ARTWORK_BYTES", 4),
            patch("PIL.Image.open") as opener,
        ):
            self.assertIsNone(compose_collection_collage([b"123", b"456"]))
        opener.assert_not_called()

    def test_collage_reduces_each_original_before_retaining_it(self):
        buffer = io.BytesIO()
        with Image.new("RGB", (2000, 2000)) as source:
            source.save(buffer, "PNG")
        from PIL import ImageOps

        transpose = ImageOps.exif_transpose
        sizes = []

        def check_size(image):
            sizes.append(image.size)
            return transpose(image)

        with patch("PIL.ImageOps.exif_transpose", side_effect=check_size):
            self.assertIsNotNone(
                compose_collection_collage([buffer.getvalue()] * 2, size=100, gap=2)
            )
        self.assertEqual(sizes, [(100, 100), (100, 100)])
