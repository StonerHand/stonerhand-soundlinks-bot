<div align="center">

# 🎧 StonerHand Soundlinks Bot

### Music link → ready-to-publish Telegram post

[Open bot](https://t.me/StonerHandBot) · [Channel](https://t.me/stonerhand) · [Русский](README.ru.md) · [Architecture](ARCHITECTURE.ru.md)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=flat-square&logo=telegram&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-Production-000?style=flat-square&logo=vercel)
![CI](https://img.shields.io/github/actions/workflow/status/StonerHand/stonerhand-soundlinks-bot/ci.yml?style=flat-square&label=CI)

</div>

StonerHand is a Telegram-native music publishing editor. It turns a release
link, an `artist — title` query or a batch of links into a finished post without
opening a separate web interface.

## Features

- accepts a music URL, an `artist — track` query or an uploaded audio file;
- resolves release metadata, artwork and platform links;
- builds a clean Telegram card with compact buttons;
- keeps a canonical **All platforms** Songlink/Odesli hub even when metadata
  temporarily falls back to Spotify;
- uses Telegram Rich Messages for structured cards, native media groups and
  in-content actions, with an automatic classic-card fallback;
- combines several links into one numbered collection;
- merges links from different services into one release instead of duplicate cards;
- imports discovered tracks from public Spotify and Apple Music playlists;
- pairs a song and YouTube clip in one clickable Rich media post;
- includes a native builder with style, intro, hashtag, platform and Telegram-format screens;
- saves named design templates and accepts custom artwork per card;
- keeps exactly one primary action on editor screens and edits the active message in place;
- preserves bold, italic, links and other Telegram formatting in author intros;
- calculates the available intro length for the exact card or photo caption;
- reapplies saved publication formats and undoes up to five setting changes;
- offers a clean final preview and returns to the active card by release name;
- remembers card preferences and keeps timestamped recent posts;
- names, previews, reorders and deduplicates collections;
- sends to the user, another chat or a configured channel;
- shows a compact final check before channel publication;
- includes a paginated admin dashboard for the durable scheduled-publishing queue;
- uses an explicit bot timezone for fixed and custom publication times;
- lets the user cancel any native text input with `/cancel`;
- works inline: `@StonerHandBot artist — track`;
- explains incomplete batches per source and lets the user replace a failed link by number;
- can keep group replies visible only to the requesting user through opt-in
  ephemeral messages on Bot API 10.3.

A single message accepts up to 10 unique sources — the same explicit limit as
the editable crate. Duplicate and tracking variants are removed before lookup.

Supported sources include Spotify, Apple Music, YouTube, SoundCloud, Bandcamp,
Deezer, Tidal, Yandex Music, podcasts, Spotify and Apple Music playlists,
Spotify artists and NTS Radio.

## Flow

```mermaid
flowchart LR
    A["Link or release name"] --> B["Resolve"]
    B --> C["Card or collection"]
    C --> D["Edit inside Telegram"]
    D --> E["Self · chat · channel · queue"]
```

Cards keep only useful information: artwork, artist, title, hashtags selected
by the user, chosen services and the complete release hub. Secondary actions
appear only in context. Multi-link inputs are not quoted back into the result.
Style, intro, hashtags, platforms, Telegram format, preview and delivery have
explicit screens. A preflight check blocks delivery without a title, usable
link or selected platform. Free-form intro, artwork and tags are entered through
native Telegram replies. Intro
formatting is preserved, while its live limit adapts to Telegram's regular
message or photo-caption budget instead of silently cutting the release card.
The editor remembers previous and named formats. **Auto** uses Rich Messages
with a safe fallback; **Classic** always sends a regular Telegram card.

The primary **Create post** action opens a native input guide for all three
input shapes: a release or artist link, an `artist — title` query, or several
links for a collection. Restoring an unfinished card is a separate named
secondary action and never replaces the main flow.

Lookup uses visible `1/3 → 3/3` progress. Every accepted source receives an
ordered success/failure status; one slow provider call cannot cancel completed
siblings or starve later links. An incomplete result stays visibly marked as
`3 of 4`, cannot be shared as finished, and its recovery action rebuilds the
entire original collection in the same order.
Each failed position also has a **Replace #N** action, so a mistyped or private
URL can be corrected without reconstructing the rest of the batch.
All output is checked against Telegram's rendered UTF-16 message and caption
limits before delivery, including emoji, with a safe fallback for oversized or
malformed formatted text.
Transient Song.link failures fall back to Spotify metadata for Spotify URLs;
the **All platforms** action still opens a canonical `song.link/s/<id>` page
instead of disappearing or duplicating the Spotify destination. Albums and
podcasts use their matching `album.link` and `pods.link` hubs.
regional misses are checked against bounded secondary regions and stable
public Spotify page metadata. The short fallback cache is automatically
replaced by the complete platform result after the provider recovers.
Incomplete regular and inline collections are never cached or offered as
finished shares; their action rechecks every original source instead. Links
hidden behind Telegram text entities are resolved too, while tracking variants
are deduplicated before lookup and sharing.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
PYTHONPATH=src python -m music_links_bot
```

Minimum environment:

```env
BOT_TOKEN=...
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
PRIMARY_PLATFORM=spotify
```

Production also uses webhook secrets and Upstash Redis. `CRON_SECRET` is
recommended for direct Vercel Cron calls; when it is blank, protected internal
worker calls derive an isolated credential from `BOT_TOKEN`. Fixed
schedule choices use `BOT_TIMEZONE` (`Europe/Moscow` by default); custom dates
can be scheduled up to 90 days ahead.

`RICH_MESSAGES_ENABLED=1` enables the Bot API 10.3 presentation layer and is
on by default. Single-release inline shares use Rich Message content and native
button rows. Inline artwork is embedded only when Telegram has a reusable
`file_id`, as required by the API; unsupported methods, old nodes and media
failures retry as the existing HTML/photo card automatically.
`RICH_DRAFTS_ENABLED=0`
keeps experimental streamed drafts off by default. `EPHEMERAL_GROUP_REPLIES=1`
enables private-to-requester group results.

## Validation

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src api tests
python -m pyflakes src api tests
python -m ruff check src api tests --select F,B,ASYNC,PERF
python -m bandit -q -r src api -x tests
python -m pip_audit -r requirements.txt --progress-spinner off
python tests/check_dependency_pins.py
python -m json.tool vercel.json >/dev/null
```

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Layout

```text
api/                    webhook, health, webhook setup and queue worker
src/music_links_bot/    orchestration, typed lookup, editor, providers and persistence
tests/                  unit and integration tests
vercel.json             production routes and cron jobs
```

Production runs on Vercel using a Telegram webhook. The webhook only processes
Telegram updates; scheduled posts are leased by the protected queue worker.
Redis stores caches, reusable Telegram cover `file_id` values,
sessions, drafts, collections, history, the publishing queue and deduplication
claims. Stored state is versioned and automatically migrates legacy records.
Non-critical flows have a bounded in-memory fallback.

`/api/health` reports Telegram, webhook, Redis, queue worker, queue state,
runtime metrics and the exact deployed version/commit. The production canary
rejects stale deployments, a failed worker and an overdue durable queue.
Provider diagnostics include request volume, success rate, average latency,
fallbacks, timeouts and rate limits. Runtime metrics also expose Rich Message
attempts, failures and automatic fallbacks.

License: [MIT](LICENSE).
