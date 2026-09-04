from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.musicbrainz import (
    MusicBrainzClient,
    _artist_credit_keys,
    _extract_exact_deezer_isrc,
    _extract_exact_entity_id,
    _extract_exact_isrc_spotify_url,
    _extract_spotify_url,
)


class MusicBrainzParsingTests(unittest.TestCase):
    def test_exact_recording_requires_artist_title_and_score(self) -> None:
        payload = {
            "recordings": [
                {
                    "id": "wrong-title",
                    "score": 100,
                    "title": "Be Quiet and Drive",
                    "artist-credit": [{"name": "Deftones"}],
                },
                {
                    "id": "exact",
                    "score": 100,
                    "title": "Rickets",
                    "artist-credit": [{"name": "Deftones"}],
                },
            ]
        }

        self.assertEqual(
            _extract_exact_entity_id(
                payload,
                result_field="recordings",
                artist="Deftones",
                title="Rickets",
            ),
            "exact",
        )
        self.assertIsNone(
            _extract_exact_entity_id(
                payload,
                result_field="recordings",
                artist="Dover",
                title="Rickets",
            )
        )

    def test_joined_artist_credit_matches_full_artist(self) -> None:
        keys = _artist_credit_keys(
            [
                {"name": "Artist One", "joinphrase": " & "},
                {"name": "Artist Two"},
            ]
        )

        self.assertIn("artistoneartisttwo", keys)

    def test_only_expected_spotify_release_type_is_accepted(self) -> None:
        payload = {
            "relations": [
                {"url": {"resource": "https://open.spotify.com/album/album-id"}},
                {
                    "url": {
                        "resource": (
                            "https://open.spotify.com/track/track-id?si=tracking"
                        )
                    }
                },
            ]
        }

        self.assertEqual(
            _extract_spotify_url(payload, expected_type="track"),
            "https://open.spotify.com/track/track-id",
        )
        self.assertEqual(
            _extract_spotify_url(payload, expected_type="album"),
            "https://open.spotify.com/album/album-id",
        )

    def test_deezer_isrc_requires_exact_artist_and_title(self) -> None:
        payload = {
            "data": [
                {
                    "title": "Rickets",
                    "artist": {"name": "Deftones"},
                    "isrc": "USMV29700146",
                }
            ]
        }

        self.assertEqual(
            _extract_exact_deezer_isrc(
                payload,
                artist="Deftones",
                title="Rickets",
            ),
            "USMV29700146",
        )
        self.assertIsNone(
            _extract_exact_deezer_isrc(
                payload,
                artist="Dover",
                title="Rickets",
            )
        )

    def test_isrc_relation_still_requires_exact_recording(self) -> None:
        payload = {
            "recordings": [
                {
                    "title": "Rickets",
                    "artist-credit": [{"artist": {"name": "Deftones"}}],
                    "relations": [
                        {
                            "url": {
                                "resource": (
                                    "https://open.spotify.com/track/"
                                    "7Ca5yTC81P0AtRnNKHKzwJ"
                                )
                            }
                        }
                    ],
                }
            ]
        }

        self.assertEqual(
            _extract_exact_isrc_spotify_url(
                payload,
                artist="Deftones",
                title="Rickets",
            ),
            "https://open.spotify.com/track/7Ca5yTC81P0AtRnNKHKzwJ",
        )
        self.assertIsNone(
            _extract_exact_isrc_spotify_url(
                payload,
                artist="Dover",
                title="Rickets",
            )
        )


class MusicBrainzClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_relation_is_resolved_and_cached(self) -> None:
        class ResponseStub:
            def __init__(self, payload: dict) -> None:
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return self._payload

        class ClientStub:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []
                self.responses = [
                    ResponseStub(
                        {
                            "recordings": [
                                {
                                    "id": "recording-id",
                                    "score": 100,
                                    "title": "Rickets",
                                    "artist-credit": [{"name": "Deftones"}],
                                }
                            ]
                        }
                    ),
                    ResponseStub(
                        {
                            "relations": [
                                {
                                    "url": {
                                        "resource": (
                                            "https://open.spotify.com/track/"
                                            "7Ca5yTC81P0AtRnNKHKzwJ"
                                        )
                                    }
                                }
                            ]
                        }
                    ),
                ]

            async def get(self, path: str, **kwargs):
                self.calls.append((path, kwargs["params"]))
                return self.responses.pop(0)

            async def aclose(self) -> None:
                return None

        client = MusicBrainzClient()
        await client._client.aclose()
        await client._deezer_client.aclose()
        http = ClientStub()
        client._client = http
        client._deezer_client = _DeezerMissStub()
        try:
            with patch(
                "music_links_bot.musicbrainz.MUSICBRAINZ_REQUEST_INTERVAL_SECONDS",
                0,
            ):
                first = await client.lookup_spotify_release("Deftones", "Rickets")
                second = await client.lookup_spotify_release("Deftones", "Rickets")
        finally:
            await client.aclose()

        self.assertEqual(
            first,
            "https://open.spotify.com/track/7Ca5yTC81P0AtRnNKHKzwJ",
        )
        self.assertEqual(second, first)
        self.assertEqual(len(http.calls), 2)
        self.assertEqual(http.calls[0][0], "/recording")
        self.assertEqual(http.calls[1][0], "/recording/recording-id")

    async def test_transient_provider_failure_is_retried_once(self) -> None:
        class ResponseStub:
            def __init__(self, payload: dict, status_code: int = 200) -> None:
                self._payload = payload
                self.status_code = status_code

            def raise_for_status(self) -> None:
                if self.status_code >= 400:
                    request = httpx.Request("GET", "https://musicbrainz.org")
                    response = httpx.Response(self.status_code, request=request)
                    raise httpx.HTTPStatusError(
                        "provider error",
                        request=request,
                        response=response,
                    )

            def json(self) -> dict:
                return self._payload

        class ClientStub:
            def __init__(self) -> None:
                self.calls = 0
                self.responses = [
                    ResponseStub({}, status_code=503),
                    ResponseStub(
                        {
                            "recordings": [
                                {
                                    "id": "recording-id",
                                    "score": 100,
                                    "title": "Rickets",
                                    "artist-credit": [{"name": "Deftones"}],
                                }
                            ]
                        }
                    ),
                    ResponseStub({"relations": []}),
                ]

            async def get(self, *args, **kwargs):
                del args, kwargs
                self.calls += 1
                return self.responses.pop(0)

            async def aclose(self) -> None:
                return None

        client = MusicBrainzClient()
        await client._client.aclose()
        await client._deezer_client.aclose()
        http_client = ClientStub()
        client._client = http_client
        client._deezer_client = _DeezerMissStub()
        try:
            with patch(
                "music_links_bot.musicbrainz.MUSICBRAINZ_REQUEST_INTERVAL_SECONDS",
                0,
            ):
                result = await client.lookup_spotify_release("Deftones", "Rickets")
        finally:
            await client.aclose()

        self.assertIsNone(result)
        self.assertEqual(http_client.calls, 3)

    async def test_deezer_isrc_uses_one_addressed_musicbrainz_request(self) -> None:
        class DeezerResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "data": [
                        {
                            "title": "Rickets",
                            "artist": {"name": "Deftones"},
                            "isrc": "USMV29700146",
                        }
                    ]
                }

        class DeezerClientStub:
            async def get(self, path: str, **kwargs):
                self.request = (path, kwargs["params"])
                return DeezerResponse()

            async def aclose(self) -> None:
                return None

        class MusicBrainzResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "recordings": [
                        {
                            "title": "Rickets",
                            "artist-credit": [{"name": "Deftones"}],
                            "relations": [
                                {
                                    "url": {
                                        "resource": (
                                            "https://open.spotify.com/track/"
                                            "7Ca5yTC81P0AtRnNKHKzwJ"
                                        )
                                    }
                                }
                            ],
                        }
                    ]
                }

        class MusicBrainzHttpStub:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            async def get(self, path: str, **kwargs):
                self.calls.append((path, kwargs["params"]))
                return MusicBrainzResponse()

            async def aclose(self) -> None:
                return None

        client = MusicBrainzClient()
        await client._client.aclose()
        await client._deezer_client.aclose()
        musicbrainz_http = MusicBrainzHttpStub()
        deezer_http = DeezerClientStub()
        client._client = musicbrainz_http
        client._deezer_client = deezer_http
        try:
            with patch(
                "music_links_bot.musicbrainz.MUSICBRAINZ_REQUEST_INTERVAL_SECONDS",
                0,
            ):
                result = await client.lookup_spotify_release("Deftones", "Rickets")
        finally:
            await client.aclose()

        self.assertEqual(
            result,
            "https://open.spotify.com/track/7Ca5yTC81P0AtRnNKHKzwJ",
        )
        self.assertEqual(len(musicbrainz_http.calls), 1)
        self.assertEqual(musicbrainz_http.calls[0][0], "/isrc/USMV29700146")


class _DeezerMissStub:
    async def get(self, *args, **kwargs):
        del args, kwargs

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"data": []}

        return Response()

    async def aclose(self) -> None:
        return None
