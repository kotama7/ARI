# Subtask 001: Measure Complexity And Dependencies

- **Subtask ID:** 001
- **Phase:** Phase 1 — Measurement and Inventory
- **Classification:** `KEEP` (measurement only; no target code is changed, only new report/data artifacts are added)
- **Changes runtime code:** **No** (see Section 16)
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`)

> **Planning-phase notice.** This document is a plan for a *future* coding session. It changes no runtime code, imports, prompts, configs, workflows, frontend, or directory names. The only file created by authoring this plan is this `.md` itself. Everything under "Concrete Work Items" and "Files Expected to Change" describes what the **implementer of subtask 001** will do in a later, separate session.

---

## 1. Goal

Produce the **canonical empirical baseline census** for the ARI refactoring effort: a committed, reproducible snapshot of (a) per-file / per-directory line counts, (b) the current `ruff` lint baseline, (c) syntax/compile health, and (d) the internal + cross-package **dependency graph** (import edges, fan-in/fan-out, and cycle proxies). This baseline is the shared factual ground that every downstream refactoring subtask measures its progress against, and it is the direct input to:

- **025 — `add_complexity_checker_script`** (`scripts/check_complexity.py`): the checker reproduces and enforces the LOC/complexity numbers frozen here.
- **031 — `add_quality_report_generator`** (`scripts/generate_quality_report.py`): the report generator aggregates these baseline artifacts.

The deliverable is a set of report + machine-readable data files under `docs/refactoring/reports/` (currently an empty workspace directory). No `scripts/`, no `ari/`, no skill, no frontend, and no config file is modified.

**Explicit non-actions of this subtask** (owned by later subtasks — do not do them here):
- Do **not** run `ruff check --fix` (would mutate source; deferred to a supervised implementation pass).
- Do **not** create `scripts/check_complexity.py` (owned by 025).
- Do **not** create `scripts/analyze_references.py` (owned by 020's reference-graph chain) or `scripts/check_dead_code.py` (dead-code chain).
- Do **not** install `radon` or add any dependency (dependency selection is a `REVIEW_REQUIRED` decision recorded, not executed, here).

---

## 2. Background

The master plan (`docs/refactoring/000_master_refactoring_plan.md`) and the complexity *methodology* plan (`docs/refactoring/002_complexity_measurement_plan.md`) both assert that **cyclomatic complexity is currently entirely unmeasured** (radon not installed; `ruff` runs with **no `[tool.ruff]` config** anywhere, so the McCabe `C901` rule is inactive) and that no complexity tooling exists (`scripts/check_complexity.py` is absent). Subtask **002** is the *methodology* document (metrics, thresholds, ratchet policy); subtask **001** — this one — is the *empirical census* that actually runs the available measurements once and freezes the numbers as artifacts.

The relationship is explicit in `002_complexity_measurement_plan.md` §11: subtask 002 declares 001 to be the upstream "repository inventory / baseline census" that 002 *measures over*, consuming 001's exclusion set, the `config`/`configs`/no-`sonfigs` clarification, and the "14-skill / `viz`-is-27 %" shape. Formally, however, the provided dependency graph lists **only** `001 -> 025` and `001 -> 031`; there is **no** `001 -> 002` edge — 002 is a separate root that *references* 001's inventory informationally (see Section 15).

The ground-truth measurement pass already recorded live numbers (reproduced in Section 6). This subtask's job is to **capture those numbers as versioned, reproducible artifacts** (with the exact commands that generated them) so downstream automation is deterministic rather than relying on prose in a planning doc.

---

## 3. Scope

In scope for the subtask implementation:

1. **LOC census** — per-file and per-directory `wc -l` totals for:
   - `ari-core/ari/**/*.py` (production Python; 30,277 LOC total, 19 subdirs + top-level `.py`).
   - `ari-core/tests/**/*.py` (recorded **separately**; tests are the heaviest files in core and must not be mixed into production gates).
   - Each of the 14 `ari-skill-*/src/**/*.py` packages (production; ≈25.5k LOC total).
   - `ari-core/ari/viz/frontend/src/**/*.{ts,tsx}` with `node_modules/` **excluded**.
2. **Ruff lint baseline** — freeze the output of `ruff check ari-core --statistics` (661 findings today) and, as a new/complementary measurement, `ruff check .` (which additionally scans `ari-skill-*`, `scripts/`, report tooling — a cohort *not* individually linted in the earlier pass; label this an explicit new census, not a re-run).
3. **Compile/syntax health** — capture `python -m compileall .` result as a smoke gate.
4. **Dependency graph census** — build an internal import-edge graph over `ari-core/ari` via a stdlib `ast` scan (resolving `Import`/`ImportFrom` to internal modules), compute **fan-in (blast radius)** and **fan-out** per module, and record the known cross-package edges: the single `ari-core -> ari_skill_memory` core→skill dependency, the `ari.public.*` contract surface, the `viz` backend ↔ frontend `services/api.ts` contract, and the MCP client→server topology. Record `E402` (135) as the cycle-hack proxy and note that neither `compileall` nor `ruff` detects cycles.
5. **Inventory clarifications** — record the config trio (`ari/config/` code vs `ari/configs/` packaged data vs top-level `config/` rubric data) and state explicitly that **no `sonfigs/` directory exists** (the master-prompt "sonfigs" is a hypothesized typo, not present).
6. **Deliverable artifacts** — a baseline report `.md` plus machine-readable data files under `docs/refactoring/reports/`, each stamped with the exact command that produced it and the tool versions (`ruff 0.15.2`, Python `3.13.2`).

Out of scope: everything in Section 4.

---

## 4. Non-Goals

- **No source mutation of any kind.** No `ruff --fix`, no import reordering, no reformatting, no file moves/renames.
- **No new runtime tooling.** No script under `scripts/` is created (25/020/013 own the checkers). Any helper used to build the import graph is a clearly-labeled one-off kept beside the report artifacts, not promoted to `scripts/`.
- **No dependency installation or manifest edit.** `radon` is not installed; `requirements.txt`, `requirements.lock`, and `ari-core/pyproject.toml` are untouched. The radon-vs-`C901` engine choice is a `REVIEW_REQUIRED` item recorded for 002/025, not decided here.
- **No cyclomatic-complexity numbers fabricated.** Because no CC tool exists, CC columns in the baseline are explicitly marked `unmeasured (no tool installed)` — never estimated.
- **No classification decisions.** 001 measures; it does not tag files `KEEP`/`ADAPT`/`MERGE`/etc. (that is later, per-area subtasks). It may record *candidate* observations but assigns no verdicts.
- **No changes to workflows, prompts, configs, checkpoints, or the frontend.**
- **No contract changes.** All surfaces in Section 10 are read-only inputs to the census.

---

## 5. Current Files / Directories to Inspect

All paths are relative to `/home/t-kotama/workplace/ARI`. These are **read-only inputs** to the census.

**Production Python — core (`ari-core/ari/`, 30,277 LOC; per verified subdir totals):**
- `viz/` (8,131 LOC, 27 `.py`) — dashboard backend: `routes.py` (1197), `api_experiment.py` (929), `api_paperbench.py` (813), `api_settings.py` (553), plus `server.py`, `state.py`, `websocket.py`, `checkpoint_*.py`, `api_*.py`, `frontend/`.
- `pipeline/` (3,900) — `orchestrator.py` (913) + stages.
- `agent/` (3,303) — `loop.py` (1630, ReAct loop).
- `orchestrator/` (2,996) — `bfts.py` (845), `lineage_decision.py` (593), `node_report/builder.py` (652).
- `cli/` (2,582) — `bfts_loop.py` (911), `run.py` (575), `commands.py`, `projects.py`, `migrate.py`, `lineage.py`, `__init__.py` (175), `__main__.py`.
- top-level `.py` (2,796) — `checkpoint.py`, `cli_ear.py`, `container.py`, `core.py`, `cost_tracker.py`, `_deprecation.py`, `env_detect.py`, `__init__.py` (**0 bytes / empty**), `lineage.py`, `memory_cli.py`, `paths.py`, `pidfile.py`.
- `evaluator/` (1,261) — `llm_evaluator.py` (723), `dynamic_axes.py` (516).
- `llm/` (1,234) — `cli_server.py` (919).
- `config/` (773) — **code** locator; `__init__.py` is unexpectedly **628 LOC** for a config-*locator*; also `finder.py`, `README.md`.
- `publish/` (756), `clone/` (665), `registry/` (511), `mcp/` (495 — `client.py` 484), `memory/` (343), `migrations/` (170), `public/` (**148** — the frozen contract surface), `configs/` (69 — packaged data + `_loader.py`), `protocols/` (63), `prompts/` (61 — `_loader.py` + `.md` templates), `schemas/` (20).

**Tests (recorded SEPARATELY — heaviest files in core):** `ari-core/tests/test_server.py` (1844), `test_gui_errors.py` (1650), `test_workflow_contract.py` (1606), `test_wizard.py` (1133), `test_settings_propagation.py` (1058), `test_pipeline_e2e.py` (1010).

**Production Python — skills (`ari-skill-*/src/`, ≈25.5k LOC across 14 pkgs):** `paper-re` (5,843; `_paperbench_bridge.py` 2376, `server.py` 1395, `_replicator_agent.py` 730, `_litellm_completer.py` 521), `paper` (4,278; `server.py` 2956), `transform` (3,180; `server.py` 2465), `memory` (2,876; `letta_backend.py` 665), `idea` (1,916; `virsci_runtime.py` 592, `snapshot.py` 549), `replicate` (1,684; `generator.py` 695), `orchestrator` (1,043; `server.py` 1043), `hpc` (1,004; `slurm.py` 527), `evaluator` (983; `server.py` 983), `plot` (802; `server.py` 802), `web` (712; `server.py` 712), `coding` (644; `server.py` 644), `vlm` (355), `benchmark` (175).

**Frontend (`ari-core/ari/viz/frontend/src/`, TS/TSX, `node_modules/` excluded):** `components/Results/resultSections.tsx` (1590), `Wizard/StepResources.tsx` (1160), `Settings/SettingsPage.tsx` (1049), `Workflow/WorkflowPage.tsx` (964), `services/api.ts` (863), `Workflow/workflowNodes.tsx` (770), `Wizard/StepGoal.tsx` (528), `Results/PaperWorkspace.tsx` (519), `Monitor/MonitorPage.tsx` (502).

**Config trio + storage inventory (for the dependency/inventory census):**
- `ari-core/ari/config/` (Python code — locator), `ari-core/ari/configs/` (packaged data: `defaults.yaml`, `model_prices.yaml`, `_loader.py`), `ari-core/config/` (rubric/profile DATA: `default.yaml`, `profiles/{cloud,hpc,laptop}.yaml`, `paperbench_rubrics/`, `reviewer_rubrics/`). **No `sonfigs/` anywhere** (confirmed absent).
- Root `checkpoints/` (empty, legacy) coexisting with `workspace/checkpoints/`, `workspace/experiments/`, `workspace/staging/`.

**Contract-surface inputs (read-only):** `ari-core/pyproject.toml` (console script `ari = ari.cli:app`), `ari-core/ari/public/__init__.py` + submodules, `ari-core/ari/mcp/client.py`, the 14 `ari-skill-*/src/server.py`, `ari-core/ari/viz/routes.py` + `api_*.py`, `ari-core/ari/viz/frontend/src/services/api.ts`.

**Existing tooling to align with (do not modify):** `scripts/docs/check_ref_coupling.py` (reverse import/doc coupling), `scripts/docs/check_doc_sources.py`, `pytest.ini`, `scripts/run_all_tests.sh`.

**Output workspace (currently empty):** `docs/refactoring/reports/`.

---

## 6. Current Problems

The problems below motivate freezing a baseline; they are recorded facts, not tasks for this subtask to fix.

1. **No cyclomatic-complexity data exists.** `radon` is `NOT installed` (`python -c "import radon"` → `ModuleNotFoundError`); `ruff 0.15.2` runs with **no `[tool.ruff]` config** (verified: no `ruff.toml`/`.ruff.toml`, no `[tool.ruff]` in `ari-core/pyproject.toml`), so `C901` is inactive. Complexity is an **unmeasured baseline of zero** — any downstream complexity gate has nothing to ratchet against until a baseline is captured and an engine is chosen.
2. **Large-file concentration.** Five production Python files exceed 1200 LOC (`ari-skill-paper/src/server.py` 2956, `ari-skill-transform/src/server.py` 2465, `ari-skill-paper-re/src/_paperbench_bridge.py` 2376, `ari/agent/loop.py` 1630, `ari-skill-paper-re/src/server.py` 1395); ~15 exceed 800 LOC. One frontend file exceeds 1200 (`resultSections.tsx` 1590); four exceed 800. `viz/` is **27 %** of core (8,131 / 30,277). Without a committed census these hotspots are only known informally.
3. **Ruff findings are large but shallow.** `ruff check ari-core --statistics` = **661 findings, 358 auto-fixable**; **341 are just `F401`** (unused-import) and **135 are `E402`** (module-import-not-at-top). A one-shot `--fix` clears 358, leaving ~303 real-signal findings — but the 661 number must be **frozen before** anyone runs `--fix`, or the baseline is lost.
4. **`E402` × 135 is a cycle-hack proxy.** Deferred imports (import-not-at-top) commonly work around circular imports; neither `compileall` nor `ruff` detects cycles, so the dependency census must build an explicit graph to find them.
5. **Dependency seams are undocumented as data.** The first `ari-core -> ari_skill_memory` core→skill edge (v0.6.0, editable-installed by `setup.sh`, deliberately absent from `pyproject.toml` dependencies), the flat MCP tool namespace (bare snake_case, `MCPClient._tool_registry` global map where cross-skill name collisions silently clobber), and the two divergent MCP server idioms (FastMCP for 10 skills; low-level `mcp.server.Server` for `coding`/`evaluator`/`hpc`/`orchestrator`) exist only as prose — the census turns them into recorded edges.
6. **Empty package surface.** `ari-core/ari/__init__.py` is **0 bytes** (no `__version__`); `ari/public/__init__.py` re-exports nothing (docstring-only) though the README says "import from `ari.public.*`". These are inventory facts to record, not fix.
7. **Cohort gap.** The earlier ruff pass linted **`ari-core` only**; `ari-skill-*`, `scripts/`, and report tooling were not individually linted — the baseline must state its cohort explicitly to avoid false "regressions" later.

---

## 7. Proposed Design / Policy

**Principle: measure with what exists, mutate nothing, make it reproducible.**

1. **Tools used (all already available):** `wc -l` (LOC), `ruff 0.15.2 --statistics` (lint), `python -m compileall` (syntax/import smoke), stdlib `ast` (import-graph scan). `git ls-files` to enumerate tracked files so the census matches version control and auto-excludes `.gitignore`d paths. **No new tool is installed.**
2. **Exclusions (frozen policy):** exclude `__pycache__/`, `node_modules/`, `.venv`/virtualenvs, `*.min.*`, `dist/`/`build/` bundles, and generated files. **Tests are measured but reported in a separate section/column** so `ari-core/tests/test_server.py` (1844) et al. never dominate production gates. Frontend LOC excludes `node_modules/` (vendored/committed — a known hygiene issue owned elsewhere).
3. **Threshold anchors (data-derived, recorded — NOT enforced here):** `>500 warn`, `>800 review`, `>1200 split-required`. These are the *labels* the census applies to each file for downstream 002/025 consumption; 001 does not gate CI on them.
4. **Complexity engine decision = `REVIEW_REQUIRED` (recorded, not executed):** two options — install `radon` (CC + maintainability index) **or** enable `ruff` `C901`. The baseline records CC as `unmeasured (no tool installed)` and hands the choice to 002/025.
5. **Dependency-graph method:** parse every tracked `ari-core/ari/**/*.py` with `ast`, resolve internal `Import`/`ImportFrom` targets to modules within `ari`, emit a directed edge list, and compute per-module fan-in (in-edges = blast radius) and fan-out. Detect cycles via Tarjan SCC over that graph and cross-reference the 135 `E402` hits as the deferred-import proxy. Record the four cross-package edges (core→`ari_skill_memory`, `ari.public.*` surface, `viz`↔`api.ts`, MCP client→14 servers) as annotated facts, since they cross the `ast`-scannable boundary.
6. **Artifact contract:** every produced data file carries a header line with the exact command, `ruff`/`python` versions, git commit SHA, and UTC timestamp, so 025/031 can re-run and diff deterministically. Machine-readable formats: CSV for LOC/fan-in tables, plain text for frozen `ruff --statistics`, JSON for the import edge list.
7. **Idempotence guarantee:** the capture writes only under `docs/refactoring/reports/`; after running, `git status --porcelain` for all paths *outside* `docs/refactoring/reports/` must be empty (proves zero source mutation). This is the primary acceptance signal (Section 13).

---

## 8. Concrete Work Items

1. **Enumerate the tracked file universe.** Use `git ls-files` filtered to `ari-core/ari/**/*.py`, `ari-core/tests/**/*.py`, `ari-skill-*/src/**/*.py`, and `ari-core/ari/viz/frontend/src/**/*.{ts,tsx}`; confirm `node_modules/` and `__pycache__/` are absent from the list.
2. **Capture the LOC census.** Run `wc -l` over each cohort; write `docs/refactoring/reports/loc_census.csv` with columns `path, loc, cohort(core-prod|core-test|skill:<name>|frontend), band(warn|review|split|-)`. Write per-directory rollups (reproducing the 19-subdir + top-level totals; e.g. `viz` 8,131, `public` 148) into the report `.md`.
3. **Freeze the ruff baseline.** Save raw `ruff check ari-core --statistics` to `docs/refactoring/reports/ruff_baseline.txt` (must reproduce 661 / 358 auto-fixable / `F401` 341 / `E402` 135). Additionally run and save `ruff check . --statistics` as `ruff_baseline_full.txt`, labeled as the broader cohort (skills + scripts + report tooling) — explicitly a **new** measurement, not a re-run of the core-only number. **Do not pass `--fix`.**
4. **Capture compile health.** Run `python -m compileall ari-core ari-skill-* -q`; save pass/fail summary to `docs/refactoring/reports/compileall.txt`.
5. **Build the dependency graph.** Run an `ast`-based internal-import scan over `ari-core/ari`; emit `docs/refactoring/reports/import_edges.json` (directed edges) and `docs/refactoring/reports/fan_in.csv` (`module, fan_in, fan_out`). Run Tarjan SCC; record any cycle(s) and cross-reference the 135 `E402` hits. If a throwaway scan helper is needed, keep it as `docs/refactoring/reports/_capture_baseline.py`, clearly commented "one-off measurement helper — NOT the canonical checker (see subtask 025)". It must not be added to `scripts/`.
6. **Record cross-package + contract edges.** In the report `.md`, document as annotated facts: the `ari-core -> ari_skill_memory` edge (with the `pyproject.toml` lines 27–31 rationale), the `ari.public.*` 8-module surface (148 LOC), the two MCP server idioms + flat-namespace collision risk, and the `viz` backend ↔ `services/api.ts` (863 LOC) contract.
7. **Record inventory clarifications.** State the config trio (`config/` code vs `configs/` data vs top-level `config/` rubric data) and assert **`sonfigs/` does not exist**. Note the empty `ari/__init__.py` (no `__version__`) and root `checkpoints/` vs `workspace/checkpoints/` coexistence as inventory facts.
8. **Write the baseline report.** `docs/refactoring/reports/001_complexity_baseline.md`: an index tying every data file to its generating command, tool versions, git SHA, and UTC timestamp, plus the large-file tiers, ruff breakdown, and dependency findings. Add the `REVIEW_REQUIRED` note on the CC engine choice.
9. **Idempotence check.** Run `git status --porcelain` and confirm no path outside `docs/refactoring/reports/` is modified. Record the check result in the report.

---

## 9. Files Expected to Change

**Created (all under the currently-empty `docs/refactoring/reports/`):**
- `docs/refactoring/reports/001_complexity_baseline.md` — the baseline report (index + narrative).
- `docs/refactoring/reports/loc_census.csv` — per-file LOC with cohort + band.
- `docs/refactoring/reports/ruff_baseline.txt` — frozen `ruff check ari-core --statistics` (661 findings).
- `docs/refactoring/reports/ruff_baseline_full.txt` — `ruff check . --statistics` (broader cohort, new measurement).
- `docs/refactoring/reports/compileall.txt` — compile/syntax smoke result.
- `docs/refactoring/reports/import_edges.json` — internal `ari` import edge list.
- `docs/refactoring/reports/fan_in.csv` — per-module fan-in / fan-out.
- `docs/refactoring/reports/_capture_baseline.py` — **optional** one-off measurement helper (labeled non-canonical; NOT promoted to `scripts/`).

**Modified:** none.

**Explicitly NOT changed** (guardrail): no file under `ari-core/ari/`, `ari-skill-*/`, `scripts/`, `.github/`, `config/`, `configs/`, `docs/` (site), `report/`, or `ari-core/ari/viz/frontend/`. No `requirements*.txt`, no `pyproject.toml`. This subtask does **not** create `scripts/check_complexity.py` (subtask 025), `scripts/analyze_references.py` (020 chain), or `scripts/check_dead_code.py` (dead-code chain).

---

## 10. Files / APIs That Must Not Be Broken

Since this subtask writes only report artifacts, breakage is impossible by design — but the census reads these contract surfaces and must record them **verbatim** without editing:

- **CLI contract:** single console script `ari = ari.cli:app` (`ari-core/pyproject.toml`); the Typer command tree in `ari/cli/` (`clone`, `run`, `resume`, `paper`, `status`, `skills-list`, `viz`, `projects`, `show`, `delete`, `settings`, and sub-typers `memory`/`ear`/`registry`/`migrate`).
- **Public Python API:** every `ari.public.*` symbol (`claim_gate`, `config_schema`, `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`) — 148 LOC surface.
- **MCP contract:** the 14 `ari-skill-*/src/server.py` tool names, `inputSchema`s, the `{"result"|"error"}` return envelope, and the `mcp__<skill>__<tool>` fully-qualified naming emitted by `ari/mcp/client.py`.
- **Dashboard API:** `ari/viz/routes.py` + `api_*.py` endpoints and `websocket.py` consumed by the React frontend (`services/api.ts`, 863 LOC).
- **Checkpoint / config file formats:** `ari/checkpoint.py`; YAML under `config/` and `configs/`.
- **Core↔skill stable interface:** `ari-core -> ari_skill_memory`.
- **Docs / workflow scripts:** files invoked by `.github/workflows/*` (e.g., `scripts/run_all_tests.sh`, `scripts/docs/*`) — read-only here.

No compatibility adapter is needed because nothing is altered.

---

## 11. Compatibility Constraints

- **Additive only (design principle P5).** The subtask only *adds* files under `docs/refactoring/reports/`; it removes/renames nothing.
- **No dependency footprint change.** No package installed, no manifest edited — CI environments (e.g., `.github/workflows/refactor-guards.yml`, which pins Python 3.13 and installs from `requirements.txt`) are unaffected.
- **Determinism (P2).** Every artifact records its exact generating command + tool versions (`ruff 0.15.2`, Python `3.13.2`) + git SHA so 025/031 can reproduce and diff byte-for-byte.
- **Report artifacts must not trip existing doc gates.** `docs/refactoring/reports/` is a planning workspace, not a VitePress site page; the new files must not be wired into `docs/.vitepress/` navigation and should not require `sources:`/`last_verified:` front-matter (they are not the English master docs that `scripts/docs/check_ref_coupling.py` / `check_doc_sources.py` map). Confirm the added files are outside those checkers' scope.
- **No `~/.ari/` references introduced** (honors `refactor-guards.yml` guard 1), trivially satisfied since only measurement data is written.

---

## 12. Tests to Run

This subtask changes no runtime code, so "tests" are smoke + idempotence checks, not behavior tests:

1. **Syntax/compile smoke:** `python -m compileall .` — must pass (captured as an artifact).
2. **Behavior gate (unchanged baseline):** `pytest -q` (core, `ari-core/tests`, honoring `pytest.ini` `--import-mode=importlib`); full multi-package suite via `bash scripts/run_all_tests.sh`. These must show **no change** vs. the pre-subtask run — the subtask must not affect any test outcome.
3. **Lint capture (not fix):** `ruff check .` and `ruff check ari-core --statistics` — run to *record* the baseline; **never** with `--fix`.
4. **Idempotence:** `git status --porcelain -- ':(exclude)docs/refactoring/reports/'` must return empty (proves zero source mutation).
5. **Frontend:** `npm test` / `npm run build` are **not required** — the frontend is only LOC-counted via `wc -l` (no `pnpm`; `node`/`npm` present but unused for measurement). Record that frontend behavior is untouched.

---

## 13. Acceptance Criteria

1. All artifacts in Section 9 exist under `docs/refactoring/reports/`, each with a header recording command + tool versions + git SHA + UTC timestamp.
2. `loc_census.csv` reproduces the verified totals: `ari-core/ari` = **30,277** production LOC; `viz` = **8,131** (27 %); `public` = **148**; and the five `>1200` production files + one `>1200` frontend file are correctly banded `split-required`.
3. `ruff_baseline.txt` reproduces **661 findings / 358 auto-fixable**, with `F401` = **341** and `E402` = **135**; `ruff_baseline_full.txt` is present and labeled as the broader (skills + scripts + report) cohort.
4. `import_edges.json` + `fan_in.csv` exist; cycle detection ran (result recorded, even if "none found"); the 135 `E402` hits are cross-referenced; the four cross-package edges (core→`ari_skill_memory`, `ari.public.*`, `viz`↔`api.ts`, MCP client→servers) are documented.
5. The report states **CC is `unmeasured (no tool installed)`** and records the radon-vs-`C901` choice as `REVIEW_REQUIRED` — no CC number is fabricated.
6. The report asserts `sonfigs/` **does not exist** and documents the `config/` (code) vs `configs/` (data) vs top-level `config/` (rubric) trio.
7. `python -m compileall .` passes and `pytest`/`run_all_tests.sh` outcomes are unchanged from baseline.
8. `git status --porcelain` shows **no** modification outside `docs/refactoring/reports/`.
9. No `scripts/*.py` checker was created (025/020/013 scope untouched); no dependency installed; no source file mutated.

---

## 14. Rollback Plan

Trivial and complete: the subtask only adds files under `docs/refactoring/reports/`. To roll back, delete the added artifacts:

```bash
git -C /home/t-kotama/workplace/ARI rm -r --cached docs/refactoring/reports/  # if staged
rm -rf /home/t-kotama/workplace/ARI/docs/refactoring/reports/*
```

Because no source, config, workflow, or dependency was touched, removal restores the exact pre-subtask state (verified by an empty `git status` afterward). There is no runtime behavior to revert and no migration to undo.

---

## 15. Dependencies

Per the provided DEPENDENCY GRAPH (`A -> B` means A must precede / enables B):

- **Upstream (must precede 001):** **none.** 001 is a graph root (no incoming edge) and is itself one of the nine inventory subtasks that **must precede any runtime code change** (001, 002, 020, 036, 045, 053, 059, 060, 067). The subtask index (`007_subtask_index.md` row 48) lists its dependency as `—`.
- **Downstream (depend on 001):** **`001 -> 025`** and **`001 -> 031`**:
  - **025 — `add_complexity_checker_script`** (`scripts/check_complexity.py`): consumes the frozen LOC/band baseline and the CC-engine `REVIEW_REQUIRED` note.
  - **031 — `add_quality_report_generator`** (`scripts/generate_quality_report.py`): aggregates the baseline artifacts produced here.
- **Sibling / informational (NOT a formal graph edge):** **002 — `complexity_measurement_plan`** references 001's census as the inventory it "measures over" (`002_complexity_measurement_plan.md` §11), but the graph contains **no** `001 -> 002` edge; 002 is a separate root. Do not treat 002 as blocking or blocked by 001.

This ordering is consistent with the DEPENDENCY GRAPH and the "inventory-before-runtime-change" gate.

---

## 16. Risk Level

**Risk: Low.** **Changes runtime code: No.**

- This is a pure measurement/inventory subtask. It writes only report + data artifacts under `docs/refactoring/reports/`; it mutates no runtime code, imports, prompts, configs, workflows, frontend, directory names, or dependencies.
- The only residual risks are (a) miscounting (mitigated by committing exact commands + tool versions so numbers are reproducible/auditable) and (b) accidentally invoking `ruff --fix` or writing outside the reports dir (mitigated by the Section 13 idempotence acceptance gate). Both are caught by `git status --porcelain`.
- Matches `007_subtask_index.md` (row 48): risk **Low**, runtime-code-change **No**, inventory **Yes**.

---

## 17. Notes for Implementer

- **Run everything from the repo root** `/home/t-kotama/workplace/ARI`; agent threads reset cwd between shells, so use absolute paths.
- **Freeze before fixing.** Capture `ruff_baseline.txt` *before* anyone is tempted to `--fix`; the 661/341-`F401` number is only meaningful pre-fix.
- **Two ruff cohorts are intentional.** The historical 661 is `ari-core`-only; `ruff check .` covers skills + scripts + report tooling and will report a *different, larger* number — label them distinctly so 025/031 don't read the delta as a regression.
- **Tests are a separate cohort.** Do not let `test_server.py` (1844) etc. leak into production LOC gates; put them in their own CSV rows/section.
- **CC stays empty on purpose.** `radon` is absent and `C901` is off — write `unmeasured (no tool installed)`, never a guess. Record the engine choice as `REVIEW_REQUIRED` for 002/025.
- **Import graph = stdlib `ast` only.** No `pydeps`/`modulegraph`/`radon`. Resolve only edges *internal* to `ari`; annotate the four cross-package edges by hand (they cross the scannable boundary). Note that `compileall`/`ruff` do not detect cycles; Tarjan SCC on your edge list does; cross-reference `E402` = 135.
- **`sonfigs/` is a phantom.** Verified absent — state so explicitly. The real trio is `ari/config/` (code) vs `ari/configs/` (packaged data) vs top-level `config/` (rubric data).
- **Keep helpers out of `scripts/`.** Any capture helper lives beside the artifacts (`docs/refactoring/reports/_capture_baseline.py`) and is labeled non-canonical; the real checker is subtask 025's `scripts/check_complexity.py`.
- **Verify the reports dir is empty first** (`docs/refactoring/reports/` currently has no files) so a clean census run is unambiguous.
- **Stamp determinism.** Every artifact header: exact command, `ruff 0.15.2`, Python `3.13.2`, `git rev-parse HEAD`, UTC timestamp — so 031's generator and 025's checker can diff against this snapshot reproducibly.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **001** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
