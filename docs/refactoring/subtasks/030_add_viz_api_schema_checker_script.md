# Subtask 030: Add Viz API Schema Checker Script

> Phase 4: Viz / Dashboard Backend
> Classification: **KEEP** (net-new tooling; adds a gate, guards a contract, redefines nothing)
> Inventory gate: **020** (`inventory_viz_dashboard_api_contracts`)
> Coordinates with: **015** (viz service layer), **021/022/023/024** (viz refactors), **012** (workflow integration plan)

This document is a PLANNING artifact. It changes **no runtime code**. It is
self-contained: a fresh coding session should be able to execute it after
reading Sections 5, 7, 8, 9, and 10. All paths are absolute-from-repo-root
(`/home/t-kotama/workplace/ARI`).

---

## 1. Goal

Add a net-new, deterministic, stdlib+PyYAML **reconciliation checker** —
`scripts/check_viz_api_schema.py` — that keeps the dashboard's server-side HTTP
surface (`ari-core/ari/viz/routes.py` + the `api_*.py` family + `websocket.py`)
in sync with its **sole** consumer, the React client
`ari-core/ari/viz/frontend/src/services/api.ts` (863 LOC).

Concretely, the checker must:

1. Enumerate the **endpoint paths + methods** the backend serves (extracted
   from the route-dispatch code, seeded/validated by the 020 inventory).
2. Enumerate the **endpoint paths + methods** the frontend actually calls
   (extracted from the `fetch` call sites in `services/api.ts`).
3. **Reconcile** the two sets after path-template normalization and report:
   - **client-only** calls (a path the frontend calls that no route serves) —
     a broken call, the **hard-error** class;
   - **server-only** routes (a path served but never called by the client) —
     candidate dead endpoints, **warning** class, most of which are legitimately
     server-only (SSE, health, reverse-proxy, container ops) and belong on an
     allowlist.
4. Emit both a human Markdown two-column report and a machine-readable `--json`
   report matching the quality-suite JSON schema, with a staged
   **warning-first** rollout.

No endpoint is renamed, added, or removed by this subtask. The checker
**guards** the dashboard API contract; it never redefines it.

## 2. Background

The dashboard backend is a bespoke, framework-free HTTP + WebSocket server
(verified 2026-07-01):

- **Python stdlib `http.server`** — no Flask/FastAPI/aiohttp/ASGI/WSGI. Request
  handling is a single `BaseHTTPRequestHandler` subclass `_Handler`
  (`ari-core/ari/viz/routes.py:77`, `protocol_version="HTTP/1.1"`). WebSocket
  runs on `port+1` via the separate `websockets` package
  (`ari-core/ari/viz/websocket.py`, 36 lines, single `{"type":"update",...}`
  message).
- **Route dispatch is two giant `if/elif` chains** over `self.path`:
  `do_GET` (`routes.py:144-1026`, ~86 branches) and `do_POST`
  (`routes.py:1028-1188`, ~51 branches), plus `do_OPTIONS` (CORS preflight,
  `127-142`). Matching is manual `startswith`/`endswith`/`re.match` with
  hand-rolled `urllib.parse` query parsing. There is **no route table**; the
  abandoned `WIZARD_ROUTES` dict (`api_wizard.py:30`) is the only partial
  declarative attempt. Handler functions live in the `api_*.py` modules and are
  imported at the top of `routes.py:27-47`.
- **The frontend is the sole consumer.** `ari-core/ari/viz/frontend/src/
  services/api.ts` (863 LOC) centralizes every call behind four helpers:
  `get`/`post` (`api.ts:18,24`, throw on `!res.ok`) and `pbGet`/`pbPost`
  (`api.ts:787,792`, PaperBench regime that returns `{error}`). There are **37
  `fetch` call sites**; paths appear both as single-quoted literals (e.g.
  `'/state'`, `'/api/checkpoints'`) and as template literals with
  `${encodeURIComponent(...)}` params (e.g.
  `` `/api/checkpoint/${encodeURIComponent(id)}/summary` ``).
- **Secondary human-readable source:** the root `README.md` REST endpoint table
  (`README.md:284-306`, base port **8765**) and its `/api/...` rows. This is a
  documentation mirror, not the authoritative set.

There is **no existing checker** for this coupling. `scripts/docs/
check_i18n_js.py` covers landing-page JS only. The one adjacent test,
`ari-core/tests/test_api_schema_contract.py` (108 lines), pins the **response
key shapes** of a few endpoints (`/api/checkpoints`, `/api/checkpoint/<id>/
summary`, `/api/settings`) by calling handler functions directly — a *shape*
guard, orthogonal to this subtask's *path-set reconciliation*. Nothing today
detects a frontend call to a path no route serves, or a route the frontend
stopped calling.

Note: the "sonfigs" directory referenced in some upstream prompts **does not
exist**. Profile YAML consumed by the `/state` builder comes from the top-level
`ari-core/config/` rubric/profile data tree (e.g. `routes.py:376,388,401,612`);
this is irrelevant to the checker but is stated here to avoid a wrong
assumption.

## 3. Scope

In scope (this subtask creates only **tooling + config + docs + a test**; it
touches **no runtime module**):

- **New** `scripts/check_viz_api_schema.py` — the reconciliation checker,
  conforming to the `scripts/`-family house style (Section 7).
- **New** `scripts/quality/` config directory (does **not** exist today) holding
  `check_viz_api_schema.yaml` (extraction patterns, normalization rules) and
  `check_viz_api_schema.allow.yaml` (intentionally server-only / client-only
  allowlist), plus a per-directory `README.md` (tracked by `readme_sync.py`).
- **New (only if absent)** `scripts/quality/_common.py` — the shared JSON/
  Markdown/allowlist helpers the 009 quality-scripts plan proposes; 030 creates
  it if no sibling checker subtask has already, otherwise imports it. The
  checker must remain runnable standalone.
- **New** `ari-core/tests/test_check_viz_api_schema.py` — unit tests for the
  extraction + normalization + reconciliation logic (fixtures, not a live
  server).
- Read-only *inputs*: `ari-core/ari/viz/routes.py`, the `api_*.py` family,
  `websocket.py`, `services/api.ts`, the 020 inventory artifact, and
  `README.md:284-306`.

Out of scope (delegated / deferred):

- **Any** change to `ari-core/ari/viz/*.py` runtime code, endpoint paths, JSON
  shapes, or `frontend/` TypeScript. This checker only reads them.
- **Wiring the checker into `.github/workflows/`.** CI integration is additive
  and belongs to the workflow-integration track
  (`docs/refactoring/012_github_workflow_integration_plan.md`); 030 ships the
  script in **warning-first** mode, not a blocking gate.
- Deep **request/response shape** validation — that is the concern of 022
  (`define_dashboard_dto_and_schema_tests`) and the existing
  `test_api_schema_contract.py`. 030 may *optionally* reconcile shapes only if a
  shared schema already exists; none does today, so shape-drift detection stays
  a documented future extension.

## 4. Non-Goals

- **NOT** renaming, adding, removing, or reordering any dashboard endpoint,
  HTTP method, JSON key, status code, header, or WebSocket message type. The
  checker is read-only and contract-preserving.
- **NOT** refactoring `routes.py` dispatch into a registry — that is 015/021.
  030 must work against the current `if/elif` string-matching code *and* against
  a future registry (extraction should not hard-code the `if/elif` shape).
- **NOT** switching HTTP frameworks or introducing auth/CSRF.
- **NOT** shelling out to `pnpm` (unavailable) or `node`/`npm`; parse
  `services/api.ts` statically in Python to stay in the stdlib+PyYAML lane and
  honor the determinism convention (design principle P2).
- **NOT** making any LLM or network call.
- **NOT** modifying `test_api_schema_contract.py` or duplicating its
  response-shape assertions.

## 5. Current Files / Directories to Inspect

Verified 2026-07-01. Line counts from `wc -l` unless noted.

Server-side inputs (`ari-core/ari/viz/`):

| Path | LOC | Relevance to the checker |
| --- | --- | --- |
| `ari-core/ari/viz/routes.py` | 1197 | `_Handler` dispatch: `do_GET` (`144-1026`, ~86 branches), `do_POST` (`1028-1188`, ~51 branches), `do_OPTIONS` (`127-142`); `_json` (`1190`), `_write_access_log` (`69`). The primary route-string source. |
| `ari-core/ari/viz/api_experiment.py` | 929 | `/api/launch`, `/api/run-stage`, `/api/logs` (SSE) handlers. |
| `ari-core/ari/viz/api_paperbench.py` | 813 | `/api/paperbench/*` (the `pbGet`/`pbPost` regime on the client). |
| `ari-core/ari/viz/api_settings.py` | 553 | `/api/settings`, `/api/env-keys`, `/api/skills`, `/api/profiles`, `/api/rubrics`, ... |
| `ari-core/ari/viz/api_workflow.py` | 462 | `/api/workflow[/default|flow|skills|disabled-tools]`. |
| `ari-core/ari/viz/ear.py` | 452 | `/api/ear/*`, `/api/nodes/<rid>/<nid>/report`. |
| `ari-core/ari/viz/checkpoint_api.py` | 327 | `/api/checkpoints`, `/api/checkpoint/<id>/summary|memory|...`, `/api/models`, lineage decisions. |
| `ari-core/ari/viz/api_orchestrator.py` | 321 | `/api/sub-experiments[/<id>|/launch]`. |
| `ari-core/ari/viz/api_paperbench_worker.py` | 319 | PaperBench run/status/results/report/logs. |
| `ari-core/ari/viz/file_api.py` | 307 | `/api/checkpoint/file/save|delete`, `/compile`, `/<id>/file[/raw]`, `/<id>/file/upload`. |
| `ari-core/ari/viz/api_tools.py` | 259 | `/api/chat-goal`, `/api/config/generate`, `/api/upload[/delete]`, `/api/ssh/test`. |
| `ari-core/ari/viz/node_work_api.py` | 233 | `/api/checkpoint/<id>/filetree|filecontent`, per-node memory. |
| `ari-core/ari/viz/api_memory.py` | 227 | `/api/memory/{health,detect,start-local,stop-local,restart}`. |
| `ari-core/ari/viz/api_fewshot.py` | 221 | `/api/fewshot/<rubric>[/sync|upload|/<ex>/delete]`. |
| `ari-core/ari/viz/checkpoint_lifecycle.py` | 205 | `/api/switch-checkpoint`, `/api/delete-checkpoint`. |
| `ari-core/ari/viz/api_process.py` | 205 | `/api/stop`, `/api/gpu-monitor`. |
| `ari-core/ari/viz/api_publish.py` | 191 | `/api/publish/*`. |
| `ari-core/ari/viz/api_ollama.py` | 90 | `/api/ollama-resources`, `/api/ollama/*` reverse proxy, container info/images/pull. |
| `ari-core/ari/viz/api_state.py` | 76 | Phase-3B re-export facade (endpoints inlined in `routes.py`). |
| `ari-core/ari/viz/websocket.py` | 36 | Single WS `{"type":"update","data":...,"timestamp":...}` on `ws://host:(port+1)/ws`. |
| `ari-core/ari/viz/README.md` | — | Module map (keep accurate if the checker adds no files here — it does not). |

Client-side + secondary inputs:

- `ari-core/ari/viz/frontend/src/services/api.ts` (863) — **authoritative
  consumer**. Helpers: `get`/`post` (`18`,`24`), `pbGet`/`pbPost`
  (`787`,`792`); **37 `fetch` call sites**; single-quote + template-literal
  paths with `${encodeURIComponent(...)}` params.
- `ari-core/ari/viz/frontend/src/services/websocket.ts` (small) — WS client URL.
- `README.md:284-306` — REST endpoint table (secondary doc source; base
  `:8765`).
- `docs/reference/rest_api.md` (260 lines) — human REST reference (optional
  cross-check source).

Convention references (house style to copy):

- `scripts/docs/check_doc_sources.py` (223 lines) — canonical checker shape:
  `#!/usr/bin/env python3`, module docstring citing a design doc, `argparse` +
  `--json`, `Finding` class with `level` in `{error,warning,coverage}`,
  `SystemExit(2)` on missing PyYAML, exit 1 on error.
- `scripts/docs/check_i18n_js.py` (parity/duplicate algorithm shape),
  `scripts/docs/check_ref_coupling.py` (`--base-ref origin/main` diff pattern).
- `scripts/readme_sync.py:31` — `REPO_ROOT = Path(__file__).resolve().parents[1]`
  (the level a top-level `scripts/` checker uses, per the 009 plan §Notes).

Upstream planning inputs:

- `docs/refactoring/007_subtask_index.md:77,252` — the 030 row and blurb.
- `docs/refactoring/009_quality_scripts_plan.md:139-145` (§5.6, this checker's
  spec), `:41-60` (common CLI/allowlist/exit contract), `:218-220`
  (placement + `scripts/quality/` + `_common.py`).
- `docs/refactoring/020_*` (viz contract inventory) — the frozen endpoint table
  the checker consumes.
- `docs/refactoring/010_contract_preservation_policy.md` — the "dashboard API is
  a preserved contract" rule this checker enforces.

## 6. Current Problems

Grounded, verified 2026-07-01:

1. **No coupling gate exists between the backend routes and `services/api.ts`.**
   A `grep` over `*.py/*.sh/*.yml/*.md` confirms `check_viz_api_schema.py` does
   not exist; nothing detects a frontend path that no route serves, or a route
   the frontend abandoned. `check_i18n_js.py` is landing-JS only;
   `test_api_schema_contract.py` (108 lines) guards *response shapes* of 3
   endpoints, not the path set.
2. **Dispatch is order-sensitive string matching with no route table.** With
   ~86 GET + ~51 POST hand-written branches (`routes.py:144-1026`,`1028-1188`)
   and only an abandoned `WIZARD_ROUTES` dict (`api_wizard.py:30`), a renamed or
   dropped endpoint can silently diverge from the 37 client `fetch` sites in
   `services/api.ts`. Manual audit across a 1197-line dispatch file plus 18
   `api_*.py` modules is error-prone.
3. **Two client request regimes obscure the surface.** `get`/`post` (throw) vs
   `pbGet`/`pbPost` (return `{error}`) — the PaperBench endpoints
   (`/api/paperbench/*`) go through the second regime, so a naive extractor that
   only knows `get`/`post` would under-count client calls and produce false
   "server-only" findings.
4. **Path templating differs across the boundary.** Server uses
   `re.match`/`startswith` patterns and `<id>`-style segments; the client uses
   `` `${encodeURIComponent(id)}` `` interpolation and query strings. Without
   normalization the two sides never text-match, so a checker must canonicalize
   both to a common `/{param}` form before diffing.
5. **The refactor waves (015/021/023) will churn this surface.** Because the viz
   backend is scheduled for heavy internal reorganization behind a frozen wire
   contract, a machine check that fails on accidental path drift is exactly the
   safety net those subtasks need — but it does not yet exist.

## 7. Proposed Design / Policy

**Policy: a deterministic, standalone, warning-first reconciliation checker that
extracts both sides statically, normalizes to a canonical endpoint identity, and
diffs the sets — guarding, never redefining, the dashboard contract.**

### 7.1 Placement and house style (matches `scripts/` family)

- File: `scripts/check_viz_api_schema.py` (top level, alongside
  `readme_sync.py`), **not** under `scripts/docs/` (that family is docs/i18n
  scoped). Per 009 plan §Notes, use `REPO_ROOT = Path(__file__).resolve().
  parents[1]` (one level up), matching `readme_sync.py:31`.
- Shape: `#!/usr/bin/env python3`; module docstring citing
  `docs/refactoring/009_quality_scripts_plan.md §5.6` and this subtask;
  `argparse`; stdlib + **PyYAML only** (guard the import with `SystemExit(2)`
  exactly like `check_doc_sources.py:29-35`). No LLM, no network, no `pnpm`/
  `node` shell-out.
- Config dir: `scripts/quality/` (new). `check_viz_api_schema.yaml` holds
  extraction/normalization patterns and target paths;
  `check_viz_api_schema.allow.yaml` holds the intentionally server-only /
  client-only allowlist keyed by canonical endpoint identity with an optional
  justification. Add `scripts/quality/README.md` (the per-directory README that
  `readme_sync.py` will track).
- Shared helpers: import from `scripts/quality/_common.py` (JSON-schema emitter,
  allowlist loader, Markdown table writer, `--base-ref` git-diff resolver). If
  `_common.py` does not yet exist (no sibling checker subtask has landed it),
  030 creates a minimal version; the checker must not hard-fail when run before
  any other quality subtask.

### 7.2 CLI contract (matches 009 plan §3 common contract)

```
scripts/check_viz_api_schema.py
  --target ari-core/ari/viz          # backend package (default)
  --client ari-core/ari/viz/frontend/src/services/api.ts   # default
  --config scripts/quality/check_viz_api_schema.yaml       # default
  --allow  scripts/quality/check_viz_api_schema.allow.yaml # default
  --inventory docs/refactoring/020_*  # optional 020 endpoint manifest
  --json                             # machine-readable output
  --warning-only                     # never exit nonzero (rollout default)
  --fail-on-regression               # exit 1 only on NEW (non-allowlisted) drift
  --base-ref origin/main             # for --fail-on-regression diffing
```

Exit convention (matches `scripts/docs/`): `0` = clean or `--warning-only`;
`1` = findings above threshold (broken client calls, or new drift under
`--fail-on-regression`); `2` = usage/environment error (missing PyYAML, missing
target file).

### 7.3 Extraction

- **Server side.** Prefer the **020 inventory artifact** as the authoritative
  endpoint list when `--inventory` points at a machine-readable manifest
  (method, path-pattern). If 020 provides only prose, fall back to **static
  extraction** from `routes.py` + `api_*.py`: scan the `do_GET`/`do_POST`/
  `do_OPTIONS` bodies for `self.path` comparisons — equality (`== "/x"`),
  `startswith("/x")`, `endswith("/x")`, and `re.match(r"...", self.path)`
  patterns — plus the top-of-file handler imports (`routes.py:27-47`) to
  attribute each route to its owning module. Extraction must be tolerant of a
  future route registry (do not hard-code the `if/elif` structure): also
  recognize a declarative `ROUTES`/`WIZARD_ROUTES`-style mapping if present.
- **Client side.** Static-parse `services/api.ts`: find every `fetch(...)`,
  `get<...>(...)`, `post<...>(...)`, `pbGet<...>(...)`, `pbPost<...>(...)` call
  and capture its path argument — both single-quoted literals and template
  literals. This must cover **all four** helper regimes (missing `pbGet`/
  `pbPost` would create false server-only findings, Problem #3). Also read
  `websocket.ts` for the single WS endpoint.
- **Doc side (secondary, advisory).** Optionally parse the `README.md:284-306`
  table for a third cross-check that flags README rows with no matching route
  (documentation drift), reported at `warning` level only.

### 7.4 Normalization to canonical endpoint identity

Canonical identity = `(METHOD, normalized_path)` where:

- `${encodeURIComponent(x)}` / `${x}` interpolation → `/{param}`.
- Server `<id>`, `re.match` capture groups, and `startswith` prefixes →
  `/{param}` / prefix form to align with the client's interpolated segments.
- Query strings (`?name=...`, `?path=...`) are stripped to the path for
  matching but retained in the report for context.
- Trailing-slash and case normalized consistently.
- SSE endpoints (`/api/logs`, PaperBench logs) and the WS endpoint are tagged so
  they are not mistaken for missing JSON routes.

### 7.5 Reconciliation + severity

Three sets after normalization:

| Finding class | Meaning | Default severity |
| --- | --- | --- |
| **client-only** | client calls a path no route serves | **error** (broken call) |
| **server-only** | route served, client never calls | **warning** (candidate dead endpoint; many legit) |
| **matched** | present on both sides | ok |

Allowlist (`check_viz_api_schema.allow.yaml`) suppresses **known** server-only
endpoints that are legitimately not called by `services/api.ts` — e.g. the
Ollama reverse proxy (`/api/ollama/*`), container ops (`/api/container/*`),
health/detect probes, `do_OPTIONS` preflight, and any endpoint consumed by a
non-`api.ts` caller. Allowlisted findings report as `known`, never as `new`, and
never trip `--fail-on-regression`.

### 7.6 Output

- **Markdown**: a two-column reconciliation table (server routes ↔ client
  calls) with a status column (matched / server-only / client-only / known),
  mirroring the human-triage style of `scripts/docs/` reports.
- **JSON** (`--json`): the quality-suite schema
  `{"checker","version","target","summary":{counts},"findings":[{id,severity,
  file,line,kind,message,allowlisted}]}` so the future `generate_quality_report`
  aggregator can merge it.

### 7.7 Rollout

Warning-first (009 plan convention): ship with `--warning-only` behavior wired
by the eventual CI job; the **client-only (broken call)** class is the first to
be promoted to a hard failure once the baseline is clean, because a broken
client call is unambiguously a bug. Server-only stays advisory behind the
allowlist.

Classification: **KEEP** (net-new tooling). The checker **guards** the preserved
dashboard-API contract; it introduces no `DELETE_CANDIDATE` / `MOVE_TO_LEGACY`
/ `ADAPT` of any runtime code.

## 8. Concrete Work Items

Execute only after the 020 inventory exists (Section 15). Suggested order:

1. **Create `scripts/quality/`** with `README.md` (per-directory README so
   `readme_sync.py --check` stays green) and, if absent, a minimal
   `_common.py` (JSON emitter, allowlist loader, Markdown writer, `--base-ref`
   resolver). If a sibling checker subtask already created `_common.py`, import
   it instead of duplicating.
2. **Write `scripts/check_viz_api_schema.py`** following `check_doc_sources.py`
   house style: docstring citing 009 §5.6 + this subtask, `argparse` with the
   Section 7.2 flags, PyYAML `SystemExit(2)` guard, `REPO_ROOT = parents[1]`.
3. **Implement server-side extraction** (Section 7.3): consume the 020 manifest
   if present, else statically scan `routes.py` + `api_*.py` for route strings
   and `re.match` patterns; attribute routes to owning modules via the
   `routes.py:27-47` imports; recognize a declarative route map if present.
4. **Implement client-side extraction** covering all four helper regimes
   (`get`/`post`/`pbGet`/`pbPost`) + raw `fetch`, both literal and template
   paths, from `services/api.ts` (+ `websocket.ts`).
5. **Implement normalization + reconciliation** (Section 7.4-7.5) producing the
   three sets and applying the allowlist.
6. **Author the config + allowlist**: `check_viz_api_schema.yaml` (patterns,
   targets) and `check_viz_api_schema.allow.yaml` seeded with the current
   legitimately-server-only endpoints (Ollama proxy, container ops,
   health/detect, OPTIONS) so the initial run is clean-or-warning.
7. **Emit Markdown + `--json`** per Section 7.6.
8. **Add `ari-core/tests/test_check_viz_api_schema.py`**: fixture-based unit
   tests for extraction (both regimes), normalization (interpolation → `/{param}`),
   reconciliation (synthetic client-only → error; allowlisted server-only →
   known), and a smoke test that the checker runs clean (or warning-only) against
   the real tree at authoring time.
9. **Run the full gate set** (Section 12); confirm the checker itself passes
   `ruff check .` and `python -m compileall .`.
10. **Do NOT wire into any workflow** — leave CI integration to the
    workflow-integration track (Section 3, 15). Note the intended job in the
    checker docstring for the follow-up.

## 9. Files Expected to Change

Created by this subtask (all net-new; **no runtime module is modified**):

- **New** `scripts/check_viz_api_schema.py` — the reconciliation checker.
- **New** `scripts/quality/README.md` — per-directory README (readme-sync
  tracked).
- **New** `scripts/quality/check_viz_api_schema.yaml` — extraction /
  normalization config + targets.
- **New** `scripts/quality/check_viz_api_schema.allow.yaml` — server-only /
  client-only allowlist.
- **New (only if absent)** `scripts/quality/_common.py` — shared helpers.
- **New** `ari-core/tests/test_check_viz_api_schema.py` — unit tests.

Read-only inputs (must **not** be modified): `ari-core/ari/viz/routes.py`, the
`api_*.py` family, `websocket.py`, `ari-core/ari/viz/frontend/src/services/
api.ts`, `websocket.ts`, `README.md`, the 020 inventory artifact.

This planning document: `docs/refactoring/subtasks/030_add_viz_api_schema_
checker_script.md` (the only file created by the planning phase).

## 10. Files / APIs That Must Not Be Broken

- **Dashboard REST + WS contract** — every path/method/JSON-key/status-code/
  header consumed by `services/api.ts` (863) and the WS message
  `{"type":"update","data":<tree>,"timestamp":...}` on `ws://host:(port+1)/ws`.
  The checker is read-only; it must not tempt an implementer to "fix" a
  reported drift by editing an endpoint — drift is reported, then resolved by
  the owning viz subtask (015/021/023) or by adding an allowlist entry.
- **`ari.public.*`** stable Python API — untouched (the checker imports none of
  it; it parses files statically).
- **CLI `ari`** (`ari.cli:app`), **MCP tool contracts** of the 14 `ari-skill-*`
  servers — untouched.
- **Scripts called by `.github/workflows`** — the 5 existing workflows and the
  scripts they invoke are unchanged; this checker is additive and **not** wired
  into CI by this subtask.
- **Existing gate scripts** under `scripts/docs/` and `report/scripts/` — the
  new file lives at `scripts/` top level and shares no code path with them
  except the copied house-style conventions.
- **`ari-core/tests/test_api_schema_contract.py`** — not modified; the new test
  is additive and covers a different concern (path reconciliation vs response
  shape).

## 11. Compatibility Constraints

- **Read-only guard.** The checker never writes to any runtime file and never
  mutates the contract; it only reports. Any real drift it surfaces is fixed by
  the responsible viz subtask, not by this tooling.
- **Determinism (P2).** Stdlib + PyYAML only; no LLM, no network, no `pnpm`/
  `node`. Same inputs → same output, so it is safe as a CI gate.
- **Registry-agnostic extraction.** Because 015/021 will replace the `if/elif`
  dispatch with a route registry, the server-side extractor must not hard-code
  the `if/elif` shape; it must also read a declarative route map. Otherwise the
  checker would break the moment the very refactor it guards lands.
- **Both client regimes.** The extractor must handle `get`/`post` **and**
  `pbGet`/`pbPost` (+ raw `fetch`); omitting the PaperBench regime would emit
  false server-only findings for every `/api/paperbench/*` route.
- **Allowlist, not endpoint edits.** Legitimately server-only endpoints
  (reverse proxy, container ops, health probes, OPTIONS) are silenced via
  `check_viz_api_schema.allow.yaml`, never by deleting a route.
- **No "deprecated" for internal code.** A server-only route flagged by the
  checker is a "candidate unused endpoint," not "deprecated" — that term is
  reserved for external contracts.
- **Warning-first rollout.** Ship non-blocking; promote the client-only class to
  hard error only after the baseline is clean (Section 7.7). Do not fail CI on
  day one.

## 12. Tests to Run

From repo root `/home/t-kotama/workplace/ARI` (editable installs already set up
by `setup.sh`: `ari-skill-memory` then `ari-core`):

```bash
python -m compileall .                 # full syntax gate (includes the new script + test)
ruff check .                           # lint (ruff IS available; radon is NOT)
pytest -q                              # full suite (must stay green)
pytest -q ari-core/tests/test_check_viz_api_schema.py   # tight loop for this subtask
```

Direct exercise of the new checker (all three exit paths):

```bash
python scripts/check_viz_api_schema.py --json            # clean/warning JSON
python scripts/check_viz_api_schema.py --warning-only     # never nonzero (rollout mode)
python scripts/check_viz_api_schema.py --fail-on-regression --base-ref origin/main
```

No frontend build is required (the checker parses `services/api.ts` statically),
so `npm test` / `npm run build` are **not** part of the 030 gate. Still run
`scripts/run_all_tests.sh` for CI parity if present. CI guard
`.github/workflows/refactor-guards.yml` must stay green (no new `~/.ari/`
references; no `$HOME/.ari/` writes during pytest). Confirm
`scripts/readme_sync.py --check` passes after adding `scripts/quality/README.md`.

## 13. Acceptance Criteria

1. `python -m compileall .` and `ruff check .` pass with no new violations; the
   new script and test are lint-clean.
2. `pytest -q` passes, including the new `test_check_viz_api_schema.py`; no
   existing test regresses (notably `test_api_schema_contract.py`).
3. `scripts/check_viz_api_schema.py` exists at the top level with the
   `check_doc_sources.py` house style (shebang, docstring citing 009 §5.6 +
   this subtask, `argparse`, PyYAML `SystemExit(2)` guard, `REPO_ROOT =
   parents[1]`), and runs with **no LLM/network/`pnpm`** dependency.
4. Running the checker against the real tree produces a reconciliation that is
   **clean or warning-only** (every server-only finding is either matched or
   allowlisted; **zero** client-only/broken-call findings) — i.e. the current
   backend and `services/api.ts` are proven in sync at authoring time.
5. The checker covers **all four** client regimes (`get`/`post`/`pbGet`/
   `pbPost`) and both literal + template paths; a test proves a synthetic
   PaperBench call is recognized.
6. Normalization aligns `${encodeURIComponent(id)}` ↔ server `<id>`/pattern
   segments (unit-tested), and query strings are stripped for matching but shown
   in the report.
7. `scripts/quality/README.md` exists and `scripts/readme_sync.py --check`
   passes; `--json` output conforms to the quality-suite schema.
8. The checker is **not** wired into any `.github/workflows/*.yml` file (CI
   integration is deferred); the 5 existing workflows are unchanged.
9. No runtime file under `ari-core/ari/viz/` or `frontend/` was modified.

## 14. Rollback Plan

- The subtask adds only new tooling/config/test files and touches no runtime
  code, so rollback is a `git revert`/`git rm` of the added files
  (`scripts/check_viz_api_schema.py`, `scripts/quality/*`,
  `ari-core/tests/test_check_viz_api_schema.py`). Nothing else references them.
- Because the checker is **not** wired into CI in this subtask, reverting it
  cannot break any existing workflow or gate.
- If `scripts/quality/_common.py` was created here and a sibling checker subtask
  later needs a different shape, that subtask evolves `_common.py`; a revert of
  030 that removes `_common.py` must check no sibling now depends on it (leave it
  if shared). No data/format migration is involved.

## 15. Dependencies

Consistent with the provided DEPENDENCY GRAPH (edge `020 -> 030`) and
`docs/refactoring/007_subtask_index.md:77,252,421`.

- **Hard predecessor (gate): 020** `inventory_viz_dashboard_api_contracts`. The
  graph lists `020 -> 021, 022, 023, 024, 030`; 020 supplies the authoritative
  endpoint/method inventory the checker consumes as its server-side source of
  truth (or validates its own extraction against). Do not author 030's config/
  allowlist before 020's endpoint table is fixed.
- **Cross-cutting inventory gate.** The master rule "inventory subtasks MUST
  precede any runtime code change" lists **001, 002, 020, 036, 045, 053, 059,
  060, 067**. Of these, **020** is the direct dependency for 030; **001**
  (current architecture) is useful context. 030 itself changes no runtime code,
  but its inputs (`routes.py`, `services/api.ts`) are frozen by 020's inventory.
- **Coordinates with (siblings, all gated by 020):** **015** (viz service
  layer / route registry), **021** (extract viz services), **022** (DTO +
  schema tests — the *shape* counterpart to 030's *path* check), **023** (viz
  file-I/O), **024** (BFTS tree-viz adapter). These form "Wave 6 — Dashboard
  backend + viz" (`007_subtask_index.md:535`). The checker must survive the
  015/021 registry refactor (Section 11), so land it registry-agnostic.
- **Downstream:** the workflow-integration track
  (`docs/refactoring/012_github_workflow_integration_plan.md`) wires this
  checker into CI in warning-first mode; the future
  `generate_quality_report` aggregator consumes its `--json`. Neither blocks
  030 from shipping.
- **Upstream policy inputs:** `009_quality_scripts_plan.md` (§5.6 spec, §3
  common contract, §Notes placement), `010_contract_preservation_policy.md`
  (dashboard API is a preserved contract), `008_viz_dashboard_refactoring_plan.md`.

## 16. Risk Level

- **Does this subtask change runtime code? NO.** It adds a standalone tooling
  script (`scripts/check_viz_api_schema.py`), its config/allowlist under a new
  `scripts/quality/` dir, an optional `scripts/quality/_common.py`, and one
  additive test. It modifies **no** module under `ari-core/ari/`, no import, no
  prompt, no config format, no workflow, no frontend file, and no directory
  name. The dashboard API contract is read-only input. (This matches
  `007_subtask_index.md:77`: Runtime = No, Inventory = No.)
- **Risk: LOW.** The only ways this can go wrong are (a) a fragile extractor
  that mis-parses `routes.py` string matching or `api.ts` template literals,
  producing false findings — mitigated by the allowlist, warning-first rollout,
  and unit tests, and bounded because the checker cannot alter runtime behavior;
  and (b) the extractor breaking when the 015/021 route-registry refactor lands
  — mitigated by making extraction registry-agnostic (Section 11). Since the
  checker is not wired into CI here, a bug cannot block the pipeline.

## 17. Notes for Implementer

- **Do not start before 020 exists.** The server-side endpoint set must come
  from (or be validated against) the 020 inventory; reverse-engineering ~137
  routes from a 1197-line `if/elif` file ad hoc is exactly the fragility this
  checker is meant to eliminate.
- **Static parsing only — no live server, no `node`/`pnpm`.** Parse
  `services/api.ts` with Python (regex/tokenizer is sufficient for the literal +
  `${encodeURIComponent(...)}` template forms). `pnpm` is not installed; do not
  shell out to any JS toolchain. Keep it stdlib + PyYAML (P2 determinism).
- **Cover both client regimes.** `get`/`post` (`api.ts:18,24`) **and**
  `pbGet`/`pbPost` (`api.ts:787,792`) — plus any raw `fetch`. Missing the
  PaperBench regime is the single most likely source of false "server-only"
  noise.
- **Registry-agnostic extraction is mandatory.** 015/021 will replace the
  `if/elif` chains with a route registry (the abandoned `WIZARD_ROUTES` at
  `api_wizard.py:30` shows the intent). Recognize both the current string-match
  form and a future declarative map, or the checker breaks on the refactor it
  guards.
- **Seed the allowlist, do not edit endpoints.** Legitimately server-only paths
  today include the Ollama reverse proxy (`/api/ollama/*`), container ops
  (`/api/container/*`), memory health/detect, and `do_OPTIONS` preflight. Put
  them in `check_viz_api_schema.allow.yaml` with justifications; never "fix" a
  server-only finding by deleting a route.
- **Match the `scripts/docs/` house style exactly.** Copy the scaffolding of
  `scripts/docs/check_doc_sources.py`: `#!/usr/bin/env python3`, a docstring
  citing the design doc, `argparse` + `--json`, a `Finding`-style object with
  `level`, `SystemExit(2)` on missing PyYAML, exit 1 on error. Use
  `REPO_ROOT = Path(__file__).resolve().parents[1]` (top-level `scripts/`, per
  009 §Notes and `readme_sync.py:31`), **not** `parents[2]` (that is the
  `scripts/docs/` level).
- **Add `scripts/quality/README.md`.** `readme_sync.py --check` will flag a new
  directory that lacks a `## Contents`-shaped README; add it and list the config
  + allowlist + `_common.py`.
- **Do not wire CI here.** The workflow-integration subtask owns adding the job
  (warning-first). Note the intended `.github/workflows` job name in the
  docstring as a hand-off, but do not create or edit any `*.yml`.
- **This checker guards, does not redefine, the contract.** The dashboard REST/
  WS endpoints and JSON shapes are a preserved external contract
  (`010_contract_preservation_policy.md`); the term "deprecated" is reserved for
  such contracts, not for a route the checker merely flags as unused.
- **The "sonfigs" directory does not exist** and is irrelevant to this checker;
  do not reference it. The confusable trio is `ari-core/ari/config/` (locator
  code) vs `ari-core/ari/configs/` (packaged defaults) vs top-level
  `ari-core/config/` (rubric data) — none of which this checker touches.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **030** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
