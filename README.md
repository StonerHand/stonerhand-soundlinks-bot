<div align="center">

# 🎧 StonerHand Soundlinks Bot

### A music link → a finished Telegram publication

[Open the bot](https://t.me/StonerHandBot) · [Channel](https://t.me/stonerhand) · [Русская версия](README.ru.md) · [Architecture (RU)](ARCHITECTURE.ru.md)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot%20%2B%20Mini%20App-26A5E4?style=flat-square&logo=telegram&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-Production-000?style=flat-square&logo=vercel)
![CI](https://img.shields.io/github/actions/workflow/status/StonerHand/stonerhand-soundlinks-bot/ci.yml?style=flat-square&label=CI)

<img src="assets/studio-demo.svg" alt="Animated StonerHand Studio search, longread and publishing flow" width="100%">

</div>

## Features

| Telegram bot | Studio Mini App |
| --- | --- |
| Link or title → exact release | Search, candidates and audio preview |
| Clean title, artwork, hashtags and compact buttons | Card or block-based Rich longread |
| Several links → one collection with per-link status | Up to 10 releases, ordering and failed-link retry |
| Song + YouTube clip → two-tile media preview | Song artwork and video thumbnail |
| Inline search with labeled history, cache and pagination | History, queue, undo and owner analytics |
| Automatic link replacement in chats and channels | Native sharing that preserves buttons |

Spotify, Apple Music, YouTube, SoundCloud, Bandcamp, Deezer, Tidal,
Yandex Music, podcasts, Spotify and Apple Music playlists, Spotify artists,
and NTS Radio are supported.

Cards contain release data and actions without generated promotional filler or
hidden heading links. Below the cover, only artist and title remain; genre,
format and year are not repeated, while genre still powers the useful automatic
hashtag. The quick surface is predictable: the primary service
plus the universal hub, followed by **Edit** and **Add to crate**. Editing stays
in the same Telegram message and exposes only style, text, hashtags and
platforms; delivery, sharing and destructive actions live in the overflow.
Drafts autosave, `/start` resumes the active one, and Recent keeps the last five
posts. The crate uses numbered selection and offers a 15-second undo. Automatic
hashtags are capped at three useful tags.

Longreads use Telegram Rich Messages with a safe HTML fallback. A song and a
YouTube clip become a native two-tile media album; the bot never downloads or
re-uploads the copyrighted video.

## Flow

```mermaid
flowchart LR
    A["Link / title"] --> B["Exact release"]
    A2["Several links"] --> C["Collection / media mix"]
    B --> D["Card / Longread"]
    C --> D
    D --> E["Chat · channel · queue"]
```

The home menu has four destinations: **Create**, **Crate**, **Recent**, and
**Studio**. The guided tour is shown only on the first visit. Settings, longreads,
scheduling and publishing live in the Mini App,
while chat stays a fast path. The bot and Studio use the same resolver. Provider
clients are lazy, independent lookups run in parallel, and successful bundles
are cached in memory and Redis. Equal concurrent searches and resolver batches
share one upstream request, while accidental repeated messages and `/start`
taps are debounced across warm instances. One request deadline bounds the entire lookup,
while a repeatedly failing provider is temporarily isolated. Partial batches
keep their successful cards and retry only failed links.

The channel remembers the last successful presentation preset (card/longread,
cover mode, hashtags and platform selection) and applies it to the next owner
draft. Telegram Rich Messages, prepared inline messages and safe HTML fallback
share one publication pipeline.

Before channel delivery, the bot checks its posting rights. Duplicate records
retain the previous post link and offer open, repeat or replace actions. The
Scheduled status is returned only after Redis confirms the durable queue write.
Queue ticks run only through a `CRON_SECRET`-protected worker, one leased job at
a time, with a bounded batch per invocation. Warm-instance caches are bounded,
draft ownership is fail-closed, and Studio payloads are normalized before storage.
The owner-only `/status` command summarizes Telegram, Redis, queue, permissions,
latency, cache and provider circuits.

## Vercel setup

```dotenv
BOT_TOKEN=123456:telegram-token
SET_WEBHOOK_SECRET=long-random-secret
CRON_SECRET=another-long-random-secret
ADMIN_CHAT_ID=123456789
PUBLISH_CHAT_ID=@channel
```

1. Create a bot with [@BotFather](https://t.me/BotFather) and enable `/setinline`.
2. Import the repository into Vercel with `./` as the project root.
3. Connect Upstash Redis from Vercel Marketplace for drafts, queue, history,
   analytics and cross-instance deduplication.
4. Open `https://<domain>/api/set_webhook?secret=<SET_WEBHOOK_SECRET>`.
5. Verify `https://<domain>/api/health` returns HTTP 200 and `"ok": true`.

See [.env.example](.env.example) for every setting.

<details>
<summary><b>Local development and verification</b></summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python -m playwright install chromium
cp .env.example .env

python -m pyflakes src api tests
python -m pytest -q
python tests/e2e/smoke.py
```

Do not run polling and the production webhook against the same token.

</details>

## Code map

```text
api/                    webhook, Studio API, health and queue worker
src/music_links_bot/    handlers, provider registry, publication, queue and Redis
webapp/                 build-free modular Telegram Mini App
tests/                  unit/integration, mobile smoke and production canary
```

See [ARCHITECTURE.ru.md](ARCHITECTURE.ru.md) for request flows, API actions,
Redis keyspace, security and extension rules.

[MIT](LICENSE)
