"""Post buttons: a lone provider beside the blue hub; optional number keypad."""

from music_links_bot.cards.keyboards import (
    _build_collection_keyboard,
    _build_link_keyboard,
    _build_mixed_collection_keyboard,
)
from music_links_bot.core.models import TrackMatch, VideoMatch
from music_links_bot.core.release_preferences import (
    PresentationPreferences,
    presentation_context,
)


def _tracks(count: int) -> list[TrackMatch]:
    return [
        TrackMatch(
            artist="Artist",
            title=f"Song {index}",
            links={},
            page_url=f"https://song.link/s/{index}",
        )
        for index in range(1, count + 1)
    ]


def _texts(keyboard) -> list[list[str]]:
    return [[button.text for button in row] for row in keyboard.inline_keyboard]


def test_one_provider_shares_the_row_with_the_blue_hub() -> None:
    keyboard = _build_link_keyboard(
        {"spotify": "https://open.spotify.com/track/1"},
        release_page_url="https://song.link/s/1",
    )

    assert _texts(keyboard) == [["🎧 Слушать трек", "🟢 Spotify"]]
    hub, spotify = keyboard.inline_keyboard[0]
    assert hub.style == "primary" and spotify.style is None


def test_three_providers_keep_their_own_row_under_the_hub() -> None:
    keyboard = _build_link_keyboard(
        {
            "spotify": "https://open.spotify.com/track/1",
            "appleMusic": "https://music.apple.com/us/album/x/1?i=2",
            "youtubeMusic": "https://music.youtube.com/watch?v=abc",
        },
        release_page_url="https://song.link/s/1",
    )

    assert _texts(keyboard)[0] == ["🎧 Слушать трек"]
    assert len(_texts(keyboard)[1]) == 3


def test_numbers_only_layout_is_a_balanced_keypad() -> None:
    with presentation_context(PresentationPreferences(layout="numbers")):
        for count, rows in ((2, [2]), (5, [5]), (6, [3, 3]), (8, [4, 4]), (10, [5, 5])):
            keyboard = _build_collection_keyboard(_tracks(count))
            assert [len(row) for row in keyboard.inline_keyboard] == rows
            flat = [b for row in keyboard.inline_keyboard for b in row]
            assert [b.text for b in flat] == [str(i) for i in range(1, count + 1)]
            assert [b.url for b in flat] == [t.page_url for t in _tracks(count)]


def test_videos_keep_their_kind_icon_on_the_keypad() -> None:
    videos = [
        VideoMatch(title="Song (Official Video)", author="A", url="https://youtu.be/1"),
        VideoMatch(title="Song (Live)", author="A", url="https://youtu.be/2"),
    ]
    with presentation_context(PresentationPreferences(layout="numbers")):
        keyboard = _build_mixed_collection_keyboard(_tracks(2), videos)

    assert _texts(keyboard) == [["1", "2", "🎬 3", "🎤 4"]]


def test_default_collection_buttons_keep_titles() -> None:
    with presentation_context():
        keyboard = _build_collection_keyboard(_tracks(2))

    assert _texts(keyboard) == [["1 · Song 1", "2 · Song 2"]]


def test_video_buttons_keep_only_the_song_name() -> None:
    from music_links_bot.cards.keyboards import _short_video_title

    assert _short_video_title("ПОЕХАЛИ – Зарплата / POEXXXALI – Payday") == "Зарплата"
    assert _short_video_title("Sleep - Dragonaut (Official Video)") == "Dragonaut"
    assert _short_video_title("POEXXXALI 3") == "POEXXXALI 3"


def test_long_titles_are_cut_to_fit_two_columns() -> None:
    from music_links_bot.cards.keyboards import _collection_label

    assert (
        _collection_label(8, "Взаимно Познакомиться", "📺")
        == "📺 8 · Взаимно Познаком…"
    )
    assert _collection_label(1, "Заложник Ритма - Демо") == "1 · Заложник Ритма…"
    assert _collection_label(2, "Котик") == "2 · Котик"
