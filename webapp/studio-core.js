const HTTP_URL = /^https?:\/\//i;
const QUERY_URL = /https?:\/\/[^\s<>"']+/gi;

export function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value == null ? "" : String(value);
  return node.innerHTML;
}

export function safeHttpUrl(value) {
  const url = String(value == null ? "" : value);
  return HTTP_URL.test(url) ? escapeHtml(url) : "";
}

export function analyzeQuery(value, maxLinks = 10) {
  const text = String(value == null ? "" : value).trim();
  const urls = text.match(QUERY_URL) || [];
  const uniqueUrls = [...new Set(urls)];
  const limit = Math.max(2, Number(maxLinks) || 10);
  return {
    empty: text.length === 0,
    mode: uniqueUrls.length >= 2 ? "batch" : "single",
    linkCount: Math.min(uniqueUrls.length, limit),
    overflow: Math.max(0, uniqueUrls.length - limit),
  };
}

export function pluralize(
  count,
  english,
  forms,
  isEnglish,
) {
  const value = Math.abs(Number(count));
  if (isEnglish) return value === 1 ? english[0] : english[1];
  const mod100 = value % 100;
  const mod10 = value % 10;
  if (mod100 > 10 && mod100 < 20) return forms[2];
  if (mod10 === 1) return forms[0];
  if (mod10 >= 2 && mod10 <= 4) return forms[1];
  return forms[2];
}

export function assessDraft(state, copy) {
  const release = state?.release || {};
  const flags = state?.flags || {};
  const enabledPlatforms = (release.platforms || []).filter(
    (platform) => platform?.enabled !== false && HTTP_URL.test(String(platform?.url || "")),
  );
  const tags = flags.hashtags
    ? String(release.hashtags || "").split(/\s+/).filter(Boolean)
    : [];
  const checks = [
    {
      key: "platforms",
      ok: enabledPlatforms.length > 0,
      blocking: enabledPlatforms.length === 0,
      label: enabledPlatforms.length
        ? copy.platforms(enabledPlatforms.length)
        : copy.noPlatforms,
    },
    {
      key: "text",
      ok: Boolean(String(release.cta || "").trim()),
      blocking: false,
      label: String(release.cta || "").trim() ? copy.textReady : copy.noText,
    },
    {
      key: "artwork",
      ok: (
        release.artwork_failed !== true
        && HTTP_URL.test(String(release.artwork || ""))
      ),
      blocking: false,
      label: release.artwork && release.artwork_failed !== true
        ? copy.artworkReady
        : copy.noArtwork,
    },
    {
      key: "hashtags",
      ok: !flags.hashtags || (tags.length >= 1 && tags.length <= 8),
      blocking: false,
      label: !flags.hashtags
        ? copy.cleanText
        : tags.length > 8
          ? copy.tooManyTags
          : copy.tagsReady(tags.length),
    },
  ];
  const completed = checks.filter((check) => check.ok).length;
  return {
    checks,
    score: Math.round((completed / checks.length) * 100),
    blockers: checks.filter((check) => check.blocking),
    enabledPlatforms: enabledPlatforms.length,
    ready: checks.every((check) => !check.blocking),
  };
}

export function assessCollection(items, meta, copy) {
  const collection = Array.isArray(items) ? items : [];
  const details = meta || {};
  const checks = [
    {
      key: "tracks",
      ok: collection.length >= 2,
      blocking: collection.length < 2,
      label: collection.length >= 2 ? copy.tracks(collection.length) : copy.needTracks,
    },
    {
      key: "title",
      ok: Boolean(String(details.title || "").trim()),
      blocking: false,
      label: details.title ? copy.titleReady : copy.noTitle,
    },
    {
      key: "notes",
      ok: collection.some((item) => Boolean(String(item?.meta?.note || "").trim())),
      blocking: false,
      label: collection.some((item) => Boolean(String(item?.meta?.note || "").trim()))
        ? copy.notesReady
        : copy.noNotes,
    },
  ];
  return {
    checks,
    score: Math.round((checks.filter((check) => check.ok).length / checks.length) * 100),
    blockers: checks.filter((check) => check.blocking),
    ready: checks.every((check) => !check.blocking),
  };
}

export function createDraftSnapshot(state) {
  if (!state?.draft_id || !state?.release) return null;
  return {
    version: 1,
    draftId: String(state.draft_id),
    artist: String(state.release.artist || ""),
    title: String(state.release.title || ""),
    artwork: (
      state.release.artwork_failed !== true
      && HTTP_URL.test(String(state.release.artwork || ""))
    )
      ? String(state.release.artwork)
      : "",
    emoji: String(state.release.emoji || "🎵"),
    updatedAt: Date.now(),
  };
}

export function parseDraftSnapshot(raw, maxAgeMs = 48 * 60 * 60 * 1000) {
  try {
    const value = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (
      !value ||
      value.version !== 1 ||
      typeof value.draftId !== "string" ||
      !value.draftId ||
      !Number.isFinite(Number(value.updatedAt)) ||
      Date.now() - Number(value.updatedAt) > maxAgeMs
    ) {
      return null;
    }
    return value;
  } catch {
    return null;
  }
}
