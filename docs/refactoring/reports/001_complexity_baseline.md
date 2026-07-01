# 001 — Empirical Complexity & Dependency Baseline (Census)

> **Artifact of subtask 001** (`docs/refactoring/subtasks/001_measure_complexity_and_dependencies.md`).
> **PLANNING/MEASUREMENT ONLY — no runtime code, config, prompt, workflow, or
> frontend was modified.** This report and its sibling data files under
> `docs/refactoring/reports/` are the only things produced. Every number below was
> captured from primary sources (`git ls-files` + `wc -l`, `ruff`, `python -m
> compileall`, stdlib `ast`); nothing is estimated. Where a tool does not exist,
> the value is written `unmeasured (no tool installed)` — never guessed.

## 0. Provenance (determinism stamp)

| Field | Value |
|---|---|
| Repo root | `/home/t-kotama/workplace/ARI` |
| Git SHA (`git rev-parse HEAD`) | `2a20bd94a06abb6013e2e85be92f978caa916df2` |
| Branch | `whole_refactoring` |
| Ruff version | `ruff 0.15.2` |
| Python version | `3.13.2` |
| Generated (UTC) | `2026-07-01T10:57:42Z` |
| Ruff config present? | **No** — no `ruff.toml`, no `.ruff.toml`, no `[tool.ruff]` in `ari-core/pyproject.toml`; therefore McCabe `C901` is **inactive**. |
| `radon` installed? | **No** — `python -c "import radon"` → `ModuleNotFoundError`. |

## 1. Artifact index (each file → exact generating command)

All artifacts live under `docs/refactoring/reports/`. Each carries its own header
line repeating command + versions + SHA + UTC timestamp so subtasks **025**
(`scripts/check_complexity.py`) and **031** (`scripts/generate_quality_report.py`)
can re-run and diff deterministically.

| Artifact | Generating command | Format |
|---|---|---|
| `001_complexity_baseline.md` | this narrative (hand-assembled from the commands below) | Markdown |
| `loc_census.csv` | `python docs/refactoring/reports/_capture_baseline.py` (`git ls-files` + `wc -l` semantics) | CSV |
| `ruff_baseline.txt` | `ruff check ari-core --statistics` | text |
| `ruff_baseline_full.txt` | `ruff check . --statistics` | text |
| `compileall.txt` | `python -m compileall -q ari-core` / `… ari-skill-* (14)` / `… .` | text |
| `import_edges.json` | `python docs/refactoring/reports/_capture_baseline.py` (stdlib `ast`) | JSON |
| `fan_in.csv` | `python docs/refactoring/reports/_capture_baseline.py` (stdlib `ast`) | CSV |
| `_capture_baseline.py` | — (the one-off helper itself; **NON-CANONICAL**, not promoted to `scripts/`) | Python |

> `_capture_baseline.py` is a labeled one-off measurement helper kept **beside** the
> artifacts. It is **not** the enforced checker; subtask 025 owns the canonical
> `scripts/check_complexity.py`. It uses stdlib only (`ast`, `wc -l` semantics via
> byte-count of `\n`) — no `radon`, no `pydeps`, no installed dependency.

## 2. LOC census

Source of truth: `loc_census.csv` (per-file rows) + the rollups here. Files are the
git-tracked set only (so `node_modules/`, `__pycache__/`, `.venv/` are auto-excluded
— `git ls-files ari-core/ari/viz/frontend/node_modules/` returns **0**). **Tests are
a separate cohort** and are excluded from every production size band so
`tests/test_server.py` (1844) et al. never swamp a production gate.

### 2.1 Cohort totals

| Cohort | Files | LOC |
|---|---:|---:|
| **core-prod** (`ari-core/ari/**/*.py`) | 139 | **30,277** |
| core-test (`ari-core/tests/**/*.py`) | 110 | 37,543 |
| skills total (`ari-skill-*/src/**/*.py`, 14 pkgs) | 61 | **25,495** (≈25.5k) |
| frontend (`ari-core/ari/viz/frontend/src/**/*.{ts,tsx}`) | 76 | 18,823 |

### 2.2 Core per-directory rollup (`ari-core/ari/`, 30,277 LOC)

| Subdir | Files | LOC | Notes |
|---|---:|---:|---|
| `viz/` | 27 | **8,131** | **27%** of core — dashboard backend |
| `pipeline/` | 17 | 3,900 | `orchestrator.py` 913 |
| `agent/` | 9 | 3,303 | `loop.py` **1630** (ReAct loop) |
| `orchestrator/` | 10 | 2,996 | `bfts.py` 845 |
| `cli/` | 8 | 2,582 | `bfts_loop.py` 911, `run.py` 575 |
| (top-level `.py`) | 12 | 2,796 | incl. `ari/__init__.py` = **0 bytes** |
| `evaluator/` | 3 | 1,261 | `llm_evaluator.py` 723 |
| `llm/` | 4 | 1,234 | `cli_server.py` 919 |
| `config/` | 2 | 773 | code locator; `__init__.py` 628 |
| `publish/` | 6 | 756 | |
| `clone/` | 7 | 665 | |
| `registry/` | 5 | 511 | HTTP artifact registry (FastAPI) |
| `mcp/` | 2 | 495 | `client.py` 484 |
| `memory/` | 6 | 343 | |
| `migrations/` | 5 | 170 | |
| `public/` | 9 | **148** | frozen contract surface (§6.2) |
| `configs/` | 2 | 69 | packaged data + `_loader.py` |
| `protocols/` | 2 | 63 | |
| `prompts/` | 2 | 61 | `_loader.py` + `.md` templates |
| `schemas/` | 1 | 20 | |

Subdir subtotal = 27,481; top-level `.py` = 30,277 − 27,481 = **2,796**. Total **30,277**. ✔

### 2.3 Size bands (data-derived anchors, RECORDED — not enforced by this subtask)

Band labels: `warn >500`, `review >800`, `split >1200`. Counts **excluding the
core-test cohort** (production Python + frontend only): **split = 6**, **review = 14**,
**warn = 21**.

**`split` band (>1200) — 5 production Python + 1 frontend (matches the plan's tiering):**

| Cohort | Path | LOC |
|---|---|---:|
| skill:paper | `ari-skill-paper/src/server.py` | 2956 |
| skill:transform | `ari-skill-transform/src/server.py` | 2465 |
| skill:paper-re | `ari-skill-paper-re/src/_paperbench_bridge.py` | 2376 |
| core-prod | `ari-core/ari/agent/loop.py` | 1630 |
| skill:paper-re | `ari-skill-paper-re/src/server.py` | 1395 |
| **frontend** | `ari-core/ari/viz/frontend/src/components/Results/resultSections.tsx` | **1590** |

Tests that exceed 1200 (kept in the separate `core-test` cohort, NOT a production
offender): `test_server.py` 1844, `test_gui_errors.py` 1650, `test_workflow_contract.py` 1606.

`ari-core/ari/viz/routes.py` at **1197** sits just under the split line (banded
`review`); it is the largest single `viz` backend file and a known refactor hotspot.

## 3. Ruff lint baseline (FROZEN before any `--fix`)

### 3.1 `ari-core` cohort — `ruff check ari-core --statistics` (`ruff_baseline.txt`)

**661 findings total; 358 auto-fixable.** Full breakdown (verbatim):

| Count | Rule | Description |
|---:|---|---|
| **341** | `F401` | unused-import |
| **135** | `E402` | module-import-not-at-top-of-file |
| 54 | `E702` | multiple-statements-on-one-line-semicolon |
| 39 | `F841` | unused-variable |
| 37 | `E701` | multiple-statements-on-one-line-colon |
| 28 | `F541` | f-string-missing-placeholders |
| 11 | `E741` | ambiguous-variable-name |
| 8 | `F811` | redefined-while-unused |
| 7 | `E401` | multiple-imports-on-one-line |
| 1 | `E731` | lambda-assignment |

Ratchet policy (RECORDED for 025/031, not enforced here): the **661** number may only
**decrease**; no new finding class may appear. A one-shot `ruff --fix` would clear
**358** (leaving ~303 real-signal findings), but that is a **deferred supervised
implementation pass** — this subtask must NOT run `--fix`, so 661 stays the frozen
pre-fix anchor. `F401` (341) + `E402` (135) = 476 ≈ 72% of findings are shallow
import hygiene.

### 3.2 Broader cohort — `ruff check . --statistics` (`ruff_baseline_full.txt`)

**1199 findings total; 544 auto-fixable.** This is a **NEW, distinct measurement**
(adds `ari-skill-*`, `scripts/`, and `report/` tooling that the historical
`ari-core`-only pass never linted). It also surfaces `import *` fallout absent from
core (`F405` 164, `F403` 7) and `I001` unsorted-imports (24). **Downstream tooling
must not read the 1199 − 661 delta as a regression** — the cohorts differ. Ruff
emitted one benign warning: rule `UP038` was removed upstream (no effect).

## 4. Compile / syntax health (`compileall.txt`)

Smoke gate — all three scopes byte-compile with **exit code 0** and zero diagnostics:

| Command | Exit code |
|---|---:|
| `python -m compileall -q ari-core` | 0 |
| `python -m compileall -q ari-skill-*` (14 pkgs) | 0 |
| `python -m compileall -q .` (whole repo) | 0 |

**RESULT: PASS.** Note: `compileall` (and `ruff`) do **not** detect import cycles — a
file with a deferred/circular import still byte-compiles. Cycle detection is done
separately in §5 via an `ast` edge graph + Tarjan SCC.

## 5. Dependency graph census (internal `ari` import edges)

Method: stdlib `ast` scan of every git-tracked `ari-core/ari/**/*.py`, resolving
`Import`/`ImportFrom` to the nearest **internal** `ari.*` module (relative imports
resolved by package level; `from ari.x import y` resolved to `ari.x.y` when that is a
real module, else `ari.x`). Cross-package targets are excluded here and recorded in
§6. Data: `import_edges.json` (edge list + cycle report) and `fan_in.csv`.

- **Modules:** 139. **Internal directed edges:** 288. **Parse errors:** 0.

### 5.1 Fan-in leaders (blast radius = in-edges)

| Module | fan_in | fan_out | in SCC of size |
|---|---:|---:|---:|
| `ari.paths` | **26** | 0 | 1 |
| `ari.viz.state` | 20 | 1 | 1 |
| `ari.config` | 14 | 1 | 1 |
| `ari.viz.api_state` | 11 | 8 | **8** |
| `ari.llm.client` | 9 | 2 | 1 |
| `ari.orchestrator.node` | 7 | 0 | 1 |
| `ari.pipeline` | 7 | 6 | 2 |
| `ari.prompts` | 7 | 1 | 1 |
| `ari.mcp.client` | 6 | 1 | 1 |
| `ari.viz.api_settings` | 6 | 2 | 1 |

`ari.paths` (fan-in 26, the `PathManager` module re-exported verbatim by
`ari.public.paths`) is the single highest-blast-radius internal module — consistent
with it being a checkpoint/path contract surface (§6). Any change there ripples to 26
modules.

### 5.2 Import cycles — **cycles DO exist** (Tarjan SCC over the edge list)

Cycle detection **ran**. **5 multi-node strongly-connected components** were found
(19 modules total); **no self-loops**:

| SCC | Size | Members |
|---|---:|---|
| SCC1 | 8 | `viz.api_state ↔ checkpoint_api, checkpoint_finder, checkpoint_lifecycle, ear, file_api, node_work_api, state_sync` |
| SCC2 | 4 | `cli ↔ cli.commands, cli.projects, cli.run` |
| SCC3 | 3 | `migrations.v05_to_v07.node_reports ↔ orchestrator.node_report, orchestrator.node_report.legacy_reconstruct` |
| SCC4 | 2 | `pipeline ↔ pipeline.orchestrator` |
| SCC5 | 2 | `viz.api_paperbench ↔ viz.api_paperbench_worker` |

Several cycles (SCC2, SCC4) are the common **package `__init__` re-export ↔ submodule**
pattern; SCC1 is a genuine tangle across the `viz` checkpoint/state handlers. All are
recorded here as data for later phases (Phase 7 orchestration / Phase 11 viz backend),
not fixed by this subtask.

### 5.3 `E402` as the deferred-import (cycle-hack) proxy

`E402` = **135** (module-import-not-at-top-of-file), the standard workaround for
circular imports. Its per-file concentration **corroborates** the SCCs found
independently in §5.2:

| File | E402 count | Note |
|---|---:|---|
| `ari/viz/server.py` | 26 | viz backend bootstrap |
| `ari/viz/api_state.py` | 15 | **member of SCC1** (the 8-node viz cycle) |
| `ari/llm/cli_server.py` | 12 | |
| `ari/viz/api_experiment.py` | 9 | |
| `ari/container.py` | 7 | |
| `ari/cli/__init__.py` | 6 | **member of SCC2** (the cli cycle) |
| `ari/cli/run.py` | 5 | **member of SCC2** |

The overlap between the top-`E402` files and the SCC members is the empirical link the
subtask asked for: deferred imports cluster exactly where the graph shows cycles.

## 6. Cross-package & contract edges (annotated facts — cross the `ast`-scannable boundary)

These edges leave the `ari-core/ari` graph and are recorded as facts, not tagged.

1. **`ari-core → ari_skill_memory` (the one core→skill dependency).** The first and
   only core→skill edge; deliberately **absent** from `ari-core/pyproject.toml`
   `dependencies` (documented in the manifest comment, editable-installed by
   `setup.sh`; `refactor-guards.yml` installs `ari-skill-memory` before `ari-core`).
   `ari-core` imports `ari_skill_memory.backends.get_backend` at ~13 sites
   (`memory_cli.py`, `cli/run.py`, `cli/commands.py`, `pipeline/orchestrator.py`,
   `pipeline/verified_context.py`, `agent/loop.py`, several `viz/*.py`,
   `memory/{letta_client,auto_migrate}.py`). The edge is bidirectional:
   `ari_skill_memory`'s `letta_backend.py` lazily imports `ari.public.cost_tracker`.
2. **`ari.public.*` contract surface (148 LOC, 8 modules + `__init__`).** The only
   surface `ari-skill-*` may import: `claim_gate, config_schema, container,
   cost_tracker, llm, paths, run_env, verified_context`. `ari/public/__init__.py` is
   **docstring-only** (re-exports nothing at package level), so
   `from ari.public import cost_tracker` works but `from ari.public import <symbol>`
   does not — an inventory fact, not fixed here.
3. **`viz` backend ↔ frontend `services/api.ts` (863 LOC).** The React client
   hard-codes ~130 REST endpoint paths served by the stdlib `http.server`
   `if/elif` dispatch in `viz/routes.py` (1197) + the `api_*.py` handlers, plus the
   single WebSocket `{"type":"update",...}` message on `port+1`. This coupling has no
   automated guard today (subtask 030's `check_viz_api_schema.py` is net-new).
4. **MCP client → 14 skill servers.** `ari/mcp/client.py` (`MCPClient`) discovers
   tools into a **flat single global namespace** (`_tool_registry: tool_name →
   skill`), so a cross-skill tool-name collision silently clobbers (last-skill-wins).
   Two divergent server idioms coexist: 10 skills use FastMCP (`@mcp.tool`, return
   strings), 4 use the low-level `mcp.server.Server` (coding, evaluator, hpc,
   orchestrator) returning `list[TextContent]`. The `{"result"|"error"}` envelope and
   the `mcp__<skill>__<tool>` fully-qualified naming are the frozen contract.

## 7. Inventory clarifications (recorded facts)

- **`sonfigs/` DOES NOT EXIST.** `find . -type d -iname '*sonfig*'` returns nothing;
  `ls -d sonfigs` → "No such file or directory". The only filesystem hit for
  `*sonfig*` is a **planning-doc filename**
  (`docs/refactoring/subtasks/003_consolidate_config_configs_sonfigs.md`), not a
  directory. The master-prompt "config/configs/sonfigs" is a hypothesized typo.
- **The real confusable trio** (all present, all distinct roles):
  `ari-core/ari/config/` = Python **code** (locator: `finder.py` + 628-LOC
  `__init__.py`); `ari-core/ari/configs/` = packaged **default data** (`defaults.yaml`,
  `model_prices.yaml`, `_loader.py`); `ari-core/config/` = shipped **rubric/profile/
  workflow data** (`default.yaml`, `workflow.yaml`, `profiles/`, `paperbench_rubrics/`,
  `reviewer_rubrics/`). Two unrelated "default(s)" files coexist (`configs/defaults.yaml`
  vs `config/default.yaml`).
- **`ari-core/ari/__init__.py` is 0 bytes** (no `ari.__version__`; version lives only
  in the manifest). Recorded, not fixed.
- **Root `checkpoints/` (empty, legacy) coexists with `workspace/checkpoints/`,
  `workspace/experiments/`, `workspace/staging/`.** All runtime storage is
  `.gitignore`d (`git ls-files` returns 0 tracked files under any), so any later
  consolidation has **zero git-tracking migration cost**.

## 8. Cyclomatic complexity — `REVIEW_REQUIRED` (no number fabricated)

**CC is `unmeasured (no tool installed)`.** `radon` is not installed and ruff's McCabe
`C901` is inactive (no `[tool.ruff]` config anywhere). No CC value is estimated. The
engine choice is a **`REVIEW_REQUIRED`** decision handed to subtasks **002**
(methodology) and **025** (`scripts/check_complexity.py`):

- **Option A — install `radon`** (true cyclomatic complexity + maintainability index),
  but that adds a dependency (a `REVIEW_REQUIRED` footprint change, out of scope here).
- **Option B — enable ruff `C901`** (McCabe threshold) via a new `[tool.ruff]` config,
  reusing the already-present ruff 0.15.2 with no new dependency.

Until then, the LOC bands in §2.3 are the only size signal, and they are **labels for
downstream consumption, not CI gates in this subtask**.

## 9. Idempotence check (primary acceptance signal)

Verified. The files **attributable to subtask 001** are exactly the 8 §9 artifacts,
all under `docs/refactoring/reports/`: `001_complexity_baseline.md` (this report),
`loc_census.csv`, `ruff_baseline.txt`, `ruff_baseline_full.txt`, `compileall.txt`,
`import_edges.json`, `fan_in.csv`, and the non-canonical `_capture_baseline.py`. This
subtask created **no** `scripts/*.py`, installed **no** dependency, and mutated **no**
source/config/workflow/prompt/frontend file; `ruff --fix` was never run. The reports
dir's `README.md` and `orchestration_status.md` were **not** touched by this subtask
(see note below).

**Concurrent/pre-existing entries (NOT products of subtask 001, recorded for
transparency):** the census ran alongside other parallel sessions. At capture time
`git status --porcelain` additionally showed, all **outside** subtask 001's scope:
`docs/refactoring/HANDOFF_PROMPTS.md` (pre-existing at session start),
`docs/refactoring/reports/002_legacy_obsolete_duplicate_inventory.md` and
`…/045_github_workflow_inventory.md` (sibling subtasks 002/045), and a modification
to `docs/refactoring/reports/orchestration_status.md`. That modification is the
**orchestrator's own** edit (it recorded its central `pytest` run and marked subtask
002 DONE) — verified by `git diff`, which touches only the status table and pytest
line, none of it authored here. No source tree, `scripts/`, or dependency was altered
by any of the above.

## 10. §13 Acceptance-criteria self-check

| # | Criterion | Status |
|---|---|---|
| 1 | All §9 artifacts exist, each header-stamped (cmd + versions + SHA + UTC) | **PASS** |
| 2 | `loc_census.csv` reproduces core=30,277, viz=8,131 (27%), public=148; 5 prod-py + 1 frontend banded `split` | **PASS** |
| 3 | `ruff_baseline.txt` = 661 / 358 fixable, F401=341, E402=135; `ruff_baseline_full.txt` present + labeled broader cohort | **PASS** |
| 4 | `import_edges.json` + `fan_in.csv` exist; cycle detection ran (5 SCCs recorded); E402=135 cross-referenced; 4 cross-package edges documented | **PASS** |
| 5 | CC stated `unmeasured (no tool installed)`; radon-vs-`C901` recorded `REVIEW_REQUIRED`; no CC fabricated | **PASS** |
| 6 | `sonfigs/` asserted absent; `config/`(code) vs `configs/`(data) vs `config/`(rubric) trio documented | **PASS** |
| 7 | `python -m compileall .` passes (exit 0); pytest run centrally by orchestrator (not run here) | **PASS** (compileall) |
| 8 | `git status --porcelain` shows no modification outside `docs/refactoring/reports/` | **PASS** |
| 9 | No `scripts/*.py` checker created; no dependency installed; no source mutated | **PASS** |

> Criterion 7 note: this subtask deliberately did **not** run the full pytest suite —
> the orchestrator runs it centrally. `compileall` (the artifact-bearing half) passed.

## 11. Retirement Condition

This report is a temporary planning artifact. It may be archived/deleted (`git rm`)
only after subtask 001's §13 Acceptance Criteria are met, the implementing PR is
merged into `main`, and `docs/refactoring/007_subtask_index.md` marks subtask **001**
as DONE — verified against primary sources, never on assumption.
