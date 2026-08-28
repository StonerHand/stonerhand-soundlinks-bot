from __future__ import annotations

import io
import unittest
from urllib.parse import parse_qs, urlparse

from PIL import Image

from music_links_bot.collection_collage import (
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
    def test_signed_preview_url_round_trips_two_to_four_covers(self) -> None:
        tracks = [
            TrackMatch(
                title=str(index),
                artist="Artist",
                links={},
                thumbnail_url=f"https://images.example/{index}.jpg",
            )
            for index in range(4)
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

    def test_preview_falls_back_when_collage_would_repeat_one_cover(self) -> None:
        tracks = [
            TrackMatch(
                title=str(index),
                artist="Blur",
                links={},
                thumbnail_url="https://images.example/shared.jpg",
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

    def test_payload_rejects_tampering_and_private_sources(self) -> None:
        tracks = [
            TrackMatch(
                title="One",
                artist="A",
                links={},
                thumbnail_url="https://images.example/1.jpg",
            ),
            TrackMatch(
                title="Two",
                artist="B",
                links={},
                thumbnail_url="https://images.example/2.jpg",
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
