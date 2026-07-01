# 002 — Complexity Measurement Plan

- **Subtask:** 002 (planning artifact; part of the ARI refactoring subtask map)
- **Phase:** PLANNING ONLY — no runtime code, imports, prompts, configs, workflows, frontend, or directory names are changed by this document.
- **Repo:** `/home/t-kotama/workplace/ARI` — git branch `main`, `ari-core` version `0.9.0`.
- **Planning date:** 2026-07-01.
- **Scope of edits from this document:** exactly one file — this `.md`. Nothing else.

This document defines *how* ARI will measure structural complexity and quality signals so that later subtasks can classify code with a shared, reproducible baseline. It does not perform any classification or refactor; it specifies metrics, thresholds, tooling, commands, exclusions, and the initial hotspot worklist.

---

## 1. Purpose and non-goals

**Purpose.** Establish a deterministic, repeatable measurement pipeline covering 17 metrics (§5) so that:

1. Every later refactoring subtask starts from the same numbers.
2. Regressions can be gated in CI/pre-commit (design only — see §9).
3. Hotspots are ranked by evidence, not intuition (§7).

**Non-goals of this subtask.**

- No `KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED` *decisions* are finalized here. Measurement produces the data; classification happens in the per-area subtasks. Where this plan tags a hotspot (§7) it uses `REVIEW_REQUIRED` as a provisional "needs a human/decision-subtask" marker, not a verdict.
- No tool is installed and no checker script is authored in this subtask. `check_complexity.py` and siblings are *designed* here and *implemented* in a later subtask (§8).

**Contract-preservation reminder.** Measurement must never require touching a public contract. The frozen surfaces this plan is careful to *read but not perturb* are: CLI `ari` (`ari.cli:app`), `ari.public.*`, the 14 `ari-skill-*` MCP tool contracts, the dashboard API (`ari/viz/routes.py` + `api_*.py` + `websocket.py`, consumed by `frontend/src/services/api.ts`), checkpoint/output/config file formats, the `ari-skill-* -> ari-core` stable interfaces, README/docs usage, and the scripts invoked by `.github/workflows/`. The word *deprecated* is reserved for those external contracts and is not used for internal code in this plan.

---

## 2. Tooling availability (verified live, 2026-07-01)

| Tool | Status | Evidence | Role in this plan |
|---|---|---|---|
| **radon** | **NOT installed** | `python -c "import radon"` → `ModuleNotFoundError`; not present in `requirements.txt`, `requirements.lock`, or `ari-core/pyproject.toml` | Preferred CC/MI engine — must be **added as a dev/optional dependency in a later subtask** before its commands run |
| **ruff** | **installed, 0.15.2** | `ruff --version` | Available *now* for lint statistics and, via `--select C901`, McCabe cyclomatic complexity — the zero-install CC path |
| **Python** | 3.13.2 | `python --version` | Host for `compileall`, `pytest`, and the planned AST fallback checker |
| **compileall** | available | `python -m compileall --help` OK | Import/syntax smoke gate |
| **pytest** | 9.0.2 | `python -m pytest --version` | Behavior gate; `pytest.ini` sets `--import-mode=importlib`, `testpaths = ari-core/tests` |
| **npm** | 10.8.2 | `npm --version` | Frontend build/test/typecheck driver |
| **pnpm** | **absent** | `pnpm: command not found` | Do **not** use pnpm anywhere |

**Frontend script reality (correcting the generic "npm test/build/lint" wording).** `ari-core/ari/viz/frontend/package.json` defines `dev`, `build` (`vite build`), `typecheck` (`tsc --noEmit`), `preview`, `test` (`vitest run`), `test:watch`. There is **no `lint` script and no ESLint config file** (`.eslintrc*` / `eslint.config.*` do not exist). So the available frontend gates today are `npm test`, `npm run build`, and `npm run typecheck` — **`npm run lint` does not exist** and is only available after a later subtask adds ESLint (§5.17).

**No existing complexity tooling.** `scripts/check_complexity.py` does not exist. Ruff runs today with **no `[tool.ruff]` config** in `ari-core/pyproject.toml` or `pytest.ini`, so the McCabe `C901` rule is **not** active. Consequently **cyclomatic complexity is entirely unmeasured today** — the baseline for every complexity metric is "not yet collected."

---

## 3. Measurement scope and exclusions

### 3.1 In-scope trees

- `ari-core/ari/**/*.py` — the core framework (30,277 LOC total, see §6).
- `ari-skill-*/src/**/*.py` — the 14 MCP skill servers (≈25.5k LOC combined).
- `ari-core/ari/viz/frontend/src/**/*.{ts,tsx}` — the dashboard frontend.
- `scripts/**/*.py` — repo tooling (measured advisory, not gated at first).

### 3.2 Hard exclusions (must be filtered from every scan)

- `__pycache__/`, `*.pyc`.
- `node_modules/` — **present on disk but gitignored** (`.gitignore` lines 112–113: `node_modules/`, `ari-core/ari/viz/frontend/node_modules/`) and **not tracked** (`git ls-files '*/node_modules/*'` → 0). It is *not* a committed/vendored-deps hygiene issue; it simply must be excluded from LOC/complexity scans or it will dominate frontend numbers.
- `workspace/`, `checkpoints/` (root-level, appears legacy), and any `staging/`/`experiments/` runtime output.
- Frontend build output (Vite `dist/` bundle under `ari-core/ari/viz/static/dist/`), `docs/.vitepress/cache`, and `report/html/` generated artifacts.
- `.venv`/virtualenvs.

### 3.3 Tests: an explicit policy decision (open question)

The heaviest Python files in `ari-core` are **tests**, not production code: `tests/test_server.py` 1844, `test_gui_errors.py` 1650, `test_workflow_contract.py` 1606, `test_wizard.py` 1133, `test_settings_propagation.py` 1058, `test_pipeline_e2e.py` 1010. If tests are counted under one global file-size gate they will dominate the offender list and drown production signal.

**Plan:** measure production and tests as **two separate cohorts**. File-size/complexity gates in §5 apply to the **production** cohort; test files are reported *advisory-only* at first. Whether tests eventually get their own (looser) thresholds is a decision to be recorded in the checker subtask (§8) — flagged here as `REVIEW_REQUIRED`.

### 3.4 The config/configs directory note (measurement hygiene, not a metric)

The confusable directory trio is real and matters for the *path-literal* and *duplicate* scans (§5.14, §5.10): `ari-core/ari/config/` (Python code that *locates* config files; `__init__.py` is an unexpectedly large 628 LOC) vs `ari-core/ari/configs/` (packaged default DATA: `defaults.yaml`, `model_prices.yaml`). **There is no `sonfigs/` directory anywhere** (`sonfigs` is a hypothesized typo; it does not exist). Scanners keying on directory names must not conflate `config/` and `configs/`.

---

## 4. Threshold tables (canonical, from the master prompt)

These are the authoritative bands. A "band" is a tier, not a hard fail; the gating policy (which band blocks CI) is chosen in the checker subtask (§8/§9).

**Cyclomatic Complexity (per function/method)**

| Band | Range | Interpretation |
|---|---|---|
| Green | CC ≤ 10 | Simple |
| Yellow | 11–15 | Moderate |
| Orange | 16–30 | High — review |
| Red | > 30 | Critical — split required |

**Function / method length (LOC)**

| Band | Range |
|---|---|
| Green | ≤ 50 |
| Yellow | 51–80 |
| Orange | 81–120 |
| Red | > 120 |

**Class size (LOC)**

| Band | Range |
|---|---|
| Green | ≤ 300 |
| Yellow | 301–500 |
| Orange | 501–700 |
| Red | > 700 |

**File size (LOC)**

| Band | Range |
|---|---|
| Green | ≤ 500 |
| Yellow | 501–1000 |
| Orange | 1001–2000 |
| Red | > 2000 |

**Frontend component (LOC, per `.tsx` component)**

| Band | Range |
|---|---|
| Green | ≤ 200 |
| Yellow | 201–400 |
| Red | > 400 |

**Data-derived tightening option (repo-specific, complementary — not a replacement).** Against ARI's actual distribution, the file-size gate lands naturally at **> 500 (warn), > 800 (review), > 1200 (split-required)**: that yields ~15 production-Python files > 800 and 5 > 1200, plus 5 frontend files > 800 and 1 > 1200. The checker subtask may adopt these as an *interim* ratchet (the canonical > 2000 "Red" is only breached by 3 production files today, so it under-flags). This is offered as an option, not a change to the canonical table above.

---

## 5. Metric catalog

For each metric: **what** it is, **how** it is measured (tool now / AST fallback later), the **command** or heuristic, **scope**, and the **current known signal** from the verified baseline.

### 5.1 Cyclomatic Complexity (CC)
- **Now (zero-install):** ruff McCabe. `ruff check ari-core --select C901 --config "lint.mccabe.max-complexity=10"` flags every function over the Green band; raise/lower `max-complexity` to probe the 15/30 bands.
- **Later (richer):** radon after it is added as a dev/optional dep — `radon cc ari-core -s -a` (per-function CC letter grades + average).
- **AST fallback (design):** `check_complexity.py` walks `ast` counting decision points (`If/For/While/And/Or/comprehension/except/assert/ternary`) per `FunctionDef`/`AsyncFunctionDef`.
- **Scope:** all in-scope Python (§3.1), production cohort gated.
- **Current signal:** **unmeasured** — no `C901` selection active, radon absent. Baseline = 0 data points.

### 5.2 Cognitive Complexity proxy
- **How:** no installed tool computes it (radon does CC/MI/raw/Halstead, not cognitive). The AST fallback `check_complexity.py` approximates the SonarSource model: +1 per control-flow break, **+nesting-depth penalty** for nested structures, +1 per boolean-operator sequence. Reported alongside CC as an orthogonal "how hard to *read*" signal.
- **Scope:** production Python; the same functions CC flags.
- **Current signal:** **unmeasured** (no tool). To be produced by the AST fallback.

### 5.3 Function length
- **How:** AST line span of module-level `FunctionDef`/`AsyncFunctionDef` (`end_lineno - lineno + 1`); radon `raw` as cross-check once installed.
- **Threshold:** function table (§4): ≤50/51–80/81–120/>120.
- **Scope:** production Python; tests advisory.
- **Current signal:** unmeasured per-function; the 15 files >800 LOC (§6) are the likely reservoirs of >120-line functions.

### 5.4 Method length
- **How:** same AST span but restricted to `FunctionDef` nodes whose parent is a `ClassDef` (distinguishes methods from module functions in the report).
- **Threshold:** same as function table (§4).
- **Scope:** production Python classes.
- **Current signal:** unmeasured. The MCP `src/server.py` files and `agent/loop.py` are the primary method-length suspects.

### 5.5 Class size
- **How:** AST line span of `ClassDef`.
- **Threshold:** class table (§4): ≤300/301–500/501–700/>700.
- **Scope:** production Python.
- **Current signal:** unmeasured per-class.

### 5.6 File size
- **How:** `wc -l`, split by production vs test cohort (§3.3), Python and TS/TSX separately.
- **Threshold:** file table (§4) for Python; frontend table for `.tsx`.
- **Scope:** all in-scope files minus §3.2 exclusions.
- **Current signal:** **fully measured** — see the large-file tiers in §6. Red-band (>2000) production Python: `ari-skill-paper/src/server.py` 2956, `ari-skill-transform/src/server.py` 2465, `ari-skill-paper-re/src/_paperbench_bridge.py` 2376 (3 files).

### 5.7 Import count (fan-out)
- **How:** AST count of `Import`/`ImportFrom` targets per module.
- **Threshold:** **no master-prompt band exists**; propose a repo-derived advisory warn at **>30 imports/module** (label: advisory, not canonical).
- **Scope:** production Python.
- **Current signal:** unmeasured; correlated with the `E402` count below.

### 5.8 Reverse import count (fan-in / blast radius)
- **How:** build an import graph across `ari-core/ari` (AST resolve of `ImportFrom` to internal modules) and count in-edges per module; `grep -rl "import <mod>"` as a coarse cross-check. High fan-in = high change-blast-radius = argues for stability/`KEEP`.
- **Threshold:** advisory ranking, not a hard gate.
- **Scope:** `ari-core/ari` internal graph; `ari.public.*` is expected to be high fan-in by design (it is the contract surface — only 148 LOC, §6, so high-fan-in-but-tiny is *good* here).
- **Current signal:** unmeasured; to be produced by the planned `analyze_references.py` (§8).

### 5.9 Circular imports
- **How:** cycle detection on the same import graph (Tarjan SCC) in the planned `check_import_boundaries.py`. `compileall` and ruff do **not** detect cycles. The live **`E402` = 135** (module-import-not-at-top) count is a strong *proxy* for cycle-breaking hacks (deferred imports) and should be cross-referenced.
- **Threshold:** any true cycle = `REVIEW_REQUIRED`.
- **Scope:** `ari-core/ari`; also skill `src/` internally.
- **Current signal:** unmeasured directly; 135 `E402` hits flag where deferred-import workarounds already live.

### 5.10 Duplicate code candidates
- **How:** no installed duplicate detector (pylint availability not confirmed this run). Plan a token-/AST-shingling detector (normalize identifiers, hash k-line windows) in `check_dead_code.py`/a dup pass. **Highest-value target: the 14 `ari-skill-*/src/server.py` files**, which almost certainly share MCP tool-registration/boilerplate scaffolding.
- **Threshold:** report clone clusters ≥ N lines (N tuned in checker subtask); each cluster = `REVIEW_REQUIRED` (candidate `MERGE`).
- **Scope:** cross-skill `src/`, plus `viz/api_*.py` (many parallel endpoint modules).
- **Current signal:** unmeasured.

### 5.11 Direct file I/O in algorithmic code
- **How:** grep for raw I/O (`open(`, `.write_text`/`.read_text`, `os.remove`, `shutil.`, `Path(...).mkdir`) inside the *algorithmic core* — `ari-core/ari/{orchestrator,pipeline,agent,evaluator}` — which should route through `ari/paths.py`, `ari/public/paths.py`, `ari/checkpoint.py`, or `ari/container.py`. Ties directly to the checkpoint-scoped / determinism design principle.
- **Command (illustrative):** `grep -rnE "\bopen\(|write_text|read_text|shutil\.|os\.(remove|makedirs)" ari-core/ari/orchestrator ari-core/ari/pipeline ari-core/ari/agent ari-core/ari/evaluator`
- **Threshold:** each hit outside the path/checkpoint helpers = `REVIEW_REQUIRED`.
- **Current signal:** unmeasured count (grep to be baselined by the checker subtask).

### 5.12 Direct model API call in orchestration code
- **How:** grep for model-call symbols (`litellm`, `acompletion`/`completion(`, `openai`, `ChatCompletion`, `anthropic`, `ollama`) inside orchestration layers `ari-core/ari/{orchestrator,pipeline,cli,agent}` that should delegate to `ari.public.llm` / `ari/llm/`. **Skill-side model calls are legitimate** (e.g. `ari-skill-paper-re/src/_litellm_completer.py` 521 LOC) and are *excluded* from this metric — only orchestration-layer direct calls are flagged.
- **Command (illustrative):** `grep -rnE "litellm|acompletion|ChatCompletion|openai\.|anthropic\.|ollama" ari-core/ari/orchestrator ari-core/ari/pipeline ari-core/ari/cli ari-core/ari/agent`
- **Threshold:** each orchestration-layer hit = `REVIEW_REQUIRED`.
- **Current signal:** unmeasured.

### 5.13 Hardcoded prompt count
- **How:** prompts are **already partially externalized** to `ari-core/ari/prompts/*.md` (loaded via `prompts/_loader.py`): `agent/system.md`; `evaluator/{extract_metrics,peer_review}.md`; `orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,root_idea_selector}.md`; `pipeline/keyword_librarian.md`; `viz/{wizard_chat_goal,wizard_generate_config}.md`. Skills carry their own (`ari-skill-paper-re/src/prompts/`, `ari-skill-replicate/src/prompts/`). The metric inventories **remaining inline prompts**: heuristic grep for long triple-quoted strings and role markers (`"You are"`, `role":"system"`, `system_prompt`) in the large `src/server.py`, `agent/loop.py` (1630), `pipeline/orchestrator.py` (913), and `evaluator/*` files.
- **Command (illustrative):** `grep -rnE "You are|system_prompt|role\"?\s*[:=]\s*\"system" ari-core/ari ari-skill-*/src`
- **Threshold:** each surviving inline prompt = candidate for externalization (feeds the future `check_prompts.py`).
- **Current signal:** partial — externalization exists; the residual inline count is unmeasured.

### 5.14 Path literal usage
- **How:** grep for hardcoded path strings (`"workspace/"`, `"checkpoints/"`, `.ari`, absolute `/`-rooted literals, string-concatenated paths) that bypass `paths.py`/`PathManager`. This **extends the precedent already enforced** by `.github/workflows/refactor-guards.yml`, whose `no-new-home-ari-refs` job already fails PRs that add new `~/.ari/` references outside `migrations/`.
- **Command (illustrative):** `grep -rnE "\"(workspace|checkpoints|staging|experiments)/|~/?\.ari|/home/" ari-core/ari`
- **Threshold:** each non-helper path literal = `REVIEW_REQUIRED` (candidate to route through `paths.py`). New `~/.ari` additions are already a hard CI fail.
- **Current signal:** `~/.ari` additions already gated; broader path-literal count unmeasured.

### 5.15 Global mutable state
- **How:** AST heuristic — module-level assignments to mutable literals (`{}`, `[]`, `set()`), module-level singletons/caches, and `global` statements. Prime suspects: `ari-core/ari/viz/state.py`, `viz/state_sync.py` (dashboard shared state), `ari/cost_tracker.py`, `ari/pidfile.py`.
- **Command (illustrative):** `grep -rnE "^[A-Za-z_]+\s*[:=]\s*(\{\}|\[\]|set\(\))|^\s*global\s" ari-core/ari`
- **Threshold:** each module-level mutable singleton = `REVIEW_REQUIRED` (thread/determinism risk; ties to design principle P2).
- **Current signal:** unmeasured.

### 5.16 Dashboard component size (backend `viz/`)
- **How:** file-size + endpoint-count per `ari-core/ari/viz/*.py` (route/API modules). `viz/` is **8,131 LOC = 27% of core** — the single largest package. Report both the module LOC and the number of route handlers per `api_*.py`.
- **Threshold:** file table (§4) for LOC; endpoint-density is advisory.
- **Current signal (measured):** `viz/routes.py` **1197**, `viz/api_experiment.py` **929**, `viz/api_paperbench.py` **813**, `viz/api_settings.py` **553** — all Orange/Yellow band. These are the **dashboard API contract surface**; any split must ship a compatibility adapter so `frontend/src/services/api.ts` (863) keeps its endpoints.

### 5.17 Frontend component complexity
- **How:** LOC per `.tsx` (`wc -l`) is the *available* proxy today. True complexity (JSX nesting depth, hook count, branch count) needs **ESLint + a complexity rule**, which does not exist yet (§2) — its addition is a later frontend subtask. Interim gates: `npm run typecheck`, `npm test` (vitest), `npm run build`. **`npm run lint` does not exist.**
- **Threshold:** frontend table (§4): ≤200/201–400/>400.
- **Current signal (measured, Red > 400):** `Results/resultSections.tsx` **1590**, `Wizard/StepResources.tsx` **1160**, `Settings/SettingsPage.tsx` **1049**, `Workflow/WorkflowPage.tsx` **964**, `services/api.ts` **863** (API client, not a visual component), `Workflow/workflowNodes.tsx` **770**, `Wizard/StepGoal.tsx` **528**, `Results/PaperWorkspace.tsx` **519**, `Monitor/MonitorPage.tsx` **502** — 8 real components far past the 400 Red line.

---

## 6. Verified baseline snapshot (facts, not estimates)

All figures below were observed live at the repo on 2026-07-01.

**Core package.** `ari-core/ari` = **30,277 LOC** of production `*.py`. Per subdir:

| Subdir | LOC | | Subdir | LOC |
|---|---:|---|---|---:|
| viz | **8,131** | | evaluator | 1,261 |
| pipeline | 3,900 | | llm | 1,234 |
| agent | 3,303 | | config | 773 |
| orchestrator | 2,996 | | publish | 756 |
| cli | 2,582 | | clone | 665 |
| (top-level `.py`) | 2,796 | | registry | 511 |
| mcp | 495 | | memory / migrations / **public** / configs / protocols / prompts / schemas | 343 / 170 / **148** / 69 / 63 / 61 / 20 |

`viz` alone is **27%** of core; the frozen contract surface `public/` is only **148 LOC** (small-and-central — the ideal shape).

**Skill packages (`src/` production LOC):** paper-re **5,843**; paper **4,278**; transform **3,180**; memory 2,876; idea 1,916; replicate 1,684; orchestrator 1,043; hpc 1,004; evaluator 983; plot 802; web 712; coding 644; benchmark 175; vlm 355. Combined ≈ 25.5k LOC across 14 skills.

**Ruff baseline — `ruff check ari-core --statistics` (661 errors, 358 auto-fixable):**

| Rule | Count | Fixable |
|---|---:|---|
| `F401` unused-import | **341** | auto |
| `E402` module-import-not-at-top | 135 | — |
| `E702` multiple-statements-semicolon | 54 | — |
| `F841` unused-variable | 39 | — |
| `E701` multiple-statements-colon | 37 | — |
| `F541` f-string-missing-placeholders | 28 | auto |
| `E741` ambiguous-variable-name | 11 | — |
| `F811` redefined-while-unused | 8 | — |
| `E401` multiple-imports-one-line | 7 | auto |
| `E731` lambda-assignment | 1 | — |

A one-shot `ruff check ari-core --fix` clears 358 immediately (341 of them just `F401`), leaving ~303 real-signal findings (`E402`/`E702`/`E701`/`F841`…). **Note:** this 661 figure is `ari-core` only; `ruff check .` also scans `ari-skill-*`, `scripts/`, and report tooling — the skills were **not** individually linted in this baseline (unconfirmed cohort).

**Large production Python files (measured `wc -l`).**

- **> 1200 LOC (5):** `ari-skill-paper/src/server.py` 2956, `ari-skill-transform/src/server.py` 2465, `ari-skill-paper-re/src/_paperbench_bridge.py` 2376, `ari/agent/loop.py` 1630, `ari-skill-paper-re/src/server.py` 1395.
- **800–1200 (10):** `viz/routes.py` 1197, `ari-skill-orchestrator/src/server.py` 1043, `ari-skill-evaluator/src/server.py` 983, `viz/api_experiment.py` 929, `llm/cli_server.py` 919, `pipeline/orchestrator.py` 913, `cli/bfts_loop.py` 911, `orchestrator/bfts.py` 845, `viz/api_paperbench.py` 813, `ari-skill-plot/src/server.py` 802.
- **Notable 500–800:** `ari-skill-web/src/server.py` 712, `ari-skill-paper-re/src/_replicator_agent.py` 730, `evaluator/llm_evaluator.py` 723, `ari-skill-replicate/src/generator.py` 695, `orchestrator/node_report/builder.py` 652, `ari-skill-coding/src/server.py` 644, **`ari/config/__init__.py` 628** (large for a config-*locator*), `orchestrator/lineage_decision.py` 593, `cli/run.py` 575, `viz/api_settings.py` 553.

**Frontend (`viz/frontend/src`, TS/TSX, node_modules excluded).** > 1200: `Results/resultSections.tsx` **1590** (only one). 800–1200: `Wizard/StepResources.tsx` 1160, `Settings/SettingsPage.tsx` 1049, `Workflow/WorkflowPage.tsx` 964, `services/api.ts` 863. 500–800: `Workflow/workflowNodes.tsx` 770, `Wizard/StepGoal.tsx` 528, `Results/PaperWorkspace.tsx` 519, `Monitor/MonitorPage.tsx` 502.

---

## 7. Initial hotspot worklist

Ranked by measured evidence. These are the entries the measurement pipeline should resolve first; the tag is a *provisional* pointer to the decision-subtask, **not** a final classification (that belongs to the per-area subtasks).

| # | Target | Metric hit | Tag (provisional) | Note |
|---|---|---|---|---|
| 1 | `ari-skill-paper/src/server.py` (2956) | file size Red | `REVIEW_REQUIRED` | Largest file in repo; MCP tool contract — split needs contract-preserving module layout |
| 2 | `ari-skill-transform/src/server.py` (2465) | file size Red | `REVIEW_REQUIRED` | MCP contract; check for shared boilerplate (§5.10) |
| 3 | `ari-skill-paper-re/src/_paperbench_bridge.py` (2376) | file size Red | `REVIEW_REQUIRED` | Private module (`_`-prefixed) — more freedom to split |
| 4 | `ari/agent/loop.py` (1630) | file size Orange; inline-prompt suspect (§5.13) | `REVIEW_REQUIRED` | ReAct loop; check hardcoded prompts + method length |
| 5 | `ari/viz/routes.py` (1197) + `api_experiment.py` (929) + `api_paperbench.py` (813) | dashboard component size | `REVIEW_REQUIRED` | Dashboard API contract — split only behind an adapter for `services/api.ts` |
| 6 | `viz/frontend/.../resultSections.tsx` (1590) | frontend Red (×4 canonical) | `REVIEW_REQUIRED` | 8 components over the 400 line; needs ESLint complexity rule (§5.17) |
| 7 | `llm/cli_server.py` (919), `pipeline/orchestrator.py` (913), `cli/bfts_loop.py` (911), `orchestrator/bfts.py` (845) | file size; direct-model-call / global-state suspects | `REVIEW_REQUIRED` | Orchestration layer — priority targets for §5.11/§5.12/§5.15 |
| 8 | `ari/config/__init__.py` (628) | file size Yellow, semantic outlier | `REVIEW_REQUIRED` | A config *locator* should not be this large; also the `config/` vs `configs/` confusability (§3.4) |
| 9 | 14 × `ari-skill-*/src/server.py` | duplicate-code candidates (§5.10) | `REVIEW_REQUIRED` | Likely shared MCP scaffolding — candidate `MERGE` into shared helper |
| 10 | ruff `F401` ×341, `E402` ×135 | lint baseline | `ADAPT` | `--fix` clears 341 `F401`; the 135 `E402` cross-reference circular-import work (§5.9) |

---

## 8. Tooling to design as later subtasks (do NOT implement here)

These checker scripts are *named and scoped* by the master plan but **do not exist** today (`scripts/` currently holds only `docs/`, `readme_sync.py`, `git-hooks/`, `run_all_tests.sh`, `sc_paper_*`, `build_pb_images.sh`, `setup/`, `letta/`, `registry/`, `fewshot/`, GPU monitors). Their design is owned by later subtasks:

| Planned script | Feeds metric(s) | Notes |
|---|---|---|
| `check_complexity.py` | §5.1–5.6 | AST fallback for CC + cognitive proxy + length/class/file; **must encode the §3.3 test-vs-prod policy** |
| `check_import_boundaries.py` | §5.8, 5.9 | import graph, fan-in, cycle (Tarjan) detection |
| `analyze_references.py` | §5.8 | reverse-import ranking / blast radius |
| `check_dead_code.py` | §5.10 | duplicate clusters + unused symbols |
| `check_prompts.py` | §5.13 | inline-prompt inventory vs `prompts/*.md` |
| `check_directory_policy.py` | §3.4, §5.14 | `config/` vs `configs/` (no `sonfigs/`) + path-literal policy |
| `check_public_api_contracts.py` / `check_viz_api_schema.py` | contract guard | ensures a split does not move `ari.public.*` / dashboard endpoints |
| `generate_quality_report.py` | all | aggregates the above into one report (downstream of this plan) |
| `check_dashboard_ux.py` | §5.16, 5.17 | frontend size/UX gate |

Two overlaps to respect: (a) a `check_docs_source_sync.py` idea **partially overlaps** the *existing* `scripts/docs/check_doc_sources.py` — reconcile, don't duplicate; (b) any complexity gate should reuse, not fork, the CI install steps already in `refactor-guards.yml`.

**radon decision.** Before `radon cc ari-core -s -a` / `radon mi ari-core -s` can run, radon must be added as a **dev/optional dependency** (candidate: an `[optional-dependencies]`/dev group in `ari-core/pyproject.toml`, or a `requirements-dev.txt`). Until then, the **ruff `C901`** path (§5.1) and the AST fallback are the measurement engines — both are zero-install today.

---

## 9. Integration points (design only — not wired in this subtask)

- **pre-commit:** `scripts/git-hooks/pre-commit` exists but is single-purpose (README sync) and explicitly *non-blocking / no network / no LLM*. A future complexity check would slot in as an additional, likewise non-blocking, local hint — the CI gate remains the enforcement point (matching the repo's existing "hook hints, CI enforces" pattern).
- **CI:** `.github/workflows/refactor-guards.yml` already runs the test suite under a redirected `HOME` and diffs against the merge base for `~/.ari` additions. A complexity/lint ratchet job should mirror its install sequence (`pip install -r requirements.txt`; editable `ari-skill-memory` then `ari-core`) rather than inventing a new one. There are 5 workflows total; **do not rewrite them wholesale**, and note the repo has **no** `ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`, `dependabot.yml`, `CODEOWNERS`, or `.github/actions/`.
- **Ratchet strategy:** freeze today's ruff baseline (661 → ~303 after `--fix`) and forbid regressions; introduce CC/length gates as *warn-only* first, then promote bands to *block* per area as each refactoring subtask lands.

---

## 10. Command runbook

Copy-paste, deterministic. Run from repo root `/home/t-kotama/workplace/ARI`.

```bash
# --- Python complexity (zero-install, ruff McCabe) ---
ruff check ari-core --select C901 --config "lint.mccabe.max-complexity=10"   # CC > 10 offenders
ruff check ari-core --statistics                                              # lint baseline (661 today)
ruff check .                                                                  # whole-repo (also scans skills/scripts)

# --- Python complexity (richer; ONLY after radon is added as a dev dep) ---
radon cc ari-core -s -a      # per-function cyclomatic complexity + average
radon mi ari-core -s         # maintainability index per module

# --- Syntax / import smoke + behavior gates ---
python -m compileall .        # every module imports/compiles
pytest -q                     # ari-core/tests (testpaths in pytest.ini); full suite: bash scripts/run_all_tests.sh

# --- File-size cohorts (production vs tests handled by the checker; wc for now) ---
find ari-core/ari ari-skill-*/src -name '*.py' -not -path '*__pycache__*' | xargs wc -l | sort -rn | head -30

# --- Frontend (from ari-core/ari/viz/frontend; NO pnpm, NO lint script) ---
npm test           # vitest run
npm run build      # vite build
npm run typecheck  # tsc --noEmit
find ari-core/ari/viz/frontend/src -name '*.tsx' | xargs wc -l | sort -rn | head -20   # excludes node_modules
```

---

## 11. Relationship to subtasks 001 and 025

This is **subtask 002** and sits between two sibling subtasks in the master refactoring map. As of 2026-07-01 the `docs/refactoring/subtasks/` and `docs/refactoring/reports/` directories are **empty** — subtasks 001 and 025 are not yet authored, so their precise scope is authoritative in those documents once written; the description below is this plan's functional interface to them, not a specification of their contents.

- **Upstream — subtask 001 (repository inventory / baseline census).** Provides the canonical file/module inventory that this plan *measures over*. The exclusion set (§3.2), the config/configs/no-sonfigs clarification (§3.4), and the 14-skill / `viz`-is-27% shape (§6) are the inventory facts 002 consumes. If 001 revises the inventory, 002's scope tables inherit the change.
- **Downstream — subtask 025 (quality-report generation / CI enforcement).** Consumes this plan's metric catalog (§5), thresholds (§4), and checker designs (§8) to produce `generate_quality_report.py` and the CI ratchet (§9). The test-vs-prod policy left open in §3.3 must be *decided and encoded* by 025's `check_complexity.py`.

Once 001 and 025 are authored, cross-link them here.

---

## 12. Open questions / risks

1. **CC is baseline-zero.** No cyclomatic data exists today; the plan depends on either enabling ruff `C901` (now) or adding radon (later). Pick one before gating — do not gate on an unmeasured metric.
2. **Test cohort policy (§3.3)** is unresolved; the six >1000-LOC test files will dominate any naive file-size gate.
3. **Skills not yet linted** — the 661-finding baseline is `ari-core` only; `ari-skill-*` must be linted per-package (mirroring `scripts/run_all_tests.sh`'s per-skill-process pattern, since cross-skill `src/server.py` imports collide in one process).
4. **Frontend true-complexity needs ESLint**, which does not exist yet; until a later subtask adds it, frontend complexity is LOC-proxy only.
5. **Duplicate-code detector engine** is unchosen (no jscpd; pylint availability unconfirmed) — the AST-shingling approach in §5.10 is the fallback assumption.
6. **Dashboard/skill splits touch contracts.** Any file-size remediation on `viz/*.py` (dashboard API) or `ari-skill-*/src/server.py` (MCP tools) must ship a compatibility adapter; this plan only measures them, it does not authorize a breaking split.

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
