---
name: stonerhand-bot-audit
description: Use when auditing, refactoring, optimizing, or stabilizing the StonerHand Soundlinks Bot repository. Applies to code quality, Telegram bot behavior, supported link routing, performance, tests, docs, privacy, and public-release cleanup.
---

# StonerHand Bot Audit

Use this skill for full-project passes on StonerHand Soundlinks Bot.

## First Read

Before changing code, read only what is needed:

- `ARCHITECTURE.ru.md` for the system map
- `README.md` and `README.ru.md` for public behavior
- `src/music_links_bot/bot.py` for Telegram flow
- `src/music_links_bot/url_utils.py` for link routing
- `src/music_links_bot/formatter.py` for UI
- `src/music_links_bot/songlink.py` for platform lookup

## Audit Workflow

1. Check `git status --short --branch`.
2. Inspect recent changes with `git diff --stat` and targeted `git diff`.
3. Search for fragile spots with `rg "TODO|FIXME|print\\(|except Exception|pass$|BOT_TOKEN|ghp_|rapidapi|X-RapidAPI-Key"`.
4. Verify no secrets, generated junk, local stats, or `.env` content are being committed.
5. Review message flow: private chat, group, channel, channel replacement, no-link silence, unsupported-link silence.
6. Review supported link types: music releases, podcasts, SoundCloud, YouTube, NTS, Spotify playlist, Spotify artist.
7. Run focused tests first, then full tests if code changed.
8. Update `README.md`, `README.ru.md`, and `ARCHITECTURE.ru.md` if behavior changed.

## Quality Rules

- Keep handlers thin; put parsing, lookup, formatting, and stats into separate modules.
- Preserve async behavior and avoid blocking network calls.
- Use `html.escape` for anything that goes into `ParseMode.HTML`.
- Do not add downloader functionality without a separate legal and product review.
- Do not store private message text or raw personal links in stats.
- Do not make the bot noisy in channels or groups.
- Prefer small, explicit helpers over clever dense code.
- Keep Telegram posts mobile-first: compact, readable, not overloaded.

## Validation

Use these checks when available:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests api
git diff --check
```

For public repo safety:

```bash
rg -n "ghp_|x-rapidapi-key|X-RapidAPI-Key|[0-9]{6,}:[A-Za-z0-9_-]{20,}" .
```

## Common Failure Modes

- Webhook and polling active at the same time causing duplicate responses.
- Vercel root page showing `404`, which is normal because the bot lives on API routes.
- Missing `BOT_TOKEN` or stale webhook after moving hosts.
- Telegram preview looking different across clients.
- Unsupported channel posts producing noisy admin logs.
- New platform added to formatter but not to URL detection or tests.
