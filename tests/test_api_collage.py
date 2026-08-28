from __future__ import annotations

import unittest
from unittest.mock import patch

from api.collage import MAX_ARTWORK_BYTES, _fetch_artwork


class _Response:
    def __init__(self, body: bytes, content_type: str = "image/jpeg") -> None:
        self.body = body
        self.headers = {
            "content-type": content_type,
            "content-length": str(len(body)),
        }
        self.status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def iter_bytes(self):
        yield self.body


class CollageApiTests(unittest.TestCase):
    def test_fetch_accepts_bounded_image_response(self) -> None:
        with patch("api.collage.httpx.stream", return_value=_Response(b"jpeg")):
            self.assertEqual(_fetch_artwork("https://images.example/1.jpg"), b"jpeg")

    def test_fetch_rejects_non_image_and_oversized_response(self) -> None:
        with patch(
            "api.collage.httpx.stream",
            return_value=_Response(b"html", "text/html"),
        ):
            self.assertIsNone(_fetch_artwork("https://images.example/page"))

        oversized = b"x" * (MAX_ARTWORK_BYTES + 1)
        with patch("api.collage.httpx.stream", return_value=_Response(oversized)):
            self.assertIsNone(_fetch_artwork("https://images.example/large.jpg"))
