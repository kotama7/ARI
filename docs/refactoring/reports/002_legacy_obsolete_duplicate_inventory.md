# 002 — Legacy / Obsolete / Duplicate Code Inventory (Report)

> **Status: PLANNING / INVENTORY ONLY.** This report changes **no** runtime code,
> imports, prompts, configs, workflows, frontend, or directory names. It is the
> grounded, classified inventory of every legacy / obsolete / duplicate-logic
> surface in ARI. Deletion and merging happen in later subtasks (**016**, and the
> **053→054→055→056→057** dead-code chain); this document only *records and
> routes*.
>
> **Subtask:** 002 `inventory_legacy_obsolete_and_duplicate_code` (Phase 1 —
> Measurement & Inventory). Direct input to **016**
> (`clean_merge_or_quarantine_legacy_code`).
>
> **Repo baseline:** `/home/t-kotama/workplace/ARI` — git branch `whole_refactoring`
> (planning corpus committed on top of `main`), `ari-core` version `0.9.0`
> (`ari-core/pyproject.toml`). Verification date **2026-07-01**. Every `path:line`
> and LOC below was re-derived from the **live tree** with read-only commands;
> where a number in the source plans (`004_legacy_obsolete_inventory.md`,
> `subtasks/002_...md §5`) drifted from the live tree, the **live tree wins** and
> the drift is recorded in §9.

## 1. Scope and rules honored

- **Classification vocabulary (exactly one verdict per row):** `KEEP` / `ADAPT` /
  `MERGE` / `MOVE_TO_LEGACY` / `DELETE_CANDIDATE` / `REVIEW_REQUIRED`.
- **"Deprecated" is reserved for external contracts only** (public API, CLI, MCP,
  dashboard API, documented import paths, `ari-skill-*` stable interfaces). The
  only legitimate internal deprecation surface is `ari/_deprecation.py` (§3.1) —
  everything else internal uses the six-value vocabulary.
- **No edits proposed as actions.** No row reads "delete X" / "rename Y" as an
  instruction; every actionable verdict names the *owner subtask* that will do the
  edit under contract-preservation rules.
- **`DELETE_CANDIDATE` is non-authoritative here.** Every such verdict is gated on
  the 053→054→055→056 dead-code chain and on the 016/057 owner's sign-off.
- **Grounding.** Each row cites a real `path:line` and names the adjacent contract,
  or says "no contract touched". Absent paths are written "does not exist".
- **Contracts preserved conceptually** (must not be broken by any downstream phase
  acting on this report): the `ari = ari.cli:app` console script; `ari.public.*`;
  MCP tool names / `inputSchema` / `{"result"|"error"}` envelope /
  `mcp__<skill>__<tool>` naming; dashboard endpoints + JSON shapes + the WS
  `update` message; checkpoint/output/config file formats; the `ari-skill-*` →
  `ari-core` interface (incl. the core→`ari_skill_memory` edge); README/docs usage;
  and the scripts invoked by `.github/workflows/`.

---

## 2. Duplicate-logic seams

Column legend: **Path:line** (live) · **LOC** (`wc -l`) · **Adjacent contract** ·
**Verdict** · **Owner subtask**.

### 2.1 Two ReAct execution paths

| Item | Path:line | LOC | Description | Adjacent contract | Verdict | Owner |
|---|---|---|---|---|---|---|
| Primary ReAct loop | `ari-core/ari/agent/loop.py` | 1630 | `AgentLoop.run` — BFTS-node-coupled Thought→Action→Observation executor over MCP tools. | None external (internal core; monkeypatch surfaces used by tests). | `MERGE` / `REVIEW_REQUIRED` | 011 |
| Generic ReAct driver | `ari-core/ari/agent/react_driver.py:1` | 442 | Docstring: "Generic ReAct loop driver, decoupled from BFTS Node concepts… Used by pipeline.py for stages declaring a `react:` block." A second, cleaner implementation of the same loop contract. | None external (internal core). | `MERGE` / `REVIEW_REQUIRED` | 011 |

**Grounding.** `wc -l` → 1630 / 442. The **only direct importer** of
`react_driver` is `ari-core/ari/pipeline/stage_runner.py` (`from ari.agent.react_driver import …`
at lines **143** `run_react`, **162** `setup_sandbox_shims`/`snapshot_env`, **278**
`restore_env`). `pipeline/orchestrator.py:690`, `orchestrator/node_report/builder.py:400`,
and `viz/api_workflow.py:252` mention `react_driver` **in comments only** — they do
*not* import it (correction to §5 of the subtask plan; see §9). The
orchestrator drives the react branch indirectly via the `if stage_cfg.get("react"):`
fork at `orchestrator.py:691`, which routes to `stage_runner._run_react_stage`
(`stage_runner.py:51`).

**Dormant-but-wired, NOT dead.** `grep -rn 'react:' ari-core/config/` → **empty**:
no shipped workflow declares a `react:` block, so this path is *dormant in the
default config*. It is still wired (stage_runner, and exercised by tests /
per-checkpoint YAML). Classify `MERGE`/`REVIEW_REQUIRED` (owner 011), **never**
`DELETE_CANDIDATE` — a workflow could enable it at runtime.

**Adapter strategy for 011:** unify behind the roadmapped `StageRunner`/ReAct
protocol; keep `AgentLoop` and `react_driver.run_react` callable (lazy delegators
+ patched symbols preserved).

### 2.2 Two pipeline runners

| Item | Path:line | LOC (fn scope) | Description | Adjacent contract | Verdict | Owner |
|---|---|---|---|---|---|---|
| YAML-driven stage executor | `ari-core/ari/pipeline/orchestrator.py:155` (`def run_pipeline`) | file 913-LOC region around `run_pipeline` | The canonical workflow-stage executor over `workflow.yaml`-defined stages. | Checkpoint/output file formats; `config/workflow.yaml` shape. | `ADAPT` (canonical) | 012 |
| Dashboard PaperBench worker | `ari-core/ari/viz/api_paperbench_worker.py:168` (`def _run_pipeline`) | thread target | Parallel "run the pipeline" implementation; spawned as a `threading.Thread(target=_run_pipeline, …)` at `api_paperbench_worker.py:313`. Divergence risk: a fix to one may not reach the other. | Dashboard API (PaperBench run endpoints); checkpoint/output formats. | `MERGE` / `ADAPT` | 012 |

**Grounding.** `grep -n 'def run_pipeline\|def _run_pipeline'` → `orchestrator.py:155`,
`api_paperbench_worker.py:168`; thread spawn at `api_paperbench_worker.py:313`.

**Adapter strategy for 012:** keep
`viz/api_paperbench_worker._run_pipeline` as a **thin wrapper delegating** to the
single driver extracted from `pipeline.orchestrator.run_pipeline` (per §11 of the
subtask plan — delegate, do not delete). Endpoint paths/JSON shapes and checkpoint
artifact formats must be preserved.

### 2.3 Two MCP server idioms

| Idiom | Skills (server.py) | Count | Description | Adjacent contract | Verdict | Owner |
|---|---|---|---|---|---|---|
| `FastMCP` (`@mcp.tool()`) | benchmark, replicate, memory, vlm, idea, web, plot, paper, transform, paper-re | 10 | Tools return strings. | MCP tool names / `inputSchema` / `{"result"|"error"}` envelope / `mcp__<skill>__<tool>` naming. | `REVIEW_REQUIRED` / `ADAPT` | 010 |
| low-level `mcp.server.Server` | coding, hpc, orchestrator, evaluator | 4 | `@server.list_tools()`/`call_tool()` returning `list[TextContent(...)]` — different return shape. | Same MCP contract as above. | `REVIEW_REQUIRED` / `ADAPT` | 010 |

**Grounding.** `grep -rln 'FastMCP' ari-skill-*/src/server.py` → 10 skills;
`grep -rln 'from mcp.server import Server' ari-skill-*/src/server.py` → coding, hpc,
orchestrator, evaluator (4). Total 14. The idiom split is *internal*; any
convergence must preserve the tool `name`, `inputSchema`, and wire result shape
exactly. Note: owner is Phase-10 skill consistency (010) — recorded here without
proposing a tool-contract change. (`004` routed this to "016"; the live subtask
index assigns MCP-idiom reconciliation to **010** ST-10-3 — see §9.)

### 2.4 Scattered rubric-format handling

| Location | Path(s) | Description | Adjacent contract | Verdict | Owner |
|---|---|---|---|---|---|
| replicate skill | `ari-skill-replicate/src/{auditor,categories,generator,manifest,server}.py` | Rubric parsing/validation logic spread across 5 files. | MCP tool contracts; rubric file format. | `REVIEW_REQUIRED` / `MERGE` | 010 / 003 (data) |
| paper-re skill | `ari-skill-paper-re/src/_replicator_agent.py`, `ari-skill-paper-re/src/_compute/local_pbtask.py` | Rubric handling inside the paper-re replication agent + compute task. | MCP tool contracts; PaperBench rubric format. | `REVIEW_REQUIRED` | 010 |
| paper skill | `ari-skill-paper/src/server.py` | Rubric usage inside the largest skill server (2956 LOC per 001). | MCP tool contracts. | `REVIEW_REQUIRED` | 010 |
| core evaluator | `ari-core/ari/evaluator/{__init__,dynamic_axes,llm_evaluator}.py` | Rubric loading for evaluation axes. | Checkpoint `evaluation_criteria.json`; `EvaluatorConfig`. | `REVIEW_REQUIRED` | 009 |
| rubric DATA | `ari-core/config/paperbench_rubrics/{generic,nature,neurips,sc}.yaml`, `ari-core/config/reviewer_rubrics/*.yaml` (23 venues) | Data files, not logic — 4 paperbench + 23 reviewer venues. | Config file formats (YAML). | `KEEP` (data) | 003 |

**Grounding.** `ls` confirms replicate `{auditor,categories,generator,manifest}.py`;
paper-re `_replicator_agent.py` + `_compute/local_pbtask.py`; evaluator rubric
references in `__init__.py`, `dynamic_axes.py`, `llm_evaluator.py`;
`reviewer_rubrics/*.yaml` count = **23**; `paperbench_rubrics/` = generic, nature,
neurips, sc. No single owner of "load + validate a rubric" today — recorded as a
seam; **002 routes, does not merge**.

---

## 3. Legacy / obsolete surfaces

### 3.1 `ari/_deprecation.py` — the one legitimate deprecation surface

| Path:line | LOC | Description | Adjacent contract | Verdict | Owner |
|---|---|---|---|---|---|
| `ari-core/ari/_deprecation.py` | 63 | Centralized `DeprecationWarning` emission for legacy `~/.ari/` paths / env aliases / config fields. CI-allow-listed in `refactor-guards.yml`. Backs an *external* migration contract. | External-contract deprecation shim; `refactor-guards.yml` allow-list. | `KEEP` | — |

**Grounding.** `wc -l` → 63. This is the sanctioned mechanism; do not remove.
(Per `004` §3.1: `warn_deprecated_env`/`warn_deprecated_field` are unused helpers —
`REVIEW_REQUIRED` to prune-or-adopt — but the module itself is `KEEP`.)

### 3.2 Migration shims — `migrations/v05_to_v07/`

| Path:line | LOC | Description | Adjacent contract | Verdict | Owner |
|---|---|---|---|---|---|
| `ari-core/ari/migrations/v05_to_v07/__init__.py` | 18 | Package marker / `maybe_auto_migrate` export. | Checkpoint/memory format migration. | `KEEP` | — |
| `ari-core/ari/migrations/v05_to_v07/legacy_axes.py` | 36 | v0.5→v0.7 axis migration. | Evaluation-criteria format. | `KEEP` | — |
| `ari-core/ari/migrations/v05_to_v07/memory.py:26` | 29 | Holds `LEGACY_GLOBAL_PATH = Path.home()/".ari"/"global_memory.jsonl"` — the **sole legitimate accessor** of the v0.5.0-retired global path (line 26). | `ari_skill_memory` store path contract; `~/.ari` migration. | `KEEP` | — |
| `ari-core/ari/migrations/v05_to_v07/node_reports.py` | 79 | node_report migration. | Checkpoint `node_report.json` format. | `KEEP` | — |

**Grounding.** `wc -l` → 18 / 36 / 29 / 79 (**dir total 162**, not 170; the three
non-`__init__` files total 144 — drift recorded in §9). `LEGACY_GLOBAL_PATH` at
`memory.py:26` (confirmed); `__all__` also exports it. All `KEEP` — legitimate
external-contract migration path.

### 3.3 Coexisting storage roots (all `.gitignore`-covered, untracked)

| Path | On-disk state | Description | Adjacent contract | Verdict | Owner |
|---|---|---|---|---|---|
| Root `checkpoints/` | **empty** (mtime Apr 30) | Legacy root-level checkpoint dir; coexists with populated `workspace/checkpoints/`. Regenerated because `ari-core/config/default.yaml:14,39` still say `dir: ./checkpoints/{run_id}/` while `ari-core/ari/config/__init__.py:592` defaults to `{repo_root}/workspace/checkpoints/{run_id}`. | Checkpoint file format; `default.yaml` config format. | `MOVE_TO_LEGACY` / `DELETE_CANDIDATE` (empty on-disk dir) + `REVIEW_REQUIRED` (config disagreement) | 005 (config), 004 (policy) |
| `workspace/staging/` | 7 stale, empty timestamp dirs: `20260430164213, 20260430164558, 20260430165552, 20260504062702, 20260504063308, 20260504064416, 20260504064644` | Leftover scratch from completed/aborted runs (Apr 30–May 4). | No contract touched (untracked scratch). | `DELETE_CANDIDATE` (local GC) + `REVIEW_REQUIRED` (retention policy) | 005 |
| `workspace/bundle.tar.gz` | 9026 bytes (mtime May 5) | Stray one-off clone/publish artifact; not referenced by tracked code. | No contract touched. | `DELETE_CANDIDATE` (local GC) | 005 |

**Grounding.** `ls -la checkpoints/` → only `.`/`..` (empty). `ls workspace/staging/`
→ 7 timestamp dirs (all empty). `ls -la workspace/bundle.tar.gz` → 9026 bytes.
`git check-ignore checkpoints workspace` → both ignored ⇒ **no git-tracking
migration cost**; only on-disk / back-compat concerns. The `default.yaml`↔
`auto_config` disagreement is owned by 004/005; **002 only records it**.
`config/__init__.py:592`: `_ckpt_dir = str(_ari_root / "workspace" / "checkpoints" / "{run_id}")`
(auto_config def at :575). `default.yaml:14` and `:39`: `dir: ./checkpoints/{run_id}/`.

### 3.4 Dangling docs reference — `docs/_archive/refactor_audit.md`

| Path:line | Description | Adjacent contract | Verdict | Owner |
|---|---|---|---|---|
| `` `docs/_archive/refactor_audit.md` `` (referenced-but-missing) | The directory `docs/_archive/` **does not exist** (`ls docs/_archive/` → "No such file or directory"), yet the file is cited from ≥10 live doc locations. VitePress `srcExclude: '**/_archive/**'` and `check_doc_sources.py`'s `EXEMPT_DIR_SEGMENTS` exempt `_archive`, so hard gates stay green; broken markdown links drift silently (only advisory `check_doc_links.py` markdown mode catches them). | README/docs usage; docs-sync workflows. | `REVIEW_REQUIRED` (docs-only; fix links or restore file) | 017 (docs) / 013 (drift gate) |

**Grounding.** `grep -rn 'refactor_audit' docs/` (excluding the `docs/refactoring/`
planning corpus itself) confirms live dangling references at, at least:
`docs/README.md:86,135`; `docs/reference/public_api.md:208` (+ `ja:207`, `zh:175`);
`docs/guides/troubleshooting.md:254` (+ `ja:245`, `zh:238`);
`docs/guides/migration.md:162` (+ `ja:149`, `zh:146`);
`docs/reference/registry.md:28` (+ `ja:20`, `zh:20`);
`docs/concepts/architecture.md:543` (+ `ja:488`, `zh:474`);
`docs/about/release_policy.md:92` (+ `ja:86`, `zh:87`, as a grep-exclusion note).
The citation above uses **inline code**, not a Markdown link, so
`check_doc_links.py` does not follow it. This is a documentation contract issue,
routed to a docs subtask; **002 only records the dangling reference.**

---

## 4. Unused / abandoned code candidates

*(All `DELETE_CANDIDATE` / `ADAPT` verdicts here are non-authoritative and gated on
053→056 confirmation + 016/057 sign-off.)*

| Item | Path:line | LOC | Description | Adjacent contract | Verdict | Owner |
|---|---|---|---|---|---|---|
| `WIZARD_ROUTES` dict | `ari-core/ari/viz/api_wizard.py:30` | — | Abandoned partial declarative route table. Repo-wide `grep 'WIZARD_ROUTES'` → **only the definition, zero readers**. Dispatch is actually the manual `if/elif` chain in `routes.py`. | Dashboard module (any deletion must be confirmed by 020 not to be a live route). | `DELETE_CANDIDATE` (land with the viz route-registry refactor) | 011 / 020 |
| `ari.schemas.load()` | `ari-core/ari/schemas/__init__.py:11` (`def load`), `:18` (`def schema_path`) | — | Loader API with **no production importer** — repo-wide grep for `schemas.load` / `from ari.schemas import` in production code → empty (only `schemas/README.md:4` mentions it). Data files `node_report.schema.json` (4302 B), `publish.schema.json` (2468 B) are consumed by test/path, not the loader. | Documented file-format surface (keep the `.schema.json` files regardless). | `REVIEW_REQUIRED` (wire the loader for validation, or trim to raw files) | 002-series / packaging |
| `server:main` console scripts | `ari-skill-replicate/pyproject.toml:27`, `ari-skill-paper-re/pyproject.toml:29` | — | Only 2 of 14 skills declare `[project.scripts] … = "server:main"`. The MCP loader launches skills by filesystem path (`python <skill>/src/server.py`), so these are unused by the loader and inconsistent with the other 12. | `[project.scripts]` packaging surface (treat as external-adjacent). | `ADAPT` / `REVIEW_REQUIRED` (standardize, do not silently delete) | 010 (ST-10-6) |
| Empty `ari/__init__.py` | `ari-core/ari/__init__.py` | 0 (0 bytes) | Empty package marker; no programmatic `ari.__version__` (version lives only in `ari-core/pyproject.toml`). | `ari.public.*` adjacency (additive `__version__` must not shadow imports). | `ADAPT` (additive — populate `__version__`) | 002-series (ST-2-6) |
| `ari.public/__init__.py` top-level | `ari-core/ari/public/__init__.py` | 27 | Docstring-only; re-exports nothing at package top level. `from ari.public import cost_tracker` works; `from ari.public import bootstrap_skill` does not. README frames the surface as `ari.public.*` (submodule-qualified — consistent). | `ari.public.*` external API (must not remove/rename any submodule symbol). | `ADAPT` (additive re-exports only) / `REVIEW_REQUIRED` | 002-series (ST-2-6) |

**Grounding.** `grep -rn 'WIZARD_ROUTES' ari-core/ari/` → single hit at
`api_wizard.py:30`. `grep -rn 'schemas.load\|from ari.schemas import'` → only
`schemas/README.md:4`; `def load` at `schemas/__init__.py:11`, `def schema_path` at
`:18`; schema JSON files present. `grep -rn 'server:main' ari-skill-*/pyproject.toml`
→ replicate:27, paper-re:29. `wc -c ari-core/ari/__init__.py` → 0.
`wc -l ari-core/ari/public/__init__.py` → 27.

---

## 5. "Do NOT statically delete" — dynamic / string-dispatched reference roots

Authoritative allow-list for the 053→056 dead-code chain and for 016/057. A naive
"unused symbol" pass **will** falsely flag these; they are live-by-string.

| Root | Path:line | Exact string keys / mechanism | Targets | Adjacent contract | Verdict |
|---|---|---|---|---|---|
| publish backend dispatch | `ari-core/ari/publish/__init__.py:198` (`def _load_backend(name)`) | `if name == "ari-registry"` → `local-tarball` → `zenodo` → `gh` (**hyphenated dispatch keys**). Call sites: `:115`, `:164`. | modules `ari-core/ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py` (**underscore module names**) | `publish.schema.json` backend-name enum; publish/promote flow. | **do NOT statically delete** |
| composite scorer registry | `ari-core/ari/evaluator/llm_evaluator.py:165` (`_COMPOSITES` dict) | keys: `"harmonic_mean"`, `"arithmetic_mean"`, `"weighted_min"`, `"geometric_mean"`. Consumed at `:280`, `:283`, `:286`. Must stay in sync with `EvaluatorConfig.composite` (Literal). | scorer fns `weighted_harmonic_mean` / `weighted_arithmetic_mean` / `weighted_min` / `weighted_geometric_mean` | `EvaluatorConfig.composite` Literal; evaluator behavior. | **do NOT statically delete** |
| schema loader (if adopted) | `ari-core/ari/schemas/__init__.py:11` (`def load(name)`) | dynamic `name` → `{name}.schema.json` | `node_report.schema.json`, `publish.schema.json` | documented file-format surface | **do NOT delete the `.schema.json` files** (loader itself is §4 `REVIEW_REQUIRED`) |

**Important correction (grounded).** The publish `_load_backend` **dispatch string
keys are hyphenated** (`"ari-registry"`, `"local-tarball"`, `"zenodo"`, `"gh"`),
which differ from the **underscore module file names**
(`ari_registry.py`, `local_tarball.py`, `zenodo.py`, `gh.py`). Both the dispatch
keys and the four backend modules are live-by-string. The `004`/index shorthand
"`ari_registry/local_tarball/zenodo/gh`" refers to the module names; the dispatch
keys are the hyphenated strings above. (See §9.)

---

## 6. Vendored / submodule seams

| Item | Path | LOC | Description | Adjacent contract | Verdict | Owner |
|---|---|---|---|---|---|---|
| VirSci submodule | `ari-skill-idea/vendor/virsci` (`.gitmodules` → `github.com/kotama7/Virtual-Scientists.git`) | — | Vendored multi-agent idea generator; injected on `sys.path`. `ari-skill-idea/src/server.py` execs vendored `utils/prompt.py`; fallback prompts exist only when the vendor path is unavailable. | Upstream parity (fork = break). | `KEEP` | — |
| PaperBench submodule | `ari-skill-paper-re/vendor/paperbench` (`.gitmodules` → `github.com/openai/preparedness.git`) | — | Vendored PaperBench harness; injected on `sys.path`. | Upstream parity; ORS reproducibility contract. | `KEEP` | — |
| PaperBench bridge | `ari-skill-paper-re/src/_paperbench_bridge.py` | 2376 | Re-exports `SimpleJudge`/`TaskNode` from the vendored submodule **with no local fallback**. The "duplication" is intentional vendoring, not copy-paste drift. Size is a decomposition target, not a legacy one. | Upstream parity; ORS contract. | `KEEP` (route size to 010/016, not legacy) | 010 |

**Grounding.** `cat .gitmodules` confirms both submodule declarations and URLs.
`wc -l _paperbench_bridge.py` → 2376.

---

## 7. Config-triple seam (record only; owned by 003)

**There is NO `sonfigs/` directory.** The confusable trio (all real, all distinct
roles) — the merge/clarification is **003's** job; 002 only records the seam:

| Path | Role | Key contents / LOC | Verdict | Owner |
|---|---|---|---|---|
| `ari-core/ari/config/` | Python **code** | `finder.py` (**145** LOC, workflow/profile YAML discovery), `__init__.py` (**628** LOC Pydantic models + `ARI_*` env glue + `auto_config`), `README.md` | `KEEP` / `REVIEW_REQUIRED` (naming clarity via shim) | 003 |
| `ari-core/ari/configs/` | packaged **default data** + loader | `_loader.py` (**58** LOC, `FilesystemConfigLoader`), `defaults.yaml` (only `models.lineage_decision_default`), `model_prices.yaml`, `README.md` | `KEEP` / `REVIEW_REQUIRED` | 003 |
| `ari-core/config/` | shipped **rubric/profile/workflow data** | `default.yaml`, `workflow.yaml`, `profiles/`, `paperbench_rubrics/` (4), `reviewer_rubrics/*.yaml` (23 venues), `README.md` | `KEEP` | 003 |

**Adjacent contract.** `ari/config/` and `ari/configs/` are **load-bearing import
paths** re-exported through `ari.public.config_schema` — renaming breaks every
internal import and must ship a compatibility shim. YAML key paths + the
`finder.find_workflow_yaml` 4-tier precedence are config-format contracts.
The two unrelated "defaults" files (`config/default.yaml` vs `configs/defaults.yaml`)
are a discoverability seam, not a duplicate to delete.

---

## 8. Verified negatives (restated — stop chasing ghosts)

| Skeleton claim | Verified reality (live tree) | Evidence |
|---|---|---|
| `sonfigs/` directory | **Does not exist.** `find -iname '*sonfig*'` matches only the planning-doc filename `docs/refactoring/subtasks/003_consolidate_config_configs_sonfigs.md` — **no directory**. | `find` output |
| top-level `pyproject.toml` | **Does not exist** (`ls pyproject.toml` → "No such file or directory"). `ari-core/pyproject.toml` is the core manifest — by design. | `ls` |
| committed `node_modules/` | **NOT tracked.** `git ls-files \| grep -c node_modules` → **0**. Ignored at `.gitignore:112,113`; exists only as a working install. | `git ls-files` |
| tracked `__pycache__/` / `.pyc` | **NOT tracked.** `git ls-files \| grep -c __pycache__` → **0**. On-disk-only clutter. | `git ls-files` |
| tracked `report/scripts/.venv/` | **NOT tracked.** `git ls-files report/scripts/.venv \| wc -l` → **0**. Local tooling env only. | `git ls-files` |
| tracked runtime storage | **NONE tracked.** `git check-ignore checkpoints workspace` → both ignored; `git ls-files` under them is empty ⇒ any later consolidation has **no git-tracking migration cost**, only on-disk / back-compat concerns. | `git check-ignore` |

---

## 9. Reconciliation vs `004_legacy_obsolete_inventory.md`

Each `004` finding mapped to **confirmed** / **moved** (line drift) / **resolved** /
**superseded**, plus new items `004` missed.

| 004 § | Finding | Status vs live tree | Note |
|---|---|---|---|
| 0 | Verified negatives (node_modules / egg-info / sonfigs) | **confirmed** | Restated in §8. |
| 1.1 | Empty root `checkpoints/` + `default.yaml` root path | **confirmed / moved** | `auto_config` default now grounded at `config/__init__.py:592` (004 cited `:588-592`; auto_config def is `:575`). default.yaml:14,39 confirmed. |
| 1.2 | 7 stale staging dirs | **confirmed** | Same 7 timestamps; all empty. |
| 1.3 | Stray `workspace/bundle.tar.gz` | **confirmed** | 9026 bytes, mtime May 5. |
| 1.4 / 1.5 | `__pycache__` / report venv untracked | **confirmed** | git counts 0. |
| 2 / 2.1 | `.gitignore` duplicate/defensive lines | **confirmed (not re-verified line-by-line here)** | `.gitignore` hygiene is out of 002's read set; `004` owns the detail — routed to 002-series hygiene. |
| 3.1 | `_deprecation.py` (63 LOC) `KEEP` | **confirmed** | 63 LOC. |
| 4.1 | PaperBench bridge + submodule `KEEP` | **confirmed** | 2376 LOC; `.gitmodules` confirmed. |
| 4.2 | VirSci submodule `KEEP` | **confirmed** | `.gitmodules` confirmed. |
| 4.3 | Two ReAct loops | **confirmed / moved** | 1630 / 442 confirmed. **Correction:** sole direct importer is `stage_runner.py:143/162/278`; `orchestrator.py:690`, `builder.py:400`, `api_workflow.py:252` reference it in **comments only**. `004`/§5 implied 4 importers. Owner reassigned to **011** (004 said 016). |
| 4.4 | Two MCP idioms | **confirmed** | 10 vs 4 confirmed. Owner reassigned to **010** (004 said 016). |
| 4.5 | Dormant `react:` stage path | **confirmed** | `stage_runner.py:51 _run_react_stage`; `grep 'react:' config/` → empty; orchestrator fork `orchestrator.py:691`. |
| 5.1 | `WIZARD_ROUTES` dead dict | **confirmed** | `api_wizard.py:30`, zero readers. |
| 5.2 | `schemas.load()` no importer | **confirmed** | `schemas/__init__.py:11`; only README mentions it. |
| 5.3 | `server:main` in 2 skills | **confirmed** | replicate:27, paper-re:29. |
| 5.4 | Empty `ari/__init__.py` | **confirmed** | 0 bytes. |
| 5.5 | `ari.public` no top-level exports | **confirmed** | 27 LOC docstring-only. |
| 6 | config/configs/config trio (no sonfigs) | **confirmed / moved** | finder.py = **145** LOC (004/§5 said 146). |
| 7.1 / 7.2 | `mcp.json` drift + version skew | **confirmed (not re-counted here)** | Owned by 010 (ST-10-1/2); recorded, not re-derived (defer to 001/010). |
| 8.1 | Dangling `docs/_archive` links | **confirmed** | ≥10 live doc refs; §3.4. |
| 8.2 | `ARI_AGENT_ENV_PATH` `~/.ari` doc contradiction | **confirmed (code path unconfirmed)** | Docs-only; owner 013/017. Code fallback not verified in this pass. |
| 9.1 | `cli/lineage.py` misleading name + core→viz edge | **carried forward** | Not re-derived here; recorded as an ADAPT seam owned by 007/008 (008 ST-8-6 flags the core→viz inversion). |

**Line/LOC drifts recorded (live tree wins):**
1. `migrations/v05_to_v07/` dir total = **162** LOC (18+36+29+79), not the "170"
   in subtask §5; the three non-`__init__` files total **144**.
2. `ari-core/ari/config/finder.py` = **145** LOC, not 146.
3. `react_driver` has **one** direct importer (`stage_runner.py`), not four; the
   other three references are comments.
4. publish `_load_backend` **dispatch keys are hyphenated** (`ari-registry`,
   `local-tarball`), distinct from the underscore backend module names.
5. `auto_config` workspace-checkpoints default resolves at `config/__init__.py:592`
   (def at `:575`), vs `004`'s "`:588-592`".

**New / sharpened items 004 under-specified:** the precise `_load_backend` dispatch
strings vs module names (§5); the single-importer correction for `react_driver`
(§2.1); the owner reassignment of the MCP-idiom and ReAct seams to 010/011 per the
live subtask index.

---

## 10. Summary roll-up

### 10.1 Count by verdict (primary verdict per row; dual-tagged rows counted under the leading verdict)

| Verdict | Count | Items |
|---|---|---|
| `KEEP` | 9 | `_deprecation.py`; 4 migration files; VirSci submodule; PaperBench submodule; PaperBench bridge; config-trio (3 dirs counted as the trio KEEP) |
| `ADAPT` | 3 | `run_pipeline` (canonical); empty `ari/__init__.py` (additive); `ari.public/__init__.py` (additive) |
| `MERGE` | 3 | two ReAct loops; two pipeline runners; (rubric handling — MERGE/REVIEW) |
| `MOVE_TO_LEGACY` | 1 | root `checkpoints/` (empty on-disk dir) |
| `DELETE_CANDIDATE` | 4 | `WIZARD_ROUTES`; `workspace/staging/` dirs; `workspace/bundle.tar.gz`; root `checkpoints/` (on-disk) |
| `REVIEW_REQUIRED` | 6+ | two MCP idioms; scattered rubric handling; `schemas.load()`; `server:main` scripts; `default.yaml`↔`auto_config`; `docs/_archive` links; `ARI_AGENT_ENV_PATH` doc |

*(Several rows carry a compound verdict, e.g. root `checkpoints/` is
`MOVE_TO_LEGACY`/`DELETE_CANDIDATE`(dir) + `REVIEW_REQUIRED`(config); the table
above lists each under its leading tag. No row is tagged "deprecated".)*

### 10.2 Top duplicate seams by LOC-at-risk

| Rank | Seam | LOC-at-risk | Owner |
|---|---|---|---|
| 1 | Two ReAct loops (`loop.py` 1630 + `react_driver.py` 442) | 2072 | 011 |
| 2 | PaperBench bridge (vendored, KEEP — size only) | 2376 | 010/016 |
| 3 | Two pipeline runners (`run_pipeline` region ~913 + `_run_pipeline` thread target) | ~900+ | 012 |
| 4 | Two MCP idioms (10 FastMCP vs 4 low-level `Server`) | 14 server.py files | 010 |
| 5 | Scattered rubric handling (replicate 5 files + paper-re 2 + paper + core evaluator 3) | ~11 files | 010/009/003 |

### 10.3 Sanity gates (baseline, this report adds only Markdown)

- `python -m compileall ari-core/ari` → **exit 0** (no `.py` touched).
- `ruff check ari-core` → **661 errors** (341 `F401`, 358 fixable) — unchanged
  baseline; this report adds no Python.
- `pytest -q` → **delegated to the orchestrator** (run centrally, not here).

---

## 11. Retirement Condition

This report is a **temporary planning/inventory artifact** under
`docs/refactoring/reports/`. It may be archived or deleted (`git rm`) only after
**all** of the following are verified against primary sources — never on
assumption:

1. Subtask **002**'s §13 Acceptance Criteria are met and the implementing PR is
   merged into `main`.
2. `docs/refactoring/007_subtask_index.md` marks subtask **002** as DONE.
3. Its consuming subtask **016** (and the 053→057 chain that ingests the
   "do NOT statically delete" allow-list in §5) has either completed or folded the
   conclusions worth keeping into permanent documentation.

Until every condition above is confirmed, this report is **KEEP**. See the
canonical policy in `docs/refactoring/007_subtask_index.md`
("Document Retirement Policy").
