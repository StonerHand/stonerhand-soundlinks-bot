# Changelog

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
