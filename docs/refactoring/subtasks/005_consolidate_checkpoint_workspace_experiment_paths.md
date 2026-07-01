# Subtask 005: Consolidate Checkpoint / Workspace / Experiment Paths

- **Phase:** Phase 2 — Repository Hygiene
- **Risk:** High
- **Depends on:** 004 (`define_runtime_path_policy`) — see [§15](#15-dependencies)
- **Changes runtime code:** **Yes** (when executed; this planning doc changes nothing)
- **Classification:** ADAPT (checkpoint/output on-disk layout is a contract; back-compat adapter mandatory)
- **Planning date:** 2026-07-01
- **Repo:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core` version `0.9.0`)

> **Planning-only guardrail.** This document changes no runtime code, imports, prompts, configs, workflows, frontend, or directory names. It specifies *what a later, adapter-gated implementation session must do*. Every "canonical destination" is a migration target, not an instruction to `git mv` anything now. The only file created by this planning step is this `.md`.

---

## 1. Goal

Collapse ARI's runtime-storage sprawl into a single per-run parent so that all of a
`run_id`'s data is co-located instead of scattered across three sibling trees plus a
duplicated root directory.

Concretely, move from today's layout:

```
<workspace_root>/
├── checkpoints/<run_id>/           # flat ~45-file pile: metadata + figures + LaTeX + grades + logs
├── experiments/<run_id>/<node_id>/ # per-node scratch (separate tree, cross-referenced by run_id)
└── staging/<ts>/                   # pre-launch upload staging
# ...and a second, empty, root-level ./checkpoints/ coexisting as legacy
```

to the canonical target policy defined by subtask 004:

```
<workspace_root>/
└── runs/
    └── <run_id>/                   # run_id = "{%Y%m%d%H%M%S}_{slug}"  (unchanged format)
        ├── workspace/              # per-node scratch   (was experiments/<run_id>/<node_id>/)
        ├── checkpoints/            # ARI metadata json  (was the flat checkpoint root)
        ├── artifacts/              # figures, LaTeX, refs.bib, paper/, repro_sandbox/, ear/
        ├── traces/                 # cost_trace.jsonl, viz/memory access logs, lineage jsonl
        └── reports/                # review_report.json, reproducibility_report.json, ors_*.json
```

The consolidation must be delivered **behind a backward-compatible adapter** so existing
runs (flat layout, gitignored on disk) keep resolving with zero migration, and so every
public contract in [§10](#10-files--apis-that-must-not-be-broken) is preserved.

## 2. Background

`PathManager` (`ari-core/ari/paths.py`, 304 lines) is already the single source of truth
for layout construction and is re-exported **verbatim** by `ari-core/ari/public/paths.py`
(6 lines) — i.e. it is part of the `ari.public.*` contract. It derives four roots from a
`workspace_root` (default `.`, cwd):

- `checkpoints_root` = `{root}/checkpoints` (`paths.py:97-99`)
- `experiments_root` = `{root}/experiments` (`paths.py:101-103`)
- `staging_root` = `{root}/staging` (`paths.py:105-107`)
- `paper_registry_root` = `{root}/paper_registry` (`paths.py:109-129`, overridable via `ARI_PAPER_REGISTRY_DIR`)

Per-run accessors: `checkpoint_dir(run_id)` = `checkpoints/{run_id}/` (`paths.py:149-151`);
`node_work_dir(run_id, node_id)` = `experiments/{run_id}/{node_id}/` (`paths.py:175-181`);
`new_staging_dir()` = `staging/{%Y%m%d%H%M%S}/` (`paths.py:185-190`). Logs are **not** a
separate tree — `log_dir()`/`log_file()` return the checkpoint dir + `ari.log`
(`paths.py:153-158`).

Two structural problems motivate this subtask (both confirmed on disk 2026-07-01):

1. **Three parallel trees keyed independently by `run_id`.** A single run's metadata
   (`checkpoints/<id>/`) and node scratch (`experiments/<id>/<node_id>/`) live in
   different roots, so every tool must cross-reference two directories by `run_id`.
2. **A flat ~45-file checkpoint pile.** The populated `workspace/checkpoints/<run_id>/`
   mixes ARI metadata, figures (`fig_*.pdf/png/svg`), LaTeX (`full_paper.tex/pdf/bbl`,
   `refs.bib`), grading JSON (`ors_*.json`), access logs (`viz_access.jsonl`,
   `memory_access.jsonl`), and sub-dirs (`paper/`, `uploads/`, `repro_sandbox/`) with **no**
   `artifacts/`, `traces/`, or `reports/` grouping. This is precisely why
   `PathManager.META_FILES` (`paths.py:51-76`) has to enumerate 19 metadata filenames plus
   a `.log` extension and a `memory_access.*.jsonl` regex (`paths.py:79-85`) — to *exclude*
   metadata from node work-dir copies.

Additionally there is a **workspace-root disagreement**: `auto_config()`
(`ari-core/ari/config/__init__.py:588-592`) defaults the checkpoint dir to
`{repo_root}/workspace/checkpoints/{run_id}`, while the shipped data file
`ari-core/config/default.yaml:14` and `:39` still say `./checkpoints/{run_id}/`
(root-level, no `workspace/` prefix). The empty root-level `./checkpoints/` exists on disk
precisely because of this split.

This subtask is the runtime-storage half of the master directory-consolidation plan
(`docs/refactoring/005_directory_consolidation_plan.md`, §5.2–§5.8). It relies on the
policy fixed by subtask 004 and is the natural consumer of the resolver introduced by
subtask 006 (`introduce_runtime_path_resolver`).

## 3. Scope

**In scope (runtime storage paths only):**

- The four `PathManager` roots and their per-run accessors: `checkpoints_root`,
  `experiments_root`, `staging_root`, `checkpoint_dir()`, `node_work_dir()`,
  `new_staging_dir()`, `log_dir()`, `log_file()`, `uploads_dir()`, `cost_trace()`,
  `cost_summary()`, `idea_file()` and the `ensure_*` helpers.
- The `{{checkpoint_dir}}` templating contract in `ari-core/config/workflow.yaml`
  (89 template references) and the `{run_id}` substitution in `default.yaml`.
- Reconciling the workspace-root disagreement (`auto_config()` vs `default.yaml`) in
  exactly one place.
- A backward-compatible dual-layout reader (new `runs/<id>/…` bucket first, flat legacy
  checkpoint/sibling second) so existing runs keep working.
- An opt-in one-shot re-bucketing pass extending `ari-core/ari/migrations/`.
- Doc/README path-text re-synchronisation via the existing doc-sync gates.

**Minimum viable deliverable vs. full deliverable:** the *minimum* is co-locating the
three sibling trees under one per-run parent (`runs/<run_id>/{workspace,checkpoints,staging-or-uploads}`)
and reconciling the root disagreement. The *full* deliverable additionally splits the flat
checkpoint pile into `artifacts/`, `traces/`, and `reports/` sub-buckets. If the fine-grained
split proves too large for one PR, it may be carved into a follow-up while keeping the
adapter and the primary co-location intact — but the target policy (§1) is the full layout.

## 4. Non-Goals

- **The config triple.** `ari-core/ari/config/` (code), `ari-core/ari/configs/`
  (packaged defaults + loader), and `ari-core/config/` (rubric/profile/workflow data) are
  the responsibility of **subtask 003** (`consolidate_config_configs_sonfigs`). This
  subtask does **not** rename or move any of them. Note explicitly: there is **NO
  `sonfigs/` directory anywhere** in the repo (`find -iname '*sonfig*'` returns nothing) —
  the master-prompt "sonfigs" is a hypothesised typo and does not exist.
- **Building the `RuntimePathResolver` itself.** That is subtask 006. This subtask
  *consumes* the resolver (or, if 006 has not landed, extends `PathManager`'s dual-layout
  support directly — see [§11](#11-compatibility-constraints)).
- **Changing the `report/` LaTeX/HTML build tree** at repo root. It is a documented build
  asset with its own PDF-sync contract (`scripts/docs/sync_report_pdf.sh`) and is one
  keystroke from the proposed `reports/` bucket — it must NOT be conflated or touched.
- **Changing the `paper_registry/` layout**, including its internal
  `paper_registry/papers/<id>/runs/<job_id>` path (`viz/api_paperbench_worker.py:189`),
  which reuses the name `runs/` for a different (PaperBench worker) concept. Keep it
  namespaced under `paper_registry_root`.
- **Changing checkpoint/output JSON *formats*.** Only *where* files live changes; the JSON
  schemas written by `ari/checkpoint.py` and the pipeline stay byte-compatible.
- **Removing the flat/legacy layout in this subtask.** Deletion of the old shape is gated
  behind ≥1 minor version of adapter default-on (see [§13](#13-acceptance-criteria)).
- **Renaming `run_id` or changing its format** (`{%Y%m%d%H%M%S}_{slug}`, `cli/run.py:322-323`).

## 5. Current Files / Directories to Inspect

Runtime code (all under `/home/t-kotama/workplace/ARI/`):

| Path | LOC / note | Why relevant |
|---|---|---|
| `ari-core/ari/paths.py` | 304 | `PathManager` — the layout source of truth; all four roots + per-run accessors + `META_FILES` + env helpers. |
| `ari-core/ari/public/paths.py` | 6 | Verbatim re-export of `PathManager` — **public API contract**. |
| `ari-core/ari/checkpoint.py` | 198 | Checkpoint JSON I/O (`save/load_tree_json`, `load_nodes_tree`, throttled `save_tree_incremental`); 3-tier `tree.json → nodes_tree.json → node_*/tree.json` precedence. |
| `ari-core/ari/config/__init__.py` | ~628 | `auto_config()` defaults ckpt dir to `workspace/checkpoints/{run_id}` (`:588-592`); literal `./checkpoints/{run_id}/` at `:163`, `:177`. |
| `ari-core/config/default.yaml` | 87 | `checkpoint.dir` (`:14`) and `logging.dir` (`:39`) = `./checkpoints/{run_id}/` — disagrees with `auto_config()`. |
| `ari-core/config/workflow.yaml` | 23.6 KB | 89 `{{checkpoint_dir}}` / `{run_id}` template references for stage output paths. |
| `ari-core/ari/cli/run.py` | 911 | `run_id` mint (`:322-323`); GUI adoption of `ARI_CHECKPOINT_DIR` name (`:280-285`); `checkpoint_dir` build (`:344`). |
| `ari-core/ari/cli/commands.py` | — | `ARI_CHECKPOINT_DIR` hand-off (`:128`). |
| `ari-core/ari/cli/bfts_loop.py` | 911 | env pin at `:378`. |
| `ari-core/ari/cli/migrate.py` | — | env pin at `:59`; entry point for a re-bucketing verb. |
| `ari-core/ari/cli/projects.py` | — | lists `<ckpt>/artifacts` at `:353-355`; checkpoint discovery. |
| `ari-core/ari/viz/api_experiment.py` | 929 | staging↔checkpoint promotion (`:161`, `:699`, `:725`); note `:243` comment on cwd-relative `./checkpoints/{run_id}/`. |
| `ari-core/ari/viz/api_tools.py` | — | `new_staging_dir()` call (`:161-163`). |
| `ari-core/ari/viz/state.py` | — | `_staging_dir` module state (`:31`). |
| `ari-core/ari/migrations/` | `v05_to_v07/{legacy_axes,memory,node_reports}.py` + `README.md` | where the opt-in re-bucketing pass must be added; `memory.py:26` is the sole legit `~/.ari` accessor — do not touch. |

Storage / config data & meta:

- On-disk (all **gitignored**): root `./checkpoints/` (empty, legacy),
  `workspace/checkpoints/<run_id>/`, `workspace/experiments/<run_id>/<node_id>/`,
  `workspace/staging/<ts>/` (7 timestamped dirs), stray `workspace/bundle.tar.gz`.
- `.gitignore` lines: `checkpoints/` (26), `experiments/` (31), `workspace/` (70),
  `ari-core/experiments/` (83), `ari-core/checkpoints/` (84).

Docs / contract text:

- `README.md:332` (`./checkpoints/<run_id>/`), `README.md:346`
  (`experiments/<slug>/<node_id>/` — note the `<slug>` vs code's `<run_id>` drift).
- `docs/reference/file_formats.md`, `docs/reference/cli_reference.md`,
  `docs/getting-started/quickstart.md` and the ja/zh mirrors reference the layout.

Tests to read before editing (reference counts, `ari-core/tests/`): **34** files mention
the `checkpoints` dir name / `checkpoints_root`; **17** mention `experiments`; **4**
mention `staging`; **6** mention `PathManager` / `from_checkpoint_dir` /
`checkpoint_dir_from_env`.

## 6. Current Problems

1. **Sibling-tree sprawl.** `checkpoints/`, `experiments/`, and `staging/` are three roots
   keyed independently by `run_id`; a run's data is not co-located (`paths.py:97-107`,
   `:175-181`, `:185-190`).
2. **Flat checkpoint pile.** ~45 mixed files at the checkpoint root force the 19-entry
   `META_FILES` frozenset + `.log` extension + `memory_access.*.jsonl` regex machinery
   (`paths.py:51-85`) to keep metadata out of node copies. There is no `artifacts/`,
   `traces/`, or `reports/` grouping.
3. **Duplicated `checkpoints/` root with a disagreeing default.** `auto_config()` pins
   `workspace/checkpoints/{run_id}` (`config/__init__.py:588-592`) while
   `default.yaml:14,:39` says `./checkpoints/{run_id}/`; the empty root-level
   `./checkpoints/` is the artifact of this split.
4. **`ARI_CHECKPOINT_DIR` fan-out.** The single run pin is read across **13 files / 26
   occurrences** under `ari-core/ari/` and handed to MCP subprocesses; any layout change
   must keep this env contract and `from_checkpoint_dir()`'s "walk up to the outermost
   `checkpoints/` ancestor" recovery (`paths.py:278-298`) working for both layouts.
5. **`workflow.yaml` templating coupling.** 89 `{{checkpoint_dir}}` references assume every
   stage output lands flat in the checkpoint root; sub-bucketing must not break these unless
   the resolver rewrites them consistently.
6. **Doc drift.** `README.md:346` documents `experiments/<slug>/<node_id>/` but code keys by
   `run_id` (`paths.py:175-181`) — a latent doc bug to fix as a doc-only follow-up.

## 7. Proposed Design / Policy

**Canonical target (from subtask 004 policy):** one directory per run under a new `runs/`
parent, with five sub-buckets replacing both the sibling sprawl and the flat pile
(layout in [§1](#1-goal)).

**Design principles:**

1. **Wrap, don't replace, `PathManager`.** `ari.public.paths.PathManager` is a public
   contract — its class name, module path, and existing method signatures stay. New
   behaviour is added additively (new accessors) or delegated to the resolver from subtask
   006. If 006 has not landed, extend `PathManager` in place with new bucket accessors and
   internal dual-layout resolution, keeping every existing method returning a valid path.
2. **Dual-layout resolution (bucketed-first, flat-fallback).** For any logical file, resolve
   `runs/<id>/<bucket>/<name>` first; if absent, fall back to the flat checkpoint root /
   legacy sibling tree. New runs write bucketed; old runs keep resolving flat with zero
   migration. `.gitignore` already ignores all runtime storage
   (`git ls-files` returns 0 tracked files), so there is **no git-tracking migration cost** —
   purely on-disk + resolver.
3. **`META_FILES` semantics preserved.** Classification (`paths.py:51-85`) must yield
   identical results regardless of which layout a file is found in. A filename that is "meta"
   flat must stay "meta" when found under `traces/` or `checkpoints/`.
4. **Single root reconciliation.** Fix the `auto_config()` vs `default.yaml` disagreement in
   exactly one place (the resolver / `PathManager` factory). `default.yaml` is reconciled
   *through the adapter* so cwd-relative `ari run` launches do not break. **REVIEW_REQUIRED:**
   pick `workspace/`-rooted (matches `auto_config()`) as canonical; keep `./checkpoints/…`
   resolvable for back-compat.
5. **Env + factory parity.** `ARI_CHECKPOINT_DIR`, `checkpoint_dir_from_env()`,
   `set_checkpoint_dir_env()`, `from_env()`, `from_checkpoint_dir()` keep identical
   signatures and semantics; `from_checkpoint_dir()` must recover `workspace_root` from
   *either* a flat `checkpoints/<id>/` path or a bucketed `runs/<id>/checkpoints/` path.
6. **Namespace safety.** The new top-level `runs/` must not collide with the registry's
   internal `paper_registry/papers/<id>/runs/<job_id>` — the latter stays addressed via
   `paper_registry_root`, never via the new `runs_root`.

**Bucket assignment (full deliverable):**

| Current flat location | Canonical bucket |
|---|---|
| `meta.json`, `launch_config.json`, `tree.json`, `nodes_tree.json`, `results.json`, `idea.json`, `workflow.yaml`, `ari.log`, `.ari_pid` | `runs/<id>/checkpoints/` |
| `experiments/<id>/<node_id>/` | `runs/<id>/workspace/<node_id>/` |
| `fig_*.{pdf,png,svg}`, `full_paper.{tex,pdf,bbl}`, `refs.bib`, `paper/`, `repro_sandbox/`, `ear/`, `uploads/` | `runs/<id>/artifacts/` |
| `cost_trace.jsonl`, `viz_access.jsonl`, `memory_access*.jsonl`, `lineage_decisions.jsonl` | `runs/<id>/traces/` |
| `review_report.json`, `reproducibility_report.json`, `ors_*.json`, `node_report.json` | `runs/<id>/reports/` |

## 8. Concrete Work Items

1. **Confirm subtask 004 policy is finalised** (the target layout, chosen canonical
   workspace-root, and `runs/` naming) before writing any code. If 006 exists, read its
   `RuntimePathResolver` surface; otherwise plan to extend `PathManager` directly.
2. **Extend `PathManager` (or the resolver) with bucket accessors:** `runs_root`,
   `run_dir(run_id)`, `artifacts_dir(run_id)`, `traces_dir(run_id)`, `reports_dir(run_id)`,
   plus dual-layout `checkpoint_file(run_id, name)` and re-pointed `node_work_dir`,
   `checkpoint_dir`, `new_staging_dir`. Keep all existing method names/signatures.
3. **Implement dual-layout resolution** (bucketed-first, flat-fallback) for every logical
   file read, including the `ARI_CHECKPOINT_DIR` and `from_checkpoint_dir()` recovery paths.
4. **Reconcile the workspace-root disagreement** in one place; adapt `default.yaml`
   (`:14`, `:39`) and `auto_config()` (`config/__init__.py:588-592`, `:163`, `:177`) so
   both spell the same canonical root, keeping the old relative form resolvable.
5. **Repoint writers** in the pipeline / viz / evaluator / cost-tracker to the new buckets
   for *new* runs (figures/LaTeX → `artifacts/`; cost/access/lineage jsonl → `traces/`;
   review/repro/ORS → `reports/`), gated so old runs still read flat.
6. **Handle `workflow.yaml` templating** (89 `{{checkpoint_dir}}` refs): either keep
   `{{checkpoint_dir}}` pointing at `runs/<id>/checkpoints/` and add new template vars
   (`{{artifacts_dir}}`, `{{traces_dir}}`, `{{reports_dir}}`) resolved centrally, or keep
   all stage outputs under `checkpoints/` and only relocate node scratch — **REVIEW_REQUIRED**;
   whichever is chosen must not change the set of files a resumed run expects.
7. **Add an opt-in one-shot re-bucketing pass** under `ari-core/ari/migrations/` (new module
   sibling to `v05_to_v07/`), invoked by a new `ari migrate` sub-path, that ports an existing
   flat run into the bucketed layout. Do not touch `migrations/v05_to_v07/memory.py`.
8. **Delete-candidate handling:** mark the empty root-level `./checkpoints/` DELETE_CANDIDATE
   only after confirming (grep) no cwd-relative writer targets it — do NOT delete in this
   subtask.
9. **Fix doc drift** (`README.md:346` `<slug>`→`<run_id>`) as a doc-only edit and update
   `README.md:332`, `docs/reference/file_formats.md`, `cli_reference.md`, and the ja/zh
   mirrors to the new layout; re-run the doc-sync gates.
10. **Add/adjust tests** for dual-layout reads, root reconciliation, and the migration pass
    (see [§12](#12-tests-to-run)).

## 9. Files Expected to Change

Runtime code:

- `ari-core/ari/paths.py` — bucket accessors + dual-layout resolution (additive; existing
  public methods unchanged).
- `ari-core/ari/checkpoint.py` — file reads routed through the resolver/dual-layout helper.
- `ari-core/ari/config/__init__.py` — reconcile `auto_config()` root (`:588-592`, `:163`,
  `:177`).
- `ari-core/config/default.yaml` — `checkpoint.dir` (`:14`), `logging.dir` (`:39`).
- `ari-core/config/workflow.yaml` — only if new bucket template vars are introduced (Work
  Item 6; REVIEW_REQUIRED).
- `ari-core/ari/cli/run.py`, `cli/commands.py`, `cli/bfts_loop.py`, `cli/migrate.py`,
  `cli/projects.py` — path construction / hand-off routed through the new accessors.
- `ari-core/ari/viz/api_experiment.py`, `viz/api_tools.py`, `viz/state.py` — staging /
  checkpoint path resolution.
- Pipeline / evaluator / cost-tracker writers that emit figures, LaTeX, jsonl traces, and
  report JSON (to be enumerated during implementation via
  `grep -rn 'checkpoint_dir\|node_work_dir' ari-core/ari/`).
- `ari-core/ari/migrations/` — **new** re-bucketing module (does not modify `v05_to_v07/`).

Docs (doc-only, after code lands):

- `README.md` (`:332`, `:346`), `README.ja.md`, `README.zh.md`,
  `docs/reference/file_formats.md`, `docs/reference/cli_reference.md`,
  `docs/getting-started/quickstart.md`, and their ja/zh mirrors.

Tests: new dual-layout / migration tests plus updates to the ~34 checkpoint-referencing and
~17 experiments-referencing files under `ari-core/tests/` that assert literal sibling paths.

**No change** to: `ari-core/ari/public/paths.py` (the re-export stays verbatim), the config
triple directories (subtask 003), `report/` (build asset), `paper_registry/` layout, or any
`.gitignore` runtime-storage rule.

## 10. Files / APIs That Must Not Be Broken

- **`ari.public.paths.PathManager`** — public Python API. Class name, module path, and every
  existing method signature (`checkpoints_root`, `experiments_root`, `staging_root`,
  `checkpoint_dir`, `node_work_dir`, `new_staging_dir`, `is_meta_file`, `slugify`,
  `checkpoint_dir_from_env`, `set_checkpoint_dir_env`, `from_env`, `from_checkpoint_dir`)
  stay callable and return valid paths.
- **CLI `ari` (`ari = ari.cli:app`)** — all subcommands, options, and the `ARI_CHECKPOINT_DIR`
  side-effect hand-off to MCP/Letta/delete subprocesses.
- **`ARI_CHECKPOINT_DIR` run pin** — read across 13 files / 26 sites under `ari-core/ari/`;
  its semantics and the `from_checkpoint_dir()` outermost-`checkpoints/` walk
  (`paths.py:278-298`) are a cross-process contract.
- **Checkpoint / output file formats** — `ari/checkpoint.py` JSON schemas and key order
  (`indent=2, ensure_ascii=False`), the `META_FILES` classification result, and the
  `tree.json → nodes_tree.json → node_*/tree.json` precedence (`checkpoint.py:86-137`).
- **`config/workflow.yaml` templating contract** — the set of files a resumed/consuming stage
  expects must be unchanged.
- **Dashboard API** — `ari/viz/routes.py` + `api_*.py` endpoints and JSON shapes consumed by
  `frontend/src/services/api.ts` (863 LOC); the dashboard reads checkpoint/EAR/trace/report
  files, so the adapter's dual-layout reads must keep those endpoints returning the same data.
- **MCP `ari-skill-*` contracts** — tool names/schemas unchanged; skills receive the pin via
  `ARI_CHECKPOINT_DIR`, so only env semantics matter here.
- **README / docs usage strings** and the scripts invoked by `.github/workflows/`
  (doc-sync, readme-sync gates).

## 11. Compatibility Constraints

- **Adapter is mandatory (ADAPT).** Ship dual-layout resolution before any writer repoints;
  a bucketed read must fall back to the flat legacy checkpoint / sibling tree so existing
  runs need no migration.
- **`META_FILES` invariance.** `is_meta_file()` (`paths.py:213-221`) must return identical
  results in both layouts; the 19 filenames + `.log` + `memory_access.*.jsonl` regex are the
  copy-exclusion contract for node work dirs.
- **Env/factory signatures frozen.** No change to `checkpoint_dir_from_env`,
  `set_checkpoint_dir_env`, `from_env`, `from_checkpoint_dir` signatures.
- **Public re-export untouched.** `ari-core/ari/public/paths.py` keeps `from ari.paths import
  PathManager`; do not add a divergent public symbol.
- **`report/` and `paper_registry/` isolation.** The new `runs/` and `reports/` names must
  never touch the top-level `report/` build tree or the registry's internal `runs/`.
- **Relationship to subtask 006.** Per the provided dependency graph the only hard predecessor
  is 004; there is **no encoded `006 -> 005` edge**. Technically, however, 006
  (`introduce_runtime_path_resolver`) is the intended vehicle for the dual-layout logic. If
  006 has already landed, implement 005 *on top of* the resolver; if not, implement the
  dual-layout resolution inside `PathManager` directly and keep it structured so 006 can later
  absorb it without a second migration. Either way the public surface is `PathManager`.
- **`.gitignore` unchanged.** All runtime storage is already ignored (`26,31,70,83,84`);
  introducing `runs/` may warrant an added ignore rule, but that is a hygiene follow-up
  (subtask 033 territory), not a break.

## 12. Tests to Run

- `python -m compileall .` — byte-compile the whole tree; catches syntax/indentation errors.
- `pytest -q` — full suite; pay special attention to the ~34 checkpoint-referencing and ~17
  experiments-referencing files under `ari-core/tests/`, plus resume/data-flow and
  delete-checkpoint tests (e.g. `test_delete_checkpoint_experiments.py`, `test_data_flow.py`,
  any `test_checkpoint_legacy_tree.py`).
- `ruff check .` — ruff is available (0.15.2); keep new code clean (baseline already has
  known F401/E402 findings — do not regress net-new).
- **New tests to add:** (a) dual-layout resolution (a file resolves under `runs/<id>/…`
  first, flat second); (b) `from_checkpoint_dir()` recovers `workspace_root` from both a flat
  `checkpoints/<id>/` path and a bucketed `runs/<id>/checkpoints/` path; (c) the opt-in
  migration pass ports a synthetic flat run into buckets and leaves JSON byte-identical;
  (d) `is_meta_file()` invariance across layouts.
- **Doc/CI gates** (after doc edits): `scripts/docs/check_doc_sources.py`,
  `scripts/docs/check_readme_parity.py`, `scripts/docs/check_ref_coupling.py`,
  `scripts/readme_sync.py` — plus the `docs-sync.yml` / `readme-sync.yml` workflows.
- No frontend build is required for this subtask (no `frontend/` source changes); the
  dashboard is exercised only via unchanged API endpoints.

## 13. Acceptance Criteria

1. `python -m compileall .`, `pytest -q`, and `ruff check .` all pass with no net-new
   failures.
2. `ari.public.paths.PathManager` retains its class name, module path, and all existing
   method signatures; `ari-core/ari/public/paths.py` is unchanged.
3. A **new** run writes into `runs/<run_id>/{workspace,checkpoints[,artifacts,traces,reports]}`
   (per chosen minimum/full scope), and an **existing** flat run still resumes, renders in the
   dashboard, and deletes correctly — verified by dual-layout tests.
4. `ARI_CHECKPOINT_DIR` hand-off, `from_checkpoint_dir()` recovery, and `META_FILES`
   classification behave identically in both layouts.
5. The `auto_config()` vs `default.yaml` workspace-root disagreement is resolved in exactly
   one place, with the legacy relative form still resolvable.
6. `config/workflow.yaml` produces the same set of resumable files a consuming stage expects.
7. Doc-sync and readme-sync gates are green after doc edits; `README.md:346` no longer says
   `<slug>`.
8. **No deletion** of the legacy layout or the root `./checkpoints/` in this subtask; both are
   only marked DELETE_CANDIDATE. Removal requires ≥1 minor version of adapter default-on, an
   `ari migrate` re-bucketing path, tests passing against both layouts, and green directory/doc
   gates (deferred to a later phase).

## 14. Rollback Plan

- All runtime storage is gitignored, so **there is nothing to un-track**; rollback is a pure
  code revert.
- Deliver the change as a single squashable branch. If regressions appear, `git revert` the
  branch: `PathManager` reverts to the flat sibling layout, `default.yaml`/`auto_config()`
  revert to their prior (disagreeing but functioning) values, and existing runs — which were
  always read via dual-layout fallback — keep resolving because the flat layout was never
  removed.
- The migration pass is **opt-in** (`ari migrate` only); it never runs automatically, so a
  revert cannot corrupt on-disk runs. Any run already re-bucketed stays resolvable by the
  reverted code only if the flat fallback is retained — therefore **do not delete the flat
  layout in the same PR** (enforced by [§13](#13-acceptance-criteria) item 8).
- Doc edits revert independently of code.

## 15. Dependencies

Per the provided dependency graph (`004 -> 005`), the single hard predecessor is:

- **004 `define_runtime_path_policy`** — fixes the target layout, the canonical workspace
  root, and the `runs/` naming this subtask implements. Must complete first.

Cross-cutting gate (not encoded as edges): every runtime-code-change subtask — this one
included — is gated by the **nine inventory subtasks** (001, 002, 020, 036, 045, 053, 059,
060, 067). None of those change runtime code; all must be complete before 005 begins.

Soft/technical coupling (not a graph edge, so **not** a blocking dependency): **006
`introduce_runtime_path_resolver`** is the intended implementation vehicle for the
dual-layout logic. The graph makes 006 a sibling of 005 (both depend on 004), not a
predecessor. Recommended ordering is 004 → 006 → 005, but if 006 slips, 005 implements the
dual-layout logic inside `PathManager` directly (see [§11](#11-compatibility-constraints)).
Downstream, subtask **010** (`extract_artifact_checkpoint_trace_store`) builds on the
bucketed layout this subtask introduces.

## 16. Risk Level

- **Risk: High.**
- **Does this subtask change runtime code? Yes.** When executed it edits `ari/paths.py`,
  `ari/checkpoint.py`, `ari/config/__init__.py`, several `cli/*` and `viz/*` modules,
  `default.yaml` (and possibly `workflow.yaml`), and adds a migrations module. (This
  *planning document* changes no code.)
- **Why High:** it touches the checkpoint/output on-disk layout (a contract), the
  `ARI_CHECKPOINT_DIR` cross-process pin, the `PathManager` public API surface, and the
  `workflow.yaml` templating contract. Mitigation is the mandatory dual-layout adapter, the
  opt-in migration, and keeping the flat layout in place until a later deletion phase.

## 17. Notes for Implementer

- **Read `docs/refactoring/005_directory_consolidation_plan.md` (§5.2–§5.8) first** — it is
  the per-directory design input (destination, migration, back-compat, deletion criteria) for
  every path this subtask touches, verified against the repo on 2026-07-01.
- **Do not conflate the two "005s":** the master plan doc `005_directory_consolidation_plan.md`
  covers *both* the config triple *and* runtime storage; this **subtask 005** is runtime
  storage only. The config triple is **subtask 003**.
- **`sonfigs/` does not exist** — do not search for it or create it.
- **Enumerate writers before repointing:** run
  `grep -rn 'checkpoint_dir\|node_work_dir\|cost_trace\|META_FILES' ari-core/ari/` to build
  the full writer list; the facts inventory names the biggest ones but is not exhaustive.
- **The 89 `{{checkpoint_dir}}` refs in `workflow.yaml`** are the trickiest coupling — decide
  the templating strategy (Work Item 6) before touching any writer, and keep the resumable
  file set invariant.
- **Keep `migrations/v05_to_v07/memory.py:26` untouched** — it is the only legitimate
  `~/.ari` accessor and unrelated to path bucketing.
- **`from_checkpoint_dir()`'s outermost-`checkpoints/` walk** (`paths.py:278-298`) is subtle:
  a bucketed path is `runs/<id>/checkpoints/`, whose parent is `<id>`, not `workspace_root`.
  The recovery logic must special-case the bucketed shape or it will infer the wrong root.
- **Verify the empty root `./checkpoints/` has no writer** (`grep` for cwd-relative
  `./checkpoints/{run_id}` — currently only `default.yaml:14,:39`, `config/__init__.py:163,177`,
  and comments in `cli/run.py:477` / `viz/api_experiment.py:243`) before proposing its
  deletion in a later phase.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **005** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
