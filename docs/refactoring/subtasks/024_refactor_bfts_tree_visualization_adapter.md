# Subtask 024: Refactor BFTS Tree Visualization Adapter

> Phase 4: Viz / Dashboard Backend · Risk: Medium · Changes runtime code: **Yes** · Changes frontend: **No**
> Depends on: **020** (`inventory_viz_dashboard_api_contracts`).

## 1. Goal

Consolidate the currently-scattered logic that converts the BFTS on-disk node
tree (`Node.to_dict()` → `tree.json` / `nodes_tree.json`) into the shape the
dashboard tree view consumes (`TreeNode`, delivered over the WebSocket `update`
message and `GET /state`) into **one backend adapter** with a single source of
truth, **without changing any emitted bytes**. Today the mapping is smeared
across `orchestrator/node.py`, `cli/bfts_loop.py`, `pipeline/orchestrator.py`,
`checkpoint.py`, `viz/state_sync.py`, `viz/checkpoint_api.py`, the inline
`/state` handler in `viz/routes.py`, and the React `TreeVisualization.tsx`,
which compensates for missing fields with `??` fallbacks. This subtask makes the
tree-view payload deterministic and centrally owned (`ADAPT` + `MERGE`), while
the WS message envelope and the JSON file formats stay frozen (`KEEP`).

## 2. Background

The BFTS "tree" data flows through a producer → wire → consumer pipeline:

- **Producer (write path).**
  - `ari-core/ari/orchestrator/node.py` (166 lines) defines the `Node`
    dataclass and `Node.to_dict()` (lines 144–166), the canonical on-disk node
    record with **21 keys** (`id, parent_id, depth, status, retry_count,
    children, created_at, completed_at, artifacts, metrics, has_real_data,
    eval_summary, label, raw_label, name, error_log, ancestor_ids, trace_log,
    original_direction, node_report_path`). `NodeStatus` enum values are
    `pending / running / success / failed / abandoned`; `NodeLabel` values are
    `draft / improve / debug / ablation / validation / other`.
  - `ari-core/ari/cli/bfts_loop.py` (911 lines) — `_save_checkpoint`
    (lines 867–910) writes the "rich" `tree.json`
    (`run_id, experiment_file, experiment_file_sha256, experiment_file_len,
    created_at, nodes=[n.to_dict()...]`), the "lightweight" `nodes_tree.json`
    (`experiment_goal, nodes`), and `results.json`. `_save_tree_incremental`
    (lines 60–113) is the throttled mid-run flush.
  - `ari-core/ari/checkpoint.py` (197 lines) is the single home for the on-disk
    JSON layout: `save_tree_json` (49), `save_nodes_tree_json` (59),
    `save_results_json` (64), `load_nodes_tree` (86–137, precedence
    `tree.json → nodes_tree.json → newest non-empty node_*/tree.json`),
    `save_tree_incremental` (150+).
  - `ari-core/ari/pipeline/orchestrator.py` (913 lines) — `build_scientific_data`
    (lines 68–…) is a **separate** adapter that strips BFTS-internal fields and
    emits a science-only view for the plot/paper skills. In scope only as a
    boundary to respect, not to merge here.
- **Wire.** `viz/state_sync._watcher_thread` polls `tree.json` /
  `nodes_tree.json` / `node_*/tree.json` mtimes every 1 s and broadcasts a single
  message `{"type":"update","data":<tree>,"timestamp":<iso>}` over
  `ws://host:(port+1)/`; `viz/websocket._ws_handler` sends the same message on
  connect; `GET /state` returns the same tree dict with extra keys merged in.
- **Consumer (frontend, NOT changed here).**
  `frontend/src/hooks/useWebSocket.ts` reads `msg.data.nodes`;
  `frontend/src/context/AppContext.tsx` line 96 selects
  `nodesData = wsNodes.length>0 ? wsNodes : state.nodes`;
  `frontend/src/components/Tree/TreeVisualization.tsx` (366 lines) d3-renders
  each node reading `d.label`, `d.status`,
  `d.scientific_score ?? d.metrics._scientific_score`, and `d.node_type`;
  `frontend/src/types/index.ts` `TreeNode` (lines 3–23) is the consumer contract.

The `020` inventory subtask enumerates these viz/dashboard contracts and gates
this refactor.

## 3. Scope

- Introduce a **single backend adapter** that maps the raw on-disk tree dict
  (returned by `ari.checkpoint.load_nodes_tree`) into the exact tree-view
  payload that the WS `update` message and `GET /state` already emit, and route
  `state_sync._load_nodes_tree`, `websocket._ws_handler`, and the `/state`
  tree-loading branch through it.
- De-duplicate the `node_count` re-derivation currently done twice
  (`load_nodes_tree` already returns `nodes`, yet `routes.py` lines 247–263
  re-reads `tree.json`/`nodes_tree.json` to recount).
- Document and centralize the status/label vocabulary and the
  `scientific_score` surfacing rule (`metrics._scientific_score`) so the
  frontend `??` fallbacks have a named backend source, **additively** (no key
  removed, no byte changed).
- Preserve the retry-on-mid-write and empty-dict-rejection semantics currently
  in `checkpoint.load_nodes_tree` (lines 123–137).

## 4. Non-Goals

- **No frontend change.** `TreeVisualization.tsx`, `TreePage.tsx`,
  `DetailPanel.tsx`, `types/index.ts`, `useWebSocket.ts`, `AppContext.tsx` stay
  as-is. The adapter must keep the wire shape they already tolerate.
- **No new WebSocket message types or channels.** The single
  `{"type":"update",...}` envelope is frozen (see 000-master / index §630).
- **No change to `tree.json` / `nodes_tree.json` / `results.json` file
  formats**, key order, or `json.dumps(..., indent=2, ensure_ascii=False)`.
- **No merge of `pipeline/orchestrator.build_scientific_data`** — that is the
  science-export adapter for plot/paper skills, a different consumer.
- Not the `/state` handler's route dispatch, subprocess, file-I/O, profile-YAML
  merge, or DTO/validation work — those belong to **021 / 022 / 023**.
- No auth/security changes (tracked elsewhere).

## 5. Current Files / Directories to Inspect

Backend producer / on-disk:
- `ari-core/ari/orchestrator/node.py` (166) — `Node`, `Node.to_dict()` 144–166, `NodeStatus`/`NodeLabel` enums.
- `ari-core/ari/cli/bfts_loop.py` (911) — `_save_checkpoint` 867–910; `_save_tree_incremental` 60–113.
- `ari-core/ari/checkpoint.py` (197) — `load_nodes_tree` 86–137; save helpers 49–66; `save_tree_incremental` 150+.
- `ari-core/ari/pipeline/orchestrator.py` (913) — `build_scientific_data` 68+ (boundary only).

Backend wire / read:
- `ari-core/ari/viz/state_sync.py` (117) — `_load_nodes_tree` 27–37, `_broadcast`/`_do_broadcast` 42–63, `_watcher_thread` 68–116.
- `ari-core/ari/viz/websocket.py` (36) — `_ws_handler` 20–36.
- `ari-core/ari/viz/api_state.py` (76) — thin re-export facade (Phase 3B).
- `ari-core/ari/viz/routes.py` (1197) — `/state` handler 219–666; tree-loading branch 225–263.
- `ari-core/ari/viz/checkpoint_api.py` (327) — `_load_nodes_tree` 45–53, `best_scientific_score` derivation 165–173.
- `ari-core/ari/viz/server.py` — re-exports `_load_nodes_tree` / `_ws_handler`.

Frontend consumers (read-only reference, NOT edited):
- `ari-core/ari/viz/frontend/src/types/index.ts` (264) — `TreeNode` 3–23; `nodes_tree` 241–243.
- `ari-core/ari/viz/frontend/src/hooks/useWebSocket.ts` (97).
- `ari-core/ari/viz/frontend/src/context/AppContext.tsx` (120) — line 96.
- `ari-core/ari/viz/frontend/src/components/Tree/TreeVisualization.tsx` (366).
- `ari-core/ari/viz/frontend/src/components/Tree/{TreePage.tsx (206),DetailPanel.tsx (425)}`.

## 6. Current Problems

1. **No single adapter.** Mapping/derivation logic is spread across at least
   seven files (`node.py`, `bfts_loop.py`, `pipeline/orchestrator.py`,
   `checkpoint.py`, `state_sync.py`, `checkpoint_api.py`, `routes.py`) plus the
   frontend. There is no one place that answers "what is the tree-view payload?".
2. **Contract drift, consumer-side patched.** `TreeNode` (`types/index.ts`
   3–23) declares `node_type`, `score`, `scientific_score`, `hypothesis`,
   `description` — **none of which `Node.to_dict()` emits**. The frontend
   compensates with `d.scientific_score ?? d.metrics._scientific_score`
   (`TreeVisualization.tsx` 274–290) and `d.label || d.node_type || 'node'`
   (line 206). The derivation rule lives in TypeScript, not in the producer.
3. **Duplicate readers kept "byte-identical by hand".**
   `viz/checkpoint_api._load_nodes_tree` (45–53) and `viz/state_sync`
   both delegate to `ari.checkpoint.load_nodes_tree`, whose docstring says it
   "mirrors `viz/api_state.py:_load_nodes_tree` exactly" (checkpoint.py 89) — a
   fragile hand-maintained equivalence rather than one function.
4. **Redundant `node_count` re-read.** `load_nodes_tree()` already returns
   `nodes`, yet `/state` (routes.py 247–263) re-opens `tree.json` /
   `nodes_tree.json` to recount, duplicating I/O and precedence logic.
5. **Internal import bypassing the public surface.** viz imports
   `ari.checkpoint` directly rather than through `ari.public.*` (consistent with
   the broader viz finding, but relevant here as the adapter's import boundary).
6. **Status/label vocabulary uncentralized.** Backend enum values
   (`success`/`failed`/…) vs frontend's hard-coded `success`/`failed`/else
   branches, and test fixtures that use `"completed"`
   (`tests/test_api_schema_contract.py:38`) — no shared constant.

## 7. Proposed Design / Policy

- **Classification:** `ADAPT` the scattered read-side mapping + `MERGE` it into
  one module. The WS envelope and the three JSON file formats are `KEEP`
  (frozen). `pipeline.build_scientific_data` is `KEEP` (untouched). The
  duplicate hand-mirrored reader path is `REVIEW_REQUIRED` for final placement.
- **Introduce one adapter function/module** — proposed
  `ari-core/ari/viz/tree_view.py` with e.g.
  `def build_tree_view(checkpoint_dir) -> dict | None` — that:
  1. Calls `ari.checkpoint.load_nodes_tree(checkpoint_dir)` (keeping the
     precedence + retry + empty-rejection semantics in exactly one place).
  2. Returns the **same dict shape emitted today** (`{"nodes": [...], ...}`),
     byte-for-byte, so `json.dumps` output over WS and `/state` is unchanged.
  3. Optionally exposes a pure helper (`derive_node_view(node_dict)`) that names
     the frontend's current derivations (surface `scientific_score` from
     `metrics._scientific_score`, default `node_type`) as **additive** keys —
     added only if 020's contract inventory confirms the frontend reads them and
     it does not alter existing bytes for current consumers. If any risk of
     changing emitted bytes, defer the additive keys and land the pure
     consolidation only.
- **Rewire call sites** to the new adapter: `state_sync._load_nodes_tree`,
  `websocket._ws_handler`, and the `/state` tree branch. `api_state.py` keeps its
  re-export facade so `from .api_state import _load_nodes_tree` paths are intact.
- **De-duplicate `node_count`**: derive it from the adapter's already-loaded
  `nodes` in `/state` instead of the second file read (routes.py 247–263),
  preserving the exact fallback numbers.
- **Centralize the status/label vocabulary** in one backend constant module
  (or reuse `orchestrator/node.py` enums) referenced by the adapter, so future
  changes are single-sourced. No behavior change now.
- **Import boundary:** the adapter is the one place allowed to import
  `ari.checkpoint`; if a `ari.public.*` accessor for tree loading is introduced
  in a later subtask, only this module changes.

Note: the `/state` profile-YAML merge reads from `ari-core/config/`
(`routes.py` 376/388) — there is **no `sonfigs/` directory** anywhere in the
repo; that path is out of scope for this subtask and belongs to 021/023.

## 8. Concrete Work Items

1. Read 020's viz/dashboard contract inventory; confirm the exact set of keys
   the WS `update.data` payload and `GET /state` currently carry and which the
   frontend actually reads (esp. whether `node_type`/`score`/`hypothesis`/
   `description` are consumed anywhere beyond the `??` fallbacks).
2. Create `ari-core/ari/viz/tree_view.py` (name `REVIEW_REQUIRED`) with
   `build_tree_view(checkpoint_dir)` that wraps `checkpoint.load_nodes_tree`
   and returns the identical dict.
3. Point `state_sync._load_nodes_tree` (27–37), `websocket._ws_handler` (24),
   and the `/state` branch (routes.py 225) at the new adapter; keep the
   `api_state` facade re-export.
4. Replace the redundant `node_count` file re-read in `/state`
   (routes.py 247–263) with a count off the adapter's `nodes`, asserting
   identical values for empty / nodes-present / legacy layouts.
5. (Conditional on step 1) Add `derive_node_view` additive-key helper only if it
   provably does not change existing emitted bytes; otherwise document the
   deferral inline.
6. Add/extend backend tests locking the WS message envelope, the `/state`
   `nodes` shape, and the legacy `node_*/tree.json` precedence (see §12).
7. Run `ruff check .`, `python -m compileall .`, `pytest -q`; snapshot-diff the
   `/state` and WS payloads before/after against a real checkpoint under
   `workspace/checkpoints/` to prove byte-identical output.

## 9. Files Expected to Change

Runtime (backend only):
- `ari-core/ari/viz/tree_view.py` — **NEW** adapter module (name subject to review).
- `ari-core/ari/viz/state_sync.py` — `_load_nodes_tree` delegates to the adapter.
- `ari-core/ari/viz/websocket.py` — `_ws_handler` uses the adapter.
- `ari-core/ari/viz/routes.py` — `/state` tree branch (225–263) uses the adapter; drop the duplicate `node_count` re-read.
- `ari-core/ari/viz/api_state.py` — keep/extend the re-export facade to include the new adapter symbol.
- Possibly `ari-core/ari/viz/checkpoint_api.py` — route `_load_nodes_tree` (45–53) through the adapter if it reduces duplication without changing `best_scientific_score` output.

Tests:
- `ari-core/tests/test_api_schema_contract.py`, `ari-core/tests/test_checkpoint_legacy_tree.py`, and/or a new `ari-core/tests/test_tree_view_adapter.py`.

Docs (if a per-directory README documents the flow):
- `ari-core/ari/viz/README.md` — note the new adapter as the single tree-view source.

NOT changed: any file under `ari-core/ari/viz/frontend/`, `orchestrator/node.py`,
`cli/bfts_loop.py` writers, `checkpoint.py` I/O semantics,
`pipeline/orchestrator.py`.

## 10. Files / APIs That Must Not Be Broken

- **WebSocket message envelope** `{"type":"update","data":<tree>,"timestamp":<iso>}`
  on `ws://host:(port+1)/` (`state_sync.py` 45–46, `websocket.py` 26–29).
- **`GET /state`** response shape, including all merged keys (`checkpoint_id`,
  `checkpoint_path`, `has_paper/has_pdf/has_review/has_repro`, `node_count`,
  `current_phase`, `phase_flags`, `actual_models`, `llm_model_actual`, …).
- **`GET /api/checkpoint/<id>/summary`** `nodes_tree` field and
  `best_scientific_score` (`checkpoint_api.py` 165–173) — locked by
  `tests/test_checkpoint_legacy_tree.py` and `tests/test_api_schema_contract.py`.
- **On-disk formats** `tree.json` / `nodes_tree.json` / `results.json` (keys,
  order, indent).
- **Frontend `TreeNode` contract** (`types/index.ts` 3–23) and the fields
  `TreeVisualization.tsx` reads (`label`, `status`, `scientific_score`,
  `metrics._scientific_score`, `node_type`, `depth`, `id`, `parent_id`).
- **Import paths** `from .api_state import _load_nodes_tree` (used by
  `routes.py` 28, `server.py` 34, `websocket.py` 17).
- **`ari.checkpoint.load_nodes_tree`** public signature/precedence (also used by
  CLI/pipeline).

## 11. Compatibility Constraints

- **Byte-for-byte output.** This is a pure structural refactor: the JSON that
  `json.dumps` produces for both the WS `data` payload and the `/state` `nodes`
  field must be identical before/after for empty, single-node, multi-node, and
  legacy `node_*/tree.json` checkpoints. Any additive key (§7 step 5) may only
  be introduced if it does not alter existing keys/values and 020 confirms the
  consumer.
- **No new dependencies.** Backend is Python stdlib `http.server` +
  `websockets`; introduce no framework.
- **Facade preservation.** `api_state.py` remains a thin re-export so downstream
  `from .api_state import ...` imports keep working (Phase 3B contract).
- **Determinism (P2).** No LLM calls, no nondeterministic ordering; node order
  from disk is preserved as-is.
- The adapter must retain `load_nodes_tree`'s mid-write retry (2 attempts,
  0.15 s) and empty/`nodes`-less rejection (returns `None`).

## 12. Tests to Run

- `python -m compileall .` — syntax/import sanity across the package.
- `pytest -q` — full suite. Targeted:
  - `pytest -q ari-core/tests/test_api_schema_contract.py`
  - `pytest -q ari-core/tests/test_checkpoint_legacy_tree.py`
  - `pytest -q ari-core/tests/test_server.py` (WS / `/state` handler)
  - `pytest -q ari-core/tests/test_gui_errors.py`
  - `pytest -q ari-core/tests/test_node.py ari-core/tests/test_bfts.py`
  - `pytest -q ari-core/tests/test_nodes_to_science_data_shrink.py` (guards the
    separate science adapter is untouched)
  - new `ari-core/tests/test_tree_view_adapter.py` if added.
- `ruff check .` — lint.
- Frontend (**smoke only, not modified**): `npm run typecheck` and `npm test`
  in `ari-core/ari/viz/frontend/` to confirm the unchanged `TreeNode` consumer
  still type-checks against the preserved payload. (No `npm run build` needed —
  no FE source changes.)
- Manual byte-diff: capture `/state` and a WS `update` frame against a real
  `workspace/checkpoints/<ts_slug>/` before and after; assert equality.

## 13. Acceptance Criteria

1. Exactly one backend function/module produces the tree-view payload; the WS
   handler, watcher broadcast, and `/state` branch all call it.
2. `/state` no longer re-reads `tree.json`/`nodes_tree.json` a second time to
   recount `node_count`; the value is identical to before for all layouts.
3. WS `update.data` and `/state` JSON are byte-identical before/after on empty,
   populated, and legacy `node_*/tree.json` checkpoints.
4. `api_state` re-exports unchanged; no import path breaks.
5. `python -m compileall .`, `pytest -q`, and `ruff check .` all pass; frontend
   `npm run typecheck` + `npm test` pass unchanged.
6. No file under `frontend/`, and no on-disk JSON format, was modified.

## 14. Rollback Plan

- The change is confined to a few backend viz modules plus one new file. Revert
  the commit(s); because `api_state.py` keeps re-exporting `_load_nodes_tree`,
  reverting restores the prior call graph with no downstream import churn.
- If a byte-diff regression is found post-merge, re-point `state_sync`,
  `websocket`, and `/state` back to the inline `checkpoint.load_nodes_tree`
  calls (a mechanical 3-site revert) and delete `tree_view.py`; the on-disk
  writers and frontend are untouched, so no data migration is needed.
- Keep the new adapter behind the identical call signature so a partial revert
  (only the `/state` `node_count` de-dup) is possible independently.

## 15. Dependencies

- **Depends on 020** (`inventory_viz_dashboard_api_contracts`) per the
  dependency graph (`020 -> 021, 022, 023, 024, 030`); 020 is one of the nine
  inventory subtasks that must precede any runtime code change. Do not start the
  code change until 020's viz/dashboard contract inventory (WS envelope + `/state`
  + tree JSON key set) is available.
- **Sibling, coordinate but not blocking:** 021 (extract viz services from
  routes), 022 (dashboard DTO + schema tests), 023 (separate viz file-I/O), and
  030 (`check_viz_api_schema.py`). If 021 lands first, layer this adapter beneath
  its service extraction; if this lands first, expose the adapter as a callable
  the later service can wrap.
- No dependency on Phase 1/2/3 path or interface subtasks for the minimal
  refactor; if a `ari.public.*` tree-loading accessor is added later, update only
  this module's import.

## 16. Risk Level

**Medium.** Runtime code change: **Yes** (backend viz only; frontend: No). The
risk driver is that the WS `update` message and `/state` tree payload are frozen
external contracts consumed by the React dashboard; a byte-level regression would
silently break live tree updates. Mitigated by: (a) delegating to the existing
`checkpoint.load_nodes_tree` rather than reimplementing precedence, (b) the
`api_state` re-export facade absorbing import churn, (c) byte-diff snapshot tests
and the existing `test_checkpoint_legacy_tree.py` / `test_api_schema_contract.py`
guards, and (d) keeping any additive field derivation opt-in and gated on 020.

## 17. Notes for Implementer

- **Prove byte-equality first.** Before rewiring, write a test that dumps the
  current `/state` `nodes` and a WS frame from a fixture checkpoint, then assert
  the adapter reproduces them exactly. Treat this as the go/no-go gate.
- **The `??` fallbacks in `TreeVisualization.tsx` are the spec** of what the
  frontend needs but the backend does not emit: `scientific_score`
  (from `metrics._scientific_score`), `node_type`, `score`, `hypothesis`,
  `description`. Do **not** delete these fallbacks; if you add the backend keys,
  add them additively so old checkpoints still render.
- Status/label vocabulary: backend enums live in `orchestrator/node.py`
  (`NodeStatus`, `NodeLabel`); note fixtures use `"completed"`
  (`test_api_schema_contract.py:38`) where runtime emits `"success"` — do not
  "fix" the fixture as part of this subtask.
- `_save_checkpoint` writes `nodes_tree.json` as `{experiment_goal, nodes}`
  while `tree.json` is `{run_id, ..., nodes}`; the reader precedence is
  `tree.json → nodes_tree.json → node_*/tree.json`. The adapter must not assume
  the top-level keys beyond `nodes`.
- Keep the watcher's 1 s poll + mtime cache (`state_sync.py` 68–116) and the
  `_broadcast`/`_do_broadcast` split (facade lookup via `api_state`, 47–51)
  untouched — only the tree-loading call changes.
- `pipeline/orchestrator.build_scientific_data` and `bfts_loop._save_checkpoint`
  are the write/science-export side and are explicitly out of scope; do not
  refactor them here even though they also call `to_dict()`.
- This document is planning-only; no runtime code, prompts, configs, workflows,
  or directory names were modified in producing it.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **024** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
