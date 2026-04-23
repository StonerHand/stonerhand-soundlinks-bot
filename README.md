# StonerHandBot

[Русская версия](README.ru.md)

Telegram music-link bot built for [@stonerhand](https://t.me/stonerhand). Send a track, album, podcast or a pack of release links, and the bot turns them into a clean Telegram post with streaming buttons.

It does not just return raw URLs. It formats every link as a small editorial card: artist, title, Telegram preview, StonerHand caption, hashtags and platform buttons.

## Features

- Resolves releases through Song.link / Odesli
- Accepts Spotify, Apple Music, YouTube / YouTube Music, Deezer, Tidal, Yandex Music, SoundCloud and podcast links
- Reads links from regular messages and media captions
- Supports tracks, albums, EPs, singles, podcasts, podcast shows and multi-link collections
- Uses direct platform buttons for a single release
- Uses playlist-style posts for multiple links
- Selects Telegram preview by preferred platform
- Replaces source messages in groups/channels when the bot has admin rights
- Adds smart hashtags: `#track`, `#album`, `#collection`, `#single`, `#ep`, `#podcast`, `#show`
- Includes public stats and private admin stats via `/stats`
- Does not store message text or source links in stats

## Post Style

Single track:

```text
@username: a little tension for tonight

📻 · Youth Code - Transitions

links are ready, the sound is waiting

#stonerhand #track
```

Album or EP:

```text
💿 · Artist - Release

album exits are ready

#stonerhand #album #ep
```

Podcast:

```text
🎙️ · Show Name - Episode Title

listen wherever it feels right

#stonerhand #podcast
```

Collection:

```text
@username: five things for the evening

today in the stack:

1. 📻 · Youth Code - Transitions
2. 🎧 · Show Me The Body - Camp Orchestra
3. 💿 · The Soft Moon - Criminal

choose where to fall in

#stonerhand #collection #track #album
```

Single-release buttons:

```text
Spotify
Apple
YouTube
Yandex
🪨 Open channel
```

Collection buttons:

```text
1. Youth Code - Transitions
2. Show Me The Body - Camp Orchestra
3. The Soft Moon - Criminal
🪨 Open channel
```

## Commands

- `/start` - intro and main buttons
- `/help` - usage help
- `/guide` - short guide for a group or channel
- `/platforms` - supported platforms
- `/channel` - open StonerHand
- `/id` - show chat id for `ADMIN_CHAT_ID`
- `/stats` - release stats

## Environment

Create `.env` from the example:

```bash
cp .env.example .env
```

Minimal setup:

```env
BOT_TOKEN=your-telegram-bot-token
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
PRIMARY_PLATFORM=spotify
```

Full setup:

```env
BOT_TOKEN=your-telegram-bot-token
SONGLINK_API_KEY=
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
ADMIN_CHAT_ID=
PRIMARY_PLATFORM=spotify
```

Important:

- `BOT_TOKEN` is required
- `SONGLINK_API_KEY` is optional
- `SONGLINK_USER_COUNTRIES=US` usually gives broader international coverage
- `ADMIN_CHAT_ID` enables private stats and admin notifications
- `PRIMARY_PLATFORM` controls preview selection and button order

Supported `PRIMARY_PLATFORM` values:

- `spotify`
- `appleMusic`
- `applePodcasts`
- `youtubeMusic`
- `deezer`
- `tidal`
- `yandexMusic`

## Local Run

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
PYTHONPATH=src python -m music_links_bot
```

On macOS, stop the local process with `Control + C`.

## Railway Deploy

Railway runs the bot as a background worker. After deploy, your Mac and Zed can be closed, and the bot stays online.

1. Push the code to GitHub
2. Create a Railway project from the repository
3. Open the `worker` service
4. Add `BOT_TOKEN`
5. Add `SONGLINK_USER_COUNTRIES=US`
6. Optionally add `ADMIN_CHAT_ID` and `PRIMARY_PLATFORM`
7. Wait for `Deployment successful`

`railway.toml` already defines:

```bash
pip install -r requirements.txt
```

```bash
PYTHONPATH=src python -m music_links_bot
```

## Render Deploy

Render can work too, but this bot needs a `Background Worker`. Some Render accounts ask for payment details even for free-like setups, so Railway is simpler for this project.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Architecture

```text
src/music_links_bot/
├── bot.py        Telegram handlers, keyboards, group/channel replacement
├── songlink.py   Song.link client and release normalization
├── formatter.py  StonerHand post style, hashtags, captions
├── phrases.py    30 phrase variants per action
├── stats.py      local stats without message text or source links
├── url_utils.py  URL extraction and platform helpers
├── config.py     environment variables
└── constants.py  platforms and aliases
```

## Reliability

- Multiple links are resolved in parallel
- Multiple Song.link countries are checked in parallel
- Long user notes are trimmed before posting
- Large link packs are limited to avoid Telegram limits
- Stats are written atomically and protected from parallel writes
- Spotify podcast episode/show links fall back to a Spotify-only post if Song.link has no cross-platform match
- Song.link outage errors are handled separately from “release not found”

## Safety Notes

- Never commit `.env` or bot tokens
- If the bot does not answer after deploy, check `BOT_TOKEN` in Railway Variables first
- If the bot runs locally and on Railway at the same time, polling conflicts may happen
- Channel/group post replacement requires admin rights to delete messages
- `/stats` stores counters, ids, labels and last seen, but not message text or source links
