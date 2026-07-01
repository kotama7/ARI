# Subtask 025: Add Complexity Checker Script

- **Phase:** Phase 8 — Quality Scripts
- **Subtask ID:** 025
- **Title (index):** `add_complexity_checker_script`
- **Primary deliverable:** a new, self-contained Python checker
  `scripts/check_complexity.py` (plus its config/allowlist and the bootstrap of
  the shared `scripts/quality/` infrastructure) that measures and holds the
  file-size and cyclomatic-complexity baseline of the repository.
- **Runtime code change:** **No** (dev tooling only — see Section 16).
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core`
  version `0.9.0`, from `ari-core/pyproject.toml`).
- **Canonical language:** English.
- **Classification vocabulary (used where relevant):** `KEEP` / `ADAPT` /
  `MERGE` / `MOVE_TO_LEGACY` / `DELETE_CANDIDATE` / `REVIEW_REQUIRED`. The word
  "deprecated" is reserved for external contracts only (public API, CLI, MCP,
  dashboard API, documented import paths, `ari-skill-*` stable interfaces).

---

## 1. Goal

Deliver `scripts/check_complexity.py`: a deterministic, stdlib+PyYAML-only
quality checker that reports (a) per-file line counts against data-derived size
tiers and (b) per-function cyclomatic complexity, and that can be run either as
an advisory report or as a regression ratchet against a frozen baseline.

The checker establishes the size/complexity gate that **does not exist anywhere
in the repo today**: there is no `radon`, no ruff McCabe (`C901`) rule active,
and no LOC gate in any of the 5 workflows. Its verdict for the family is
`KEEP` (net-new) per `docs/refactoring/009_quality_scripts_plan.md` §4.

Success = a fresh coding session, running only this checker plus its frozen
allowlist, can (1) reproduce the measured baseline (5 production-Python files
>1200 LOC, ~15 >800 LOC, 1 frontend file >1200 LOC, 5 frontend >800 LOC), (2)
fail CI **only** on net-new oversized files/functions under
`--fail-on-regression`, and (3) never turn the existing historical debt into red
CI on unrelated PRs.

## 2. Background

ARI has a mature *documentation/i18n* gate family under `scripts/docs/`
(`check_doc_sources.py`, `check_doc_links.py`, `check_i18n_js.py`,
`check_readme_parity.py`, `check_ref_coupling.py`, `check_report_cochange.py`,
`check_site_i18n.py`, `check_translation_freshness.py`) and a *report-build* gate
family under `report/scripts/` (`check_prompt_snapshots.py` Gate 10, etc.). It
has **no source-code quality suite**. `docs/refactoring/009_quality_scripts_plan.md`
designs 11 net-new checkers to fill that gap; this subtask delivers the first of
them, `check_complexity.py`, assigned to subtask 025 in that plan's §10 table.

Measured baseline (all `wc -l` / `ruff` outputs observed live 2026-07-01, from
`docs/refactoring/reports/001_complexity_baseline.md` produced by Subtask 001):

- `ari-core/ari` total: **30,277 LOC** of Python; `viz/` alone is **8,131** (27%
  of core); the frozen contract layer `ari/public/` is only **148 LOC**.
- Production Python >1200 LOC (5): `ari-skill-paper/src/server.py` **2956**,
  `ari-skill-transform/src/server.py` **2465**,
  `ari-skill-paper-re/src/_paperbench_bridge.py` **2376**,
  `ari-core/ari/agent/loop.py` **1630**, `ari-skill-paper-re/src/server.py`
  **1395**.
- Production Python 800–1200 LOC (10): `ari-core/ari/viz/routes.py` 1197,
  `ari-skill-orchestrator/src/server.py` 1043,
  `ari-skill-evaluator/src/server.py` 983, `ari-core/ari/viz/api_experiment.py`
  929, `ari-core/ari/llm/cli_server.py` 919,
  `ari-core/ari/pipeline/orchestrator.py` 913, `ari-core/ari/cli/bfts_loop.py`
  911, `ari-core/ari/orchestrator/bfts.py` 845,
  `ari-core/ari/viz/api_paperbench.py` 813, `ari-skill-plot/src/server.py` 802.
- Frontend >800 LOC (`ari-core/ari/viz/frontend/src`, TS/TSX): `Results/resultSections.tsx`
  **1590** (the only >1200), `Wizard/StepResources.tsx` 1160,
  `Settings/SettingsPage.tsx` 1049, `Workflow/WorkflowPage.tsx` 964,
  `services/api.ts` 863.
- **Tests dominate any naive global LOC threshold**: `ari-core/tests/test_server.py`
  **1844**, `test_gui_errors.py` **1650**, `test_workflow_contract.py` **1606**,
  `test_wizard.py` **1133**, `test_settings_propagation.py` 1058,
  `test_pipeline_e2e.py` 1010 — the 4 largest core files are all tests.

Tooling (measured, confirmed this planning session):

| Tool | State | Consequence |
|---|---|---|
| `radon` | **NOT installed** (`import radon` → `ModuleNotFoundError`) | cannot assume radon; use ruff McCabe. |
| `ruff` | **installed, 0.15.2** | supplies `C901` cyclomatic complexity via CLI. |
| `python` / `compileall` / `pytest` | available (3.13.2; pytest 9.0.2) | AST fallback + test gate. |
| `PyYAML` | available (`pyyaml>=6.0` in `ari-core/pyproject.toml:24`) | config/allowlist parsing. |
| `node`/`npm` | available; **no `pnpm`** | not needed — LOC is counted statically, no build. |

Crucially: `ari-core/pyproject.toml` has **no `[tool.ruff]` / `[tool.ruff.lint]`
section** (verified — only `[tool.hatch.build.targets.wheel]` at line 42), and
there is **no `ruff.toml` / `.ruff.toml`** anywhere. So `C901` is inactive and
**cyclomatic complexity is an entirely unmeasured, zero baseline** today.

## 3. Scope

In scope:

1. Create **`scripts/check_complexity.py`** — the checker, conforming to the
   house style of `scripts/docs/` (`#!/usr/bin/env python3`, module docstring
   citing `docs/refactoring/009_quality_scripts_plan.md` §5.1, `argparse`,
   `REPO_ROOT = Path(__file__).resolve().parents[1]`, stdlib+PyYAML only,
   `SystemExit(2)` on environment error).
2. Two measurement dimensions:
   - **(a) File-size tiers** — physical LOC (`wc -l`-parity so numbers match the
     Subtask 001 baseline) against **>500 warn / >800 review / >1200
     split-required**.
   - **(b) Cyclomatic complexity** — per-function, via **ruff `C901`** invoked
     through the CLI with a configurable `max-complexity` (ruff present; radon
     is not). Python-only (ruff does not parse TS/TSX; frontend files get the
     LOC tier dimension only).
3. **Bootstrap the shared `scripts/quality/` directory** (does **not** exist
   today — `ls scripts/quality` → "No such file or directory"), per
   `009_quality_scripts_plan.md` §8: `_common.py` (JSON-schema emitter, allowlist
   loader, Markdown table writer, git `--base-ref` resolver mirroring
   `check_ref_coupling.py`), `check_complexity.yaml` (thresholds), and
   `check_complexity.allow.yaml` (frozen baseline). Add the per-directory
   `scripts/quality/README.md` required by the repo's README convention.
4. The canonical flag set and exit convention from `009_quality_scripts_plan.md`
   §3 (see Section 7).
5. Keep the `readme_sync.py` gate green: adding `scripts/check_complexity.py`
   and the new `scripts/quality/` subtree requires updating `scripts/README.md`'s
   `## Contents` block (and creating `scripts/quality/README.md`), because
   `readme-sync.yml` runs `python scripts/readme_sync.py --check` and fails on
   missing/extra paths.

Out of scope (owned by sibling subtasks; do not implement here):

- The other 10 checkers (`check_import_boundaries`, `check_directory_policy`,
  `check_public_api_contracts`, `check_viz_api_schema`, `check_prompts`,
  `check_dashboard_ux`, `analyze_references`, `check_dead_code`,
  `generate_quality_report`, and the REVIEW_REQUIRED `check_docs_source_sync`) —
  `009_quality_scripts_plan.md` §5/§10.
- Actually **splitting** any oversized file (that is the runtime-editing work of
  the viz/agent/pipeline refactor subtasks, e.g. 008/011/012/015). This subtask
  only *measures*; it moves no code.
- Installing `radon`/`vulture` or adding a `[tool.ruff]` block to
  `ari-core/pyproject.toml` (a separate reviewed decision — Section 4/11).
- Wiring the checker into any workflow as a hard gate (warning-mode-first —
  Section 7).

## 4. Non-Goals

- **No runtime code changes.** No edits to any file under `ari-core/ari/`,
  `ari-skill-*/`, the frontend, `ari-core/config/`, `ari-core/ari/configs/`,
  prompts, or `.github/workflows/`.
- **No file splits / renames / moves.** The checker reports oversized files; it
  does not touch them. The 5 >1200-LOC files stay exactly where they are.
- **No new runtime dependency.** No `radon`, no `vulture`, and no new entry in
  `ari-core/pyproject.toml` `[project.dependencies]` or `[project.optional-dependencies].dev`.
- **No `[tool.ruff]` in `ari-core/pyproject.toml`.** `C901` is selected on the
  ruff CLI (`--select C901 --config 'lint.mccabe.max-complexity=N'`) so the
  repo-wide lint posture is not silently changed. Adding a persistent ruff config
  is a distinct decision left to a later subtask.
- **No LLM calls, no network** (preserves the `scripts/docs/` determinism
  convention and design principle P2).
- **No hard CI gate** in this subtask; if wired at all, advisory
  (`continue-on-error: true`) only.
- **No `pnpm`** usage (absent); frontend LOC is counted by reading files, not by
  invoking a build.

## 5. Current Files / Directories to Inspect

All paths verified present on `main` at planning time unless marked. Line counts
are `wc -l`.

**House-style reference (the convention to copy):**
- `scripts/docs/check_doc_sources.py` (223 LOC) — canonical checker shape:
  shebang, docstring citing a design doc, `argparse` with `--json`,
  `REPO_ROOT = Path(__file__).resolve().parents[2]`, `Finding` class with
  `as_dict()`, exit `1` on error / `SystemExit(2)` on missing PyYAML.
- `scripts/docs/check_ref_coupling.py` (6488 bytes) — `--base-ref origin/main`
  git-diff resolution to mirror for `--fail-on-regression`.
- `scripts/readme_sync.py` (14330 bytes) — lives at `scripts/` top level and
  uses `REPO_ROOT = Path(__file__).resolve().parents[1]`; the new checker sits
  beside it and uses the same `parents[1]`.

**Directory the checker is added to / creates:**
- `scripts/` — top level (has `readme_sync.py`, `run_all_tests.sh`,
  `git-hooks/`, `docs/`, `setup/`, `letta/`, `registry/`, `fewshot/`,
  `README.md`). The new `check_complexity.py` goes **here** (source-code gate
  family, not under `scripts/docs/`).
- `scripts/quality/` — **does not exist**; created by this subtask.
- `scripts/README.md` (4913 bytes) — its `## Contents` block must be updated
  (or regenerated via `readme_sync.py --write`) to list the new file(s).

**Design inputs (read before implementing):**
- `docs/refactoring/009_quality_scripts_plan.md` — §2 (tooling baseline), §3
  (common script contract), §5.1 (`check_complexity.py` design block), §6
  (warning-mode-first rollout), §8 (placement / `scripts/quality/` / `_common.py`).
- `docs/refactoring/reports/001_complexity_baseline.md` +
  `docs/refactoring/reports/loc_census.csv` +
  `docs/refactoring/reports/ruff_baseline.txt` — the frozen numbers this checker
  must reproduce (produced by Subtask 001, this subtask's hard predecessor).
- `docs/refactoring/002_complexity_measurement_plan.md` — the top-level plan
  behind the 001 measurement.

**Targets the checker will scan (default + opt-in):**
- Default: `ari-core/ari` (30,277 LOC production Python).
- Opt-in via `--target`: each `ari-skill-*/src/` (≈25.5k LOC across 14 skills;
  largest are `ari-skill-paper/src` 4,278, `ari-skill-paper-re/src` 5,843,
  `ari-skill-transform/src` 3,180) and `ari-core/ari/viz/frontend/src` (TS/TSX,
  LOC-tier dimension only).
- **Excluded by default:** `ari-core/tests/**` (the 4 largest core files are
  tests — see Section 2), `node_modules/`, `__pycache__/`, `vendor/` submodules
  (`ari-skill-idea/vendor/virsci`, `ari-skill-paper-re/vendor/paperbench`).

**Confirmed absent (state explicitly, do not chase):**
- `scripts/quality/` (to be created). No `radon`, no `vulture`. No `[tool.ruff]`
  in `ari-core/pyproject.toml`; no `ruff.toml`/`.ruff.toml`. No `sonfigs/`
  anywhere. No top-level `pyproject.toml`.

## 6. Current Problems

1. **No size gate exists.** Nothing in the 5 workflows or `scripts/` measures
   file LOC; the repo already carries 5 production files >1200 LOC and ~15 >800
   LOC with no automated visibility, so new oversized files can land unnoticed.
2. **Cyclomatic complexity is unmeasured (baseline zero).** `ruff check
   ari-core --statistics` reports 661 findings but **no `C901`** — the McCabe
   rule is not selected. There is no per-function complexity number anywhere in
   the repo today.
3. **Tests would dominate a naive threshold.** A global LOC gate that includes
   `ari-core/tests/**` would immediately flag `test_server.py` (1844),
   `test_gui_errors.py` (1650), `test_workflow_contract.py` (1606) as the top
   offenders, drowning the real production signal. Test inclusion must be an
   explicit, configurable decision (default: exclude).
4. **radon is assumed by nobody's tooling but named in some notes.** The
   engine choice (ruff `C901` vs adding radon) is unresolved
   (`009_quality_scripts_plan.md` §11); this subtask must pick one, and the only
   installed option is ruff.
5. **Historical debt must not become red CI.** 30,277 LOC of core plus 25.5k of
   skills predate this gate. Turning the existing >800/>1200 files into hard
   failures would block every unrelated PR — the checker must ship
   warning-mode-first with a frozen allowlist (`009_quality_scripts_plan.md` §6).
6. **Adding a `scripts/` file trips the README-sync gate** unless `scripts/README.md`
   is updated in the same change — an easy-to-miss coupling because
   `readme-sync.yml` runs `readme_sync.py --check` (exit 1 on missing/extra paths).

## 7. Proposed Design / Policy

Deliver `scripts/check_complexity.py` plus the `scripts/quality/` config/allowlist
and shared helper, following `009_quality_scripts_plan.md` §3/§5.1/§8.

**7.1 Placement & bootstrap.** The checker lives at `scripts/check_complexity.py`
(`REPO_ROOT = Path(__file__).resolve().parents[1]`), alongside `readme_sync.py`,
not under `scripts/docs/` (docs family). It creates `scripts/quality/` with:
- `scripts/quality/_common.py` — shared JSON-schema emitter, allowlist loader,
  Markdown-table writer, and `--base-ref` git-diff resolver (mirrors
  `check_ref_coupling.py`'s `origin/main` default). Written once here, reused by
  sibling checkers 026–031/etc.
- `scripts/quality/check_complexity.yaml` — thresholds/config (see 7.4).
- `scripts/quality/check_complexity.allow.yaml` — frozen baseline (see 7.5).
- `scripts/quality/README.md` — per-directory README (README convention).

**7.2 Two measurement dimensions.**
- **File-size (all targets, incl. frontend):** physical LOC per file, classified
  into `warn` (>500), `review` (>800), `split-required` (>1200). Physical-line
  counting keeps parity with the `wc -l` numbers in
  `docs/refactoring/reports/loc_census.csv`; an optional "code lines only" mode
  (strip blank/comment lines via `ast`/tokenize for `.py`) may be offered behind
  a config toggle but is **not** the default (parity first).
- **Cyclomatic complexity (Python targets only):** shell out to
  `ruff check --select C901 --config 'lint.mccabe.max-complexity=<N>' --output-format json <paths>`
  and parse the JSON. This activates McCabe **without** editing
  `ari-core/pyproject.toml`. `N` defaults to a value chosen from the first
  measured run (recommend starting generous, e.g. 15–20, then ratcheting down);
  the exact default is an implementer decision recorded in `check_complexity.yaml`.

**7.3 Test inclusion policy.** Default **exclude** `**/tests/**` and
`**/test_*.py` from the size gate (the 4 largest core files are tests).
Overridable via `include_tests: true` in the config so a maintainer can audit
test bloat deliberately.

**7.4 Canonical flags (`009_quality_scripts_plan.md` §3 — accept all, ignore
inapplicable ones):**

| Flag | Meaning |
|---|---|
| `--target <path>` | Restrict scan (default `ari-core/ari`; repeatable for per-skill / frontend rollout). |
| `--config <file>` | YAML config (default `scripts/quality/check_complexity.yaml`). |
| `--output <file>` | Write report to a file instead of stdout. |
| `--format markdown\|json` | `json` = aggregator building block (stable schema); `markdown` = human report. |
| `--warning-only` | Force exit 0 regardless of findings (advisory; the **default posture** while new). |
| `--fail-on-regression` | Exit non-zero **only** for findings above the frozen allowlist (net-new debt). |
| `--base-ref <ref>` | For diff-scoped regression checks (default `origin/main`, mirroring `check_ref_coupling.py`). |
| `--update-baseline` | Regenerate `check_complexity.allow.yaml` from the current tree (deliberate freeze, analogous to `report/scripts/snapshot_prompts.py`). |

**7.5 Allowlist / baseline.** `check_complexity.allow.yaml` freezes the current
offenders keyed by file path (with LOC-at-freeze + optional justification): the 5
files >1200 and the ~15 >800, plus any function over `max-complexity` on the
first run. Allowlisted findings are reported as `known`, never `new`, and never
fail `--fail-on-regression`. Ratchet direction: entries shrink as files are split
by the runtime-editing subtasks; the baseline never grows silently.

**7.6 Output schema.** JSON matches `009_quality_scripts_plan.md` §3:
`{ "checker": "check_complexity", "version": 1, "target": <str>,
"summary": {counts by tier + over-complexity count},
"findings": [ {id, severity, file, line, kind: "loc"|"complexity", message,
allowlisted: bool} ] }`. Markdown = a triage table (file, LOC, tier, function,
complexity, allowlisted?). Exit convention: `0` clean or `--warning-only`; `1`
findings above threshold (non-warning, or net-new under `--fail-on-regression`);
`2` usage/environment error (e.g. ruff not on PATH), matching
`check_doc_sources.py`'s `SystemExit(2)`.

**7.7 Rollout (warning-mode-first, `009_quality_scripts_plan.md` §6).** Land as
advisory: `--warning-only` default, frozen allowlist, **no** hard workflow gate.
Any later CI wiring is a separate subtask and uses `continue-on-error: true`
(like `docs-sync.yml`'s advisory `translation_freshness` step). This subtask does
**not** modify any of the 5 existing workflows.

## 8. Concrete Work Items

1. Read `docs/refactoring/009_quality_scripts_plan.md` §3/§5.1/§8/§11 and
   `docs/refactoring/reports/001_complexity_baseline.md` (+ `loc_census.csv`,
   `ruff_baseline.txt`). Copy the checker shape from
   `scripts/docs/check_doc_sources.py`.
2. Create `scripts/quality/` and write `scripts/quality/_common.py`
   (JSON emitter matching the §3 schema; allowlist YAML loader; Markdown table
   writer; `--base-ref` resolver mirroring `check_ref_coupling.py`).
3. Write `scripts/check_complexity.py`:
   - `REPO_ROOT = Path(__file__).resolve().parents[1]`; shebang; docstring citing
     `docs/refactoring/009_quality_scripts_plan.md` §5.1.
   - File-walk with default target `ari-core/ari`, exclusions (`tests/`,
     `node_modules/`, `__pycache__/`, `vendor/`), and `--target` override.
   - LOC tier classification (>500/>800/>1200), physical-line count.
   - Complexity via `ruff check --select C901 --config
     'lint.mccabe.max-complexity=<N>' --output-format json <py-paths>`; parse and
     map to findings. Handle "ruff missing" → `SystemExit(2)`.
   - Allowlist load + `known`/`new` tagging; `--fail-on-regression`,
     `--warning-only`, `--format`, `--output`, `--base-ref`, `--update-baseline`.
4. Write `scripts/quality/check_complexity.yaml` (tiers, `max-complexity`,
   include/exclude globs, `include_tests: false`).
5. Generate `scripts/quality/check_complexity.allow.yaml` via `--update-baseline`
   on the current tree; verify it contains exactly the measured offenders (5
   >1200, ~15 >800, and first-run over-complexity functions).
6. Add `scripts/quality/README.md` (per-directory README convention).
7. Update `scripts/README.md` `## Contents` to list `check_complexity.py` and the
   `quality/` subtree — or run `python scripts/readme_sync.py --write` and stage
   the result — so `readme_sync.py --check` stays green.
8. Ensure the new `.py` files are **ruff-clean** (`ruff check scripts/check_complexity.py
   scripts/quality/_common.py` → 0 findings) so the repo-wide `ruff check .` count
   does not rise above the 661 baseline.
9. Optional: add a small self-test (e.g. `ari-core/tests/test_check_complexity.py`
   or `scripts/quality/tests/`) covering tier boundaries and allowlist
   suppression, following the pattern that no `scripts/docs/` checker currently
   has dedicated tests (so this is additive, not required for parity).
10. Run the Section-12 gates; confirm baseline is unchanged and the new checker
    reproduces the 001 numbers under `--warning-only`.

## 9. Files Expected to Change

Runtime code: **none**.

Created (dev tooling / config / docs only):
- `scripts/check_complexity.py` — the checker.
- `scripts/quality/_common.py` — shared checker infrastructure (first user).
- `scripts/quality/check_complexity.yaml` — thresholds/config.
- `scripts/quality/check_complexity.allow.yaml` — frozen baseline allowlist.
- `scripts/quality/README.md` — per-directory README (README-sync convention).
- *(optional)* `ari-core/tests/test_check_complexity.py` — self-test.

Updated (non-runtime):
- `scripts/README.md` — `## Contents` gains `check_complexity.py` and the
  `quality/` entry (required for `readme_sync.py --check`).

Explicitly **not** changed:
- `ari-core/pyproject.toml` (no `[tool.ruff]`, no new dep).
- Any of `.github/workflows/{docs-change-coupling,docs-sync,pages,readme-sync,refactor-guards}.yml`.
- Any file under `ari-core/ari/`, `ari-skill-*/`, the frontend,
  `ari-core/config/`, or `ari-core/ari/configs/`.

## 10. Files / APIs That Must Not Be Broken

This subtask adds a read-only static-analysis script and touches no runtime
surface, so it breaks nothing directly. It must nonetheless preserve:

- **CLI** `ari = ari.cli:app` — untouched; the checker adds no `ari` subcommand
  and is invoked as `python scripts/check_complexity.py`.
- **`ari.public.*`** (148 LOC frozen surface: `claim_gate`, `config_schema`,
  `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`) —
  not imported, not modified.
- **MCP tool contracts** (14 `ari-skill-*/src/server.py`) — the checker *reads*
  these files for LOC/complexity; it must not edit them or change any tool
  contract. The sanctioned `ari-core → ari_skill_memory` edge is irrelevant here.
- **Dashboard API** (`ari/viz/routes.py` + `api_*.py` + `websocket.py`, consumed
  by `frontend/src/services/api.ts`) — read-only measurement target; endpoints
  unchanged.
- **Checkpoint / output / config file formats** — untouched; the checker writes
  only its own report (stdout or `--output`).
- **Scripts invoked by `.github/workflows/`** — the `readme_sync.py --check` gate
  (`readme-sync.yml`) must stay green, which is why `scripts/README.md` is
  updated in the same change. The other four workflows are not modified.
- **`scripts/git-hooks/pre-commit`** — runs `readme_sync.py --write`
  (non-blocking); the new files must be README-sync-consistent so the hook does
  not report a lingering `— TODO`.

## 11. Compatibility Constraints

- **No `[tool.ruff]` added to `ari-core/pyproject.toml`.** `C901` is selected on
  the ruff CLI per-invocation (`--select C901 --config
  'lint.mccabe.max-complexity=N'`), so the repo-wide `ruff check .` baseline (661
  findings, no `C901`) is unchanged for everyone else. Persisting a ruff config
  is a separate, reviewed decision.
- **No new dependency.** `radon`/`vulture` are not installed and are not added;
  the checker depends only on ruff (already present) + stdlib + PyYAML
  (`pyyaml>=6.0`, already a core dep). If a future subtask wants radon, that is
  its own reviewed change to `[project.optional-dependencies].dev`.
- **Determinism (P2).** No LLM, no network — same input tree ⇒ same report.
  This matches the `scripts/docs/` convention (PyYAML the only non-stdlib dep).
- **README-sync parity.** Adding files under `scripts/` and creating
  `scripts/quality/` obliges updating `scripts/README.md` and adding
  `scripts/quality/README.md`; otherwise `readme_sync.py --check` (and thus
  `readme-sync.yml`) fails.
- **Warning-mode-first.** The checker must default to `--warning-only` and ship a
  frozen allowlist; it must **not** be wired as a hard CI gate in this subtask.
  Promotion to a ratchet (`--fail-on-regression`) or hard gate is a later,
  explicit subtask (`009_quality_scripts_plan.md` §6).
- **`ruff --output-format json` shape** is a ruff-version detail (0.15.2); the
  parser should tolerate absent `C901` results gracefully and fail with exit `2`
  only if ruff itself is unavailable, not merely because there are no complexity
  findings.

## 12. Tests to Run

- `python -m compileall .` — confirms the new `.py` files (and nothing else)
  compile; no runtime `.py` was accidentally touched.
- `pytest -q` — full suite must pass unchanged from baseline (heaviest:
  `ari-core/tests/test_server.py` 1844, `test_gui_errors.py` 1650,
  `test_workflow_contract.py` 1606). If a self-test was added, it runs here.
- `ruff check .` — baseline is **661 findings**; must not increase. The new
  `scripts/check_complexity.py` and `scripts/quality/_common.py` must themselves
  be ruff-clean (`ruff check scripts/check_complexity.py scripts/quality/`).
- `python scripts/readme_sync.py --check` — must exit 0 after `scripts/README.md`
  and `scripts/quality/README.md` are updated/added (this is the gate
  `readme-sync.yml` runs).
- **Checker self-run (smoke):**
  - `python scripts/check_complexity.py --target ari-core/ari --warning-only`
    → exit 0, reproduces the ~15 >800 / 5 >1200 offenders.
  - `python scripts/check_complexity.py --target ari-core/ari --format json`
    → valid JSON per the §3 schema.
  - `python scripts/check_complexity.py --fail-on-regression` on the clean tree
    → exit 0 (all offenders allowlisted).
- **Frontend (`npm test` / `npm run build` under `ari-core/ari/viz/frontend/`) is
  NOT applicable** — this subtask adds a Python static-analysis script and does
  not touch frontend code or require a build (`npm`, not `pnpm`, in this env).

If `compileall` / `pytest` / `ruff check .` regress beyond the 661 baseline, the
session touched something outside the intended file set and must revert.

## 13. Acceptance Criteria

1. `scripts/check_complexity.py` exists, is executable-style
   (`#!/usr/bin/env python3`), uses `REPO_ROOT = Path(__file__).resolve().parents[1]`,
   depends only on stdlib + PyYAML + the ruff CLI, and its docstring cites
   `docs/refactoring/009_quality_scripts_plan.md` §5.1.
2. `scripts/quality/` exists with `_common.py`, `check_complexity.yaml`,
   `check_complexity.allow.yaml`, and `README.md`.
3. The size gate reports the measured offenders — 5 production-Python files
   >1200 LOC and ~15 >800 LOC (Section 2) — and **excludes** `tests/**` by
   default (configurable via `include_tests`).
4. The complexity gate runs via ruff `C901` on the CLI **without** any
   `[tool.ruff]` edit to `ari-core/pyproject.toml`, and degrades to exit `2` only
   when ruff is unavailable.
5. All of `--target`, `--config`, `--output`, `--format markdown|json`,
   `--warning-only`, `--fail-on-regression`, `--base-ref`, `--update-baseline`
   are accepted; exit convention is `0`/`1`/`2` per Section 7.6.
6. `--fail-on-regression` on the clean tree exits `0` (every current offender is
   allowlisted); a synthetic net-new oversized file/function makes it exit `1`.
7. `python scripts/readme_sync.py --check` passes (README updated for the new
   files).
8. `python -m compileall .`, `pytest -q`, and `ruff check .` pass with the
   `ruff` count **≤ 661** (no new lint debt from the added scripts).
9. No runtime code, config, prompt, workflow, frontend, or directory under
   `ari-core/ari/` / `ari-skill-*/` / the frontend was created, edited, moved,
   renamed, or deleted. The word "deprecated" is not applied to any internal code.

## 14. Rollback Plan

Trivial and complete — the subtask's artifacts are new tooling files plus one
README edit, none imported by runtime code:

- `git rm scripts/check_complexity.py` and `git rm -r scripts/quality/`
  (or delete if not yet committed).
- `git checkout -- scripts/README.md` to restore the `## Contents` block (or
  re-run `python scripts/readme_sync.py --write`).
- If the optional self-test was added, `git rm ari-core/tests/test_check_complexity.py`.

No runtime state, no migrations, no config-format change, no schema change, no
workflow change → nothing else to undo. Rollback cannot affect the running
system, checkpoints, MCP tools, the dashboard, or any preserved contract.

## 15. Dependencies

Per the program dependency graph:

- **Predecessor (hard, incoming edge):** `001 -> 025`. Subtask 025 **depends on
  Subtask 001** (`measure_complexity_and_dependencies`), which produces the
  frozen baseline this checker must reproduce and freeze into its allowlist:
  `docs/refactoring/reports/001_complexity_baseline.md`, `loc_census.csv`,
  `ruff_baseline.txt`. 025 must not start until 001 is complete.
- **Sibling of 001's other successor:** `001 -> 031` — Subtask 031
  (`check_dashboard_ux.py`, per `009_quality_scripts_plan.md` §10) shares the
  same predecessor but is independent of 025 (no edge between them).
- **No outgoing hard edge from 025** in the provided graph — 025 is not a
  predecessor of any other subtask. (Soft, non-graph relationship: the
  aggregator `generate_quality_report.py` — the terminal node of the
  `053 -> 054 -> 055 -> 056 -> 057 -> 058` chain — will consume this checker's
  JSON output once built, but that is a runtime-of-the-aggregator concern, not a
  build-order edge on 025.)
- **Gate context:** 001 is one of the nine inventory/measurement subtasks
  (001, 002, 020, 036, 045, 053, 059, 060, 067) that **must precede any runtime
  code change**. 025 sits downstream of 001 and is itself **not** a runtime code
  change (it adds tooling), so it does not block, and is not blocked by, the
  runtime-editing cohort beyond its 001 predecessor.
- **Sibling coordination (no hard edge, do not duplicate):** the other
  `scripts/quality/` checkers (`check_import_boundaries`, `check_directory_policy`,
  `check_public_api_contracts`, `check_viz_api_schema`, `check_prompts`,
  `check_dashboard_ux`, `analyze_references`, `check_dead_code`,
  `generate_quality_report`) reuse the `scripts/quality/_common.py` bootstrapped
  here; keep it minimal and general so those subtasks inherit it cleanly.

This is consistent with the provided graph edge `001 -> 025` and the inventory
gate list.

## 16. Risk Level

- **Risk: Low.**
- **Changes runtime code? No.** The deliverables are dev tooling
  (`scripts/check_complexity.py`, `scripts/quality/*`), a documentation README
  update (`scripts/README.md`, `scripts/quality/README.md`), and an optional
  test. None is imported by the `ari` package, any `ari-skill-*` server, the CLI,
  the dashboard, or any of the 5 workflows. The checker is read-only static
  analysis and modifies no runtime code, imports, prompts, configs, workflows,
  frontend, or directory names.
- Residual risks: (a) the ruff `--output-format json` shape differing across ruff
  versions — mitigated by tolerant parsing and the `exit 2` env-error path; (b)
  accidentally raising the `ruff check .` baseline by shipping a non-clean script
  — mitigated by the Section-12 ruff gate; (c) forgetting the `scripts/README.md`
  update and failing `readme-sync.yml` — mitigated by the explicit `readme_sync
  --check` gate in Section 12. All are contained to tooling and caught by the
  standard gates.

## 17. Notes for Implementer

- **Reproduce, then freeze.** Run against `ari-core/ari` first and confirm the
  offender set matches `docs/refactoring/reports/loc_census.csv` before writing
  the allowlist. If numbers drift from Section 2, the live tree wins — re-measure
  and note the drift; do not hardcode the Section-2 list.
- **Physical LOC = `wc -l` parity.** Default counting must match the 001 baseline
  (physical lines), or the allowlist will not line up with the census. Offer a
  "code lines only" mode as an opt-in config toggle, not the default.
- **Exclude tests by default.** The 4 largest core files
  (`test_server.py` 1844, `test_gui_errors.py` 1650, `test_workflow_contract.py`
  1606, `test_wizard.py` 1133) are tests; including them by default would bury the
  production signal. Gate this on `include_tests: false` in
  `check_complexity.yaml`.
- **Engine = ruff, not radon.** radon is not installed and must not be assumed
  (`009_quality_scripts_plan.md` §11). Invoke `ruff check --select C901 --config
  'lint.mccabe.max-complexity=N' --output-format json`; do **not** add a
  `[tool.ruff]` block to `ari-core/pyproject.toml` (that would change everyone's
  lint posture and is a separate decision).
- **Frontend is LOC-only.** ruff cannot compute TS/TSX complexity; for
  `ari-core/ari/viz/frontend/src` targets emit only the size-tier dimension
  (`resultSections.tsx` 1590 is the sole frontend >1200). Skip `node_modules/`.
- **Bootstrap `_common.py` for reuse.** This is the *first* `scripts/quality/`
  checker; keep `_common.py` (JSON emitter, allowlist loader, Markdown writer,
  `--base-ref` resolver) generic so 026–031 and the aggregator inherit it without
  a rewrite (`009_quality_scripts_plan.md` §8). This is the one place up-front
  de-duplication is worth it.
- **Keep the README gate green in the same commit.** After adding the files, run
  `python scripts/readme_sync.py --write`, stage the updated `scripts/README.md`
  and new `scripts/quality/README.md`, then verify `--check` exits 0 — otherwise
  `readme-sync.yml` fails on the PR.
- **Warning-mode-first, no CI wiring here.** Ship `--warning-only` as the default
  and a frozen allowlist. Do **not** edit any workflow; promotion to
  `--fail-on-regression` or a hard gate is a separate, explicitly-scoped subtask.
- **Match the house style.** Mirror `scripts/docs/check_doc_sources.py`: shebang
  line, docstring citing the design doc, `argparse`, a small `Finding`/dataclass
  with `as_dict()`, `SystemExit(2)` on environment error, `--json`-equivalent via
  `--format json`. Consistency with the existing checker family is a review
  criterion.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **025** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
