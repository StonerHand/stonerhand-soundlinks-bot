from __future__ import annotations

import logging
from typing import Any

from telegram import Message
from telegram.constants import ParseMode
from telegram.error import TelegramError

from music_links_bot.chat_access import PublishAccess, check_publish_access
from music_links_bot.bot_builder import (
    MESSAGE_TEXT_LIMIT,
    PHOTO_CAPTION_LIMIT,
    fit_telegram_html,
)
from music_links_bot.channel_templates import save_channel_template
from music_links_bot.models import TrackMatch
from music_links_bot.publication_view import (
    build_publication_view,
    draft_message_overrides,
)

LOGGER = logging.getLogger(__name__)


class PublicationService:
    """One Telegram delivery pipeline shared by the bot and queue."""

    def __init__(
        self,
        context,
        *,
        channel_username: str,
        branding_hooks: tuple | None = None,
    ) -> None:
        self.context = context
        self.channel_username = channel_username.lstrip("@")
        self.branding_hooks = branding_hooks

    async def publish(
        self,
        draft: dict,
        *,
        notify_failure: bool = True,
    ) -> Message | bool | None:
        target = (
            self.context.application.bot_data.get("publish_chat_id")
            or f"@{self.channel_username}"
        )
        return await self.deliver(
            draft,
            target=target,
            channel_style=True,
            notify_failure=notify_failure,
        )

    async def deliver(
        self,
        draft: dict,
        *,
        target: int | str,
        channel_style: bool,
        notify_failure: bool = True,
    ) -> Message | bool | None:
        track = TrackMatch(**draft["item"])
        access = PublishAccess(True, False, checked=False)
        if channel_style:
            access = await check_publish_access(self.context, target)
            if not access.allowed:
                if notify_failure:
                    await self._report_failure(
                        track,
                        target=target,
                        detail=access.detail,
                    )
                self._record_publication(False)
                await self._persist_metrics()
                return None

        try:
            sent = await self._send(
                draft,
                track,
                target=target,
                channel_style=channel_style,
            )
        except Exception as exc:
            LOGGER.warning(
                "Could not deliver %s — %s to %s",
                track.artist,
                track.title,
                target,
                exc_info=True,
            )
            if channel_style and notify_failure:
                await self._report_failure(
                    track,
                    target=target,
                    detail=f"{type(exc).__name__}: {str(exc)[:180]}",
                )
            self._record_publication(False)
            await self._persist_metrics()
            return None

        delivered = sent is not None and sent is not False
        self._record_publication(delivered)
        if channel_style and delivered:
            await save_channel_template(self.context, target, draft)
        await self._persist_metrics()
        return sent if delivered else None

    async def _send(
        self,
        draft: dict,
        track: TrackMatch,
        *,
        target: int | str,
        channel_style: bool,
    ):
        from music_links_bot.formatter import build_auto_hashtags
        from music_links_bot.keyboards import (
            _build_link_preview_options,
            _select_preview_url,
        )
        from music_links_bot.rich_publications import (
            build_fallback_html,
            build_rich_html,
            is_longread,
            rich_api_unavailable,
            send_rich_publication,
        )

        include_hashtags, overrides = draft_message_overrides(
            draft,
            include_hashtags=(True if channel_style else bool(draft.get("hashtags"))),
        )
        include_channel_button = (
            str(target).lstrip("@").casefold() != self.channel_username.casefold()
        )
        view = build_publication_view(
            draft,
            track,
            context=self.context,
            include_channel_button=include_channel_button,
            channel_style=channel_style,
        )
        text = view.text
        keyboard = view.keyboard

        if is_longread(draft):
            hashtags = overrides.get("hashtags")
            if include_hashtags and not hashtags:
                hashtags = build_auto_hashtags(track)
            rich_html = build_rich_html(
                draft,
                track,
                hashtags=hashtags if include_hashtags else None,
            )
            try:
                return await send_rich_publication(
                    self.context.bot,
                    chat_id=target,
                    rich_html=rich_html,
                    reply_markup=keyboard,
                )
            except TelegramError as exc:
                if not rich_api_unavailable(exc):
                    raise
                LOGGER.info(
                    "Rich Messages unavailable for %s; using HTML fallback",
                    target,
                )
                return await self.context.bot.send_message(
                    chat_id=target,
                    text=fit_telegram_html(
                        build_fallback_html(
                            draft,
                            track,
                            hashtags=hashtags if include_hashtags else None,
                        ),
                        MESSAGE_TEXT_LIMIT,
                    ),
                    parse_mode=ParseMode.HTML,
                    link_preview_options=_build_link_preview_options(
                        _select_preview_url(track.links, self.context)
                        or track.thumbnail_url,
                        prefer_large_media=True,
                    ),
                    reply_markup=keyboard,
                )

        if draft.get("as_photo") and track.thumbnail_url:
            photo: Any = track.thumbnail_url
            # Pillow and image networking are loaded only for explicit photo
            # posts, keeping normal bot cold starts light.
            if self.branding_hooks is None:
                from music_links_bot.branding import (
                    brand_label,
                    brand_logo_url,
                    build_branded_cover,
                    photo_branding_enabled,
                )
            else:
                (
                    photo_branding_enabled,
                    build_branded_cover,
                    brand_label,
                    brand_logo_url,
                ) = self.branding_hooks

            if photo_branding_enabled():
                branded = await build_branded_cover(
                    track.thumbnail_url,
                    label=brand_label(f"@{self.channel_username}"),
                    logo_url=brand_logo_url(),
                )
                if branded is not None:
                    photo = branded
            return await self.context.bot.send_photo(
                chat_id=target,
                photo=photo,
                caption=fit_telegram_html(text, PHOTO_CAPTION_LIMIT),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )

        return await self.context.bot.send_message(
            chat_id=target,
            text=fit_telegram_html(text, MESSAGE_TEXT_LIMIT),
            parse_mode=ParseMode.HTML,
            link_preview_options=_build_link_preview_options(
                _select_preview_url(track.links, self.context) or track.thumbnail_url,
                prefer_large_media=bool(draft.get("large_preview")),
            ),
            reply_markup=keyboard,
        )

    def _record_publication(self, ok: bool) -> None:
        runtime = self.context.application.bot_data.get("runtime")
        if runtime is not None and hasattr(runtime, "record_publication"):
            runtime.record_publication(ok=ok)

    async def _persist_metrics(self) -> None:
        runtime = self.context.application.bot_data.get("runtime")
        if runtime is not None and hasattr(runtime, "persist_metrics"):
            await runtime.persist_metrics()

    async def _report_failure(
        self,
        track: TrackMatch,
        *,
        target: int | str,
        detail: str,
    ) -> None:
        admin_chat_id = self.context.application.bot_data.get("admin_chat_id")
        if admin_chat_id is None:
            return
        text = (
            "⚠️ Не опубликован пост\n"
            f"{track.artist} — {track.title}\n"
            f"Канал: {target}\n"
            f"Причина: {detail or 'неизвестная ошибка'}"
        )
        try:
            await self.context.bot.send_message(
                chat_id=admin_chat_id,
                text=text[:4000],
            )
        except Exception:
            LOGGER.info("Could not notify the bot owner about publish failure")
