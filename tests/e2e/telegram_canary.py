"""Opt-in live send/verify/delete canary. Never run this against a channel."""

# Real network probes prioritize cleanup clarity over micro-optimizing rare loops.
# ruff: noqa: PERF203

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
from telegram import Bot, Message

from music_links_bot.draft_model import new_track_draft
from music_links_bot.keyboards import _build_link_preview_options
from music_links_bot.lookup_models import LookupBundle
from music_links_bot.publication_service import PublicationService
from music_links_bot.release_hubs import is_universal_release_url
from music_links_bot.rich_publications import send_rich_publication
from music_links_bot.rich_rendering import build_rich_collection_html
from music_links_bot.sharing import render_inline_share_card
from music_links_bot.soundcloud import SoundCloudClient
from music_links_bot.spotify import SpotifyClient

SPOTIFY_URLS = (
    "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
    "https://open.spotify.com/track/7Ca5yTC81P0AtRnNKHKzwJ",
)
SOUNDCLOUD_URL = (
    "https://soundcloud.com/stoner-hand/ethan-kath-dj-set-park-live-moscow-30062013"
)


class RecordedBot:
    """Keep every confirmed test message for cleanup, including failed checks."""

    def __init__(self, bot: Bot, target: int):
        self.bot = bot
        self.target = target
        self.message_ids: set[int] = set()

    @property
    def token(self):
        return self.bot.token

    def record(self, value):
        message_id = (
            value.get("message_id")
            if isinstance(value, dict)
            else getattr(value, "message_id", None)
        )
        if isinstance(message_id, int) and message_id > 0:
            self.message_ids.add(message_id)
        return value

    async def _post(self, endpoint, *, data, **kwargs):
        if data.get("chat_id") != self.target:
            raise ValueError("Canary attempted to use another chat")
        return self.record(await self.bot._post(endpoint, data=data, **kwargs))

    async def send_message(self, **kwargs):
        if kwargs.get("chat_id") != self.target:
            raise ValueError("Canary attempted to use another chat")
        return self.record(
            await self.bot.send_message(**kwargs, disable_notification=True)
        )


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise RuntimeError(detail)


async def verify(chat_id: int) -> tuple[list[str], list[str]]:
    token = os.getenv("BOT_TOKEN", "").strip()
    if (
        not token
        or not chat_id
        or str(chat_id) == os.getenv("PUBLISH_CHAT_ID", "").strip()
    ):
        raise ValueError("Set BOT_TOKEN and choose a separate test chat")
    os.environ.setdefault(
        "WEBHOOK_BASE_URL",
        os.getenv("CANARY_BASE_URL", "https://tg-bot-sh.vercel.app"),
    )
    spotify, soundcloud = SpotifyClient(timeout=12), SoundCloudClient(timeout=12)
    passed, failures = [], []
    async with Bot(token) as bot:
        chat = await bot.get_chat(chat_id)
        require(
            chat.type in {"private", "group", "supergroup"},
            "Channels are not allowed for this canary",
        )
        require(chat.type == "private" or not chat.username, "Use a private test group")
        recorded = RecordedBot(bot, chat_id)
        context = SimpleNamespace(
            bot=recorded, application=SimpleNamespace(bot_data={})
        )
        service = PublicationService(context, channel_username="stonerhand")
        try:
            tracks = [await spotify.lookup_release(url) for url in SPOTIFY_URLS]
            sc_track = await soundcloud.lookup_track(SOUNDCLOUD_URL)
            require(
                all(track.thumbnail_url for track in tracks),
                "Spotify artwork metadata missing",
            )

            for name, track in (
                ("classic-track", tracks[0]),
                ("soundcloud-only", sc_track),
            ):
                try:
                    draft = new_track_draft(
                        track,
                        chat_id=chat_id,
                        lang="ru",
                        prefix="Проверка перед релизом — сообщение будет удалено.",
                    )
                    draft["delivery_mode"] = "classic"
                    sent = await service.preview(draft, target=chat_id)
                    require(
                        isinstance(sent, Message),
                        "Telegram did not confirm the test card",
                    )
                    rows = (
                        sent.reply_markup.inline_keyboard if sent.reply_markup else ()
                    )
                    buttons = [button for row in rows for button in row if button.url]
                    if name == "classic-track":
                        require(
                            any(
                                "spotify" in button.text.casefold()
                                for button in buttons
                            ),
                            "Spotify button missing",
                        )
                        require(
                            bool(buttons) and is_universal_release_url(buttons[0].url),
                            "Primary CTA is not a universal release page",
                        )
                    else:
                        require(
                            not any(
                                "spotify" in button.text.casefold()
                                for button in buttons
                            ),
                            "False Spotify match for SoundCloud-only recording",
                        )
                        require(
                            any(
                                urlparse(button.url).hostname == "soundcloud.com"
                                for button in buttons
                            ),
                            "SoundCloud source button missing",
                        )
                    passed.append(name)
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{name}: {type(exc).__name__}: {str(exc)[:140]}")

            bundle = LookupBundle(
                tracks=tracks,
                unavailable_urls=[],
                videos=[],
                radios=[],
                playlists=[],
                artists=[],
            )
            card = render_inline_share_card(
                bundle,
                context=context,
                lang="ru",
                share_query=None,
                share_label="Поделиться",
                requested_count=len(tracks),
            )
            try:
                require(
                    bool(card.preview_url) and "/api/collage?" in card.preview_url,
                    "Signed collage preview is missing",
                )
                async with httpx.AsyncClient(
                    timeout=20, follow_redirects=False
                ) as client:
                    image = await client.get(card.preview_url)
                    require(
                        image.status_code == 200
                        and image.headers.get("content-type", "").startswith(
                            "image/jpeg"
                        ),
                        "Collage renderer failed or fell back to one artwork",
                    )
                sent = await recorded.send_message(
                    chat_id=chat_id,
                    text=card.text,
                    parse_mode="HTML",
                    reply_markup=card.keyboard,
                    link_preview_options=_build_link_preview_options(
                        card.preview_url, prefer_large_media=True
                    ),
                )
                require(
                    all(track.title in (sent.text or "") for track in tracks),
                    "Collection lost a release",
                )
                require(
                    sent.reply_markup == card.keyboard,
                    "Telegram changed the collection buttons",
                )
                passed.append("classic-collection-collage")
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    f"classic-collection: {type(exc).__name__}: {str(exc)[:140]}"
                )

            try:
                rich = build_rich_collection_html(
                    tracks,
                    title=card.title,
                    hashtags="#stonerhand #collection",
                    reply_markup=card.keyboard,
                )
                sent = await send_rich_publication(
                    recorded, chat_id=chat_id, rich_html=rich
                )
                require(
                    isinstance(sent, Message),
                    "Telegram did not confirm the Rich Message",
                )
                passed.append("rich-collection")
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    f"rich-collection: {type(exc).__name__}: {str(exc)[:140]}"
                )
        finally:
            for message_id in sorted(recorded.message_ids):
                try:
                    require(
                        await bot.delete_message(chat_id, message_id),
                        "Deletion was not confirmed",
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append(
                        f"cleanup message {message_id}: {type(exc).__name__}"
                    )
            await spotify.aclose()
            await soundcloud.aclose()
    return passed, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-id", type=int, required=True)
    args = parser.parse_args()
    # Never include transport URLs containing a bot token in canary output.
    logging.disable(logging.CRITICAL)
    try:
        passed, failures = asyncio.run(verify(args.chat_id))
    except Exception as exc:  # noqa: BLE001
        print(f"Canary could not start: {type(exc).__name__}")
        return 1
    print("Confirmed: " + ", ".join(passed))
    for failure in failures:
        print(failure)
    print("Cleanup attempted for every confirmed test message.")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
