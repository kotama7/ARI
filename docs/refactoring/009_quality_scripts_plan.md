# 009 — Quality Scripts Plan

- **Status:** Planning only (no runtime code, config, workflow, prompt, or directory changes in this document).
- **Planning date:** 2026-07-01
- **Repo:** `/home/t-kotama/workplace/ARI` — `main`, ari-core `0.9.0`.
- **Scope:** Design the `scripts/` quality-check suite (11 net-new checkers + one aggregator), reconcile it with the existing `scripts/docs/` and `report/scripts/` gate families, and define a common CLI contract, allowlist model, and **warning-mode-first** rollout.
- **Out of scope:** Implementation. Every checker named here is a *design target* delivered by a later subtask (see §10). Nothing in this document is wired into a workflow.

---

## 1. Why this document exists

ARI has a mature *documentation/i18n* gate family under `scripts/docs/` and a *report-build* gate family under `report/scripts/`, but it has **no source-code quality suite**: no complexity gate, no import-boundary enforcement, no `ari.public.*` contract snapshot, no dashboard-API↔frontend coupling check, no dead-code scan, and no aggregated quality report. The 11 proposed scripts fill that gap.

Two hard constraints shape every design decision below:

1. **Complement, do not duplicate.** Several proposed names overlap conceptually with existing checkers (`check_docs_source_sync` ↔ `check_doc_sources.py` + `check_ref_coupling.py`; `check_prompts` ↔ `report/scripts/check_prompt_snapshots.py` Gate 10; `check_directory_policy` ↔ `readme_sync.py`). Where an existing checker already covers a direction, the new script must add a *different* dimension or be dropped (see §4).
2. **Warning-mode-first.** The measured baseline is large (30,277 LOC in `ari-core/ari` alone; 661 ruff findings; 15 production Python files >800 LOC). Turning that historical debt into red CI on day one would block every unrelated PR. Every checker ships `--warning-only` and a frozen **allowlist/baseline**, and enters CI as advisory (`continue-on-error` or `exit 0`) before any ratchet is proposed.

Verified negative: **all 11 proposed script names are absent** from the repo today (`grep` over `*.py`/`*.sh`/`*.yml`/`*.md`, excluding `node_modules` and `docs/refactoring/`). Every one is a net-new file — none is a rename of an existing checker.

---

## 2. Tooling baseline (measured 2026-07-01)

| Tool | State | Consequence for this plan |
|---|---|---|
| `radon` | **NOT installed** (`import radon` → `ModuleNotFoundError`) | `check_complexity` cannot assume radon. Either add it as a dev dep or use ruff's McCabe (`C901`). |
| `ruff` | **installed, 0.15.2** | Reusable engine for `check_dead_code` (`F401`/`F841`), `check_complexity` (`C901`), and lint hotspots. Not wired into any workflow today. |
| `vulture` | **NOT installed** (`import vulture` → `ModuleNotFoundError`) | `check_dead_code` should lean on ruff `F401`/`F811`/`F841` + a custom reachability pass rather than assume vulture. |
| `python` / `compileall` / `pytest` | available (3.13.2) | AST-based checkers (import graph, public-API, prompt scan) can parse with stdlib `ast`. |
| `node` + `npm` | available; **no `pnpm`** | `check_viz_api_schema` / `check_dashboard_ux` must not shell out to `pnpm`. |
| `PyYAML` | available (already the only non-stdlib dep in `scripts/docs/`) | Reuse for config/allowlist parsing. |

Ruff baseline to freeze (from `ruff check ari-core --statistics`, 661 total): `F401` unused-import **341** (auto-fixable), `E402` **135**, `E702` **54**, `F841` **39**, `E701` **37**, `F541` **28**, `E741` **11**, `F811` **8**, `E401` **7**, `E731` **1**. No `C901` (McCabe) rule is active, so **cyclomatic complexity is entirely unmeasured today** — `check_complexity` establishes that baseline from zero.

---

## 3. Common script contract (all 11 scripts)

To match the house style already set by `scripts/docs/` (each file: `#!/usr/bin/env python3`, module docstring citing a design doc, `argparse`, `REPO_ROOT = Path(__file__).resolve().parents[N]`, PyYAML-only non-stdlib dep, staged warn→error rollout), every new checker in `scripts/` (top level, alongside `readme_sync.py`) conforms to:

**Language / deps.** Python 3.13, stdlib + PyYAML only where a checker parses YAML config. No LLM calls, no network. (This preserves the `scripts/docs/` determinism convention and aligns with design principle P2.)

**Flags (canonical set — every checker accepts all of these, ignoring the ones that do not apply):**

| Flag | Meaning |
|---|---|
| `--target <path>` | Restrict the scan to a subtree (default: repo-relevant root, e.g. `ari-core/ari` or the whole repo). Enables per-package rollout. |
| `--config <file>` | Path to the checker's YAML config (thresholds, roots, role vocab). Default: a sibling `scripts/quality/<name>.yaml` (new dir, created by the first implementing subtask; does **not** exist yet). |
| `--output <file>` | Write the report to a file instead of stdout. |
| `--format markdown\|json` | `json` is the machine-readable building block consumed by the aggregator (§ generate_quality_report); `markdown` is the human report. Mirrors the existing `--json` flag but adds an explicit Markdown emitter. |
| `--warning-only` | Force exit 0 regardless of findings (advisory mode). This is the **default posture** while a checker is new. |
| `--fail-on-regression` | Exit non-zero **only** when findings exceed the frozen allowlist/baseline (net-new debt), never on pre-existing entries. This is the ratchet mode adopted after the warning period. |

**Allowlist / baseline.** Each checker reads an allowlist (a `known-offenders` list keyed by stable identity — file path, `module→module` edge, symbol qualname, or endpoint name — with an optional justification string). Findings on allowlisted identities are reported as `known` (not `new`) and never fail `--fail-on-regression`. This is the mechanism that keeps historical debt out of CI while still blocking *new* debt. Convention: allowlists live next to the config as `scripts/quality/<name>.allow.yaml`.

**Reports.** Markdown report = human triage table (severity, identity, location, note). JSON report = a stable schema `{ "checker": str, "version": int, "target": str, "summary": {counts}, "findings": [ {id, severity, file, line, kind, message, allowlisted: bool} ] }` so the aggregator can merge heterogeneous checkers without bespoke parsing.

**Exit convention (matches `scripts/docs/`):** `0` = clean or `--warning-only`; `1` = findings above threshold (only when not `--warning-only`, or under `--fail-on-regression` with net-new debt); `2` = usage/environment error (e.g. missing PyYAML), same as `check_doc_sources.py`'s `SystemExit(2)`.

**Wiring rule.** No checker is added to `.github/workflows/*` in its delivering subtask beyond `continue-on-error: true` (advisory). Promotion to a hard gate is a *separate, later* decision with its own subtask and requires the allowlist to be frozen first. The 5 existing workflows (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`, `refactor-guards.yml`) are **not rewritten**.

---

## 4. Reconciliation with existing checkers (overlap matrix)

Existing gate inventory (all confirmed by reading source):

- `scripts/` top level: `readme_sync.py` (per-dir README `## Contents` drift, `--check`/`--write`), `run_all_tests.sh` (per-skill pytest isolation), `git-hooks/pre-commit` (runs `readme_sync --write`, non-blocking `exit 0`).
- `scripts/docs/`: `check_doc_sources.py`, `check_doc_links.py`, `check_i18n_js.py`, `check_readme_parity.py`, `check_ref_coupling.py`, `check_report_cochange.py`, `check_site_i18n.py`, `check_translation_freshness.py`, `sync_report_pdf.sh`, `assemble_site.sh`.
- `report/scripts/`: `check_prompt_snapshots.py` (**Gate 10**), `snapshot_prompts.py`, `check_i18n.py` (Gate 6), plus `check_bib/glossary/figures/notation/tikz/toc_consistency/logs_for_secrets.py`.

Classification of each proposed script against that inventory (vocabulary: KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED):

| Proposed script | Nearest existing coverage | Verdict | Rationale |
|---|---|---|---|
| `check_complexity.py` | none (no radon, no `C901`) | **KEEP** (net-new) | No LOC/cyclomatic gate exists anywhere. |
| `check_import_boundaries.py` | `refactor-guards.yml` inline `~/.ari` diff-grep (a *content ban*, not an import graph) | **KEEP** (net-new) | No `ari.public.*` / core→skill boundary is enforced. |
| `check_docs_source_sync.py` | `check_doc_sources.py` (forward) **+** `check_ref_coupling.py` (reverse) | **REVIEW_REQUIRED → likely MERGE/DELETE_CANDIDATE** | Both directions already covered. A new file duplicates them unless it adds a *distinct* dimension. See §5.3 — recommended outcome is **do not create a new script**; extend the existing pair instead. |
| `check_directory_policy.py` | `readme_sync.py` (every dir README lists all files) | **KEEP for the new part** (PARTIAL OVERLAP) | README-enumeration is covered; **placement/naming policy** (e.g. `config/` vs `configs/`, no `sonfigs/`, legacy-dir bans) is not. Scope the new script to policy only, delegate enumeration to `readme_sync.py`. |
| `check_public_api_contracts.py` | none | **KEEP** (net-new) | No gate/snapshot over `ari.public.*`. |
| `check_viz_api_schema.py` | none | **KEEP** (net-new) | No gate couples `viz/routes.py`+`api_*.py` to frontend `services/api.ts`. |
| `check_prompts.py` | `report/scripts/check_prompt_snapshots.py` (Gate 10) | **KEEP for the new part** (PARTIAL OVERLAP) | Gate 10 already byte-verifies `ari-core/ari/prompts/**/*.md` snapshots. The **inline-prompt inventory** (hardcoded strings in `agent/loop.py`, `*/server.py`) is new; the snapshot slice must **not** be re-implemented — call Gate 10 or leave it alone. |
| `check_dashboard_ux.py` | `check_i18n_js.py` (landing JS only) | **KEEP** (net-new) | `check_i18n_js.py` covers `docs/i18n/landing.*.js`, **not** the React `frontend/src/i18n/{en,ja,zh}.ts` triple (444/441/441 LOC). |
| `analyze_references.py` | `check_ref_coupling.py` (doc↔source), `report/scripts/check_bib.py` (bibliography) | **KEEP** (net-new) | Neither analyzes *code* cross-references/dependencies. Name collides conceptually only. |
| `check_dead_code.py` | none (no vulture; ruff `F401` unused) | **KEEP** (net-new) | Reuse ruff `F401`/`F811`/`F841`; add a reachability pass. |
| `generate_quality_report.py` | none (every checker emits JSON, nothing aggregates) | **KEEP** (net-new) | Aggregator over the other checkers' JSON. |

**Net:** 10 KEEP (net-new or new-slice-only), 1 REVIEW_REQUIRED/likely-drop (`check_docs_source_sync`).

---

## 5. Per-script design blocks

Each block: **purpose / what it detects / inputs / outputs / overlap note / classification**. Threshold anchors are data-derived from the measured baseline in §2 and the file-size census below.

Production-Python size census (measured `wc -l`, for the complexity/split thresholds): >1200 LOC (5): `ari-skill-paper/src/server.py` 2956, `ari-skill-transform/src/server.py` 2465, `ari-skill-paper-re/src/_paperbench_bridge.py` 2376, `ari-core/ari/agent/loop.py` 1630, `ari-skill-paper-re/src/server.py` 1395. 800–1200 (10): `ari-core/ari/viz/routes.py` 1197, `ari-skill-orchestrator/src/server.py` 1043, `ari-skill-evaluator/src/server.py` 983, `ari-core/ari/viz/api_experiment.py` 929, `ari-core/ari/llm/cli_server.py` 919, `ari-core/ari/pipeline/orchestrator.py` 913, `ari-core/ari/cli/bfts_loop.py` 911, `ari-core/ari/orchestrator/bfts.py` 845, `ari-core/ari/viz/api_paperbench.py` 813, `ari-skill-plot/src/server.py` 802. Frontend >800 (5): `Results/resultSections.tsx` 1590, `Wizard/StepResources.tsx` 1160, `Settings/SettingsPage.tsx` 1049, `Workflow/WorkflowPage.tsx` 964, `services/api.ts` 863.

### 5.1 `check_complexity.py` — file-size & cyclomatic-complexity gate

- **Purpose:** Establish and hold the (currently unmeasured) size/complexity baseline so refactors reduce, and new code does not add, oversized files/functions.
- **Detects:** (a) per-file LOC over data-derived tiers **>500 (warn), >800 (review), >1200 (split-required)** — yields ~15 production-Python offenders >800 and 5 >1200; (b) per-function cyclomatic complexity via **ruff `C901`** (preferred — ruff is present; `radon` is not) with a configurable `max-complexity`. Must explicitly decide **test inclusion**: `ari-core/tests/test_server.py` (1844), `test_gui_errors.py` (1650), `test_workflow_contract.py` (1606), `test_wizard.py` (1133) dominate any global LOC threshold — recommend excluding `tests/**` from the size gate by default, configurable via `--config`.
- **Inputs:** `--target` (default `ari-core/ari`; opt-in per-skill `src/` and `frontend/src/`), `--config` (tiers, `max-complexity`, include/exclude globs), allowlist of known large files.
- **Outputs:** Markdown table (file, LOC, tier, function, complexity) + JSON. Under `--fail-on-regression`, fails only when a file crosses a tier it was previously below or a new function exceeds `max-complexity`.
- **Overlap:** none. **Classification: KEEP.**

### 5.2 `check_import_boundaries.py` — layering / dependency-direction gate

- **Purpose:** Enforce the architectural contract that **skills import only from `ari.public.*`** (stated verbatim in `ari-core/ari/public/__init__.py`: "Skills must only import from `ari.public.*`") and that core→skill coupling stays intentional.
- **Detects (AST import graph, stdlib `ast`):** (a) any `ari-skill-*/src/**` importing `ari.<internal>` instead of `ari.public.*`; (b) reverse core→skill imports beyond the one sanctioned edge — `ari-core` importing `ari_skill_memory` directly (first core→skill dependency, v0.6.0) is the **allowlisted** exception; (c) cross-skill imports; (d) optionally, forbidden intra-core edges (e.g. `public/` importing back into heavy internals — `public/` is only 148 LOC of thin re-exports and must stay thin).
- **Inputs:** `--target` (repo root), `--config` (allowed-edge rules), allowlist seeded with the `ari_skill_memory` exception and any current violations.
- **Outputs:** Markdown edge table + JSON; optional DOT/edge-list for review. `--fail-on-regression` blocks new boundary violations only.
- **Overlap:** conceptually adjacent to `refactor-guards.yml`'s inline `~/.ari` grep, but that is a content ban, not an import graph — **no functional overlap**. **Classification: KEEP.** Contract note: this *enforces* the `ari-skill-* → ari-core` stable interface; it must not itself propose changing it.

### 5.3 `check_docs_source_sync.py` — docs↔source drift (REVIEW_REQUIRED)

- **Purpose (as proposed):** Verify docs front-matter `sources[].path` stays in sync with the tree.
- **Reality:** This is **already covered in both directions**: `check_doc_sources.py` hard-gates that every declared `sources[].path` resolves (forward) and validates the `role` vocab `{implementation,schema,config,prompt,test,vendor,doc}`; `check_ref_coupling.py` is the reverse change-coupling gate (a changed source must bump the referencing doc's `last_verified`). Investigation confirmed **no front-matter drift currently exists** — every declared source path resolves.
- **Recommendation:** **Do not create a new competing script.** Either (a) **MERGE**: fold any genuinely missing dimension (e.g. reporting docs whose `last_verified` is stale relative to a *content* change, not just a path move) into `check_ref_coupling.py`; or (b) **DELETE_CANDIDATE**: drop the name entirely. A net-new `check_docs_source_sync.py` that re-scans front-matter paths would duplicate `check_doc_sources.py` and add a maintenance burden. If a new file is nonetheless wanted, it must document precisely which dimension the existing pair does *not* cover; absent that, it is redundant.
- **Inputs/Outputs:** N/A pending the REVIEW decision. **Classification: REVIEW_REQUIRED → MERGE or DELETE_CANDIDATE.**

### 5.4 `check_directory_policy.py` — placement & naming policy gate

- **Purpose:** Enforce *where files live and what dirs are named* — the dimension `readme_sync.py` does not cover (it only enforces that each dir README enumerates its files).
- **Detects:** (a) the confusable **config trio** stays correctly separated — `ari-core/ari/config/` (Python *locator* code), `ari-core/ari/configs/` (packaged default *data*: `defaults.yaml`, `model_prices.yaml`), and top-level `ari-core/config/` (rubric/profile *data*) — and that **no `sonfigs/` directory is ever introduced** (verified absent today; the "sonfigs" token in upstream prompts is a typo, not a real path); (b) legacy/duplicate-dir bans (e.g. flag reintroduction of removed dirs, or new top-level checkpoint dirs given root `checkpoints/` already coexists with `workspace/checkpoints/`); (c) forbidden tracked artifacts by policy (e.g. vendored `node_modules/` under `frontend/`, `report/scripts/.venv/` + `__pycache__/` — known hygiene issues, allowlisted so they warn but don't block).
- **Inputs:** `--target` (repo root), `--config` (allowed/forbidden dir-name rules, path-placement rules), allowlist of current known-bad tracked paths.
- **Outputs:** Markdown policy-violation list + JSON.
- **Overlap:** PARTIAL with `readme_sync.py` — **scope this script to policy only**; delegate README enumeration to `readme_sync.py`. **Classification: KEEP (new slice).**

### 5.5 `check_public_api_contracts.py` — `ari.public.*` contract snapshot

- **Purpose:** Freeze the public API surface skills depend on so core refactors cannot silently break it. `ari/public/` is the frozen contract layer (148 LOC of thin re-exports over 8 submodules).
- **Detects (AST):** removal/rename of any public submodule or exported symbol vs a committed snapshot. Current surface (from `ari/public/__init__.py` docstring + files): `claim_gate` (`run_hard_gate`), `config_schema` (Pydantic models), `container`, `cost_tracker`, `llm` (`LLMClient`), `paths` (`PathManager`), `run_env` (`capture_env`, `shell_capture_snippet`), `verified_context` (`render_grounded_block`, `write_verified_context`). Also flag when a public module stops being a thin re-export (grows real logic).
- **Inputs:** `--target ari-core/ari/public`, `--config` (snapshot path), snapshot file (committed) acting as the allowlist/baseline.
- **Outputs:** Markdown diff (added/removed/changed symbols) + JSON; a `--update`-style regenerate mode analogous to `report/scripts/snapshot_prompts.py` (regenerate snapshot deliberately). Removals default to **error even in warning mode** once promoted, since this is an external contract.
- **Overlap:** none. **Classification: KEEP.** This *protects* a stable contract; it must never be used to justify breaking one without a compatibility-adapter note.

### 5.6 `check_viz_api_schema.py` — dashboard API ↔ frontend coupling

- **Purpose:** Keep the dashboard REST/WS surface (`ari/viz/routes.py` 1197 + the `api_*.py` family, e.g. `api_experiment.py` 929, `api_paperbench.py` 813) in sync with its sole consumer, the React client `frontend/src/services/api.ts` (863 LOC) + `websocket.py`.
- **Detects:** endpoint paths declared server-side that `services/api.ts` never calls (dead endpoints) and, conversely, client calls to paths no route serves (broken calls); optionally request/response shape drift if a shared schema is introduced. The root `README.md` REST endpoint table (lines ~285–302) and CLI table are a secondary source; port **8765** is the consistent base.
- **Inputs:** `--target ari-core/ari/viz`, `--config` (route-extraction patterns, ignore lists), allowlist of intentionally-server-only or client-only paths.
- **Outputs:** Markdown two-column reconciliation (server routes ↔ client calls) + JSON.
- **Overlap:** none (`check_i18n_js.py` is landing-JS only). **Classification: KEEP.** Contract note: dashboard API endpoints/schema are a preserved contract — this checker guards, never redefines, them.

### 5.7 `check_prompts.py` — inline-prompt externalization inventory

- **Purpose:** Track migration of hardcoded LLM prompts into the already-partially-externalized `ari-core/ari/prompts/` tree (loader `_loader.py`, `.md` templates for agent/evaluator/orchestrator/pipeline/viz).
- **Detects (the NEW slice):** likely inline/hardcoded prompt strings still living in large runtime files — `ari/agent/loop.py` (1630), `ari-skill-paper/src/server.py` (2956), `ari-skill-transform/src/server.py` (2465), evaluator/pipeline modules — using heuristics (long multi-line f-strings with role markers like "You are", "Return JSON", etc.), reported as externalization candidates.
- **Does NOT re-implement:** the **snapshot-consistency** slice. `report/scripts/check_prompt_snapshots.py` (**Gate 10**) already byte-verifies every `ari-core/ari/prompts/**/*.md` against `report/shared/appendix/prompts/**` via SHA-256 headers. `check_prompts.py` must **invoke or defer to Gate 10**, not duplicate it.
- **Inputs:** `--target` (repo root or per-package), `--config` (heuristic patterns, min length), allowlist of accepted inline prompts (e.g. tiny system strings not worth externalizing).
- **Outputs:** Markdown candidate inventory (file, line, snippet, size) + JSON.
- **Overlap:** PARTIAL with Gate 10 (snapshot slice only). **Classification: KEEP (inventory slice); MERGE/defer for snapshots.** Prompt templates are a documented/snapshotted surface — treat as REVIEW_REQUIRED before proposing any move.

### 5.8 `check_dashboard_ux.py` — React i18n / UX-consistency gate

- **Purpose:** Extend i18n parity enforcement to the dashboard React app, which `check_i18n_js.py` does not cover.
- **Detects:** key-set parity + duplicate keys across `frontend/src/i18n/{en.ts,ja.ts,zh.ts}` (444/441/441 LOC; `index.ts` is the barrel); optionally hardcoded user-facing strings in `.tsx` that bypass the i18n dictionary. Can reuse the parity/duplicate algorithm shape from `check_i18n_js.py` (which exports `keys_of`/`duplicates`/`parity_errors`), but the input is `.ts` object literals, not `landing.*.js`, so parsing differs.
- **Inputs:** `--target ari-core/ari/viz/frontend/src`, `--config` (i18n dir, string-literal ignore patterns), allowlist of intentional untranslated strings.
- **Outputs:** Markdown parity/duplicate report + JSON. Must run without `pnpm` (node/npm only) or, preferably, parse `.ts` statically with Python to stay in the stdlib+PyYAML lane like the other checkers.
- **Overlap:** none functional (landing vs React). **Classification: KEEP.**

### 5.9 `analyze_references.py` — code cross-reference / dependency analyzer

- **Purpose:** Provide the code-level reference map that no existing tool produces (the doc↔source coupler `check_ref_coupling.py` and the bibliography tools `report/scripts/check_bib.py` cover unrelated domains despite the name collision).
- **Detects / produces:** per-symbol and per-module reference counts across `ari-core` + skills (who imports/calls what), feeding `check_dead_code` (unreferenced symbols) and refactor triage (fan-in/fan-out of the 5 >1200-LOC files). Primarily an **analysis/report producer**, not a pass/fail gate — default posture is report-only.
- **Inputs:** `--target` (repo root), `--config` (roots, ignore patterns).
- **Outputs:** Markdown reference/dependency tables + JSON graph (nodes = modules/symbols, edges = references) consumable by `generate_quality_report.py`.
- **Overlap:** none (name-only collision with `check_ref_coupling.py`). **Classification: KEEP.**

### 5.10 `check_dead_code.py` — unreachable / unused-symbol scan

- **Purpose:** Surface dead code without assuming `vulture` (not installed).
- **Detects:** unused imports/vars via **ruff** (`F401` 341 findings today, `F841` 39, `F811` 8 — already available signal), plus a custom AST reachability pass over the `analyze_references.py` graph to flag module-private symbols with zero references. Must respect dynamic-dispatch false positives (MCP tool registration, typer command discovery, pydantic models) via allowlist.
- **Inputs:** `--target` (default `ari-core/ari`, opt-in skills), `--config` (ruff rule subset, dynamic-entrypoint allowlist), allowlist frozen at current 341 `F401` + friends so the baseline is *known*, not *new*.
- **Outputs:** Markdown dead-symbol table + JSON. Strongly `--warning-only` by default given the false-positive risk. `--fail-on-regression` blocks only *new* unused imports/symbols — a natural ratchet that lets a one-shot `ruff --fix` (clears 358) shrink the baseline over time.
- **Overlap:** none (no vulture; ruff unused-import rule not wired). **Classification: KEEP.**

### 5.11 `generate_quality_report.py` — aggregator

- **Purpose:** Merge the JSON outputs of the other checkers into a single quality dashboard/report; nothing aggregates today even though every checker emits JSON.
- **Detects:** nothing itself — consumes each checker's stable JSON schema (§3) and rolls up counts, per-area breakdowns (viz is 8,131 LOC = 27% of core; `public/` 148 LOC; per-skill totals), regression deltas vs a stored previous run, and allowlist coverage.
- **Inputs:** `--target` (dir of per-checker JSON, or it invokes the checkers itself with `--format json`), `--config` (which checkers to include, weightings).
- **Outputs:** One consolidated Markdown report (for a PR comment or `docs/refactoring/reports/`) + one JSON roll-up. Should be the only checker a maintainer needs to run for a full picture.
- **Overlap:** none. **Classification: KEEP.**

---

## 6. Warning-mode-first rollout (do not weaponize historical debt)

Phased, per-checker, and reversible:

1. **Land as advisory.** Ship the checker + its frozen allowlist/baseline. If wired at all, use `continue-on-error: true` (like `docs-sync.yml`'s advisory `translation_freshness`/`doc_links` steps and `docs-change-coupling.yml`'s advisory `ref_coupling`). Default flag posture: `--warning-only`.
2. **Freeze the baseline.** Record the current findings as the allowlist (e.g. 341 `F401`, 15 files >800 LOC, current import violations). These are `known`, never `new`.
3. **Ratchet on new debt only.** Flip to `--fail-on-regression`: CI fails **only** when findings exceed the frozen allowlist. Pre-existing debt never blocks an unrelated PR.
4. **Shrink deliberately.** Reduce the allowlist as debt is paid down (e.g. one-shot `ruff --fix` removes 358 findings; splitting a >1200-LOC file drops a `check_complexity` entry). Baseline shrink is a normal PR, never automatic.
5. **Promote to hard gate only by explicit subtask.** External-contract checkers (`check_public_api_contracts` removals, `check_import_boundaries` `ari.public` violations) are the first candidates for a true hard gate; internal-quality checkers (`check_complexity`, `check_dead_code`) may stay advisory indefinitely.

No existing workflow is rewritten. `refactor-guards.yml`, `docs-sync.yml`, `docs-change-coupling.yml`, `readme-sync.yml`, `pages.yml` keep their current jobs; new advisory steps are additive.

---

## 7. Preserved contracts (this plan guards, never breaks)

- **CLI** `ari` (`ari.cli:app`) — untouched; no checker changes command surface.
- **`ari.public.*`** — `check_public_api_contracts` *protects* it; any future removal needs a compatibility-adapter note, not a silent break.
- **MCP tool contracts** (14 `ari-skill-*/src/server.py`) — `check_import_boundaries` enforces the `ari-skill-* → ari.public` interface; the sanctioned `ari-core → ari_skill_memory` edge is allowlisted, not banned.
- **Dashboard API** (`viz/routes.py` + `api_*.py` + `websocket.py`) and its schema — `check_viz_api_schema` guards the coupling to `services/api.ts`; endpoints are not renamed by this plan.
- **Checkpoint / config / output file formats** — `check_directory_policy` guards placement of the `config/`/`configs/`/top-level `config/` trio without moving or renaming any of them.
- **Prompt templates** (`ari/prompts/**/*.md`) — snapshot integrity stays with Gate 10; `check_prompts` only inventories, it does not move files.
- **Scripts called by `.github/workflows/`** — unchanged; new checkers are additive and advisory.

---

## 8. Placement, naming, and shared infrastructure

- New checkers live at **`scripts/` top level** (alongside `readme_sync.py`), not under `scripts/docs/` (which is scoped to the docs/i18n/report surface). Rationale: these are *source-code* gates, a distinct family. `REPO_ROOT = Path(__file__).resolve().parents[1]` (one level, like `readme_sync.py`), versus `parents[2]` used inside `scripts/docs/`.
- A new **`scripts/quality/`** config dir (does **not** exist today) holds `<name>.yaml` (thresholds) + `<name>.allow.yaml` (baselines). Created by the first implementing subtask; add a `README.md` per the repo's per-directory-README convention (and it will be tracked by `readme_sync.py`).
- Shared helpers (JSON schema emitter, allowlist loader, Markdown table writer, git-diff base-ref resolution mirroring `check_ref_coupling.py`'s `--base-ref origin/main`) should live in a small `scripts/quality/_common.py` to avoid copy-paste across 11 files. This is the one place duplication is worth eliminating up front.

---

## 9. Non-goals / explicit exclusions

- **No** installation of `radon` or `vulture` is assumed; `check_complexity`/`check_dead_code` build on ruff (present) instead. If a subtask decides to add a dev dependency, that is its own reviewed decision.
- **No** `pnpm` usage (absent) — frontend checkers use static parsing or npm only.
- **No** LLM/network calls in any checker (preserves the `scripts/docs/` determinism convention and design principle P2).
- **No** rewrite of the 5 existing workflows; **no** new `ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`, `dependabot.yml`, `CODEOWNERS`, or `.github/actions/` (all confirmed absent — out of scope for this plan).
- The word "deprecated" is reserved here for external contracts only; internal removals use KEEP/ADAPT/MERGE/MOVE_TO_LEGACY/DELETE_CANDIDATE/REVIEW_REQUIRED.

---

## 10. Subtask mapping

These subtask IDs are the intended delivery units (files under `docs/refactoring/subtasks/` do not exist yet — this section defines the assignment, it does not describe existing content). One script per subtask, except the docs-sync review and the aggregator ordering:

| Subtask | Script | Deliverable |
|---|---|---|
| **025** | `check_complexity.py` | LOC-tier + ruff `C901` gate, tests excluded by default. |
| **026** | `check_import_boundaries.py` | AST import-graph, `ari.public` + core→skill enforcement. |
| **027** | `check_directory_policy.py` | Placement/naming policy (config trio, no `sonfigs/`, legacy-dir bans). |
| **028** | `check_public_api_contracts.py` | `ari.public.*` symbol snapshot + regenerate mode. |
| **029** | `check_viz_api_schema.py` | `viz` routes ↔ `services/api.ts` reconciliation. |
| **030** | `check_prompts.py` | Inline-prompt inventory; defer snapshots to Gate 10. |
| **031** | `check_dashboard_ux.py` | React `i18n/{en,ja,zh}.ts` parity + hardcoded-string scan. |
| **043** | `analyze_references.py` | Code cross-reference/dependency graph (feeds 055 + 058). |
| **055** | `check_dead_code.py` | ruff `F401`/`F841`/`F811` + reachability over the 043 graph. |
| **058** | `generate_quality_report.py` | Aggregate all checker JSON into one Markdown+JSON roll-up. |

`check_docs_source_sync.py` is intentionally **not assigned a build subtask**: it is REVIEW_REQUIRED (§5.3) and the recommended outcome is to extend `check_doc_sources.py`/`check_ref_coupling.py` rather than create a duplicate. If the review concludes a distinct dimension exists, it can be added to subtask 043's scope or given a new ID at that time.

Dependency order: `043` (reference graph) precedes `055` (dead code consumes it); every checker precedes `058` (aggregator consumes their JSON). `028`/`026` (external-contract gates) are the first candidates for eventual promotion to hard gates.

---

## 11. Open questions / unconfirmed

- **Complexity engine choice** (ruff `C901` vs adding `radon`) is a subtask-025 decision; this plan recommends ruff since it is already installed and no `C901` rule is active today (complexity baseline = zero).
- **Test-vs-production inclusion** for `check_complexity` size gate is unresolved; recommendation is to exclude `tests/**` (the 4 largest core files are tests) but it must be a `--config` toggle.
- Whether `docs/refactoring/` planning docs should carry `sources:` front-matter under `check_doc_sources.py --require-all` is **unconfirmed** (this workspace is not part of the published VitePress IA).
- Whether the `check_docs_source_sync` review yields a genuine new dimension is deferred to that review (§5.3).
- Skills were not individually ruff-linted in the baseline run (only `ari-core`); per-skill counts for `check_dead_code`'s allowlist must be measured at implementation time.

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
