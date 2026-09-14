"""Read-only live lookup-to-card checks. Never sends a Telegram message."""

from __future__ import annotations

import argparse
import asyncio
from types import SimpleNamespace

from music_links_bot.apple_radio import AppleRadioClient
from music_links_bot.artist import ArtistClient
from music_links_bot.bot_inline import _build_inline_result
from music_links_bot.bot_lookup import resolve_sources
from music_links_bot.draft_model import new_track_draft
from music_links_bot.nts import NTSClient
from music_links_bot.playlist import PlaylistClient
from music_links_bot.public_release import PublicReleaseRegionUnavailable
from music_links_bot.publication_contract import require_valid_publication
from music_links_bot.publication_view import (
    build_publication_view,
    publication_contract_from_view,
)
from music_links_bot.search import SearchClient
from music_links_bot.songlink import SonglinkClient
from music_links_bot.soundcloud import SoundCloudClient
from music_links_bot.youtube import YouTubeClient

CASES = {
    "Spotify track": (
        "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
        "Never Gonna Give You Up",
    ),
    "Spotify album": (
        "https://open.spotify.com/album/5Z9iiGl2FcIfa3BMiv6OIw",
        "Whenever You Need Somebody",
    ),
    "Apple Witness": (
        "https://music.apple.com/tr/album/witness/1703729138?i=1703729139",
        "Witness",
    ),
    "Apple Shut Me Up": (
        "https://music.apple.com/tr/album/shut-me-up/411940499?i=411940619",
        "Shut Me Up",
    ),
    "Apple What Do They Know": (
        "https://music.apple.com/tr/album/what-do-they-know/411940499?i=411940907",
        "What Do They Know?",
    ),
    "Deezer short link": (
        "https://link.deezer.com/s/34owmSLTeGPHKvokPhNcA",
        "Calm Down",
    ),
    "Deezer album": ("https://www.deezer.com/album/347960617", "Calm Down"),
    "Tidal track": ("https://tidal.com/track/94560983", "Sounds Good To Me"),
    "Tidal album": ("https://tidal.com/album/94560982", "Sounds Good To Me"),
    "Yandex Music track": ("https://music.yandex.ru/track/21940", "Blue Eyes"),
    "Yandex Music album": ("https://music.yandex.ru/album/2512328", "Музыка Фитнеса"),
    "Bandcamp": ("https://sleep.bandcamp.com/album/dopesmoker", "Dopesmoker"),
    "SoundCloud": (
        "https://soundcloud.com/stoner-hand/ethan-kath-dj-set-park-live-moscow-30062013",
        "Ethan Kath",
    ),
    "YouTube": (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "Never Gonna Give You Up",
    ),
    "YouTube Music": (
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "Never Gonna Give You Up",
    ),
    "NTS": ("https://www.nts.live/shows/guests", "Guest"),
    "Apple Radio": (
        "https://music.apple.com/tr/curator/the-alligator-hour/993270307",
        "The Alligator Hour",
    ),
}


async def verify(*, allow_region_unavailable: bool = False) -> list[str]:
    clients = {
        "songlink_client": SonglinkClient(user_countries=("US",)),
        "search_client": SearchClient(),
        "soundcloud_client": SoundCloudClient(),
        "youtube_client": YouTubeClient(),
        "playlist_client": PlaylistClient(),
        "artist_client": ArtistClient(),
        "nts_client": NTSClient(),
        "apple_radio_client": AppleRadioClient(),
    }
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data=dict(clients)),
        bot=SimpleNamespace(id=1, username="StonerHandBot"),
    )
    failures = []

    async def check(name, source, expected):
        try:
            if name.startswith("Yandex Music"):
                # Distinguish an explicit regional refusal from a broken parser.
                await clients["songlink_client"]._public_release_client.lookup_release(
                    source
                )
            bundle = await resolve_sources(context.application.bot_data, [source])
            if not bundle.is_complete_for([source]):
                raise AssertionError("lookup is incomplete")
            for track in bundle.tracks:
                # The same publication gate that rejected real editor posts.
                view = build_publication_view(
                    new_track_draft(track, chat_id=1, lang="ru"),
                    track,
                    context=context,
                    include_channel_button=False,
                )
                require_valid_publication(publication_contract_from_view(view, track))
                if not view.text:
                    raise AssertionError("empty publication")
            inline = await _build_inline_result(source, context, force_classic=True)
            if inline is None or expected.casefold() not in inline.title.casefold():
                raise AssertionError("inline title is missing or incorrect")
            print(f"OK {name}: lookup, card, inline", flush=True)
        except PublicReleaseRegionUnavailable as exc:
            print(f"UNAVAILABLE {name}: {exc}", flush=True)
            if not allow_region_unavailable:
                failures.append(f"{name}: {exc}")
        except Exception as exc:  # noqa: BLE001 — collect every provider failure.
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"FAIL {failures[-1]}", flush=True)

    try:
        for name, (source, expected) in CASES.items():
            await check(name, source, expected)
        candidates = await clients["search_client"].search_release_candidates(
            "кино - пачка сигарет"
        )
        kino = next(
            (
                c
                for c in candidates
                if c.artist.casefold() in {"kino", "кино"}
                and c.title == "Пачка сигарет"
            ),
            None,
        )
        if kino is None:
            failures.append("Кино text search: exact result missing")
        else:
            await check("Кино text search", kino.url, "Пачка сигарет")
    finally:
        await asyncio.gather(*(client.aclose() for client in clients.values()))
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-region-unavailable",
        action="store_true",
        help="Report explicit regional provider refusals separately from regressions",
    )
    args = parser.parse_args()
    raise SystemExit(
        bool(
            asyncio.run(verify(allow_region_unavailable=args.allow_region_unavailable))
        )
    )
