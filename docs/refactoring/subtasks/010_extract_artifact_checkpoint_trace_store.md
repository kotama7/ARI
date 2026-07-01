# Subtask 010: Extract Artifact / Checkpoint / Trace Store

> Phase 3: Core Architecture · Risk: High · Runtime code change: **Yes** ·
> Depends on: **007** (per dependency graph `007 -> 010`)

---

## 1. Goal

Introduce three storage abstractions and their KEEP-behaviour concrete
implementations, so that ARI's runtime storage I/O is reached through injected
interfaces rather than scattered, hard-wired filesystem access:

- **`CheckpointStore`** — read/write the run's tree / nodes-tree / results JSON
  with the *exact* current layout, key order, formatting, and throttling.
- **`TraceStore`** — append/read execution traces, per-node reports, and the
  structured JSONL access logs, decoupled from the executors that emit them.
- **`ArtifactStore`** — read/write experiment artefacts (papers, figures,
  science data, EAR bundles) by *logical name*, hiding the flat checkpoint
  filesystem.

The extraction wraps existing behaviour behind `ari/protocols/*`-style
interfaces (Protocol or ABC per the target plan) and threads a single
construction point through the core. It must **preserve every on-disk
contract**: flat checkpoint filenames, JSON key order, `indent=2,
ensure_ascii=False`, the throttle interval, and the `Node.to_dict()`
formatting-stays-in-caller boundary. **No path renames and no
`runs/<id>/{artifacts,traces,reports}` consolidation happen in this subtask.**

---

## 2. Background

- The store roadmap is declared, not yet built. `ari-core/ari/protocols/`
  already exists as a deliberate Protocol package (`__init__.py:19-23` exposes
  `Evaluator`, re-exports `PromptLoader`, `ConfigLoader`), and its docstring
  names the roadmap: `LLMClient, MCPClient, MemoryClient, NodeStore,
  StageRunner` "land in subsequent phases." The three stores in this subtask are
  the storage members of that roadmap.
- The target design is specified in
  `docs/refactoring/006_target_architecture_plan.md` §3.8 (`BaseArtifactStore`),
  §3.9 (`BaseCheckpointStore`), §3.10 (`BaseTraceStore`), and the L1 Foundation
  layer at §2.2 (L135-137). This subtask implements those three sections.
- **Numbering discrepancy to be aware of:** §3.8-3.10 of `006_...md` label the
  stores "→ subtask 011". The **authoritative subtask index**
  (`docs/refactoring/007_subtask_index.md:57`) maps
  `extract_artifact_checkpoint_trace_store` to **subtask 010**, Phase 3, Risk
  High, depends on 007. Treat **010 as canonical**; §3.8-3.10's "011" label is a
  stale internal cross-reference to the plan's own detailed-doc numbering
  (`011_storage_and_paths.md`), not the runtime subtask id. Subtask **011** in
  the index is `separate_bfts_strategy_from_react_loop`, a different task.
- Current state (verified 2026-07-01):
  - JSON checkpoint I/O is already centralized in `ari-core/ari/checkpoint.py`
    (197 lines) as **module functions, not a class**.
  - `ari-core/ari/paths.py` (303 lines) `PathManager` is the single source of
    truth for directory layout, re-exported verbatim by
    `ari-core/ari/public/paths.py` (6 lines) as stable public API.
  - There is **no** `ArtifactStore` / `TraceStore` class anywhere. There is
    **no** `ExecutionServices` composition root (`grep -rn ExecutionServices
    ari` returns nothing — the name appears only as a *proposed* construct in
    `006_...md`). There is **no** `RuntimePathResolver` yet (proposed, L135).
  - No `artifacts/`, `traces/`, or `reports/` subdirectory exists inside a
    checkpoint today — the layout is flat (~45 sibling files verified on a real
    run).

---

## 3. Scope

**In scope (this subtask):**

1. Define three interfaces alongside the existing `ari/protocols/` package,
   consistent with its Protocol-first convention:
   - `CheckpointStore` — Protocol (single concrete impl expected, per §3.9).
   - `TraceStore` — Protocol (single concrete impl + optional in-memory test
     variant, per §3.10).
   - `ArtifactStore` — **ABC** (layout may vary across local/registry backends,
     per §3.8).
2. Implement concrete KEEP-behaviour classes:
   - `JsonCheckpointStore` wrapping the `ari/checkpoint.py` module functions;
     move the module-global lock/monotonic bookkeeping
     (`_INCR_LOCK`, `_INCR_LAST_SAVE_MONO`, `checkpoint.py:145-147`) to instance
     fields, keeping the module functions as thin back-compat shims.
   - `JsonlTraceStore` consolidating trace appends, node-report read/write, and
     the JSONL access-log writers behind `append_trace` / `read_trace` /
     `write_node_report` / `read_node_report` / `read_sibling_reports`.
   - `CheckpointArtifactStore` absorbing the pipeline's type-sniffing output
     writer (`pipeline/orchestrator.py` around L757-826) behind
     `put/get/exists/list`.
3. Route the current call sites through the injected stores **without renaming
   any file or changing any on-disk format** (see Section 8).
4. Add one minimal, non-breaking construction/injection point so callers can be
   handed a store; default to the current behaviour when no store is injected.

**Out of scope — deferred to other subtasks or later phases** (see Section 4).

---

## 4. Non-Goals

- **No `runs/<id>/{workspace,checkpoints,artifacts,traces,reports}`
  consolidation.** That is a separate on-disk migration; here we only introduce
  the seam that would later make it possible. The stores must sit on today's
  flat layout.
- **No path/file renames.** `PathManager.META_FILES` (`paths.py:51-76`) and the
  ~40 `{{checkpoint_dir}}/...` templated paths in
  `ari-core/config/workflow.yaml` are an on-disk contract.
- **No `RuntimePathResolver` extraction.** `PathManager` stays as-is;
  `ArtifactStore` composes the existing `PathManager` for path derivation. A
  full `RuntimePathResolver` is a paths/007-adjacent concern.
- **No memory-client changes** (subtask 013). `LettaMemoryClient`
  (`core.py:130`) is untouched here; only `memory_access.jsonl` *writing* (an
  access log) is routed through `TraceStore` if it is currently emitted from a
  viz/memory path — the memory *client* itself is not.
- **No BFTS strategy / ReAct split** (subtask 011) and **no pipeline stage
  architecture** (subtask 012). This subtask only removes filesystem coupling
  from those files; it does not restructure their control flow.
- **No remote-registry rewrite.** `ari/registry/` (HTTP artefact registry) and
  `ari/publish/` remain as-is; they are candidate *backends* for a future
  `RegistryArtifactStore`, out of scope here.
- **No change to `cost_tracker.py`** internals (subtask covers cost tracker
  separately per `006_...md` §3.16). `cost_trace.jsonl` naming/format is a
  public contract and is only *read* via `TraceStore` if needed.
- **No JSON-schema enforcement rollout.** Optionally validating
  `write_node_report` against `ari/schemas/node_report.schema.json` is a
  low-risk add, but it must not become a hard gate that rejects currently-valid
  reports.

---

## 5. Current Files / Directories to Inspect

Core storage seams (line counts verified 2026-07-01):

| Path | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/checkpoint.py` | 197 | Checkpoint JSON I/O module functions — the `CheckpointStore` seam. |
| `ari-core/ari/paths.py` | 303 | `PathManager`, `META_FILES`, run-id/env helpers — composed by stores. |
| `ari-core/ari/public/paths.py` | 6 | Stable public re-export of `PathManager` — must not break. |
| `ari-core/ari/protocols/__init__.py` | — | Existing Protocol package; add the three store interfaces here (or a submodule). |
| `ari-core/ari/protocols/evaluator.py` | — | Convention reference (`@runtime_checkable` Protocol). |

Producers/consumers to route (verified line refs):

| Path | LOC | What it does today |
| --- | --- | --- |
| `ari-core/ari/pipeline/orchestrator.py` | 913 | Type-sniffing output writer (`.tex`/`.pdf`/figures branches around L659-826) → `ArtifactStore.put`. |
| `ari-core/ari/agent/loop.py` | 1630 | `node.trace_log.append` (L899, L901) and `node.artifacts.append` (L912) → `TraceStore.append_trace`. |
| `ari-core/ari/cli/bfts_loop.py` | 911 | `write_node_report(...)` (L663) + `node_report.json` (L407, L692) → `TraceStore.write_node_report`. |
| `ari-core/ari/orchestrator/bfts.py` | 845 | `_get_node_report` (L372), `_load_sibling_node_reports` (L406), mtime cache (L261), `node_work_dir/.../node_report.json` (L77, L382) → `TraceStore.read_node_report`/`read_sibling_reports`. |
| `ari-core/ari/orchestrator/node_report/builder.py` | 652 | Node-report builder; blocklists `memory_access.jsonl`/`viz_access.jsonl`/`cost_trace.jsonl` (L36-38). |
| `ari-core/ari/orchestrator/node_report/__init__.py` | — | Exposes `write_node_report`, `compute_files_changed`. |
| `ari-core/ari/viz/state_sync.py` | 117 | Dashboard node-tree reader `_load_nodes_tree` (L27) — already **delegates** to `ari.checkpoint.load_nodes_tree` (L36), but the watcher globs `tree.json`/`nodes_tree.json`/`node_*/tree.json` directly (L79-96). |
| `ari-core/ari/viz/api_state.py` | 76 | Re-exports `_load_nodes_tree` from `state_sync` (L31). |
| `ari-core/ari/viz/routes.py` | 1197 | Writes a JSONL access log (`viz_access.jsonl`). |
| `ari-core/ari/viz/api_memory.py` | 227 | Writes/reads `memory_access.jsonl`. |
| `ari-core/ari/viz/node_work_api.py` | 233 | Writes an access log. |
| `ari-core/ari/memory_cli.py` | 407 | Access-log writer path. |
| `ari-core/ari/cost_tracker.py` | 448 | Owns `cost_trace.jsonl` / `cost_summary.json` (not rewritten here). |
| `ari-core/ari/core.py` | — | Composition point; constructs `LettaMemoryClient` at L130. No `ExecutionServices` exists yet. |
| `ari-core/ari/schemas/__init__.py` | — | `load(name)` (L11) / `schema_path(name)` (L18); **no production importer** — used only by README/tests. |
| `ari-core/ari/schemas/node_report.schema.json` | — | JSON Schema draft-07 for node reports (candidate runtime validation target). |

Config/contract data to respect (do not edit here):

- `ari-core/config/workflow.yaml` — ~40 `{{checkpoint_dir}}/<file>` output-path
  templates (e.g. `related_refs.json`, `science_data.json`, `full_paper.tex`,
  `full_paper.pdf`, `refs.bib`, `figures_manifest.json`, `tree.json`).

---

## 6. Current Problems

1. **No storage seam for artefacts or traces.** `CheckpointStore` is *almost*
   there (module functions in `checkpoint.py`), but `ArtifactStore` and
   `TraceStore` have **no class at all**; behaviour is smeared across
   `pipeline/orchestrator.py`, `agent/loop.py`, `cli/bfts_loop.py`,
   `orchestrator/bfts.py`, and four viz/memory writers.
2. **Hard-wired filenames everywhere.** Artefact names
   (`science_data.json`, `full_paper.tex`, `fig_*.pdf/png/svg`, `refs.bib`,
   `figures_manifest.json`, …) are string literals in many modules with no
   single name→path table, making any future layout change require edits in
   every caller.
3. **Module-global mutable state in `checkpoint.py`.** The throttle lock and
   `_INCR_LAST_SAVE_MONO` dict (`checkpoint.py:145-147`) are process-global,
   which is hard to test in isolation and couples all runs to one lock.
4. **BFTS ↔ filesystem coupling.** `orchestrator/bfts.py` reads
   `node_report.json` directly via `PathManager.node_work_dir(...)` (L77, L382)
   and keeps its own mtime cache (L261) — strategy logic is entangled with disk
   layout, blocking the 011 strategy/executor split.
5. **Loop ↔ filesystem coupling.** `agent/loop.py` appends trace/artefact
   entries onto `Node` fields (L899-912) that are later flushed to disk by other
   code, with no store boundary.
6. **Scattered JSONL access-log writers.** `viz_access.jsonl`,
   `memory_access.jsonl`, and `cost_trace.jsonl` are written from at least five
   places (`viz/routes.py`, `viz/api_memory.py`, `viz/node_work_api.py`,
   `memory_cli.py`, and referenced by `orchestrator/node_report/builder.py`),
   with the names duplicated in `META_FILES` and the builder blocklist.
7. **A schema with no runtime user.** `ari/schemas/node_report.schema.json`
   exists but `ari.schemas.load()` has **no production importer** (only
   README + tests reference it) — the node-report contract is never validated at
   runtime.

---

## 7. Proposed Design / Policy

### 7.1 Interfaces (add to `ari/protocols/`)

Signatures are **one-to-one** with existing behaviour so the concrete classes
are pure wrappers.

```text
# CheckpointStore (Protocol) — mirrors ari/checkpoint.py exactly
save_tree(tree: dict) -> None
save_nodes_tree(nodes: dict) -> None
save_results(results: dict) -> None
load_tree() -> dict | None
load_nodes_tree() -> dict | None            # 3-tier precedence preserved
save_tree_incremental(writer, *, force=False, throttle_sec=1.0) -> None

# TraceStore (Protocol)
append_trace(node_id: str, entry: str | dict) -> None
read_trace(node_id: str) -> list
write_node_report(node_id: str, report: dict) -> None
read_node_report(node_id: str) -> dict | None
read_sibling_reports(node_id) -> dict[str, dict]

# ArtifactStore (ABC) — absorbs pipeline persist_outputs type-sniffing
put(name: str, data_or_path) -> Path
get(name: str) -> Path
exists(name: str) -> bool
list(kind: str | None = None) -> list[Path]
```

### 7.2 Concrete implementations and per-file classification

| Component | Wraps / replaces | Classification |
| --- | --- | --- |
| `JsonCheckpointStore` | `ari/checkpoint.py` module functions; lock → instance field | **ADAPT** (behaviour KEEP, wrap in class) |
| `ari/checkpoint.py` module funcs | kept as thin shims delegating to a default store instance | **KEEP** (back-compat surface) |
| `JsonlTraceStore` | loop trace appends + bfts node-report reads + `write_node_report` + JSONL access logs | **ADAPT** / **MERGE** (5 ad-hoc writers → one) |
| `CheckpointArtifactStore` | `pipeline/orchestrator.py` output writer + hard-wired filenames | **ADAPT** |
| `RegistryArtifactStore` | *(not built here)* future wrapper over `ari/registry/` + `ari/publish` | **REVIEW_REQUIRED** (out of scope) |
| `ari.schemas.load()` loader API | unused by production | **DELETE_CANDIDATE** (the *loader API*, not the schema file) — do **not** delete here; instead give `node_report.schema.json` a first runtime user via optional validation in `write_node_report`. |
| `viz/state_sync.py` watcher globs | keep, but read tree via `CheckpointStore` | **ADAPT** |

### 7.3 KEEP-behaviour invariants (must hold byte-for-byte)

- File names unchanged; JSON written with `json.dumps(..., indent=2,
  ensure_ascii=False)` (`checkpoint.py:45-46`).
- `load_nodes_tree` precedence stays `tree.json → nodes_tree.json → newest
  non-empty node_*/tree.json`, including the empty-`{}` skip (`size > 2`) and the
  one-shot `JSONDecodeError` retry with `time.sleep(0.15)` (`checkpoint.py:86-137`).
- Throttle default stays **1.0 s** (`checkpoint.py:147`), lock-serialised, with
  `force=True` bypass.
- `Node.to_dict()` formatting stays in caller code — the store remains
  domain-agnostic (`checkpoint.py:23-25`).
- Access-log file names (`viz_access.jsonl`, `memory_access.jsonl`,
  `cost_trace.jsonl`) and append-only JSONL format preserved; they remain in
  `META_FILES` and the builder blocklist.

### 7.4 Construction / injection policy (non-breaking)

- `ExecutionServices` does **not** exist. Do **not** invent a large composition
  root in this subtask. Instead:
  - Add store construction helpers that default to the current checkpoint dir
    (via `PathManager.from_env()` / an explicit `checkpoint_dir` argument).
  - Where a call site is routed, accept an **optional** store parameter
    defaulting to `None`; when `None`, construct the default store internally so
    existing callers and tests keep working unchanged.
- `ArtifactStore` composes the existing `PathManager` for path derivation (no
  `RuntimePathResolver` dependency yet).

---

## 8. Concrete Work Items

1. **Add interfaces.** Create the three Protocol/ABC definitions in
   `ari/protocols/` (a new `ari/protocols/stores.py` submodule re-exported from
   `ari/protocols/__init__.py`), matching the existing `evaluator.py`
   `@runtime_checkable` convention. Update the package docstring roadmap note.
2. **`JsonCheckpointStore`.** Wrap the six `ari/checkpoint.py` functions in a
   class; move `_INCR_LOCK` / `_INCR_LAST_SAVE_MONO` into instance fields. Keep
   the existing module-level functions as delegating shims so
   `viz/state_sync.py:36` (`from ari.checkpoint import load_nodes_tree`) and any
   other importer are unaffected.
3. **`JsonlTraceStore`.** Implement `append_trace` / `read_trace` /
   `write_node_report` / `read_node_report` / `read_sibling_reports`. Back
   `write_node_report` with the existing
   `ari.orchestrator.node_report.write_node_report` so byte output is identical.
4. **Route BFTS reads.** In `orchestrator/bfts.py`, replace direct
   `node_work_dir(...)/"node_report.json"` reads (L77, L382) and
   `_load_sibling_node_reports` (L406) with `TraceStore` calls; keep the mtime
   cache behaviour (L261) inside the store or pass the cache through.
5. **Route loop appends.** In `agent/loop.py`, keep `Node.trace_log` /
   `Node.artifacts` as the in-memory model but funnel any *disk* trace writes
   through `TraceStore.append_trace` (the loop currently mutates `Node` fields
   at L899-912; do not change the in-memory contract, only the persistence
   path).
6. **`CheckpointArtifactStore`.** Extract the type-sniffing output writer from
   `pipeline/orchestrator.py` (the `.tex`/`.pdf`/figures branches, L659-826)
   into `ArtifactStore.put`, and introduce a name→path table for the hard-wired
   artefact filenames. Route the pipeline through `put()`.
7. **Consolidate access-log writers.** Provide a single `TraceStore` append path
   for `viz_access.jsonl` / `memory_access.jsonl` and update
   `viz/routes.py`, `viz/api_memory.py`, `viz/node_work_api.py`, `memory_cli.py`
   to call it. **Keep file names and format identical.** (`cost_trace.jsonl`
   stays owned by `cost_tracker.py`; `TraceStore` may *read* it but must not
   change how it is written.)
8. **Dashboard reader.** Point `viz/state_sync.py` at `CheckpointStore` for tree
   reads (it already delegates to `ari.checkpoint.load_nodes_tree`); leave the
   file-watcher globs functioning.
9. **Optional schema use.** Give `node_report.schema.json` a first runtime user:
   validate in `write_node_report` behind a soft warning (log only, never
   reject) so no currently-valid report is broken.
10. **Injection wiring.** Add the minimal optional-store construction described
    in §7.4 at the routed call sites; no new mandatory constructor arguments.
11. **Tests.** Add unit tests for each store asserting byte-identical output vs.
    the pre-refactor functions (golden-file comparison on `tree.json`,
    `nodes_tree.json`, `results.json`, a node report, and one artefact).

---

## 9. Files Expected to Change

New files (all under `ari-core/`):

- `ari-core/ari/protocols/stores.py` — the three interface definitions
  (or three small files re-exported from `__init__.py`).
- `ari-core/ari/checkpoint_store.py` **or** extend `ari/checkpoint.py` in place
  — `JsonCheckpointStore`.
- `ari-core/ari/trace_store.py` — `JsonlTraceStore`.
- `ari-core/ari/artifact_store.py` — `ArtifactStore` ABC + `CheckpointArtifactStore`.
- Test files under `ari-core/tests/` (e.g. `tests/test_checkpoint_store.py`,
  `tests/test_trace_store.py`, `tests/test_artifact_store.py`).

Modified files:

- `ari-core/ari/protocols/__init__.py` — export new interfaces; update roadmap
  docstring.
- `ari-core/ari/checkpoint.py` — module functions become shims over
  `JsonCheckpointStore`; lock moved to instance.
- `ari-core/ari/orchestrator/bfts.py` — node-report reads via `TraceStore`.
- `ari-core/ari/agent/loop.py` — trace persistence via `TraceStore`.
- `ari-core/ari/cli/bfts_loop.py` — node-report write via `TraceStore`.
- `ari-core/ari/pipeline/orchestrator.py` — output writer via `ArtifactStore`.
- `ari-core/ari/viz/state_sync.py` — tree read via `CheckpointStore`.
- `ari-core/ari/viz/routes.py`, `ari-core/ari/viz/api_memory.py`,
  `ari-core/ari/viz/node_work_api.py`, `ari-core/ari/memory_cli.py` — access-log
  append via `TraceStore` (names/format unchanged).
- Possibly `ari-core/ari/core.py` — optional store construction helper
  (no mandatory signature change).

Files explicitly **not** changed: `ari-core/ari/paths.py`,
`ari-core/ari/public/paths.py`, `ari-core/config/workflow.yaml`,
`ari-core/ari/cost_tracker.py`, `ari/registry/*`, `ari/publish/*`.

---

## 10. Files / APIs That Must Not Be Broken

- **Public Python API:** `ari.public.paths.PathManager` (re-export). No import
  path or class-shape change.
- **CLI:** `ari` console script (`ari.cli:app`) and all subcommands
  (`cli/{commands,run,bfts_loop,lineage,migrate,projects}.py`) — behaviour and
  output paths unchanged.
- **Checkpoint format contract:** every file in `PathManager.META_FILES`
  (`paths.py:51-76`), plus `tree.json` / `nodes_tree.json` / `results.json` /
  `node_report.json` byte layout (key order, `indent=2, ensure_ascii=False`).
- **Dashboard API:** `viz/routes.py` + `api_*.py` endpoints and the data shapes
  consumed by `frontend/src/services/api.ts` (863 lines) and `websocket.py`.
  `viz/api_state.py` re-export names (`_load_nodes_tree`) must remain importable.
- **Workflow output paths:** the ~40 `{{checkpoint_dir}}/<file>` templates in
  `ari-core/config/workflow.yaml` must resolve to the same on-disk locations.
- **MCP contracts:** the 14 `ari-skill-*` servers write into the checkpoint via
  `ARI_CHECKPOINT_DIR`; their expected filenames must not move.
- **Cost trace contract:** `cost_trace.jsonl` / `cost_summary.json` produced by
  `cost_tracker.py` (a documented public contract) — unchanged.
- **Existing importers of `ari.checkpoint`** (e.g. `viz/state_sync.py:36`) must
  keep working via the retained module functions.

---

## 11. Compatibility Constraints

- **On-disk only, no git migration cost.** `.gitignore` already ignores all
  runtime dirs (`checkpoints/` L26, `experiments/` L31, `workspace/` L70,
  `ari-core/experiments/` L83, `ari-core/checkpoints/` L84); `git ls-files`
  returns zero tracked runtime files. There is therefore no tracked-file
  migration — only on-disk back-compat.
- **Flat layout stays flat.** No `artifacts/`/`traces/`/`reports/` subdirectory
  is introduced. A future `runs/<id>/...` consolidation must ship behind a
  back-compat reader in a *later* subtask; this one only creates the seam.
- **No `~/.ari` access.** The v0.5.0 checkpoint-scoped design forbids reading
  `~/.ari`; the sole legitimate legacy accessor stays
  `ari/migrations/v05_to_v07/memory.py:26`. Stores must derive paths from the
  active checkpoint via `PathManager` only.
- **Workspace-root ambiguity is pre-existing and out of scope.** `config/
  __init__.py` (`auto_config`) defaults to `{repo_root}/workspace/checkpoints/`
  while `ari-core/config/default.yaml` says `./checkpoints/` — do **not** try to
  resolve this here; the stores must accept whatever `checkpoint_dir` they are
  given.
- **Interface-vs-ABC convention.** Follow the existing package: `CheckpointStore`
  and `TraceStore` as `@runtime_checkable` Protocols; `ArtifactStore` as an ABC
  (multiple backend layouts). Note the pre-existing inconsistency that
  `MemoryClient` is an ABC while called a "protocol" — do not add to it.

---

## 12. Tests to Run

- `python -m compileall .` — byte-compile the whole tree.
- `pytest -q` — full suite. Pay attention to the large storage-adjacent suites:
  `ari-core/tests/test_server.py` (1844), `tests/test_gui_errors.py` (1650),
  `tests/test_workflow_contract.py` (1606), `tests/test_wizard.py` (1133), and
  any `tests/test_node_report.py` / `tests/test_checkpoint*` present.
- `ruff check .` — lint (ruff is available; radon is not).
- New golden-file tests (Section 8, item 11) asserting byte-identical
  `tree.json` / `nodes_tree.json` / `results.json` / `node_report.json` and one
  artefact vs. the pre-refactor functions.
- Frontend: **not applicable** (no frontend change in this subtask); `npm
  test` / `npm run build` are not required here.

---

## 13. Acceptance Criteria

1. Three interfaces exist in `ari/protocols/` and are importable; the package
   docstring roadmap is updated to mark the storage members as landed.
2. `JsonCheckpointStore`, `JsonlTraceStore`, `CheckpointArtifactStore` exist and
   produce **byte-identical** output to the current code paths (golden tests
   pass).
3. `ari/checkpoint.py` module functions still exist and delegate to
   `JsonCheckpointStore`; no importer breaks.
4. `orchestrator/bfts.py`, `agent/loop.py`, `cli/bfts_loop.py`, and
   `pipeline/orchestrator.py` no longer construct checkpoint/artefact/trace
   paths ad-hoc for the routed operations — they go through an injected store.
5. Access-log file names and formats (`viz_access.jsonl`,
   `memory_access.jsonl`, `cost_trace.jsonl`) are unchanged; the dashboard still
   reads them.
6. `node_report.schema.json` gains a runtime user via soft (log-only)
   validation that never rejects a currently-valid report.
7. `python -m compileall .`, `pytest -q`, and `ruff check .` all pass.
8. No file in `PathManager.META_FILES` and no `workflow.yaml` output path moved.

---

## 14. Rollback Plan

- The change is additive-first: interfaces and concrete stores are new modules;
  routed call sites default to internally-constructed stores. Rollback = revert
  the routing edits and delete the new modules; the retained `checkpoint.py`
  shims mean `ari/checkpoint.py` returns to its current function-only shape by
  a single revert.
- Because there is **no on-disk format change and no git-tracked runtime data**,
  rollback needs no data migration — existing checkpoints remain readable by the
  pre-refactor code.
- Land in reviewable slices, each independently revertible: (a)
  `CheckpointStore` + shims; (b) `TraceStore` + BFTS/loop routing; (c)
  `ArtifactStore` + pipeline routing; (d) access-log consolidation; (e) optional
  schema validation. If any slice destabilises a large suite
  (`test_workflow_contract.py`, `test_server.py`), revert that slice only.

---

## 15. Dependencies

- **Hard prerequisite (dependency graph `007 -> 010`):** **007
  define_core_interfaces_and_protocols** must land first — it establishes the
  Protocol/ABC conventions and stubs (`LLMClient, MCPClient, MemoryClient,
  NodeStore, StageRunner`) that this subtask's store interfaces slot into. The
  storage interfaces here are the concrete realisation of 007's `NodeStore`
  roadmap entry.
- **Governance prerequisites (inventory subtasks that must precede any runtime
  code change):** **001, 002, 020, 036, 045, 053, 059, 060, 067** per the master
  plan. In particular 001 (architecture report) and 002 (complexity baseline)
  fix the "before" measurements this High-risk extraction is judged against.
- **Enables / is depended on by (siblings, no ordering among them):** this
  subtask removes filesystem coupling that **011**
  (separate_bfts_strategy_from_react_loop) and **012**
  (refactor_pipeline_stage_architecture) build on; coordinate so 011/012 consume
  the `TraceStore`/`ArtifactStore` seams rather than re-touching the same files.
  **013** (memory boundary) is adjacent but independent — do not fold it in.
- No frontend, docs-site, or `.github/workflows` dependency.

---

## 16. Risk Level

**High.** Runtime code change: **Yes**. Rationale:

- Touches the hot path of every run (checkpoint writes, node-report reads in the
  BFTS loop, trace appends in the agent loop, pipeline artefact persistence).
- Any deviation in JSON key order, formatting, filename, or throttle timing is a
  silent on-disk contract break consumed by the dashboard, MCP skills, and
  downstream report tooling.
- Large, storage-coupled test suites (`test_workflow_contract.py` 1606,
  `test_server.py` 1844, `test_gui_errors.py` 1650) are sensitive to exactly
  these paths.

Mitigations: byte-identical golden tests, additive-first landing in
independently-revertible slices, retained module-function shims, and the strict
"no path renames / no layout consolidation" boundary.

---

## 17. Notes for Implementer

- **Numbering:** you are subtask **010**. Ignore the "→ subtask 011" labels in
  `006_...md` §3.8-3.10 — they refer to that plan's internal detailed-doc file
  (`011_storage_and_paths.md`), not to runtime subtask 011
  (`separate_bfts_strategy_from_react_loop`). Confirmed by
  `007_subtask_index.md:57`.
- **`ExecutionServices` and `RuntimePathResolver` do not exist.** Do not create
  a heavyweight composition root here; use optional-store injection with default
  construction (§7.4). Leave the full DI root to the orchestration-layer work
  in `006_...md` §3.19-3.20.
- **`viz/state_sync.py` is already a thin delegate** (`from ari.checkpoint
  import load_nodes_tree`, L36) — it is *not* a full duplicate reader. The only
  direct disk knowledge to migrate is the watcher's tree-file globs (L79-96);
  keep the watcher functioning.
- **`ari.schemas.load()` has no production importer** (only README + tests). Do
  not delete the schema; wire it as a *soft* validator inside
  `write_node_report`. Treat the loader *API* as DELETE_CANDIDATE for a later
  dead-code subtask (013 in the top-level plan set /
  `013_reference_graph_and_dead_code_plan.md`), not here.
- **There is no `sonfigs/` directory** anywhere in the repo; the config trio is
  `ari-core/ari/config/` (code), `ari-core/ari/configs/` (packaged defaults),
  and `ari-core/config/` (rubric/profile/workflow data). None of them change in
  this subtask.
- **Keep `Node.to_dict()` in the caller.** The store must stay domain-agnostic
  (`checkpoint.py:23-25`); do not let `Node` serialization leak into
  `CheckpointStore`.
- Verify byte-identity with a real checkpoint before/after (e.g. diff a
  `tree.json` produced by the old function vs. the new store on the same input).

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **010** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
