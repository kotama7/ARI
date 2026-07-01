# Subtask 013: Refactor Memory Boundary

> Phase 3: Core Architecture · Priority: High · Classification: **ADAPT**
> Depends on: **007** (`docs/refactoring/007_subtask_index.md`) · Changes runtime code: **Yes**
> Grounded on ari-core `0.9.0`, `ari-skill-memory` `0.6.0`, planning date 2026-07-01.

---

## 1. Goal

Collapse the sprawled `ari-core → ari_skill_memory` import edge into a **single sanctioned funnel** inside `ari-core/ari/memory/`, so that the one allowed core→skill dependency (introduced v0.6.0, documented in `docs/refactoring/003_dependency_boundary_report.md` §11) is confined to `ari/memory/**` instead of being spread across 12 modules. Simultaneously **document and stabilize the two-tier memory abstraction** (the narrow `ari.memory.MemoryClient` ABC vs. the rich skill-side `MemoryBackend` ABC) without merging them or altering any method signature.

This is a **boundary / import-hygiene** refactor. No memory semantics, storage format, MCP tool, ABC method, or dashboard endpoint changes. Success = every non-`ari/memory/` module reaches the skill backend through `ari.memory.*` re-exports, and a future import-boundary checker (subtask 026, not built here) can assert "exactly one core→skill import path, rooted at `ari/memory/**`".

## 2. Background

The memory subsystem has **two parallel, deliberately divergent abstractions** that do not share types:

- **Core `MemoryClient` ABC** — `ari-core/ari/memory/client.py:8`, a 3-method interface (`add`, `search`, `get_all`) for the ReAct-trace view. Concrete impls: `LettaMemoryClient` (`letta_client.py:22`, default since v0.6.0, delegates to the skill), `FileMemoryClient` (`file_client.py:16`, legacy JSONL, migration-only), `LocalMemoryClient` (`local_client.py:8`, tests).
- **Skill `MemoryBackend` ABC** — `ari-skill-memory/src/ari_skill_memory/backends/base.py:8`, a rich ~17-method interface (node-scope `add_memory`/`search_memory`/`get_node_memory`/`clear_node_memory`/`get_experiment_context`, plus library-only `list_all_nodes`, `bulk_import`, `list_react_entries`, `react_add`/`react_search`/`react_get_all`, `seed_core_memory`, `purge_checkpoint`, `health`). Impls: `InMemoryBackend`, `LettaBackend`, produced by the factory `ari_skill_memory.backends.get_backend(...)` (`backends/__init__.py:15`).

`LettaMemoryClient` is a thin adapter: its three methods forward to the backend's `react_add`/`react_search`/`react_get_all` (`letta_client.py:35,53,67`). So the intended layering is already **`MemoryClient` (narrow) → `MemoryBackend` (rich) → Letta/in-memory**.

The problem is that most callers **skip `ari.memory` entirely** and import `ari_skill_memory.backends.get_backend` directly to reach the rich API. A repo-wide grep for `ari_skill_memory` inside `ari-core/ari/` returns **13 import lines across 12 files** — only two of which (`memory/letta_client.py`, `memory/auto_migrate.py`) are the sanctioned home. The dependency-boundary report explicitly recommends centralizing this so the checker can "additionally restrict the allowed `ari_skill_memory` import to `ari/memory/**`" (`003_dependency_boundary_report.md` §11, lines 586-587).

## 3. Scope

In scope:

1. Add a single thin re-export surface in `ari-core/ari/memory/` (a new `backend.py` accessor module + `__init__.py` exports) that forwards to `ari_skill_memory.backends.get_backend` / `clear_backend_cache` and to `ari_skill_memory.context_builder` where needed — preserving the exact return objects (no wrapping, no behavior change).
2. Redirect the **10 sprawl call sites** (files outside `ari/memory/` that import `ari_skill_memory`) to import from `ari.memory.*` instead.
3. Keep the two ABCs as-is; add authoritative module/`README.md` documentation of the two-tier relationship so future readers stop re-reaching into the skill.
4. Leave `ari/memory/letta_client.py` and `ari/memory/auto_migrate.py` importing `ari_skill_memory` directly (they are the sanctioned home and become the funnel's internals).

Out of scope: see §4.

## 4. Non-Goals

- **Do NOT merge the two ABCs** (`MemoryClient` and `MemoryBackend`). The subtask index is explicit: "Unify without changing tool names/schema or the ABC methods" (`007_subtask_index.md:627`). Method names/signatures on both ABCs are frozen here.
- Do NOT change any MCP tool name, `inputSchema`, or the `{"result"|"error"}` return envelope of `ari-skill-memory/src/server.py` (15 `@mcp.tool` functions).
- Do NOT change the CoW bridge contract (`_set_current_node`, `$ARI_CURRENT_NODE_ID`) in `server.py:212`, `ari/mcp/client.py:263` (`_COW_TOOLS`), or `ari/agent/loop.py:31` (`_INTERNAL_MCP_TOOLS`).
- Do NOT change storage formats or paths (`memory_store.jsonl`, `memory.json`, `memory_access.jsonl`, per-checkpoint Letta collections).
- Do NOT fix the `FileMemoryClient._load` JSON-vs-JSONL question (`file_client.py:44`) here — flag it as REVIEW_REQUIRED for a separate ticket; it is legacy migration-only code and touching it risks the v0.5→v0.6 import path.
- Do NOT move/rename `ari/memory/` or `ari-skill-memory/` directories, and do NOT build the import-boundary checker (that is subtask 026).
- Do NOT declare `ari_skill_memory` in `ari-core/pyproject.toml` dependencies (it is intentionally editable-installed by `setup.sh`; see `pyproject.toml:27-31`).

## 5. Current Files / Directories to Inspect

Core memory package `ari-core/ari/memory/` (6 py, 343 LOC total):

| File | LOC | Role |
|---|---|---|
| `ari-core/ari/memory/client.py` | 22 | `MemoryClient` ABC (`add`/`search`/`get_all`) — **KEEP** |
| `ari-core/ari/memory/letta_client.py` | 74 | `LettaMemoryClient`, sanctioned skill import at `:27` — **KEEP (funnel internal)** |
| `ari-core/ari/memory/file_client.py` | 82 | `FileMemoryClient` legacy JSONL — **KEEP**; `_load` JSON/JSONL is REVIEW_REQUIRED |
| `ari-core/ari/memory/local_client.py` | 24 | `LocalMemoryClient` (tests) — **KEEP** |
| `ari-core/ari/memory/auto_migrate.py` | 118 | `maybe_auto_migrate`, sanctioned skill import at `:54` — **KEEP (funnel internal)** |
| `ari-core/ari/memory/__init__.py` | 23 | package docstring + intended public symbols — **ADAPT (add re-exports)** |
| `ari-core/ari/memory/README.md` | — | per-dir README — **ADAPT (document two-tier)** |

Skill boundary (consumed as a library API, not modified):

- `ari-skill-memory/src/ari_skill_memory/backends/base.py` (80) — `MemoryBackend` ABC.
- `ari-skill-memory/src/ari_skill_memory/backends/__init__.py` (63) — `get_backend`, `clear_backend_cache` factory (per-checkpoint cache).
- `ari-skill-memory/src/ari_skill_memory/backends/{in_memory.py (392), letta_backend.py (665), letta_client.py (402)}`.
- `ari-skill-memory/src/server.py` (238) — 15 FastMCP tools; CoW bridge `_set_current_node:212`.
- `ari-skill-memory/src/ari_skill_memory/context_builder.py` (91) — reached directly by `pipeline/verified_context.py`.

Sprawl call sites (the 10 files to redirect — all outside `ari/memory/`):

- `ari-core/ari/agent/loop.py:1047` (`get_backend as _gmb`)
- `ari-core/ari/cli/commands.py:129` (`get_backend, clear_backend_cache`)
- `ari-core/ari/cli/run.py:537` (`get_backend`)
- `ari-core/ari/memory_cli.py:49` (`get_backend`)
- `ari-core/ari/pipeline/orchestrator.py:250` (`get_backend as _get_mem_backend`)
- `ari-core/ari/pipeline/verified_context.py:74` (`get_backend`) **and** `:76` (`context_builder as _cb`)
- `ari-core/ari/viz/api_memory.py:40` (`get_backend`)
- `ari-core/ari/viz/checkpoint_lifecycle.py:89` (`get_backend`)
- `ari-core/ari/viz/node_work_api.py:193` (`get_backend`)
- `ari-core/ari/viz/routes.py:203` (`get_backend`)

Wiring / consumers of the narrow ABC (verify unbroken, do not edit for redirect):

- `ari-core/ari/core.py:101,130` — `build_runtime` constructs `LettaMemoryClient`.
- `ari-core/ari/orchestrator/bfts.py:18,422,524` — takes `MemoryClient` params.
- `ari-core/ari/agent/loop.py:20,370` — takes `MemoryClient` param.
- `ari-core/ari/protocols/__init__.py:14` — notes `MemoryClient` as a future Protocol.
- `ari-core/ari/migrations/v05_to_v07/memory.py:20` — re-exports `maybe_auto_migrate`.

## 6. Current Problems

1. **Edge sprawl.** 13 `ari_skill_memory` import lines across 12 core files; 10 of them bypass `ari.memory`. This makes the "single sanctioned exception" claim (`003` §11) unverifiable by a mechanical checker, because the allowlist would have to name 12 files rather than one directory.
2. **Two entry idioms for the same factory.** Callers variously alias `get_backend as _gmb` (`loop.py:1047`), `as _get_mem_backend` (`orchestrator.py:250`), or import bare (`viz/*`, `cli/*`), and all repeat `PathManager.set_checkpoint_dir_env(...)` + `get_backend(checkpoint_dir=...)` boilerplate (e.g. `letta_client.py:25-28`, `api_memory.py:38-41`, `auto_migrate.py:51-55`). No single documented accessor.
3. **Second reached module.** `pipeline/verified_context.py:76` imports `ari_skill_memory.context_builder` directly — a distinct skill module beyond `backends`, widening the surface the checker must allow.
4. **Layering is implicit, not documented.** `MemoryClient` is a 3-method adapter over the ~17-method `MemoryBackend`, but nothing states this, so new code keeps reaching past the adapter into `get_backend` to get the rich API. The two ABCs "don't share types and diverge (unconfirmed whether intentional)" per the eval findings.
5. **REVIEW_REQUIRED (out of scope to fix here):** `FileMemoryClient._load` (`file_client.py:44`) parses the whole file as a single JSON array while the canonical path is line-wise `memory_store.jsonl` and `auto_migrate._load_jsonl` (`auto_migrate.py:97`) reads it line-by-line — a possible JSON-vs-JSONL mismatch. Note it; do not change it.

## 7. Proposed Design / Policy

**Policy:** exactly one directory — `ari-core/ari/memory/` — may `import ari_skill_memory`. Everything else in `ari-core` reaches the skill backend through `ari.memory.*`.

**Design (ADAPT, thin passthrough — no behavior change):**

1. **New accessor module `ari-core/ari/memory/backend.py`** exposing:
   - `get_backend(checkpoint_dir=None, *, reset=False)` — forwards verbatim to `ari_skill_memory.backends.get_backend`, returning the identical `MemoryBackend` instance (do NOT wrap it — callers rely on the full rich API and per-checkpoint caching).
   - `clear_backend_cache()` — forwards to the skill factory (used by `cli/commands.py:129` and tests).
   - `build_verified_context(backend, ancestor_ids, *, purpose="paper", limit=None)` — forwards to `ari_skill_memory.context_builder.build_verified_context`, so `verified_context.py:76` stops importing the skill's `context_builder` directly. (Alternatively re-export the `context_builder` module object; prefer the function forward to keep the surface minimal.)
   - Optionally `set_checkpoint_dir_env` is NOT duplicated here — callers keep using `ari.paths.PathManager` as today.

2. **Re-export from `ari-core/ari/memory/__init__.py`** the full intended public set: `MemoryClient`, `LettaMemoryClient`, `FileMemoryClient`, `LocalMemoryClient`, `maybe_auto_migrate`, plus the new `get_backend`, `clear_backend_cache`, `build_verified_context`. Add `__all__`. Guard the skill-touching re-exports so importing `ari.memory` never hard-fails if `ari_skill_memory` is absent (mirror the existing lazy/`try` style — several current sites already import `get_backend` inside functions, not at module top).

3. **Redirect the 10 sprawl sites** to `from ari.memory import get_backend` (and `clear_backend_cache` / `build_verified_context` as applicable), preserving each site's existing local-import placement (keep them function-local where they are today to avoid import-time cost and cycles — `viz`, `cli`, `pipeline`, `agent/loop` all import lazily now).

4. **Keep both ABCs; document the two-tier contract** in `ari/memory/__init__.py` and `ari/memory/README.md`: `MemoryClient` (narrow ReAct-trace adapter) sits on top of skill `MemoryBackend` (rich node-scope + typed + react). State that `ari_skill_memory` may be imported **only** from `ari/memory/**`.

Net effect: `grep -rl ari_skill_memory ari-core/ari` returns exactly the files under `ari/memory/` (`letta_client.py`, `auto_migrate.py`, and the new `backend.py`), enabling subtask 026's checker to set its allowlist to `ari/memory/**`.

## 8. Concrete Work Items

1. Create `ari-core/ari/memory/backend.py` with `get_backend`, `clear_backend_cache`, `build_verified_context` thin forwards (docstrings citing they are the sole sanctioned funnel).
2. Update `ari-core/ari/memory/__init__.py`: add re-exports + `__all__`, and expand the docstring with the two-tier layering + "only `ari/memory/**` imports `ari_skill_memory`" rule.
3. Update `ari-core/ari/memory/README.md` "Contents" to list `backend.py` and the funnel policy.
4. Redirect each sprawl site to `ari.memory`:
   - `ari/agent/loop.py:1047` → `from ari.memory import get_backend as _gmb`.
   - `ari/cli/commands.py:129` → `from ari.memory import get_backend, clear_backend_cache`.
   - `ari/cli/run.py:537` → `from ari.memory import get_backend`.
   - `ari/memory_cli.py:49` → `from ari.memory import get_backend`.
   - `ari/pipeline/orchestrator.py:250` → `from ari.memory import get_backend as _get_mem_backend`.
   - `ari/pipeline/verified_context.py:74,76` → `from ari.memory import get_backend, build_verified_context` (replace the direct `context_builder` call at the `_cb.build_verified_context(...)` site).
   - `ari/viz/api_memory.py:40` → `from ari.memory import get_backend`.
   - `ari/viz/checkpoint_lifecycle.py:89` → `from ari.memory import get_backend`.
   - `ari/viz/node_work_api.py:193` → `from ari.memory import get_backend`.
   - `ari/viz/routes.py:203` → `from ari.memory import get_backend`.
5. Verify `ari/memory/letta_client.py:27` and `ari/memory/auto_migrate.py:54` remain the sanctioned internal importers (either keep their direct `ari_skill_memory` import or route via the new `backend.py`; keeping direct is fine — they are inside `ari/memory/**`).
6. Run `grep -rn ari_skill_memory ari-core/ari` and confirm every hit is under `ari-core/ari/memory/`.
7. Leave a `# REVIEW_REQUIRED (subtask-out-of-scope):` note comment near `file_client.py:44` referencing the JSON/JSONL question — **only if** the surrounding line is otherwise touched; otherwise record it in this doc only (do not add stray edits).

## 9. Files Expected to Change

Create:

- `ari-core/ari/memory/backend.py` (new, ~30-50 LOC thin forwards)

Modify (core):

- `ari-core/ari/memory/__init__.py`
- `ari-core/ari/memory/README.md`
- `ari-core/ari/agent/loop.py`
- `ari-core/ari/cli/commands.py`
- `ari-core/ari/cli/run.py`
- `ari-core/ari/memory_cli.py`
- `ari-core/ari/pipeline/orchestrator.py`
- `ari-core/ari/pipeline/verified_context.py`
- `ari-core/ari/viz/api_memory.py`
- `ari-core/ari/viz/checkpoint_lifecycle.py`
- `ari-core/ari/viz/node_work_api.py`
- `ari-core/ari/viz/routes.py`

Not changed (verify only): `ari-core/ari/memory/letta_client.py`, `ari-core/ari/memory/auto_migrate.py`, `ari-core/ari/core.py`, `ari-core/ari/orchestrator/bfts.py`, and the entire `ari-skill-memory/` package.

## 10. Files / APIs That Must Not Be Broken

- **MCP tool contract** — `ari-skill-memory/src/server.py`: all 15 `@mcp.tool` names (`add_memory`, `search_memory`, `get_node_memory`, `clear_node_memory`, `get_experiment_context`, `add_experiment_result`, `add_failure_case`, `add_procedure_memory`, `add_reflection`, `add_reproducibility_event`, `search_research_memory`, `get_verified_context`, `audit_memory`, `consolidate_node_memory`, `_set_current_node`), their `inputSchema`, and the `mcp__memory__<tool>` fully-qualified naming.
- **CoW bridge** — `_set_current_node` / `$ARI_CURRENT_NODE_ID` (`server.py:212`), `ari/mcp/client.py:263` `_COW_TOOLS`, `ari/agent/loop.py:31` `_INTERNAL_MCP_TOOLS`.
- **Core internal ABCs** — `MemoryClient` (`client.py:8`, 3 methods) and skill `MemoryBackend` (`base.py:8`, ~17 methods): signatures frozen. `MemoryClient` consumers `bfts.py:422,524` and `loop.py:370` must still type-check.
- **`ari.public.verified_context`** — re-exports `build_verified_context` / `write_verified_context` / `render_grounded_block` from `ari.pipeline.verified_context`; the redirect must keep `verified_context.py`'s public functions identical (only its internal skill import changes).
- **Dashboard API** — `ari/viz/api_memory.py` handlers (`/api/memory/health|detect|start-local|stop-local`, `/api/checkpoint/{id}/memory_access`) and their JSON shapes consumed by the React frontend (`Tree/DetailPanelTabs/MemoryTab.tsx`, `MemoryEntryCard.tsx`).
- **CLI** — `ari memory` subcommands (`migrate/backup/restore/start-local/stop-local/prune-local/compact-access/health`) via `memory_cli.py`; `ari.migrations.v05_to_v07.memory.maybe_auto_migrate` re-export path.
- **Sanctioned-edge invariant** — `pyproject.toml:27-31` (do not add `ari_skill_memory` to declared deps); `.github/workflows/refactor-guards.yml:39` installs `ari-skill-memory` editable first.

## 11. Compatibility Constraints

- Pure import-path centralization: the funnel returns the **same** `MemoryBackend` object the callers use today (identity + per-checkpoint cache preserved via the skill factory). No adapter/wrapper that could change `.react_search`, `.list_all_nodes`, `.bulk_import`, etc.
- `ari.memory` must remain importable when `ari_skill_memory` is not installed (keep skill-touching forwards lazy / behind `try` as the current call sites already do), so `python -m compileall .` and non-memory tests do not regress.
- Preserve each site's existing lazy (function-local) import placement to avoid new import cycles among `viz` ↔ `pipeline` ↔ `agent` ↔ `memory`.
- No new runtime dependency; no change to `requirements.txt` / `requirements.lock`.
- Docstrings/README are the only doc surface touched; no VitePress/report co-change expected (verify against `scripts/docs/check_ref_coupling.py` and `docs-change-coupling.yml`).

## 12. Tests to Run

From repo root:

- `python -m compileall ari-core ari-skill-memory` (and `python -m compileall .` for the full tree).
- `ruff check .`
- `pytest -q ari-core/tests/test_memory.py ari-core/tests/test_no_user_home_writes.py ari-core/tests/test_idea_integration.py ari-core/tests/test_laptop_hpc_skill_drop.py ari-core/tests/test_viz_memory_api.py ari-core/tests/test_system_prompt_memory.py`
- `pytest -q ari-skill-memory/tests` (backend/CoW/ancestor-scope/backup-restore — note `ari-skill-memory/tests/test_backup_restore.py:14` imports `ari.memory_cli`, so this exercises the cross-package path).
- `pytest -q` (full suite) as the final gate; large memory-adjacent suites include `ari-core/tests/test_server.py` and `test_workflow_contract.py`.
- Boundary confirmation (manual): `grep -rn "ari_skill_memory" ari-core/ari` must return only paths under `ari-core/ari/memory/`.
- `bash scripts/run_all_tests.sh` if a full local gate is desired.

Frontend `npm test` / `npm run build` are **not required** (no `frontend/` change; the dashboard JSON contract is unchanged).

## 13. Acceptance Criteria

1. `grep -rn "ari_skill_memory" ari-core/ari` returns import lines **only** under `ari-core/ari/memory/` (`backend.py`, `letta_client.py`, `auto_migrate.py`).
2. `ari.memory` exports `get_backend`, `clear_backend_cache`, `build_verified_context`, `MemoryClient`, `LettaMemoryClient`, `FileMemoryClient`, `LocalMemoryClient`, `maybe_auto_migrate` (all in `__all__`).
3. All 10 sprawl sites import from `ari.memory` and behave identically (same backend object, same aliases where they mattered).
4. `python -m compileall .`, `ruff check .`, and `pytest -q` pass (including `ari-skill-memory/tests`).
5. Both ABCs unchanged (`git diff` shows no signature edits in `client.py` or `backends/base.py`); no MCP tool / dashboard / CLI surface diff.
6. `ari/memory/__init__.py` + `README.md` document the two-tier layering and the "`ari/memory/**`-only" import rule.
7. `ari.memory` imports cleanly even with `ari_skill_memory` uninstalled (skill forwards stay lazy).

## 14. Rollback Plan

Self-contained and low-risk: revert the single commit/branch. Because every change is either (a) a new file (`backend.py`) or (b) a one-line import-statement swap that resolves to the same `get_backend`/`context_builder` callables, `git revert` restores the prior direct-import graph with no data/format migration. No checkpoint, config, or storage state is touched, so rollback needs no runtime cleanup. If only the `verified_context.py` change misbehaves, it can be reverted in isolation (it is the only site touching `context_builder`).

## 15. Dependencies

Per the dependency graph, `007 -> 013`. Subtask **007** (`docs/refactoring/007_subtask_index.md`, the subtask index / Protocol-planning wave) must precede this work. This subtask is part of the "Core architecture extractions" wave (007 → 008..014) and shares the `ari/protocols` framing (`protocols/__init__.py:14` names `MemoryClient` as a future Protocol adopter).

This subtask **enables but does not include** subtask **026** (import-boundary checker, `scripts/check_import_boundaries.py` — listed as MISSING/to-be-designed): after 013, that checker's allowlist for the sanctioned core→skill edge can be tightened from 12 files to `ari/memory/**`. Also relevant: the inventory subtasks that must precede any runtime code change are **001, 002, 020, 036, 045, 053, 059, 060, 067** — 013 assumes those planning/inventory gates are already satisfied for Phase 3.

## 16. Risk Level

**Changes runtime code: Yes.** **Risk: Low–Medium.**

- Low because every edit is a mechanical import redirect to the identical callable, plus one additive module and doc text; no logic, format, or contract change.
- Medium tail-risk from: import ordering / lazy-import cycles among `viz`/`pipeline`/`agent`/`memory` (mitigated by keeping imports function-local), and the `verified_context.py` `context_builder` swap (mitigated by an exact-forward function and targeted tests). The wide fan-out (12 files) raises review surface, not runtime danger.

## 17. Notes for Implementer

- **Do not wrap the backend.** `get_backend` must return the raw `MemoryBackend`; callers such as `pipeline/orchestrator.py:250`, `viz/node_work_api.py:193`, and `agent/loop.py:1047` use rich methods (`list_all_nodes`, `react_*`, `bulk_get_node_memory`) that a narrow `MemoryClient` does not expose. This is exactly why the two ABCs are NOT merged (§4).
- Preserve the per-site aliases that already exist (`_gmb`, `_get_mem_backend`) to keep diffs minimal and blame-stable.
- `pipeline/verified_context.py` currently does `from ari_skill_memory import context_builder as _cb` then `_cb.build_verified_context(backend, lineage, purpose="paper")` (`:76,82`). Route this through `ari.memory.build_verified_context(backend, lineage, purpose="paper")` so no code outside `ari/memory/` names `context_builder`.
- Keep `ari/memory/letta_client.py:25-28`'s `PathManager.set_checkpoint_dir_env` + `get_backend` sequence intact; it is the reference pattern.
- The "sonfigs" directory referenced in some master prompts **does not exist**; irrelevant here — the memory subsystem has no config-triple entanglement.
- REVIEW_REQUIRED carry-over (do not fix here): `FileMemoryClient._load` JSON-array vs. `memory_store.jsonl` line-wise mismatch (`file_client.py:44` vs `auto_migrate.py:97`). Record as a follow-up ticket; it is legacy migration-only.
- After edits, the definitive check is the grep in §13.1 — treat any `ari_skill_memory` hit outside `ari/memory/` as a failing acceptance criterion.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **013** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
