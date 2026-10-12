<p align="center">
  <img src="../src/music_links_bot/assets/brandmark.png?v=132ca07bddeb" width="96" alt="StonerHand avatar: a clawed hand on white and turquoise">
</p>

<h1 align="center">StonerHand SoundLinks</h1>

<p align="center"><strong>One music link in — a publish-ready Telegram post out.</strong></p>

<p align="center">
  <a href="https://t.me/StonerHandBot"><strong>Open the bot ↗</strong></a> ·
  <a href="https://t.me/stonerhand">Channel</a> ·
  <a href="../README.md">Русский</a>
</p>

<p align="center">
  <img src="assets/hero.png" width="100%" alt="A link becomes a post with artwork, tags and platform buttons">
</p>

## ✨ Features

- 🔗 **Any link or query** — Spotify, Apple Music, YouTube, SoundCloud, Deezer, Tidal, Bandcamp, Yandex Music, NTS, or just `artist — track`.
- 🖼 **Posts with artwork** — signed cover, title, year, length, smart hashtags and buttons for every platform.
- 🎶 **Collections** — up to 10 tracks, albums and videos in one post with a shared collage.
- ✏️ **In-chat editor** — your own text, tags, look and buttons.
- 📣 **Channel publishing** — now, on a schedule ("tomorrow 18:30") or with one-tap quick publish; 2 minutes to undo.
- ⚡ **Inline mode** — `@StonerHandBot artist — track` in any chat.

| Channel post | Draft in the bot | Collection with videos |
| :---: | :---: | :---: |
| <img src="assets/post.png" width="240" alt="Channel post"> | <img src="assets/draft.png" width="240" alt="Draft card"> | <img src="assets/collection.png" width="240" alt="Collection post"> |

## 🛠 Run your own

Python 3.10+ and a bot token from [@BotFather](https://t.me/BotFather):

```bash
git clone https://github.com/StonerHand/stonerhand-soundlinks-bot.git
cd stonerhand-soundlinks-bot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # set BOT_TOKEN
python -m music_links_bot
```

Production runs on Vercel (webhook) with Upstash Redis for state and Upstash QStash for scheduled posts. The full guide is in Russian: [SETUP.ru.md](SETUP.ru.md), [ARCHITECTURE.ru.md](ARCHITECTURE.ru.md).

[MIT](../LICENSE) © StonerHand
