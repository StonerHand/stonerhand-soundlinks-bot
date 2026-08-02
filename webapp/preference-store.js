const ALLOWED_PRESETS = new Set(["minimal", "cover", "longread"]);

function sanitize(raw) {
  if (!raw || typeof raw !== "object") return null;
  const value = {};
  if (ALLOWED_PRESETS.has(raw.preset)) value.preset = raw.preset;
  for (const flag of ["hashtags", "as_photo"]) {
    if (typeof raw[flag] === "boolean") value[flag] = raw[flag];
  }
  if (Array.isArray(raw.platforms)) {
    value.platforms = raw.platforms.filter((item) => typeof item === "string").slice(0, 8);
  }
  return Object.keys(value).length ? value : null;
}

export function createPreferenceStore(cloud, key = "studio:prefs:v2") {
  return {
    load(callback) {
      cloud.get(key, (_error, raw) => {
        let parsed = null;
        try { parsed = raw ? JSON.parse(raw) : null; } catch (_error) {}
        callback(sanitize(parsed));
      });
    },
    save(value) {
      const clean = sanitize(value);
      if (clean) cloud.set(key, JSON.stringify(clean));
    },
  };
}
