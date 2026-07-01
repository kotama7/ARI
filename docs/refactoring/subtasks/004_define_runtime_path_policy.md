# Subtask 004: Define Runtime Path Policy

- **Phase:** Phase 2 — Repository Hygiene
- **Status:** PLANNING ONLY (this subtask produces a policy document; it does **not** modify runtime code)
- **Planning date:** 2026-07-01
- **Repo:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core` version 0.9.0)
- **Author role:** senior software architect
- **Hands off to:** subtask **005** (`consolidate_checkpoint_workspace_experiment_paths`) and subtask **006** (`introduce_runtime_path_resolver`). Both consume the policy fixed here.

> **Hard scope note.** This document defines *policy* — the canonical rules for where ARI runtime data lives and how paths are resolved. It proposes **nothing** that changes on-disk layout, imports, configs, workflows, or directory names *today*. Every "canonical target" named here is a destination for the later, adapter-gated migrations in 005/006 — not an instruction to `git mv` or edit any YAML now.

---

## 1. Goal

Produce a single, authoritative **Runtime Path Policy** that later subtasks (005, 006) can implement against without re-litigating design questions. The policy must:

1. Declare `PathManager` (`ari-core/ari/paths.py`) the **single source of truth (SSOT)** for deriving every runtime directory ARI touches, and forbid ad-hoc path arithmetic outside it.
2. Declare `ARI_CHECKPOINT_DIR` the **one canonical run pin**, and mandate that all reads go through `PathManager` env helpers rather than direct `os.environ` access.
3. **Reconcile the observed workspace-root disagreement** between `config/__init__.py` (defaults to `{repo}/workspace/checkpoints/{run_id}`) and `ari-core/config/default.yaml` (ships `./checkpoints/{run_id}/`), by naming one canonical default.
4. Define the **target run-directory layout** (`runs/<run_id>/{workspace,checkpoints,artifacts,traces,reports}`) as the destination policy that 005 will migrate toward behind a compatibility adapter.
5. Define the **`run_id` format**, **`paper_registry` location**, and **`~/.ari` prohibition** rules, and classify every current straggler with KEEP / ADAPT / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED.

The deliverable is this `.md` file. There is no code change in subtask 004.

## 2. Background

ARI already centralises path derivation in a `PathManager` class, but three unresolved tensions block the physical consolidation planned in 005:

- **A second env-read path exists.** `PathManager` exposes `checkpoint_dir_from_env()`, `set_checkpoint_dir_env()`, `from_env()`, and `from_checkpoint_dir()` (`ari-core/ari/paths.py:238-298`) so that no other module needs to spell `ARI_CHECKPOINT_DIR`. In practice ~15 modules still read the env var directly (see Section 6), so the SSOT is aspirational, not enforced.
- **Two different "default checkpoint dir" answers ship in the same repo.** `ari-core/ari/config/__init__.py` `auto_config()` derives `{repo_root}/workspace/checkpoints/{run_id}` (walks `Path(__file__).resolve().parents[3]`, lines ~583-592), while the packaged data file `ari-core/config/default.yaml:14` (`checkpoint.dir: ./checkpoints/{run_id}/`) and `:39` (`logging.dir: ./checkpoints/{run_id}/`) still point at a root-level `./checkpoints/`. On disk both exist: root `checkpoints/` is present but **empty**; `workspace/checkpoints/<ts_slug>/` is the populated one.
- **The checkpoint directory is a flat pile.** A real run's checkpoint dir holds ~45-46 sibling files — ARI metadata (enumerated in `META_FILES`, `paths.py:51-76`), figures (`fig_*.pdf/png/svg`), LaTeX artifacts (`full_paper.tex/pdf/bbl`, `refs.bib`), grading JSON (`ors_*.json`), plus `repro_sandbox/`, `paper/`, `uploads/` subdirs. There is **no** `artifacts/`, `traces/`, or `reports/` sub-structure today. This flat mixing is the concrete driver for the sub-bucketed target layout.

Subtask 004 does not fix any of these; it writes the rulebook so 005 (consolidation + migration) and 006 (`RuntimePathResolver` behind `PathManager`) implement one agreed policy.

> **`sonfigs/` note.** The master prompt's `sonfigs/` directory **does not exist** anywhere in the repo (`find -iname '*sonfig*'` returns nothing). The confusable trio is the *config* namespace (`ari/config/` code vs `ari/configs/` packaged defaults vs top-level `config/` rubric data), which is owned by **subtask 003**, not this one. It is out of scope here except where run-path resolution reads config (Section 4).

## 3. Scope

In scope for the **policy** (implemented later, not here):

- Rules for deriving runtime directories: `checkpoints/`, `experiments/`, `staging/`, `paper_registry/`, logs, uploads, per-node work dirs.
- The single env pin `ARI_CHECKPOINT_DIR` and the contract that all access is mediated by `PathManager`.
- The canonical workspace-root default that reconciles `config/__init__.py` vs `default.yaml`.
- The target run-dir layout (`runs/<run_id>/{workspace,checkpoints,artifacts,traces,reports}`) as a *destination*, plus the classification (META vs artifact/trace/report) that seeds the sub-buckets.
- The `run_id` naming rule (`{timestamp}_{slug}`).
- The `~/.ari` prohibition (with the single documented migration exception).

Out of scope (owned elsewhere): the config-directory triple (**003**); the physical move + migration shim (**005**); the resolver class + adapter (**006**); dashboard API path fields (**008**); prompt path externalisation (**011**).

## 4. Non-Goals

- **No runtime code changes.** No edit to `paths.py`, `checkpoint.py`, `config/__init__.py`, `default.yaml`, `workflow.yaml`, CLI, viz, or any skill.
- **No directory renames or `git mv`.** Root `checkpoints/` stays where it is until 005.
- **No migration code.** Writing/altering `ari-core/ari/migrations/` is 005's job.
- **No config-triple resolution.** `config/` vs `configs/` vs top-level `config/` is subtask 003.
- **No new env vars.** The policy consolidates onto the *existing* `ARI_CHECKPOINT_DIR` (and the existing overrides `ARI_PAPER_REGISTRY_DIR`, `ARI_LOG_DIR`); it does not invent new ones.
- **No change to the public re-export.** `ari.public.paths.PathManager` stays a verbatim re-export (contract).

## 5. Current Files / Directories to Inspect

Path-resolution SSOT and its consumers (verified line counts via Read; `wc -l` reports one fewer where a file lacks a trailing newline):

| Path | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/paths.py` | 304 | `PathManager` — SSOT for all runtime paths; `META_FILES` frozenset; env helpers |
| `ari-core/ari/public/paths.py` | 6 | **Public contract** — verbatim `from ari.paths import PathManager` re-export |
| `ari-core/ari/checkpoint.py` | 198 | Checkpoint JSON I/O: `save/load_tree_json`, `load_nodes_tree` 3-tier precedence, throttled `save_tree_incremental` |
| `ari-core/ari/config/finder.py` | 146 | Workflow/profile YAML discovery; `package_config_root()` → `ari-core/config/` |
| `ari-core/ari/config/__init__.py` | 628 | Pydantic config models + `auto_config()` (the `workspace/checkpoints/{run_id}` default, ~lines 583-592) |
| `ari-core/ari/env_detect.py` | 88 | Scheduler/runtime detection (no path derivation; inspect only to confirm it does not) |
| `ari-core/ari/container.py` | 481 | Container build/run — path mounts (inspect for any checkpoint-path assumptions) |
| `ari-core/ari/migrations/v05_to_v07/memory.py` | — | Sole legitimate `~/.ari/global_memory.jsonl` accessor (`LEGACY_GLOBAL_PATH`, line 26) |
| `ari-core/ari/migrations/v05_to_v07/{legacy_axes,node_reports}.py` | — | Other v0.5→v0.7 shims |

Shipped data files that encode path defaults (read-only in this subtask):

| Path | Relevant lines | Content |
| --- | --- | --- |
| `ari-core/config/default.yaml` | `:14` `checkpoint.dir: ./checkpoints/{run_id}/`; `:39` `logging.dir: ./checkpoints/{run_id}/` | Root-level default (disagrees with `auto_config`) |
| `ari-core/config/workflow.yaml` | 89 occurrences of `{{checkpoint_dir}}` | Templated output paths, all flat in the checkpoint root (e.g. `:100`, `:109`, `:113`, `:125`) |

Runtime storage directories on disk (all git-ignored — see `.gitignore:26,31,70,83,84`):

- `checkpoints/` — root-level, **empty**, appears legacy.
- `workspace/checkpoints/<ts_slug>/` — populated (e.g. `20260507051857_We_propose_an_implementation_of_CSR-form/`).
- `workspace/experiments/<ts_slug>/<node_id>/`, `workspace/staging/<ts>/`.

## 6. Current Problems

1. **SSOT is not enforced.** `ARI_CHECKPOINT_DIR` is read directly (bypassing `PathManager` helpers) in at least: `cli/__init__.py:52`, `cli/run.py:273`, `pipeline/stage_runner.py:362,410`, `orchestrator/bfts.py:44`, `viz/api_orchestrator.py:284`, `viz/api_experiment.py:781`, `agent/loop.py:231,483`, `config/__init__.py:383+`, plus `lineage.py`, `memory_cli.py`, `cost_tracker.py:214`, `memory/__init__.py`. Some of these are legitimate hand-off writes (spawning children); others are reads that should go through `checkpoint_dir_from_env()`. No policy currently distinguishes the two.

2. **Workspace-root disagreement.** `config/__init__.py` `auto_config()` → `{repo}/workspace/checkpoints/{run_id}`; `default.yaml:14/:39` → `./checkpoints/{run_id}/`. A user running from a raw checkout with the shipped YAML would write to root `checkpoints/`; the GUI/CLI `auto_config` path writes to `workspace/checkpoints/`. Two code paths, two answers, two on-disk trees (one empty, one populated).

3. **Flat checkpoint pile.** ~45-46 files at the checkpoint root with no `artifacts/`/`traces/`/`reports/` separation. `META_FILES` (`paths.py:51-76`) already distinguishes ARI metadata from copyable content, but only for the "don't copy into node work dirs" rule — there is no *output-bucket* classification. `workflow.yaml` hard-codes `{{checkpoint_dir}}/...` for 89 templated paths, so any sub-bucketing must be planned centrally.

4. **`~/.ari` stragglers.** v0.5.0 declared checkpoint-scoped storage (no `~/.ari`), but `Path.home() / ".ari"` still appears in `publish/backends/ari_registry.py:47`, `memory/auto_migrate.py:43`, `viz/api_publish.py:43`, `registry/__init__.py:40`, `clone/resolvers/ari.py:46`. Only `migrations/v05_to_v07/memory.py:26` is the *documented* legitimate accessor. There is no policy stating which are legacy-read-only vs. must-be-removed.

5. **Logs have no dedicated tree.** `log_dir()`/`log_file()` return the checkpoint dir + `ari.log` (`paths.py:153-158`). This is intentional today but interacts with the target layout (should logs land under `traces/` or stay at the checkpoint root?) — the policy must state the rule so 005 does not guess.

6. **`run_id` format is implicit.** Generated as `{strftime("%Y%m%d%H%M%S")}_{slug}` in `cli/run.py:322-323`; when launched from the GUI with `ARI_CHECKPOINT_DIR` set, the existing dir *name* is adopted as `run_id` (`run.py:273-283`). This coupling (dir name == run_id) is load-bearing for `from_checkpoint_dir()` and must be stated as policy, not left as folklore.

## 7. Proposed Design / Policy

The following seven rules constitute the Runtime Path Policy. Each rule carries a KEEP/ADAPT/... classification for the code it governs.

### P0 — `PathManager` is the SSOT (KEEP + ADAPT)
Every runtime directory is derived from `PathManager`. No module constructs `checkpoints/`, `experiments/`, `staging/`, `paper_registry/`, log, upload, or node-work paths via ad-hoc `Path(...) / "..."` arithmetic. `PathManager` (`paths.py`) is **KEEP** (extend, do not rewrite); the ~15 direct-arithmetic/env-read sites in Section 6 are **ADAPT** (route through `PathManager` in 005/006). The public re-export `ari.public.paths.PathManager` (`public/paths.py:3`) is a **contract — KEEP verbatim**.

### P1 — `ARI_CHECKPOINT_DIR` is the single run pin (KEEP + ADAPT)
`ARI_CHECKPOINT_DIR` remains the one env var that pins a process to a run. **Reads** go through `PathManager.checkpoint_dir_from_env()` / `from_env()`. **Writes for child hand-off** go through `PathManager.set_checkpoint_dir_env()`. Direct `os.environ["ARI_CHECKPOINT_DIR"] = ...` writes (`agent/loop.py:483`, `viz/api_orchestrator.py:284`, `viz/api_experiment.py:781`) are **ADAPT**: replace with the helper in 006. No new env var is introduced. Existing overrides `ARI_PAPER_REGISTRY_DIR` and `ARI_LOG_DIR` are retained as-is.

### P2 — Canonical workspace root = `{repo_root}/workspace/` (ADAPT `default.yaml`)
The reconciliation: **`workspace/` wins.** `auto_config()`'s `{repo}/workspace/checkpoints/{run_id}` is the canonical default because it is what the shipped GUI+CLI actually use and where data lives on disk. Therefore:
- `ari-core/config/default.yaml:14` and `:39` are classified **ADAPT** — a later subtask (005) updates them to `./workspace/checkpoints/{run_id}/` (or removes the redundant literal in favour of `auto_config`). Not changed in 004.
- Root-level `checkpoints/` (empty) is **MOVE_TO_LEGACY / DELETE_CANDIDATE** — remove in 005 once `default.yaml` no longer targets it. Because `.gitignore` ignores it (line 26) there is **no git-tracking cost**.

### P3 — Target run-directory layout (destination policy for 005)
The canonical destination is one directory per run with named sub-buckets, replacing today's sibling-tree sprawl + flat pile:

```
runs/<run_id>/
├── workspace/        # scratch / working tree (today: workspace/experiments/<run_id>/<node_id>)
├── checkpoints/      # ARI metadata only (META_FILES set)
├── artifacts/        # figures, LaTeX, refs.bib, produced outputs (today: flat in checkpoint root)
├── traces/           # cost_trace.jsonl, *.log, access logs (today: flat in checkpoint root)
└── reports/          # node_report.json, results.json, grading (ors_*.json)
```
This is **policy only**. 005 implements the move behind a compatibility adapter; 004 changes nothing. The bucket assignment is seeded by extending the existing `META_FILES` classification in `paths.py:51-76` into an output-bucket map (metadata → `checkpoints/`, figures/LaTeX → `artifacts/`, `*.log`/`cost_trace.jsonl`/`*_access.jsonl` → `traces/`, `*_report.json`/`results.json`/`ors_*.json` → `reports/`).

### P4 — `run_id` format is `{YYYYmmddHHMMSS}_{slug}` (KEEP)
The `run_id` = timestamp + slug rule (`cli/run.py:322-323`) is **KEEP** and now *stated as policy*. The invariant "checkpoint directory basename == `run_id`" (relied on by `PathManager.from_checkpoint_dir()`, `paths.py:278-298`, and by GUI adoption in `run.py:273-283`) is a **hard invariant**; 005/006 must preserve it.

### P5 — `paper_registry/` is cross-run (KEEP)
`paper_registry/` stays a workspace-root sibling shared across checkpoints (`paths.py:110-129`), overridable via `ARI_PAPER_REGISTRY_DIR`. Under P3 it remains **outside** any single `runs/<run_id>/` (it is inter-run state). **KEEP.**

### P6 — `~/.ari` is prohibited except the documented migration accessor (REVIEW_REQUIRED)
Only `migrations/v05_to_v07/memory.py:26` (`LEGACY_GLOBAL_PATH`) may reference `~/.ari`, and only for read/migrate. The other five sites (`publish/backends/ari_registry.py:47`, `memory/auto_migrate.py:43`, `viz/api_publish.py:43`, `registry/__init__.py:40`, `clone/resolvers/ari.py:46`) are **REVIEW_REQUIRED**: 004 records them; a later subtask decides KEEP-as-legacy-read vs. remove. None are touched in 004.

### P7 — Logs stay at the checkpoint root today, move to `traces/` under P3 (KEEP now, ADAPT later)
`log_dir()`/`log_file()` returning `{checkpoint}/ari.log` (`paths.py:153-158`) is **KEEP** for the current layout. Under the P3 target, logs are classified into `traces/`; this is **ADAPT** in 005, gated by the same adapter. `ARI_LOG_DIR` override is retained.

## 8. Concrete Work Items

All work items produce **only** this policy document — no code.

1. **Write P0–P7** into this file with the classification per governed component (done in Section 7).
2. **Enumerate the SSOT-bypass sites** (Section 6, item 1) as an explicit ADAPT list that 006 consumes — cite file:line for each.
3. **State the P2 reconciliation decision** (`workspace/` wins) with the exact `default.yaml` lines (`:14`, `:39`) and `auto_config()` location that 005 must edit.
4. **Define the P3 bucket map** by extending the `META_FILES` categories (`paths.py:51-76`) into metadata/artifact/trace/report groups; record it as a table for 005.
5. **Record the `run_id` invariant** (P4) and the `from_checkpoint_dir()` dependency (`paths.py:278-298`) that any migration must not break.
6. **List the `~/.ari` REVIEW_REQUIRED sites** (P6) with file:line for a downstream decision.
7. **Cross-check the dependency edges** `004 -> 005` and `004 -> 006` against `docs/refactoring/007_subtask_index.md` (rows 52-53) and confirm this policy supplies everything 005/006 need.

## 9. Files Expected to Change

**In this subtask (004):**

| Path | Change |
| --- | --- |
| `docs/refactoring/subtasks/004_define_runtime_path_policy.md` | **Created** — this policy document (the only file written) |

No other file — no `.py`, `.yaml`, `.ts`, workflow, or config — is created or modified in subtask 004.

**Files the policy will GOVERN in downstream subtasks (informational; NOT changed here):**

| Path | Governed by | Subtask that edits it |
| --- | --- | --- |
| `ari-core/ari/paths.py` | P0, P3, P4, P5, P7 (extend `PathManager` + bucket map) | 005 / 006 |
| `ari-core/ari/config/__init__.py` | P2 (canonical default) | 005 |
| `ari-core/config/default.yaml` (`:14`, `:39`) | P2 (retarget to `workspace/`) | 005 |
| `ari-core/config/workflow.yaml` (89 `{{checkpoint_dir}}`) | P3 (bucket templating) | 005 |
| ~15 direct-`ARI_CHECKPOINT_DIR` sites (Section 6.1) | P0, P1 (route through helpers) | 006 |
| Root `checkpoints/` (empty) | P2 (MOVE_TO_LEGACY / DELETE_CANDIDATE) | 005 |
| Five `~/.ari` sites (Section 6.4) | P6 (REVIEW_REQUIRED) | later (TBD) |

## 10. Files / APIs That Must Not Be Broken

The policy must be expressible **without** breaking any of these (compatibility-adapter notes required if a later phase touches them):

- **Public Python API:** `ari.public.paths.PathManager` — the verbatim re-export in `ari-core/ari/public/paths.py:3`. Any `PathManager` extension must keep the existing method surface (`checkpoint_dir`, `experiments_root`, `staging_root`, `paper_registry_root`, `log_dir/log_file`, `uploads_dir`, `node_work_dir`, `new_staging_dir`, `is_meta_file`, `slugify`, and the four env helpers) importable and behaviour-compatible.
- **CLI:** `ari = ari.cli:app`. Subcommands in `cli/{commands,run,bfts_loop,lineage,migrate,projects}.py` rely on `PathManager` and `ARI_CHECKPOINT_DIR` hand-off.
- **Checkpoint format:** `ari-core/ari/checkpoint.py` file names and JSON key order (`tree.json`, `nodes_tree.json`, `results.json`) and the 3-tier `load_nodes_tree` precedence (`checkpoint.py:86-137`).
- **Config file formats:** `ari-core/config/*.yaml` schema and the `{{checkpoint_dir}}` template contract in `workflow.yaml`.
- **MCP tool contracts:** the 14 `ari-skill-*` servers receive `ARI_CHECKPOINT_DIR` via env hand-off; the pin name and semantics must not change.
- **Dashboard API:** `ari/viz/routes.py` + `api_*.py` endpoints and `services/api.ts` — path fields returned to the React frontend must remain valid.
- **`ari-skill-memory`:** the `{ARI_CHECKPOINT_DIR}/memory_store.jsonl` location contract.

## 11. Compatibility Constraints

- **Env pin name is frozen.** `ARI_CHECKPOINT_DIR` is a cross-process (CLI ↔ MCP skills ↔ Letta ↔ viz) contract. The policy consolidates *access* onto `PathManager`, never renames the variable.
- **`run_id` == directory basename invariant** (P4) must hold so `from_checkpoint_dir()` and GUI dir-name adoption keep working.
- **Any P3 move is adapter-gated.** 005 must ship a backward-compatible resolver (subtask 006's `RuntimePathResolver`, sitting *behind* `PathManager` — ADAPT, public-API adjacency) so old flat-layout checkpoints still load. The policy forbids a hard cut-over.
- **No git-tracking migration cost.** All runtime storage is git-ignored (`.gitignore:26,31,70,83,84`), so consolidation is purely on-disk/back-compat; the policy notes this so 005 does not add spurious `git rm`/`git mv` steps.
- **`config`/`configs` namespace untouched.** The policy must not depend on resolving the config-directory triple (subtask 003); it only names *runtime storage* paths.

## 12. Tests to Run

This subtask writes documentation only, so these are **smoke checks confirming nothing regressed** (the repo is unchanged apart from the `.md` file):

- `python -m compileall .` — must pass (no `.py` touched).
- `pytest -q` — must pass (path-related tests such as those exercising `PathManager`/`checkpoint.py` remain green).
- `ruff check .` — must pass (`ruff` is available; `radon` is not — do not rely on it).
- Frontend `npm test` / `npm run build` — **not applicable** (no frontend files in scope).
- Doc-lint gates that already exist may run in CI: `scripts/docs/check_doc_links.py`, `scripts/docs/check_doc_sources.py`. Ensure the new doc's internal links resolve.

## 13. Acceptance Criteria

1. This file exists at the required absolute path and follows the standard 17-section template.
2. Every rule P0–P7 carries a KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED classification for the code it governs.
3. The workspace-root disagreement is explicitly reconciled with a named winner (`workspace/`) and the exact files/lines a later subtask must edit (`config/__init__.py` `auto_config`, `default.yaml:14`, `:39`).
4. The target `runs/<run_id>/{workspace,checkpoints,artifacts,traces,reports}` layout and its file-bucket map (seeded from `META_FILES`, `paths.py:51-76`) are specified as *destinations*, not applied.
5. The `~/.ari` prohibition names the single legitimate accessor (`migrations/v05_to_v07/memory.py:26`) and lists the five REVIEW_REQUIRED stragglers with file:line.
6. Section 15 dependencies match the dependency graph (`004 -> 005`, `004 -> 006`) and `docs/refactoring/007_subtask_index.md` rows 52-53.
7. `python -m compileall .`, `pytest -q`, and `ruff check .` still pass (repo functionally unchanged).
8. No runtime file (`.py`, `.yaml`, `.ts`, workflow) is modified.

## 14. Rollback Plan

Trivial: this subtask adds exactly one Markdown file. To roll back, `git rm docs/refactoring/subtasks/004_define_runtime_path_policy.md` (or revert the commit). No runtime state, config, or on-disk layout is affected, so rollback carries zero migration or data-loss risk.

## 15. Dependencies

Per the dependency graph and `docs/refactoring/007_subtask_index.md`:

- **Upstream (must precede 004):** none. 004 is a **root** node (no incoming edge; listed among roots in `007_subtask_index.md`). It is a planning/policy doc and does not itself change runtime code, so it is **not** blocked by the inventory subtasks (001, 002, 020, 036, 045, 053, 059, 060, 067) that must precede any *runtime code change*.
- **Downstream (depend on 004):**
  - **005** `consolidate_checkpoint_workspace_experiment_paths` — implements P2/P3/P7 (the physical move + `default.yaml` retarget + migration shim). *Runtime code change: Yes.*
  - **006** `introduce_runtime_path_resolver` — implements P0/P1 (`RuntimePathResolver` behind `PathManager`; routes the ~15 direct env-read sites through helpers). *Runtime code change: Yes.*
- **Adjacent (not a hard dependency):** subtask **003** (config-triple consolidation) shares the directory-namespace concern but is independent; the policy here deliberately stays out of the config triple.

Because 005 and 006 are the runtime-changing consumers, they additionally inherit the graph's rule that inventory subtasks (001, 002, 020, 036, 045, 053, 059, 060, 067) must precede any runtime code change — that gate applies to 005/006, not to 004.

## 16. Risk Level

- **Overall risk: LOW.**
- **Changes runtime code: NO.** This subtask produces a single policy `.md` and touches no `.py`, `.yaml`, `.ts`, config, workflow, prompt, or directory name. (`007_subtask_index.md` row 51 marks 004 "Runtime code change: No".)
- The *decisions* recorded here (especially P2's `workspace/` winner and P3's target layout) carry design risk that is realised only when 005/006 implement them; those subtasks own that risk and must land the compatibility adapter.

## 17. Notes for Implementer

- **Do not implement anything.** If you find yourself editing `paths.py`, `default.yaml`, or `config/__init__.py`, stop — that is 005/006.
- **Verify before citing.** Line numbers here were read on 2026-07-01 against `ari-core` 0.9.0. Re-Read `paths.py:51-76,153-158,238-298`, `config/__init__.py:~583-592`, `config/default.yaml:14,39`, and the `ARI_CHECKPOINT_DIR` grep before quoting them in a later PR — large files drift.
- **`workflow.yaml` is the hidden cost of P3.** There are 89 `{{checkpoint_dir}}/...` occurrences (verified via `grep -c`). Any sub-bucketing of the checkpoint root forces a coordinated template edit; flag this prominently to 005 so it is not discovered mid-migration.
- **The empty root `checkpoints/` is a tell.** Its emptiness while `workspace/checkpoints/` is populated is the evidence that P2's `workspace/` winner is already the de-facto behaviour; 005 is codifying reality, not changing it.
- **`from_checkpoint_dir()` walks to the outermost `checkpoints/` ancestor** (`paths.py:278-298`). Under the P3 `runs/<id>/checkpoints/` layout this heuristic changes meaning — call it out to 006 so the resolver handles both layouts during the transition.
- **Keep language English.** ARI canonical is English; ja/zh are mirrors. This doc, like the rest of `docs/refactoring/`, is English-only.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **004** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
