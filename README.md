<div align="center">

# 🎧 StonerHand Soundlinks Bot

### Drop a link — get a perfect post

**Track, album, playlist, podcast, YouTube or NTS Radio → a card with cover art,
auto-hashtags and buttons for every streaming platform. One tap.**

[Русская версия](README.ru.md) · [Architecture](ARCHITECTURE.ru.md) · [Bot](https://t.me/StonerHandBot) · [Channel](https://t.me/stonerhand)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot%20+%20Mini%20App-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-Serverless-000000?style=for-the-badge&logo=vercel&logoColor=white)
![CI](https://img.shields.io/github/actions/workflow/status/StonerHand/stonerhand-soundlinks-bot/ci.yml?style=for-the-badge&label=CI)
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

## 🎛 The Studio — a Mini App inside Telegram

A visual post editor: opens from the menu button or the 🎛 button under any post.

- **Search** — free text with a candidate picker, a link, or straight from the
  clipboard (the Studio offers to paste a copied link on open)
- **▶ Audio preview** — 30 seconds of the track right on the cover, with a progress
  ring and an equalizer
- **Style sheet** — one panel with amp-style rocker switches: hashtags, quote,
  📸 photo mode, preview size + your own text, custom tags and the platform button
  set and order
- **Action dock** — publish is always pinned at the bottom; schedule, crate and
  share sit next to it
- **Undo** — 5 seconds to take a published post back out of the channel
- **🧺 Collection crate** — collect tracks from any cards → one playlist post
- **🕒 Scheduled posting** — "in an hour / tonight / custom", the queue is visible
  and cancellable
- **🕘 History** — recent releases marked "already in the channel" + typeahead
- **📊 Dashboard** — stats with charts (admin)
- **🎨 Living accent** — the card takes on the artwork's dominant color
- **☀️🌙 Light & dark themes** — follows Telegram, with a header toggle
- **📱 Bottom tab bar** — Home / Crate / Queue / Stats; Unbounded + Golos Text + JetBrains Mono type

## What the bot itself does

- 🔎 **Search without a link** — DM `artist - track`
- 🪄 **Inline** — `@StonerHandBot query` in any chat → pick from three releases
- 🎚 **Chat editor** — compact toggles and 📤 "To channel" right under the post
- 🛡 **Duplicate guard** — warns if the release was already published
- 🏷 **Auto genres** — `#doom`, `#hiphop` straight from iTunes metadata
- 📚 **Collections** — several links → a numbered playlist post
- 🤖 **Channel autopilot** — the admin bot silently swaps raw links for clean posts
- 🫥 **Invisible group replies** — only the person who dropped the link sees the card (opt-in, `EPHEMERAL_GROUP_REPLIES`)
- ⚡ **Live loading** — "⏳ building the post…" morphs into the card
- 🌍 **RU/EN** — the interface follows the user's Telegram language

Forwarded posts keep working: the CTA phrase is a live song.link hub link
(Telegram itself strips buttons on forward — for every bot out there).

## 🩺 Reliability

- **CI** — GitHub Actions runs 252 tests, the linter and a JS check on every push
- **`/api/health`** — the bot's pulse: Telegram API, webhook registration, Redis;
  it also delivers due scheduled posts
- **Owner alerts** — when a health check fails, a scheduled post is dropped or the
  webhook starts crashing, the bot DMs you (at most once per hour per problem)
- **Self-healing** — a daily cron re-registers the webhook, menu and descriptions
- **Secure by default** — the webhook secret is derived from the bot token
  automatically; updates cannot be forged even with zero configuration

**Tip:** point a free [UptimeRobot](https://uptimerobot.com) monitor at
`https://<domain>/api/health` every 5 minutes — that single ping covers outage
detection, alerts, minute-precise scheduling and warm instances.

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
| `UPSTASH_REDIS_REST_URL/TOKEN` | Redis: shared cache, live `/stats`, persistent drafts, dup guard, Studio history/queue, alert dedup (the crate lives client-side in the Mini App, so it works without Redis) |
| `ADMIN_CHAT_ID` | your chat id (`/id` command): private stats, the 📤 button and alerts |
| `PUBLISH_CHAT_ID` | where 📤 posts (defaults to `@stonerhand`) |
| `PRIMARY_PLATFORM` | which platform goes first: `spotify`, `appleMusic`, `tidal`… |
| `SONGLINK_USER_COUNTRIES` | Song.link regions, comma-separated, e.g. `US,DE` |
| `BOT_UI_MODE` | button style: `stonerhand` / `minimal` / `editorial` |
| `EPHEMERAL_GROUP_REPLIES` | `1` — in groups the bot replies "invisibly" (only the person who dropped the link sees the card). Opt-in; falls back to a normal reply when Telegram doesn't support it |
| `TELEGRAM_WEBHOOK_SECRET` | signs incoming updates (unset — derived from the bot token automatically) |
| `WEBAPP_URL`, `WEBHOOK_BASE_URL`, `STATS_PATH`, `LOG_LEVEL` | fine-tuning |

Vercel KV aliases (`KV_REST_API_URL/TOKEN`) work too. Without Redis everything lives in instance memory.
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
api/telegram.py      webhook: warm reuse, queue tick, crash alert
api/webapp.py        Studio API (initData signature, drafts, queue, crate)
api/health.py        pulse: Telegram/webhook/Redis + alerts + queue tick
api/set_webhook.py   self-healing: webhook, commands, descriptions, menu button
webapp/index.html    the Studio Mini App — one file, vanilla JS
src/music_links_bot/
  bot.py             routing, keyboards, editor, inline, drafts
  publish_queue.py   scheduled publications queue
  songlink.py        cross-platform links + artwork + Redis cache
  search.py          search, genres and audio previews (iTunes)
  alerts.py          owner DMs about problems (deduped via Redis)
  kvstore.py         Redis over REST, graceful fallback
  i18n.py            RU/EN interface
  formatter.py       post layout, hashtags, CTA
  …and a dozen small single-purpose modules
```

Full map: [ARCHITECTURE.ru.md](ARCHITECTURE.ru.md).

```bash
PYTHONPATH=src python -m pytest tests/   # 252 tests, no network
```

## Your channel instead of StonerHand

`constants.py` (channel, platforms) → `phrases.py` (voice) → `formatter.py` (layout) →
`.env` (`PUBLISH_CHAT_ID`, `PRIMARY_PLATFORM`). All the branding lives in these files.

<details>
<summary><b>🚑 Troubleshooting</b></summary>

| Symptom | Fix |
| --- | --- |
| Bot is silent | Open `/api/health` — it tells you what broke |
| Menu buttons dead | Open `/api/set_webhook?secret=…` (or wait for the nightly cron) |
| Duplicate posts | Polling and webhook both running — stop one |
| Links not replaced in channel | Grant the bot delete-messages right |
| `/stats` shows zeros | Plug in Redis (Upstash, free) |
| Inline not working | `/setinline` in BotFather + one `/api/set_webhook` call |
| Scheduled post is late | Ping `/api/health` every 5 min (UptimeRobot) — every ping ticks the queue |
| No alerts arriving | Check `ADMIN_CHAT_ID` (the `/id` command) |
| Site root gives 404 | By design: the live paths are `/app`, `/api/health` and `/api/*` |

</details>

## License

[MIT](LICENSE) — fork it, remix it, run it for your own channel. 🤘
