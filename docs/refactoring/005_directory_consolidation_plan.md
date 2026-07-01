# 005 — Directory Consolidation Plan

- **Status:** PLANNING ONLY (no runtime changes in this subtask)
- **Planning date:** 2026-07-01
- **Repo:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core` version 0.9.0)
- **Author role:** senior software architect
- **Depends on / hands off to:** subtask **004** (`RuntimePathResolver`) and subtask **006** (backward-compatible path adapter). Neither exists yet — see [Related subtasks](#related-subtasks).

> **Hard scope note.** This document proposes *nothing that changes on-disk layout, imports, configs, workflows, or directory names today*. It inventories the real state of the storage/config directory namespace, names the canonical destination policy, and specifies the compatibility machinery that MUST land *before* any physical move. Every "Canonical destination" below is a target for a later, adapter-gated migration — not an instruction to `git mv` anything now.

---

## 1. Executive summary

ARI's on-disk namespace has two independent confusion axes:

1. **The config triple.** Three similarly-named directories with three unrelated jobs:
   `ari-core/ari/config/` (Python **code** — Pydantic models + YAML discovery),
   `ari-core/ari/configs/` (packaged **defaults data** + a loader),
   `ari-core/config/` (shipped **rubric / profile / workflow data**).
   The hypothesized `sonfigs/` **does not exist** anywhere in the repo (`find -iname '*sonfig*'` returns nothing) — it is a typo in the master prompt and is called out as such wherever relevant.

2. **The runtime storage sprawl.** A single `run_id`'s outputs are scattered across sibling trees
   (`workspace/checkpoints/<run_id>/`, `workspace/experiments/<run_id>/<node_id>/`, `workspace/staging/<ts>/`),
   *and* the checkpoint directory itself is a **flat pile of ~46 files** (metadata + figures + LaTeX + grading JSON + sandboxes) with **no** `artifacts/`, `traces/`, or `reports/` sub-structure. A second, empty, root-level `checkpoints/` coexists as legacy.

The recommended canonical policy is:

- **`configs/` = templates/presets** (one clearly-labelled home for shipped config data; the code package keeps a distinct name).
- **`runs/<run_id>/{workspace,checkpoints,artifacts,traces,reports}`** = one directory per run, with sub-buckets replacing today's flat pile and sibling-tree sprawl.

**Because the CLI, README, `default.yaml`, `workflow.yaml` templating, checkpoint format, and `ARI_CHECKPOINT_DIR` hand-off all assume the current layout, this plan explicitly recommends NOT changing the layout immediately.** The migration is only safe once a `RuntimePathResolver` (subtask 004) centralises *reads* and a backward-compatible adapter (subtask 006) makes both the old and new layouts resolvable. This document is the design input for those two subtasks.

---

## 2. Scope, non-goals, and contract guardrails

**In scope (this doc):** classify every directory name in the storage/config namespace; map each to a canonical destination; specify migration + back-compat + deletion criteria; enumerate the contracts that gate the work.

**Explicitly NOT in scope (this doc):** editing `paths.py`, `config/__init__.py`, `default.yaml`, `workflow.yaml`, `.gitignore`, any CLI command, any viz endpoint, any test, or performing any `git mv`.

**Contracts that MUST survive the eventual migration** (never break without a compatibility-adapter note):

| Contract | Anchor | Consumer |
|---|---|---|
| CLI `ari` console script | `ari = ari.cli:app` | end users, `README`, `scripts/`, workflows |
| Public Python API | `ari.public.*` (incl. `ari.public.paths` re-exporting `PathManager`) | downstream importers |
| MCP tool contracts | 14 `ari-skill-*/src/server.py` | `ari-core` via `ari/mcp/client.py` |
| Dashboard API | `ari/viz/routes.py` + `api_*.py` | React `frontend/src/services/api.ts` |
| Checkpoint format | `ari/checkpoint.py`, `PathManager.META_FILES` | resume, viz, migrations |
| Config file formats | YAML under `ari-core/config/` + `ari-core/ari/configs/` | loaders, profiles, rubrics |
| `ARI_CHECKPOINT_DIR` run-pin | `paths.py:238-274` | CLI ↔ MCP ↔ viz subprocess hand-off |
| README/docs usage strings | `README.md:332`, `:346`; `docs/reference/*` | users, doc-sync gates |

The word **"deprecated"** is reserved below for *external contracts only* (CLI/API/MCP/dashboard/documented paths). Internal code slated for removal is labelled with the classification vocabulary: **KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED**.

---

## 3. Ground-truth presence table

Verified by direct inspection on 2026-07-01. "Top-level" = repo root `/home/t-kotama/workplace/ARI`.

| Name (spec) | Present? | Where it actually is | Kind |
|---|---|---|---|
| `config/` (top-level) | **does not exist** | only `ari-core/ari/config/` and `ari-core/config/` | — |
| `configs/` (top-level) | **does not exist** | only `ari-core/ari/configs/` | — |
| `sonfigs/` | **does not exist anywhere** | `find -iname '*sonfig*'` → empty (prompt typo) | — |
| `checkpoint/` (singular) | **does not exist** | — | — |
| `checkpoints/` | **present (two)** | root `./checkpoints/` (empty, legacy) + `workspace/checkpoints/<run_id>/` (populated) | runtime |
| `workspace/` | **present** | `./workspace/` (root of runtime output) | runtime |
| `workspaces/` | **does not exist** | — | — |
| `experiment/` (singular) | **does not exist** | — | — |
| `experiments/` | **present** | `workspace/experiments/<run_id>/<node_id>/`; `ari-core/experiments/` is gitignored (not on disk) | runtime |
| `artifact/` (singular) | **does not exist** | — | — |
| `artifacts/` | **not a storage dir** | only a JSON field + optional per-checkpoint `<ckpt>/artifacts/` read by `cli/projects.py:353` | field/subdir |
| `trace/` (singular) | **does not exist** | — | — |
| `traces/` | **does not exist** | only the file `cost_trace.jsonl` + `trace_log` node field | file/field |
| `run/` (singular) | **does not exist** | — | — |
| `runs/` | **not a storage dir** | only `paper_registry/papers/<id>/runs/<job_id>` (`api_paperbench_worker.py:189`) | scoped subdir |
| `report/` (singular, top-level) | **present** | `./report/` — separate LaTeX/HTML build tree (`en/ja/zh`, `shared/`, `scripts/`, `html/`) | build asset |
| `reports/` | **not a runtime dir** | `paper_registry/reports/<job_id>` (`api_paperbench.py:714,735`) + `docs/refactoring/reports/` (planning) | scoped subdir |

**Reading of the table:** of the 16 names the spec asks about, only **`checkpoints/`, `workspace/`, `experiments/`, and `report/`** exist as real directories. The remaining 12 are either absent, or exist only as JSON fields / narrowly-scoped subdirectories. The canonical policy therefore *introduces* `artifacts/`, `traces/`, `reports/`, and `runs/` as new sub-buckets rather than renaming existing ones — which is why the risk is concentrated in the resolver/adapter, not in mass renames.

---

## 4. Recommended canonical policy (target state)

```
<workspace_root>/
├── configs/                         # templates / presets (shipped config DATA)
│   ├── default.yaml  workflow.yaml
│   ├── profiles/{cloud,hpc,laptop}.yaml
│   ├── paperbench_rubrics/*.yaml
│   └── reviewer_rubrics/*.yaml  (+ fewshot_examples/)
└── runs/
    └── <run_id>/                    # run_id = "{%Y%m%d%H%M%S}_{slug}"
        ├── workspace/               # per-node scratch  (today: experiments/<run_id>/<node_id>/)
        ├── checkpoints/             # ARI metadata      (today: checkpoints/<run_id>/*.json etc.)
        ├── artifacts/               # figures, LaTeX, EAR, repro sandboxes (today: flat in ckpt)
        ├── traces/                  # cost_trace.jsonl, viz/memory access logs, lineage jsonl
        └── reports/                 # review_report.json, reproducibility_report.json, ORS grades
```

- **`configs/` = the single "templates/presets" home.** It absorbs the *data* currently split between `ari-core/config/` (rubrics/profiles/workflow) and `ari-core/ari/configs/` (defaults). The **code** package `ari-core/ari/config/` (Pydantic models + `finder.py`) is renamed conceptually to remove the collision (see §5.1). This is a documented-import-path concern → adapter-gated.
- **`runs/<run_id>/…` = one directory per run.** The five sub-buckets replace both the sibling-tree sprawl (`checkpoints/` vs `experiments/` vs `staging/`) and the flat 46-file checkpoint pile.
- **No `~/.ari/`** anywhere (v0.5.0 checkpoint-scoped design is preserved; only `migrations/v05_to_v07/memory.py:26` may still read the legacy global path).

This policy is a *destination*, reached only after subtasks 004 + 006. The per-directory blocks in §5 spell out how each current directory maps into it.

---

## 5. Per-directory analysis

Each block follows the required schema: *Exists / Current contents / Current responsibility / Read by / Written by / Referenced in docs / Referenced in tests / Overlaps with / Problem / Canonical destination / Migration strategy / Backward compatibility strategy / Deletion criteria / Related subtasks.*

### 5.1 `config/` and `configs/` (the config triple)

There is **no top-level `config/` or `configs/`**. The concern is the three package-internal directories below. **`sonfigs/` does not exist** — stated here explicitly per spec.

#### 5.1.a `ari-core/ari/config/` — Python **code**

- **Exists:** Yes. `ari-core/ari/config/`.
- **Current contents:** `__init__.py` (25,413 bytes — Pydantic models `LLMConfig`/`BFTSConfig`/`ARIConfig`, env overrides, `auto_config()`), `finder.py` (146 lines — workflow/profile YAML discovery), `README.md`, `__pycache__/`.
- **Current responsibility:** Config *behaviour* — parse env vars, build the config object, and **locate** config files. `finder.py:package_config_root()` returns `ari-core/config/` (the sibling data dir, via `parent.parent.parent`, `finder.py:28-42`).
- **Read by:** `ari.config` is imported broadly (CLI, pipeline, viz). `auto_config()` at `config/__init__.py:583-596` is the canonical config builder. `finder.find_workflow_yaml` is the union discovery function (`finder.py:60-100`).
- **Written by:** No runtime writes (source package).
- **Referenced in docs:** `docs/reference/configuration.md`, `docs/reference/environment_variables.md`, and its own `README.md` name the Pydantic models as the authoritative field-level contract.
- **Referenced in tests:** `test_launch_config.py` and other config tests import from `ari.config`; `finder` behaviour is covered indirectly via workflow-loading tests.
- **Overlaps with:** name-collides with `ari-core/ari/configs/` (data) and `ari-core/config/` (data). `auto_config()` (`__init__.py:592`) disagrees with the shipped `default.yaml` on the workspace root (see §5.1.d Problem).
- **Problem:** The name `config` reads as "config files" but this is *code*. The three-way `config`/`configs`/`config` collision is the single biggest onboarding trap in the tree.
- **Canonical destination:** **ADAPT / KEEP** — remains a code package but should be renamed to disambiguate from the data dir (e.g. `ari.configmodel` / `ari.settings` — exact name is a subtask-004 decision, **REVIEW_REQUIRED**). This is a **documented-import-path** surface, so any rename is a public-contract change requiring a re-export shim.
- **Migration strategy:** Not now. When 004 lands, introduce `RuntimePathResolver` and (if renamed) keep `ari.config` as a thin re-export module. No data moves here.
- **Backward compatibility strategy:** Keep `from ari.config import auto_config, …` working via a compat re-export module for at least one minor version; `ari.public.*` must not change spelling.
- **Deletion criteria:** The old module name may be removed only after (a) one deprecation minor version has shipped, (b) `grep -rn 'from ari.config import\|import ari.config'` across `ari-core/`, all 14 `ari-skill-*`, and `docs/` returns only the compat shim, and (c) `check_public_api_contracts.py` (to be built, subtask ~006/scripts) passes.
- **Related subtasks:** 004 (resolver naming), 006 (import-compat shim), plus a future `check_import_boundaries.py` gate.

#### 5.1.b `ari-core/ari/configs/` — packaged **defaults data** + loader

- **Exists:** Yes. `ari-core/ari/configs/`.
- **Current contents:** `__init__.py` (310 B — export plumbing), `_loader.py` (58 lines — `ConfigLoader` Protocol + `FilesystemConfigLoader`, `.yaml→.yml→.json` search), `defaults.yaml` (393 B — only `models.lineage_decision_default: gpt-4o-mini`), `model_prices.yaml` (1,121 B — LLM price table), `README.md`, `__pycache__/`.
- **Current responsibility:** Out-of-band lookup tables the code used to hard-code (model prices, single default model), loaded via `FilesystemConfigLoader` whose base defaults to this dir (`_loader.py:16-18,37-38`).
- **Read by:** `ari.configs._loader.FilesystemConfigLoader`; `defaults.yaml` is read by `ari/orchestrator/lineage_decision.py:_default_model` (per the file's own comment); `model_prices.yaml` feeds `ari.cost_tracker`.
- **Written by:** No runtime writes.
- **Referenced in docs:** `docs/reference/configuration.md` (settings), and its `README.md` names `ari.protocols.ConfigLoader` as the loader contract.
- **Referenced in tests:** loader tests can pass a custom `base=` (designed for fixtures, `_loader.py:37`).
- **Overlaps with:** `ari-core/config/default.yaml` — **two different "defaults" files with unrelated content** (`configs/defaults.yaml` = one model key; `config/default.yaml` = BFTS + checkpoint settings). Name-collides with the code package `ari.config`.
- **Problem:** "defaults" is ambiguous across `configs/defaults.yaml` vs `config/default.yaml`; the plural/singular distinction is not self-documenting.
- **Canonical destination:** **MERGE** into the unified **`configs/`** templates/presets tree (§4). It is packaged data, so it belongs with the other shipped YAML.
- **Migration strategy:** Later. `FilesystemConfigLoader`'s base becomes the resolver-provided `configs/` root; keep the Protocol so call-sites don't change.
- **Backward compatibility strategy:** `ConfigLoader` Protocol is the abstraction seam — swap the base path behind it; `package_configs_root()` keeps returning a valid location during the transition.
- **Deletion criteria:** Old path removed only after the loader base is resolver-driven, `check_directory_policy.py` (to be built) asserts a single `defaults` source, and no test hard-codes `ari/configs/`.
- **Related subtasks:** 004 (resolver base), 006 (loader base swap).

#### 5.1.c `ari-core/config/` — shipped rubric / profile / workflow **data**

- **Exists:** Yes. `ari-core/config/` (sibling of `ari/`).
- **Current contents:** `default.yaml`, `workflow.yaml` (23.6 KB, ~89 `checkpoint_dir` template references), `profiles/{cloud,hpc,laptop}.yaml`, `paperbench_rubrics/{generic,nature,neurips,sc}.yaml`, `reviewer_rubrics/*.yaml` (23 venues: acl, aer, ahr, apsr, chi, cvpr, econometrica, generic_conference, iclr, icml, icra, journal_generic, nature, neurips, osdi, philreview, pmla, qje, sc, siggraph, stoc, usenix_security, workshop), `reviewer_rubrics/fewshot_examples/neurips/*.json` (3 examples), per-dir `README.md`.
- **Current responsibility:** The real, shipped config *data* — the workflow definition, environment profiles, and all peer-review/PaperBench rubrics.
- **Read by:** `finder.package_config_root()` (`finder.py:28-42`) resolves here; `find_workflow_yaml` fallback tiers 3–4 read `default.yaml`/`workflow.yaml`; `find_profile_yaml` reads `profiles/`; rubric loaders (evaluator/paperbench) read `reviewer_rubrics/` and `paperbench_rubrics/`.
- **Written by:** No runtime writes (checkpoints get *copies* of `workflow.yaml`, not writes here).
- **Referenced in docs:** `docs/reference/configuration.md`, `docs/reference/execution_profile.md`, `docs/reference/rubric_schema.md`, `docs/guides/experiment_file.md`.
- **Referenced in tests:** workflow-contract and rubric tests (`test_workflow_contract.py` 1,606 lines) load from here.
- **Overlaps with:** `finder.find_workflow_yaml` spreads a **four-tier** search across *two* directory trees (checkpoint → `{pkg}/profiles/{profile}.yaml` → `{pkg}/default.yaml` → `{pkg}/workflow.yaml`, `finder.py:60-100`). `default.yaml` here vs `configs/defaults.yaml` there.
- **Problem:** This is the largest, most important config surface but is buried under a name (`config/`) that collides with the code package one directory up.
- **Canonical destination:** **MERGE → `configs/`** (templates/presets, §4). This dir *is* the "templates/presets" the policy names; it should own that name outright.
- **Migration strategy:** Later, resolver-gated. `package_config_root()` becomes a resolver call; the four search tiers stay identical in order (the resolver just changes *where* each tier looks).
- **Backward compatibility strategy:** `finder.py` is already the single seam that centralises discovery — repoint it through the resolver without changing search order or file names (its own docstring commits to "without changing the search order or the on-disk file names").
- **Deletion criteria:** Old `ari-core/config/` path removed only after (a) resolver owns `package_config_root()`, (b) all 23 rubric + 3 profile + 2 top-level YAML are addressable via the new root, (c) `check_directory_policy.py` passes, (d) doc `sources:` front-matter re-verified by `check_doc_sources.py`.
- **Related subtasks:** 004 (resolver `package_config_root`), 006 (finder repoint), doc-sync re-verification.

#### 5.1.d Cross-cutting config problem (all three)

- **Workspace-root disagreement (confirmed):** `auto_config()` at `config/__init__.py:592` defaults the checkpoint dir to `{repo_root}/workspace/checkpoints/{run_id}`, but `ari-core/config/default.yaml:14` and `:39` still say `./checkpoints/{run_id}/` (root-level, no `workspace/`). The empty root `checkpoints/` exists precisely because of this split. **REVIEW_REQUIRED** — the canonical policy must pick one root (the resolver), and `default.yaml` must be reconciled *through the adapter* so existing relative-path assumptions do not break `ari run` from a cwd.

---

### 5.2 `checkpoint/` and `checkpoints/`

- **Exists:** `checkpoint/` (singular) **does not exist**. `checkpoints/` exists **twice**: root-level `./checkpoints/` (empty — legacy) and `workspace/checkpoints/<run_id>/` (populated, e.g. `20260507051857_We_propose_an_implementation_of_CSR-form`).
- **Current contents (populated one):** a **flat directory of ~46 files** at the checkpoint root, mixing: ARI metadata (`meta.json`, `launch_config.json`, `tree.json`, `nodes_tree.json`, `results.json`, `idea.json`, `workflow.yaml`, `ari.log`), figures (`fig_1.pdf/png`, `fig_2.*`, `fig_3.*`, `figures_manifest.json`), LaTeX (`full_paper.tex/pdf/bbl`, `refs.bib`), grading (`ors_*.json`, `review_report.json`, `review_merge_log.json`, `vlm_review.json`, `science_data.json`), access logs (`viz_access.jsonl`, `memory_access.jsonl`, `lineage_decisions.jsonl`), plus `paper/`, `uploads/`, `repro_sandbox/`, a stray `ari_run_1778131137.log`, and a stray `_rerun_react_only.py`. **No `artifacts/`, `traces/`, or `reports/` sub-dirs exist.**
- **Current responsibility:** The checkpoint dir is the run's metadata + artifact home and the resume/viz anchor. `PathManager.checkpoint_dir(run_id)` = `checkpoints/{run_id}/` (`paths.py:149-151`); logs live *inside* it (`paths.py:153-158`).
- **Read by:** everything — `ari/checkpoint.py` (JSON I/O), `ari/viz/*` (dashboard), `cli/{run,commands,projects,migrate}.py`, MCP skills via `ARI_CHECKPOINT_DIR`. `checkpoint_dir_from_env()`/`from_checkpoint_dir()` (`paths.py:238-298`) centralise the pin; hand-off confirmed at `cli/commands.py:128`, `cli/run.py:280-283/538`, `cli/bfts_loop.py:378`, `cli/migrate.py:59`. `ARI_CHECKPOINT_DIR` is read across 13 files under `ari-core/ari/`.
- **Written by:** `PathManager.ensure_checkpoint()`, `checkpoint.py:save_*` (throttled `save_tree_incremental()`, 1.0 s lock, `checkpoint.py:150-183`), viz/memory access-log writers, all pipeline stages.
- **Referenced in docs:** `README.md:332` ("`./checkpoints/<run_id>/`"), `docs/reference/file_formats.md` (whole page keyed on `{checkpoint}/…`), `docs/reference/cli_reference.md`, `docs/getting-started/quickstart.md`. 35 docs reference the `checkpoints/`/`experiments/` layout.
- **Referenced in tests:** **33** test files reference the `checkpoints` dir name / `checkpoints_root`; 6 reference `PathManager`/`from_checkpoint_dir`/`checkpoint_dir_from_env`.
- **Overlaps with:** root `./checkpoints/` vs `workspace/checkpoints/` (legacy coexistence); flat mixing means it currently *is* the (missing) `artifacts/`/`traces/`/`reports/` buckets all at once.
- **Problem:** (a) Two `checkpoints/` roots with a disagreeing default (§5.1.d). (b) ~46 flat files with no separation of metadata vs artifacts vs traces vs reports — the concrete driver for the `runs/<id>/{…}` split. (c) `META_FILES` (`paths.py:51-76`) has to enumerate 19 metadata filenames precisely *because* they are intermixed with node artifacts.
- **Canonical destination:** **ADAPT → `runs/<run_id>/checkpoints/`** for metadata, with figures/LaTeX/EAR/sandboxes moving to `runs/<run_id>/artifacts/`, cost/access/lineage logs to `runs/<run_id>/traces/`, and review/repro/ORS grades to `runs/<run_id>/reports/`. Root-level `./checkpoints/` is **DELETE_CANDIDATE** (empty legacy).
- **Migration strategy:** Not now. Requires `RuntimePathResolver` (004) so every read of `{checkpoint}/x.json` becomes `resolver.checkpoint_file("x.json")`, which can resolve *either* the flat legacy layout *or* the new bucketed layout. Only then can new runs write bucketed while old runs keep resolving flat.
- **Backward compatibility strategy:** The adapter (006) must (a) accept `ARI_CHECKPOINT_DIR` pointing at either layout, (b) keep `from_checkpoint_dir()`'s "walk up to outermost `checkpoints/`" recovery working, (c) resolve a filename by checking the bucket first then the flat root, (d) preserve `META_FILES` classification semantics. No git-tracking cost: `.gitignore` ignores `checkpoints/`, `workspace/`, `ari-core/checkpoints/` (lines 26, 70, 84) and `git ls-files` returns zero tracked files — the migration is purely on-disk + resolver.
- **Deletion criteria (flat layout):** removable only after (a) resolver+adapter shipped and default for ≥1 minor version, (b) a one-shot `ari migrate` path re-buckets existing checkpoints (extends `ari/migrations/`), (c) `test_checkpoint_legacy_tree.py` + resume tests pass against both layouts, (d) README/`file_formats.md` updated and doc-sync green. **Deletion criteria (root `./checkpoints/`):** removable once confirmed no code writes there — `grep` shows only `default.yaml` and `auto_config`/`api_experiment.py` mention the literal `./checkpoints/{run_id}/`, and the dir is empty; still **REVIEW_REQUIRED** to confirm no relative-cwd run lands there.
- **Related subtasks:** 004 (resolver), 006 (dual-layout adapter), a migrations extension, doc-sync + README-parity re-verification.

---

### 5.3 `workspace/` and `workspaces/`

- **Exists:** `workspace/` **exists** (repo root). `workspaces/` (plural) **does not exist**.
- **Current contents:** `workspace/checkpoints/<run_id>/`, `workspace/experiments/<run_id>/<node_id>/`, `workspace/staging/<ts>/` (7 timestamped staging dirs on disk), and a stray `workspace/bundle.tar.gz`.
- **Current responsibility:** The runtime output root — the `workspace_root` that `PathManager` derives `checkpoints_root`/`experiments_root`/`staging_root`/`paper_registry_root` from (`paths.py:97-129`). Default `workspace_root` is `.` (cwd, `paths.py:87`), but `auto_config()` pins it to `{repo_root}/workspace` (`config/__init__.py:592`).
- **Read by:** `PathManager` (all derived roots), viz (checkpoint discovery), CLI. `from_checkpoint_dir()` recovers this root by walking up from a checkpoint.
- **Written by:** every runtime stage, indirectly, via `PathManager` roots.
- **Referenced in docs:** `docs/getting-started/{index,quickstart,faq}.md`, `docs/ja|zh/reference/rest_api.md`, `docs/ja/reference/cli_reference.md`, README triples — 35 docs touch the `workspace/`-derived layout.
- **Referenced in tests:** tests construct `PathManager(tmp_path)` and assert on `checkpoints`/`experiments`/`staging` sub-roots (33/14/5 files respectively); the *name* `workspace` is mostly implicit via `workspace_root`.
- **Overlaps with:** conceptually equals the future `runs/` parent; `staging/` (a sibling) overlaps with per-run scratch.
- **Problem:** `workspace/` is a *flat container of parallel trees* keyed independently by `run_id` in each subtree — a run's data is split across three siblings rather than co-located. It is also the site of the root disagreement (§5.1.d).
- **Canonical destination:** **ADAPT → `runs/`** as the per-run parent, with `workspace/experiments/<run_id>/<node_id>/` becoming `runs/<run_id>/workspace/<node_id>/`. The singular `workspace/` name is retained *inside each run* as the node-scratch bucket.
- **Migration strategy:** Not now. Resolver introduces `runs_root` and `run_dir(run_id)`; sibling roots become sub-buckets under `run_dir`.
- **Backward compatibility strategy:** Adapter keeps `PathManager.experiments_root`/`checkpoints_root`/`staging_root` resolvable (they become thin views into `runs/<id>/…` or the legacy siblings). `workspace_root=.` default preserved so cwd-relative launches still work.
- **Deletion criteria:** the old sibling-tree shape removed only after resolver default-on ≥1 minor version, migration tool ports existing runs, and no test asserts the literal `workspace/experiments` sibling path.
- **Related subtasks:** 004, 006, migrations extension.

---

### 5.4 `experiment/` and `experiments/`

- **Exists:** `experiment/` (singular) **does not exist** as a directory (note: `experiment.md` is a *file* inside each checkpoint, and `ari-core/experiment.md` is gitignored). `experiments/` **exists** as `workspace/experiments/<run_id>/<node_id>/`; `ari-core/experiments/` is gitignored (line 83) and not on disk.
- **Current contents:** per-run bucket `workspace/experiments/<run_id>/` containing per-node work dirs `node_<id>/` (e.g. `node_44a3b688`, plus the root `node_..._root`).
- **Current responsibility:** Per-node working directories — where each BFTS node's code/data is materialised. `PathManager.node_work_dir(run_id, node_id)` = `experiments/{run_id}/{node_id}/` (`paths.py:175-181`), keyed by `run_id` (not slug) so same-topic runs never collide.
- **Read by:** pipeline/orchestrator (node execution), viz (node file explorer, `node_work_api.py`), `cli/projects.py` (artifact listing at `<ckpt>/artifacts`, distinct from node dirs).
- **Written by:** `ensure_node_work_dir()`, node execution, code-copy data path (respecting `META_FILES` exclusion).
- **Referenced in docs:** `README.md:346` ("`experiments/<slug>/<node_id>/`"), `docs/reference/file_formats.md:123` (`work_dir`), `docs/reference/architecture` / `bfts`.
- **Referenced in tests:** **14** test files reference the `experiments` dir name / `experiments_root` (e.g. `test_delete_checkpoint_experiments.py`, `test_data_flow.py`).
- **Overlaps with:** the checkpoint dir (node artifacts get copied/summarised back into the flat checkpoint); `README.md:346` still says `<slug>` while code keys by `<run_id>` (doc drift, **REVIEW_REQUIRED**).
- **Problem:** Node scratch lives in a *different tree* (`experiments/`) from run metadata (`checkpoints/`), so tooling must cross-reference two roots by `run_id`; the README/code slug-vs-run_id mismatch is a latent doc bug.
- **Canonical destination:** **ADAPT → `runs/<run_id>/workspace/<node_id>/`** (co-located with the run's checkpoint/artifacts/traces/reports buckets).
- **Migration strategy:** Not now. `node_work_dir` becomes `resolver.node_work_dir(run_id, node_id)` returning the `runs/<id>/workspace/<node_id>` path; keep `run_id` keying.
- **Backward compatibility strategy:** Adapter resolves node dirs under *either* `experiments/<run_id>/` or `runs/<run_id>/workspace/`; `META_FILES` copy-exclusion semantics unchanged. Fix README `<slug>`→`<run_id>` as a doc-only follow-up (not a layout change).
- **Deletion criteria:** old `experiments/` sibling removed only after resolver default-on, migration tool ports node dirs, and `test_delete_checkpoint_experiments.py` passes against the co-located layout.
- **Related subtasks:** 004, 006, README doc-fix, migrations extension.

---

### 5.5 `artifact/` and `artifacts/`

- **Exists:** `artifact/` (singular) **does not exist**. `artifacts/` **does not exist as a first-class storage dir**. It appears only as: (a) a JSON field `artifacts: [...]` on node/result records (`orchestrator/node.py:154`, `bfts_loop.py:905`, `node_report/builder.py`, `results.json`, `file_formats.md:124`); and (b) an **optional per-checkpoint subdir** `<ckpt>/artifacts/` that `cli/projects.py:353-355` lists if present.
- **Current contents:** in practice the "artifact" *files* (figures, `full_paper.*`, `refs.bib`, `repro_sandbox/`, `paper/`, EAR via `ear/`) sit **flat at the checkpoint root**, not under an `artifacts/` dir. The `ear/` subdir (`viz/ear.py:56`, README.md:344 "Experiment Artifact Repository") is the nearest existing artifact bucket, but it was absent in the sampled run.
- **Current responsibility:** No dedicated dir today; artifacts are tracked as *provenance records* (path + sha256) inside `results.json`/`node_report.json` rather than physically grouped.
- **Read by:** `cli/projects.py` (`<ckpt>/artifacts` listing), viz Results view (`resultSections.tsx`, `PaperWorkspace.tsx`), claim/evidence gate (`claim_gate/gate.py:162` reads `sb["artifacts"]`).
- **Written by:** node execution emits artifact *records*; figures/LaTeX written flat to the checkpoint; `<ckpt>/artifacts/` is written ad-hoc where `cli/projects.py` expects it.
- **Referenced in docs:** `docs/reference/file_formats.md` (`artifacts` field, `artifact_refs`), `README.md:337,344`.
- **Referenced in tests:** `test_cli.py`, `test_ear.py`, claim-gate tests assert on the `artifacts` *field* (not a dir).
- **Overlaps with:** the flat checkpoint dir (§5.2) — the missing `artifacts/` bucket is currently the checkpoint root itself; `ear/` partially fills this role.
- **Problem:** No physical grouping of artifact files means the checkpoint root is a 46-file pile and `META_FILES` must exhaustively list metadata to *exclude* it from node copies.
- **Canonical destination:** **ADAPT (introduce) → `runs/<run_id>/artifacts/`** — a *new* bucket that gathers figures, LaTeX, `refs.bib`, `paper/`, `repro_sandbox/`, and the EAR (`ear/`). The `artifacts` JSON *field* is a KEEP (contract).
- **Migration strategy:** Not now. Resolver adds `artifacts_dir(run_id)`; writers of figures/LaTeX repoint there; `artifacts`-field paths become relative to the new bucket.
- **Backward compatibility strategy:** Adapter resolves an artifact path by checking `runs/<id>/artifacts/` then the flat checkpoint root; the `artifacts` field schema and sha256 records are unchanged (contract). `<ckpt>/artifacts/` continues to be listed for legacy runs.
- **Deletion criteria:** flat-root artifact scattering removed only after resolver default-on, migration re-buckets figures/LaTeX/EAR, and Results-view + claim-gate tests pass against bucketed paths.
- **Related subtasks:** 004 (`artifacts_dir`), 006 (dual-root artifact resolution), migrations extension.

---

### 5.6 `trace/` and `traces/`

- **Exists:** `trace/` (singular) **does not exist**. `traces/` **does not exist**. "trace" exists only as: the file `cost_trace.jsonl` (`paths.py:164-165`), the node field `trace_log` (list of `{role, content}` records, `file_formats.md:122`), and jsonl access/lineage logs at the checkpoint root (`viz_access.jsonl`, `memory_access.jsonl`, `lineage_decisions.jsonl`, `memory_access.*.jsonl`).
- **Current contents:** n/a (no dir). The trace-like files are flat in the checkpoint and are enumerated in `META_FILES` (`paths.py:60,70-72,84`).
- **Current responsibility:** Per-call cost tracking, LLM/tool message transcripts, and viz/memory access diagnostics — all currently loose files.
- **Read by:** cost accounting (`cost_tracker`), viz (EAR/trace tabs — `DetailPanelTabs/Trace`, `useEAR`), lineage tooling.
- **Written by:** `cost_tracker`, `viz` access-log writers, `memory` backend, lineage decision logging.
- **Referenced in docs:** `file_formats.md` (`cost_trace.jsonl`, `trace_log`), `README.md:345`.
- **Referenced in tests:** `test_event_loop_and_csv.py`, cost-tracking tests reference `cost_trace.jsonl`.
- **Overlaps with:** the flat checkpoint dir; `traces` and `reports` are the two buckets that today have *zero* physical existence.
- **Problem:** Diagnostics are interleaved with experiment artifacts, forcing the `META_FILES`/`_META_PATTERNS` regex machinery (`paths.py:83-85`) to keep them out of node copies.
- **Canonical destination:** **ADAPT (introduce) → `runs/<run_id>/traces/`** — gathers `cost_trace.jsonl`, `viz_access.jsonl`, `memory_access*.jsonl`, `lineage_decisions.jsonl`.
- **Migration strategy:** Not now. Resolver adds `traces_dir(run_id)`; `cost_trace()`/access-log writers repoint there.
- **Backward compatibility strategy:** Adapter resolves each trace filename under `runs/<id>/traces/` then the flat checkpoint root; `META_FILES` classification is preserved (a filename found in either location is still "meta"). File *formats* (jsonl schemas) unchanged.
- **Deletion criteria:** flat trace files removed only after resolver default-on, migration moves them, and viz EAR/trace tabs + cost tests pass against the bucket.
- **Related subtasks:** 004 (`traces_dir`), 006 (dual-root trace resolution).

---

### 5.7 `run/` and `runs/`

- **Exists:** `run/` (singular) **does not exist**. `runs/` **does not exist as a general storage root**. `runs/` appears only *inside the paper registry*: `paper_registry/papers/<paper_id>/runs/<job_id>` (`viz/api_paperbench_worker.py:189`; test fixture `test_api_paperbench_worker.py:71`). (There is also an unrelated CLI verb `ari run` and a code module `cli/run.py` — not a directory.)
- **Current contents:** n/a at the storage-root level; the registry `runs/<job_id>/` holds PaperBench worker outputs (`rubric.json`, etc.).
- **Current responsibility:** none as a top-level concept today — this is the *name the canonical policy introduces* for the per-run parent.
- **Read by:** `api_paperbench_worker.py` (registry job runs); nothing else uses `runs/` as a root.
- **Written by:** the PaperBench worker (registry-scoped).
- **Referenced in docs:** `docs/concepts/verifiable_research_memory.md` mentions run-scoped storage; no doc documents a top-level `runs/` root yet.
- **Referenced in tests:** `test_api_paperbench_worker.py:71` (registry-scoped `runs/`).
- **Overlaps with:** `workspace/` (the current de-facto per-run parent) and the registry's own `runs/`.
- **Problem:** The name `runs/` is *already in use* inside `paper_registry/` for a *different* concept (PaperBench worker jobs). Introducing a top-level `runs/` risks a second collision unless the registry usage is kept clearly namespaced. **REVIEW_REQUIRED.**
- **Canonical destination:** **ADAPT (introduce) → top-level `runs/<run_id>/`** as the per-run parent (§4). The registry `runs/<job_id>/` stays where it is (under `paper_registry/papers/<id>/`), namespaced by the registry root, so the two do not clash.
- **Migration strategy:** Not now. Resolver introduces `runs_root`/`run_dir(run_id)`; the registry path is left untouched but documented as a distinct namespace.
- **Backward compatibility strategy:** Adapter treats `runs/` as an *additional* resolvable root layered over `workspace/{checkpoints,experiments,staging}`; the registry `runs/` is addressed via `paper_registry_root` (`paths.py:110-129`), never via `runs_root`.
- **Deletion criteria:** n/a (nothing to delete — this is an introduced name). The *legacy* `workspace/` sibling shape it supersedes has its own criteria in §5.3.
- **Related subtasks:** 004 (`runs_root`/`run_dir` + registry namespacing decision), 006.

---

### 5.8 `report/` and `reports/`

- **Exists:** `report/` (singular, top-level) **exists** — but it is **NOT runtime storage**. `reports/` (as a runtime dir) **does not exist**; `reports/` appears only as `paper_registry/reports/<job_id>` (`api_paperbench.py:714,735`) and `docs/refactoring/reports/` (this planning workspace, currently empty).
- **Current contents (`report/`):** a separate LaTeX/HTML build tree — `en/`, `ja/`, `zh/` (each `chapters/` + `main.tex`/`main.pdf` and many latexmk build files), `shared/`, `html/{en,ja,zh}/`, `audit/`, `scripts/`, `CLAUDE.md`, `.gitignore`, `.latexmkrc`. The triple PDF is kept in sync with `docs/public/report/*.pdf` and `docs/assets/report/*.pdf` by `scripts/docs/sync_report_pdf.sh`.
- **Current responsibility (`report/`):** the human-facing research report document build — entirely unrelated to per-run outputs. The *runtime* "report" concept is instead the loose files `review_report.json`, `reproducibility_report.json`, `review_merge_log.json`, `ors_*.json` at the checkpoint root, and `node_report.json`.
- **Read by:** `report/` — `scripts/docs/sync_report_pdf.sh`, `.github/workflows/pages.yml` / `docs-*`; runtime report *files* — viz Results view, `cli/projects.py`, evaluator.
- **Written by:** `report/` — latexmk / report `scripts/`; runtime report files — evaluator/reviewer stages, reproducibility driver.
- **Referenced in docs:** `report/` is documented in root README (shared/assets listing, readme-sync gate) and its own `CLAUDE.md`; runtime report files in `file_formats.md`, `README.md:341-342`.
- **Referenced in tests:** runtime report *files* appear in evaluator/reproducibility tests; `report/` build tree is exercised by doc-sync scripts, not `pytest`.
- **Overlaps with:** **name overlap only** — the singular `report/` (build asset) must not be conflated with the proposed per-run `reports/` bucket. The runtime report files currently live flat in the checkpoint.
- **Problem:** (a) The singular `report/` name is one keystroke from the proposed `reports/` bucket — high confusion risk. (b) Runtime report JSON is scattered flat in the checkpoint with no `reports/` grouping.
- **Canonical destination:** `report/` (LaTeX build) → **KEEP as-is** (out of scope for storage consolidation; it is a documented build asset with its own PDF-sync contract). The runtime report *files* → **ADAPT (introduce) → `runs/<run_id>/reports/`**.
- **Migration strategy:** Not now, and **not for `report/` at all**. For runtime files: resolver adds `reports_dir(run_id)`; evaluator/reproducibility writers repoint there.
- **Backward compatibility strategy:** Adapter resolves `review_report.json`/`reproducibility_report.json`/`ors_*.json` under `runs/<id>/reports/` then the flat checkpoint root; JSON schemas unchanged (contract). `report/` build tree and its PDF-sync (`sync_report_pdf.sh --check`) are left completely untouched — explicitly excluded from this consolidation to avoid the name collision breaking the pages build.
- **Deletion criteria:** flat runtime report files removed only after resolver default-on, migration re-buckets them, and evaluator/repro/Results-view tests pass. The `report/` dir is **never** a deletion candidate here.
- **Related subtasks:** 004 (`reports_dir`), 006 (dual-root report resolution). `report/` (build) is governed by the docs subtasks, not this one.

---

## 6. `RuntimePathResolver` (subtask 004) — design input

`RuntimePathResolver` **does not exist** yet. This section is the spec input for subtask 004, not an implementation.

Today, `PathManager` (`paths.py`, 304 lines; re-exported verbatim by `ari/public/paths.py`, 6 lines) is already the single source of truth for *layout construction*. The gap is that it hard-codes the current shape (`{root}/checkpoints/{run_id}`, `{root}/experiments/{run_id}/{node_id}`) and callers embed literal filenames (`{checkpoint}/tree.json`). A resolver must:

1. **Wrap, not replace, `PathManager`.** `ari.public.paths.PathManager` is a public contract — keep it. `RuntimePathResolver` composes it and adds *dual-layout file resolution* (bucketed-first, flat-fallback).
2. **Own the four config search tiers** currently in `finder.find_workflow_yaml` and `finder.package_config_root()` (`finder.py:28-100`) without changing order or filenames.
3. **Own `ARI_CHECKPOINT_DIR` semantics** — remain the only env pin, keep `from_checkpoint_dir()`'s outermost-`checkpoints/` walk (`paths.py:278-298`) working for both layouts.
4. **Expose bucket accessors** (`run_dir`, `checkpoint_file`, `artifacts_dir`, `traces_dir`, `reports_dir`, `node_work_dir`) that map a logical name to *either* the new `runs/<id>/…` bucket or the legacy flat/sibling location.
5. **Reconcile the workspace-root disagreement** (§5.1.d) in exactly one place.

No behaviour changes until callers are migrated to the resolver *and* the adapter (006) is default-on.

## 7. Backward-compatible adapter (subtask 006) — design input

The adapter **does not exist** yet. Requirements distilled from the blocks above:

- **Dual-layout reads:** any logical file resolves in the new bucket first, then the flat legacy checkpoint / sibling tree. Old runs keep working with zero migration.
- **`META_FILES` preservation:** classification (`paths.py:51-85`, 19 filenames + `.log` + `memory_access.*.jsonl` regex) must yield identical results regardless of which layout a file is found in.
- **Env + factory parity:** `ARI_CHECKPOINT_DIR`, `checkpoint_dir_from_env()`, `set_checkpoint_dir_env()`, `from_env()`, `from_checkpoint_dir()` unchanged in signature and semantics.
- **Config-loader seam reuse:** repoint `FilesystemConfigLoader` base and `finder.package_config_root()` through the resolver without touching the `ConfigLoader` Protocol or search order.
- **One-shot migration path:** extend `ari/migrations/` (currently `v05_to_v07/{legacy_axes,memory,node_reports}.py`) with an opt-in re-bucketing pass invoked by `ari migrate`. Zero git-tracking cost — all runtime storage is gitignored (`.gitignore:26,31,70,83,84`; `git ls-files` returns nothing under these).
- **Doc/README re-verification:** after any user-visible path text changes, re-run `check_doc_sources.py`, `check_readme_parity.py`, `check_ref_coupling.py` (doc-sync + readme-sync gates).

## 8. New quality gates this consolidation needs (do NOT implement here)

These scripts **do not exist** yet (per the facts inventory) and should be designed as their own subtasks:

- `check_directory_policy.py` — assert the config triple has one data home and one code home; assert no new top-level `config`/`configs` collision; assert the `runs/<id>/{…}` bucket policy for new runs.
- `check_public_api_contracts.py` — guard `ari.public.*` (incl. `paths`) spelling if `ari.config` is renamed.
- `check_import_boundaries.py` — catch `from ari.config import …` reaching into internals during the rename window.
- (`check_docs_source_sync.py` would **partially overlap** the existing `scripts/docs/check_doc_sources.py` — reuse, don't duplicate.)

## 9. Contract-impact matrix

| Contract | Touched by this plan? | Gating requirement |
|---|---|---|
| CLI `ari` (`ari.cli:app`) | Indirectly (output paths) | resolver+adapter default-on; README/`cli_reference.md` re-synced |
| `ari.public.*` (incl. `paths`) | Only if `ari.config` renamed | re-export shim + `check_public_api_contracts.py` |
| MCP `ari-skill-*` servers | Via `ARI_CHECKPOINT_DIR` hand-off | env semantics unchanged (adapter) |
| Dashboard API (`viz/routes.py`, `api_*.py`) | Reads checkpoint/EAR/trace/report files | adapter dual-layout reads; `services/api.ts` untouched |
| Checkpoint format (`checkpoint.py`, `META_FILES`) | Layout re-bucketing | migration tool + dual-layout `META_FILES` |
| Config file formats (YAML) | Data dir MERGE only | loader base swapped via Protocol; formats unchanged |
| `report/` PDF-sync | **No** (explicitly excluded) | leave `sync_report_pdf.sh` + pages build alone |
| README/docs usage strings | Yes (path text) | doc-sync + readme-sync gates re-run |

## 10. Consolidated deletion criteria

No deletions in this subtask. For later phases, a legacy layout element is deletable only when **all** hold:

1. `RuntimePathResolver` (004) + adapter (006) shipped and default-on for **≥ 1 minor version**.
2. A one-shot `ari migrate` re-bucketing pass exists and is documented.
3. `grep -rn` across `ari-core/`, all 14 `ari-skill-*`, `docs/`, `scripts/`, and `.github/workflows/` shows no remaining references to the old path except compat shims.
4. Relevant tests pass against **both** layouts (`test_checkpoint_legacy_tree.py`, `test_delete_checkpoint_experiments.py`, resume/data-flow tests).
5. Doc gates green (`check_doc_sources.py`, `check_readme_parity.py`, `check_ref_coupling.py`) and `check_directory_policy.py` (new) green.
6. Special-cased items: root `./checkpoints/` — confirm empty + no cwd-relative writer (**REVIEW_REQUIRED**); `report/` — **never deleted** by this workstream.

## 11. Related subtasks

| ID | Title | Relationship |
|---|---|---|
| **004** | `RuntimePathResolver` | Prerequisite — centralises path *reads* before any move |
| **006** | Backward-compatible path adapter | Prerequisite — dual-layout resolution + migration hook |
| (new) | `ari/migrations/` re-bucketing pass | One-shot porter for existing runs |
| (new) | `check_directory_policy.py` | CI guard for the canonical policy |
| (new) | `check_public_api_contracts.py` / `check_import_boundaries.py` | Guard the `ari.config` rename window |
| docs | README/`file_formats.md` path-text + `<slug>`→`<run_id>` fix | Doc-only follow-up after adapter |

## 12. Open questions (REVIEW_REQUIRED)

1. **Config code-package rename target** (`ari.config` → ?) — needs a name that ends the triple collision without churning the public API. (§5.1.a)
2. **Workspace-root reconciliation** — `default.yaml` (`./checkpoints/{run_id}/`) vs `auto_config()` (`workspace/checkpoints/{run_id}`); the resolver must pick one and adapt the other. (§5.1.d)
3. **`runs/` name collision** — top-level `runs/` vs registry `paper_registry/papers/<id>/runs/<job_id>`; confirm namespacing keeps them distinct. (§5.7)
4. **README slug drift** — `README.md:346` says `experiments/<slug>/<node_id>/` but code keys by `run_id`; fix as doc-only. (§5.4)
5. **Root `./checkpoints/` writers** — confirm nothing lands there via a cwd-relative launch before deleting the empty legacy dir. (§5.2)
6. **`environment_variables.md:211`** documents `ARI_AGENT_ENV_PATH` falling back to `~/.ari/agent.env`, contradicting the v0.5.0 "no `~/.ari/`" stance — verify against code before any path-doc edits (out of this subtask's scope, but adjacent).

---

*End of 005 — Directory Consolidation Plan. Planning only; no runtime code, config, workflow, or directory names were modified by this document.*

## Retirement Condition

This is a **program-level planning document**, not a per-subtask artifact. It
stays live for the duration of the refactoring program and may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources — never on assumption:

1. Every subtask this document governs is marked **DONE** in
   `docs/refactoring/007_subtask_index.md`, **or** this document has been
   explicitly **superseded** by a named replacement (the superseding document
   must reference this file by name).
2. Any conclusions worth keeping have been folded into the permanent
   documentation / architecture.

Before any `git rm`, re-read this document's own conditions and check each one
against the current repository. See the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
