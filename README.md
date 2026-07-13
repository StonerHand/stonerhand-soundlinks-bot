<div align="center">

# 🎧 StonerHand Soundlinks Bot

### Drop a link — get a perfect post

**Track, album, playlist, podcast, YouTube or NTS Radio → a card with cover art,
auto-hashtags and buttons for every streaming platform. One tap.**

[Русская версия](README.ru.md) · [Architecture](ARCHITECTURE.ru.md) · [Bot](https://t.me/StonerHandBot) · [Channel](https://t.me/stonerhand)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot%20+%20Mini%20App-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-Serverless-000000?style=for-the-badge&logo=vercel&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-2ea44f?style=for-the-badge)

<img src="assets/studio-demo.svg" alt="Studio demo: search → vinyl → card with platform buttons" width="100%">

</div>

```text
in   →  https://open.spotify.com/track/...   (or just «black sabbath paranoid»)

out  →  📻 · Black Sabbath
        Paranoid

        кнопки ниже, трек ждет

        #stonerhand #track #heavymetal

        [🟢 Spotify] [⚪ Apple] [🟦 Deezer] [⚫ Tidal]
        [🪩 All platforms]
```

## What it does

- 🎛 **Studio** — a Mini App inside Telegram: live preview, pick from several matches, ▶ 30-sec audio preview right on the cover, custom text and hashtags, platform button set and order, ↗️ share to any chat, smart clipboard paste and post-publish undo
- 🧺 **Collection crate** — "➕ To crate" on any card, reorder, publish one playlist post
- 📸 **Photo mode** — the post ships as a photo with caption: artwork always on top on every client
- 🎨 **Living accent** — the card UI takes on the artwork's dominant color
- 🕒 **Scheduled posting** — "Schedule" in the Studio: the post goes to the channel by itself, the queue is visible and cancellable
- 🕘 **History** — recent releases on the Studio home screen, marked when already in the channel
- 📊 **Dashboard** — stats with charts right in the Mini App (admin)
- 🔎 **Search without a link** — type `artist - track`, the bot finds the release itself
- 🪄 **Inline** — `@StonerHandBot query` in any chat → pick from three releases with cover art
- 🎚 **Post editor** — hashtags, quote, preview size, 📤 to channel — right under the post
- 🛡 **Duplicate guard** — warns if the release was already published to the channel
- 🏷 **Auto genres** — `#doom`, `#hiphop` straight from iTunes metadata
- 📚 **Collections** — several links → a numbered playlist post
- 🤖 **Channel autopilot** — the admin bot silently swaps raw links for clean posts
- ⚡ **Live loading** — "⏳ building the post…" morphs into the card, zero dead air
- 🚀 **Serverless-fast** — warm instances, shared Redis cache, repeats are near-instant
- 🔁 **Self-healing** — a daily cron re-registers the webhook, menu and descriptions
- 🌍 **RU/EN** — the interface follows the user's Telegram language

Forwarded posts keep working: the CTA phrase is a live song.link hub link
(Telegram itself strips buttons on forward — for every bot out there).

## Quick start (Vercel, ~10 min)

1. Fork the repo → import into [Vercel](https://vercel.com) (Python preset, root `./`)
2. Add env: `BOT_TOKEN`, `SET_WEBHOOK_SECRET` (any long random string), `CRON_SECRET`
3. Deploy → open `https://<domain>/api/set_webhook?secret=<your secret>`
4. In [@BotFather](https://t.me/BotFather): `/setinline` → enable inline mode
5. Done. Send the bot a link

<details>
<summary><b>⚙️ All environment variables</b></summary>

| Variable | Purpose |
| --- | --- |
| `BOT_TOKEN` ⭐ | token from BotFather |
| `SET_WEBHOOK_SECRET` ⭐ | protects `/api/set_webhook` |
| `CRON_SECRET` | daily webhook self-healing via Vercel Cron |
| `UPSTASH_REDIS_REST_URL/TOKEN` | Redis: shared cache, live `/stats`, persistent drafts, dup guard, Studio history & queue |
| `ADMIN_CHAT_ID` | your chat id (`/id` command): private stats + the 📤 button |
| `PUBLISH_CHAT_ID` | where 📤 posts (defaults to `@stonerhand`) |
| `PRIMARY_PLATFORM` | which platform goes first: `spotify`, `appleMusic`, `tidal`… |
| `SONGLINK_USER_COUNTRIES` | Song.link regions, comma-separated, e.g. `US,DE` |
| `BOT_UI_MODE` | button style: `stonerhand` / `minimal` / `editorial` |
| `TELEGRAM_WEBHOOK_SECRET` | signs incoming updates (unset — derived from the bot token automatically) |
| `WEBAPP_URL`, `WEBHOOK_BASE_URL`, `STATS_PATH`, `LOG_LEVEL` | fine-tuning |

Vercel KV aliases (`KV_REST_API_URL/TOKEN`) work too. Without Redis everything lives in memory.
</details>

<details>
<summary><b>🚂 Railway / local (polling)</b></summary>

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m music_links_bot
```

`railway.toml` is already in the repo. Don't run polling alongside the Vercel webhook — you'll get duplicates.
</details>

## Under the hood

**Python 3.10+ · python-telegram-bot 21 · httpx · Song.link/Odesli · iTunes Search · Upstash Redis · Vercel**

```text
api/telegram.py      webhook + warm application reuse
api/webapp.py        Studio API (initData signature validation)
api/set_webhook.py   self-healing: webhook, commands, descriptions, menu button
webapp/index.html    the Studio Mini App
src/music_links_bot/
  bot.py             routing, keyboards, editor, inline, drafts
  songlink.py        cross-platform links + artwork + Redis cache
  search.py          name search and genres (iTunes)
  kvstore.py         Redis over REST, graceful fallback
  i18n.py            RU/EN interface
  formatter.py       post layout, hashtags, CTA
  …and a dozen small single-purpose modules
```

Full map: [ARCHITECTURE.ru.md](ARCHITECTURE.ru.md).

```bash
PYTHONPATH=src python -m pytest tests/   # 231 tests, no network
```

## Your channel instead of StonerHand

`constants.py` (channel, platforms) → `phrases.py` (voice) → `formatter.py` (layout) →
`.env` (`PUBLISH_CHAT_ID`, `PRIMARY_PLATFORM`). All the branding lives in these files.

<details>
<summary><b>🚑 Troubleshooting</b></summary>

| Symptom | Fix |
| --- | --- |
| Bot is silent | Check `BOT_TOKEN` in hosting env |
| Menu buttons dead | Open `/api/set_webhook?secret=…` (or wait for the nightly cron) |
| Duplicate posts | Polling and webhook both running — stop one |
| Links not replaced in channel | Grant the bot delete-messages right |
| `/stats` shows zeros | Plug in Redis (Upstash, free) |
| Inline not working | `/setinline` in BotFather + one `/api/set_webhook` call |
| Scheduled post is late | The queue ticks on any bot activity; for minute precision ping `GET /api/webapp` every 5 min (UptimeRobot, free) |
| Site root gives 404 | By design: the live paths are `/app` and `/api/*` |

</details>

## License

[MIT](LICENSE) — fork it, remix it, run it for your own channel. 🤘
