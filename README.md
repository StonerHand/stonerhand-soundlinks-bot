# StonerHandBot

[Русская версия](README.ru.md)

Telegram music-link bot built for [@stonerhand](https://t.me/stonerhand). Send a track, album, podcast, Spotify playlist, Spotify artist, YouTube video or a pack of links, and the bot turns them into a clean Telegram post with buttons.

It does not just return raw URLs. It formats every link as a small editorial card: artist, title, Telegram preview, StonerHand caption, hashtags and platform buttons. The bot copy is intentionally Russian, because it is tuned for the StonerHand channel voice.

## Features

- Resolves releases through Song.link / Odesli
- Accepts Spotify, Apple Music, Apple Podcasts, YouTube / YouTube Music, Deezer, Tidal, Yandex Music, SoundCloud and podcast links
- Reads links from regular messages and media captions
- Turns user-written notes above a link into Telegram quote blocks
- Supports tracks, albums, EPs, singles, podcasts, podcast shows, Spotify playlists, Spotify artists, YouTube videos and multi-link collections
- Gives tracks, albums, podcasts, playlists, artists and YouTube videos distinct editorial layouts
- Keeps posts lean: release-cover heading, human CTA, hashtags, preview and buttons
- Uses direct platform buttons for a single release
- Places short platform buttons two per row, with the channel button on its own row
- Uses playlist-style posts for multiple music links or mixed music + YouTube links
- Formats Spotify playlists as dedicated playlist posts with a direct `▶️ Открыть плейлист` button
- Formats Spotify artist links as dedicated artist cards with a direct `🧬 Открыть артиста` button
- Formats regular YouTube links as standalone video posts with a button and preview
- Treats only real YouTube video URLs as video posts: `watch`, `youtu.be`, `shorts`, `live` and `embed`
- Keeps `music.youtube.com` in the Song.link music lookup flow
- Stays silent on regular group/channel posts when there is no supported music link
- Selects Telegram preview by preferred platform
- Replaces source messages in groups/channels when the bot has admin rights
- Hides the `🪨 Открыть канал` self-link when posting directly inside `@stonerhand`
- Adds smart hashtags: `#track`, `#album`, `#collection`, `#single`, `#ep`, `#podcast`, `#show`, `#playlist`, `#artist`
- Keeps hashtags in groups and channels, but hides them in private chats
- Includes public stats and private admin stats via `/stats`, including playlist and artist counts
- Does not store message text or source links in stats

## Post Style

Single track:

```text
quote:
@username: немного тревоги на вечер

📻 · Youth Code
Transitions

ссылки готовы, звук рядом

#stonerhand #track
```

Album or EP:

```text
💿 · Artist
Release

альбом везде, где нужно

#stonerhand #album #ep
```

Podcast:

```text
🎙️ · Show Name
выпуск: Episode Title

выпуск на месте, кнопки ниже

#stonerhand #podcast
```

YouTube video:

```text
📺 · SANSAE Live Session Vol.3 - Melon
канал: SANSAE

экран готов, жми смотреть

#stonerhand #video
```

Spotify playlist:

```text
🎛 · Women of Punk
платформа: Spotify

пачка собрана, вход открыт

#stonerhand #playlist
```

Spotify artist:

```text
🧬 · 1.Kla$
артист: Spotify

профиль открыт, можно копать глубже

#stonerhand #artist
```

Collection:

```text
quote:
@username: пять вещей на вечер

сегодня в подборке:

1. 📻 · Youth Code - Transitions
2. 🎧 · Show Me The Body - Camp Orchestra
3. 💿 · The Soft Moon - Criminal

выбирай с чего начать

#stonerhand #collection #track #album
```

Mixed collection:

```text
quote:
@username: вечерний набор

сегодня в подборке:

1. 📻 · Youth Code - Transitions
2. 📺 · SANSAE Live Session Vol.3 - Melon

выбирай с чего начать

#stonerhand #collection #track #video
```

Single-release buttons:

```text
🟢 Spotify | 🍎 Apple
▶️ YouTube | 🟡 Yandex
🪨 Открыть канал
```

Spotify playlist buttons:

```text
▶️ Открыть плейлист
🪨 Открыть канал
```

Spotify artist buttons:

```text
🧬 Открыть артиста
🪨 Открыть канал
```

Collection buttons:

```text
1. Youth Code - Transitions | 2. Show Me The Body - Camp Orchestra
3. The Soft Moon - Criminal
🪨 Открыть канал
```

Inside `@stonerhand`, the self-link button is hidden automatically.

## Commands

- `/start` - начать
- `/help` - как кидать ссылки
- `/platforms` - что умею открыть
- `/channel` - канал StonerHand
- `/stats` - статистика бота

The public command menu is synced automatically on startup. Hidden utility command:
`/id` shows the current chat id for `ADMIN_CHAT_ID` setup.

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
- `ADMIN_CHAT_ID` enables private stats and admin notifications for channel processing errors
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
├── cache.py      small TTL cache for repeated external lookups
├── songlink.py   Song.link client and release normalization
├── formatter.py  StonerHand post style, hashtags, captions
├── playlist.py   Spotify playlist metadata through oEmbed
├── phrases.py    30 phrase variants per action
├── stats.py      local stats without message text or source links
├── url_utils.py  URL extraction and platform helpers
├── config.py     environment variables
├── youtube.py    YouTube oEmbed metadata for video posts
└── constants.py  platforms and aliases
```

## Reliability

- Multiple links are resolved in parallel
- Mixed music + YouTube packs are resolved in parallel and published as one collection post
- Multiple Song.link countries are checked in parallel
- Repeated Song.link, YouTube oEmbed and Spotify playlist lookups are cached in memory
- Long user notes are trimmed before posting
- Large link packs are limited to avoid Telegram limits
- URL hosts are normalized through parsed hostnames, so common variants like explicit ports do not break detection
- Stats are written atomically and protected from parallel writes
- Regular posts, Instagram/TikTok/Pinterest and other non-music links in groups/channels are ignored without admin spam
- YouTube video posts need no API key: title and channel are fetched through public oEmbed, with a safe fallback if metadata fails
- YouTube channel/profile links are ignored, so a regular `youtube.com/@channel` post will not trigger music lookup
- Spotify playlists do not go through Song.link; they use Spotify oEmbed metadata and fall back to a safe generic playlist title
- Spotify and Apple Podcasts episode/show links fall back to a platform-only post if Song.link has no cross-platform match
- Song.link outages, rate limits and temporary failures are handled separately from “release not found”

## Safety Notes

- Never commit `.env` or bot tokens
- If the bot does not answer after deploy, check `BOT_TOKEN` in Railway Variables first
- If the bot runs locally and on Railway at the same time, polling conflicts may happen
- Channel/group post replacement requires admin rights to delete messages
- `/stats` stores counters, ids, labels and last seen, but not message text or source links
