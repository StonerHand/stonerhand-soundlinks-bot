---
name: stonerhand-bot-deploy
description: Use when deploying, migrating, restarting, or debugging hosting for StonerHand Soundlinks Bot on Vercel, Railway, Render, VPS, or local Mac. Applies to webhook setup, polling, environment variables, logs, and deployment failures.
---

# StonerHand Bot Deploy

Use this skill for deployment and production troubleshooting.

## Golden Rule

Only one runtime must receive Telegram updates:

- Vercel/serverless uses webhook
- Railway/VPS/local uses polling

Never keep webhook and polling active for the same bot token at the same time.

## Required Env

Minimum production env:

```env
BOT_TOKEN=...
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
PRIMARY_PLATFORM=spotify
SET_WEBHOOK_SECRET=...
```

Optional:

```env
SONGLINK_API_KEY=...
ADMIN_CHAT_ID=...
TELEGRAM_WEBHOOK_SECRET=...
WEBHOOK_BASE_URL=...
STATS_PATH=...
```

Never print, commit, quote, or expose real tokens.

## Vercel Flow

1. Confirm `vercel.json` routes `/api/telegram` and `/api/set_webhook`.
2. Confirm `api/telegram.py` imports the app and handles POST updates.
3. Confirm env variables are set for Production.
4. Deploy from `main`.
5. Open `/api/set_webhook?secret=...` after deploy; the endpoint stays closed without `SET_WEBHOOK_SECRET`.
6. If `TELEGRAM_WEBHOOK_SECRET` is configured, confirm setup registered it before testing updates.
7. Test `/start` in Telegram.
8. Send a Spotify track, SoundCloud link, YouTube link, NTS link, and one invalid message.

Vercel root `404` is normal. The useful routes are API routes.

## Polling Flow

Use for local, Railway, VPS:

```bash
PYTHONPATH=src python -m music_links_bot
```

Before starting polling in production, delete webhook if needed:

```text
https://api.telegram.org/bot<token>/deleteWebhook
```

Do not paste the real token into docs or chat logs.

## Debug Checklist

| Symptom | Check |
| --- | --- |
| Bot silent | `BOT_TOKEN`, webhook URL, deploy logs |
| Duplicate replies | Webhook and polling both active |
| Vercel deploy works but bot silent | Protected `/api/set_webhook?secret=...` was not opened |
| Setup endpoint returns 503 | `SET_WEBHOOK_SECRET` is missing |
| Telegram updates return 403 | `TELEGRAM_WEBHOOK_SECRET` was added but webhook was not re-registered |
| `No module named music_links_bot` | Missing `PYTHONPATH=src` or package install issue |
| `BOT_TOKEN is not set` | Env variable missing in host |
| Channel replacement fails | Bot lacks admin rights or delete permission |
| Root URL is 404 | Normal for this project |

## Pre-Deploy Checks

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests api
git diff --check
```

After changing env or webhook code, always verify with a real Telegram message.
