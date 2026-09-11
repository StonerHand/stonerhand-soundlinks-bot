<p align="center">
  <img src="../src/music_links_bot/assets/brandmark.png?v=132ca07bddeb" width="88" alt="Original StonerHand avatar: a clawed hand on white and turquoise">
</p>

<h1 align="center">StonerHand</h1>
<p align="center"><strong>Music in. Publish-ready Telegram post out.</strong></p>

<p align="center">
  <a href="https://t.me/StonerHandBot"><strong>Open the bot ↗</strong></a> ·
  <a href="https://t.me/stonerhand">See the channel</a> ·
  <a href="README.md">Documentation</a> ·
  <a href="../README.md">Русский</a>
</p>

<p align="center">
  <a href="https://github.com/StonerHand/stonerhand-soundlinks-bot/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/StonerHand/stonerhand-soundlinks-bot/ci.yml?branch=main&amp;style=flat-square&amp;label=CI&amp;color=00CDA8" alt="CI status for main"></a>
  <a href="../pyproject.toml"><img src="https://img.shields.io/badge/Python-3.10%2B-00CDA8?style=flat-square" alt="Python 3.10 or newer"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-00CDA8?style=flat-square" alt="MIT license"></a>
</p>

![Link → card → publish. Tracks, albums and collections in Telegram.](assets/hero.svg)

**StonerHand is a music publishing editor inside Telegram.** Send a link, an
`artist — title` query or an audio file. Get artwork, release details and service
buttons, add your own words, then preview and share. Several links become one
editable collection.

## From discovery to a finished post

| 01 · Find | 02 · Edit | 03 · Publish |
| --- | --- | --- |
| A link, search query, audio or up to 10 items | Intro, artwork, tags, buttons and a clean preview | Yourself, another chat, a channel or the scheduled queue |

Text above a link becomes the intro. Bold, italic and external links survive.
The editor stays open while a separate preview shows the finished publication.

### Edit directly below the post

```text
        Text           Tags
       Artwork        Buttons
       Preview         More
             Publish…
```

Common edits are one tap away. More contains collections, templates and extra
settings. Publish opens the channel, scheduling and send-to-self options;
regular users see Send instead. Drafts and search history live in My library.

## Inside the editor

| | Features |
| --- | --- |
| **Release cards** | Tracks, albums, EPs, compilations and soundtracks. Service branding is removed from titles; meaningful version and remaster details stay. |
| **Complete collections** | Up to 10 entries in one post, with a full list and matching button numbers. Sections, notes and public Spotify / Apple Music playlist imports. |
| **Useful tags** | Publication type takes priority, with up to 5 normalized automatic tags. Verified genres, individual toggles, custom additions and saved per-release corrections. |
| **Presentation controls** | Original artwork or a provider preview, collection collages, saved One column / Auto / Compact button layouts and reusable templates. |
| **Video and radio** | Playable YouTube previews and NTS Radio pages. Recording titles and sources stay separate; an uploader is not treated as the performer. |
| **Publishing tools** | Drafts, lookup history, undo, RU / EN, inline sharing and an administrator's scheduled queue. |

### Keep the full list

Example collection text; the bot adds artwork and link buttons:

> **Collection · 6 tracks**
>
> **Mindless Self Indulgence**<br>
> 1. Pay For It<br>
> 2. 1989<br>
> 3. Lights Out<br>
> 4. Tom Sawyer<br>
> 5. Seven Minutes in Heaven<br>
> 6. Witness
>
> #stonerhand #collection #track

Button numbers match the list. A shared artist is not repeated on every button;
mixed collections retain artist names. Long labels receive their own row.
Colors, fonts and label clipping depend on the Telegram client.

## Music sources

**Spotify · Apple Music · YouTube / YouTube Music · SoundCloud · Deezer · Tidal · Yandex Music · NTS Radio**

Songlink / Odesli connects a release across services. Cards use direct links to
resolved material; availability depends on the source and region. The main
“🎧 Listen to track” or “💿 Listen to album” button opens the release page
with available services; “🟢 Spotify” opens Spotify directly. If a release
hub is unavailable, the card keeps verified direct links. Collection genres
require agreement across all musical entries.

Search from another conversation: `@StonerHandBot artist — title`.

## Run your own bot

Use **Python 3.10+** and a separate bot token from [@BotFather](https://t.me/BotFather).

```bash
git clone https://github.com/StonerHand/stonerhand-soundlinks-bot.git
cd stonerhand-soundlinks-bot
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Set `BOT_TOKEN` in `.env`, then start polling:

```bash
python -m music_links_bot
```

Only the token is required locally. Redis is needed for durable production
state on Vercel. On Windows, activate with `.venv\Scripts\Activate.ps1` in
PowerShell and use `Copy-Item .env.example .env`.

## Quality and documentation

CI covers Python **3.10 / 3.11 / 3.12**, branch coverage, lint and dependencies.
Separate canaries check music providers and the deployed revision. Preview,
direct delivery and the queue share one publication pipeline.

An uncertain delivery asks the administrator to check the channel before a
retry. Unsupported Telegram enhancements fall back to classic cards.

Detailed operations and architecture documentation is maintained in Russian:

| Guide | Contents |
| --- | --- |
| [Documentation index](README.md) | Project navigation |
| [Setup and operations](SETUP.ru.md) | Local development, Vercel, Redis and checks |
| [Architecture](ARCHITECTURE.ru.md) | Lookup, editing, storage and delivery |
| [Release checklist](RELEASE_CHECKLIST.ru.md) | Automated and manual Telegram verification |
| [Changelog](../CHANGELOG.md) | Release history |

---

<p align="center"><a href="https://t.me/StonerHandBot"><strong>Create your first post ↗</strong></a><br><sub>StonerHand · Original artwork. Your words. Your music.</sub></p>
