# 004 — Legacy / Obsolete / Unused / Duplicate Inventory

> **Status: PLANNING ONLY.** Nothing in this document deletes, moves, or edits any
> runtime code, config, prompt, workflow, or directory. It is a grounded inventory of
> removal/consolidation *candidates* for later, contract-safe implementation subtasks.
> Every path and count below was verified by direct inspection of the repository on the
> planning date **2026-07-01** (git branch `main`, `ari-core` version `0.9.0`). Where a
> hypothesized artifact does **not** exist, this document says so explicitly rather than
> speculating.

## Scope and rules honored here

- **Contracts preserved conceptually.** No candidate in this document proposes breaking,
  without an explicit compatibility-adapter note, any of: the `ari` console script,
  `ari.public.*`, MCP tool contracts (`ari-skill-*` servers), dashboard API
  endpoints/schema, checkpoint/output/config file formats, `ari-skill-*` → `ari-core`
  stable interfaces, README/docs usage, or scripts invoked by `.github/workflows/`.
- **"Deprecated" is reserved for external contracts only.** Internal dead/unused code is
  labeled *unused*, *obsolete*, *duplicate*, or *unclear* — never "deprecated". The single
  legitimate internal "deprecation" surface is `ari/_deprecation.py`, whose *purpose* is to
  emit warnings for external-contract paths/env-vars/fields (see §4).
- **Classification vocabulary:** `KEEP` / `ADAPT` / `MERGE` / `MOVE_TO_LEGACY` /
  `DELETE_CANDIDATE` / `REVIEW_REQUIRED`.
- **Candidate block schema** (per the master spec): *Type* / *Evidence* / *Referenced by* /
  *Used in tests* / *Used in docs* / *Runtime role* / *Replacement candidate* / *Risk of
  removal* / *Recommended action* / *Related subtask*.

### Subtask cross-reference map

Subtask numbers are those of the master refactoring plan; the parenthetical descriptors
below are this document's working mapping (derived from the master prompt and the storage
findings), not fabricated titles.

- **002** — repository hygiene / build-artifact & runtime-storage policy, `.gitignore`
  consolidation, packaging surface.
- **016** — large-file decomposition (the >800 / >1200 LOC offenders).
- **055–057** — storage / paths / checkpoint-layout consolidation (the proposed
  `runs/<id>/{workspace,checkpoints,artifacts,traces,reports}` model; unify the
  `default.yaml` vs `auto_config` workspace-root disagreement).

---

## 0. Corrections to the working skeleton (verified negatives)

Before the inventory, three items the intake skeleton flagged are **NOT present** and must
not be actioned as if they were:

| Skeleton claim | Verified reality | Evidence |
|---|---|---|
| "committed frontend `node_modules` in git" | **FALSE.** `git ls-files \| grep node_modules` → **0** tracked files. `node_modules/` exists only as a 112 MB working install; it is gitignored. | `.gitignore:112` (`node_modules/`), `.gitignore:113` (`ari-core/ari/viz/frontend/node_modules/`) |
| "any `*.egg-info` tracked" | **FALSE.** `git ls-files \| grep egg-info` → **0** tracked. 6 skill + 4 vendor `*.egg-info` dirs exist on disk (editable installs) but are gitignored. | `.gitignore:11`, `.gitignore:90` (`*.egg-info/`) |
| "`sonfigs/` directory" | **Does not exist anywhere.** `find -iname '*sonfig*'` → empty. The confusable trio is `ari/config/` (code) vs `ari/configs/` (data) vs top-level `ari-core/config/` (rubric data). See §6. | `find` empty |

These negatives are load-bearing: subtasks must not "remove committed node_modules",
"untrack egg-info", or "delete sonfigs" — there is nothing to remove. The genuine hygiene
signal (untracked local caches, `.gitignore` duplication) is inventoried in §2–§3.

---

## 1. Runtime storage artifacts (local, untracked)

All ARI runtime storage is gitignored, so *none* of the items in this section is a
git-tracked change. "Removal" here means local `rm`/GC of on-disk scratch, plus fixing the
*config that keeps regenerating the legacy layout* (which IS a tracked change, deferred to
055–057). Confirmed ignored: `git check-ignore checkpoints/ workspace/ workspace/staging/`
→ all three ignored; `git ls-files` returns zero entries under either tree.

### 1.1 Root-level `checkpoints/` (coexists with `workspace/checkpoints/`)

- **Type:** legacy / unused (on-disk), plus a tracked *config* root cause.
- **Evidence:** `checkpoints/` exists at repo root, **empty** (mtime Apr 30), while the only
  populated run lives at `workspace/checkpoints/20260507051857_We_propose_an_implementation_of_CSR-form/`.
  The root dir is regenerated because the shipped data file
  `ari-core/config/default.yaml:14` (and `:39`) still specify `./checkpoints/{run_id}/`
  (root-relative), whereas `ari-core/ari/config/__init__.py:588-592` (`auto_config`) defaults
  to `{repo_root}/workspace/checkpoints/{run_id}`. Two sources of truth for the workspace
  root disagree.
- **Referenced by:** `default.yaml:14,39` (legacy value); `PathManager` derives
  `checkpoints_root = {workspace_root}/checkpoints` (`ari/paths.py`).
- **Used in tests:** path-derivation tests exercise `PathManager`; no test asserts the
  *root-level* empty dir (unconfirmed exhaustively).
- **Used in docs:** `reference/file_formats.md` / storage docs describe the checkpoint
  layout; the root-vs-workspace split is not documented as intentional.
- **Runtime role:** none for the empty root dir; the populated dir under `workspace/` is the
  live checkpoint store.
- **Replacement candidate:** single workspace-root source of truth →
  `runs/<id>/{checkpoints,...}` consolidation (055–057). Reconcile `default.yaml` with
  `auto_config`.
- **Risk of removal:** low for the empty on-disk dir; **medium** for the config change —
  `default.yaml` is a config *file format* surface, and `checkpoint_dir` templating flows
  through `finder.find_workflow_yaml` and `{{checkpoint_dir}}` expansion in `workflow.yaml`.
- **Recommended action:** `DELETE_CANDIDATE` for the empty on-disk `checkpoints/` (local
  only); `REVIEW_REQUIRED` / `ADAPT` for the `default.yaml`↔`auto_config` disagreement (with
  a back-compat note so existing pinned `ARI_CHECKPOINT_DIR` runs still resolve).
- **Related subtask:** 055–057.

### 1.2 `workspace/staging/` — 7 stale, empty timestamp dirs

- **Type:** obsolete / unused runtime output.
- **Evidence:** `workspace/staging/` holds 7 dirs named `YYYYmmddHHMMSS`
  (`20260430164213 … 20260504064644`), timestamps **Apr 30 – May 4** (7–9 weeks before the
  planning date). Each sampled dir is **empty**; total tree is **32K**. Produced by
  `PathManager.new_staging_dir()` (`ari/paths.py`), gitignored at `.gitignore:70`.
- **Referenced by:** `new_staging_dir()`; publish/clone staging flows.
- **Used in tests:** staging creation is covered indirectly by publish tests; the stale dirs
  themselves are not referenced.
- **Used in docs:** staging is mentioned in the publication-lifecycle concept doc; no
  retention policy is documented.
- **Runtime role:** none (leftover scratch from completed/aborted runs).
- **Replacement candidate:** a staging GC / retention policy under the `runs/<id>/` model.
- **Risk of removal:** low (local, empty, untracked).
- **Recommended action:** `DELETE_CANDIDATE` (local cleanup); `REVIEW_REQUIRED` to add a
  retention/GC policy so this does not re-accumulate.
- **Related subtask:** 055–057.

### 1.3 `workspace/bundle.tar.gz` — stray artifact

- **Type:** unused / stray runtime artifact.
- **Evidence:** a 9,026-byte `bundle.tar.gz` sits at `workspace/bundle.tar.gz` (mtime
  May 5). Under the gitignored `workspace/` tree; not referenced by any tracked code
  (grep of `ari-core/ari` for `bundle.tar.gz` yields only clone/publish generic tarball
  handling, not this literal path).
- **Referenced by:** none directly.
- **Used in tests / docs:** no.
- **Runtime role:** none (appears to be a one-off clone/publish output).
- **Replacement candidate:** n/a.
- **Risk of removal:** negligible (local, untracked).
- **Recommended action:** `DELETE_CANDIDATE` (local cleanup).
- **Related subtask:** 002.

### 1.4 `__pycache__/` — 2,930 dirs on disk, **zero tracked**

- **Type:** unused build cache (hygiene).
- **Evidence:** `find . -type d -name __pycache__` (excl. `node_modules`) → **2,930** dirs;
  `git ls-files | grep -E '__pycache__|\.pyc$'` → **0**. All ignored via `.gitignore:6` and
  `.gitignore:87`. Present under `ari-core/ari/config/`, `ari-core/ari/configs/`, every
  `ari-skill-*/src` and `/tests`, and `report/scripts/`.
- **Referenced by / tests / docs:** n/a (transient).
- **Runtime role:** CPython bytecode cache.
- **Replacement candidate:** n/a.
- **Risk of removal:** none (regenerated on import).
- **Recommended action:** `KEEP` the ignore rule as-is; optional local `find -delete` before
  packaging. No repo change needed — the intake skeleton's "committed pycache" concern does
  not apply.
- **Related subtask:** 002.

### 1.5 `report/scripts/{.venv,__pycache__}` — on disk, **not tracked**

- **Type:** unused build cache (hygiene) — *correction to a prior finding*.
- **Evidence:** `report/scripts/.venv/` and `report/scripts/__pycache__/` exist on disk, but
  `git ls-files report/ | grep -E '\.venv|__pycache__|\.pyc'` → **0**. The docs-area finding
  that called these "tracked" is imprecise: they are present locally but ignored
  (`.gitignore:108` `.venv/`, `:87` `__pycache__/`).
- **Referenced by / tests / docs:** the report Gate scripts (`report/scripts/check_*.py`)
  run under this local venv; nothing tracked references the venv path.
- **Runtime role:** local tooling environment for report gates.
- **Replacement candidate:** n/a.
- **Risk of removal:** none for the caches; `.venv/` is a developer convenience.
- **Recommended action:** `KEEP` (ignored working files); no action.
- **Related subtask:** 002.

---

## 2. `.gitignore` hygiene — duplicated ignore blocks

- **Type:** duplicate / typo (config hygiene).
- **Evidence:** three ignore patterns each appear **twice** in `.gitignore`:
  `__pycache__/` at **line 6 and line 87**; `*.egg-info/` at **line 11 and line 90**;
  `dist/` at **line 12 and line 93**. The file appears to concatenate two ignore blocks
  (an upper generic block and a lower repeated block ~line 83–93 that also adds
  `ari-core/experiments/` `:83` and `ari-core/checkpoints/` `:84`).
- **Referenced by:** git only.
- **Used in tests:** no. **Used in docs:** no.
- **Runtime role:** ignore policy; duplicates are harmless but obscure intent.
- **Replacement candidate:** a single de-duplicated ignore section.
- **Risk of removal:** low — `.gitignore` is not runtime code, but it is tracked; changing it
  is out of scope for this planning doc and must land in an implementation subtask.
- **Recommended action:** `MERGE` (collapse the duplicate lines) — `REVIEW_REQUIRED` first to
  confirm the two blocks were not intended for different directory scopes.
- **Related subtask:** 002.

### 2.1 Defensive ignores for non-existent dirs

- **Type:** unclear (possibly obsolete).
- **Evidence:** `.gitignore:83` `ari-core/experiments/` and `:84` `ari-core/checkpoints/` are
  ignored, but neither directory exists on disk (`ls ari-core/checkpoints` /
  `ari-core/experiments` → absent). These are defensive entries from when runs could be
  launched with cwd = `ari-core/`.
- **Referenced by / tests / docs:** none.
- **Runtime role:** none currently.
- **Replacement candidate:** n/a.
- **Risk of removal:** low, but harmless to keep.
- **Recommended action:** `REVIEW_REQUIRED` (keep as defensive, or drop when the workspace
  root is unified in 055–057).
- **Related subtask:** 002 / 055–057.

---

## 3. Deprecation infrastructure (external-contract; partial dead code)

### 3.1 `ari/_deprecation.py` — the one legitimate "deprecation" surface

- **Type:** KEEP core, with *unused* sub-functions.
- **Evidence:** `ari-core/ari/_deprecation.py` (**63 LOC**) centralizes `DeprecationWarning`
  emission for legacy `~/.ari/` paths, env-var aliases, and config/CLI fields. It exposes
  three helpers: `warn_deprecated_path`, `warn_deprecated_env`, `warn_deprecated_field`.
  Only **`warn_deprecated_path`** is actually called, at **5 sanctioned sites**:
  `memory_cli.py:321`, `publish/backends/ari_registry.py:49`, `clone/resolvers/ari.py:48`,
  `viz/api_publish.py:45`, `registry/__init__.py:41` (these match the `refactor-guards.yml`
  allow-list of sanctioned `~/.ari` shim sites). `warn_deprecated_env` and
  `warn_deprecated_field` have **zero call sites** (`grep` outside the module → empty).
- **Referenced by:** the 5 sites above (path helper only); it is also on the
  `refactor-guards.yml` `~/.ari` allow-list — so the file itself is a CI-sanctioned shim.
- **Used in tests:** deprecation-warning behavior may be asserted in memory/publish tests
  (unconfirmed exhaustively); the two unused helpers have no coverage.
- **Used in docs:** its docstring cites `DEPRECATION_REMOVAL.md` — **which does not exist**
  (`find -iname 'DEPRECATION_REMOVAL*'` → empty). Doc drift.
- **Runtime role:** emits warnings when Tier-B `~/.ari/` fallbacks are hit (v0.5→v1.0
  migration). Legitimately gates *external-contract* legacy behavior.
- **Replacement candidate:** none for the module; the two unused helpers could be pruned or
  wired to real deprecation sites (env aliases, config fields) if any remain.
- **Risk of removal:** **do not remove the module** — it backs an external migration
  contract and is CI-allow-listed. Removing the two *unused* helpers is low-risk but they may
  be intentional API symmetry.
- **Recommended action:** `KEEP` the module and `warn_deprecated_path`; `REVIEW_REQUIRED` for
  `warn_deprecated_env` / `warn_deprecated_field` (prune or adopt). Separately, resolve the
  dangling `DEPRECATION_REMOVAL.md` reference (create the doc or drop the citation).
- **Related subtask:** 002 (hygiene) + docs-source-sync follow-up.

---

## 4. Vendored / submodule / duplicate-logic candidates

### 4.1 `_paperbench_bridge.py` + `vendor/paperbench` submodule

- **Type:** duplicate (apparent) / vendored (actual) — **not** a delete candidate.
- **Evidence:** `ari-skill-paper-re/vendor/paperbench/` is a **git submodule**
  (`.gitmodules`: `openai/preparedness`), injected on `sys.path` via `src/_vendor_path.py`.
  `ari-skill-paper-re/src/_paperbench_bridge.py` (**2,376 LOC**) re-exports SimpleJudge /
  TaskNode from that submodule **with no local fallback**. The dashboard-side
  `ari-core/ari/viz/api_paperbench.py` (813 LOC) is an *independent* PaperBench surface — the
  skills findings confirm PaperBench logic is **not** duplicated across skills.
- **Referenced by:** `ari-skill-paper-re/src/server.py` (1,395 LOC); the ORS pipeline stages
  (`ors_grade`) in `config/workflow.yaml`.
- **Used in tests:** `ari-skill-paper-re/tests/` (bridge behavior).
- **Used in docs:** `reference/api_paperbench.md`, `guides/paperbench/*`.
- **Runtime role:** adapter over upstream PaperBench grading; the "duplication" is
  intentional vendoring, not copy-paste drift.
- **Replacement candidate:** none for the bridge role; the *size* (2,376 LOC) is a
  decomposition target, not a legacy one.
- **Risk of removal:** high — removing the bridge breaks the ORS reproducibility contract.
- **Recommended action:** `KEEP` (bridge + submodule). Route the file-size concern to 016
  (large-file split), not to this legacy inventory.
- **Related subtask:** 016.

### 4.2 `vendor/virsci` submodule (idea skill)

- **Type:** vendored — KEEP.
- **Evidence:** `.gitmodules` declares `ari-skill-idea/vendor/virsci`
  (`kotama7/Virtual-Scientists`). `ari-skill-idea/src/server.py` execs the vendored
  `utils/prompt.py`; fallback prompts at `server.py:252-266` exist only for when the vendor
  path is unavailable.
- **Referenced by:** idea skill runtime; `virsci_runtime.py`, `snapshot.py`.
- **Used in tests / docs:** idea-skill tests; `guides/` idea generation.
- **Runtime role:** upstream multi-agent idea generator.
- **Risk of removal:** high (forks upstream / breaks idea generation).
- **Recommended action:** `KEEP`.
- **Related subtask:** n/a.

### 4.3 Two ReAct loops — `agent/loop.py` vs `agent/react_driver.py`

- **Type:** duplicate (logic).
- **Evidence:** `ari-core/ari/agent/loop.py` (**1,630 LOC**, `AgentLoop.run` ~1,170-line
  method) is the ReAct executor for BFTS nodes; `ari-core/ari/agent/react_driver.py`
  (**442 LOC**) is a second, cleaner generic ReAct loop used by pipeline stages
  (`pipeline/stage_runner.py:143`). Two implementations of the same Thought→Action→
  Observation contract.
- **Referenced by:** `loop.py` ← `core.py::build_runtime`; `react_driver.py` ←
  `pipeline/stage_runner.py`.
- **Used in tests:** both paths exercised (agent tests + pipeline e2e).
- **Used in docs:** `concepts/architecture.md`, `concepts/bfts.md`.
- **Runtime role:** node execution (loop.py) vs pipeline-stage ReAct (react_driver.py).
- **Replacement candidate:** a single unified ReAct driver behind the (roadmapped)
  `StageRunner` protocol.
- **Risk of removal:** **high** — both are live; unifying them touches BFTS execution and
  pipeline stages. This is a decomposition, not a deletion.
- **Recommended action:** `MERGE` (long-horizon) / `REVIEW_REQUIRED`. Do not delete either in
  isolation.
- **Related subtask:** 016.

### 4.4 Two MCP server idioms (FastMCP vs low-level `Server`)

- **Type:** duplicate (pattern).
- **Evidence:** 10 skills use `FastMCP` + `@mcp.tool()`; 4 (coding, evaluator, hpc,
  orchestrator) use low-level `mcp.server.Server` + `@server.list_tools()`/`call_tool()`,
  returning `list[TextContent(...)]`. Divergent return shapes and registration.
- **Referenced by:** `ari/mcp/client.py` consumes both via the `{"result"|"error"}` envelope.
- **Used in tests:** per-skill server tests.
- **Used in docs:** `reference/mcp_tools.md`, `reference/skills.md`.
- **Runtime role:** MCP tool servers.
- **Replacement candidate:** one idiom (FastMCP) for all skills, behind stable tool names.
- **Risk of removal:** **high** — MCP tool names / `inputSchema` / return envelope are a
  hard contract; any unification must preserve them exactly.
- **Recommended action:** `REVIEW_REQUIRED` → `ADAPT` (converge idioms with a
  contract-preserving adapter). Not a delete.
- **Related subtask:** 016 (skill-server normalization).

### 4.5 Dormant `react:` stage path in the default workflow

- **Type:** unused-in-default (obsolete?) — unclear.
- **Evidence:** `stage_runner.py:51 _run_react_stage` implements a ReAct stage branch, but
  `grep -c 'react:' ari-core/config/workflow.yaml` → **0**: no shipped stage uses it in the
  default config. It is exercised only by tests / per-checkpoint YAML (unconfirmed which).
- **Referenced by:** `pipeline/orchestrator.py` (`if stage_cfg.get("react")` fork).
- **Used in tests:** likely (pipeline tests); unconfirmed exhaustively.
- **Used in docs:** `guides/experiment_file.md` documents the stage schema.
- **Runtime role:** alternate stage dispatch; dormant in default config.
- **Replacement candidate:** fold into `BasePipelineStage` subclasses (`SubprocessMCPStage`
  / `ReActStage`) per the pipeline findings.
- **Risk of removal:** medium — removing would drop a documented stage capability even if
  unused by default; keep unless tests confirm it is fully dead.
- **Recommended action:** `REVIEW_REQUIRED` (confirm test/per-checkpoint usage before any
  MOVE_TO_LEGACY).
- **Related subtask:** 016.

---

## 5. Unused / dead code surfaces

### 5.1 `WIZARD_ROUTES` dict — abandoned partial route table

- **Type:** unused (dead code).
- **Evidence:** `ari-core/ari/viz/api_wizard.py:30` defines `WIZARD_ROUTES = {...}`. Repo-wide
  `grep 'WIZARD_ROUTES'` finds **only** the definition — zero readers. It is a partial,
  abandoned attempt at the declarative route table that `routes.py` never adopted (dispatch
  is still the giant `if/elif` chain).
- **Referenced by:** nothing.
- **Used in tests / docs:** no.
- **Runtime role:** none.
- **Replacement candidate:** the real route-registry refactor (viz thin-routes) would
  *supersede* it; the current dict is not that registry.
- **Risk of removal:** negligible (unreferenced literal).
- **Recommended action:** `DELETE_CANDIDATE` (defer to the viz route-registry subtask so the
  intended replacement lands in the same change).
- **Related subtask:** 016 (viz decomposition).

### 5.2 `ari.schemas.load()` — loader API with no production importer

- **Type:** unused surface (unclear).
- **Evidence:** `ari-core/ari/schemas/__init__.py` exposes `load(name)` / `schema_path(name)`
  over `node_report.schema.json` (125 lines) + `publish.schema.json` (56 lines). Repo-wide
  grep for `schemas.load` / `from ari.schemas` in `ari-core/ari/` production code → **empty**;
  the only consumer is `tests/test_node_report.py:30`, which reads the file by direct path,
  **bypassing the loader**. So the loader API is effectively unused, and the JSON schemas are
  not runtime-validated by any core code.
- **Referenced by:** one test, by filesystem path (not via `load()`).
- **Used in tests:** yes (indirectly, not through the API).
- **Used in docs:** `reference/rubric_schema.md` / `file_formats.md` describe schemas.
- **Runtime role:** none currently (schemas are documentation-grade, not enforced).
- **Replacement candidate:** either wire `schemas.load()` into checkpoint/publish write paths
  (make it live) or drop the loader and keep raw JSON files.
- **Risk of removal:** low for the loader; the *schema files* are a documented file-format
  surface and must be kept.
- **Recommended action:** `REVIEW_REQUIRED` (adopt the loader for validation, or trim to the
  raw files). Keep the `.schema.json` files regardless.
- **Related subtask:** 002 / packaging.

### 5.3 `[project.scripts]` `server:main` in 2 skills — unused, inconsistent

- **Type:** unused / inconsistent (external-contract-adjacent).
- **Evidence:** only `ari-skill-replicate/pyproject.toml:27` and
  `ari-skill-paper-re/pyproject.toml:29` declare a console script, both
  `= "server:main"` — a bare `server:` module ref relying on `src/` on `sys.path`. The MCP
  loader launches every skill by filesystem path (`python <skill>/src/server.py`), so these
  entry points are **unused by the loader** and inconsistent with the other 12 skills.
- **Referenced by:** nothing in the launch path.
- **Used in tests / docs:** no.
- **Runtime role:** none (loader ignores them).
- **Replacement candidate:** either remove both, or standardize a console entry across all 14
  skills.
- **Risk of removal:** low *functionally*, but `[project.scripts]` is a packaging surface — a
  downstream user could `pip install` the skill and rely on the entry point. Treat as
  external contract per the rules.
- **Recommended action:** `ADAPT` / `REVIEW_REQUIRED` (standardize rather than silently
  delete; if removed, note the packaging-surface change).
- **Related subtask:** 002.

### 5.4 Empty `ari/__init__.py` — no `__version__`

- **Type:** unclear / incomplete (not legacy).
- **Evidence:** `ari-core/ari/__init__.py` is **empty** (0 bytes / one blank line). Version
  `0.9.0` exists only in `ari-core/pyproject.toml`; there is no programmatic
  `ari.__version__`. Any code expecting `ari.__version__` would fail (no such caller
  confirmed).
- **Referenced by:** implicit package import.
- **Used in tests / docs:** README says to "import from `ari.public.*`"; the empty root
  package is not itself documented.
- **Runtime role:** package marker only.
- **Replacement candidate:** add `__version__` (single-sourced from the manifest) — additive,
  contract-safe.
- **Risk of removal:** n/a (nothing to remove; this is an *add* candidate).
- **Recommended action:** `REVIEW_REQUIRED` / `ADAPT` (populate `__version__`).
- **Related subtask:** 002.

### 5.5 `ari.public` package exports nothing at top level

- **Type:** unclear (contract-vs-docs mismatch).
- **Evidence:** `ari-core/ari/public/__init__.py` (28 lines) is docstring-only; callers must
  import submodules (`ari.public.paths`, `ari.public.llm`, …) even though the README frames
  the surface as `ari.public.*`. The submodule surface itself is the stable contract and must
  not break.
- **Referenced by:** 8 public submodules; consumed by skills via `try/except ImportError`.
- **Used in tests:** public-API tests exist for submodules.
- **Used in docs:** `reference/public_api.md`.
- **Runtime role:** stable API facade.
- **Replacement candidate:** add explicit top-level re-exports (additive) so `ari.public`
  matches the documented `.*` framing.
- **Risk of removal:** n/a (additive change, not removal); **must not** remove or rename any
  existing submodule symbol.
- **Recommended action:** `REVIEW_REQUIRED` / `ADAPT` (additive re-exports only).
- **Related subtask:** 002.

---

## 6. `config` / `configs` / `config` triple + `sonfigs` (does not exist)

- **Type:** duplicate-looking / naming-confusable (KEEP all three; distinct roles).
- **Evidence:** three same-family dirs with **different** roles:
  - `ari-core/ari/config/` — **code**: `finder.py` (workflow/profile YAML discovery),
    `__init__.py` (628 LOC Pydantic models + `ARI_*` env overrides + `auto_config`), `README.md`.
  - `ari-core/ari/configs/` — **packaged data + loader**: `defaults.yaml`,
    `model_prices.yaml`, `_loader.py` (`FilesystemConfigLoader`), `__init__.py`, `README.md`.
  - `ari-core/config/` — **shipped rubric/profile/workflow data**: `default.yaml`,
    `workflow.yaml`, `profiles/{cloud,hpc,laptop}.yaml`,
    `paperbench_rubrics/{generic,nature,neurips,sc}.yaml`, `reviewer_rubrics/*.yaml`
    (23 venues), `reviewer_rubrics/fewshot_examples/neurips/*.json`.
  - **`sonfigs/` does not exist** (`find -iname '*sonfig*'` → empty). The intake prompt's
    "sonfigs" typo is not present in the repo.
- **Overlaps worth noting (not deletions):** (a) `default.yaml` (rubric-data defaults) vs
  `configs/defaults.yaml` (only `models.lineage_decision_default`) are two unrelated
  "defaults" files; (b) `finder.find_workflow_yaml` has a 4-tier fallback spread across two
  dir trees.
- **Referenced by:** `config/__init__.py`, `config/finder.py`, `configs/_loader.py`,
  `public/config_schema.py` (re-exports the Pydantic models — **stable API**).
- **Used in tests:** config-loading / settings-propagation tests.
- **Used in docs:** `reference/configuration.md`, per-dir `README.md`.
- **Runtime role:** config location (code) / packaged defaults (data) / rubric+workflow data.
- **Replacement candidate:** clearer names (e.g. `config_locator/` vs `config_defaults/` vs
  top-level `rubrics/`) — but renaming `ari/config`/`ari/configs` **breaks documented import
  paths** and the `ari.public.config_schema` re-export chain.
- **Risk of removal:** none should be removed. Renaming is **high** contract risk.
- **Recommended action:** `KEEP` all three; `REVIEW_REQUIRED` for a naming-clarity pass that,
  if pursued, must ship a compatibility shim (keep the old module importable). At minimum,
  document the trio in the per-dir READMEs and add a `check_directory_policy.py` naming rule.
- **Related subtask:** 055–057 (path/config consolidation) + a proposed
  `check_directory_policy.py` (planning only; see 006-series checker inventory).

---

## 7. Stale metadata / manifest drift

### 7.1 `mcp.json` tool lists out of sync with `@mcp.tool` decorators

- **Type:** obsolete metadata.
- **Evidence (from skills findings, not re-counted here):** `memory/mcp.json` advertises 4
  tools but `server.py` has **15** decorators; `web` advertises 5 vs 9; `paper` 12 vs 14;
  `coding`/`hpc`/`vlm`/`orchestrator` list `[]`; **`transform` has no `mcp.json` at all**
  (only `skill.yaml`).
- **Referenced by:** skill registry / dashboard `GET /api/skills` may read these manifests.
- **Used in tests:** unconfirmed.
- **Used in docs:** `reference/mcp_tools.md`, `reference/skills.md` list tools.
- **Runtime role:** discovery metadata (the authoritative source is the live server's
  `list_tools()`).
- **Replacement candidate:** generate `mcp.json` tool lists from the server decorators.
- **Risk of removal:** **do not delete** — regenerate. The *file* is a discovery contract
  surface; only its *stale contents* are the defect.
- **Recommended action:** `ADAPT` / `REVIEW_REQUIRED` (regenerate + add a
  `check_public_api_contracts`-style manifest gate). Not a delete.
- **Related subtask:** 002.

### 7.2 Skill version skew across manifests

- **Type:** obsolete metadata.
- **Evidence:** `paper-re` = 0.8.0 (pyproject) / 0.4.0 (mcp.json) / 0.5.0 (skill.yaml);
  `evaluator` 1.0.0 vs skill.yaml 0.4.1; `replicate` 0.2.0 vs mcp.json 0.1.0. No shared
  versioning; `orchestrator` has **no** `pyproject.toml` (only `src/requirements.txt`).
- **Referenced by:** manifests only.
- **Used in tests / docs:** no.
- **Runtime role:** none functional (skills launch by path).
- **Replacement candidate:** single-source version per skill.
- **Risk of removal:** low (metadata reconciliation).
- **Recommended action:** `REVIEW_REQUIRED` / `ADAPT` (reconcile; do not delete manifests).
- **Related subtask:** 002.

---

## 8. Legacy references in docs / config (dangling, not code)

### 8.1 `docs/_archive/refactor_audit.md` — referenced but MISSING

- **Type:** legacy dangling reference.
- **Evidence:** `docs/_archive/` **does not exist** (`ls docs/_archive` → absent), yet
  `docs/README.md` links it at **4 places**: line 5 (prose), line 20 (dir table), line 86
  (`_archive/refactor_audit.md` TOC), line 135 (tri-language parity row en/ja/zh). VitePress
  `srcExclude: '**/_archive/**'` and `check_doc_sources` exempt `_archive`, so hard gates stay
  green; the broken markdown links are caught only by `check_doc_links` markdown mode, which
  is **advisory** → silent drift.
- **Referenced by:** `docs/README.md` (4 lines).
- **Used in tests:** advisory link checker only.
- **Used in docs:** yes (broken links).
- **Runtime role:** none.
- **Replacement candidate:** either restore the archived doc or remove the 4 references.
- **Risk of removal:** low (docs only). Must not touch VitePress IA otherwise.
- **Recommended action:** `REVIEW_REQUIRED` (fix links or restore file). Docs-only; defer to a
  docs-sync subtask.
- **Related subtask:** 002 / docs-source-sync.

### 8.2 `ARI_AGENT_ENV_PATH` → `~/.ari/agent.env` doc contradiction

- **Type:** legacy reference (potential contradiction).
- **Evidence:** `reference/environment_variables.md:211` says `ARI_AGENT_ENV_PATH` "falls back
  to `~/.ari/agent.env`", while the **same file** (line 19), `guides/migration.md`, and
  `concepts/architecture.md:541` state `~/.ari/` was **removed in v0.5.0**. Whether code still
  falls back is **unconfirmed** (not verified against `config/__init__.py`/`paths.py` in this
  pass).
- **Referenced by:** docs prose.
- **Used in tests:** the `refactor-guards.yml` `~/.ari` grep guard covers *code*, not this doc.
- **Used in docs:** yes.
- **Runtime role:** unclear (needs code verification).
- **Replacement candidate:** align the doc with actual code behavior.
- **Risk of removal:** low (docs); but first verify the code path.
- **Recommended action:** `REVIEW_REQUIRED` (verify `ARI_AGENT_ENV_PATH` handling in code,
  then correct the doc).
- **Related subtask:** 055–057 (paths) + docs-sync.

---

## 9. Naming / typo candidates (unclear, contract-sensitive)

### 9.1 `ari/cli/lineage.py` — not a Typer command despite the name

- **Type:** typo / misleading naming (unclear).
- **Evidence:** `ari-core/ari/cli/lineage.py` sits under `cli/` but is **not** a Typer
  command group — it holds `_execute_lineage_decision` etc., imported by `cli/__init__.py:70`,
  `cli/run.py`, and `cli/bfts_loop.py`. It also creates a **core→viz** dependency
  (`cli/lineage.py:151` imports `viz.api_orchestrator._api_launch_sub_experiment`). The name
  implies a CLI subcommand that does not exist.
- **Referenced by:** `cli/__init__.py`, `cli/run.py`, `cli/bfts_loop.py`, plus lazy
  monkeypatch delegators.
- **Used in tests:** lineage-decision tests.
- **Used in docs:** `concepts/` lineage material.
- **Runtime role:** lineage-decision execution (BFTS post-node hook).
- **Replacement candidate:** relocate to `ari/orchestrator/lineage_actions.py` (or similar)
  to stop implying a CLI command, breaking the core→viz edge.
- **Risk of removal:** **medium** — many importers and monkeypatch surfaces depend on the
  current module path; any move needs a re-export shim to keep import paths stable.
- **Recommended action:** `REVIEW_REQUIRED` / `ADAPT` (rename/move with a compatibility
  re-export). Not a delete.
- **Related subtask:** 016.

---

## 10. Summary table (classification roll-up)

| # | Candidate | Path(s) | Type | Class |
|---|---|---|---|---|
| 1.1 | Empty root `checkpoints/` + `default.yaml` root path | `checkpoints/`, `ari-core/config/default.yaml:14,39` | legacy | DELETE_CANDIDATE (dir) / REVIEW_REQUIRED (config) |
| 1.2 | 7 stale empty staging dirs | `workspace/staging/2026043…–2026050…` | obsolete | DELETE_CANDIDATE |
| 1.3 | Stray bundle tarball | `workspace/bundle.tar.gz` | unused | DELETE_CANDIDATE |
| 1.4 | pycache caches (2,930, untracked) | repo-wide `__pycache__/` | unused | KEEP (ignore rule) |
| 1.5 | report script venv/cache (untracked) | `report/scripts/{.venv,__pycache__}` | unused | KEEP |
| 2 | Duplicated ignore lines | `.gitignore:6/87, 11/90, 12/93` | duplicate/typo | MERGE |
| 2.1 | Ignores for non-existent dirs | `.gitignore:83,84` | unclear | REVIEW_REQUIRED |
| 3.1 | `_deprecation.py` unused helpers | `ari-core/ari/_deprecation.py` | unused (partial) | KEEP core / REVIEW_REQUIRED helpers |
| 4.1 | PaperBench bridge + vendor submodule | `ari-skill-paper-re/src/_paperbench_bridge.py`, `vendor/paperbench` | duplicate(apparent)/vendored | KEEP (016 for size) |
| 4.2 | VirSci vendor submodule | `ari-skill-idea/vendor/virsci` | vendored | KEEP |
| 4.3 | Two ReAct loops | `ari/agent/loop.py`, `ari/agent/react_driver.py` | duplicate | MERGE / REVIEW_REQUIRED |
| 4.4 | Two MCP server idioms | 10× FastMCP vs 4× low-level `Server` | duplicate | REVIEW_REQUIRED / ADAPT |
| 4.5 | Dormant `react:` stage path | `ari/pipeline/stage_runner.py:51` | unused-in-default | REVIEW_REQUIRED |
| 5.1 | `WIZARD_ROUTES` dead dict | `ari/viz/api_wizard.py:30` | unused | DELETE_CANDIDATE |
| 5.2 | `schemas.load()` no prod importer | `ari/schemas/__init__.py` | unused | REVIEW_REQUIRED |
| 5.3 | `server:main` console scripts | `ari-skill-{replicate,paper-re}/pyproject.toml` | unused/inconsistent | ADAPT / REVIEW_REQUIRED |
| 5.4 | Empty `ari/__init__.py` (no `__version__`) | `ari-core/ari/__init__.py` | incomplete | ADAPT (additive) |
| 5.5 | `ari.public` no top-level exports | `ari-core/ari/public/__init__.py` | unclear | ADAPT (additive) |
| 6 | config/configs/config trio (no sonfigs) | `ari/config`, `ari/configs`, `ari-core/config` | naming-confusable | KEEP / REVIEW_REQUIRED |
| 7.1 | Stale `mcp.json` tool lists | `ari-skill-*/mcp.json` | obsolete metadata | ADAPT |
| 7.2 | Skill version skew | `ari-skill-*/{pyproject,mcp.json,skill.yaml}` | obsolete metadata | REVIEW_REQUIRED |
| 8.1 | Dangling `docs/_archive` links | `docs/README.md:5,20,86,135` | legacy dangling | REVIEW_REQUIRED |
| 8.2 | `ARI_AGENT_ENV_PATH` `~/.ari` doc contradiction | `reference/environment_variables.md:211` | legacy reference | REVIEW_REQUIRED |
| 9.1 | `cli/lineage.py` misleading name + core→viz edge | `ari/cli/lineage.py` | typo/naming | ADAPT / REVIEW_REQUIRED |

**No item in this document is classified `MOVE_TO_LEGACY`**: the on-disk scratch (§1) is
already gitignored and better handled by local GC + a retention policy than by a `legacy/`
tree, and every other candidate is either KEEP, an additive ADAPT, a MERGE that must preserve
a live contract, or a small DELETE_CANDIDATE deferred to its owning subtask.

---

## 11. What is explicitly NOT a candidate (verified negatives, restated)

- Committed `node_modules` — **none tracked** (`.gitignore:112–113`).
- Tracked `*.egg-info` — **none tracked** (`.gitignore:11,90`).
- Tracked `__pycache__`/`.pyc` — **none tracked** (`.gitignore:6,87`).
- `sonfigs/` — **does not exist**.
- Top-level `pyproject.toml` — **does not exist** (the core manifest is
  `ari-core/pyproject.toml`); this is by design, not a defect.
- `_paperbench_bridge.py` / `vendor/paperbench` / `vendor/virsci` — vendored submodules, not
  removable duplicates.

---

## 12. Planning disclaimer (restated)

This is the **planning phase**. **Nothing is deleted, moved, renamed, or edited by this
document.** Each candidate above is routed to an implementation subtask (002 hygiene/packaging,
016 large-file/duplicate-logic decomposition, 055–057 storage/paths consolidation), where the
change must (a) preserve every contract listed in §Scope with an explicit compatibility note
where a symbol/path/name would otherwise move, and (b) land alongside its intended replacement
rather than as a bare deletion. Local on-disk scratch (§1.1–§1.3) may be GC'd without any
git-tracked change; everything else requires a reviewed subtask.

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
