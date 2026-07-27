const HTTP_URL = /^https?:\/\//i;
const QUERY_URL = /https?:\/\/[^\s<>"']+/gi;
const LONGREAD_BLOCK_TYPES = new Set([
  "paragraph", "heading", "quote", "list", "details", "divider",
]);

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
  const publication = state?.publication || {};
  const longread = publication.mode === "longread"
    ? normalizeLongread(publication.longread, release)
    : null;
  const hasEditorialText = Boolean(
    release.title || (longread && longread.title),
  );
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
      ok: hasEditorialText,
      blocking: false,
      label: hasEditorialText ? copy.textReady : copy.noText,
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

function cleanText(value, limit = 1800) {
  return String(value == null ? "" : value)
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join("\n")
    .slice(0, limit);
}

function blockId(value, index) {
  const candidate = String(value || "");
  return /^[A-Za-z0-9_-]{1,32}$/.test(candidate)
    ? candidate
    : `block-${index + 1}`;
}

export function normalizeLongread(value, release = {}) {
  const source = value && typeof value === "object" ? value : {};
  const defaultTitle = [release.artist, release.title].filter(Boolean).join(" — ");
  const title = cleanText(source.title || defaultTitle, 140);
  const lead = cleanText(source.lead, 420);
  let remaining = Math.max(0, 22_000 - title.length - lead.length);
  const budgeted = (input, limit = 1800) => {
    if (remaining <= 0) return "";
    const result = cleanText(input, Math.min(limit, remaining));
    remaining -= result.length;
    return result;
  };
  const rawBlocks = Array.isArray(source.blocks) ? source.blocks : [];
  const blocks = rawBlocks.slice(0, 24).flatMap((raw, index) => {
    if (remaining <= 0) return [];
    if (!raw || typeof raw !== "object" || !LONGREAD_BLOCK_TYPES.has(raw.type)) return [];
    const id = blockId(raw.id, index);
    if (raw.type === "divider") return [{ id, type: "divider" }];
    if (raw.type === "list") {
      const items = (Array.isArray(raw.items) ? raw.items : [])
        .slice(0, 16).map((item) => budgeted(item, 320)).filter(Boolean);
      return items.length ? [{ id, type: "list", ordered: Boolean(raw.ordered), items }] : [];
    }
    if (raw.type === "details") {
      const detailsTitle = budgeted(raw.title, 120), text = budgeted(raw.text);
      return detailsTitle && text
        ? [{ id, type: "details", title: detailsTitle, text, open: Boolean(raw.open) }]
        : [];
    }
    const text = budgeted(raw.text);
    return text ? [{ id, type: raw.type, text }] : [];
  });
  return {
    title,
    lead,
    blocks,
  };
}

export function markdownToLongread(markdown, release = {}) {
  const lines = String(markdown || "").replace(/\r/g, "").split("\n");
  const blocks = [];
  let title = "";
  let lead = "";
  let paragraph = [];
  let list = [];
  let ordered = false;
  const flushParagraph = () => {
    const text = cleanText(paragraph.join("\n"));
    if (text) blocks.push({ id: `block-${blocks.length + 1}`, type: "paragraph", text });
    paragraph = [];
  };
  const flushList = () => {
    if (list.length) blocks.push({
      id: `block-${blocks.length + 1}`, type: "list", ordered, items: list.slice(0, 16),
    });
    list = []; ordered = false;
  };
  lines.forEach((raw) => {
    const line = raw.trim();
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    const bullet = line.match(/^[-*+]\s+(.+)$/);
    const numbered = line.match(/^\d+[.)]\s+(.+)$/);
    const quote = line.match(/^>\s?(.*)$/);
    if (!line) { flushParagraph(); flushList(); return; }
    if (heading) {
      flushParagraph(); flushList();
      if (!title && heading[1].length === 1) title = cleanText(heading[2], 140);
      else blocks.push({ id: `block-${blocks.length + 1}`, type: "heading", text: cleanText(heading[2]) });
      return;
    }
    if (bullet || numbered) {
      flushParagraph();
      const nextOrdered = Boolean(numbered);
      if (list.length && ordered !== nextOrdered) flushList();
      ordered = nextOrdered;
      list.push(cleanText((bullet || numbered)[1], 320));
      return;
    }
    if (quote) {
      flushParagraph(); flushList();
      blocks.push({ id: `block-${blocks.length + 1}`, type: "quote", text: cleanText(quote[1]) });
      return;
    }
    if (/^([-*_])\1\1+$/.test(line.replace(/\s/g, ""))) {
      flushParagraph(); flushList();
      blocks.push({ id: `block-${blocks.length + 1}`, type: "divider" });
      return;
    }
    if (!lead && title && blocks.length === 0 && paragraph.length === 0) {
      lead = cleanText(line, 420);
      return;
    }
    paragraph.push(line);
  });
  flushParagraph(); flushList();
  return normalizeLongread({ title, lead, blocks }, release);
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
