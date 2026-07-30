from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from music_links_bot.url_utils import (
    is_nts_url,
    is_playlist_url,
    is_spotify_artist_url,
    is_youtube_video_url,
)


@dataclass(slots=True, frozen=True)
class ProviderAdapter:
    """Declarative URL routing for one external provider."""

    name: str
    accepts: Callable[[str], bool]


DEFAULT_PROVIDER_ADAPTERS = (
    ProviderAdapter("artists", is_spotify_artist_url),
    ProviderAdapter("playlists", is_playlist_url),
    ProviderAdapter("youtube", is_youtube_video_url),
    ProviderAdapter("nts", is_nts_url),
    ProviderAdapter("songlink", lambda _url: True),
)


class ProviderRegistry:
    def __init__(
        self,
        adapters: Iterable[ProviderAdapter] = DEFAULT_PROVIDER_ADAPTERS,
    ) -> None:
        self.adapters = tuple(adapters)
        if not self.adapters:
            raise ValueError("provider registry requires at least one adapter")

    def provider_for(self, source_url: str) -> str:
        for adapter in self.adapters:
            if adapter.accepts(source_url):
                return adapter.name
        return self.adapters[-1].name

    def group(self, source_urls: Iterable[str]) -> dict[str, list[str]]:
        grouped = {adapter.name: [] for adapter in self.adapters}
        for source_url in source_urls:
            grouped[self.provider_for(source_url)].append(source_url)
        return grouped


DEFAULT_PROVIDER_REGISTRY = ProviderRegistry()
