export const PRESET_ORDER = ["minimal", "cover", "longread"];

const LEGACY_PRESETS = {
  clean: "cover",
  editorial: "minimal",
  poster: "cover",
};

export function normalizePreset(value, state) {
  const raw = String(value || "").toLowerCase();
  if (PRESET_ORDER.includes(raw)) return raw;
  if (state?.publication?.mode === "longread") return "longread";
  if (LEGACY_PRESETS[raw]) return LEGACY_PRESETS[raw];
  if (state?.flags?.large_preview === false) return "minimal";
  return "cover";
}

export function presetDefinitions(english = false) {
  return english ? [
    { key:"minimal", icon:"—", title:"Minimal", copy:"Text-first, compact preview" },
    { key:"cover", icon:"▣", title:"Cover", copy:"Artwork and a playable card" },
    { key:"longread", icon:"¶", title:"Longread", copy:"Article with a block editor" },
  ] : [
    { key:"minimal", icon:"—", title:"Минимал", copy:"Текст и компактное превью" },
    { key:"cover", icon:"▣", title:"Обложка", copy:"Арт и карточка с плеером" },
    { key:"longread", icon:"¶", title:"Лонгрид", copy:"Материал с блочным редактором" },
  ];
}

export function presetPatch(value) {
  const preset = normalizePreset(value);
  if (preset === "minimal") {
    return { preset, large_preview:false, as_photo:false, publication_mode:"card" };
  }
  if (preset === "longread") {
    return { preset, large_preview:true, as_photo:false, publication_mode:"longread" };
  }
  return { preset:"cover", large_preview:true, as_photo:false, publication_mode:"card" };
}

export function applyPresetLocally(state, value) {
  if (!state) return null;
  const patch = presetPatch(value);
  state.flags.large_preview = patch.large_preview;
  state.flags.as_photo = patch.as_photo;
  state.publication = state.publication || {};
  state.publication.mode = patch.publication_mode;
  state.presentation = {
    ...(state.presentation || {}),
    preset:patch.preset,
    mode:patch.publication_mode,
    show_cover:patch.preset !== "minimal" && Boolean(state.release?.artwork),
  };
  return patch;
}
