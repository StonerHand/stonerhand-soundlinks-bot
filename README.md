# StonerHandBot

Music linker for Telegram. Drop a music URL, get a clean post with release metadata, platform buttons, Telegram preview, author note and StonerHand hashtags.

Built for [@stonerhand](https://t.me/stonerhand). Works in private chats, groups and channels.

## Core

StonerHandBot accepts links to tracks, albums, EPs, singles, podcast episodes and multi-link collections. It resolves them through Song.link / Odesli, formats the result as a channel-ready post, and keeps the buttons readable.

Single release:

- direct platform buttons
- preview from the preferred platform
- release-specific CTA
- automatic hashtags

Collection:

- one playlist-style post
- one Song.link button per release
- compact button labels
- collection hashtags

## Features

- Compact buttons: `Spotify`, `Apple`, `YouTube`, `Deezer`, `Tidal`, `Yandex`
- Input links from Spotify, Apple Music, YouTube / YouTube Music, Deezer, Tidal, Yandex Music, SoundCloud and Song.link-compatible podcast sources
- Tracks, albums, EPs, singles, podcasts and collections
- Spotify podcast episode/show fallback when Song.link has no cross-platform match
- Platform priority with `PRIMARY_PLATFORM`
- Parallel lookup for multiple links
- Smart hashtags: `#track`, `#album`, `#collection`, `#single`, `#ep`, `#podcast`, `#show`
- User note line: `@username: text`
- Direct compact platform buttons for one release
- Song.link buttons for collections
- Channel button: `🪨 Открыть канал`
- Group/channel message replacement when the bot has admin rights
- Public stats plus private admin stats

## Post Examples

Track:

```text
@username: немного тревоги на вечер

📻 · Youth Code - Transitions

ссылки готовы, звук ждет

#stonerhand #track
```

EP:

```text
💿 · Artist - Release

альбом на всех выходах

#stonerhand #album #ep
```

Podcast:

```text
🎙️ · Show Name - Episode Title

слушай выпуск там, где удобно

#stonerhand #podcast
```

Podcast show fallback:

```text
🎙️ · Spotify - Podcast show

выпуск готов, осталось выбрать площадку

#stonerhand #podcast #show
```

Collection:

```text
@username: пять вещей на вечер

сегодня в подборке:

1. 📻 · Youth Code - Transitions
2. 🎧 · Show Me The Body - Camp Orchestra
3. 💿 · The Soft Moon - Criminal

выбирай, куда провалиться

#stonerhand #collection #track #album
```

Collection buttons:

```text
1. Youth Code - Transitions
2. Show Me The Body - Camp Orchestra
3. The Soft Moon - Criminal
🪨 Открыть канал
```

Single-release buttons stay compact:

```text
Spotify
Apple
YouTube
Yandex
🪨 Открыть канал
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

Recommended values:

```env
BOT_TOKEN=your-telegram-bot-token
SONGLINK_API_KEY=
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
ADMIN_CHAT_ID=
PRIMARY_PLATFORM=spotify
```

`BOT_TOKEN` is required. `SONGLINK_API_KEY` is optional. `ADMIN_CHAT_ID` enables private stats for your personal chat. `PRIMARY_PLATFORM` controls preview selection and button order.

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

Railway runs the bot as a background worker, so your Mac and Zed can be closed.

1. Push the project to GitHub
2. Create a Railway project from the GitHub repo
3. Add `BOT_TOKEN` in `Variables`
4. Add `ADMIN_CHAT_ID` and `PRIMARY_PLATFORM` if needed
5. Wait for `Deployment successful`

`railway.toml` already defines:

```bash
pip install -r requirements.txt
```

```bash
PYTHONPATH=src python -m music_links_bot
```

## Render Deploy

Render needs a `Background Worker`, because the bot uses polling and does not expose an HTTP port. `render.yaml` is included, but Render may require payment details for worker services.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Notes

- Never commit `.env` or bot tokens
- If the bot does not answer after deploy, check `BOT_TOKEN` first
- If Railway and a local bot run at the same time, stop the local process
- Message replacement in groups/channels requires admin rights to delete messages
- If Song.link cannot resolve a Spotify podcast episode/show, the bot still returns a Spotify-only podcast post instead of an error
- Private stats do not store message text or source links; they store counters, ids, labels and last-seen time
