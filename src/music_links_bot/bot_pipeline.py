from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DeliveryKind = Literal[
    "tracks",
    "videos",
    "radios",
    "playlists",
    "artists",
    "mixed",
    "empty",
]


@dataclass(slots=True)
class LookupRequest:
    message_text: str
    source_urls: list[str]
    is_private: bool
    lang: str
    user_id: int
    include_channel_button: bool
    include_hashtags: bool
    search_query: str | None = None
    found_via_search: bool = False

    @property
    def prefix_is_noise(self) -> bool:
        return self.found_via_search


def delivery_kind(bundle) -> DeliveryKind:
    if not bundle.item_count:
        return "empty"
    if bundle.content_type_count != 1:
        return "mixed"
    if bundle.tracks:
        return "tracks"
    if bundle.videos:
        return "videos"
    if bundle.radios:
        return "radios"
    if bundle.playlists:
        return "playlists"
    if bundle.artists:
        return "artists"
    return "empty"
