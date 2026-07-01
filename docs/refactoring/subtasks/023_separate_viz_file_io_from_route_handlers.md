# Subtask 023: Separate Viz File I/O from Route Handlers

> Phase 4: Viz / Dashboard Backend
> Classification: **ADAPT** (extract file I/O behind an unchanged wire contract)
> Inventory gate: **020** (`inventory_viz_dashboard_api_contracts`)
> Risk (per `007_subtask_index.md:70`): **Medium**
> Coordinates with: **015** (umbrella service/adapter pattern), **021**
> (extract_viz_services_from_routes), **022** (DTO + schema tests), **030**
> (viz API schema checker)

This document is a PLANNING artifact. It changes **no runtime code**. It is
self-contained: a fresh coding session should be able to execute it after
reading Sections 5, 7, 8, 9, and 10, and after subtask **020** has produced the
frozen endpoint/branch-order inventory.

---

## 1. Goal

Concentrate all **filesystem I/O** performed by the ARI dashboard backend into a
single, testable **FileService** layer, so that the HTTP request handlers in
`ari-core/ari/viz/` no longer open, resolve, validate, read, write, seed,
delete, or content-type files inline. After this subtask:

- The three inconsistent path-traversal guard styles collapse to **one**
  validated resolver.
- The two duplicated content-type maps (`/codefile` vs `/file/raw`) collapse to
  **one** table.
- The scattered size thresholds (5 MB text, 20 MB binary, 20 MB `/codefile`,
  10 MB POST cap) live in **one** place as named constants.
- Route handlers become thin: parse request → call FileService → emit
  bytes/JSON.

All of this happens **without changing a single wire-visible endpoint path,
HTTP method, JSON key, content-type, status code, header, or byte threshold**
consumed by the React frontend (`ari-core/ari/viz/frontend/src/services/api.ts`,
863 lines) or by `docs/reference/rest_api.md`.

## 2. Background

The viz backend is a bespoke, framework-free HTTP + WebSocket server built on
Python stdlib `http.server` (no Flask/FastAPI/aiohttp/ASGI). Request handling is
a single `BaseHTTPRequestHandler` subclass `_Handler` in
`ari-core/ari/viz/routes.py` (1197 LOC), with dispatch performed by two giant
`if/elif` chains (`do_GET` at `routes.py:144-1026`, `do_POST` at
`routes.py:1028-1188`). Handlers are plain functions imported from the
per-cluster `api_*.py` modules; JSON responses go through the `_json` helper
(`routes.py:1190-1197`).

A prior refactor (Phase 3B, "PR-3B-2") already split the per-checkpoint file
operations out of the old `api_state.py` into two dedicated modules —
`file_api.py` (307 LOC, paper/ CRUD + LaTeX compile) and `node_work_api.py`
(233 LOC, per-node filetree/filecontent/memory) — while `api_state.py` (76 LOC)
remains a **thin re-export facade** so `from .api_state import ...` paths keep
working. That refactor moved *functions* into modules but did **not** unify the
file-I/O primitives: traversal validation, content-type mapping, size limits,
and paper/ seeding are still hand-rolled and duplicated across `routes.py`,
`file_api.py`, `node_work_api.py`, and `api_tools.py`.

This subtask (023) is the **file-I/O half** of the Wave-6 viz refactor. Subtask
**015** owns the umbrella pattern (route registry, response wrapper,
`ari.public.*` adapter boundary, state encapsulation) and explicitly delegates
"File-serving + path-traversal consolidation (`file_api.py`, `node_work_api.py`,
inline `/codefile`, `/api/checkpoint/.../file/raw`, `paper.*`) → executed by
**023**" (see `subtasks/015_refactor_dashboard_viz_api_services.md:109-111`).
Subtask **021** owns the `/state` builder and the SSE/subprocess orchestration;
023 must not touch those. `007_subtask_index.md:245` names 023 as sharing the
worst-offender viz hotspots.

Note: the "sonfigs" directory referenced in some planning prompts **does not
exist**. This subtask does not touch config at all; it is about
checkpoint/experiment file serving. The confusable trio (`ari/config/` code,
`ari/configs/` packaged defaults, top-level `config/` rubric data) is out of
scope here.

## 3. Scope

In scope (runtime code, executed **only after** the 020 inventory gate):

1. **`ari-core/ari/viz/file_api.py`** (307) — per-checkpoint `paper/` file
   enumeration, read, save, upload, delete, LaTeX compile, plus the
   `_ensure_paper_dir` seeding logic and `_resolve_paper_file` guard.
2. **`ari-core/ari/viz/node_work_api.py`** (233) — per-node/per-checkpoint
   `filetree` + `filecontent` walks and their traversal guards
   (`_api_checkpoint_filetree`, `_api_checkpoint_filecontent`,
   `_resolve_node_work_dir`). `_api_checkpoint_memory` (memory backend read) is
   **not** file I/O in the FileService sense — leave it where it is.
3. **Inline file-serving branches in `ari-core/ari/viz/routes.py`**:
   - `/logo.png` / `/logo` static image serving (`routes.py:145-159`).
   - `/codefile?path=` binary artifact serving with substring traversal guard
     (`routes.py:678-719`).
   - `/api/checkpoint/<id>/paper.(pdf|tex)` serving from hardcoded search paths
     (`routes.py:723-745`).
   - `/api/checkpoint/<id>/file/raw` binary serving (`routes.py:788-818`).
   - `_serve_spa_index` (`routes.py:109-125`) — reads `static/dist/index.html`
     or `dashboard.html`.
   - `_write_access_log` (`routes.py:69-74`) — per-request write of
     `viz_access.jsonl`, called from `log_request` (`routes.py:102`).
4. **`ari-core/ari/viz/api_tools.py`** file-write helpers only:
   `_api_upload_file` (`api_tools.py:144-186`, incl. multipart parsing +
   `uploads/` write) and `_api_upload_delete` (`api_tools.py:190-213`). The
   chat-goal / config-gen / ssh-test functions in the same module are **not** in
   scope.

Explicitly delegated / coordinated (do NOT re-own here):

- The ~450-line inline `GET /state` builder (`routes.py:219-666`) and its glob
  scans → **021**.
- The two SSE streaming loops (`/api/logs` at `routes.py:901-908`; PaperBench
  logs at `routes.py:934-1000`) → **021** (these stream in-memory/log rows, not
  FileService reads).
- Subprocess orchestration for launch/run-stage → **021/024**. Exception: the
  LaTeX `pdflatex/bibtex` invocation inside `_api_checkpoint_compile`
  (`file_api.py:246-306`) stays with 023 because it is intrinsically a `paper/`
  file-staging operation (see Section 7.5), but coordinate the subprocess-spawn
  seam with 021.
- The route registry, response wrapper, `ari.public.*` adapter, and state
  encapsulation → **015** (023 consumes those seams if 015 has landed first;
  otherwise 023 introduces the FileService only and leaves the adapter reroute
  to 015).

## 4. Non-Goals

- **NOT** changing any endpoint path, HTTP method, request body shape, response
  JSON key set, content-type, status code, header (including
  `Access-Control-Allow-Origin: *` and the `/api/gpu-monitor` deliberate
  omission), or byte-size threshold. Every wire behavior stays identical.
- **NOT** tightening the security posture. The weak `/codefile` substring guard
  (`"checkpoints" in str(p)`, `routes.py:692`) is *current behavior*; changing
  it changes what files are served. Flag it **REVIEW_REQUIRED** in Section 17
  for a dedicated security subtask; do not "fix" it here.
- **NOT** adding authentication/authorization/CSRF to file endpoints.
- **NOT** touching `/state` (021), the SSE loops (021), subprocess launch (021/
  024), PaperBench (`api_paperbench.py`), config/rubric YAML loading, or
  `_api_checkpoint_memory` (memory backend read).
- **NOT** touching `frontend/` TypeScript, `docs/`, `.github/workflows/`, or
  `scripts/`.
- **NOT** removing the `api_state.py` re-export facade or the `server.py`
  backward-compat re-exports. Downstream `from .api_state import ...` imports and
  the test suite depend on them.
- **NOT** renaming any `state.py` module-level global (tests monkeypatch them).

## 5. Current Files / Directories to Inspect

All paths absolute-from-repo-root (`/home/t-kotama/workplace/ARI`). Line counts
verified 2026-07-01.

Primary targets:

| File | LOC | File-I/O surface to extract |
| --- | --- | --- |
| `ari-core/ari/viz/file_api.py` | 307 | `_ensure_paper_dir` (53-102, `shutil.copy2` seeding), `_api_checkpoint_files` (106-131, `rglob`), `_api_checkpoint_file_read` (135-153), `_resolve_paper_file` (157-171), `_api_checkpoint_file_save` (175-196), `_api_checkpoint_file_upload` (200-217), `_api_checkpoint_file_delete` (221-242), `_api_checkpoint_compile` (246-306, pdflatex/bibtex + PDF copy-back). Traversal guard style: `target.resolve().relative_to(base.resolve())` (142-143, 164-165, 187-189, 209-211, 232-234). |
| `ari-core/ari/viz/node_work_api.py` | 233 | `_resolve_node_work_dir` (50-83), `_api_checkpoint_filetree` (87-145, recursive `_build_tree`), `_api_checkpoint_filecontent` (149-176, `relative_to` guard 161-163). Binary-ext + skip-dir sets (27-38). |
| `ari-core/ari/viz/routes.py` | 1197 | `_write_access_log` (69-74) + `log_request` (87-104); `_serve_spa_index` (109-125); `/logo` (145-159); `/codefile` (678-719, substring guard 692, ctype_map 701-707); `paper.(pdf\|tex)` (723-745, hardcoded search paths 727-732, ctype ternary 735); `/file/raw` (788-818, ctype_map 804-810). |
| `ari-core/ari/viz/api_tools.py` | 259 | `_api_upload_file` (144-186, `uploads/` mkdir+write, multipart split), `_api_upload_delete` (190-213, `unlink` with root fallback). |
| `ari-core/ari/viz/api_state.py` | 76 | Re-export facade: re-exports the `file_api` + `node_work_api` symbols (54-73). Must keep re-exporting the same names. |

Supporting / reference (read-only, do not edit unless noted):

- `ari-core/ari/viz/state.py` (79) — `_st._checkpoint_dir`, `_st._ari_root`,
  `_st._staging_dir`, `require_checkpoint_dir`, `set_active_checkpoint`; read by
  the file helpers.
- `ari-core/ari/viz/checkpoint_finder.py` (65) — `_resolve_checkpoint_dir`
  (the resolver `file_api`/`node_work_api` defer to via bare-name wrappers at
  `file_api.py:47-49`, `node_work_api.py:44-46`).
- `ari-core/ari/viz/server.py` (201) — re-exports `_Handler`; do not break.
- `ari-core/ari/viz/README.md` — per-directory module map (readme-parity gate).

Contract references (the frozen surface this subtask must preserve):

- `ari-core/ari/viz/frontend/src/services/api.ts` (863) — the file endpoints it
  calls: `/api/checkpoint/<id>/files` (633), `.../filecontent?path=` (650),
  `.../filetree` (661), `/api/checkpoint/file/save` (669), `.../file/upload`
  (680), `/api/checkpoint/file/delete` (696), `/api/checkpoint/compile` (706).
- Frontend consumers of raw-serve endpoints:
  `frontend/src/components/Results/PaperWorkspace.tsx` (`codefileUrl` 76-77,
  `paper.pdf` 319/363), `Results/EarSection.tsx` (`/codefile` 61/418),
  `Results/resultSections.tsx` (`/codefile` 1114), `Results/ResultsPage.tsx`
  (329).
- `docs/reference/rest_api.md` — human-readable REST reference.

Tests to inspect before editing (Section 12 runs them):

- `ari-core/tests/test_file_explorer.py` — filetree/filecontent, path-traversal
  protection, binary filtering, dir skipping (fixture builds a real checkpoint
  with `paper/`, `code/`, `__pycache__/`, binary `.pkl`).
- `ari-core/tests/test_server.py` (1844), `test_gui_errors.py` (1650),
  `test_workflow_contract.py` (1606), `test_api_paperbench.py`, `test_ear.py`,
  `test_publish_yaml_api.py`, `test_api_schema_contract.py`,
  `test_public_api_boundary.py`.

Upstream planning references: `docs/refactoring/subtasks/020_*` (inventory, once
authored), `subtasks/015_refactor_dashboard_viz_api_services.md`,
`docs/refactoring/008_viz_dashboard_refactoring_plan.md`,
`docs/refactoring/010_contract_preservation_policy.md`.

## 6. Current Problems

Grounded in the files read above; all line references verified 2026-07-01.

1. **Three incompatible path-traversal guard styles.** (a) canonicalize +
   `relative_to`: `file_api.py:142-143,164-165,187-189,209-211,232-234` and
   `node_work_api.py:161-163`; (b) substring check + parent scan:
   `routes.py:692-697` (`/codefile` allows *any* file whose path contains a
   `checkpoints` component); (c) basename sanitize `Path(filename).name`:
   `api_tools.py:155,182,199` and `file_api.py:205`. Three styles = three places
   a bug can hide, and one (b) is materially weaker than the others.
2. **Duplicated content-type maps.** `/codefile` has an 8-entry map
   (`routes.py:701-707`, includes `.gif`, default `text/plain; charset=utf-8`);
   `/file/raw` has a 7-entry map (`routes.py:804-810`, no `.gif`, default
   `application/octet-stream`); `paper.(pdf|tex)` uses an inline ternary
   (`routes.py:735`). Same concept, three divergent implementations — a source
   of subtle wire drift.
3. **Scattered, magic-number size limits.** 5 MB text read
   (`file_api.py:147`, `node_work_api.py:167`), 20 MB paper binary
   (`file_api.py:169`), 20 MB `/codefile` (`routes.py:698`), 10 MB byte-tree
   text cutoff (`node_work_api.py:133`), 10 MB POST cap (`routes.py:1030`), 5 MB
   compile-PDF sanity (`file_api.py:295` uses `> 1024`). No named constants;
   each is a wire-visible threshold that must be preserved exactly.
4. **File I/O inlined directly in the HTTP handler.** `do_GET` reads bytes and
   writes the socket for `/logo` (`145-159`), `/codefile` (`698-713`),
   `paper.*` (`736-742`), `/file/raw` (`811-817`); `_serve_spa_index`
   (`109-125`) reads the SPA build; `_write_access_log` (`69-74`) appends
   `viz_access.jsonl` on *every* request from `log_request` (`102`). None of
   this is unit-testable without spinning up a socket.
5. **Hardcoded, layout-fragile search paths.** `paper.(pdf|tex)` hunts two
   literal roots — `ari-core/checkpoints/<id>` and `workspace/checkpoints/<id>`
   (`routes.py:727-730`) — encoding the legacy root-`checkpoints/` vs
   `workspace/checkpoints/` coexistence directly in a route. This duplicates
   discovery logic that `checkpoint_finder._resolve_checkpoint_dir` already
   centralizes.
6. **Side-effecting reads.** `_ensure_paper_dir` (`file_api.py:53-102`) is
   called by every `paper/` read endpoint and performs `mkdir` +
   drift-detecting `shutil.copy2` seeding — a *read* endpoint mutates the
   filesystem. This is intentional (see the docstring) but the seeding logic is
   entangled with the read path and cannot be exercised independently.
7. **Direct internal imports bypassing `ari.public.*`.** `node_work_api.py`
   imports `from ari.paths import PathManager` (`58,104,191`); `file_api.py`
   reaches `_resolve_checkpoint_dir` via a deferred wrapper. These bypass the
   stable `ari.public.paths` surface — the same coupling problem 015 addresses
   with an adapter module.
8. **`api_tools._api_upload_file` mixes transport parsing with I/O.** It parses
   multipart boundaries (`174-185`) *and* writes bytes to `uploads/`; the
   business-logic (staging auto-create, `164`) and the byte-write are one blob.

## 7. Proposed Design / Policy

**Policy: one FileService owns every filesystem primitive; route handlers and
`api_*` functions become thin call-throughs. Zero wire change.** The stdlib
server, endpoint paths, response shapes, content-types, status codes, headers,
and byte thresholds all stay byte-for-byte identical, pinned by the 020
inventory and the existing contract tests.

### 7.1 Introduce a FileService module

Add `ari-core/ari/viz/services/file_service.py` (new; under the `services/`
subpackage that 015 establishes — if 015 has not landed, create the subpackage
here and note it in the README). It centralizes:

- **`safe_resolve(base, rel) -> tuple[Path | None, str | None]`** — the single
  canonicalize-and-`relative_to` traversal validator that replaces styles (a)
  and (c) from problem #1. Returns `(path, error)` matching today's
  `{"error": "path traversal denied"}` sentinel exactly.
- **`content_type_for(ext) -> str`** — the single content-type table that
  supersedes the two duplicated maps (problem #2). It must reproduce **both**
  historical defaults where they differ: expose the caller-chosen fallback
  (`text/plain; charset=utf-8` for `/codefile`, `application/octet-stream` for
  `/file/raw`) via an argument so no served byte changes.
- **Named size constants** — `MAX_TEXT_READ = 5_000_000`,
  `MAX_BINARY_SERVE = 20_000_000`, `MAX_TREE_TEXT = 10_000_000`,
  `MAX_POST_BODY = 10 * 1024 * 1024`, mirroring problem #3's current literals
  exactly.
- **Read/serve helpers** — `read_text(path, limit)`, `read_bytes(path, limit)`,
  and a `serve_binary(handler, path, ctype)` that writes the socket with the
  same headers currently emitted inline (Content-Type, Content-Length,
  `Access-Control-Allow-Origin: *`, 200/404). The compile subprocess stays in
  `file_api` (see 7.5).
- **Write/delete helpers** — `write_text`, `write_bytes`, `delete` used by
  `file_api` save/upload/delete and `api_tools` upload/delete.
- **Binary-ext + skip-dir sets** — relocate `_BINARY_EXTENSIONS`/`_SKIP_DIRS`
  (`node_work_api.py:27-38`) and `_TEXT_EXTENSIONS` (`file_api.py:30-33`) into
  the service as the single source of truth (keep the same members).

### 7.2 Thin the route handlers

`/logo`, `/codefile`, `paper.(pdf|tex)`, `/file/raw`, and `_serve_spa_index`
shrink to: parse path/query → call `FileService.serve_binary(...)` (or
`serve_spa`) → done. The inline `ctype_map` literals and byte reads are removed
from `routes.py`. Handler *bodies* change; endpoint strings, matched patterns,
and emitted bytes do not. Keep first-match dispatch order (from 020); if 015's
registry has landed, register these through it, otherwise leave the `if/elif`
branch shells and only swap their bodies.

### 7.3 Thin the `api_*` file functions

`file_api.py` and `node_work_api.py` functions keep their **names and
signatures** (the `api_state.py` facade and the tests depend on them) but their
bodies delegate to the FileService: e.g. `_api_checkpoint_file_read` becomes
`ensure paper dir → FileService.read_text(paper / filename, MAX_TEXT_READ)`. The
bare-name `_resolve_checkpoint_dir` wrappers (`file_api.py:47-49`,
`node_work_api.py:44-46`) and the `_resolve_node_work_dir` legacy fallback
(`node_work_api.py:50-83`) are preserved verbatim — tests monkeypatch through
them.

### 7.4 Route `paper.*` through the resolver, not hardcoded paths

Replace the two literal search roots (`routes.py:727-730`) with a call into the
FileService that reuses `checkpoint_finder._resolve_checkpoint_dir` +
`full_paper.<ext>` lookup, preserving the exact fallback order (active
checkpoint first, then the two legacy roots) so the same file is served for the
same request. This removes the hardcoded layout knowledge from the route
without changing behavior.

### 7.5 Compile stays file-scoped, subprocess seam shared with 021

`_api_checkpoint_compile` (`file_api.py:246-306`) keeps ownership in the
FileService/`file_api` because it is a `paper/`-directory build (resolve paper
dir → run 4-pass `pdflatex/bibtex` → copy PDF back to checkpoint root). Extract
the *path resolution and PDF copy-back* into FileService; leave the actual
`subprocess.run` invocation as a thin call and cross-reference 021's
subprocess-orchestration seam so the two subtasks agree on where process
spawning lives. Preserve the exact `{"ok": bool, "log": str}` shape and the
timeout/`FileNotFoundError` branches.

### 7.6 Access-log write

Move `_write_access_log` (`routes.py:69-74`) into a small FileService helper
(`append_access_log(checkpoint_dir, entry)`) reusing the existing
`_access_log_lock`. `log_request` (`routes.py:87-104`) calls the helper. The
`viz_access.jsonl` line format (JSON + `\n`, `ensure_ascii=False`) is unchanged.

### 7.7 `api_tools` upload split

Split `_api_upload_file` (`api_tools.py:144-186`) into (i) multipart/transport
parsing that stays in `api_tools` and (ii) a `FileService.write_upload(dir,
name, data)` for the byte-write. `_api_upload_delete` delegates its `unlink`
(with the root fallback at `api_tools.py:203-206`) to `FileService.delete`.
Response dicts (`{"ok": True, "path": ..., "filename": ...}`) unchanged.

### 7.8 `ari.public.*` boundary

Where 015's `viz/adapters.py` exists, route `ari.paths.PathManager` access
(problem #7) through it; where it does not yet exist, keep the current imports
and leave a `# TODO(015): route via ari.public.paths` marker — do **not** invent
new `ari.public` exports in this subtask (that is a core-API concern). This keeps
`test_public_api_boundary.py` green (it governs skills, but the intent applies).

### 7.9 Classification summary

- `file_api.py`, `node_work_api.py`, inline serving in `routes.py`,
  `api_tools` upload → **ADAPT** (extract I/O into FileService behind the frozen
  wire contract).
- The two duplicated `ctype_map` literals and the three traversal-guard styles →
  **MERGE** into one table / one validator.
- No **DELETE_CANDIDATE**: nothing is dead; the weak `/codefile` guard is
  **REVIEW_REQUIRED** (security follow-up), not deleted here.
- No **MOVE_TO_LEGACY**. Do **not** use "deprecated" for any of this internal
  reorganization.

## 8. Concrete Work Items

Execute only after 020 inventory exists (Section 15). Suggested order; run the
Section 12 gate after each step:

1. **Ingest the 020 inventory** rows for the file endpoints (`/codefile`,
   `paper.(pdf|tex)`, `/file/raw`, `/files`, `/filetree`, `/filecontent`,
   `/file/save|delete|upload`, `/compile`, `/logo`) — their exact methods,
   query params, content-types, status codes, headers, and byte thresholds.
   Treat this as the frozen table.
2. **Create `services/file_service.py`** with the traversal validator,
   content-type table (both fallbacks), size constants, and read/serve/write/
   delete helpers (7.1). Add unit tests in a **new**
   `ari-core/tests/test_viz_file_service.py` (traversal denial, size limits,
   content-type mapping, binary vs text). No handler changes yet.
3. **Migrate `file_api.py`** function bodies to delegate to the FileService
   (7.3, 7.5). Keep names/signatures and the `_resolve_checkpoint_dir` wrapper.
   Run `test_file_explorer.py` + `test_server.py`.
4. **Migrate `node_work_api.py`** filetree/filecontent to the FileService (move
   the ext/skip sets in). Preserve `_resolve_node_work_dir` legacy fallback.
5. **Thin the inline route handlers** `/logo`, `/codefile`, `paper.*`,
   `/file/raw`, `_serve_spa_index` (7.2, 7.4). Verify byte-for-byte output
   parity per endpoint against `test_server.py`/`test_gui_errors.py`.
6. **Move `_write_access_log`** into the FileService helper (7.6); repoint
   `log_request`.
7. **Split `api_tools` upload/delete** (7.7).
8. **Route `ari.paths` access through 015's adapter if present**, else leave a
   TODO marker (7.8).
9. **Update `ari-core/ari/viz/README.md`** to list `services/file_service.py`
   (readme-parity gate).
10. **Run the full Section 12 gate** and confirm no contract-test regression.

## 9. Files Expected to Change

Runtime code (only when this subtask is executed, post-020):

- **New** `ari-core/ari/viz/services/file_service.py` — the FileService (create
  the `services/` package here if 015 has not already).
- **New** `ari-core/ari/viz/services/__init__.py` — only if the subpackage does
  not yet exist.
- `ari-core/ari/viz/file_api.py` — bodies delegate to FileService; names/
  signatures unchanged.
- `ari-core/ari/viz/node_work_api.py` — filetree/filecontent delegate; ext/skip
  sets relocated.
- `ari-core/ari/viz/routes.py` — inline `/logo`, `/codefile`, `paper.*`,
  `/file/raw`, `_serve_spa_index`, `_write_access_log` bodies thinned to
  FileService calls; endpoint strings and emitted bytes unchanged.
- `ari-core/ari/viz/api_tools.py` — `_api_upload_file` / `_api_upload_delete`
  delegate byte I/O to FileService.
- `ari-core/ari/viz/api_state.py` — only if new symbols must be re-exported;
  keep all existing re-exports intact.
- `ari-core/ari/viz/README.md` — module map updated for `services/file_service.py`.
- **New** `ari-core/tests/test_viz_file_service.py` — FileService unit tests
  (additive; does not replace contract tests).

Files that MUST NOT change in this subtask (delegated): `routes.py:219-666`
`/state` builder and the SSE loops `901-908`/`934-1000` (021),
`api_paperbench.py`, `api_experiment.py` launch internals (021/024),
`_api_checkpoint_memory` in `node_work_api.py` (memory backend read), all
`frontend/` TS, `docs/`, `.github/workflows/`, `scripts/`.

This planning document:
`docs/refactoring/subtasks/023_separate_viz_file_io_from_route_handlers.md`
(the only file created by the planning phase).

## 10. Files / APIs That Must Not Be Broken

- **Dashboard REST file contract** — every path/method/query-param/JSON-key/
  content-type/status-code/header consumed by
  `ari-core/ari/viz/frontend/src/services/api.ts` (633,650,661,669,680,696,706)
  and the raw-serve consumers in `PaperWorkspace.tsx`, `EarSection.tsx`,
  `resultSections.tsx`, `ResultsPage.tsx`. Specifically preserve: `/codefile`
  content-types + default, `/api/checkpoint/<id>/paper.pdf` and `.tex` serving,
  `/api/checkpoint/<id>/file/raw` content-types + default, and the
  `{"error": ...}`/`{"ok": ...}`/`{"name","content"}`/`{"id","path","files"}`/
  `{"id","path","tree"}` response shapes.
- **The `api_state.py` re-export facade** (`api_state.py:54-73`) — all
  `from .api_state import _api_checkpoint_file_*` / `_api_checkpoint_filetree` /
  `_api_checkpoint_filecontent` / `_resolve_paper_file` / `_ensure_paper_dir`
  paths must keep resolving to callables with the same behavior.
- **`server.py` re-exports** (`_Handler` etc.) — keep importable.
- **`state.py` global attribute names** — `_st._checkpoint_dir`, `_st._ari_root`,
  `_st._staging_dir` are monkeypatched in `test_file_explorer.py` and others; do
  not rename.
- **Byte thresholds** — 5 MB / 20 MB / 10 MB limits and the `{"error": "file
  too large (>5MB)"}` / `(>20MB)` sentinels are wire-visible; preserve exact
  strings and numbers.
- **CLI `ari` / `ari.public.*` / MCP tool contracts / checkpoint + config file
  formats** — read-only from viz; unchanged.
- **Scripts called by `.github/workflows`** — unaffected.

## 11. Compatibility Constraints

- **Byte-compatible responses and served files.** The FileService must emit the
  same bytes, headers, content-types, and status codes as the current inline
  code. `test_api_schema_contract.py` enforces additive-subset JSON shapes;
  `test_server.py`/`test_gui_errors.py`/`test_file_explorer.py` pin file
  behavior. Do not drop/rename keys, change content-types, or alter thresholds.
- **Preserve the two content-type defaults.** `/codefile` defaults unknown
  extensions to `text/plain; charset=utf-8`; `/file/raw` defaults to
  `application/octet-stream`. The unified table must keep both via an explicit
  fallback argument.
- **Preserve `/codefile`'s permissive guard exactly.** Do not tighten
  `"checkpoints" in str(p)` (`routes.py:692`) — narrowing it would 404 files
  that are currently served. Any hardening is a separate REVIEW_REQUIRED
  security subtask.
- **Preserve `_ensure_paper_dir` seeding side effects.** The drift-detecting
  `shutil.copy2` behavior (`file_api.py:78-102`) is relied upon by the Files
  tab; keep the mtime-based copy semantics.
- **Dispatch order fidelity.** If reusing the `if/elif` shells, keep first-match
  ordering so `/api/checkpoint/<id>/file/raw` still wins over the generic
  `/api/checkpoint/<id>/file` text branch (`routes.py:788-821`).
- **No "deprecated" label** for any internal viz code moved into the
  FileService — this is internal reorganization, not an external-contract
  deprecation.

## 12. Tests to Run

From repo root `/home/t-kotama/workplace/ARI` (editable installs already set up
by `setup.sh`: `ari-skill-memory` then `ari-core`):

```bash
python -m compileall ari-core/ari/viz          # fast syntax gate (viz only)
python -m compileall .                          # full syntax gate
ruff check .                                     # lint (ruff IS available; radon is NOT)
pytest -q                                        # full suite
```

Targeted viz/file suites (tight loop):

```bash
pytest -q ari-core/tests/test_file_explorer.py \
          ari-core/tests/test_viz_file_service.py \
          ari-core/tests/test_server.py \
          ari-core/tests/test_gui_errors.py \
          ari-core/tests/test_api_schema_contract.py \
          ari-core/tests/test_public_api_boundary.py \
          ari-core/tests/test_workflow_contract.py \
          ari-core/tests/test_api_paperbench.py \
          ari-core/tests/test_ear.py \
          ari-core/tests/test_publish_yaml_api.py
```

No frontend build is required (backend-only; `frontend/` untouched), so
`npm test` / `npm run build` are **not** part of the 023 gate. Still run
`scripts/run_all_tests.sh` if present for CI parity. The
`.github/workflows/refactor-guards.yml` guard must stay green (no new `~/.ari/`
references; no `$HOME/.ari/` writes during pytest).

## 13. Acceptance Criteria

1. `python -m compileall .` and `ruff check .` pass with no new violations.
2. `pytest -q` passes with the same-or-greater passing count; no contract test
   (`test_api_schema_contract.py`, `test_public_api_boundary.py`,
   `test_file_explorer.py`) regresses.
3. All filesystem primitives (traversal validation, content-type mapping, size
   limits, read/write/serve/delete, access-log write) live in
   `services/file_service.py`; `routes.py` `/logo` / `/codefile` / `paper.*` /
   `/file/raw` / `_serve_spa_index` / `_write_access_log` bodies contain no
   inline `read_bytes`/`ctype_map`/`relative_to`/traversal literals.
4. The two duplicated content-type maps and the three traversal-guard styles are
   unified to one table + one validator, with both historical defaults
   preserved.
5. `file_api.py` and `node_work_api.py` keep their public function names and
   signatures; the `api_state.py` facade re-exports still resolve.
6. Served files, content-types, status codes, headers, and byte thresholds are
   byte-for-byte identical to pre-refactor (verified by the targeted suites).
7. `ari-core/ari/viz/README.md` lists `services/file_service.py` (readme-parity
   / doc-source gates pass).
8. The delegated hotspots (`/state` 021, SSE 021, PaperBench, memory read) are
   untouched.
9. `ari viz` still launches and serves the SPA + file endpoints (smoke:
   `python -m ari.viz.server` starts without error; `/codefile` and
   `/api/checkpoint/<id>/files` respond).

## 14. Rollback Plan

- The work is a pure internal reorganization behind a frozen wire contract, so
  rollback is a `git revert` of the subtask's commits.
- Land incrementally per Section 8; each step is independently revertible and
  independently gated by `pytest -q`. If a served-file byte diff appears
  (e.g. a content-type default mismatch), revert only the offending step and
  re-derive the expected bytes from the 020 inventory before retrying.
- Keep the old inline serving code reachable (do not delete it) until the
  FileService is proven byte-identical by the targeted suites; delete the inline
  duplicates only after step 5/6 pass.
- No data/format migration is involved (viz reads checkpoints/experiments
  read-only except for the pre-existing `paper/` seeding, `uploads/` writes, and
  `viz_access.jsonl` append — all behavior-preserved), so there is no state to
  migrate back.

## 15. Dependencies

Consistent with the provided DEPENDENCY GRAPH (`020 -> 021, 022, 023, 024, 030`)
and `007_subtask_index.md:70,419,475,535,599`.

- **Hard predecessor (gate): 020** `inventory_viz_dashboard_api_contracts`. The
  graph edge `020 -> 023` makes 020 the viz inventory that must precede any viz
  runtime change; it supplies the frozen endpoint/content-type/threshold table
  this subtask freezes against. Do not start 023 before 020 exists.
- **Cross-cutting inventory gates.** The master rule "inventory subtasks MUST
  precede any runtime code change" lists **001, 002, 020, 036, 045, 053, 059,
  060, 067**. Of these, **001** (current architecture) and **020** (viz
  contracts) are the ones 023 directly relies on; **003** (dependency/boundary
  report) informs the `ari.public.*` adapter reroute.
- **Coordinates with (siblings, all gated by 020): 015** establishes the
  `services/` subpackage, response wrapper, and `viz/adapters.py`; sequence 015
  before 023 where possible so the FileService lands inside the shared
  `services/` layout and reuses the adapter. **021** owns the `/state` builder,
  SSE loops, and subprocess launch — 023 must avoid those and share the
  subprocess-spawn seam for `compile`. **022** (DTO + schema tests) and **030**
  (`check_viz_api_schema.py`) provide the schema-drift guardrails that protect
  023's byte-compatibility claim. Per `007_subtask_index.md:535`, 015/021/023/
  024 form "Wave 6 — Dashboard backend + viz".
- **Downstream (not blocked by 023, but shares the contract):** frontend
  subtasks (gated by 059/060/067) consume the same file endpoints; keeping wire
  output byte-compatible protects them.
- Upstream policy inputs: **006** (target architecture), **010** (contract
  preservation), **008** (viz dashboard refactoring plan).

## 16. Risk Level

- **Does this subtask change runtime code? YES** — when executed it modifies
  Python under `ari-core/ari/viz/` (adds `services/file_service.py`; thins
  `routes.py`, `file_api.py`, `node_work_api.py`, `api_tools.py`) and adds a
  test module. (This planning document itself changes no runtime code.)
- **Risk: MEDIUM** (consistent with `007_subtask_index.md:70`). Rationale: the
  change is mechanical (move I/O primitives behind a service) rather than
  semantic, and it is guarded by strong existing tests
  (`test_file_explorer.py`, `test_server.py`, `test_gui_errors.py`,
  `test_api_schema_contract.py`). The dominant residual risks are (a)
  content-type-default drift between the two merged maps, (b) an off-by-one in
  the unified traversal validator that changes which files are served, and (c)
  breaking the `_ensure_paper_dir` seeding side effect. All three are covered by
  the targeted suites and by byte-for-byte parity checks. Risk is lower than the
  umbrella 015 (High) because 023 leaves dispatch/registry/state ownership to
  015/021 and touches a narrower, well-tested file surface.

## 17. Notes for Implementer

- **Do not start before 020 exists.** Freezing content-types, status codes, and
  byte thresholds requires the authoritative inventory. If 020 is not authored,
  stop and escalate rather than reverse-engineering the wire contract ad hoc.
- **Prefer landing after 015.** If 015's `services/` subpackage and
  `viz/adapters.py` already exist, put the FileService there and route
  `ari.paths` access through the adapter. If 015 has not landed, create
  `ari-core/ari/viz/services/` here and leave a `# TODO(015)` marker for the
  adapter reroute — do not invent new `ari.public` exports.
- **Both content-type defaults matter.** `/codefile` falls back to
  `text/plain; charset=utf-8`; `/file/raw` falls back to
  `application/octet-stream`; `paper.*` uses `application/pdf` / `text/plain`.
  The unified table must reproduce each via an explicit fallback argument — a
  single hardcoded default will silently change served bytes.
- **Do NOT harden the `/codefile` guard.** `"checkpoints" in str(p)`
  (`routes.py:692`) is permissive by design today; narrowing it is a behavior
  change. Record it as a **REVIEW_REQUIRED** security follow-up (the viz backend
  has no auth on any endpoint) and leave it functionally identical here.
- **Keep the seeding side effect.** `_ensure_paper_dir` intentionally mutates
  the filesystem on read (mtime-based `shutil.copy2` from checkpoint root into
  `paper/`). Preserve the exact drift-detection semantics or the Files tab shows
  "0 files".
- **Preserve function names + the `_resolve_checkpoint_dir` deferred wrappers.**
  `file_api.py:47-49` and `node_work_api.py:44-46` exist specifically so tests
  can `monkeypatch.setattr(api_state, ...)` and have the helpers pick it up at
  call time. Do not inline them.
- **Compile is file-scoped, not launch.** Keep `_api_checkpoint_compile` in the
  file layer, but coordinate the `subprocess.run` seam with 021 so the two
  subtasks agree on where process spawning lives.
- **The "sonfigs" directory does not exist.** This subtask does not touch config
  at all; do not create or reference one.
- **Framework-free is intentional.** Do not "modernize" to Flask/FastAPI/aiofiles
  — stay on stdlib `http.server` + synchronous file reads. `radon` is not
  installed; use `ruff check .`. `node`/`npm` exist (no `pnpm`) but the frontend
  is out of scope for this backend-only subtask.
- **Update `ari-core/ari/viz/README.md`** when you add `services/file_service.py`
  — a readme-parity gate (`scripts/docs/check_readme_parity.py`) and doc-source
  checks run in CI.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **023** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
