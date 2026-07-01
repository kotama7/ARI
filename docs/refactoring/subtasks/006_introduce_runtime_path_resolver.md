# Subtask 006: Introduce Runtime Path Resolver

- **Program:** ARI Refactoring — Phase 2: Repository Hygiene
- **Subtask ID:** 006 (`introduce_runtime_path_resolver`)
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core` version `0.9.0`)
- **Canonical language:** English
- **Classification of this subtask:** **ADAPT** (a `RuntimePathResolver` is introduced *behind* the existing `PathManager`; the public symbol `ari.public.paths.PathManager` and all its methods stay put).
- **Planning status:** PLANNING ONLY. This document changes no runtime code, imports, prompts, configs, workflows, frontend, or directory names. It is a design/execution spec that a fresh coding session can pick up and implement.

> Naming note (carried through the whole program): there is **NO `sonfigs/` directory** anywhere in the repo (`find -iname '*sonfig*'` returns nothing). The confusable trio is `ari-core/ari/config/` (Python discovery code — `finder.py`), `ari-core/ari/configs/` (packaged defaults data + `_loader.py`), and `ari-core/config/` (rubric/profile/`workflow.yaml` data). There is also **no top-level `pyproject.toml`** (`ari-core/pyproject.toml` is the core manifest). This subtask does not touch the config trio; it is called out only because the resolver is adjacent to `ari/config/finder.py::package_config_root()`.

---

## 1. Goal

Introduce a single `RuntimePathResolver` that becomes the one place where ARI *reads* the `ARI_CHECKPOINT_DIR` run pin and resolves run-scoped files, so that:

1. The scattered, direct `os.environ.get("ARI_CHECKPOINT_DIR")` reads across the core are funnelled through one seam (today the pin is read directly in at least eight production modules — see §6).
2. Both the **current flat checkpoint layout** and the **future bucketed `runs/<run_id>/{workspace,checkpoints,artifacts,traces,reports}` layout** designed in subtask 005 are resolvable through the same API (bucket-first, then flat-root fallback), making 005's on-disk migration safe to land later without a flag-day.
3. The canonical workspace-root decision produced by subtask **004** (`define_runtime_path_policy`) is implemented in exactly one function, reconciling the confirmed disagreement between `auto_config()` (`config/__init__.py:583-592`, defaults to `{repo_root}/workspace/checkpoints/{run_id}`) and the shipped `ari-core/config/default.yaml:14,39` (`./checkpoints/{run_id}/`).

The resolver **sits behind** `PathManager`; `PathManager` becomes a thin facade that delegates to it. The public re-export `ari.public.paths.PathManager` (and every method/attribute it exposes) is unchanged. No on-disk data moves in this subtask, and new runs keep writing the **flat** layout by default (behavior-preserving) until subtask 005 flips the default.

## 2. Background

`PathManager` (`ari-core/ari/paths.py`, ~304 lines) is already the documented single source of truth for every directory ARI touches. It derives four roots from a `workspace_root` (default `"."` = cwd): `checkpoints_root`, `experiments_root`, `staging_root`, and `paper_registry_root` (overridable via `ARI_PAPER_REGISTRY_DIR`). It is re-exported verbatim by `ari-core/ari/public/paths.py` (5 lines) as part of the stable `ari.public.*` surface. `PathManager` already centralizes the env pin through four helpers: `checkpoint_dir_from_env()`, `set_checkpoint_dir_env()`, `from_env()`, and `from_checkpoint_dir()` (the last walks up to the outermost `checkpoints/` ancestor to recover `workspace_root`).

Two structural problems remain that this subtask targets:

- **The env pin is still read directly in several modules** that never route through `PathManager` (see §6), so the "single spelling" invariant is only partially enforced.
- **Every read of a run-scoped file assumes the flat checkpoint layout.** `PathManager.META_FILES` (`paths.py:51-76`) has to enumerate 19 metadata filenames precisely *because* metadata, figures, LaTeX, sandboxes, ORS grades and access logs are all intermixed flat in the checkpoint root (~46 sibling files on a real run). Subtask 005 proposes splitting these into `runs/<run_id>/{workspace,checkpoints,artifacts,traces,reports}`, but that migration is only safe once reads are centralized and dual-layout-aware — which is what this subtask builds.

Subtask 004 (the direct predecessor) produces the *policy* (which root is canonical, how the `default.yaml`↔`auto_config()` split is reconciled). Subtask 005 (a sibling that also depends on 004) produces the *target directory layout*. This subtask (006) produces the *mechanism* (`RuntimePathResolver`) that both of those depend on operationally: 005's own text names "subtask 006 (backward-compatible path adapter)" as its migration enabler.

> Cross-reference caveat: the 005 planning doc (`docs/refactoring/005_directory_consolidation_plan.md:7`) informally labels 004 as "`RuntimePathResolver`" and 006 as "backward-compatible path adapter". The authoritative subtask index (`docs/refactoring/007_subtask_index.md:51-53`) and the master prompt are canonical: **004 = `define_runtime_path_policy` (policy doc, no runtime change); 006 = `introduce_runtime_path_resolver` (this subtask, runtime change).** Where 005 says "004 (resolver)" read "the resolver introduced by 006, following 004's policy".

## 3. Scope

In scope (runtime code change = **Yes**):

- Add a new `RuntimePathResolver` (a class; recommended location `ari-core/ari/paths.py` alongside `PathManager`, or a new sibling module `ari-core/ari/runtime_paths.py` imported by `paths.py`). `RuntimePathResolver` **does not exist today** (`grep -rn "RuntimePathResolver" ari-core/` returns nothing).
- Give the resolver: (a) one `workspace_root` resolution function implementing 004's policy; (b) run-scoped *file* resolution with dual-layout fallback — e.g. `checkpoint_file(name)` that returns the bucketed path when it exists, else the flat `{checkpoint_dir}/name`; (c) accessors for the new 005 buckets (`artifacts_dir`, `traces_dir`, `reports_dir`, node `workspace_dir`) that degrade gracefully to the flat root when the bucket is absent.
- Make `PathManager` delegate to the resolver so its existing methods (`checkpoint_dir`, `node_work_dir`, `log_file`, the four roots, `from_env`, `from_checkpoint_dir`, `checkpoint_dir_from_env`, `set_checkpoint_dir_env`) keep their exact signatures and return values for the flat layout.
- Route the direct `ARI_CHECKPOINT_DIR` reads listed in §6 through the resolver (this can be done incrementally; the resolver seam is the deliverable, wholesale call-site migration can trail).
- Extend `ari-core/tests/test_paths.py` with resolver + dual-layout tests.

Explicitly *behavior-preserving* in this subtask: new runs still emit the flat checkpoint layout; the resolver only *adds* the ability to resolve a bucketed layout that 005 will later populate.

## 4. Non-Goals

- **No physical directory migration / re-bucketing of existing checkpoints.** That is 005's on-disk migration plus a future `ari migrate` extension under `ari-core/ari/migrations/`. This subtask writes zero data and moves zero files.
- **No default layout switch.** New runs keep writing flat; do not make `runs/<id>/…` the default write path here (that flip is gated behind 005 landing default-on for ≥1 minor version).
- **No change to the `ARI_CHECKPOINT_DIR` spelling, the env hand-off protocol, or `ARI_PAPER_REGISTRY_DIR`.**
- **No config-trio consolidation** (`ari/config/` vs `ari/configs/` vs `ari-core/config/`) — that is subtask 003. Repointing `package_config_root()` through the resolver is explicitly deferred to 003/005 coordination.
- **No CLI option / subcommand changes.**
- **No changes to `ari/checkpoint.py` JSON I/O semantics or the `META_FILES` set** (the resolver *reads* through the same classification; it does not redefine which files are metadata).
- **No workflow.yaml templating change** (`{{checkpoint_dir}}` output paths stay literal in this subtask).

## 5. Current Files / Directories to Inspect

Real repo paths (verified 2026-07-01):

| Path | LOC / note | Why relevant |
|------|-----------|--------------|
| `ari-core/ari/paths.py` | ~304 | Home of `PathManager`; the resolver lands here (or a sibling module imported here). |
| `ari-core/ari/public/paths.py` | 5 | `from ari.paths import PathManager` re-export — the public contract to preserve. |
| `ari-core/ari/config/finder.py` | 145 | `package_config_root()` (finder.py:28-42) and the four-tier `find_workflow_yaml` search (finder.py:60-100); resolver-adjacent, do not repoint here (003/005). |
| `ari-core/ari/config/__init__.py` | ~628 | `auto_config()` (line 575) pins the checkpoint dir to `{repo_root}/workspace/checkpoints/{run_id}` at `:583-592`; already calls `PathManager.checkpoint_dir_from_env()` at `:586`. |
| `ari-core/config/default.yaml` | — | `checkpoint.dir: ./checkpoints/{run_id}/` at line 14 and `:39` — the disagreeing default the resolver policy must reconcile. |
| `ari-core/ari/checkpoint.py` | 198 | Flat-file JSON I/O + `save_tree_incremental`; the resolver must keep resolving the files it reads/writes. |
| `ari-core/ari/orchestrator/bfts.py` | 845 | `_resolve_pm_and_run_id()` (bfts.py:43-60) already routes through `PathManager.checkpoint_dir_from_env()` — the pattern to generalize. |
| `ari-core/ari/cli/run.py` | — | run_id generation `{strftime}_{slug}` (run.py:322-323); env hand-off (run.py:280-283, 538). |
| `ari-core/ari/cli/__init__.py` | — | direct `os.environ.get("ARI_CHECKPOINT_DIR")` at line 52 for `.env` discovery. |
| `ari-core/ari/agent/loop.py` | 1630 | direct env read at `:231`, direct env write at `:483`. |
| `ari-core/ari/pipeline/stage_runner.py` | — | direct env touch at `:362`, `:410` (child-process pin). |
| `ari-core/ari/lineage.py` | — | direct env read at `:53` (parent-of-checkpoint logs logic). |
| `ari-core/ari/cost_tracker.py` | — | `from_env`-style init from the pin at `:214`. |
| `ari-core/ari/memory_cli.py` | — | requires the pin at `:41`. |
| `ari-core/ari/viz/api_experiment.py` | 929 | sets `proc_env["ARI_CHECKPOINT_DIR"]` at `:781`. |
| `ari-core/ari/viz/api_orchestrator.py` | — | sets `proc_env["ARI_CHECKPOINT_DIR"]` at `:284`. |
| `ari-core/tests/test_paths.py` | 371 (54 `PathManager` refs) | the test suite the resolver must not regress and must extend. |
| `ari-core/tests/test_resolve_node_work_dir.py`, `test_node_report.py`, `test_launch_config.py`, `test_settings_roundtrip.py`, `test_server.py` | — | other `PathManager` consumers (6/4/1/1/5 refs). |
| `docs/refactoring/004_*` (policy), `docs/refactoring/005_directory_consolidation_plan.md` | — | the policy input and target-layout input for this subtask. |

Directories (all `.gitignore`d — no git-tracking migration cost): root `checkpoints/` (empty, legacy), `workspace/checkpoints/<ts_slug>/`, `workspace/experiments/<ts_slug>/<node_id>/`, `workspace/staging/<ts>/`, `paper_registry/` (via `ARI_PAPER_REGISTRY_DIR`).

Full `PathManager` consumer set (38 files from `grep -rln PathManager --include=*.py ari-core/`): production — `agent/loop.py`, `cli/{bfts_loop,commands,__init__,migrate,projects,run}.py`, `config/{finder,__init__}.py`, `core.py`, `cost_tracker.py`, `lineage.py`, `memory/{auto_migrate,letta_client}.py`, `memory_cli.py`, `orchestrator/{bfts,node_selection}.py`, `orchestrator/node_report/builder.py`, `paths.py`, `pipeline/{orchestrator,stage_runner}.py`, `public/{__init__,paths}.py`, `viz/{api_experiment,api_memory,api_paperbench,api_tools,checkpoint_lifecycle,ear,node_work_api,routes,state}.py`; tests — `test_{paths,resolve_node_work_dir,node_report,launch_config,settings_roundtrip,server}.py`.

## 6. Current Problems

1. **The run pin is read directly in ≥8 production modules, bypassing `PathManager`.** `grep -rn ARI_CHECKPOINT_DIR --include=*.py ari-core/` (excluding tests and docstrings) shows direct `os.environ` access at: `cli/__init__.py:52`, `agent/loop.py:231` and `:483`, `pipeline/stage_runner.py:362,410`, `lineage.py:53`, `cost_tracker.py:214`, `memory_cli.py:41`, `viz/api_experiment.py:781`, `viz/api_orchestrator.py:284`. Some (`bfts.py:44`, `config/__init__.py:586`) already route through `PathManager.checkpoint_dir_from_env()` — the good pattern that is not yet universal. The spelling/behavior of the pin is therefore duplicated instead of owned by one seam.

2. **Workspace-root disagreement (confirmed, REVIEW_REQUIRED from 004/005).** `auto_config()` (`config/__init__.py:583-592`) defaults to `{repo_root}/workspace/checkpoints/{run_id}`, while `ari-core/config/default.yaml:14` and `:39` still say `./checkpoints/{run_id}/`. The empty root `checkpoints/` dir exists precisely because of this split. There is no single function that owns "what is the workspace root".

3. **Every run-scoped read hard-assumes the flat layout.** `{checkpoint_dir}/tree.json`, `/results.json`, `/cost_trace.jsonl`, `/idea.json`, figures, `full_paper.tex`, `ors_*.json`, `repro_sandbox/`, etc. are all resolved as siblings. There is no seam that could resolve the same logical file in a bucketed `runs/<id>/{checkpoints,artifacts,traces,reports}/` layout, so 005's migration cannot be attempted incrementally.

4. **`META_FILES` classification is coupled to flatness.** The 19-name `META_FILES` frozenset (`paths.py:51-76`) plus the `.log` extension and the `memory_access.*.jsonl` regex exist to keep metadata out of node work dirs *because* it is intermixed with artifacts. A resolver that knows about buckets is a prerequisite to eventually shrinking this coupling (out of scope to change here, but the resolver must preserve the classification exactly).

## 7. Proposed Design / Policy

**Design principle:** the resolver is an *internal* mechanism; `PathManager` remains the public face (`ari.public.paths.PathManager`). Implement 004's policy in the resolver, not in `auto_config()` or `default.yaml`.

### 7.1 `RuntimePathResolver` responsibilities

- **Own the workspace-root decision (single function).** Precedence should follow 004's policy; the observed intended precedence is: explicit `ARI_CHECKPOINT_DIR` (recover root via the existing walk-up) → explicit `workspace_root` argument → `ARI_ROOT` env (already read in `cli/__init__.py:46`) → `{repo_root}/workspace` (matching `auto_config()`), with cwd (`.`) as the last-resort default so `ari run` from an arbitrary cwd keeps working. The resolver must expose this as one method; `auto_config()` and every direct env reader call it instead of recomputing.
- **Own the env pin read/write.** Wrap `checkpoint_dir_from_env()` / `set_checkpoint_dir_env()` so no other module reads/writes the raw variable. Keep `from_checkpoint_dir()`'s "walk up to the outermost `checkpoints/` ancestor, else use direct parent" recovery (`paths.py:278-298`) verbatim — several tests and the GUI hand-off depend on it.
- **Dual-layout file resolution.** Add `checkpoint_file(name)` (and bucket accessors below) that return the **bucketed path when the bucket exists on disk, else the flat `{checkpoint_dir}/name`**. For *writes*, default to flat (behavior-preserving); expose a mode/flag the future 005 flip can set to write bucketed. Resolution order is bucket→flat so a partially-migrated run still resolves.
- **Bucket accessors for the 005 target layout.** `workspace_dir(node_id)` → `runs/<id>/workspace/<node_id>` or legacy `experiments/<run_id>/<node_id>`; `artifacts_dir()`, `traces_dir()`, `reports_dir()` → the new buckets, each falling back to the flat checkpoint root when absent. These must be additive and inert until 005 populates them.
- **Preserve `META_FILES` semantics.** Reuse `PathManager.is_meta_file()` / `META_FILES` / `META_EXTENSIONS` / `_META_PATTERNS` unchanged; the resolver may *consult* them but must not redefine them.

### 7.2 `PathManager` becomes a facade

`PathManager` keeps its public API byte-for-byte and delegates internally. Concretely: `checkpoint_dir(run_id)`, `node_work_dir(run_id, node_id)`, `log_dir/log_file`, `uploads_dir`, `cost_trace`, `cost_summary`, `idea_file`, the four `*_root` properties, `ensure_*`, `is_meta_file`, `slugify`, `project_settings_path`, `project_memory_path`, `checkpoint_dir_from_env`, `set_checkpoint_dir_env`, `from_env`, `from_checkpoint_dir`, `__repr__` all keep identical signatures and return the same values for the flat layout. Where useful, `PathManager` instances hold or construct a `RuntimePathResolver` and forward to it.

### 7.3 Public surface

Do **not** remove or rename anything from `ari.public.paths`. Optionally *add* `RuntimePathResolver` to `ari.public.paths.__all__` only if a skill needs it — default recommendation is to keep the resolver internal and expose behavior solely through `PathManager` to minimize the public contract.

## 8. Concrete Work Items

1. **Land 004 first** (policy) and read 005's target-layout section so the bucket names (`workspace/checkpoints/artifacts/traces/reports`) are authoritative.
2. **Add `RuntimePathResolver`** in `ari-core/ari/paths.py` (or a new `ari-core/ari/runtime_paths.py` imported by `paths.py`). Implement: `workspace_root` resolution (§7.1), env pin ownership, `checkpoint_dir(run_id)`, `checkpoint_file(name)` with bucket→flat fallback, `node_work_dir/workspace_dir`, `artifacts_dir/traces_dir/reports_dir`, `from_env`, `from_checkpoint_dir`.
3. **Refactor `PathManager` to delegate** to the resolver while preserving every current method/attribute (see §7.2). Keep `META_FILES` and the classifier where they are.
4. **Route direct env reads through the resolver** (incremental, low-risk first): replace `os.environ.get("ARI_CHECKPOINT_DIR")` in `cli/__init__.py:52`, `lineage.py:53`, `cost_tracker.py:214`, `memory_cli.py:41`, `agent/loop.py:231`, and the two `proc_env[...]=` set-sites (`viz/api_experiment.py:781`, `viz/api_orchestrator.py:284`) plus `pipeline/stage_runner.py:362,410` with resolver calls. Generalize `bfts.py:_resolve_pm_and_run_id` to the resolver.
5. **Reconcile `auto_config()`** (`config/__init__.py:583-592`) to obtain the checkpoint dir from `resolver.workspace_root`/`resolver.checkpoint_dir` instead of the inline `parents[3] / "workspace" / "checkpoints" / "{run_id}"` arithmetic — implementing 004's chosen root without changing the emitted default for existing cwd-relative launches. (Do **not** edit `default.yaml` here unless 004's policy explicitly requires it; if it does, gate that behind the adapter so `./checkpoints/{run_id}/` still resolves.)
6. **Extend tests** (`ari-core/tests/test_paths.py`): resolver construction, workspace-root precedence, `checkpoint_file` bucket→flat fallback (both layouts on `tmp_path`), bucket accessors' graceful degradation, and a regression asserting `PathManager` public methods are unchanged for the flat layout.
7. **Run the full gate** (§12) and confirm `test_resolve_node_work_dir.py`, `test_node_report.py`, `test_launch_config.py`, `test_settings_roundtrip.py`, `test_server.py` stay green.

## 9. Files Expected to Change

Primary (mechanism):

- `ari-core/ari/paths.py` — add `RuntimePathResolver`; make `PathManager` a delegating facade. (Or add `ari-core/ari/runtime_paths.py` — a new file — and import it here.)
- `ari-core/ari/public/paths.py` — unchanged by default; only touch if the team decides to additively export `RuntimePathResolver` (not recommended for a minimal contract).

Incremental call-site routing (optional within this subtask, but the resolver seam is the deliverable):

- `ari-core/ari/config/__init__.py` (`auto_config`, ~`:583-592`)
- `ari-core/ari/cli/__init__.py` (`:52`)
- `ari-core/ari/agent/loop.py` (`:231`, `:483`)
- `ari-core/ari/pipeline/stage_runner.py` (`:362`, `:410`)
- `ari-core/ari/lineage.py` (`:53`)
- `ari-core/ari/cost_tracker.py` (`:214`)
- `ari-core/ari/memory_cli.py` (`:41`)
- `ari-core/ari/viz/api_experiment.py` (`:781`)
- `ari-core/ari/viz/api_orchestrator.py` (`:284`)
- `ari-core/ari/orchestrator/bfts.py` (`_resolve_pm_and_run_id`, `:43-60`)

Tests:

- `ari-core/tests/test_paths.py` — extended (new resolver + dual-layout cases).

Explicitly **not** changed here: `ari-core/config/default.yaml` (unless 004 mandates, gated behind adapter), `ari-core/ari/checkpoint.py`, `ari-core/config/workflow.yaml`, `ari-core/ari/config/finder.py`, any frontend file, any `.github/workflows/` file.

## 10. Files / APIs That Must Not Be Broken

- **`ari.public.paths.PathManager`** (re-exported from `ari-core/ari/public/paths.py`) — every method and attribute: the four `*_root` properties, `checkpoint_dir`, `node_work_dir`, `log_dir`, `log_file`, `uploads_dir`, `cost_trace`, `cost_summary`, `idea_file`, `new_staging_dir`, `ensure_checkpoint`, `ensure_uploads`, `ensure_node_work_dir`, `project_settings_path`, `project_memory_path`, `is_meta_file`, `slugify`, `checkpoint_dir_from_env`, `set_checkpoint_dir_env`, `from_env`, `from_checkpoint_dir`, `META_FILES`, `META_EXTENSIONS`, `__repr__`. Signatures and flat-layout return values must be identical.
- **`ARI_CHECKPOINT_DIR` env hand-off contract** — CLI → MCP skills / Letta / delete subprocesses (`set_checkpoint_dir_env`, and the two `proc_env[...]=` writers in viz). Child processes must still bind to the same run.
- **`ARI_PAPER_REGISTRY_DIR`** override for `paper_registry_root` (`paths.py:110-129`).
- **Checkpoint / output file format** (`ari/checkpoint.py`; `META_FILES` classification) — the resolver reads through the same semantics; the on-disk format is unchanged.
- **`ari-skill-*` → `ari-core` stable interface** — skills import from `ari.public.paths` (and `ari.public.run_env` / `ari.public.container` / etc.); none of those import paths change.
- **CLI console script `ari = ari.cli:app`** and all subcommands — no option or side-effect change.
- **Dashboard API** (`ari/viz/routes.py` + `api_*.py`) — endpoint paths and JSON shapes unchanged; only the internal env-read is routed.
- **run_id format** `{strftime("%Y%m%d%H%M%S")}_{slug}` (`cli/run.py:322-323`) and the GUI "adopt existing dir name as run_id" behavior (`run.py:280-283`).

## 11. Compatibility Constraints

- **ADAPT, public-API adjacency:** the resolver is strictly *behind* `PathManager`; the public symbol and its behavior for the flat layout are unchanged. This is the compatibility-adapter note required by the program for any subtask touching `ari.public.*`.
- **Dual-layout resolution is additive:** `checkpoint_file(name)` resolves bucket→flat; when no bucket exists (today's reality) it returns exactly the flat path `PathManager` returns now. New runs keep writing flat.
- **`from_checkpoint_dir()` walk-up preserved:** the "outermost `checkpoints/` ancestor, else direct parent" recovery (`paths.py:278-298`) must keep working so GUI-launched runs and test fixtures that skip the `checkpoints/` nesting still resolve.
- **No git-tracking cost:** `.gitignore` ignores `checkpoints/` (line 26), `experiments/` (31), `workspace/` (70), `ari-core/experiments/` (83), `ari-core/checkpoints/` (84); `git ls-files` returns zero tracked runtime-storage files. The change is purely on-disk resolution + code.
- **`default.yaml` reconciliation, if any, goes through the adapter:** relative `./checkpoints/{run_id}/` launches from a cwd must not break; the resolver resolves both the relative default and the `workspace/`-prefixed default.

## 12. Tests to Run

From the repo root `/home/t-kotama/workplace/ARI`:

```bash
python -m compileall .                 # byte-compile: catch syntax/import errors
pytest -q                              # full suite
pytest -q ari-core/tests/test_paths.py \
         ari-core/tests/test_resolve_node_work_dir.py \
         ari-core/tests/test_node_report.py \
         ari-core/tests/test_launch_config.py \
         ari-core/tests/test_settings_roundtrip.py \
         ari-core/tests/test_server.py   # focused PathManager consumers
ruff check .                           # lint (ruff IS available; radon is NOT installed)
```

No frontend `npm test` / `npm run build` is required for this subtask — it touches no `ari-core/ari/viz/frontend/` code. Acceptance is gated on all three commands above passing (and specifically the six focused test files staying green).

## 13. Acceptance Criteria

1. `RuntimePathResolver` exists and is the single reader/writer of `ARI_CHECKPOINT_DIR`; `grep -rn "os.environ.*ARI_CHECKPOINT_DIR" --include=*.py ari-core/ari` shows only the resolver (in `paths.py`/`runtime_paths.py`) and the two intentional `proc_env[...]=` subprocess hand-offs (or those too routed through a resolver helper).
2. `PathManager` public API is byte-compatible: `python -m compileall .`, `pytest -q`, and `ruff check .` all pass; the six focused test files in §12 pass unchanged plus new resolver tests.
3. `RuntimePathResolver.checkpoint_file(name)` resolves the flat path today and, given a bucketed `runs/<id>/checkpoints/name` on disk, prefers the bucket (proven by a `tmp_path` test).
4. Workspace-root resolution lives in one function implementing 004's policy; `auto_config()` no longer computes the checkpoint dir with inline `parents[3]` arithmetic (it calls the resolver).
5. No on-disk data was moved; new runs still produce the flat checkpoint layout (verified by an existing end-to-end/resume test staying green).
6. No public contract in §10 changed (spot-check: `python -c "from ari.public.paths import PathManager; PathManager.from_env()"` and a skill-style `from ari.public.paths import PathManager` still import).

## 14. Rollback Plan

Low-cost rollback because nothing on disk moves and the default write layout is unchanged:

1. Revert the commit(s) introducing `RuntimePathResolver` and the `PathManager` delegation, restoring the direct `PathManager` implementation.
2. Revert the incremental call-site routing (they are independent, small edits).
3. No data migration to undo; `.gitignore` guarantees no tracked runtime storage. Re-run §12 to confirm green.

Because `PathManager`'s public behavior is preserved throughout, a partial rollback (keep the resolver, revert only a call-site edit) is also safe.

## 15. Dependencies

Per the provided dependency graph edge `004 -> 006` and the cross-cutting inventory-gate constraint:

- **Direct predecessor — 004 `define_runtime_path_policy` (must precede).** Supplies the canonical workspace-root decision and the reconciliation of the `auto_config()` ↔ `default.yaml` disagreement that the resolver implements. Do not start 006 before 004's policy is fixed.
- **Sibling coordination — 005 `consolidate_checkpoint_workspace_experiment_paths` (also depends on 004; same wave — see 007 index "Wave 3: 005, 006 (need 004)").** 005 defines the target `runs/<run_id>/{workspace,checkpoints,artifacts,traces,reports}` layout that this resolver must be able to resolve; 006 is the mechanism 005's on-disk migration relies on. They should land in a coordinated pair, resolver (006) first or together, migration (005) never before the resolver can read both layouts.
- **Cross-cutting gate — the nine inventory subtasks must all complete first.** This subtask has **Runtime Code Change = Yes**, so per the master constraint and `007_subtask_index.md` footnote 1 it is gated by **001, 002, 020, 036, 045, 053, 059, 060, 067** (all read-only inventories). None of those changes runtime code; starting 006 before they complete is out of order.
- **Soft adjacency (not a graph edge) — 003 `consolidate_config_configs_sonfigs`.** `finder.py::package_config_root()` may later be repointed through the resolver; that repoint is deferred to 003/005 and is a Non-Goal here.

This subtask does **not** enable any downstream subtask via an outgoing edge in the provided graph (006 is a leaf of the `004 -> {005, 006}` fan-out).

## 16. Risk Level

- **Risk: Medium** (matches `007_subtask_index.md:53`).
- **Runtime Code Change: Yes.** This subtask, when executed, edits shipping code inside the `ari` package (`ari-core/ari/paths.py` and, incrementally, several core modules).
- Why not High: no on-disk migration, no default-layout flip, no public-symbol change; the resolver is additive behind an unchanged `PathManager`. Why not Low: it edits a heavily-consumed core module (38 `PathManager` consumers, incl. viz, pipeline, CLI, agent loop) and touches the `ARI_CHECKPOINT_DIR` hand-off that MCP skills and the GUI depend on — a regression here breaks run resolution program-wide. Mitigation: keep `PathManager`'s public behavior byte-identical, land call-site routing incrementally, and rely on the six focused tests plus the full suite as guards.

## 17. Notes for Implementer

- **Prefer extending `paths.py` over a new module** unless the file grows unwieldy; keeping `RuntimePathResolver` next to `PathManager` keeps the single-source-of-truth story intact and avoids a new import surface. If you do add `ari-core/ari/runtime_paths.py`, import it from `paths.py` so `ari.public.paths` needs no change.
- **Do not touch `META_FILES`, `META_EXTENSIONS`, or `_META_PATTERNS`.** They are a contract-adjacent classification (`paths.py:51-85`) consumed when copying files into node work dirs; the resolver may read them but must not redefine them.
- **`from_checkpoint_dir` is subtle:** it walks up to the *outermost* `checkpoints/` (guarding `cur.parent.name != "checkpoints"`) and falls back to the direct parent for test layouts that skip nesting (`paths.py:278-298`). Preserve this exactly — `test_resolve_node_work_dir.py` and GUI hand-off rely on it.
- **The two `proc_env["ARI_CHECKPOINT_DIR"] = ...` writers** (`viz/api_experiment.py:781`, `viz/api_orchestrator.py:284`) are *intentional* subprocess pins, not accidental bypasses; route them through `set_checkpoint_dir_env`-style helpers but keep the subprocess-env semantics.
- **`bfts.py:_resolve_pm_and_run_id` (lines 43-60)** is the reference pattern: it already does `PathManager.checkpoint_dir_from_env()` → `from_checkpoint_dir()` → `run_id = basename(ckpt)`. Generalize this into the resolver and have call-sites use it.
- **`auto_config()` reconciliation** is the highest-value single edit (removes the `parents[3]/"workspace"/"checkpoints"` inline arithmetic and the `default.yaml` disagreement's code half). Coordinate the exact chosen root with 004's policy doc before editing; if 004 says keep the relative `./checkpoints/{run_id}/` default, make the resolver resolve it and leave `default.yaml` alone.
- **Keep writes flat.** Any code path that *creates* a checkpoint/artifact must keep writing the flat layout in this subtask; only *reads* become dual-layout-aware. The write-side flip is 005's job.
- **`radon` is not installed**; do not add a complexity-gate dependency here. `ruff` is available and is the only linter to satisfy.
- **No `~/.ari`.** The v0.5.0 checkpoint-scoped design forbids reintroducing a global home dir; the sole legitimate legacy accessor stays `ari/migrations/v05_to_v07/memory.py:26`. The resolver must never read/write `~/.ari`.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **006** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
