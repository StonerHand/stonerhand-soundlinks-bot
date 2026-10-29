# StonerHand bot — working notes

Telegram bot that turns music, video and film links into channel-ready posts.
Python 3.11+, python-telegram-bot 22, Vercel serverless (`api/*.py`), Upstash Redis.

## Project structure

`src/music_links_bot/` is split into 11 packages by purpose; each `__init__.py` says what
belongs there. The full table is in `docs/ARCHITECTURE.ru.md` («Структура кода»).

- `core/`: settings, constants, models, errors, i18n, URL/text/time helpers, caches.
- `ops/`: production-only bits (alerts, release smoke, polling worker, QStash, metrics).
- `tg/`: Bot API wrappers (gateway, buttons, HTML text, messages, ephemeral, effects).
- `state/`: Redis store, sessions/runtime (`bot_runtime`), drafts storage, stats, privacy.
- `providers/`: one module per external service, plus registry and provider runtime.
- `lookup/`: a message becomes results; progress, Stop, delivery back to the chat.
- `cards/`: card texts, keyboards, share links, tags, release hubs.
- `artwork/`: signed `/api/collage` images, collages, frames, cover signature.
- `editor/`: the draft model, editor card and screens, sending a draft.
- `publishing/`: channel posts, publication contract, schedule queue, receipts.
- `chat/`: app wiring, dispatcher, commands, menus, settings, crate, inline mode.

Rules:
- Imports are absolute (`from music_links_bot.lookup.track_lookup import …`).
- Package `__init__.py` files import nothing.
- New code goes into the package whose description fits. A new external service is a new module in `providers/`.

## Checks before a PR

```bash
.venv/bin/python -m ruff check src api tests && .venv/bin/python -m ruff format --check src api tests
PYTHONPATH=src .venv/bin/python -m coverage run -m pytest -q && .venv/bin/python -m coverage report
PYTHONPATH=src .venv/bin/python -m mypy
```

Anything that changes how messages are sent, edited or deleted must also be replayed on the full app with realistic updates:
- a private link;
- a group link with a real `from`;
- a channel post auto-forwarded into its discussion group (`from` 777000, `sender_chat`, `is_automatic_forward`);
- a channel post;
- inline mode;
- draft → Publish.

Use a fake Telegram transport and a fakeredis-backed Upstash (`tests/test_audit_reliability.RedisREST`).

## Behaviour that must not regress

- The user's intro quote above a link is always shown in full, never folded.
- In groups a card replaces the link message publicly (card, then delete). Invisible cards only with `EPHEMERAL_GROUP_CARDS=1`.
- A timed-out *new* message is never sent again or deleted (it may have landed); only edits are retried.
- YouTube cards ask for Telegram's own player first and fall back to the signed frame.
- Progress is a real message edited into the result. It appears only when a lookup takes longer than a second. Telegram drafts are not used.
- UI text is Russian (and English), informal «ты».

## Releasing

1. Bump the version in `src/music_links_bot/__init__.py` and `pyproject.toml`.
2. Add a `CHANGELOG.md` entry, in Russian.
3. Merge after green CI.
4. Wait until `/api/health` reports the commit.
5. Run `CANARY_EXPECT_COMMIT=<full sha> python tests/e2e/production_canary.py`.
6. Run `gh release create v<version> --target <full sha>`.
