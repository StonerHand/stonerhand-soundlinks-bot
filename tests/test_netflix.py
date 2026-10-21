"""Netflix film and series cards: parsing, trailer, soundtrack and delivery."""

import json
import unittest
from unittest.mock import patch

import httpx

from music_links_bot.formatter import format_title_message
from music_links_bot.i18n import language_context
from music_links_bot.keyboards import _build_title_keyboard
from music_links_bot.models import TitleMatch
from music_links_bot.netflix import (
    NetflixClient,
    NetflixLookupError,
    NetflixUnavailableError,
    parse_title_page,
    pick_soundtrack,
    pick_trailer,
)
from music_links_bot.publication_contract import (
    RenderedPublication,
    validate_rendered_publication,
)
from music_links_bot.url_utils import extract_supported_urls, netflix_title_id

SERIES_URL = "https://www.netflix.com/id-en/title/81054853"
FILM_URL = "https://www.netflix.com/title/80175798"
HERO = "https://occ-0-1.1.nflxso.net/dnm/api/v6/x/hero.jpg?r=dab"


def _page(title_id: int, *, title: str, kind: str, extra: str = "") -> str:
    """A tiny stand-in for a public title page, escaped the way Netflix does."""
    data = (
        '"heroImage":{"url":"' + HERO + '"},"copy":{"title":"' + title + '",'
        '"synopsis":"A story."},"contentAdvisory":{"certificationValue":"18+"},'
        '"latestYear":2026,"primaryGenres":{"edges":[{"node":{"genreId":1,'
        '"name":"Anime"}}]},' + extra + '"isOriginal":true,"type":"' + kind + '",'
        '"videoId":' + str(title_id) + "},"
        # A recommendation of another kind must not change this title's kind.
        '"videos":[{"__typename":"Movie","type":"Movie","videoId":1234567}]'
    )
    escaped = data.replace(" ", "\\x20").replace("/", "\\x2F")
    return (
        f"<html><body><h1 class='title'>{title}</h1>"
        f"<script>netflix.reactContext = {{{escaped}}};</script></body></html>"
    )


SERIES_PAGE = _page(
    81054853,
    title="Cyberpunk: Edgerunners",
    kind="Show",
    extra='"numSeasonsLabel":"2 Seasons",',
)
FILM_PAGE = _page(80175798, title="The Irishman", kind="Movie")

ITUNES = {
    "results": [
        {"collectionId": 1, "collectionName": "Cyberpunk Edgerunners - Single"},
        {
            "collectionId": 1711647903,
            "collectionName": "Cyberpunk: Edgerunners (Original Series Soundtrack)",
        },
    ]
}


def _video(video_id: str, title: str, channel: str = "Netflix") -> dict:
    return {
        "videoRenderer": {
            "videoId": video_id,
            "title": {"runs": [{"text": title}]},
            "ownerText": {"runs": [{"text": channel}]},
        }
    }


YOUTUBE = {
    "contents": [
        _video("aaaaaaaaaaa", "Cyberpunk: Edgerunners | Official Teaser | Netflix"),
        _video("bbbbbbbbbbb", "Cyberpunk Edgerunners trailer reaction", "Fan Club"),
        _video("ccccccccccc", "Cyberpunk: Edgerunners | Official NSFW Trailer"),
        _video("ddddddddddd", "Cyberpunk: Edgerunners | Official Trailer | Netflix"),
    ]
}


class LinkTests(unittest.TestCase):
    def test_title_pages_are_supported_and_other_pages_are_not(self) -> None:
        self.assertEqual(netflix_title_id(SERIES_URL), "81054853")
        self.assertEqual(netflix_title_id(FILM_URL + "?trkid=1"), "80175798")
        for url in (
            "https://www.netflix.com/browse",
            "https://www.netflix.com/watch/81008957",
            "https://netflix.example.com/title/81054853",
        ):
            with self.subTest(url=url):
                self.assertIsNone(netflix_title_id(url))
        self.assertEqual(
            extract_supported_urls(f"смотри {SERIES_URL} и netflix.com/browse"),
            [SERIES_URL],
        )


class ParsingTests(unittest.TestCase):
    def test_series_page(self) -> None:
        card = parse_title_page(SERIES_PAGE, SERIES_URL)

        self.assertIsNotNone(card)
        assert card is not None
        self.assertEqual(card.title, "Cyberpunk: Edgerunners")
        self.assertEqual((card.kind, card.seasons), ("series", 2))
        self.assertEqual((card.genre, card.rating), ("Anime", "18+"))
        self.assertEqual(card.image_url, HERO)
        # The card keeps the user's link (status accounting matches on it)
        # and offers a region-free page to watch.
        self.assertEqual(card.url, SERIES_URL)
        self.assertEqual(card.watch_url, "https://www.netflix.com/title/81054853")

    def test_film_page(self) -> None:
        card = parse_title_page(FILM_PAGE, FILM_URL)

        assert card is not None
        self.assertEqual((card.kind, card.year, card.seasons), ("film", 2026, None))

    def test_a_login_wall_or_changed_page_is_no_card(self) -> None:
        self.assertIsNone(parse_title_page("<html>Netflix</html>", SERIES_URL))
        self.assertIsNone(parse_title_page(SERIES_PAGE, "https://example.com/x"))

    def test_only_the_official_soundtrack_is_used(self) -> None:
        url = pick_soundtrack(ITUNES["results"], "Cyberpunk: Edgerunners")

        self.assertEqual(url, "https://album.link/i/1711647903")
        self.assertIsNone(pick_soundtrack(ITUNES["results"][:1], "Cyberpunk"))
        self.assertIsNone(pick_soundtrack(None, "Cyberpunk"))

    def test_trailer_is_official_clean_and_about_this_title(self) -> None:
        self.assertEqual(
            pick_trailer(YOUTUBE, "Cyberpunk: Edgerunners"),
            "https://www.youtube.com/watch?v=ddddddddddd",
        )
        self.assertIsNone(pick_trailer(YOUTUBE, "The Irishman"))
        self.assertIsNone(pick_trailer({"contents": [YOUTUBE["contents"][1]]}, "x"))


def _card(**overrides) -> TitleMatch:
    values = {
        "title": "Cyberpunk: Edgerunners",
        "url": SERIES_URL,
        "watch_url": "https://www.netflix.com/title/81054853",
        "seasons": 2,
        "genre": "Anime",
        "rating": "18+",
        "image_url": HERO,
        "trailer_url": "https://www.youtube.com/watch?v=ddddddddddd",
        "soundtrack_url": "https://album.link/i/1711647903",
    }
    return TitleMatch(**{**values, **overrides})


class CardTests(unittest.TestCase):
    def test_series_card_text_in_both_languages(self) -> None:
        with language_context("ru"):
            ru = format_title_message(_card())
        with language_context("en"):
            en = format_title_message(_card(kind="film", year=2019, seasons=None))

        self.assertEqual(
            ru,
            "<b>Cyberpunk: Edgerunners</b>\n\n"
            "📺 Сериал · Netflix · 2 сезона · Аниме · 18+\n\n"
            "#stonerhand #series #netflix",
        )
        self.assertIn("🎬 Film · Netflix · 2019 · Anime · 18+", en)
        self.assertTrue(en.endswith("#stonerhand #film #netflix"))

    def test_keyboard_puts_netflix_first_and_extras_together(self) -> None:
        with language_context("ru"):
            full = _build_title_keyboard(_card()).inline_keyboard
            bare = _build_title_keyboard(
                _card(trailer_url=None, soundtrack_url=None)
            ).inline_keyboard

        self.assertEqual(
            [[button.text for button in row] for row in full],
            [["🎬 Смотреть на Netflix"], ["▶️ Трейлер", "🎧 Саундтрек"]],
        )
        self.assertEqual(len(bare), 1)

    def test_card_passes_the_publication_contract(self) -> None:
        card = _card()
        result = validate_rendered_publication(
            RenderedPublication(
                text=format_title_message(card),
                keyboard=_build_title_keyboard(card),
                preview_url=card.image_url,
                source_urls=(card.url,),
                content_kind="title",
            )
        )

        self.assertEqual(result.issues, ())


def _transport(*, netflix_status: int = 200, youtube_ok: bool = True):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "www.netflix.com":
            return httpx.Response(netflix_status, text=SERIES_PAGE)
        if request.url.host == "www.youtube.com":
            if not youtube_ok:
                return httpx.Response(500)
            return httpx.Response(
                200,
                text=f"<script>var ytInitialData = {json.dumps(YOUTUBE)};</script>",
            )
        return httpx.Response(200, json=ITUNES)

    return httpx.MockTransport(handler), calls


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def _client(self, transport) -> NetflixClient:
        client = NetflixClient()
        await client.aclose()
        client._client = httpx.AsyncClient(transport=transport)
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_one_lookup_fills_the_whole_card_and_is_cached(self) -> None:
        transport, calls = _transport()
        client = await self._client(transport)

        card = await client.lookup_title(SERIES_URL)
        again = await client.lookup_title(SERIES_URL)

        self.assertIs(card, again)
        self.assertEqual(
            card.trailer_url, "https://www.youtube.com/watch?v=ddddddddddd"
        )
        self.assertEqual(card.soundtrack_url, "https://album.link/i/1711647903")
        self.assertEqual(len(calls), 3)

    async def test_a_refusal_is_an_outage_and_a_404_is_a_missing_title(self) -> None:
        for status, error in (
            (403, NetflixUnavailableError),
            (404, NetflixLookupError),
        ):
            with self.subTest(status=status):
                transport, _ = _transport(netflix_status=status)
                client = await self._client(transport)

                with self.assertRaises(NetflixLookupError) as caught:
                    await client.lookup_title(SERIES_URL)

                self.assertIs(type(caught.exception), error)

    async def test_a_broken_youtube_only_drops_the_trailer(self) -> None:
        transport, _ = _transport(youtube_ok=False)
        client = await self._client(transport)

        card = await client.lookup_title(SERIES_URL)

        self.assertIsNone(card.trailer_url)
        self.assertIsNotNone(card.soundtrack_url)


class _NetflixStub:
    async def lookup_title(self, url: str) -> TitleMatch:
        return _card(url=url)


class _BlockedNetflix:
    async def lookup_title(self, url: str) -> TitleMatch:
        raise NetflixUnavailableError("403")


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def _lookup(self, client, text: str = SERIES_URL):
        from test_bot import ContextStub, PrivateMessageStub, UpdateStub

        from music_links_bot.bot_lookup_flow import track_lookup_message

        class NetflixMessage(PrivateMessageStub):
            pass

        NetflixMessage.text = text
        message = NetflixMessage()
        context = ContextStub()
        context.application.bot_data["netflix_client"] = client
        with patch("music_links_bot.bot_stats.record_matches"):
            await track_lookup_message(UpdateStub(message), context)
        return message

    async def test_a_blocked_netflix_is_named_and_retryable(self) -> None:
        message = await self._lookup(_BlockedNetflix())

        reply = message.replies[-1]
        self.assertIn("Netflix", reply)
        self.assertNotIn("Song.link", reply)
        markup = message.reply_kwargs[-1]["reply_markup"]
        callbacks = [
            str(button.callback_data)
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertTrue(any("|retry|" in data or "retry" in data for data in callbacks))

    async def test_a_netflix_link_in_chat_becomes_the_card(self) -> None:
        from test_bot import ContextStub, PrivateMessageStub, UpdateStub

        from music_links_bot.bot_lookup_flow import track_lookup_message

        class NetflixMessage(PrivateMessageStub):
            text = f"Лучший саундтрек года {SERIES_URL}"

        message = NetflixMessage()
        context = ContextStub()
        context.application.bot_data["netflix_client"] = _NetflixStub()
        with patch("music_links_bot.bot_stats.record_matches"):
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        card = message.replies[0]
        self.assertIn("<b>Cyberpunk: Edgerunners</b>", card)
        self.assertIn("Лучший саундтрек года", card)
        markup = message.reply_kwargs[0]["reply_markup"]
        labels = [button.text for row in markup.inline_keyboard for button in row]
        self.assertEqual(
            labels[:3], ["🎬 Смотреть на Netflix", "▶️ Трейлер", "🎧 Саундтрек"]
        )
        self.assertIn(HERO, str(message.reply_kwargs[0]["link_preview_options"].url))

    async def test_sharing_a_card_rebuilds_it_inline(self) -> None:
        from test_bot import ContextStub

        from music_links_bot.bot_inline import _build_inline_result

        context = ContextStub()
        context.application.bot_data["netflix_client"] = _NetflixStub()

        result = await _build_inline_result(SERIES_URL, context)

        assert result is not None
        self.assertEqual(result.title, "Cyberpunk: Edgerunners")
        self.assertIn("Netflix", result.input_message_content.message_text)


if __name__ == "__main__":
    unittest.main()
