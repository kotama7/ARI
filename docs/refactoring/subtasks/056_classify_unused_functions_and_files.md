# Subtask 056: Classify Unused Functions and Files

> **Phase:** Phase 1 — Measurement and Inventory
> **Canonical index entry (`000_master_refactoring_plan.md:103`):**
> `056 | classify_unused_functions_and_files | phase 1 | Low | depends 055 | Dead-code classification report | changes runtime code: No | inventory-gate: No`.
> **Status:** PLANNING ONLY. This document changes no runtime code, imports,
> prompts, configs, workflows, frontend, or directory names. Scope anchor:
> `ari-core` version `0.9.0`, git branch `main`, planning date `2026-07-01`. All
> paths are repository-relative to `/home/t-kotama/workplace/ARI`.
>
> **Vocabulary.** Directory/module/file-level decisions use the master
> classification KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE /
> REVIEW_REQUIRED. Symbol-level dead-code buckets reuse the finer set defined in
> `013_reference_graph_and_dead_code_plan.md` §7: PUBLIC_CONTRACT /
> DYNAMIC_REFERENCE_RISK / TEST_ONLY / DOCS_ONLY / QUARANTINE_CANDIDATE /
> SAFE_DELETE_CANDIDATE / REVIEW_REQUIRED. This subtask maps the latter onto the
> former.

## 1. Goal

Produce a single, human-reviewed **dead-code classification report** that assigns
every unused-looking Python/TypeScript symbol, module, and data file in the repo a
final master classification (KEEP / ADAPT / MERGE / MOVE_TO_LEGACY /
DELETE_CANDIDATE / REVIEW_REQUIRED), grounded in the machine-generated evidence
from the two upstream tools:

- `reference_graph.json` — the static + dynamic reference graph emitted by
  `analyze_references.py` (subtask 054, seeded by the reference-roots inventory of
  subtask 053).
- `dead_code_candidates.md` — the raw, unreviewed candidate buckets emitted by
  `check_dead_code.py` (subtask 055).

The deliverable is the **review/triage layer** on top of that machine output: the
document that subtask 057 (`delete_safe_dead_code_candidates`) will consume as its
authoritative work-list. This subtask does **not** delete, move, or edit any
runtime code — it only classifies and records decisions. It is a measurement /
inventory deliverable, not a code change.

## 2. Background

ARI has grown to **30,277 LOC in `ari-core/ari`** (viz alone = 8,131 LOC / 27% of
core; `ari-core/ari/public` = only 148 LOC), plus **~25.5k LOC across the 14
`ari-skill-*` packages** and a large React/TypeScript dashboard under
`ari-core/ari/viz/frontend/`. Ruff reports **661 findings, 341 of them `F401`
unused-import** and **39 `F841` unused-variable** — a corroborating "possibly
unused" signal, but ruff sees only imports/locals within a file, never
cross-module reachability.

Planning document `013_reference_graph_and_dead_code_plan.md` established the
methodology: reachability is computed from a fixed root set (§3 of that doc:
R1 console script through R12 registry HTTP surface), the graph overlays the
dynamic edge sources that static import analysis cannot see (publish backends,
prompt/rubric/schema string keys, MCP tool dispatch, cross-language HTTP, `ARI_*`
env pairs), and only fully-orphan `SAFE_DELETE_CANDIDATE` nodes are ever eligible
for deletion.

The linear dead-code chain is `053 -> 054 -> 055 -> 056 -> 057 -> 058`. Subtasks
053–055 build the *evidence and tooling*; **this subtask (056) is the human
classification pass** that turns raw buckets into an auditable, actionable
inventory; 057 executes the (few) deletions; 058 folds the counts into the quality
report.

> **Numbering caveat for the implementer.** The internal §10 table of
> `013_reference_graph_and_dead_code_plan.md` uses a *different* local numbering
> (there 056 = "quarantine mechanism"). The **canonical** numbering is the one in
> `000_master_refactoring_plan.md:100-105` and `007_subtask_index.md`, which this
> document follows: 056 = classification report (no runtime change), 057 =
> deletion (the only code-changing step). Where 013's prose says "subtask 056
> quarantine / subtask 057 delete", read it against the canonical map: the
> classification produced here *labels* nodes MOVE_TO_LEGACY, and the actual
> relocation/deletion is executed downstream under 057.

## 3. Scope

In scope:

- Consuming `reference_graph.json` (054) and `dead_code_candidates.md` (055) as
  inputs.
- Human review of **every** candidate node the checker did not confidently place
  as PUBLIC_CONTRACT or DYNAMIC_REFERENCE_RISK, i.e. the full
  `SAFE_DELETE_CANDIDATE`, `QUARANTINE_CANDIDATE`, `TEST_ONLY`, `DOCS_ONLY`, and
  `REVIEW_REQUIRED` lists.
- Assigning each reviewed node a **master classification** (KEEP / ADAPT / MERGE /
  MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED) with a one-line rationale
  and an `evidence` pointer (file:line + matched key/path/route) copied or
  cross-referenced from the graph.
- Writing the reviewed report as a new Markdown artifact under
  `docs/refactoring/reports/` (proposed name `dead_code_classification.md`).
- Recording the per-classification counts so 058 can trend them.

Out of scope (belongs to other subtasks):

- Building `analyze_references.py` / the dynamic overlay (053/054) or
  `check_dead_code.py` (055).
- Any relocation of code into a legacy zone or any file deletion (057).
- Naming the legacy holding directory (owned by the directory-policy stream,
  subtasks 004/005) — this report only *labels* nodes MOVE_TO_LEGACY.
- Frontend component splitting and the committed `node_modules/` hygiene issue
  (separate streams); the classification ignores `node_modules/` entirely.
- Complexity metrics (radon not installed; ruff `C901` not enabled) — this
  subtask does not depend on them.

## 4. Non-Goals

- **No code deletion or movement.** Not one `.py`/`.ts`/`.tsx`/`.yaml`/`.md`
  runtime file is edited, moved, or removed. The report only records intended
  classifications; execution is subtask 057.
- **No new tooling.** The classifier logic lives in `check_dead_code.py` (055);
  this subtask runs it and reviews its output, it does not add analyzers.
- **No contract changes.** The console script, `ari.public.*`, MCP tool
  contracts, dashboard API, checkpoint/config formats, and CI-invoked scripts are
  untouched and, per §10, must never be reclassified toward deletion.
- **No "deprecated" labels on internal code.** Reserve "deprecated" for external
  contracts only; internal orphans are labeled SAFE_DELETE_CANDIDATE /
  MOVE_TO_LEGACY / REVIEW_REQUIRED.
- **No auto-acceptance of ruff-only signal.** `F401`/`F841` alone never justify a
  DELETE_CANDIDATE label; they only corroborate a graph-confirmed orphan.

## 5. Current Files / Directories to Inspect

Upstream evidence inputs (generated by 054/055 when they run; the output
directory exists and is currently **empty**):

- `docs/refactoring/reports/` — output dir for `reference_graph.json` and
  `dead_code_candidates.md`; verified present and empty today.
- `docs/refactoring/013_reference_graph_and_dead_code_plan.md` — the methodology,
  root set (§3), dynamic sources (§5), output formats (§6), and classification
  rules (§7) this report must apply.
- `docs/refactoring/000_master_refactoring_plan.md:100-105` — canonical
  chain/titles for 053–058.

Ground-truth code anchors the reviewer must cross-check for the known
dynamic-reference seams (each is a "looks-unused-but-live" hazard — verified live
this planning pass):

- Publish backends: `ari-core/ari/publish/__init__.py:198` `_load_backend(name)`
  string dispatch → `ari-core/ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py`
  (all four present; **no static importer** → must land DYNAMIC_REFERENCE_RISK / KEEP).
- Evaluator composites: `ari-core/ari/evaluator/llm_evaluator.py:165`
  `_COMPOSITES: dict[str, callable]` (used at `:280`, `:283`, `:286`) — string-keyed callables.
- Prompt loader: `ari-core/ari/prompts/_loader.py:41` `FilesystemPromptLoader.load(key)`
  / `:45` `load_versioned(key)` → `.md` templates under `ari-core/ari/prompts/**`
  reached only by string key.
- Schema loader: `ari-core/ari/schemas/__init__.py:11` `load(name)` / `:18`
  `schema_path(name)` → `node_report.schema.json`, `publish.schema.json`
  (loader is TEST_ONLY-reachable per 013 §5.2; the `.json` files are live data).
- Rubric/profile DATA: `ari-core/config/reviewer_rubrics/*.yaml` (23 files,
  verified), `ari-core/config/paperbench_rubrics/*.yaml`,
  `ari-core/config/profiles/{cloud,hpc,laptop}.yaml`,
  `ari-core/config/reviewer_rubrics/fewshot_examples/neurips/*.json` — selected by
  `ari paper --rubric` / `ARI_RUBRIC` / `--profile`, no import edge.
- MCP tool handlers: `ari-skill-*/src/server.py` (`@mcp.tool` / `Tool(name=...)`)
  dispatched by `ari-core/ari/mcp/client.py` `call_tool()` — PUBLIC_CONTRACT.
- Cross-language edges: `ari-core/ari/viz/frontend/src/services/api.ts` (863 LOC)
  → `ari-core/ari/viz/routes.py` (1197) + the 14 `ari-core/ari/viz/api_*.py` +
  `websocket.py` — PUBLIC_CONTRACT dashboard surface.
- Structural shells that are **not** dead: `ari-core/ari/__init__.py` (verified
  **0 lines / empty**) and `ari-core/ari/public/__init__.py` (27 lines,
  docstring-oriented; owned by the public-API stream, not this report).
- Entrypoint noise to flag REVIEW_REQUIRED (not delete): the unused
  `[project.scripts]` `server:main` in `ari-skill-replicate` and
  `ari-skill-paper-re` (skills launch by filesystem path, not console script).

Corroborating lint signal:

- `ruff check ari-core --output-format=json` → **661 findings** (verified),
  including 341 `F401` and 39 `F841` — folded in as hints only.

## 6. Current Problems

1. **No authoritative unused-code inventory exists.** The repo has no
   `dead_code_candidates.md`, no `reference_graph.json`, and no reviewed
   classification — `docs/refactoring/reports/` is empty. Refactoring subtasks
   downstream (016 legacy merge, 057 deletion) have nothing grounded to act on.
2. **Static signal alone is dangerous here.** ARI is import-driven at its
   extensibility seams (§5 above). A raw "no importer → delete" pass would flag
   the four live publish backends, every prompt `.md`, and the 23 reviewer rubrics
   as dead. The raw 055 buckets therefore *require* a human classification pass
   before anything is actionable — that pass is this subtask.
3. **Ruff over-reports and under-reports.** 341 `F401` unused-imports are real but
   file-local; they do not tell you whether the *module* is reachable. Conversely,
   ruff cannot see cross-module orphans at all. Neither number is a
   delete-decision on its own.
4. **REVIEW_REQUIRED will be non-trivial.** The flat MCP tool namespace can
   silently clobber (`client.py` last-skill-wins), guarded CLI imports
   (`cli/__init__.py:82-100`), and `ARI_MEMORY_BACKEND` set-without-consumer all
   produce ambiguous nodes the checker must down-classify to REVIEW_REQUIRED,
   leaving a human backlog that this subtask is responsible for resolving.
5. **Legacy zone not yet named.** MOVE_TO_LEGACY nodes cannot be relocated until
   the directory-policy stream (004/005) names the holding area; this report must
   therefore *label* rather than *move*, and stay decoupled from that naming.

## 7. Proposed Design / Policy

### 7.1 Deliverable

A new report `docs/refactoring/reports/dead_code_classification.md`, produced by a
human reviewer running the 055 checker and triaging its output. Structure:

- **Header:** commit SHA, generation timestamp, input artifact SHAs
  (`reference_graph.json`, `dead_code_candidates.md`), tool versions
  (ruff 0.15.2, Python 3.13.2).
- **Summary table:** count per master classification and per finer §7 bucket.
- **Ranked candidate table** (most-confident deletions first), one row per node:
  `file` | `symbol` | `loc` | `finer_bucket` | `master_classification` |
  `reachable_from` (empty for true orphans) | `evidence` (file:line + matched
  key/path/route) | `rationale` (one line).
- **Allow-list appendix:** the live-by-string roots that must never be deleted
  (publish backends, prompt/rubric/schema data files, MCP tool handlers,
  `ari.public.*`) — this is the input 057 uses as its deletion firewall.

### 7.2 Classification mapping (finer bucket → master vocabulary)

Apply top-down precedence; first match wins (contract surfaces always outrank
delete candidates):

| Finer bucket (013 §7) | Master classification | Notes |
|---|---|---|
| `PUBLIC_CONTRACT` | **KEEP** | Never deleted; changes need a compatibility-adapter note in a later phase. |
| `DYNAMIC_REFERENCE_RISK` | **KEEP** (or **REVIEW_REQUIRED** if the resolver could not be proven) | Includes the four `publish/backends/*`, `_COMPOSITES` callables, prompt/rubric/schema data files, memory-backend classes gated by `ARI_MEMORY_BACKEND`. |
| `TEST_ONLY` | **REVIEW_REQUIRED** | e.g. `ari.schemas.load()`/`schema_path()`; promote a real caller, keep as helper, or MOVE_TO_LEGACY — never silently deleted (would break tests). |
| `DOCS_ONLY` | **REVIEW_REQUIRED** | Coordinate with `scripts/docs/check_doc_sources.py`; any deletion must update docs in the same change. |
| `QUARANTINE_CANDIDATE` | **MOVE_TO_LEGACY** | Retained but isolated for one release cycle; label only — relocation is 057 after the legacy zone is named. |
| `SAFE_DELETE_CANDIDATE` | **DELETE_CANDIDATE** | The only class eligible for deletion, and only in subtask 057. |
| duplicate-of-another-symbol | **MERGE** or **ADAPT** | When the node is a near-duplicate/superseded helper; cross-reference subtask 002 (duplicate-code inventory). |
| anything the checker could not place | **REVIEW_REQUIRED** | Default bucket. |

### 7.3 Hard rules

- A node is DELETE_CANDIDATE **only** if it fails every liveness test in 013
  §3–§5 (static, dynamic, cross-lang, test, docs). When in doubt, down-classify to
  REVIEW_REQUIRED or MOVE_TO_LEGACY — never up to DELETE_CANDIDATE.
- Every DELETE_CANDIDATE and MOVE_TO_LEGACY row must carry an `evidence` field; a
  row with no evidence is invalid and must be REVIEW_REQUIRED.
- Ruff `F401`/`F841`/`F811` are corroborating hints only; they never by themselves
  promote a node to DELETE_CANDIDATE.
- Determinism (design principle P2): the report is regenerable — re-running the
  055 checker on the same commit must reproduce the same candidate set, and this
  report records the exact input SHAs so the review is falsifiable. No LLM calls
  are used to make classification decisions.

## 8. Concrete Work Items

1. **Confirm inputs exist.** Verify subtasks 053/054/055 have produced
   `docs/refactoring/reports/reference_graph.json` and
   `docs/refactoring/reports/dead_code_candidates.md`; record their git SHAs. If
   missing, stop — this subtask is blocked (see §15).
2. **Run the checker in report mode.** Execute `check_dead_code.py --report`
   (055) to regenerate `dead_code_candidates.md` from the current graph; capture
   the per-bucket counts.
3. **Triage each bucket** per §7.2, in this order: PUBLIC_CONTRACT (spot-check
   only), DYNAMIC_REFERENCE_RISK (verify the seam anchors in §5 are all present),
   TEST_ONLY, DOCS_ONLY, QUARANTINE_CANDIDATE, then SAFE_DELETE_CANDIDATE, then the
   REVIEW_REQUIRED backlog.
4. **Cross-check the §5 dynamic seams by hand** for every candidate that touches
   `publish/backends`, `prompts/`, `config/`/`configs/`, `schemas/`, `mcp/`, or
   `viz/` — confirm none of them slipped into DELETE_CANDIDATE.
5. **Resolve REVIEW_REQUIRED** into a concrete master classification (KEEP /
   ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE) with a rationale, or leave
   as REVIEW_REQUIRED with an explicit "needs owner decision" note.
6. **Write the report** to `docs/refactoring/reports/dead_code_classification.md`
   with the structure in §7.1, most-confident-first ordering, and the allow-list
   appendix.
7. **Emit the summary counts** in a form 058 can ingest (a small table at the top
   of the report is sufficient; no separate machine file is required by this
   subtask).
8. **Sanity gates:** run the §12 commands to prove no runtime file was touched and
   the docs gates stay green.

## 9. Files Expected to Change

Runtime code changed: **none.** The only files created/modified by the implementer
of this subtask are documentation artifacts:

- **Create:** `docs/refactoring/reports/dead_code_classification.md` — the reviewed
  classification report (primary deliverable).
- **Possibly touch (docs only, optional):**
  - `docs/refactoring/subtasks/056_classify_unused_functions_and_files.md` — this
    plan, only to check off acceptance items.
  - `docs/refactoring/reports/README.md` — if a per-directory README index exists
    and the readme-sync gate requires listing the new report (verify with
    `scripts/readme_sync.py`; do not create one speculatively).

No file under `ari-core/`, `ari-skill-*/`, `scripts/`, `.github/`, or any frontend
directory is created, edited, moved, or deleted by this subtask.

## 10. Files / APIs That Must Not Be Broken

This subtask writes only a report, so nothing is *modified*; but the report's
classifications must never place any of the following into DELETE_CANDIDATE or
MOVE_TO_LEGACY (they are the contract firewall enforced downstream in 057):

- **CLI:** console script `ari = ari.cli:app`; all command names/flags in
  `ari-core/ari/cli/{__init__,commands,run,bfts_loop,lineage,migrate,projects}.py`
  and their `ARI_*` env side effects.
- **Public Python API:** every `ari.public.*` submodule (`claim_gate`,
  `config_schema`, `container`, `cost_tracker`, `llm`, `paths`, `run_env`,
  `verified_context`) and the shells `ari-core/ari/__init__.py`,
  `ari-core/ari/public/__init__.py`.
- **MCP contracts:** every `@mcp.tool` / `Tool(name=...)` handler across the 14
  `ari-skill-*/src/server.py`, their `inputSchema`, the `{"result"|"error"}`
  envelope, and `mcp__<skill>__<tool>` naming (`ari/mcp/client.py`).
- **Dashboard API:** `ari/viz/routes.py`, the 14 `ari/viz/api_*.py`,
  `websocket.py`, and everything reached by `frontend/src/services/api.ts`.
- **Checkpoint/config/output formats:** `ari/checkpoint.py`; YAML under
  `ari-core/config/`, `ari-core/ari/configs/`; JSON schemas under `ari/schemas/`.
- **Dynamic-seam live-by-string code:** `ari/publish/backends/*`, all prompt
  `.md` templates, the 23 reviewer rubrics + profiles + fewshot JSON,
  `ari/evaluator/llm_evaluator.py` `_COMPOSITES` targets.
- **CI-invoked scripts:** everything called by `.github/workflows/*` (docs
  checkers, `scripts/readme_sync.py`, `scripts/git-hooks/pre-commit`).

## 11. Compatibility Constraints

- The report is additive documentation; it introduces no import, config, workflow,
  or interface change, so all external contracts are trivially preserved.
- The classification must be consistent with the master vocabulary and the 013 §7
  finer buckets; do not invent new labels and do not use "deprecated" for internal
  code.
- The report must be **deterministic and falsifiable**: it pins input artifact
  SHAs and the commit, so a reviewer can regenerate `dead_code_candidates.md` and
  confirm every row's evidence. No wall-clock dependence beyond the header
  timestamp; no LLM-derived verdicts.
- The MOVE_TO_LEGACY label is decoupled from directory naming: it records intent
  only, so the directory-policy stream (004/005) can name the legacy zone later
  without invalidating this report.

## 12. Tests to Run

Because no runtime code changes, these are sanity/regeneration checks that the
tree is untouched and the docs gates stay green:

- `python -m compileall ari-core` — confirms no Python file was accidentally
  edited/broken (expected: unchanged pass/fail from baseline).
- `pytest -q` (from `ari-core/`, honoring `pytest.ini`) — full suite must remain
  green; this subtask must not perturb it.
- `ruff check .` — the 661-finding baseline must be unchanged (this subtask adds no
  code, so the count must not move).
- `python check_dead_code.py --report` (subtask 055 tool) — regenerate
  `dead_code_candidates.md` and confirm it matches the SHAs recorded in the
  report.
- Docs gates that CI runs: `python scripts/readme_sync.py --check`,
  `python scripts/docs/check_doc_links.py`,
  `python scripts/docs/check_doc_sources.py` — must pass for the new report file.
- `git status --porcelain` — must show **only** the new/modified files listed in
  §9; any change under `ari-core/`, `ari-skill-*/`, `scripts/`, `.github/`, or the
  frontend is a defect.

(No `npm test` / `npm run build` is required: this subtask produces no frontend
change. It may *read* frontend files to trace cross-language edges, but edits
none.)

## 13. Acceptance Criteria

1. `docs/refactoring/reports/dead_code_classification.md` exists, is written in
   English, and follows the §7.1 structure (header with input SHAs, summary counts,
   ranked table, allow-list appendix).
2. Every candidate node from `dead_code_candidates.md` appears exactly once with a
   master classification (KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE
   / REVIEW_REQUIRED) and a mapped finer bucket.
3. Every DELETE_CANDIDATE and MOVE_TO_LEGACY row carries an `evidence` field and a
   one-line rationale; no such row lacks evidence.
4. None of the §10 contract-firewall items appears as DELETE_CANDIDATE or
   MOVE_TO_LEGACY. Specifically, the four `publish/backends/*`, all prompt `.md`
   templates, the 23 reviewer rubrics, the MCP tool handlers, and every
   `ari.public.*` symbol are classified KEEP / DYNAMIC_REFERENCE_RISK.
5. `ari.schemas.load()` / `schema_path()` are classified TEST_ONLY →
   REVIEW_REQUIRED (not DELETE_CANDIDATE), per the 013 §5.2 finding.
6. The summary table's per-classification counts are present and machine-ingestible
   for subtask 058.
7. All §12 gates pass, and `git status` shows only the §9 files (no runtime code
   touched).
8. The report is regenerable: re-running the 055 checker on the recorded commit
   reproduces the same candidate set (determinism confirmed).

## 14. Rollback Plan

Trivial and low-risk: the deliverable is a single new documentation file.

- To roll back, delete `docs/refactoring/reports/dead_code_classification.md`
  (and revert any optional README index edit). No runtime behavior is affected.
- Because no `ari-core`/`ari-skill-*`/frontend/config/workflow file is touched,
  there is nothing to revert in the running system, and no test/CI state changes.
- Downstream subtask 057 must not begin until this report is accepted; if the
  report is rolled back, 057 is automatically blocked (it has no work-list).

## 15. Dependencies

Consistent with the dependency graph `053 -> 054 -> 055 -> 056 -> 057 -> 058`:

- **Hard upstream (must complete first):**
  - **055** (`add_dead_code_candidate_checker`, `check_dead_code.py`) — direct
    predecessor; produces `dead_code_candidates.md`, the primary input.
  - **054** (`add_reference_graph_analyzer`, `analyze_references.py`) — produces
    `reference_graph.json` (transitive, via 055).
  - **053** (`inventory_reference_roots`) — the reference-roots inventory that
    seeds the graph; an **inventory subtask that must precede any runtime code
    change** (per the gate list `001, 002, 020, 036, 045, 053, 059, 060, 067`).
- **Hard downstream (this enables):**
  - **057** (`delete_safe_dead_code_candidates`) — consumes this report's
    DELETE_CANDIDATE rows and allow-list as its authoritative, human-reviewed
    work-list. 057 is the only code-deleting step and depends on 056.
  - **058** (`add_dead_code_checker_to_quality_report`) — ingests this report's
    per-classification counts (transitively via 057).
- **Soft / informational cross-references (not blocking):**
  - `013_reference_graph_and_dead_code_plan.md` — the methodology, root set, and
    §7 vocabulary this report applies.
  - **002** (`inventory_legacy_obsolete_and_duplicate_code`) — its duplicate-code
    findings inform MERGE/ADAPT labels here.
  - Directory-policy stream (**004/005**) — owns naming the legacy holding zone
    that MOVE_TO_LEGACY nodes will eventually move into; this report only labels,
    so it is not blocked by that naming.

## 16. Risk Level

**Risk: Low. Changes runtime code: No.**

This subtask writes a single documentation/report artifact and touches no runtime
code, imports, prompts, configs, workflows, frontend, or directory names
(matching `000_master_refactoring_plan.md:103` `changes runtime code: No`,
`risk: Low`). The only substantive risk is *analytical*: mis-classifying a
live-by-string node as DELETE_CANDIDATE. That risk is contained because (a) this
report never deletes anything, (b) 057 re-verifies the allow-list and re-runs the
full suite before any removal, and (c) §7.3 forces down-classification when in
doubt.

## 17. Notes for Implementer

- **Follow the canonical numbering** (`000`/`007`), not the local §10 table inside
  `013_reference_graph_and_dead_code_plan.md`. In canonical terms: 056 =
  classification report (no code change, this doc); 057 = the only deletion step.
- **Do not delete or move anything.** If you find yourself editing a `.py`/`.ts`
  file or `git mv`-ing a module, you have crossed into 057 — stop and record the
  intent as a classification row instead.
- **Verify the seam anchors before trusting the buckets.** All of these were
  confirmed live on 2026-07-01: `publish/__init__.py:198` `_load_backend`;
  `evaluator/llm_evaluator.py:165` `_COMPOSITES`; `prompts/_loader.py:41`
  `FilesystemPromptLoader.load`; `schemas/__init__.py:11` `load` / `:18`
  `schema_path`; `ari-core/config/reviewer_rubrics/` = 23 YAML files;
  `ari-core/ari/__init__.py` empty (0 lines); `ari-core/ari/public/__init__.py`
  27 lines. If any anchor moved, re-run 053/054 before classifying.
- **Treat ruff as a hint, not a verdict.** `ruff check ari-core
  --output-format=json` returns 661 findings (341 `F401`, 39 `F841`); use them to
  corroborate graph-confirmed orphans, never to promote a delete on their own.
- **`sonfigs/` does not exist.** The confusable trio is `ari-core/ari/config/`
  (Python locator code), `ari-core/ari/configs/` (packaged default DATA +
  `_loader.py`), and top-level `ari-core/config/` (rubric/profile DATA). Key the
  report on these three exact paths; never fabricate a `sonfigs/` node.
- **MCP flat-namespace hazard.** `ari/mcp/client.py` maps tool names in one flat
  namespace (last-skill-wins on collision). When a server-side handler looks
  unreferenced within its package, it is still the live contract surface —
  classify KEEP / PUBLIC_CONTRACT and cross-reference the 054 collision report.
- **Structural shells are not dead.** The empty `ari/__init__.py` and the
  docstring-oriented `ari/public/__init__.py` are owned by the public-API stream;
  do not classify them here beyond a KEEP / PUBLIC_CONTRACT note.
- **Keep it falsifiable.** Pin the commit SHA and the input-artifact SHAs in the
  report header so a reviewer can regenerate `dead_code_candidates.md` and audit
  every `evidence` pointer. No LLM-derived verdicts (design principle P2).

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **056** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
