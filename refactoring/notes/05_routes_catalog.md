# viz/routes.py Route Catalog & Extraction Plan (requirement 05)

Task-control note from `05_viz_routes_service_extraction.md`. Captured
2026-05-30 from a 3-agent cataloging workflow over `ari-core/ari/viz/routes.py`
(1344 lines pre-extraction). This is the durable map for the **remaining**
routes.py thinning, deliberately deferred from the first (process-control) PR.

## What was done in the first PR

Extracted the **experiment process-control** concern into a new sibling
`ari/viz/api_process.py` (matches the existing `api_*.py` convention):

| Service fn | Route | Notes |
|------------|-------|-------|
| `_api_gpu_monitor_status()` | GET `/api/gpu-monitor` | route keeps a manual response with **no** `Access-Control-Allow-Origin` header (pre-existing quirk) — preserved |
| `_api_gpu_monitor_action(body)` | POST `/api/gpu-monitor` | start (confirm-gated) / stop |
| `_api_stop()` | POST `/api/stop` | SIGTERM→SIGKILL escalation, pidfile fallback, pkill safety net, survivor check |

Logic moved verbatim; the three route branches became parse→call→`self._json`.
`routes.py` dropped ~154 lines; the now-dead `os`/`subprocess` module imports it
left were removed (pre-existing unused `asyncio`/`argparse` imports left alone —
out of scope). Real characterization tests added in `tests/test_api_process.py`
(the legacy `/api/stop` + gpu-monitor tests re-implement the logic inline and
never call the handler, so they could not catch extraction regressions).

## Hard constraints (must hold for any further routes.py work)

1. **Dispatch order is load-bearing** — `do_GET`/`do_POST` are first-match-wins
   `if/elif` chains. Verbatim-preserve the order. Key hazards:
   - `/api/checkpoint/` family: six branches share the broad prefix and are
     disambiguated only by suffix/substring — `/file/raw|/file?` must precede the
     bare `/filecontent` substring test; no catch-all (unmatched → 404 via else).
   - `/api/ear/`: `/publish-yaml` before broad `/api/ear/` catch-all.
   - `/api/publish/`: `/promote` before the negative-suffix catch-all
     `startswith('/api/publish/') and not endswith(('/preview','/record','/settings'))`.
   - `/api/paperbench/run/`: `/logs`(SSE), `/results`, `/report` before the broad
     `/api/paperbench/run/` status catch-all.
   - GET regex `^/api/checkpoint/[^/]+/paper\.(pdf|tex)$` sits before the
     checkpoint family (anchored, can't be shadowed).
   - GET **static fall-through** (final else): non-`/api/` → SPA `index.html`
     (client-side routing); unknown `/api/*` → bare 404. do_POST has **no**
     static fall-through — final else is a bare 404.
2. `_json(self, data, status=200)` signature + exact headers (Content-Type
   application/json, Access-Control-Allow-Origin:*, Content-Length) must not change.
3. `server.py:78` re-exports `_Handler` and `_write_access_log` from `.routes` —
   keep them importable there. `test_server.py::_viz_server_concat()` concatenates
   `ui_helpers.py + websocket.py + routes.py + server.py` for source-text checks —
   moving a literal to a *new* module can break those unless the test is updated.
4. The watcher/broadcast path is **outside** routes.py: `_broadcast`,
   `_do_broadcast`, `_watcher_thread` are imported but never called here (re-export
   only). Don't "clean up" those imports.

## Deferred fat handlers (for a follow-up requirement)

| Concern | Route(s) | lines (pre-extr.) | risk | target |
|---------|----------|-------|------|--------|
| `/state` aggregate builder | GET `/state` | 220-667 (~447) | high | `_api_state()` in checkpoint_api/api_state. **CAUTION**: current block serializes with `json.dumps(data)` (NO `ensure_ascii=False`) and emits NO CORS header — do NOT switch to `self._json`; keep the manual tail or replicate exactly. |
| container pull | POST `/api/container/pull` | 1321-1332 | med | `_api_container_pull(body)` in a new `api_container.py` |
| static serving | GET `/logo*`, `/static/`, `/codefile`, `/api/checkpoint/.../paper.(pdf\|tex)`, `/file/raw` | various | med | `file_api.py` serve helpers + a **shared content-type map** (currently duplicated 4×) |
| access log | `_write_access_log` + `_access_log_lock` | 70-75 (+58-65) | low | new `access_log.py` (stdlib-only, explicit `checkpoint_dir` arg); keep `server.py` re-export |
| SPA index bytes | `_serve_spa_index` | 110-126 | low | factor bytes-selection into a helper; response shell stays on `_Handler` |
| SSE scaffolding | GET `/api/logs`, `/api/paperbench/run/.../logs` | 917-924, 950-1016 | med | shared `_start_sse()` header helper; loops into api_experiment/api_paperbench |
| legacy node memory | GET `/memory/` | 192-219 | low | `api_memory._api_legacy_node_memory()` |
| JSON-parse-or-400 guard | many POST branches | — | low | shared `_parse_json_body()` helper (behaviour differs per branch today: 400 vs 500 vs handler-parsed — preserve per-route) |

Most other branches are already **thin** (delegate to `api_*` modules). The full
per-route table (96 branches: 55 GET + 41 POST) lived in the cataloging workflow
output; the hazards above are the load-bearing subset.

## Follow-up

Route the deferred handlers above into a new follow-up requirement (sibling to
`15`) when picked up; coordinate the `ari.viz.state` global reduction with `07`.
