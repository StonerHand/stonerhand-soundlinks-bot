from __future__ import annotations

import asyncio
import copy
import re
import time
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram import Chat, Message, Update, User
from telegram.ext import Application

from music_links_bot.bot import _handle_editor_action
from music_links_bot.bot_crate import save_crate, save_crate_title
from music_links_bot.bot_inline import (
    _build_inline_collection_result,
    _build_inline_result,
)
from music_links_bot.bot_pending import consume_pending_input
from music_links_bot.bot_preferences import (
    LocalizedApplication,
    apply_preferences,
    dispatch_preferences,
)
from music_links_bot.bot_release_settings import tag_code
from music_links_bot.bot_runtime import BotRuntime, CallbackAction, UserSession
from music_links_bot.bot_storage import load_draft, store_draft
from music_links_bot.draft_model import new_track_draft, normalize_track_draft
from music_links_bot.formatter import (
    format_collection_message,
    format_track_message,
    format_video_message,
)
from music_links_bot.keyboards import _build_collection_keyboard, _build_link_keyboard
from music_links_bot.lookup_models import LookupBundle, SourceStatus
from music_links_bot.metadata_cleaning import positive_track_count
from music_links_bot.models import TrackMatch, VideoMatch
from music_links_bot.publication_budget import visible_length
from music_links_bot.publication_view import build_publication_view
from music_links_bot.release_preferences import (
    PresentationPreferences,
    current_presentation,
    normalize_annotations,
    normalize_release_tags,
    preferences_from_session,
    presentation_context,
    release_preference_key,
)
from music_links_bot.release_tags import (
    build_auto_hashtags,
    build_collection_hashtags,
    build_mixed_collection_hashtags,
)
from music_links_bot.rich_publications import (
    build_rich_collection_html,
    build_rich_inline_card_html,
)
from music_links_bot.search import _extract_matching_genre
from music_links_bot.spotify import parse_spotify_page
from music_links_bot.track_merge import coalesce_equivalent_tracks


def track(index=1, **changes):
    return replace(
        TrackMatch(
            title=f"Song {index}",
            artist="Artist",
            links={"spotify": f"https://open.spotify.com/track/{index}"},
            page_url=f"https://song.link/s/{index}",
            thumbnail_url="https://i.scdn.co/image/artwork",
        ),
        **changes,
    )


@pytest.mark.parametrize(
    "kind,release_format,tag",
    [
        ("song", None, "#track"),
        ("album", None, "#album"),
        ("album", "ep", "#ep"),
        ("album", "single", "#single"),
        ("album", "compilation", "#compilation"),
        ("album", "soundtrack", "#soundtrack"),
        ("video", None, "#video"),
    ],
)
def test_verified_release_types_keep_mandatory_tag(kind, release_format, tag):
    with presentation_context():
        result = build_auto_hashtags(
            track(
                kind=kind,
                release_format=release_format,
                genre="Rock; Alternative; Music",
            )
        ).split()
    assert result[:2] == ["#stonerhand", tag]
    assert len(result) <= 5 and len(set(result)) == len(result)


def test_collection_genres_require_all_releases_and_types_have_priority():
    tracks = [track(1, genre="Metal"), track(2, genre="Metal", kind="album")]
    with presentation_context():
        assert (
            build_collection_hashtags(tracks)
            == "#stonerhand #collection #track #album #metal"
        )
        for genre in (None, "Pop"):
            assert "#metal" not in build_collection_hashtags(
                [tracks[0], replace(tracks[1], genre=genre)]
            )
        assert "#artist" in build_collection_hashtags([track(1), track(2)])
        assert "#variousartists" not in build_collection_hashtags(
            [track(1, artist="Various Artists"), track(2, artist="Various Artists")]
        )
        mixed = build_mixed_collection_hashtags(
            tracks, has_playlists=True, has_artists=True, has_radios=True
        )
        assert mixed.split()[:2] == ["#stonerhand", "#collection"]
        assert len(mixed.split()) == 5


def test_ambiguous_exact_genre_matches_and_repeated_conflicts_are_omitted():
    payload = {
        "results": [
            {"artistName": "Artist", "trackName": "Song 1", "primaryGenreName": genre}
            for genre in ("Metal", "Pop")
        ]
    }
    assert _extract_matching_genre(payload, artist="Artist", title="Song 1") is None
    payload["results"][1]["trackName"] = "Different release"
    assert _extract_matching_genre(payload, artist="Artist", title="Song 1") == "Metal"
    merged = coalesce_equivalent_tracks(
        [track(1, genre=value) for value in ("Metal", "Pop", "Metal")]
    )
    assert len(merged) == 1 and merged[0].genre is None


def test_soundtrack_example_has_clean_title_and_confirmed_counts():
    title = "Scott Pilgrim vs. the World (Original Motion Picture Soundtrack)"
    release = parse_spotify_page(
        "https://open.spotify.com/album/scott",
        (
            f'<meta property="og:title" content="{title} - Compilation by Various Artists | Spotify">'
            '<meta property="og:type" content="music.album">'
            '<meta property="og:description" content="Various Artists · compilation · 2010 · 19 songs">'
        ),
    )
    assert (
        release.title,
        release.release_format,
        release.track_count,
        release.release_year,
    ) == (title, "soundtrack", 19, "2010")
    text = format_track_message(release)
    assert text.startswith(f"<b>{title}</b>\nVarious Artists")
    assert "Саундтрек · 2010 · 19 треков" in text
    assert "Compilation by" not in text and "#soundtrack" in text
    restored = normalize_track_draft(new_track_draft(release, chat_id=7, lang="ru"))
    assert restored["item"]["track_count"] == 19


@pytest.mark.parametrize(
    "value", [None, "unknown", 0, -1, True, 1.5, 10000, float("inf")]
)
def test_unconfirmed_counts_are_not_displayed(value):
    assert positive_track_count(value) is None


@pytest.mark.parametrize(
    "title",
    [
        "Fool (Remastered 2012)",
        "Collector (Live at Maxidrom 2001)",
        "Original Motion Picture Soundtrack",
    ],
)
def test_meaningful_versions_are_preserved_in_text_and_buttons(title):
    releases = [track(1, title=title), track(2)]
    with presentation_context():
        assert title in format_collection_message(releases)
        assert title in _build_collection_keyboard(releases).inline_keyboard[0][0].text


@pytest.mark.parametrize("layout,rows", [("column", 10), ("auto", 5), ("compact", 5)])
def test_ten_item_layouts_preserve_order_and_destinations(layout, rows):
    tracks = [track(index) for index in range(1, 11)]
    with presentation_context(PresentationPreferences(layout=layout)):
        keyboard = _build_collection_keyboard(tracks)
        text = format_collection_message(tracks)
    assert len(keyboard.inline_keyboard) == rows
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert len(buttons) == 10
    assert [button.url for button in buttons] == [item.page_url for item in tracks]
    for index, button in enumerate(buttons, start=1):
        assert button.text == f"{index} · Song {index}"
        assert f"{index}. Song {index}" in text


def test_long_labels_get_full_width_and_single_primary_action_is_deduplicated():
    with presentation_context(PresentationPreferences(layout="compact")):
        keyboard = _build_collection_keyboard(
            [
                track(1),
                track(2),
                track(3, title="A long song title with a meaningful live version"),
            ]
        )
        assert [len(row) for row in keyboard.inline_keyboard] == [2, 1]
    apple = "https://music.apple.com/us/album/release/123?i=456"
    keyboard = _build_link_keyboard({"appleMusic": apple}, release_page_url=apple)
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert len(buttons) == 1 and buttons[0].text == "⚪ Apple Music"
    keyboard = _build_link_keyboard(
        {"spotify": "https://open.spotify.com/track/1", "appleMusic": apple},
        release_page_url="https://song.link/s/1",
        platform_selection=["spotify", "appleMusic"],
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.text for button in buttons] == [
        "🎧 Слушать трек",
        "🟢 Spotify",
        "⚪ Apple Music",
    ]
    assert sum(button.style == "primary" for button in buttons) == 1
    assert len({button.url for button in buttons}) == 3


def test_maximal_notes_keep_all_ten_entries_within_telegram_limit():
    tracks = [
        track(
            index,
            artist=f"Band {index} " + "🎧" * 100,
            title=f"Track {index} " + "🎧" * 100,
        )
        for index in range(1, 11)
    ]
    annotations = {
        release_preference_key(item): {
            "note": "🎧" * 140,
            "section": "Раздел " + "x" * 60,
        }
        for item in tracks
    }
    with presentation_context(PresentationPreferences(annotations=annotations)):
        text = format_collection_message(tracks, title="Большая подборка")
    assert visible_length(text) <= 4096
    assert re.findall(r"^(\d+)\. ", text, flags=re.M) == [
        str(index) for index in range(1, 11)
    ]
    assert "#collection" in text and "10. <b>Band 10" in text


def test_groups_notes_and_rich_use_same_order_without_html_injection():
    tracks = [
        track(1, artist="A", album_title="First"),
        track(2, artist="B", album_title="Second"),
        track(3, artist="A", album_title="First"),
    ]
    preferences = PresentationPreferences(
        grouping="album",
        annotations={
            release_preference_key(tracks[1]): {"note": "<b>My note</b>", "section": ""}
        },
    )
    with presentation_context(preferences):
        text = format_collection_message(tracks)
        rich = build_rich_collection_html(
            tracks, title="Подборка", hashtags="#collection", reply_markup=None
        )
    assert text.count("<b>First</b>") == 2
    assert "&lt;b&gt;My note&lt;/b&gt;" in text and "&lt;b&gt;My note&lt;/b&gt;" in rich
    assert text.index("1. <b>A") < text.index("2. <b>B") < text.index("3. <b>A")


def test_video_source_is_separate_from_artist_and_cover_choice():
    video = VideoMatch(
        title="Deadушки — Коллекционер (Maxidrom 2001)",
        author="Aleksandr Doronin",
        url="https://www.youtube.com/watch?v=abc",
    )
    text = format_video_message(video)
    assert text.startswith("<b>Deadушки — Коллекционер (Maxidrom 2001)</b>")
    assert "Источник: Aleksandr Doronin" in text
    item = track(
        kind="video",
        title=video.title,
        artist=video.author,
        links={"youtubeMusic": video.url},
    )
    draft = new_track_draft(item, chat_id=7, lang="ru")
    apply_preferences(draft, UserSession(user_id=7, default_artwork="clean"))
    assert not draft["as_photo"]
    rich = build_rich_inline_card_html(item, hashtags="#video", reply_markup=None)
    assert f"<h1>{video.title}</h1>" in rich
    assert "Источник: Aleksandr Doronin" in rich


def test_saved_inputs_are_normalized_and_bounded():
    tags = normalize_release_tags(
        {f"{index:024x}": ["#ROCK", "rock", "<bad>", None] for index in range(100)}
    )
    assert len(tags) == 60 and all(
        value == ["#rock", "#bad"] for value in tags.values()
    )
    assert normalize_annotations({"bad": {"note": "x"}}) == {}


class MemoryKV:
    def __init__(self):
        self.values = {}

    async def get_json(self, key):
        return copy.deepcopy(self.values.get(key))

    async def set_json(self, key, value, **kwargs):
        self.values[key] = copy.deepcopy(value)
        return True


def context_for(runtime, **data):
    return SimpleNamespace(
        application=SimpleNamespace(bot_data={"runtime": runtime, **data}),
        bot=SimpleNamespace(delete_message=AsyncMock()),
    )


def query_for(user_id=7):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, language_code="ru"),
        message=SimpleNamespace(chat_id=user_id),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )


class ReleaseSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_inline_retains_crate_name_notes_and_changes_id_with_layout(self):
        items = [track(1), track(2)]
        sources = [item.links["spotify"] for item in items]
        context = context_for(BotRuntime())
        await save_crate(
            context.application.bot_data, 7, [{"item": asdict(item)} for item in items]
        )
        await save_crate_title(context.application.bot_data, 7, "Моя подборка")
        bundle = LookupBundle(
            items,
            [],
            [],
            [],
            [],
            [],
            [SourceStatus(url, "spotify", "success") for url in sources],
        )
        annotations = {release_preference_key(items[0]): {"note": "Первый трек"}}
        results = []
        with patch(
            "music_links_bot.bot_inline.bot_lookup.resolve_sources",
            new=AsyncMock(return_value=bundle),
        ):
            for layout in ("column", "compact"):
                with presentation_context(
                    PresentationPreferences(layout=layout, annotations=annotations)
                ):
                    result = await _build_inline_collection_result(
                        sources, context, lang="ru", user_id=7
                    )
                assert (
                    "<b>Моя подборка</b>" in result.input_message_content.message_text
                )
                assert "Первый трек" in result.input_message_content.message_text
                results.append(result)
        assert results[0].id != results[1].id

    async def test_inline_native_preview_stays_playable_with_cached_artwork(self):
        item = track()
        context = context_for(
            BotRuntime(), songlink_client=object(), soundcloud_client=object()
        )
        with (
            presentation_context(PresentationPreferences(artwork="native")),
            patch(
                "music_links_bot.bot_inline.bot_lookup._lookup_tracks",
                new=AsyncMock(return_value=([item], [])),
            ),
            patch(
                "music_links_bot.bot_inline.get_cached_file_id",
                new=AsyncMock(return_value="cached-artwork"),
            ),
        ):
            result = await _build_inline_result(item.links["spotify"], context)
        assert (
            result.input_message_content.link_preview_options.url
            == item.links["spotify"]
        )
        assert result.reply_markup is not None

    async def test_settings_and_release_corrections_survive_restart_and_queue_snapshot(
        self,
    ):
        kv = MemoryKV()
        runtime = BotRuntime(kv)
        context = context_for(runtime, kv_store=kv)
        query = query_for()
        item = track(1, genre="Metal")
        with presentation_context():
            for action, value in (
                ("layout", "compact"),
                ("grouping", "album"),
                ("artwork", "clean"),
            ):
                await dispatch_preferences(
                    query, context, CallbackAction("prefs", action, value)
                )
            await store_draft(
                context, "card", new_track_draft(item, chat_id=7, lang="ru")
            )
            await _handle_editor_action(query, context, tag_code("#metal"), "card")
            await _handle_editor_action(query, context, "hp", "card")
            saved_draft = await load_draft(context, "card")
            assert saved_draft["custom_tags"] == ["#stonerhand", "#track"]
        saved = await BotRuntime(kv).get_session(7)
        assert (
            saved.collection_layout,
            saved.collection_grouping,
            saved.default_artwork,
        ) == ("compact", "album", "clean")
        new_draft = new_track_draft(item, chat_id=7, lang="ru")
        apply_preferences(new_draft, saved)
        assert (
            new_draft["custom_tags"] == ["#stonerhand", "#track"]
            and new_draft["as_photo"]
        )
        view = build_publication_view(
            saved_draft, item, context=context, include_channel_button=False
        )
        assert "#metal" not in view.text
        other = new_track_draft(track(2, genre="Metal"), chat_id=7, lang="ru")
        apply_preferences(other, saved)
        assert "custom_tags" not in other
        assert not (await BotRuntime(kv).get_session(8)).release_tags
        with presentation_context(preferences_from_session(saved)):
            await _handle_editor_action(query, context, "hr", "card")
            restored = await load_draft(context, "card")
            assert (
                "#metal"
                in build_publication_view(
                    restored, item, context=context, include_channel_button=False
                ).text
            )
            assert not (await runtime.get_session(7)).release_tags

    async def test_forged_overflow_and_foreign_tag_callbacks_do_not_modify_card(self):
        runtime = BotRuntime()
        context = context_for(runtime)
        draft = new_track_draft(track(1, genre="Metal"), chat_id=7, lang="ru")
        draft["custom_tags"] = ["#stonerhand", "#track", "#one", "#two", "#three"]
        with presentation_context():
            await store_draft(context, "card", draft)
            for user_id, action in (
                (8, tag_code("#track")),
                (7, "hg00000000"),
                (7, tag_code("#metal")),
            ):
                query = query_for(user_id)
                await _handle_editor_action(query, context, action, "card")
                assert (await load_draft(context, "card"))["custom_tags"] == draft[
                    "custom_tags"
                ]
                query.answer.assert_awaited_once()

    async def test_note_reply_targets_release_after_reordering_and_survives_restart(
        self,
    ):
        kv = MemoryKV()
        runtime = BotRuntime(kv)
        context = context_for(runtime, kv_store=kv)
        first, second = track(1), track(2)
        await save_crate(
            context.application.bot_data,
            7,
            [
                {"draft_id": f"card{i}", "item": asdict(item)}
                for i, item in enumerate((second, first))
            ],
        )
        session = await runtime.get_session(7)
        key = release_preference_key(first)
        session.pending_input = {
            "kind": "crate_note",
            "release_key": key,
            "created_at": int(time.time()),
        }
        await runtime.save_session(session)
        message = SimpleNamespace(
            text="Моя заметка <live>",
            caption=None,
            entities=(),
            chat=SimpleNamespace(type="private"),
            chat_id=7,
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=7, language_code="ru"),
        )
        with (
            presentation_context(),
            patch("music_links_bot.bot_pending._restore_crate_screen", new=AsyncMock()),
        ):
            assert await consume_pending_input(
                update, context, retry_lookup=AsyncMock()
            )
        saved = await BotRuntime(kv).get_session(7)
        assert saved.collection_annotations[key]["note"] == "Моя заметка <live>"
        assert not saved.pending_input
        with presentation_context(preferences_from_session(saved)):
            text = format_collection_message([second, first])
        assert "2. Song 1\n   <i>↳ Моя заметка &lt;live&gt;</i>" in text

    async def test_concurrent_updates_isolate_presentation_and_restore_context_on_error(
        self,
    ):
        runtime = BotRuntime()
        session = await runtime.get_session(7)
        session.collection_layout = "compact"
        await runtime.save_session(session)
        app = (
            Application.builder()
            .application_class(LocalizedApplication)
            .token("123:ABC")
            .build()
        )
        app.bot_data["runtime"] = runtime
        values = {}

        async def capture(app, update):
            await asyncio.sleep(0)
            values[update.effective_user.id] = current_presentation.get().layout
            if update.effective_user.id == 7:
                raise ValueError("simulated handler failure")

        def update_for(user_id):
            return Update(
                user_id,
                message=Message(
                    user_id,
                    datetime.now(timezone.utc),
                    Chat(user_id, "private"),
                    from_user=User(user_id, "User", False),
                ),
            )

        with (
            presentation_context(),
            patch.object(Application, "process_update", capture),
        ):
            results = await asyncio.gather(
                *(app.process_update(update_for(user_id)) for user_id in (7, 8)),
                return_exceptions=True,
            )
            assert isinstance(results[0], ValueError)
            assert values == {7: "compact", 8: "column"}
            assert current_presentation.get().layout == "column"
