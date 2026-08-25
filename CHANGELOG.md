# Changelog

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
