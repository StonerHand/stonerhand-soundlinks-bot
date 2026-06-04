---
name: stonerhand-bot-editorial-ui
description: Use when changing Telegram post design, copywriting, buttons, phrases, hashtags, previews, commands, onboarding, or channel editorial style for StonerHand Soundlinks Bot.
---

# StonerHand Bot Editorial UI

Use this skill for visual and text changes in the bot.

## Style Direction

The bot should feel like a music-channel editor, not a generic utility bot:

- compact
- human
- slightly gritty
- mobile-first
- not overloaded
- consistent across tracks, albums, podcasts, video, radio, playlists, artists, and collections

## Main Files

| Area | File |
| --- | --- |
| Post layout | `src/music_links_bot/formatter.py` |
| Buttons | `src/music_links_bot/bot.py` |
| Platform names | `src/music_links_bot/constants.py` |
| CTA phrases | `src/music_links_bot/phrases.py` |
| Commands and onboarding | `src/music_links_bot/bot.py` |
| UI tests | `tests/test_formatter.py`, `tests/test_phrases.py` |

## Post Rules

- User note above a link should become a quote block.
- Track and album posts should not look like long reports.
- Keep the first visual block strong: icon, artist/title, CTA, hashtags.
- Buttons should be easy to hit on mobile.
- Platform buttons should usually be two per row.
- Hide the channel button inside the home channel `@stonerhand`.
- Keep the channel button in other chats.
- Avoid final periods in short bot phrases unless the sentence needs it.
- Avoid long dash in Telegram copy if a simple hyphen feels cleaner.

## Content Types

| Type | Feeling |
| --- | --- |
| Track | fast, direct, one-tap listening |
| Album / EP | whole-release mood |
| Podcast | conversation, episode, show |
| YouTube | video card, watch action |
| NTS | radio/session/archive mood |
| Spotify playlist | collection / playlist transition |
| Spotify artist | artist profile card |
| Multi-link collection | editorial playlist post |

## HTML Safety

Telegram messages use `ParseMode.HTML`.

Always escape user-controlled content:

```python
html.escape(value)
```

Allowed useful tags:

```html
<b>...</b>
<i>...</i>
<blockquote>...</blockquote>
```

Do not introduce unsupported Telegram HTML tags.

## Preview Reality

Telegram decides final preview rendering per client. The code can request:

- large preview
- preview above text
- preview URL

But it cannot fully control image size or layout on every Telegram version.

## Validation

For UI changes:

```bash
PYTHONPATH=src python -m unittest tests.test_formatter tests.test_phrases -v
git diff --check
```

Then test manually in Telegram with:

- Spotify track
- Spotify album
- SoundCloud link
- YouTube link
- NTS link
- Spotify playlist
- Spotify artist
- Message with user text + link
- Message with several links
