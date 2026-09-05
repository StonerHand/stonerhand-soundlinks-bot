from __future__ import annotations

import logging
from typing import Any

from telegram import Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from music_links_bot.bot_builder import (
    MESSAGE_TEXT_LIMIT,
    PHOTO_CAPTION_LIMIT,
    fit_telegram_html,
)
from music_links_bot.channel_templates import save_channel_template
from music_links_bot.chat_access import PublishAccess, check_publish_access
from music_links_bot.draft_model import prepare_publication_draft
from music_links_bot.models import TrackMatch
from music_links_bot.publication_contract import require_valid_publication
from music_links_bot.publication_preflight import validate_publication
from music_links_bot.publication_view import (
    build_publication_view,
    publication_contract_from_view,
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
        self.confirmed_not_sent = True

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

    async def preview(
        self,
        draft: dict,
        *,
        target: int | str,
    ) -> Message | bool | None:
        """Send the exact publication without editor controls or side effects."""
        prepared = prepare_publication_draft(draft)
        if (
            prepared is None
            or not validate_publication(prepared.data, prepared.track).ready
        ):
            return None
        try:
            return await self._send(
                prepared.data,
                prepared.track,
                target=target,
                channel_style=False,
                include_channel_button=False,
                record_metrics=False,
            )
        except Exception:
            LOGGER.info("Could not render clean publication preview", exc_info=True)
            return None

    async def deliver(
        self,
        draft: dict,
        *,
        target: int | str,
        channel_style: bool,
        notify_failure: bool = True,
    ) -> Message | bool | None:
        # The service may be reused. Retry safety describes this delivery only,
        # never the outcome of an earlier call on the same instance.
        self.confirmed_not_sent = True
        prepared = prepare_publication_draft(draft)
        if prepared is None:
            self._record_publication(False)
            await self._persist_metrics()
            return None
        draft = prepared.data
        track = prepared.track
        if not validate_publication(draft, track).ready:
            self._record_publication(False)
            await self._persist_metrics()
            return None
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

        self.confirmed_not_sent = False
        try:
            sent = await self._send(
                draft,
                track,
                target=target,
                channel_style=channel_style,
            )
        except Exception as exc:
            # These are explicit Bot API rejections. A network failure can
            # occur after Telegram accepted the post and must stay ambiguous.
            self.confirmed_not_sent = isinstance(
                exc, (BadRequest, Forbidden, RetryAfter)
            )
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
            try:
                await save_channel_template(self.context, target, draft)
            except Exception:  # noqa: BLE001
                LOGGER.warning(
                    "Post delivered, but channel template could not be saved"
                )
        await self._persist_metrics()
        return sent if delivered else None

    async def _send(
        self,
        draft: dict,
        track: TrackMatch,
        *,
        target: int | str,
        channel_style: bool,
        include_channel_button: bool | None = None,
        record_metrics: bool = True,
    ):
        if include_channel_button is None:
            include_channel_button = (
                str(target).lstrip("@").casefold() != self.channel_username.casefold()
            )
        view = build_publication_view(
            draft,
            track,
            context=self.context,
            include_channel_button=include_channel_button,
        )
        require_valid_publication(publication_contract_from_view(view, track))
        text = view.text
        keyboard = view.keyboard

        if view.source_audio_file_id:
            return await self._send_audio(
                draft,
                track,
                target=target,
                audio_file_id=view.source_audio_file_id,
                text=text,
                keyboard=keyboard,
            )

        handled, sent = await self._try_send_rich(
            draft,
            track,
            target=target,
            keyboard=keyboard,
            hashtags=view.hashtags,
            preview_url=view.preview_url,
            delivery_mode=view.delivery_mode,
            as_photo=view.as_photo,
            record_metrics=record_metrics,
        )
        if handled:
            return sent

        if view.as_photo and view.cover:
            return await self._send_photo(
                draft,
                track,
                target=target,
                cover=view.cover,
                text=text,
                keyboard=keyboard,
            )

        return await self._send_classic_message(
            target=target,
            text=text,
            keyboard=keyboard,
            preview_url=view.preview_url,
            prefer_large_preview=view.prefer_large_preview,
        )

    async def _send_audio(
        self,
        draft,
        track,
        *,
        target,
        audio_file_id,
        text,
        keyboard,
    ):
        return await self.context.bot.send_audio(
            chat_id=target,
            audio=audio_file_id,
            caption=fit_telegram_html(text, PHOTO_CAPTION_LIMIT),
            parse_mode=ParseMode.HTML,
            title=track.title[:64],
            performer=track.artist[:64],
            duration=int(draft.get("source_audio_duration") or 0) or None,
            reply_markup=keyboard,
        )

    async def _try_send_rich(
        self,
        draft,
        track,
        *,
        target,
        keyboard,
        hashtags: str | None,
        preview_url: str | None,
        delivery_mode: str,
        as_photo: bool,
        record_metrics: bool,
    ) -> tuple[bool, Any]:
        from music_links_bot.keyboards import (
            _build_link_preview_options,
        )
        from music_links_bot.rich_publications import (
            build_fallback_html,
            build_rich_card_html,
            build_rich_html,
            is_longread,
            rich_api_unavailable,
            rich_messages_enabled,
            send_rich_publication,
        )

        # Explicit photo mode (including branded frames) remains authoritative.
        if not rich_messages_enabled() or delivery_mode == "classic" or as_photo:
            return False, None
        longread = is_longread(draft)
        rich_html = (
            build_rich_html(
                draft,
                track,
                hashtags=hashtags,
                reply_markup=keyboard,
            )
            if longread
            else build_rich_card_html(
                draft,
                track,
                hashtags=hashtags,
                reply_markup=keyboard,
            )
        )
        if not rich_html:
            return False, None
        try:
            sent = await send_rich_publication(
                self.context.bot,
                chat_id=target,
                rich_html=rich_html,
            )
            if record_metrics:
                self._record_rich(ok=True)
            return True, sent
        except TelegramError as exc:
            # Falling back after a lost HTTP response could publish twice.
            # Only a definitive API rejection permits another send method.
            if not isinstance(exc, BadRequest):
                raise
            if record_metrics:
                self._record_rich(ok=False, fallback=True)
            LOGGER.info(
                "Rich Messages failed for %s; using HTML fallback",
                target,
                exc_info=not rich_api_unavailable(exc),
            )
            if not longread:
                return False, None
            sent = await self.context.bot.send_message(
                chat_id=target,
                text=fit_telegram_html(
                    build_fallback_html(draft, track, hashtags=hashtags),
                    MESSAGE_TEXT_LIMIT,
                ),
                parse_mode=ParseMode.HTML,
                link_preview_options=_build_link_preview_options(
                    preview_url,
                    prefer_large_media=True,
                ),
                reply_markup=keyboard,
            )
            return True, sent

    async def _send_photo(self, draft, track, *, target, cover, text, keyboard):
        photo: Any = cover
        cacheable = not bool(draft.get("custom_cover_file_id"))
        # Pillow and image networking are loaded only for explicit photo posts.
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

        if cacheable and track.thumbnail_url and photo_branding_enabled():
            cacheable = False
            branded = await build_branded_cover(
                track.thumbnail_url,
                label=brand_label(f"@{self.channel_username}"),
                logo_url=brand_logo_url(),
            )
            if branded is not None:
                photo = branded
        if cacheable and track.thumbnail_url:
            from music_links_bot.telegram_media_cache import get_cached_file_id

            photo = await get_cached_file_id(self.context, track.thumbnail_url) or photo
        sent = await self.context.bot.send_photo(
            chat_id=target,
            photo=photo,
            caption=fit_telegram_html(text, PHOTO_CAPTION_LIMIT),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        if cacheable and track.thumbnail_url:
            from music_links_bot.telegram_media_cache import remember_photo_file_id

            await remember_photo_file_id(self.context, track.thumbnail_url, sent)
        return sent

    async def _send_classic_message(
        self,
        *,
        target,
        text,
        keyboard,
        preview_url,
        prefer_large_preview,
    ):
        from music_links_bot.keyboards import _build_link_preview_options

        return await self.context.bot.send_message(
            chat_id=target,
            text=fit_telegram_html(text, MESSAGE_TEXT_LIMIT),
            parse_mode=ParseMode.HTML,
            link_preview_options=_build_link_preview_options(
                preview_url,
                prefer_large_media=prefer_large_preview,
            ),
            reply_markup=keyboard,
        )

    def _record_publication(self, ok: bool) -> None:
        runtime = self.context.application.bot_data.get("runtime")
        if runtime is not None and hasattr(runtime, "record_publication"):
            runtime.record_publication(ok=ok)

    def _record_rich(self, *, ok: bool, fallback: bool = False) -> None:
        runtime = self.context.application.bot_data.get("runtime")
        if runtime is not None and hasattr(runtime, "record_rich_message"):
            runtime.record_rich_message(ok=ok, fallback=fallback)

    async def _persist_metrics(self) -> None:
        runtime = self.context.application.bot_data.get("runtime")
        if runtime is not None and hasattr(runtime, "persist_metrics"):
            try:
                await runtime.persist_metrics()
            except Exception:  # noqa: BLE001
                LOGGER.debug("Publication metrics could not be persisted")

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
        except TelegramError:
            # Failure reporting is deliberately best-effort: an unexpected
            # transport/runtime error must not hide the original publish error.
            LOGGER.info("Could not notify the bot owner about publish failure")
