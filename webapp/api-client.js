function requestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function createApiClient({ getInitData, onUnauthorized, defaultTimeout = 20000 }) {
  let pendingAbort = null;
  const retryIds = new Map();

  async function request(action, payload, opts = {}) {
    const signature = `${action}:${JSON.stringify(payload || {})}`;
    const id = opts.requestId || retryIds.get(signature) || requestId();
    retryIds.set(signature, id);
    if (retryIds.size > 50) retryIds.delete(retryIds.keys().next().value);
    const attempts = Math.max(1, Number(opts.attempts) || 2);
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const ctrl = new AbortController();
      const pending = { ctrl, cancelled: false };
      if (opts.abortable) pendingAbort = pending;
      const timer = setTimeout(() => ctrl.abort(), opts.timeout || defaultTimeout);
      let result;
      try {
        const response = await fetch("/api/webapp", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            init_data: getInitData(), action, payload,
            request_id: id, api_version: 1,
          }),
          signal: ctrl.signal,
        });
        if (response.status === 401) {
          onUnauthorized();
          retryIds.delete(signature);
          return { ok: false, error: "unauthorized", retryable: false };
        }
        try { result = await response.json(); }
        catch (error) {
          result = { ok: false, error: response.ok ? "bad_response" : `http_${response.status}`, retryable: response.status >= 500 };
        }
      } catch (error) {
        result = pending.cancelled
          ? { ok: false, error: "cancelled", retryable: false }
          : { ok: false, error: error?.name === "AbortError" ? "timeout" : "network", retryable: true };
      } finally {
        clearTimeout(timer);
        if (opts.abortable && pendingAbort === pending) pendingAbort = null;
      }
      if (!result.retryable || attempt === attempts - 1) {
        if (!result.retryable || result.ok) retryIds.delete(signature);
        return result;
      }
      await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
    }
    return { ok: false, error: "network", retryable: true };
  }

  function cancelPending() {
    if (pendingAbort) {
      pendingAbort.cancelled = true;
      pendingAbort.ctrl.abort();
    }
    pendingAbort = null;
  }

  return { request, cancelPending };
}
