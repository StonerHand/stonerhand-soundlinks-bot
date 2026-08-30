# Changelog

## Unreleased

## 1.13.0 — 2026-08-30

- Turned empty inline mode into a personal discovery surface with up to three
  recent releases, a live fallback example and a persistent Find music action.
- Added a first-visit Try an example action beside the packaged onboarding tour.
- Replaced generic error menus with one contextual recovery action per failure.
- Added compact native confirmations for editor and collection mutations,
  reduced editor-setting undo to 30 seconds and retained 15-second destructive undo.
- Added a terminal Post ready screen with Create another as its primary action.
- Strengthened the production UI contract around descriptive labels, named
  destructive actions, two-button rows and matching RU/EN hierarchy while
  explicitly removing the arbitrary 28–32-character accessibility rule.
- Documented the required BotFather inline placeholder and expanded release tests.

## 1.12.0 — 2026-08-30

- Rebuilt the visual hierarchy around one primary action: Songlink/Odesli owns
  the universal release CTA, provider shortcuts and sharing stay neutral, and
  the home screen no longer adds a second accent for a non-empty collection.
- Added a shared button-icon vocabulary with optional Bot API 10.3 custom emoji
  IDs and complete regular-emoji fallbacks, including Rich button conversion.
- Added a deterministic packaged five-second first-visit animation that shows
  the link → card → publish flow once without delaying later `/start` screens.
- Reordered Rich cards into a magazine layout and removed duplicated release
  titles below artwork while retaining complete Classic fallback behavior.
- Replaced verbose editor diagnostics with a one-line cover/tags/platform/mode
  summary and added a clean preview action that sends the exact final post
  through the production delivery pipeline without publication side effects.
- Reworked lookup progress into a stable three-stage checklist, enabled safe
  ephemeral group errors and Rich drafts by default, and kept public/classic
  fallbacks for clients or chats that do not support the new capabilities.
- Expanded UI, first-run, custom-icon, preview, publication and release-smoke
  regressions; updated operations, architecture and RU/EN product documentation.

## 1.11.0 — 2026-08-30

- Expanded the read-only production smoke contract with RU/EN home screens,
  editor actions and settings. It now blocks missing primary actions, cramped
  rows, empty or oversized callbacks, long labels and any reintroduced Mini App.
- Made the production canary verify smoke contract v2 and the complete UI/UX
  matrix in addition to the seven publication scenarios.
- Cancelled and awaited active Songlink single-flight lookups before closing
  HTTP transports, preventing background tasks from surviving shutdown.
- Added a batch fallback regression that guarantees one source status per
  submitted link and protects collection counts during provider failures.
- Made CI execute the full test suite on every supported Python version
  (3.10, 3.11 and 3.12) while retaining the complete quality/security gate on 3.12.
- Normalized `asyncio.wait_for` timeout handling across Python 3.10–3.12 so
  genre enrichment, playlist import and status diagnostics keep their intended
  soft fallbacks instead of leaking `asyncio.TimeoutError` on Python 3.10.
- Updated Ruff to 0.16.5 and completed a clean dependency, vulnerability,
  dead-code, secret, repository and Graphify architecture audit.

## 1.10.1 — 2026-08-30

- Removed Spotify branding and SEO phrases such as
  `Album by … | Spotify` from release, artist and playlist names.
- Normalized titles at the shared model and durable-draft boundaries so cached
  and previously saved cards cannot reintroduce provider copy.
- Added regressions for Spotify albums, tracks, playlists, legacy drafts,
  Classic cards and Rich release smoke output.
- Removed millisecond-level runner jitter from the ten-source batch integrity
  test while preserving its concurrency and provider-budget contract.

## 1.10.0 — 2026-08-29

- Added one final publication contract shared by Classic, Rich, inline,
  channel, photo/audio and editor delivery. It blocks visible music-source
  URLs, invalid partial counts, unsafe or search destinations, broken
  universal buttons, missing required artwork and Telegram limit violations
  before a post can leave the bot.
- Added a deterministic seven-case release matrix for a universal track,
  SoundCloud-only source, complete and partial collections, channel-safe
  keyboard, inline share and Rich artwork/buttons, with a reviewed golden snapshot.
- Added the read-only `/api/smoke` production endpoint and made the guarded
  production canary verify the complete publication matrix after every deploy.
- Added 500 deterministic fuzz cases for provider URLs, punctuation, CRLF,
  emoji/UTF-16 entities and safe external editorial links.
- Extracted lookup delivery and safe Telegram message deletion from the central
  bot controller, reducing its size while preserving existing interaction
  points and fallbacks.
- Updated architecture, release operations and product documentation for the
  new pre-delivery contract and production smoke gate.

## 1.9.2 — 2026-08-29

- Removed clickable Spotify, Apple Music and other supported source links from
  author intros when Telegram hides them behind linked text; meaningful anchor
  text and surrounding bold or italic formatting stay intact.
- Hardened URL-boundary handling so the end of a message is never mistaken for
  whitespace, and normalized common typographic punctuation around shared URLs.
- Expanded regression coverage across supported providers, message boundaries,
  multiple sources, CRLF input, emoji/UTF-16 entities, media captions, external
  editorial links and the complete bot delivery path.

## 1.9.1 — 2026-08-29

- Fixed source-URL removal when a Spotify, Apple Music or another supported
  music link is the first character of a message followed by an editorial intro.
- Preserved the complete intro and its entity mapping instead of leaking the
  source URL into the quote and truncating the final character.
- Added URL utility, Telegram HTML and end-to-end post regressions for the exact
  album-link-first message shape reported from production.

## 1.9.0 — 2026-08-29

- Split editor callbacks and native Force Reply handling into focused state and
  input modules while preserving the existing Telegram interaction contract.
- Replaced the monolithic lookup controller with a linear request pipeline for
  admission, source resolution, access checks, progress and delivery.
- Separated pure Rich HTML rendering from Telegram transport, keeping the
  public compatibility surface and complete Classic fallback unchanged.
- Moved every RU/EN interface string into a packaged JSON catalog with
  placeholder and completeness contracts; shortened the main delivery action
  to **Send to me** / **Отправить себе**.
- Split editor UI tests from the large bot integration suite and refreshed the
  golden keyboard snapshot for the compact action label.
- Removed duplicated orchestration code, reducing the executable Python
  surface without removing product features.

## 1.8.2 — 2026-08-28

- Removed the legacy compatibility surface from the central bot module: command,
  inline, lookup and UI symbols are now imported directly from their owning
  modules by the application assembler and tests.
- Deleted dead empty lookup adapters and a redundant mixed-preview wrapper,
  and collapsed repeated editor-screen rendering into one declarative mapping.
- Centralized HTTP request headers and the durable statistics key so provider,
  privacy and admin paths no longer maintain independent copies.
- Simplified small return paths and health degradation checks without changing
  user-visible behavior; focused regression tests cover the resulting module
  boundaries before the full release gate.

## 1.8.1 — 2026-08-28

- Removed synthetic Spotify search buttons: a platform now appears only when
  the resolver returned a direct release URL for that exact card.
- Sanitized legacy search destinations across cached lookups, durable drafts,
  editor selections, publication preflight, keyboards and inline sharing.
- Versioned the aggregate lookup cache so previously generated search links
  disappear immediately after deployment.
- Added a regression for the SoundCloud-only Ethan Kath Park Live DJ set and
  release contracts for direct provider links.

## 1.8.0 — 2026-08-28

- Added signed, cached 2–4-cover collages to classic collection link previews;
  duplicate or unavailable artwork falls back to the existing single-cover
  card, while Rich Telegram collections keep their native media layout.
- Compressed signed collage payloads to stay within Telegram-safe URL limits,
  added immutable ETags and warm HTTP connection reuse, and kept incomplete
  collections on a deliberately honest single-cover preview.
- Added an independent collection-artwork health contract to the production
  canary, so a release cannot pass while its new preview endpoint is missing.
- Added `COLLECTION_COLLAGE_ENABLED` as a deploy-free kill switch; global safe
  mode also disables the enhancement without affecting complete Classic cards.
- Simplified collection previews while keeping the full localized release
  count: repeated type icons and artists are removed, provider remaster
  suffixes are hidden, and Classic and Rich cards now use the same layout.
- Made collection keyboards content-adaptive: repeated artists and remaster
  suffixes are omitted from button labels, short actions share a row, and long
  labels receive the full width with word-boundary shortening.
- Split provider resolution from Telegram result delivery while preserving the
  existing bot-facing compatibility surface, reducing the largest lookup
  module and making provider changes safer to review.
- Added one immutable publication plan shared by preview and every delivery
  path, plus strict normalization of current and legacy durable drafts before
  any Telegram call.
- Batched current and legacy session restoration into one Redis request, with
  compatibility fallback for mixed-version workers and local adapters.
- Prevented duplicate progress edits and added release contracts for complete
  RU/EN localization with identical formatting placeholders.
- Added bounded request p95 and cache-hit telemetry without retaining request
  content or growing per-process memory over time.

## 1.7.0 — 2026-08-26

- Fixed the publication pipeline so the editor's hashtag choice is respected
  identically in preview, direct send, channel publishing and queued delivery;
  channel mode can no longer silently re-enable disabled hashtags.
- Centralized final hashtag resolution in the canonical publication view,
  removing duplicate formatting logic from the delivery service.
- Updated semantic buttons to use the native typed `style` field in
  python-telegram-bot 22.8 with central validation and focused Bot API fallbacks.
- Restored discoverability of Help, Services, Channels, Demo and Privacy from
  the main screen under one compact **More** action.
- Made independent home-state reads concurrent and clarified first-run,
  creation, hashtag and profile guidance without adding interface levels.
- Added channel-publication regressions for disabled hashtags and tightened
  release-readiness contracts for package metadata and the public repository.
- Removed unused Docker configuration, internal assistant instructions and a
  local statistics artifact from the product tree.
- Rebuilt the English and Russian README files as concise product, operations
  and release documentation; refreshed package metadata, CI concurrency,
  dependency grouping and production environment guidance.

## 1.6.1 — 2026-08-26

- Fixed incorrect automatic genre hashtags caused by trusting the first
  relevance-ranked Apple Search result without verifying its artist or title.
- Genre enrichment now requires an exact punctuation-normalized artist and
  track/collection match; uncertain metadata produces no genre tag instead of
  publishing a confidently wrong one.
- Versioned the aggregate lookup cache so previously cached false tags such as
  `#rnb` on Knocked Loose disappear immediately after deployment.
- Added regressions for wrong-artist results, Unicode apostrophes, album-title
  matching and the safe structural-tag fallback.

## 1.6.0 — 2026-08-25

- Added cancellable lookup progress with a Classic-client fallback and
  cross-instance request generations, so a cancelled or superseded search can
  no longer publish a stale result after another Vercel invocation wins.
- Added a Redis-backed per-user burst limit with a clear retry time instead of
  letting accidental request storms overload music providers.
- Added `/privacy` with a two-step destructive confirmation and deletion of
  sessions, drafts, crates, history, templates, inline history, personal stats
  labels and user-owned scheduled posts while retaining anonymous totals.
- Added an anonymous `request → resolve → edit → publish` funnel and persisted
  provider circuit state; `/status`, `/stats` and health now distinguish a
  degraded music provider from a complete bot outage.
- Added `BOT_SAFE_MODE` plus a dedicated inline Rich-media flag, providing one
  emergency switch back to complete Classic Telegram cards without disabling
  lookup or publishing.
- Added a guarded production rollback path: only the exact newly deployed
  unhealthy commit can trigger Vercel Instant Rollback, never a stale build or
  an unreadable external health endpoint.
- Added a real-client release matrix for Telegram iOS, Android, Desktop and Web,
  and refreshed English, Russian and architecture documentation for the new
  safety, privacy and operations controls.
- Expanded regression coverage for rate limiting, stale cross-instance
  requests, provider degradation, privacy deletion, queue ownership, feature
  flags, anonymous stats and rollback eligibility.

## 1.5.0 — 2026-08-25

- Hardened the release pipeline: CI now runs the complete configured Ruff
  ruleset, verifies deterministic formatting and executes the full pytest
  collection instead of relying on a narrower lint/test subset.
- Normalized the entire Python codebase and removed all full-lint findings,
  including stale suppressions, ambiguous exception boundaries and inconsistent
  imports.
- Tightened exception handling and documented the few deliberate broad catches
  at HTTP, alerting and best-effort media boundaries so fallback guarantees
  remain explicit and testable.
- Added release contracts for Vercel route/build/cron alignment and CI quality
  gates so deployment configuration cannot silently drift from the code.
- Refreshed public documentation and architecture for the adaptive Bot API 10.3
  inline path: Rich Messages require reusable Telegram artwork, while classic
  shares retain the large cover and complete keyboard.

## 1.4.4 — 2026-08-25

- Restored large artwork in shared track cards: inline delivery now selects
  Rich Message only when a reusable Telegram cover `file_id` is available and
  otherwise uses the classic large-preview card instead of dropping artwork.
- Versioned fresh share queries again so Telegram cannot reuse the cached
  no-artwork result; all previous compact and legacy share buttons still parse.

## 1.4.3 — 2026-08-25

- Restored the **All platforms** action and made Spotify tracks resolve to a
  real canonical `song.link/s/<id>` page even while metadata uses the Spotify
  fallback; albums and podcasts use their matching Odesli hubs.
- Removed invalid nested Song.link URLs and centralized release-hub resolution
  for lookup results, keyboards and provider fallbacks.
- Upgraded single-release inline shares to Bot API 10.3 Rich Message content
  with in-message button rows, semantic styles and an automatic classic retry.
- Made inline Rich media spec-compliant: cached Telegram `file_id` artwork is
  reused when available, while remote artwork is never sent in an invalid
  inline Rich payload.
- Added regressions for the reported Lime Garden release, canonical hubs,
  cached Rich artwork and Telegram's Rich-to-classic fallback.
- Versioned new share queries to bypass Telegram's cached pre-fix inline cards
  immediately while keeping older share buttons backward-compatible.

## 1.4.2 — 2026-08-25

- Hid the misleading release-hub action when its destination duplicates a
  Spotify or another platform button, including tracking URL variants.
- Kept all real platform buttons visible when no distinct universal release
  page is available.

## 1.4.1 — 2026-08-25

- Hardened durable draft migration: unknown future fields and unsafe URLs no
  longer break strict release reconstruction after a Redis cold start.
- Made Telegram text limits use the rendered UTF-16 length, including emoji,
  and added a safe fallback for malformed HTML.
- Paginated the complete admin queue while preserving item numbering and the
  current page after refresh or cancellation.
- Made localized commands, menu and profile descriptions synchronize
  independently; fixed the English command scope using Russian descriptions.
- Split audio, Rich Message, photo and classic-card delivery into isolated
  paths without changing their fallback order.
- Versioned provider requests, disabled caching on operational API responses
  and added dependency vulnerability auditing to CI.
- Updated runtime dependencies and expanded the release suite to 507 tests.

## 1.4.0 — 2026-08-24

- Expanded the Telegram-native composer: uploaded audio becomes an editable
  publication, and any release card can use a user-supplied cover.
- Added explicit Auto and Classic Telegram delivery modes with the existing
  lossless Rich Message fallback kept in Auto mode.
- Added reusable named design templates, up to five reversible setting steps
  and a preflight check that blocks invalid delivery before it reaches Telegram.
- Added an admin queue dashboard with refresh and per-item cancellation.
- Added best-effort track import from public Spotify and Apple Music playlists.
- Coalesced matching cross-platform links into one release with the union of
  service buttons while preserving per-source diagnostics and retry state.
- Isolated aggregate caches for custom client bundles while retaining one
  stable Redis namespace across production cold starts and deployments.
- Added regressions for audio delivery, custom covers, templates, playlist
  extraction, queue UI, preflight validation, session recovery and cache scope.
- Extended the release suite to 502 automated tests.

## 1.3.0 — 2026-08-24

- Added a Bot API 10.3 compatibility gateway for Rich Messages, Rich drafts,
  in-place Rich edits and the new ephemeral-message parameter contract.
- Upgraded finished cards, collections and song + video posts to structured
  Rich HTML with artwork groups and platform actions inside the publication.
- Added automatic capability cooldown and a lossless fallback to the existing
  HTML/photo delivery path for unsupported methods, old nodes and media errors.
- Added native disabled progress buttons with a classic-client fallback.
- Added a transport-neutral music publication model, strict rich-fragment and
  action URL sanitization, and bounded Rich Message output.
- Added Redis-backed Telegram cover `file_id` reuse to avoid downloading and
  uploading the same artwork repeatedly.
- Added Rich delivery/fallback metrics and regression coverage for the 10.3
  payloads, builders, editing, media cache and sanitization.
- Extended the release suite to 479 automated tests.

## 1.2.0 — 2026-08-20

- Rebuilt the native card actions around one unmistakable primary button and
  neutral secondary controls; editor screens now use one accent action each.
- Added a reusable “same as last time” format, full Telegram formatting for
  author intros and a dynamic character budget for messages and photo captions.
- Made partial batches explain every failed source and offer replacement of a
  specific link without rebuilding the collection manually.
- Added source-aware progress, short in-place confirmations and named item
  actions in the collection editor.
- Centralized semantic Telegram button construction and introduced a versioned,
  typed draft schema v4.
- Split editor rendering and lookup accounting out of the orchestration modules,
  keeping cache/source invariants in a dedicated typed layer.
- Added per-provider request, success-rate, average-latency, fallback, timeout
  and rate-limit metrics to runtime diagnostics and health persistence.
- Added stable UI snapshots plus regressions for formatted intros, dynamic
  limits, reusable templates and provider metrics.
- Extended the release suite to 468 automated tests.

## 1.1.4 — 2026-08-12

- Made multi-link resolution source-accountable: every unique input now has
  exactly one ordered status and complete-cache entries must match every item.
- Prevented slow sources at the beginning of a batch from starving later
  links; five paced provider slots let all ten accepted sources receive their
  complete per-source deadline inside the webhook budget.
- Kept one-item partial results as visibly incomplete collections across
  music, video, radio, playlist, artist and mixed cards.
- Removed finished-share actions from all partial results and made retry
  atomically rebuild the complete original collection.
- Added support for Telegram links hidden behind text entities and deduplicated
  tracking variants in lookup and share queries.
- Stopped transient Song.link outages from fanning out regional requests,
  while keeping the independent Spotify metadata fallback available even when
  the provider circuit is open.
- Removed raw source and signed artwork URLs from diagnostics and added batch,
  timeout, cache-repair, hidden-link and partial-card regression coverage.
- Extended the release suite to 459 automated tests.

## 1.1.3 — 2026-08-12

- Recovered Spotify releases that Song.link misses in its primary region by
  checking bounded secondary regions and stable public Spotify page metadata.
- Retried false Spotify `not found` results once and made the failed source
  individually retryable in private chats.
- Prevented incomplete inline collections from being cached or reshared as a
  finished post; partial cards now offer an explicit recheck action.
- Replaced raw failed-source URLs in lookup logs with anonymous diagnostic IDs.
- Extended the release suite to 442 automated tests.

## 1.1.2 — 2026-08-12

- Protected health-to-worker calls with a stable purpose-specific secret when
  the Vercel `CRON_SECRET` variable exists but has an empty value.
- Kept an explicit `CRON_SECRET` authoritative and isolated the derived worker
  credential from Telegram's webhook credential.
- Extended the release suite to 432 automated tests.

## 1.1.1 — 2026-08-12

- Derived the protected queue-worker origin from Telegram's registered HTTPS
  webhook when optional Vercel hostname variables are absent.
- Kept explicit production URLs authoritative and rejected unsafe fallback
  origins.
- Extended the release suite to 429 automated tests.

## 1.1.0 — 2026-08-12

Production stabilization and performance release.

- Removed durable-queue processing from Telegram's webhook request path; queue work now stays in the dedicated protected worker.
- Canonicalized aggregate lookup keys, so tracking variants of the same links share cache and single-flight work.
- Added Spotify metadata fallback for transient Song.link outages, with a short shared fallback TTL that upgrades to a full platform result after recovery.
- Matched partial provider results by canonical source URL instead of fragile list position.
- Cancelled metadata enrichment that cannot finish before rendering instead of leaking background work past the response.
- Made a full queue explicit and lossless: existing scheduled posts are never silently evicted, and the user receives a specific recovery message.
- Aligned batch input, native crate and scheduling limits: 10 sources per post and a 90-day queue horizon.
- Consolidated Redis health reads, parallelized independent production checks, made worker failures and overdue jobs fail the canary, and ignored active queue leases.
- Added deployed version and commit identity to `/api/health`; the production canary now detects a stale deployment.
- Extended regression coverage to 426 automated tests and tightened lint/type hygiene.

## 1.0.0 — 2026-08-12

First production-stable release of the Telegram-only StonerHand editor.

- Native card builder with explicit style, text, hashtags, services, preview and delivery screens.
- Single releases, multi-link collections, song + video posts, playlists, artists, podcasts and NTS Radio.
- Button-preserving sharing, inline search, personal delivery, channel publishing and a durable scheduled queue.
- Redis-backed sessions, drafts, history, collections, deduplication, queue leases and provider diagnostics.
- Partial-result delivery, single-flight lookups, short negative cache and provider circuit breakers.
- Mobile-friendly keyboards, reversible settings, safe destructive actions and cancellable native input.
- Russian and English UI, 406 automated tests, CI security checks and a production canary.
