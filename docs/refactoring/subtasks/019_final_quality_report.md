# Subtask 019: Final Quality Report

> Phase 11: Final Report · Risk: Low · Runtime code change: **No** · Depends on: — (no graph edge; logically terminal)
>
> Planning document only. Nothing here modifies runtime code, imports, prompts,
> configs, workflows, frontend, or directory names. It hands a fresh coding
> session an executable plan whose sole output is a report artifact. All paths are
> repository-real and verified against the tree at planning date 2026-07-01
> (ari-core 0.9.0, branch `main`).

## 1. Goal

Produce the single, authoritative **end-of-program quality report** for the ARI
refactoring effort: one consolidated Markdown document plus one machine-readable
JSON roll-up that

1. aggregates the `--json` output of every quality checker built by the Phase-8
   tooling subtasks (via the aggregator `scripts/generate_quality_report.py`,
   built by subtask **031**),
2. diffs the post-refactor state against the **measured 2026-07-01 baseline**
   (§2 — e.g. `ruff check ari-core` = 661 findings / 341 `F401`; `ari-core/ari`
   total 30,277 LOC with `viz` at 8,131 = 27 %; `public/` = 148 LOC; 5 prod-Python
   files >1200 LOC), and
3. **certifies** that every preserved external contract (CLI `ari`,
   `ari.public.*`, the 14 `ari-skill-*` MCP servers, the dashboard REST/WS API,
   and the checkpoint/config/output file formats) is still intact.

The deliverable is "Final quality report" per `docs/refactoring/007_subtask_index.md:66`,
sequenced **last** despite having no encoded predecessor edge
(`007_subtask_index.md:131-135`, `:375-380`). It is a reporting/aggregation
subtask: **it changes no runtime code**, it runs existing tooling and writes a
report into the already-present (empty) `docs/refactoring/reports/` directory.

## 2. Background

- **Placement.** 019 is the sole member of Phase 11 (`007_subtask_index.md:375-380`).
  Its own index row marks Runtime Code Change = **No**, Can-Run-Independently =
  **Yes**, Risk = **Low** (`007_subtask_index.md:66`). Footnote 3
  (`007_subtask_index.md:131-135`) is explicit: 018 and 019 have no predecessor
  edges in the graph, so they are listed independently runnable, but 019 is
  logically *terminal* — "the final report aggregates all prior outputs" — a soft
  ordering captured in the recommended execution order (`:538` places "**019
  last**"), not as an invented graph edge.
- **Nothing aggregates today.** The quality-scripts design (subtask 009,
  `docs/refactoring/009_quality_scripts_plan.md:180-186`) states every checker
  emits a stable JSON schema (`:58` —
  `{ "checker", "version", "target", "summary", "findings":[{id,severity,file,line,kind,message,allowlisted}] }`)
  but "nothing aggregates today even though every checker emits JSON." The
  aggregator `generate_quality_report.py` is the missing capstone.
- **The aggregator is subtask 031, not 019.** Per the authoritative index,
  `031 add_quality_report_generator → generate_quality_report.py` (Phase 8, depends
  on 001) `007_subtask_index.md:78`, and the provided DEPENDENCY GRAPH edge
  `001 -> 031` matches. 019 **consumes** that tool; it does **not** build it.
- **Naming discrepancy — REVIEW_REQUIRED.** The subtask→script mapping in
  `009_quality_scripts_plan.md:238-249` (§10 of that doc) assigns
  `generate_quality_report.py` to `058` and `check_dead_code.py`/`analyze_references.py`
  to `055`/`043`, whereas `007_subtask_index.md:72-105` assigns
  `generate_quality_report.py` to `031`, `analyze_references.py` to `054`,
  `check_dead_code.py` to `055`, and `058` to "dead-code section in quality
  report". **These two planning documents disagree on the numbering.** The
  provided DEPENDENCY GRAPH (`001 -> 031`, `053 -> 054 -> 055 -> 056 -> 057 -> 058`)
  matches the **007 index**, so this document treats the 007 index as
  authoritative and flags the 009 §10 mapping as stale. The implementer of 019
  must confirm which subtask actually delivered `generate_quality_report.py`
  before invoking it.
- **Measured baseline the report diffs against** (all `wc -l`/`ruff` outputs
  observed live 2026-07-01, from the metrics-area findings):
  - `ruff check ari-core --statistics`: **661 errors, 358 auto-fixable**; `F401`
    341, `E402` 135, `E702` 54, `F841` 39, `E701` 37, `F541` 28, `E741` 11,
    `F811` 8, `E401` 7, `E731` 1. No `C901` rule active → cyclomatic complexity is
    an **unmeasured baseline of zero**. `ruff` is 0.15.2; **radon NOT installed**.
  - `ari-core/ari` = 30,277 prod LOC; per-subdir: `viz` 8,131, `pipeline` 3,900,
    `agent` 3,303, `orchestrator` 2,996, top-level `.py` 2,796, `cli` 2,582,
    `evaluator` 1,261, `llm` 1,234, `config` 773, `publish` 756, `clone` 665,
    `registry` 511, `mcp` 495, `memory` 343, `migrations` 170, `public` **148**,
    `configs` 69, `protocols` 63, `prompts` 61, `schemas` 20.
  - Prod-Python >1200 LOC (5): `ari-skill-paper/src/server.py` 2956,
    `ari-skill-transform/src/server.py` 2465,
    `ari-skill-paper-re/src/_paperbench_bridge.py` 2376, `ari-core/ari/agent/loop.py`
    1630, `ari-skill-paper-re/src/server.py` 1395. Frontend >800 (5):
    `Results/resultSections.tsx` 1590, `Wizard/StepResources.tsx` 1160,
    `Settings/SettingsPage.tsx` 1049, `Workflow/WorkflowPage.tsx` 964,
    `services/api.ts` 863.
- **Report home already exists and is empty.** `docs/refactoring/reports/`
  is present with no files (verified `ls`). It is the intended commit target for
  the human-readable report; the master plan references
  `docs/refactoring/reports/` as an aggregator output home
  (`009_quality_scripts_plan.md:185`).

## 3. Scope

In scope (all reporting/aggregation, zero runtime code change):

- **Run the aggregator** `scripts/generate_quality_report.py` (subtask 031),
  which either invokes each checker with `--format json` or merges pre-generated
  per-checker JSON, over the whole tree at the *end* of the refactoring program.
- **Produce the final report artifact**: `docs/refactoring/reports/final_quality_report.md`
  (human triage roll-up) plus `docs/refactoring/reports/final_quality_report.json`
  (stable machine roll-up), and commit them.
- **Baseline diff**: include a per-area delta table (ruff findings, per-dir LOC,
  large-file census, complexity, dead-code) against the 2026-07-01 baseline in §2.
- **Contract-certification matrix**: a checklist section asserting each preserved
  contract is intact, sourced from the relevant checker's JSON
  (`check_public_api_contracts` for `ari.public.*`, `check_viz_api_schema` for the
  dashboard API↔`services/api.ts` coupling, `check_import_boundaries` for
  `ari-skill-* → ari.public`, `check_prompts`/Gate 10 for prompt snapshots).
- **Optionally** append a completion entry to `CHANGELOG.md` and update the
  progress tracker (subtask 035 deliverable, if present) to mark the program done.
- Add/refresh the per-directory `README.md` inside `docs/refactoring/reports/` if
  one is required by `scripts/readme_sync.py` conventions (the repo enforces a
  `## Contents` list per directory).

## 4. Non-Goals

- **Do NOT build or modify any checker script.** The 11 checkers and the
  aggregator are the deliverables of subtasks **025, 026, 027, 028, 029, 030,
  031, 043, 054, 055, 058** (`007_subtask_index.md:72-105`). 019 only *runs* them
  and reads their JSON. If a required checker does not exist yet, see §15 — 019 is
  blocked on it, not licensed to write it.
- **Do NOT fix any finding.** 019 is a snapshot, not a remediation. Do not run
  `ruff --fix`, do not split large files, do not remove dead code (that is subtask
  057), do not touch prompts/config/imports.
- **Do NOT wire anything into CI.** Workflow integration is subtasks 032/046–052;
  the 5 existing workflows (`docs-change-coupling.yml`, `docs-sync.yml`,
  `pages.yml`, `readme-sync.yml`, `refactor-guards.yml`) are not rewritten or
  extended here.
- **Do NOT install `radon` or `vulture`.** The report records complexity/dead-code
  only from tooling that exists (`ruff` present; `radon`/`vulture` absent) — a
  missing metric is reported as "unmeasured", never fabricated.
- **Do NOT modify runtime code, imports, prompts, configs, frontend, workflows, or
  directory names.** This is the single hardest rule for this subtask: its output
  is confined to `docs/refactoring/reports/` (plus the optional CHANGELOG/tracker
  doc edits).
- **Do NOT invent contract status.** If a contract-checker subtask has not run,
  mark its row "not-yet-checked", not "PASS".

## 5. Current Files / Directories to Inspect

Report target (write here):

- `docs/refactoring/reports/` — **exists, empty** (verified `ls`). Sibling of the
  numbered planning docs `docs/refactoring/000_master_refactoring_plan.md` …
  `014_dashboard_ux_refactoring_plan.md` and `docs/refactoring/subtasks/`.

Aggregator + checkers the report consumes (existence status noted):

- `scripts/generate_quality_report.py` — **does not exist yet**; built by subtask
  031 (`ls scripts/` shows `readme_sync.py`, `run_all_tests.sh`,
  `sc_paper_dogfood.py`, `sc_paper_stage23_chain.py`, `build_pb_images.sh`,
  `gpu_ollama_monitor.sh`, `run_ollama_gpu.sh` and the `docs/`, `fewshot/`,
  `git-hooks/`, `letta/`, `registry/`, `setup/` subdirs — no `generate_quality_report.py`).
- `scripts/check_complexity.py`, `check_import_boundaries.py`,
  `check_directory_policy.py`, `check_public_api_contracts.py`,
  `check_viz_api_schema.py`, `check_prompts.py`, `check_dashboard_ux.py`,
  `analyze_references.py`, `check_dead_code.py` — **none exist today** (`grep`
  over `*.py/*.sh/*.yml/*.md` confirmed all proposed names are net-new); each is a
  separate Phase-1/4/7/8 subtask.
- `scripts/quality/` (config/allowlist home + `_common.py`) — **does not exist**
  (`ls -d scripts/quality` → absent); created by the first checker subtask, not by 019.

Existing tooling whose live output belongs in the report:

- `scripts/docs/*.py` — 7 of 9 support `--json`
  (`check_doc_links.py`, `check_readme_parity.py`, `check_translation_freshness.py`,
  `check_site_i18n.py`, `check_ref_coupling.py`, `check_doc_sources.py`,
  `check_i18n_js.py`); plus `assemble_site.sh`, `sync_report_pdf.sh`.
- `scripts/readme_sync.py` (14,330 bytes) — `--check` gate for per-directory
  README `## Contents` drift.
- `scripts/run_all_tests.sh` (2,572 bytes) — per-skill pytest driver (own
  processes to dodge `sys.modules['src.server']` collisions).
- `report/scripts/` gates — notably `check_prompt_snapshots.py` (**Gate 10**,
  byte-verifies `ari-core/ari/prompts/**/*.md` snapshots), `snapshot_prompts.py`,
  `check_i18n.py` (Gate 6), `check_bib.py`, `check_figures.py`, `check_glossary.py`,
  `check_notation.py`, `check_tikz.py`, `check_toc_consistency.py`,
  `check_logs_for_secrets.py`.

Baseline / contract source-of-truth to cite in the report:

- `ari-core/ari/public/__init__.py` — the "Skills must only import from
  `ari.public.*`" contract statement; `public/` is 148 LOC of thin re-exports over
  `claim_gate, config_schema, container, cost_tracker, llm, paths, run_env,
  verified_context`.
- `ari-core/ari/viz/routes.py` (1197) + `api_*.py` family + `websocket.py` and the
  frontend client `ari-core/ari/viz/frontend/src/services/api.ts` (863) — the
  dashboard-API coupling the report certifies.
- `README.md` / `README.ja.md` / `README.zh.md` REST-endpoint + CLI tables (base
  port 8765) — secondary contract source.
- `CHANGELOG.md` (129 KB) — optional completion entry.
- The measured baseline numbers in §2 (frozen values to diff against).

## 6. Current Problems

1. **No end-of-program certification exists.** Every checker (existing
   `scripts/docs/*` and the future `scripts/*`) emits `--json`, but nothing merges
   them into a single pass/fail picture (`009_quality_scripts_plan.md:182`).
   A maintainer today must run ≥9 scripts by hand and eyeball outputs.
2. **The aggregator is unbuilt.** `scripts/generate_quality_report.py` does not
   exist (subtask 031 deliverable), so there is no roll-up producer for 019 to run.
3. **The report directory is empty.** `docs/refactoring/reports/` is a committed,
   empty placeholder — no baseline-vs-final comparison artifact has ever been
   produced.
4. **Complexity is an unmeasured baseline of zero.** No `C901` ruff rule is active
   and `radon` is absent, so any "complexity improved" claim is unverifiable
   unless the report explicitly records the metric as newly-enabled-or-still-unmeasured.
5. **Cross-document numbering drift** (see §2) risks the implementer invoking the
   wrong subtask's script; the report must pin the exact script paths it consumed.
6. **Contract status is implicit.** There is no single place that answers "did the
   refactor keep `ari.public.*`, the MCP tool contracts, and the dashboard API
   byte-stable?" — 019 makes that explicit.

## 7. Proposed Design / Policy

Classification of the 019 deliverable itself: **KEEP** (net-new report artifact
under `docs/refactoring/reports/`; no existing file is superseded). All checkers
and the aggregator it consumes are **KEEP** (built by their own subtasks); this
subtask neither ADAPTs nor DELETEs any code.

### 7.1 Report shape

Produce two co-located files under `docs/refactoring/reports/`:

- `final_quality_report.md` — the human roll-up. Recommended sections:
  1. **Header** — generation timestamp, ari-core version (0.9.0), git SHA of
     `main`, list of every checker script + version consumed (pin exact paths per
     §6.5).
  2. **Executive verdict** — one-line PASS / PASS-WITH-WARNINGS / FAIL derived
     from whether any *hard-gated / external-contract* checker reports a
     non-allowlisted finding.
  3. **Baseline delta table** — for each metric in §2 (ruff total + per-rule,
     per-dir LOC, large-file census, complexity, dead-code count) show
     `baseline → final → Δ`. Never invent a metric; mark absent ones "unmeasured".
  4. **Per-area breakdown** — reuse the aggregator's per-area roll-up (`viz` is
     8,131 LOC / 27 %; `public/` 148 LOC; per-skill totals).
  5. **Contract-certification matrix** — one row per preserved contract (§10) with
     source checker and status. Any checker that did not run → "not-yet-checked".
  6. **Open findings / allowlist coverage** — counts of `allowlisted: true` vs new.
- `final_quality_report.json` — the machine roll-up. Reuse the aggregator's stable
  schema so downstream tooling (or a later CI step in subtask 032/049) can parse it
  without bespoke logic.

### 7.2 Invocation policy

- Prefer running `scripts/generate_quality_report.py` once; it invokes each
  checker with `--format json` (or reads a directory of per-checker JSON) and
  writes both artifacts. If the aggregator supports a `--target`
  output directory, point it at `docs/refactoring/reports/`.
- Independently capture the *raw* end-state numbers the report leans on, so they
  are reproducible without the aggregator:
  `ruff check ari-core --statistics` (and `ruff check .` for the whole tree),
  per-dir `wc -l`, and the large-file census. Record the exact commands in the
  report header for reproducibility (design principle P2 — determinism).
- **No LLM / network calls** anywhere in report generation (mirrors the
  `scripts/docs/` determinism convention).

### 7.3 Warning-mode posture

Consistent with the staged rollout in `009_quality_scripts_plan.md:190-201`, the
final report is **advisory**: it *records* debt against the frozen baseline; it
does not itself fail CI. Pre-existing debt (e.g. the 341 `F401`, the 15 prod files
>800 LOC) is reported as `allowlisted`/known, never as a new regression. Only
*new* external-contract breakage (a removed `ari.public.*` symbol, a dashboard
route with no client caller) is surfaced as a red-flag verdict.

### 7.4 Handling missing prerequisites

If some checker subtasks have not landed when 019 runs, generate a **partial**
report: include the checkers that exist, and list the missing ones explicitly in
the contract-certification matrix as "not-yet-checked" with the owning subtask ID.
Do **not** silently omit a contract row, and do **not** report "PASS" for an
unchecked contract.

## 8. Concrete Work Items

1. **Confirm prerequisites.** Verify `scripts/generate_quality_report.py` exists
   (subtask 031) and enumerate which of the 11 checkers under `scripts/` are
   present. Reconcile the 007-vs-009 numbering (§2) and record the exact script
   paths used.
2. **Snapshot end-state raw metrics.** Run `ruff check . --statistics`,
   `ruff check ari-core --statistics`, per-directory `wc -l` over `ari-core/ari`
   and each `ari-skill-*/src`, and the frontend `wc -l` over
   `ari-core/ari/viz/frontend/src`. Capture verbatim into the report.
3. **Run the aggregator** over the tree, emitting Markdown + JSON into
   `docs/refactoring/reports/`.
4. **Build the baseline delta table** comparing step-2 output against the §2
   frozen baseline; annotate any metric that is still unmeasured (complexity,
   dead-code if `check_dead_code.py` absent).
5. **Build the contract-certification matrix** from `check_public_api_contracts`,
   `check_viz_api_schema`, `check_import_boundaries`, `check_prompts`/Gate 10 JSON;
   mark absent checkers "not-yet-checked".
6. **Write `final_quality_report.md` + `final_quality_report.json`** to
   `docs/refactoring/reports/`.
7. **README/readme_sync.** If `docs/refactoring/reports/` is under
   `readme_sync.py`'s coverage, add/update its `README.md` `## Contents` list and
   run `python scripts/readme_sync.py --check`.
8. **(Optional) Program-completion doc edits.** Append a CHANGELOG entry marking
   the refactoring program complete and/or update the subtask-035 progress
   tracker. Keep these to documentation only.
9. **Self-verify** with §12 and confirm no runtime file changed
   (`git status` shows only `docs/refactoring/reports/**` and the optional doc
   edits).

## 9. Files Expected to Change

Created by this subtask (report artifacts):

- `docs/refactoring/reports/final_quality_report.md` — **new** human roll-up.
- `docs/refactoring/reports/final_quality_report.json` — **new** machine roll-up.
- `docs/refactoring/reports/README.md` — **new**, only if the directory is under
  `scripts/readme_sync.py` coverage (per-directory `## Contents` convention).

Optionally edited (documentation only, no runtime code):

- `CHANGELOG.md` — one completion entry (optional).
- The subtask-035 progress-tracker doc (if it exists at execution time) — mark
  program done (optional).

Explicitly **NOT** changed: any file under `ari-core/ari/**`, `ari-skill-*/**`,
`ari-core/ari/viz/frontend/**`, `.github/workflows/**`, `scripts/**` (including the
checkers — 019 runs them, never edits them), `config/`, `configs/`, prompt
templates, or any checkpoint/output/config format.

## 10. Files / APIs That Must Not Be Broken

019 writes only a report, so nothing *should* break — but the report **certifies**
these preserved contracts, and the subtask must not touch them:

- **CLI `ari`** (`ari = ari.cli:app`, typer) — subcommands in
  `ari-core/ari/cli/{commands,run,bfts_loop,lineage,migrate,projects}.py`.
- **`ari.public.*`** — `claim_gate, config_schema, container, cost_tracker, llm,
  paths, run_env, verified_context` (148 LOC of thin re-exports).
- **14 `ari-skill-*` MCP servers** (`src/server.py` each) and their tool contracts;
  the sanctioned `ari-core → ari_skill_memory` import edge stays intact.
- **Dashboard API** — `ari-core/ari/viz/routes.py` + `api_*.py` + `websocket.py`
  endpoints/schema consumed by `frontend/src/services/api.ts` (863 LOC); base port
  8765; endpoints not renamed.
- **Checkpoint / config / output formats** — `ari-core/ari/checkpoint.py`; YAML
  under `ari-core/config/` + `ari-core/ari/configs/`; the config trio
  (`ari/config/` code vs `ari/configs/` packaged data vs top-level `config/` rubric
  data). **No `sonfigs/` directory exists** — that upstream token is a typo, not a
  path in this repo; the report must not claim otherwise.
- **`ari-skill-* → ari-core` stable interface**, README/docs usage, and every
  **script called by `.github/workflows/`** — all untouched (019 adds no workflow
  step).

## 11. Compatibility Constraints

- The report is a **purely additive documentation artifact** under
  `docs/refactoring/reports/`. It introduces no import, no code path, no schema,
  and therefore requires **no compatibility adapter**.
- **No top-level `pyproject.toml` exists** — the core manifest is
  `ari-core/pyproject.toml` and is not touched. No `requirements*.txt`, no
  workflow, no prompt file is modified.
- The report's numbers must be **deterministic and reproducible** (design
  principle P2): record exact commands and the git SHA so a re-run reproduces the
  same figures. No LLM/network calls.
- If a CHANGELOG entry is added, it is prose only and must not alter any documented
  CLI/API usage example (those are contracts guarded by `check_readme_parity.py`
  and `report/scripts/` gates).
- The optional `docs/refactoring/reports/README.md` must satisfy
  `scripts/readme_sync.py --check` so the `readme-sync.yml` workflow stays green.

## 12. Tests to Run

From repo root (`/home/t-kotama/workplace/ARI`):

- `python -m compileall .` — must remain clean (no runtime code changed; this
  confirms 019 introduced no accidental `.py` edits).
- `pytest -q` — full core suite (`ari-core/tests/`) must be green; capture the
  pass count into the report. Optionally `scripts/run_all_tests.sh` for the
  per-skill suites (13 hardcoded skill paths, isolated processes).
- `ruff check .` and `ruff check ari-core --statistics` — capture the *final*
  numbers verbatim for the baseline-delta table (baseline was 661 / 341 `F401`).
- **Aggregator + checker runs** (the report's inputs, not pass/fail gates on 019
  itself): `python scripts/generate_quality_report.py --format json ...` plus each
  `scripts/check_*.py --json` / `scripts/docs/check_*.py --json` that exists.
- `python scripts/readme_sync.py --check` — if a `reports/README.md` is added.
- Docs guards for the report + optional doc edits:
  `python scripts/docs/check_doc_links.py --json`,
  `python scripts/docs/check_readme_parity.py --json`, and — since the report is a
  tracked doc — `python scripts/docs/check_ref_coupling.py` /
  `check_doc_sources.py` as applicable. Confirm `refactor-guards.yml`'s invariant
  (no new `~/.ari` references; HOME-write guard) still holds.
- **No `npm test` / `npm run build` is required** for the report itself. If the
  report cites frontend build health, a one-off `npm run build` inside
  `ari-core/ari/viz/frontend/` may be run to *confirm* the number, but it is not a
  gate on 019 (no frontend file changes). `npm` is available; `pnpm` is not.

## 13. Acceptance Criteria

1. `docs/refactoring/reports/final_quality_report.md` and
   `final_quality_report.json` exist, are committed, and are internally consistent
   (Markdown counts equal JSON `summary` counts).
2. The report header pins: generation timestamp, ari-core 0.9.0, `main` git SHA,
   and the exact path+version of every checker/aggregator it consumed (resolving
   the 007-vs-009 numbering per §2).
3. The baseline-delta table covers every §2 metric with `baseline → final → Δ`;
   any unavailable metric (complexity if no `C901`/radon; dead-code if
   `check_dead_code.py` absent) is explicitly marked "unmeasured", never fabricated.
4. The contract-certification matrix has a row for each contract in §10, each with
   its source checker and a status of PASS / WARN / not-yet-checked — no contract
   row is omitted and none is falsely marked PASS.
5. `python -m compileall .`, `pytest -q`, and `ruff check .` outcomes are recorded
   in the report and are green/at-baseline; **`git status` shows only files under
   `docs/refactoring/reports/`** plus the optional CHANGELOG/tracker edits — zero
   runtime, prompt, config, workflow, or frontend files changed.
6. If `reports/README.md` was added, `python scripts/readme_sync.py --check` and
   `readme-sync.yml`'s gate pass.
7. The report makes **no** claim that any preserved contract (§10) was changed, and
   contains **no** reference to a nonexistent `sonfigs/` directory.

## 14. Rollback Plan

Trivial and risk-free — the change set is confined to documentation artifacts:

1. `git rm docs/refactoring/reports/final_quality_report.md
   docs/refactoring/reports/final_quality_report.json` (and `reports/README.md` if
   added), or `git revert` the single commit.
2. Revert the optional `CHANGELOG.md` / progress-tracker edits.

Because 019 touches no runtime code, no data/format migration is involved and
rollback cannot affect the running system. Re-running §12 after rollback returns
the pre-report state.

## 15. Dependencies

- **No explicit graph edge.** The provided DEPENDENCY GRAPH lists no `X -> 019`
  edge, matching `007_subtask_index.md:66` (Can-Run-Independently = Yes) and
  footnote 3 (`:131-135`). 019 is therefore *not* hard-blocked by any single
  subtask in the graph.
- **Hard build-dependency (out-of-graph but real): subtask 031** —
  `generate_quality_report.py` (Phase 8, `007_subtask_index.md:78`; graph edge
  `001 -> 031`). 019 cannot produce the aggregated roll-up without it. 031 in turn
  depends on **001** (`inventory_current_architecture`).
- **Soft/logical prerequisites (aggregated outputs).** 019 is sequenced *last*
  (`007_subtask_index.md:538` — "**019 last**"; `:379-380` — "aggregates all prior
  outputs"). For a *complete* (non-partial) report it wants every quality checker
  landed: **025** (`check_complexity.py`), **026** (`check_import_boundaries.py`),
  **027**/**028** (`check_docs_source_sync.py`/`check_directory_policy.py`, gated
  by 003), **029** (`check_public_api_contracts.py`), **030**
  (`check_viz_api_schema.py`, gated by 020), **043** (`check_prompts.py`, gated by
  036), **054 → 055 → 056 → 057 → 058** (reference graph → dead-code → classify →
  delete → dead-code-in-report chain, per `053 -> 054 -> 055 -> 056 -> 057 -> 058`),
  and the dashboard-UX regression checks under **067–073**. Any not-yet-landed
  checker yields a "not-yet-checked" row per §7.4 rather than blocking 019.
- **Baseline dependency: subtask 002** (`002_complexity_measurement_plan.md`) — the
  frozen 2026-07-01 measurement baseline (§2) is the reference the delta table
  diffs against.
- **Inventory gate note.** The nine read-only inventory subtasks that MUST precede
  any *runtime* code change — **001, 002, 020, 036, 045, 053, 059, 060, 067** — do
  not gate 019 directly, because 019 makes **no runtime code change**. But since
  019 reports on the *result* of the runtime refactors, it is only meaningful once
  those refactors (and thus their inventory gates) have run. Run 019 at the very
  end of the program.
- **Downstream:** 019 has no dependents — it is the terminal deliverable
  (Phase 11).

## 16. Risk Level

**Low** (matches `007_subtask_index.md:66`). **Runtime code change: No.** 019
writes a report and runs existing tooling; it does not alter dispatch, data, or
any contract. The residual risks are entirely about *report correctness*, not
system behavior: (a) fabricating an unmeasured metric — mitigated by §7.4/§13.3
("mark unmeasured, never invent"); (b) invoking the wrong script because of the
007-vs-009 numbering drift — mitigated by §8.1 (pin exact paths, treat 007 index
as authoritative); (c) accidentally editing a runtime/config/prompt file while
gathering numbers — mitigated by §13.5 (`git status` must show only
`docs/refactoring/reports/**`). All three are caught by §12/§13.

## 17. Notes for Implementer

- **This subtask consumes tooling; it does not build it.** If you find yourself
  writing a checker or the aggregator, you have crossed into subtask 025–031 /
  043 / 054–058 territory — stop. 019's only outputs are the two report files
  (plus optional doc edits).
- **Resolve the numbering first.** `007_subtask_index.md` says
  `generate_quality_report.py` = subtask **031**; `009_quality_scripts_plan.md:249`
  says **058**. The provided DEPENDENCY GRAPH (`001 -> 031`) agrees with the 007
  index — follow it, and record in the report exactly which script path you ran.
- **Report reproducibly.** Record the git SHA, ari-core version (0.9.0), and every
  command verbatim. Determinism is design principle P2; a reader must be able to
  re-run and reproduce the numbers. No LLM/network calls.
- **Do not fabricate contract PASS.** Complexity has **no** baseline (`radon`
  absent, no `C901` rule) and several checkers may be unbuilt when you run; report
  those honestly as "unmeasured"/"not-yet-checked". A partial-but-honest report is
  correct; a complete-but-invented one is a defect.
- **The `sonfigs/` trap.** The upstream master prompt references a `sonfigs/`
  directory; it **does not exist** in this repo. The real, correctly-separated trio
  is `ari-core/ari/config/` (locator code), `ari-core/ari/configs/` (packaged
  defaults), and top-level `ari-core/config/` (rubric/profile data). Do not
  reference `sonfigs/` in the report.
- **Watch the report footprint.** Before committing, run `git status` and confirm
  the diff is confined to `docs/refactoring/reports/**` (and any optional
  CHANGELOG/tracker doc). Any `ari-core/`, `ari-skill-*/`, `scripts/`, or
  `frontend/` change means you overstepped — revert it.
- **`docs/refactoring/reports/` is currently empty**; you are creating its first
  contents. If `scripts/readme_sync.py` covers that directory, add its `README.md`
  with a `## Contents` block matching the reference format
  (`ari-core/ari/orchestrator/README.md`) so `readme-sync.yml` stays green.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **019** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
