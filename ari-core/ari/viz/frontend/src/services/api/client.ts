// ARI Dashboard – shared transport core for the typed API client.
//
// All fetch calls target the same origin (API_BASE = '').
//
// Two error regimes are preserved BYTE-FOR-BYTE from the original api.ts and are
// a documented wire contract (see src/services/__tests__/api.test.tsx and
// docs/refactoring/010_contract_preservation_policy.md §5):
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
  if (method === 'POST') {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(json ?? {});
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
