"""Regression tests for the full-code review fixes."""

from datetime import datetime
from zoneinfo import ZoneInfo

from music_links_bot.bot_builder import fit_telegram_html
from music_links_bot.formatter import format_collection_message
from music_links_bot.human_time import parse_human_datetime
from music_links_bot.keyboards import _collection_label, _short_video_title
from music_links_bot.models import TrackMatch
from music_links_bot.publication_budget import sends_as_photo
from music_links_bot.rich_rendering import build_rich_collection_html


def _tracks(*pairs: tuple[str, str]) -> list[TrackMatch]:
    return [TrackMatch(artist=a, title=t, links={}) for a, t in pairs]


def test_cut_never_leaves_an_ellipsis_inside_a_custom_emoji() -> None:
    emoji = '<tg-emoji emoji-id="5368324170671202286">🎧</tg-emoji>'
    cut = fit_telegram_html("<b>" + "a" * 9 + "</b>" + emoji + "b" * 20, 11)

    assert "tg-emoji" not in cut
    assert cut == "<b>aaaaaaaaa</b>…"


def test_user_titles_with_digits_keep_the_count_line() -> None:
    tracks = _tracks(("Sleep", "Dopesmoker"), ("Kyuss", "Gardenia"))

    assert "Подборка · 2 трека" in format_collection_message(tracks, title="Лето 2025")
    generated = format_collection_message(tracks, title="⚠️ Подборка · 2 из 3")
    assert generated.startswith("<b>⚠️ Подборка · 2 из 3</b>")
    assert "2 трека" not in generated


def test_one_rule_decides_photo_or_message() -> None:
    long_text = "x" * 2000

    assert sends_as_photo(as_photo=True, custom_cover=False, text="short")
    assert not sends_as_photo(as_photo=True, custom_cover=False, text=long_text)
    # An uploaded cover cannot be a link preview, so it stays a photo.
    assert sends_as_photo(as_photo=True, custom_cover=True, text=long_text)
    assert not sends_as_photo(as_photo=False, custom_cover=True, text="short")


def test_button_titles_never_end_on_half_an_emoji() -> None:
    label = _collection_label(1, "Hello world fam👨‍👩‍👧 song")

    assert "‍…" not in label
    assert label.endswith("…")


def test_video_noise_keeps_featured_artists_and_versions() -> None:
    assert _short_video_title("Song (feat. MVP)") == "Song (feat. MVP)"
    assert _short_video_title("Track (Audiovisual Session)") == (
        "Track (Audiovisual Session)"
    )
    assert _short_video_title("Song (Official Video)") == "Song"


def test_rich_collection_with_a_generated_title_has_no_stray_heading() -> None:
    tracks = _tracks(("A", "x"), ("B", "y"), ("C", "z"))
    rich = build_rich_collection_html(
        tracks, title="Подборка · 3 релиза", hashtags=None, reply_markup=None
    )

    assert "<b>Подборка</b>" not in rich


def test_relative_times_are_real_durations_across_dst() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    # 01:30 on the night clocks go back (25 October 2026, 03:00 → 02:00).
    now = datetime(2026, 10, 25, 1, 30, tzinfo=berlin).timestamp()

    result = parse_human_datetime(
        "через 2 часа", timezone_name="Europe/Berlin", now=now
    )

    assert result == now + 2 * 3600
