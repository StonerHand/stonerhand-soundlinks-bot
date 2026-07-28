const ERROR_KEYS = {
  network: "network",
  timeout: "timeout",
  provider_unavailable: "timeout",
  action_busy: "busy",
  request_in_progress: "busy",
  queue_busy: "busy",
  draft_expired: "draftExpired",
  "draft not found": "draftExpired",
  need_more_tracks: "needMore",
  "need more tracks": "needMore",
  permission_denied: "unauthorized",
  unauthorized: "unauthorized",
  save_failed: "saveFailed",
  rate_limited: "rateLimited",
  crate_full: "crateFull",
};

export function createErrorText({ strings, english }) {
  const local = {
    draftExpired: english
      ? "This draft expired. Find the release again."
      : "Черновик устарел. Найди релиз ещё раз.",
    unauthorized: english
      ? "Reopen Studio from the bot."
      : "Закрой и снова открой Студию из бота.",
    saveFailed: english
      ? "Changes were not saved. Check the connection and retry."
      : "Изменения не сохранены. Проверь соединение и повтори.",
    rateLimited: english
      ? "Too many requests. Wait a moment and retry."
      : "Слишком много запросов. Подожди немного и повтори.",
  };

  return function errorText(error) {
    const raw = typeof error === "object" && error
      ? error.error_code || error.error
      : error;
    const key = ERROR_KEYS[String(raw || "")];
    if (key === "network") return strings.network;
    if (key === "timeout") return strings.timeout;
    if (key === "busy") return strings.busy;
    if (key === "draftExpired") return local.draftExpired;
    if (key === "needMore") return strings.needMore;
    if (key === "unauthorized") return local.unauthorized;
    if (key === "saveFailed") return local.saveFailed;
    if (key === "rateLimited") return local.rateLimited;
    if (key === "crateFull") return strings.crateFull;
    return strings.err;
  };
}
