// ARI Dashboard – shared transport core for the typed API client.
//
// All fetch calls target the same origin (API_BASE = '').
//
// Two error regimes are preserved BYTE-FOR-BYTE from the original api.ts and are
// a documented wire contract (see src/services/__tests__/api.test.tsx; the
// contract-preservation policy §5, refactoring plan 010, has since been retired):
//
//   - get<T> / post<T>  → THROW `new Error('<METHOD> <path> failed: <status>')`
//                          on a non-2xx response (used by the app-wide `useApi`
//                          hook, which relies on the client throwing).
//   - pbGet<T> / pbPost<T> → NEVER throw; return the parsed `{...,error?}` body
//                          verbatim. The PaperBench backend `_json` helper
//                          defaults to HTTP 200 and smuggles status via
//                          `_status`, so an application error arrives as
//                          `200 + {error}` and is handled inline by the caller.
//
// The two regimes are expressed as thin wrappers over one `request` primitive;
// the wrappers' observable behavior (which calls throw, the error message text,
// the POST request-init shape) is unchanged.

export const API_BASE = '';

// ── MN-8 remote token auth (gui_refresh Wave 5b, ADR-13) ────────────────
// When the GUI is served from a remote bind (ARI_GUI_BIND non-loopback),
// the backend requires `Authorization: Bearer <ARI_GUI_TOKEN>` on every
// request. The operator stores the token in localStorage under
// 'ari_gui_token' (manual `localStorage.setItem` for now; a Settings
// diagnostics affordance is a documented follow-up in ADR-13). The default
// loopback flow never sets the key, so nothing below changes any request
// in local mode. EventSource/WebSocket cannot set headers, so streaming
// consumers append the token as a `token` query parameter instead
// (withTokenParam); the backend accepts both and redacts the query form
// from its access log.

export const GUI_TOKEN_STORAGE_KEY = 'ari_gui_token';

/** The operator-configured MN-8 token, or null when unset (loopback mode). */
export function getGuiToken(): string | null {
  try {
    const raw = window.localStorage.getItem(GUI_TOKEN_STORAGE_KEY);
    const token = raw === null ? '' : raw.trim();
    return token === '' ? null : token;
  } catch {
    return null; // storage unavailable (non-browser env / privacy mode)
  }
}

/** `Authorization` header map — empty when no token is configured. */
export function authHeaders(): Record<string, string> {
  const token = getGuiToken();
  return token === null ? {} : { Authorization: `Bearer ${token}` };
}

/** Append `token=` for EventSource/WebSocket URLs (header-less transports). */
export function withTokenParam(url: string): string {
  const token = getGuiToken();
  if (token === null) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}token=${encodeURIComponent(token)}`;
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  /** JSON body — serialized as `JSON.stringify(json ?? {})` for POST. */
  json?: unknown;
  /** When true (default), throw on a non-2xx response; when false, resolve with the parsed body. */
  throwOnError?: boolean;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', json, throwOnError = true } = opts;
  const init: RequestInit = { method };
  // MN-8: attach Authorization only when a token is configured, so the
  // loopback-default request-init shape (no headers key on GET, exactly
  // {'Content-Type'} on POST) stays byte-identical to the frozen contract.
  const headers: Record<string, string> = { ...authHeaders() };
  if (method === 'POST') {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(json ?? {});
  }
  if (Object.keys(headers).length > 0) {
    init.headers = headers;
  }
  const res = await fetch(`${API_BASE}${path}`, init);
  if (throwOnError && !res.ok) {
    throw new Error(`${method} ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── throw-regime helpers (get/post) ─────────────
// Reject on non-2xx with `new Error('<METHOD> <path> failed: <status>')`.

export async function get<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET', throwOnError: true });
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', json: body, throwOnError: true });
}

// ── swallow-regime helpers (pbGet/pbPost) ───────
// PaperBench endpoints return 200 + {error} for application errors (routes.py
// _json defaults to status=200). These helpers deliberately do NOT throw on
// non-2xx — they mirror the components' existing `fetch(...).then(r => r.json())`
// behavior exactly.

export async function pbGet<T = any>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET', throwOnError: false });
}

export async function pbPost<T = any>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', json: body, throwOnError: false });
}

// ── v1-envelope regime helper (v1Get) — ADDITIVE, gui_refresh Wave 2b ───
// The /api/v1 backend (ari/viz/v1/router.py) returns REAL non-2xx statuses
// (404/500) whose JSON body is the typed ErrorEnvelopeV1
// ({error: {code, message, details, request_id, retryable}}). The throwing
// get<T> regime above discards that body (it throws before reading it), so
// the typed v1 client (services/api/v1.ts) uses this helper: the same shared
// `request` primitive, resolving with the parsed body regardless of status,
// so the envelope survives for normalization. The client contract is that a
// caller switches on the envelope's frozen `code`, never on `message`, and
// quotes `request_id` when reporting — which is only possible if the body
// reaches the caller instead of being thrown away with the status.
// get/post/pbGet/pbPost above are UNCHANGED (documented wire contract).

export async function v1Get<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET', throwOnError: false });
}

// ── v1 mutation transport (v1Send) — ADDITIVE, gui_refresh Wave 4d ──────
// The /api/v1 config CRUD + secret assignment endpoints (POST/PATCH/PUT/
// DELETE) speak the same envelope regime as v1Get: real non-2xx statuses
// whose JSON body is the typed ErrorEnvelopeV1, so this resolves with the
// parsed body regardless of status and services/api/v1.ts normalizes.
// PATCH/DELETE optimistic concurrency rides the If-Match header (the
// document revision, quoted per RFC 9110). The `request` primitive above is
// deliberately NOT widened — its RequestOptions shape is part of the frozen
// legacy wire contract; this helper builds its own RequestInit instead.

export async function v1Send<T>(
  path: string,
  opts: {
    method: 'POST' | 'PATCH' | 'PUT' | 'DELETE';
    json?: unknown;
    ifMatch?: number;
  },
): Promise<T> {
  // MN-8: authHeaders() is empty in the loopback default, so the v1
  // mutation header set is unchanged unless a token is configured.
  const headers: Record<string, string> = { ...authHeaders() };
  const init: RequestInit = { method: opts.method };
  if (opts.method !== 'DELETE') {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.json ?? {});
  }
  if (opts.ifMatch !== undefined) {
    headers['If-Match'] = `"${opts.ifMatch}"`;
  }
  init.headers = headers;
  const res = await fetch(`${API_BASE}${path}`, init);
  return res.json() as Promise<T>;
}
