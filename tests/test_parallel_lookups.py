"""Independent provider requests run side by side instead of one after another."""

import asyncio

import httpx

from music_links_bot.providers.search import SearchClient
from music_links_bot.providers.spotify import SpotifyClient

ALBUM = "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy"
PAGE = (
    '<meta property="og:type" content="music.album">'
    '<meta property="og:title" content="Global Warming">'
    '<meta property="music:musician_description" content="Pitbull">'
)


def test_an_album_page_and_its_embed_are_requested_at_once():
    async def run():
        started: list[str] = []
        release = asyncio.Event()

        async def respond(request):
            started.append(request.url.path)
            if len(started) == 2:
                release.set()
            # Neither answer arrives until both requests are on the wire.
            await asyncio.wait_for(release.wait(), timeout=1)
            return httpx.Response(200, text=PAGE)

        named = []
        client = SpotifyClient(on_identified=named.append)
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            match = await client.lookup_release(ALBUM)
        finally:
            await client.aclose()
        return started, match, named

    started, match, named = asyncio.run(run())

    assert sorted(started) == [
        "/album/4aawyAB9vmqN3uQ7FjRGTy",
        "/embed/album/4aawyAB9vmqN3uQ7FjRGTy",
    ]
    assert (match.artist, match.title) == ("Pitbull", "Global Warming")
    # The caller hears the name before the slower details are in.
    assert named == [match]


def test_a_warmed_genre_lookup_is_joined_not_repeated():
    async def run():
        calls = 0

        async def respond(request):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "artistName": "Pitbull",
                            "collectionName": "Global Warming",
                            "primaryGenreName": "Pop",
                        }
                    ]
                },
            )

        client = SearchClient()
        await client._client.aclose()
        client._client = httpx.AsyncClient(
            base_url="https://itunes.apple.com",
            transport=httpx.MockTransport(respond),
        )
        try:
            client.warm_genre("Pitbull", "Global Warming")
            client.warm_genre("Pitbull", "Global Warming")
            first = await client.lookup_genre("Pitbull", "Global Warming")
            second = await client.lookup_genre("Pitbull", "Global Warming")
        finally:
            await client.aclose()
        return calls, first, second

    assert asyncio.run(run()) == (1, "Pop", "Pop")


def _album(**changes):
    from music_links_bot.core.models import TrackMatch

    return TrackMatch(
        **{
            "title": "Global Warming",
            "artist": "Pitbull",
            "links": {"spotify": ALBUM},
            "kind": "album",
            "thumbnail_url": "https://i.scdn.co/image/cover",
            **changes,
        }
    )


def test_a_named_release_starts_its_genre_search_and_its_cover():
    from types import SimpleNamespace

    from music_links_bot.lookup.head_start import cover_head_start, release_identified

    warmed, covers = [], []
    data = {
        "search_client": SimpleNamespace(
            warm_genre=lambda artist, title: warmed.append((artist, title))
        )
    }
    token = cover_head_start.set(covers.append)
    try:
        release_identified(data, _album())
    finally:
        cover_head_start.reset(token)
    # Outside a photo flow, and with the genre already known, nothing starts.
    release_identified(data, _album(genre="Pop"))

    assert warmed == [("Pitbull", "Global Warming")]
    assert len(covers) == 1


class _ChannelLink:
    """A Spotify link posted in the channel, on the stubs of test_bot."""

    def __init__(self, member):
        from unittest.mock import AsyncMock

        from test_bot import ContextStub, ReplaceableChannelMessageStub

        self.lookup_started = asyncio.Event()
        outer = self

        class Songlink:
            async def lookup_track(self, source_url):
                outer.lookup_started.set()
                return _album()

        class Message(ReplaceableChannelMessageStub):
            text = ALBUM

        async def get_chat_member(**_kwargs):
            # The rights answer arrives only once the lookup is under way.
            await asyncio.wait_for(outer.lookup_started.wait(), timeout=1)
            return member

        self.message = Message()
        self.context = ContextStub(songlink_client=Songlink())
        self.context.bot.get_chat_member = get_chat_member
        self.context.bot.send_photo = AsyncMock()

    def post(self):
        from unittest.mock import AsyncMock, patch

        from test_bot import UpdateStub

        from music_links_bot.lookup.bot_lookup_flow import track_lookup_message

        async def run():
            with (
                patch("music_links_bot.lookup.bot_stats.record_post"),
                patch(
                    "music_links_bot.lookup.bot_lookup_flow.warm_cover", AsyncMock()
                ) as cover,
            ):
                await track_lookup_message(UpdateStub(self.message), self.context)
            return cover

        return asyncio.run(run())


def test_a_channel_link_is_looked_up_beside_the_rights_check():
    from types import SimpleNamespace

    link = _ChannelLink(
        SimpleNamespace(
            status="administrator", can_post_messages=True, can_delete_messages=True
        )
    )
    cover = link.post()

    assert link.context.bot.send_photo.await_count == 1
    assert link.message.deleted
    # Its cover was asked for once, for this channel, while the lookup ran.
    assert cover.await_count == 1
    assert cover.await_args.args[1] == "https://i.scdn.co/image/cover"
    assert cover.await_args.kwargs == {"channel_username": "stonerhand"}


def test_without_the_right_to_post_the_found_release_is_not_published():
    from types import SimpleNamespace

    link = _ChannelLink(
        SimpleNamespace(
            status="administrator", can_post_messages=False, can_delete_messages=True
        )
    )
    link.post()

    assert link.context.bot.send_photo.await_count == 0
    assert not link.message.deleted


def test_a_cover_telegram_already_has_is_not_downloaded_again():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from music_links_bot.publishing.publication_service import warm_cover

    context = SimpleNamespace(application=SimpleNamespace(bot_data={}))

    async def run(file_id):
        with (
            patch(
                "music_links_bot.artwork.telegram_media_cache.get_cached_file_id",
                AsyncMock(return_value=file_id),
            ),
            patch(
                "music_links_bot.artwork.branding.build_branded_cover", AsyncMock()
            ) as build,
            patch.dict("os.environ", {"BRAND_PHOTO_FRAME": "1"}),
        ):
            await warm_cover(
                context, "https://i.scdn.co/image/cover", channel_username="@stonerhand"
            )
        return build

    assert asyncio.run(run("known-file-id")).await_count == 0
    build = asyncio.run(run(None))
    assert build.await_count == 1
    assert build.await_args.kwargs["label"] == "@stonerhand"


def test_a_draft_reads_its_templates_and_the_crate_together():
    from unittest.mock import patch

    from test_bot import ContextStub, PrivateMessageStub

    from music_links_bot.lookup import bot_lookup_flow

    waiting: list[str] = []
    together = asyncio.Event()

    async def gated(name, result):
        waiting.append(name)
        if len(waiting) == 3:
            together.set()
        # Read one after another, the first would wait here forever.
        await asyncio.wait_for(together.wait(), timeout=1)
        return result

    async def load_template(_context, target):
        return await gated(f"template {target}", {})

    async def load_crate(_bot_data, _user_id):
        return await gated("crate", [])

    async def run():
        context = ContextStub()
        context.application.bot_data["admin_chat_id"] = 456
        message = PrivateMessageStub()
        with (
            patch.object(bot_lookup_flow, "load_channel_template", load_template),
            patch.object(bot_lookup_flow, "load_crate", load_crate),
        ):
            await bot_lookup_flow._send_track_draft(
                message, context, _album(), user_prefix="", lang="ru", user_id=456
            )
        return message

    message = asyncio.run(run())

    assert sorted(waiting) == ["crate", "template @stonerhand", "template user:456"]
    assert "Global Warming" in message.replies[-1]


def test_an_embed_that_answers_first_names_the_album_before_a_slow_page():
    embed_html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"state":{"data":{"entity":{"type":"album",'
        '"name":"Global Warming","artists":[{"name":"Pitbull"}]}}}}}}</script>'
    )

    async def run():
        named = []
        page_may_answer = asyncio.Event()

        async def respond(request):
            if "/embed/" in request.url.path:
                return httpx.Response(200, text=embed_html)
            await asyncio.wait_for(page_may_answer.wait(), timeout=1)
            return httpx.Response(200, text=PAGE)

        def identified(match):
            named.append((match.artist, match.title))
            page_may_answer.set()  # the page answers only after the embed named it

        client = SpotifyClient(on_identified=identified)
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            match = await client.lookup_release(ALBUM)
        finally:
            await client.aclose()
        return named, match

    named, match = asyncio.run(run())

    # Named by the embed first, then by the page it did not wait for.
    assert named == [("Pitbull", "Global Warming")] * 2
    assert match.title == "Global Warming"


def test_an_owners_photo_draft_prepares_its_cover_for_publishing():
    from unittest.mock import AsyncMock, patch

    from test_bot import ContextStub, PrivateMessageStub

    from music_links_bot.lookup import bot_lookup_flow

    async def run(owner_id):
        context = ContextStub()
        context.application.bot_data["admin_chat_id"] = owner_id
        with patch.object(bot_lookup_flow, "warm_cover", AsyncMock()) as cover:
            await bot_lookup_flow._send_track_draft(
                PrivateMessageStub(),
                context,
                _album(),
                user_prefix="",
                lang="ru",
                user_id=456,
            )
            await asyncio.sleep(0)
        return cover

    owner = asyncio.run(run(456))
    assert owner.await_count == 1
    assert owner.await_args.args[1] == "https://i.scdn.co/image/cover"
    # Someone who cannot publish gets no cover prepared.
    assert asyncio.run(run(123)).await_count == 0
