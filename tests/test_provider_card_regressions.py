import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

import httpx
import pytest
from test_bot import (
    ContextStub,
    PrivateMessageStub,
    ReplaceableChannelMessageStub,
    UpdateStub,
)
from test_card_details import run_async
from test_release_card import sample

from music_links_bot.bot import track_lookup_message
from music_links_bot.bot_inline import _build_inline_result
from music_links_bot.deezer import DeezerClient, DeezerLookupError
from music_links_bot.draft_model import new_track_draft
from music_links_bot.formatter import format_track_message
from music_links_bot.public_release import (
    PublicReleaseClient,
    PublicReleaseError,
    PublicReleaseRegionUnavailable,
    parse_public_release,
)
from music_links_bot.publication_contract import (
    RenderedPublication,
    validate_rendered_publication,
)
from music_links_bot.publication_service import PublicationService
from music_links_bot.songlink import SonglinkClient
from music_links_bot.youtube import YouTubeClient


@run_async
@pytest.mark.parametrize("delivery_fails", [False, True])
async def test_direct_channel_link_uses_branded_photo_and_preserves_source_on_failure(
    delivery_fails,
):
    source = "https://open.spotify.com/track/102"
    track = sample(title="Samhain", artist="Froglord", links={"spotify": source})
    context = ContextStub(
        songlink_client=SimpleNamespace(lookup_track=AsyncMock(return_value=track))
    )
    message = ReplaceableChannelMessageStub()
    message.text = "тест\n" + source

    async def send_photo(**kwargs):
        assert not message.deleted
        if delivery_fails:
            raise TimeoutError("Delivery outcome unknown")
        return SimpleNamespace(message_id=123)

    context.bot.send_photo = AsyncMock(side_effect=send_photo)
    context.bot.get_chat_member = AsyncMock(
        return_value=SimpleNamespace(
            status="administrator", can_post_messages=True, can_delete_messages=True
        )
    )
    with (
        patch("music_links_bot.branding.photo_branding_enabled", return_value=True),
        patch(
            "music_links_bot.branding.build_branded_cover",
            new=AsyncMock(return_value=b"BRANDED"),
        ) as brand,
    ):
        await track_lookup_message(UpdateStub(message), context)

    context.bot.send_photo.assert_awaited_once()
    payload = context.bot.send_photo.await_args.kwargs
    assert payload["photo"] == b"BRANDED"
    assert "Samhain" in payload["caption"] and "тест" in payload["caption"]
    assert brand.await_args.kwargs["label"] == "@stonerhand"
    assert all(
        button.url and not button.callback_data
        for row in payload["reply_markup"].inline_keyboard
        for button in row
    )
    assert message.deleted is not delivery_fails
    assert not context.bot.sent_messages


@pytest.mark.parametrize("platform", ["spotify", "appleMusic"])
@pytest.mark.parametrize("mode", ["classic", "photo", "inline", "rich"])
def test_generated_metadata_links_pass_the_final_publication_gate(platform, mode):
    root = (
        "https://open.spotify.com"
        if platform == "spotify"
        else "https://music.apple.com/us"
    )
    track = sample(
        links={platform: root + "/album/unified/101?i=102"}
        if platform == "appleMusic"
        else {platform: root + "/track/102"},
        album_url=root + "/album/unified/101",
        artist_url=root + "/artist/band/103?uo=4&l=en",
    )
    result = validate_rendered_publication(
        RenderedPublication(
            text=format_track_message(track),
            source_urls=tuple(track.links.values()),
            mode=mode,
        )
    )
    assert result.ready, result.blocking_codes


@pytest.mark.parametrize(
    "text",
    [
        "https://music.apple.com/us/album/unified/101?i=102",
        '<a href="https://music.apple.com/us/album/unified/101?i=102">Слушать</a>',
        '<a href="https://open.spotify.com/artist/103">https://open.spotify.com/artist/103</a>',
        "https://open.<b>spotify</b>.com/track/102",
    ],
)
def test_raw_source_urls_are_still_rejected(text):
    result = validate_rendered_publication(RenderedPublication(text=text))
    assert "visible_source_url" in result.blocking_codes


@run_async
@pytest.mark.parametrize("platform", ["spotify", "appleMusic"])
async def test_real_caption_reaches_editor_inline_and_photo_delivery(platform):
    root = (
        "https://open.spotify.com"
        if platform == "spotify"
        else "https://music.apple.com/us"
    )
    source = root + (
        "/track/102" if platform == "spotify" else "/album/unified/101?i=102"
    )
    track = sample(
        links={platform: source},
        album_url=root + "/album/unified/101",
        artist_url=root + "/artist/band/103",
        duration_ms=222000,
    )
    client = SimpleNamespace(lookup_track=AsyncMock(return_value=track))
    context = ContextStub(songlink_client=client)
    message = PrivateMessageStub()
    message.text = source
    await track_lookup_message(UpdateStub(message), context)
    assert any("Dig" in r for r in message.replies)
    inline = await _build_inline_result(source, context)
    assert inline is not None
    assert "href=" in inline.input_message_content.message_text
    context.bot.send_photo = AsyncMock(return_value=SimpleNamespace(message_id=1))
    result = await PublicationService(context, channel_username="stonerhand").deliver(
        new_track_draft(track, chat_id=7, lang="ru"), target=7, channel_style=False
    )
    assert result is not None
    context.bot.send_photo.assert_awaited_once()


def deezer_payload():
    return {
        "id": 1873297197,
        "type": "track",
        "title": "Calm Down",
        "artist": {"name": "Rema"},
        "album": {
            "title": "Calm Down",
            "cover_xl": "https://cdn-images.dzcdn.net/images/cover/test/1000.jpg",
        },
        "duration": 239,
        "release_date": "2022-08-25",
    }


@run_async
@pytest.mark.parametrize("envelope", [False, True])
async def test_deezer_short_link_works_without_songlink_credentials(envelope):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if request.url.host == "link.deezer.com":
            destination = "https://www.deezer.com/track/1873297197?utm_source=test"
            return httpx.Response(
                301,
                headers={
                    "location": "https://link.deezer.com/?"
                    + urlencode({"dest": destination})
                    if envelope
                    else destination
                },
            )
        assert str(request.url) == "https://api.deezer.com/track/1873297197"
        return httpx.Response(200, json=deezer_payload())

    client = SonglinkClient(user_countries=("US",))
    await client._deezer_client._client.aclose()
    client._deezer_client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(respond)
    )
    try:
        context = ContextStub(songlink_client=client)
        result = await _build_inline_result(
            "https://link.deezer.com/s/example", context
        )
        assert result is not None and "Calm Down" in result.title
        buttons = json.dumps(result.reply_markup.to_dict())
        assert "https://www.deezer.com/track/1873297197" in buttons
        assert "spotify.com" not in buttons
        assert len(calls) == 2
    finally:
        await client.aclose()


@run_async
@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1/track/1",
        "https://evil.test/track/1",
        "https://deezer.com.evil.test/track/1",
    ],
)
async def test_deezer_redirect_never_contacts_a_foreign_host(target):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(301, headers={"location": target})

    client = DeezerClient()
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(DeezerLookupError):
            await client.lookup_release("https://link.deezer.com/s/example")
        assert len(calls) == 1
    finally:
        await client.aclose()


@run_async
async def test_deezer_rejects_a_different_release_returned_by_the_api():
    client = DeezerClient()
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=deezer_payload())
        )
    )
    try:
        with pytest.raises(DeezerLookupError):
            await client.lookup_release("https://www.deezer.com/track/999")
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "source,kind,artist,title",
    [
        (
            "https://tidal.com/track/94560983",
            "MusicRecording",
            "Hanne Mjøen",
            "Sounds Good To Me",
        ),
        (
            "https://tidal.com/browse/album/94560982",
            "MusicAlbum",
            "Hanne Mjøen",
            "Sounds Good To Me",
        ),
        (
            "https://sleep.bandcamp.com/album/dopesmoker",
            "MusicAlbum",
            "Sleep",
            "Dopesmoker",
        ),
    ],
)
@pytest.mark.parametrize("artist_shape", ["object", "list", "multiple", "invalid"])
def test_public_release_uses_exact_schema_metadata(
    source, kind, artist, title, artist_shape
):
    schema = {
        "@type": kind,
        "@id": source,
        "name": title,
        "byArtist": {"name": artist},
        "duration": "PT3M15S",
    }
    if artist_shape == "list":
        schema["byArtist"] = [{"name": artist}]
    elif artist_shape == "multiple":
        schema["byArtist"] = [{"name": artist}, {"name": "Guest"}, {"name": artist}]
    elif artist_shape == "invalid":
        schema["byArtist"] = [None, {"name": 42}, {"name": " "}]
    page = f'<meta property="og:url" content="{source}"><script type="application/ld+json">{json.dumps(schema)}</script>'
    if artist_shape == "invalid":
        with pytest.raises(PublicReleaseError, match="Incomplete release"):
            parse_public_release(source, page)
        return
    if artist_shape == "multiple":
        artist += ", Guest"
    track = parse_public_release(source, page)
    assert (track.title, track.artist, track.duration_ms) == (title, artist, 195000)
    assert list(track.links.values()) == [source]
    with pytest.raises(PublicReleaseError):
        parse_public_release(
            source, page.replace(source, "https://tidal.com/track/999")
        )


def test_yandex_full_album_title_and_track_metadata_do_not_use_generic_page_titles():
    source = "https://music.yandex.ru/album/11792937"
    schema = {
        "@type": "MusicAlbum",
        "url": "/album/11792937",
        "name": "Full album title without clipping",
    }
    page = f'<meta property="og:url" content="http://music.yandex.ru/album/11792937"><meta property="og:title" content="Clipped..."><meta property="og:description" content="Artist • Альбом • 2020"><script type="application/ld+json">{json.dumps(schema)}</script>'
    track = parse_public_release(source, page)
    assert track.title == schema["name"]
    assert (track.artist, track.release_year, track.kind) == ("Artist", "2020", "album")
    with pytest.raises(PublicReleaseError):
        parse_public_release(
            source, page.replace("Artist • Альбом • 2020", "Яндекс Музыка недоступна")
        )


def test_yandex_regional_refusal_is_distinct_from_missing_release_metadata():
    source = "https://music.yandex.ru/track/21940"
    with pytest.raises(PublicReleaseRegionUnavailable):
        parse_public_release(
            source, "<html>Яндекс Музыка недоступна<!-- --> в вашем регионе</html>"
        )
    with pytest.raises(PublicReleaseError) as error:
        parse_public_release(source, "<html>Temporary error</html>")
    assert not isinstance(error.value, PublicReleaseRegionUnavailable)


@run_async
async def test_public_provider_redirect_rejects_changed_release_before_fetch():
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(
            302, headers={"location": "https://evil.test/track/94560983"}
        )

    client = PublicReleaseClient()
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(PublicReleaseError):
            await client.lookup_release("https://tidal.com/track/94560983")
        assert len(calls) == 1
    finally:
        await client.aclose()


@run_async
async def test_youtube_music_uses_official_oembed_and_keeps_the_original_link():
    source = "https://music.youtube.com/watch?v=abc"
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "title": "Song",
                "author_name": "Channel",
                "thumbnail_url": "https://i.ytimg.com/vi/abc/hqdefault.jpg",
            },
        )

    client = YouTubeClient()
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="https://www.youtube.com", transport=httpx.MockTransport(respond)
    )
    try:
        context = ContextStub(youtube_client=client)
        result = await _build_inline_result(source, context)
        assert result is not None
        assert "Song" in result.title
        assert requests[0].url.params["url"] == "https://www.youtube.com/watch?v=abc"
        assert any(
            button.url == source
            for row in result.reply_markup.inline_keyboard
            for button in row
        )
    finally:
        await client.aclose()
