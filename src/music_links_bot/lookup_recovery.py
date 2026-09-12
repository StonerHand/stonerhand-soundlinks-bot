"""Retain successful source results while retrying only missing collection items."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict

from music_links_bot.lookup_models import LookupBundle, SourceStatus, bundle_from_cache
from music_links_bot.url_utils import cache_key_for_url

completed_sources: ContextVar[dict | None] = ContextVar(
    "completed_lookup_sources", default=None
)
FIELDS = ("tracks", "videos", "radios", "playlists", "artists")


def capture_sources(bundle):
    if bundle.source_results:
        return bundle.source_results
    result = {}
    music = iter(bundle.tracks)
    for status in bundle.statuses:
        if status.state != "success":
            continue
        key = cache_key_for_url(status.source_url)
        selected = None
        for field in FIELDS[1:]:
            match = next(
                (
                    item
                    for item in getattr(bundle, field)
                    if cache_key_for_url(item.url) == key
                ),
                None,
            )
            if match is not None:
                selected = (field, match)
                break
        if selected is None and status.provider in {
            "songlink",
            "spotify",
            "soundcloud",
            "appleMusic",
            "apple_music",
            "music",
        }:
            item = next(music, None)
            if item is not None:
                selected = ("tracks", item)
        if selected is not None:
            field, item = selected
            result[key] = {field: [asdict(item)], "statuses": [asdict(status)]}
    return result


def restore_source(payload, url):
    if not isinstance(payload, dict):
        return None
    bundle = bundle_from_cache(payload)
    if bundle is not None and bundle.is_complete_for([url]):
        return bundle
    return None


def merge_recovered(urls, completed, fresh):
    fresh_by_source = capture_sources(fresh)
    statuses = {cache_key_for_url(s.source_url): s for s in fresh.statuses}
    result = LookupBundle([], [], [], [], [], [])
    for url in urls:
        key = cache_key_for_url(url)
        source = restore_source(completed.get(key), url) or restore_source(
            fresh_by_source.get(key), url
        )
        if source is not None:
            for field in FIELDS:
                getattr(result, field).extend(getattr(source, field))
            result.statuses.extend(source.statuses)
        else:
            status = statuses.get(key) or SourceStatus(
                url, "songlink", "unavailable", retryable=True
            )
            result.statuses.append(status)
            if status.state == "unavailable":
                result.unavailable_urls.append(url)
    return result
