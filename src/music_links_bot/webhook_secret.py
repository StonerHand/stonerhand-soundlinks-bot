from __future__ import annotations

import hashlib
import os


def _derived_secret(purpose: str) -> str:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        return ""

    digest = hashlib.sha256(f"stonerhand-{purpose}:{bot_token}".encode())
    return digest.hexdigest()[:48]


def telegram_webhook_secret() -> str:
    """The secret Telegram must echo back on every webhook delivery.

    Explicit TELEGRAM_WEBHOOK_SECRET wins; otherwise a stable value is
    derived from the bot token, so incoming updates are authenticated even
    on deployments that never configured the variable. Both the webhook
    registration (api/set_webhook.py) and the verification
    (api/telegram.py) call this, so the two sides always agree.
    """
    configured = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if configured:
        return configured

    return _derived_secret("webhook")


def queue_worker_secret() -> str:
    """Protect the queue worker even when CRON_SECRET was saved empty.

    An explicit production secret still wins. The stable fallback uses a
    separate purpose from Telegram's webhook secret and never exposes the bot
    token itself.
    """
    configured = os.getenv("CRON_SECRET", "").strip()
    if configured:
        return configured

    return _derived_secret("queue-worker")
