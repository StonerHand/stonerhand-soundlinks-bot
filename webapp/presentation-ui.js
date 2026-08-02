import { normalizePreset } from "/webapp/studio-presets.js";

export function normalizePresentation(state) {
  const source = state?.presentation && typeof state.presentation === "object"
    ? state.presentation
    : {};
  const preset = normalizePreset(source.preset, state);
  const release = state?.release || {};
  const flags = state?.flags || {};
  return {
    version: Number(source.version) || 1,
    preset,
    mode: preset === "longread" ? "longread" : "card",
    artist: String(source.artist || release.artist || ""),
    title: String(source.title || release.title || ""),
    emoji: String(source.emoji || release.emoji || "🎵"),
    showCover: preset !== "minimal" && (
      source.show_cover !== undefined
        ? Boolean(source.show_cover)
        : Boolean(release.artwork)
    ),
    showHashtags: source.show_hashtags !== undefined
      ? Boolean(source.show_hashtags)
      : Boolean(flags.hashtags && release.hashtags),
  };
}

export function cardMode(state) {
  const presentation = normalizePresentation(state);
  if (presentation.mode === "longread") return "longread";
  return presentation.preset === "minimal" ? "compact" : "large";
}
