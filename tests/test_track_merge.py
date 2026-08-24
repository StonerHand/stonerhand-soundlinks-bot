from music_links_bot.models import TrackMatch
from music_links_bot.track_merge import coalesce_equivalent_tracks


def test_same_release_from_multiple_services_becomes_one_card() -> None:
    tracks = [
        TrackMatch(
            artist="Slowdive",
            title="Kisses",
            links={"spotify": "https://open.spotify.com/track/1"},
            thumbnail_url="https://img/cover.jpg",
        ),
        TrackMatch(
            artist="slowdive",
            title="KISSES",
            links={"apple_music": "https://music.apple.com/song/1"},
            page_url="https://song.link/kisses",
        ),
    ]

    merged = coalesce_equivalent_tracks(tracks)

    assert len(merged) == 1
    assert merged[0].artist == "Slowdive"
    assert set(merged[0].links) == {"spotify", "apple_music"}
    assert merged[0].thumbnail_url == "https://img/cover.jpg"
    assert merged[0].page_url == "https://song.link/kisses"


def test_different_releases_keep_original_order() -> None:
    tracks = [
        TrackMatch(title="A", artist="Band", links={"spotify": "https://s/a"}),
        TrackMatch(title="B", artist="Band", links={"spotify": "https://s/b"}),
    ]

    assert [item.title for item in coalesce_equivalent_tracks(tracks)] == ["A", "B"]


def test_same_metadata_with_different_ids_on_one_service_is_not_merged() -> None:
    tracks = [
        TrackMatch(
            title="Song",
            artist="Band",
            links={"spotify": "https://open.spotify.com/track/a"},
        ),
        TrackMatch(
            title="Song",
            artist="Band",
            links={"spotify": "https://open.spotify.com/track/b"},
        ),
    ]

    assert len(coalesce_equivalent_tracks(tracks)) == 2


def test_synthetic_search_link_does_not_block_cross_service_merge() -> None:
    tracks = [
        TrackMatch(
            title="Kisses",
            artist="Slowdive",
            links={"spotify": "https://open.spotify.com/track/abc"},
        ),
        TrackMatch(
            title="Kisses",
            artist="Slowdive",
            links={
                "apple_music": "https://music.apple.com/us/album/kisses/123?i=456",
                "spotify": "https://open.spotify.com/search/Slowdive%20Kisses",
            },
        ),
    ]

    merged = coalesce_equivalent_tracks(tracks)

    assert len(merged) == 1
    assert set(merged[0].links) == {"spotify", "apple_music"}
    assert "/track/" in merged[0].links["spotify"]
