# StonerHand bot — working notes

Telegram bot that turns music, video and film links into channel-ready posts.
Python 3.11+, python-telegram-bot 22, Vercel serverless (`api/*.py`), Upstash Redis.

## Project structure

`src/music_links_bot/` is split into 11 packages by purpose; each `__init__.py` says what
belongs there. The full table is in `docs/ARCHITECTURE.ru.md` («Структура кода»).

Layers, bottom to top (a package imports only from packages below it):

- `core/`: settings, constants, models (releases, presentation presets and preferences, the draft), metadata cleanup, i18n, URL/text/time helpers, caches, metrics.
- `tg/`: Bot API wrappers (gateway, buttons, callback action registry, HTML text and its limits, messages, ephemeral, effects).
- `state/`: Redis store, sessions/runtime (`bot_runtime`), drafts storage, the crate, publication state, stats.
- `artwork/`: signed `/api/collage` images, collages, frames, cover signature.
- `providers/`: one module per external service, plus release hub links, registry and provider runtime.
- `cards/`: card texts, keyboards, share links, tags, publication text budget and contract.
- `publishing/`: channel posts, publication view and service, schedule queue, receipts.
- `lookup/`, `editor/`, `chat/`: the scenarios, on one layer and allowed to call each other. `lookup` turns a message into results and delivers them; `editor` is the draft editor; `chat` is app wiring, dispatcher, commands, menus, settings, inline mode, data deletion.
- `ops/`: production-only bits on top (alerts, release smoke, polling worker, QStash).

Rules:
- Imports are absolute (`from music_links_bot.lookup.track_lookup import …`).
- Package `__init__.py` files import nothing.
- The layer order is an import-linter contract in `pyproject.toml`; `lint-imports` runs in CI. If a lower package needs something from a higher one, move that code down instead of importing upwards.
- After moving code between packages run `python scripts/package_map.py --write` (it redraws the map in `docs/ARCHITECTURE.ru.md`; `tests/test_package_map.py` fails while it is stale).
- New code goes into the package whose description fits. A new external service is a new module in `providers/`.

## Checks before a PR

```bash
.venv/bin/python -m ruff check src api tests && .venv/bin/python -m ruff format --check src api tests
PYTHONPATH=src .venv/bin/python -m coverage run -m pytest -q && .venv/bin/python -m coverage report
PYTHONPATH=src .venv/bin/python -m mypy
PYTHONPATH=src .venv/bin/lint-imports
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
