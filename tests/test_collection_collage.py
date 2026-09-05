from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from PIL import Image

from music_links_bot.collection_collage import (
    MAX_PREVIEW_URL_LENGTH,
    collection_collage_preview_url,
    compose_collection_collage,
    decode_collage_payload,
)
from music_links_bot.models import TrackMatch


def _image_bytes(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (200, 300), color).save(output, "PNG")
    return output.getvalue()


class CollectionCollageTests(unittest.TestCase):
    def test_signed_preview_url_round_trips_two_to_six_covers(self) -> None:
        tracks = [
            TrackMatch(
                title=str(index),
                artist="Artist",
                links={},
                thumbnail_url=f"https://i.scdn.co/{index}.jpg",
            )
            for index in range(6)
        ]

        url = collection_collage_preview_url(
            tracks,
            base_url="https://bot.example/custom/path",
            signing_secret="secret",
        )

        self.assertIsNotNone(url)
        assert url is not None
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/api/collage")
        self.assertEqual(
            decode_collage_payload(
                query["p"][0],
                query["s"][0],
                signing_secret="secret",
            ),
            [track.thumbnail_url for track in tracks],
        )
        self.assertLessEqual(len(url), MAX_PREVIEW_URL_LENGTH)

    def test_repeated_provider_prefixes_are_compressed_for_telegram_url_limit(
        self,
    ) -> None:
        tracks = [
            TrackMatch(
                title=str(index),
                artist="Artist",
                links={},
                thumbnail_url=(
                    "https://i.scdn.co/image/"
                    + f"ab67616d0000b273{'a' * 120}{index}"
                    + "?width=1200&height=1200"
                ),
            )
            for index in range(6)
        ]

        url = collection_collage_preview_url(
            tracks,
            base_url="https://bot.example",
            signing_secret="secret",
        )

        self.assertIsNotNone(url)
        assert url is not None
        self.assertLessEqual(len(url), MAX_PREVIEW_URL_LENGTH)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(
            decode_collage_payload(
                query["p"][0],
                query["s"][0],
                signing_secret="secret",
            ),
            [track.thumbnail_url for track in tracks],
        )

    def test_preview_falls_back_when_collage_would_repeat_one_cover(self) -> None:
        tracks = [
            TrackMatch(
                title=str(index),
                artist="Blur",
                links={},
                thumbnail_url="https://i.scdn.co/shared.jpg",
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

    def test_preview_can_be_disabled_without_a_deploy(self) -> None:
        tracks = [
            TrackMatch(
                title=str(index),
                artist="Artist",
                links={},
                thumbnail_url=f"https://i.scdn.co/{index}.jpg",
            )
            for index in range(2)
        ]

        with patch.dict(os.environ, {"COLLECTION_COLLAGE_ENABLED": "0"}, clear=True):
            self.assertIsNone(
                collection_collage_preview_url(
                    tracks,
                    base_url="https://bot.example",
                    signing_secret="secret",
                )
            )

    def test_payload_rejects_tampering_and_private_sources(self) -> None:
        tracks = [
            TrackMatch(
                title="One",
                artist="A",
                links={},
                thumbnail_url="https://i.scdn.co/1.jpg",
            ),
            TrackMatch(
                title="Two",
                artist="B",
                links={},
                thumbnail_url="https://i.scdn.co/2.jpg",
            ),
        ]
        url = collection_collage_preview_url(
            tracks,
            base_url="https://bot.example",
            signing_secret="secret",
        )
        assert url is not None
        query = parse_qs(urlparse(url).query)

        self.assertIsNone(
            decode_collage_payload(
                query["p"][0],
                query["s"][0] + "x",
                signing_secret="secret",
            )
        )
        unsafe = [
            TrackMatch(
                title="One",
                artist="A",
                links={},
                thumbnail_url="https://127.0.0.1/1.jpg",
            ),
            tracks[1],
        ]
        self.assertIsNone(
            collection_collage_preview_url(
                unsafe,
                base_url="https://bot.example",
                signing_secret="secret",
            )
        )

    def test_three_cover_layout_is_square_and_visually_stable(self) -> None:
        collage = compose_collection_collage(
            [
                _image_bytes((240, 20, 20)),
                _image_bytes((20, 240, 20)),
                _image_bytes((20, 20, 240)),
            ],
            size=600,
            gap=10,
        )

        self.assertIsNotNone(collage)
        assert collage is not None
        image = Image.open(io.BytesIO(collage))
        self.assertEqual(image.format, "JPEG")
        self.assertEqual(image.size, (600, 600))
        self.assertGreater(image.getpixel((100, 300))[0], 180)
        self.assertGreater(image.getpixel((450, 100))[1], 180)
        self.assertGreater(image.getpixel((450, 500))[2], 180)

    def test_six_cover_layout_uses_every_tile_in_three_by_two_grid(self) -> None:
        colors = [
            (240, 20, 20),
            (20, 240, 20),
            (20, 20, 240),
            (240, 240, 20),
            (240, 20, 240),
            (20, 240, 240),
        ]

        collage = compose_collection_collage(
            [_image_bytes(color) for color in colors],
            size=600,
            gap=12,
        )

        self.assertIsNotNone(collage)
        assert collage is not None
        image = Image.open(io.BytesIO(collage))
        samples = [
            image.getpixel((100, 140)),
            image.getpixel((300, 140)),
            image.getpixel((500, 140)),
            image.getpixel((100, 460)),
            image.getpixel((300, 460)),
            image.getpixel((500, 460)),
        ]
        for sample, expected in zip(samples, colors, strict=True):
            self.assertLess(
                sum(abs(a - b) for a, b in zip(sample, expected, strict=True)),
                80,
            )
