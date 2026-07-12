from __future__ import annotations

import hashlib
import os


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

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        return ""

    digest = hashlib.sha256(f"stonerhand-webhook:{bot_token}".encode("utf-8"))
    return digest.hexdigest()[:48]
