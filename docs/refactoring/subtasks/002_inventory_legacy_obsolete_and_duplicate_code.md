# Subtask 002: Inventory Legacy, Obsolete, and Duplicate Code

- **Phase:** Phase 1 — Measurement and Inventory
- **Subtask ID:** 002
- **Title (index):** `inventory_legacy_obsolete_and_duplicate_code`
- **Primary output:** a factual inventory report classifying every legacy /
  obsolete / duplicate-logic surface in the repo.
- **Runtime code change:** **No** (see Section 16).
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core`
  version `0.9.0`, from `ari-core/pyproject.toml`).
- **Canonical language:** English.
- **Classification vocabulary (used throughout):** `KEEP` / `ADAPT` / `MERGE` /
  `MOVE_TO_LEGACY` / `DELETE_CANDIDATE` / `REVIEW_REQUIRED`. The word
  "deprecated" is reserved for external contracts only (public API, CLI, MCP,
  dashboard API, documented import paths, `ari-skill-*` stable interfaces).

---

## 1. Goal

Produce a single, self-contained inventory report that enumerates and classifies
every **legacy**, **obsolete**, and **duplicate-logic** surface in the ARI
repository, with real file paths, line counts, and a `KEEP / ADAPT / MERGE /
MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED` verdict for each item.

The report is the direct input to **Subtask 016
(`clean_merge_or_quarantine_legacy_code`)**, which is the runtime-editing subtask
that acts on these findings. This subtask (002) only *records and classifies*; it
edits **no** runtime code, imports, prompts, configs, workflows, frontend, or
directory names.

Success = a fresh coding session executing Subtask 016 can act on the report
without re-deriving the inventory, and every entry either cites a preserved
contract or explicitly notes "no contract touched".

## 2. Background

The refactoring program's master plan (`docs/refactoring/000_master_refactoring_plan.md`)
and subtask index (`docs/refactoring/007_subtask_index.md`, rows 001–073) place
this subtask in the Phase-1 inventory cohort **001, 002, 053, 054, 055, 056**.
002 is one of the nine inventory subtasks that MUST precede *any* runtime code
change (001, 002, 020, 036, 045, 053, 059, 060, 067).

A prior top-level report already exists and covers much of this ground:
`docs/refactoring/004_legacy_obsolete_inventory.md` (37 KB). This subtask's report
should **reconcile with, refresh, and supersede** that document's findings against
the live tree (dates drift; line numbers move). Where 004 and the live tree
disagree, the live tree wins and the discrepancy is recorded.

The repository is large and heterogeneous: `ari-core/ari` is **30,277 LOC** of
Python (measured; `viz/` alone is 8,131 = 27%), plus **~25.5k LOC** across the 14
`ari-skill-*` servers, plus a React/TypeScript dashboard under
`ari-core/ari/viz/frontend/`. Growth over multiple version cycles (v0.5.0
checkpoint-scoping, v0.6.0 first core→skill edge) has left several duplicate
seams and dormant surfaces that this inventory must catalog.

## 3. Scope

In scope — enumerate and classify:

1. **Duplicate-logic seams** — two or more code paths implementing the same
   behavior (ReAct loops, pipeline runners, MCP server idioms, rubric handling).
2. **Legacy / obsolete surfaces** — migration shims, coexisting old/new storage
   roots, stale on-disk artifacts, and dangling documentation references.
3. **Unused / abandoned code candidates** — symbols and files with no production
   importer or caller (recorded here; *confirmation* is deferred to the
   053→054→055→056 dead-code chain — this subtask must not itself assert
   deletion-safety for dynamically referenced code).
4. **String-dispatched / dynamic reference roots** — code that static analysis
   would falsely flag as dead, recorded as an explicit "do NOT delete" allow-list
   for 016 and 057.
5. **Verified negatives / corrections** — confusable or hypothesized items that
   turn out not to exist, so downstream sessions stop chasing them.

Out of scope for the *report content* (owned by sibling subtasks; only
cross-reference, do not duplicate the analysis):

- Complexity / LOC baselines and the import-graph → **001**.
- Config-triple consolidation (`config/` vs `configs/` vs top-level `config/`) →
  **003** (record the seam; do not design the merge here).
- Runtime-path / storage-root consolidation → **004/005/006**.
- Dead-code *confirmation and removal* → **053–057**.
- Hardcoded-prompt inventory → **036**.
- Dashboard route/service duplication analysis → **020/059/060**.

## 4. Non-Goals

- **No runtime code changes.** No edits to any file under `ari-core/ari/`,
  `ari-skill-*/`, the frontend, `ari-core/config/`, workflows, or scripts.
- **No renames, moves, or deletions** of any code, directory, or config.
- **No `git rm`** of stale on-disk artifacts (they are `.gitignore`-covered and
  untracked anyway; see Section 6).
- **No new checker scripts** (`check_dead_code.py`, `analyze_references.py`, etc.
  are separate subtasks 054/055).
- **No decision authority over deletion** — every `DELETE_CANDIDATE` verdict is a
  *candidate* pending the 055/056 chain and the 016 owner's sign-off.
- **Do not** re-open or re-lint the skills for style (that is 001 / ruff scope).

## 5. Current Files / Directories to Inspect

All paths verified present on `main` at planning time unless marked. Line counts
are `wc -l`.

**Duplicate-logic seams**

- `ari-core/ari/agent/loop.py` (1630 LOC) — primary ReAct loop.
- `ari-core/ari/agent/react_driver.py` (442 LOC) — "generic ReAct loop driver,
  decoupled from BFTS Node concepts", used for stages declaring a `react:` block
  (docstring lines 1–7). Imported by `ari-core/ari/pipeline/orchestrator.py`,
  `ari-core/ari/pipeline/stage_runner.py`, `ari-core/ari/orchestrator/node_report/builder.py`,
  `ari-core/ari/viz/api_workflow.py`.
- `ari-core/ari/pipeline/orchestrator.py` — `def run_pipeline(...)` at **line 155**.
- `ari-core/ari/viz/api_paperbench_worker.py` — `def _run_pipeline(...)` at
  **line 168** (spawned via `threading` target at line 313).
- MCP server idiom split: FastMCP used by 10 skills
  (`ari-skill-{replicate,memory,benchmark,plot,web,vlm,transform,idea,paper-re,paper}/src/server.py`);
  low-level `mcp.server.Server` used by 4 skills
  (`ari-skill-{coding,hpc,orchestrator,evaluator}/src/server.py`).
- Rubric-format handling spread: `ari-skill-replicate/src/{auditor.py,categories.py,manifest.py,generator.py,server.py}`,
  `ari-skill-paper-re/src/{_replicator_agent.py,_compute/local_pbtask.py}`,
  `ari-skill-paper/src/server.py`, and `ari-core/ari/evaluator/` rubric loading.
  Rubric DATA lives in `ari-core/config/{paperbench_rubrics,reviewer_rubrics}/`.

**Legacy / obsolete surfaces**

- `ari-core/ari/_deprecation.py` (63 LOC) — the one legitimate external-contract
  deprecation shim.
- `ari-core/ari/migrations/v05_to_v07/{legacy_axes,memory,node_reports}.py`
  (dir total 170 LOC). `migrations/v05_to_v07/memory.py:26` holds
  `LEGACY_GLOBAL_PATH` (`~/.ari/global_memory.jsonl`) — the sole legitimate
  accessor of the v0.5.0-retired global path.
- Root `checkpoints/` (empty on disk) coexisting with populated
  `workspace/checkpoints/<ts_slug>/`, `workspace/experiments/`, `workspace/staging/`.
- Stale on-disk runtime artifacts (untracked): `workspace/staging/` (7 stale
  empty timestamp dirs, e.g. `20260430164213`), `workspace/bundle.tar.gz` (stray).
- `docs/_archive/refactor_audit.md` — **directory `docs/_archive/` does not
  exist**, yet the file is referenced from ≥10 doc locations (e.g.
  `docs/README.md:86,135`, `docs/reference/public_api.md:208`,
  `docs/guides/troubleshooting.md:254`, `docs/about/release_policy.md:92`, and the
  ja/zh mirrors). Dangling documentation reference (not code).

**Unused / abandoned code candidates**

- `ari-core/ari/viz/api_wizard.py:30` — `WIZARD_ROUTES` dict, an abandoned partial
  declarative route table (dispatch is actually a manual if/elif chain in
  `routes.py`).
- `ari-core/ari/schemas/__init__.py:11` — `def load(name: str) -> dict` with no
  production importer; data files `node_report.schema.json`, `publish.schema.json`.
- `[project.scripts] ... = "server:main"` in exactly 2 of 14 skills:
  `ari-skill-replicate/pyproject.toml:27`, `ari-skill-paper-re/pyproject.toml:29`
  (inconsistent with the other 12 skills' manifests).
- `ari-core/ari/__init__.py` — **0 LOC / empty**, no `__version__`.
- `ari-core/ari/public/__init__.py` (27 LOC) — docstring-only; exports no symbols
  at top level (submodules imported individually).

**String-dispatched roots — record as "do NOT delete" for 016/057**

- `ari-core/ari/publish/__init__.py:198` — `def _load_backend(name)` string-dispatches
  `ari_registry` / `zenodo` / `gh` (call sites at lines 115, 164).
- `ari-core/ari/evaluator/llm_evaluator.py:165` — `_COMPOSITES` dict, keyed by
  string, consumed at lines 280–286.

**Vendored / submodule seams**

- `.gitmodules`: `ari-skill-idea/vendor/virsci` (Virtual-Scientists) and
  `ari-skill-paper-re/vendor/paperbench` (openai/preparedness).
- `ari-skill-paper-re/src/_paperbench_bridge.py` (2376 LOC) — bridge to the
  vendored paperbench harness (largest single bridge file).

**Config-triple seam (record only; owned by 003)**

- `ari-core/ari/config/` (Python discovery code; `finder.py` 146 LOC,
  `__init__.py` 628 LOC), `ari-core/ari/configs/` (packaged defaults +
  `_loader.py`), `ari-core/config/` (rubric/profile/`workflow.yaml` data).

**Reconciliation source**

- `docs/refactoring/004_legacy_obsolete_inventory.md` — prior inventory to
  refresh/supersede.

## 6. Current Problems

1. **Two ReAct execution paths.** `agent/loop.py` (1630 LOC, BFTS-node-coupled)
   and `agent/react_driver.py` (442 LOC, "decoupled from BFTS Node concepts") both
   implement Thought→Action→Observation loops over MCP tools. `react_driver` is
   wired into `pipeline/orchestrator.py` and `stage_runner.py` for `react:` stages,
   **but `grep -rn 'react:' ari-core/config/*.yaml` returns nothing** — no default
   workflow currently declares a `react:` block, so this path is *dormant but
   wired*. This is a genuine `MERGE` / `REVIEW_REQUIRED` seam, not dead code.

2. **Two pipeline runners.** `pipeline/orchestrator.py:155 run_pipeline` (the
   YAML-driven stage executor) and `viz/api_paperbench_worker.py:168 _run_pipeline`
   (a thread target for the dashboard PaperBench worker) are parallel
   implementations of "run the pipeline". Divergence risk: fixes to one may not
   reach the other.

3. **Two MCP server idioms.** 10 skills use FastMCP; 4 (`coding`, `hpc`,
   `orchestrator`, `evaluator`) use the low-level `mcp.server.Server`. This is a
   maintenance/consistency seam; MCP *tool contracts* must not change regardless
   of idiom.

4. **Rubric-format handling is scattered** across `ari-skill-paper`,
   `ari-skill-replicate`, `ari-skill-paper-re`, and `ari-core/ari/evaluator/`, with
   rubric DATA under `ari-core/config/{paperbench_rubrics,reviewer_rubrics}/`
   (23 reviewer venues). No single owner of "load + validate a rubric".

5. **Coexisting storage roots.** Empty root `checkpoints/` coexists with populated
   `workspace/checkpoints/`. `ari-core/ari/config/__init__.py:588` defaults runs to
   `{repo}/workspace/checkpoints/{run_id}` while `ari-core/config/default.yaml:14`
   still says `./checkpoints/{run_id}/`. (Consolidation is 004/005's job; here just
   record that the root dir is legacy/coexisting.)

6. **Dangling docs reference.** `docs/_archive/refactor_audit.md` is cited from
   ≥10 places but the `docs/_archive/` directory does not exist — a broken
   documentation contract that the docs-link checker
   (`scripts/docs/check_doc_links.py`) may or may not currently catch.

7. **Abandoned/unused surfaces.** `WIZARD_ROUTES` (never dispatched),
   `ari.schemas.load()` (no importer), the 2-of-14 `server:main` script entries,
   the empty `ari/__init__.py` (no `__version__`) — small but real drift.

8. **Corrections to the working skeleton (verified negatives — must be restated so
   downstream sessions stop chasing ghosts):**
   - **NO `sonfigs/` directory exists** anywhere (`find -iname '*sonfig*'` → empty).
     The "config/configs/sonfigs" concern is really the confusable *trio*
     `ari/config/` (code) vs `ari/configs/` (packaged data) vs top-level
     `ari-core/config/` (rubric data).
   - **No top-level `pyproject.toml`** — `ari-core/pyproject.toml` is the core
     manifest.
   - **`node_modules/` is NOT committed** — `git ls-files | grep -c node_modules`
     returns **0**; ignored at `.gitignore:112,113`. (This corrects the
     "committed node_modules" claim in some working notes.)
   - **`__pycache__/` and `report/scripts/.venv/` are NOT tracked** —
     `git ls-files` counts are **0** for both. On-disk-only clutter, no git cost.
   - **No runtime storage is tracked** — `.gitignore` covers `checkpoints/` (26),
     `experiments/` (31), `workspace/` (70), `ari-core/experiments/` (83),
     `ari-core/checkpoints/` (84); `git ls-files` under these is empty. So any
     later consolidation has **no git-tracking migration cost**, only on-disk /
     back-compat concerns.

## 7. Proposed Design / Policy

Deliver **one Markdown inventory report** (path in Section 9) structured as a set
of classified tables. Policy for building it:

**7.1 Classification rubric.** Assign exactly one verdict per item:

| Verdict | Meaning in this inventory |
|---|---|
| `KEEP` | Correct as-is; recorded for completeness (e.g. `_deprecation.py`, migration shims, vendored submodules). |
| `ADAPT` | Keep behavior but adjust behind a compatibility adapter in a later subtask (e.g. one pipeline runner delegating to the other). |
| `MERGE` | Two+ implementations should collapse to one (e.g. the two ReAct paths / two pipeline runners). Owner subtask noted. |
| `MOVE_TO_LEGACY` | Relocate to a quarantine/legacy area rather than delete, because a contract *might* touch it. |
| `DELETE_CANDIDATE` | Appears unused/abandoned; deletion pending 055/056 confirmation and 016 sign-off. Never asserted as safe here. |
| `REVIEW_REQUIRED` | Ambiguous; needs a human or a later analyzer (053–056) decision. |

**7.2 Grounding rule.** Every row cites a real `path:line` and, where a contract
is adjacent, names it (CLI / `ari.public.*` / MCP tool / dashboard API / checkpoint
or config format / core↔skill interface / README-docs usage / workflow-invoked
script). Rows that touch no contract say "no contract touched".

**7.3 Dynamic-reference safety.** Maintain an explicit **"do NOT statically
delete"** table (publish `_load_backend` string dispatch; `_COMPOSITES`;
`ari.schemas.load` if any dynamic loader exists) so 016/057 cannot mistake
string-referenced code for dead code. This table is authoritative input to the
053→056 chain.

**7.4 Duplicate-seam ownership.** For each duplicate seam, record the *owner*
subtask that will resolve it (e.g. ReAct-loop merge → 011; pipeline-stage
architecture → 012; config triple → 003; storage roots → 005). 002 does not
resolve them; it routes them.

**7.5 Reconciliation.** Diff findings against
`docs/refactoring/004_legacy_obsolete_inventory.md`; for each 004 item, mark
`confirmed` / `moved` (line drift) / `resolved` / `superseded`, and add any new
items 004 missed.

**7.6 Verified-negatives section (mandatory).** Restate Section 6.8's negatives so
downstream sessions do not re-investigate non-existent surfaces.

**7.7 Summary roll-up.** End with a count-by-verdict table and a short list of the
top duplicate seams by LOC-at-risk.

## 8. Concrete Work Items

1. **Read the reconciliation source** `docs/refactoring/004_legacy_obsolete_inventory.md`
   and the subtask index detail for 002/016
   (`docs/refactoring/007_subtask_index.md`, lines ~159–195, 403–405).
2. **Confirm each duplicate seam live** with read-only commands, e.g.:
   - `wc -l ari-core/ari/agent/loop.py ari-core/ari/agent/react_driver.py`
   - `grep -rn 'react:' ari-core/config/` (expect empty → dormant path)
   - `grep -rln 'react_driver' ari-core/ari` (confirm importers)
   - `grep -n 'def run_pipeline\|def _run_pipeline' ari-core/ari/pipeline/orchestrator.py ari-core/ari/viz/api_paperbench_worker.py`
   - `grep -rln 'FastMCP' ari-skill-*/src/server.py` and
     `grep -rln 'from mcp.server import Server\|Server(' ari-skill-*/src/server.py`
3. **Confirm legacy/obsolete surfaces**: `ls -la checkpoints/ workspace/staging/`,
   `ls -la workspace/bundle.tar.gz`, `wc -l ari-core/ari/_deprecation.py`,
   `wc -l ari-core/ari/migrations/v05_to_v07/*.py`, and the
   `docs/_archive/refactor_audit.md` reference set
   (`grep -rn 'refactor_audit' docs/`; confirm `ls docs/_archive/` fails).
4. **Confirm unused-code candidates**: `grep -n 'WIZARD_ROUTES' ari-core/ari/viz/api_wizard.py`,
   `grep -rn 'schemas.load\|from ari.schemas import' ari-core ari-skill-*`,
   `grep -rn 'server:main' ari-skill-*/pyproject.toml`,
   `wc -l ari-core/ari/__init__.py`.
5. **Confirm dynamic roots**: read `ari-core/ari/publish/__init__.py:198` and
   `ari-core/ari/evaluator/llm_evaluator.py:165` to capture the exact string keys.
6. **Confirm verified negatives**: `find . -iname '*sonfig*'`,
   `ls pyproject.toml` (expect absent at root),
   `git ls-files | grep -c node_modules`,
   `git ls-files | grep -c __pycache__`,
   `git ls-files report/scripts/.venv | wc -l`,
   `git check-ignore checkpoints workspace`.
7. **Write the classified inventory report** to the Section-9 path, one table per
   category, each row `{path:line, LOC, description, adjacent contract, verdict,
   owner-subtask}`.
8. **Add the reconciliation table** vs 004 and the **verified-negatives** section.
9. **Add the summary roll-up** (count-by-verdict; top seams by LOC).
10. **Self-check**: every row has a verdict and either a named contract or "no
    contract touched"; no row proposes an edit (this is inventory only).

## 9. Files Expected to Change

Runtime code: **none**.

Created (documentation only, non-runtime):

- `docs/refactoring/reports/002_legacy_obsolete_duplicate_inventory.md` — the
  inventory report (the `docs/refactoring/reports/` directory already exists and is
  currently empty).

Optionally updated (documentation only, if the executing session is explicitly
asked to reconcile rather than supersede):

- `docs/refactoring/004_legacy_obsolete_inventory.md` — only to add a pointer to
  the refreshed report. Not required; default is to leave 004 untouched and let the
  new report supersede it by reference.

No other file — under `ari-core/`, `ari-skill-*/`, the frontend, `config/`,
`scripts/`, `.github/`, or any submodule — may be created, edited, moved, renamed,
or deleted by this subtask.

## 10. Files / APIs That Must Not Be Broken

This subtask does not edit code, so nothing is *broken* by it directly. But the
report must correctly *preserve and annotate* these contracts so that Subtask 016
(which does edit code) inherits an accurate contract map:

- **CLI:** console script `ari = ari.cli:app`; every subcommand/option/env-var
  side effect in `ari-core/ari/cli/{commands,run,bfts_loop,lineage,migrate,projects}.py`.
- **Public Python API:** `ari.public.*`
  (`claim_gate, config_schema, container, cost_tracker, llm, paths, run_env,
  verified_context`). `public/` is only 148 LOC — the frozen surface.
- **MCP tool contracts:** all 14 `ari-skill-*/src/server.py` servers — tool names,
  `inputSchema`, the `{"result"|"error"}` envelope, `mcp__<skill>__<tool>` naming.
  The FastMCP-vs-`Server` idiom split is *internal* and must be recorded without
  proposing a tool-contract change.
- **Dashboard API:** endpoints/JSON shapes in `ari-core/ari/viz/routes.py` +
  `api_*.py`, consumed by `frontend/src/services/api.ts` and the WebSocket channel.
  `WIZARD_ROUTES` is unused, but any `DELETE_CANDIDATE` on it must note it lives in
  the dashboard module and be confirmed by 020/059/060 not to be a live route.
- **Checkpoint / output / config formats:** `ari-core/ari/checkpoint.py`; YAML under
  `ari-core/config/` and `ari-core/ari/configs/`. The `_run_pipeline`/`run_pipeline`
  seam writes checkpoint artifacts — a merge must preserve the format.
- **Core↔skill stable interface:** the `ari.public.*` touchpoints and the core→skill
  `ari_skill_memory` edge (first core→skill dependency, v0.6.0).
- **Docs/README usage examples** and scripts invoked by `.github/workflows/`
  (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`,
  `refactor-guards.yml`).
- **Dynamic reference roots** (publish `_load_backend`, `_COMPOSITES`,
  `ari.schemas.load`): must be flagged "do NOT statically delete".

## 11. Compatibility Constraints

- This is a **planning/inventory** subtask; it introduces no behavior, so there is
  no runtime compatibility surface of its own.
- The report must **not** propose breaking any contract in Section 10 without an
  accompanying compatibility-adapter note routed to the owning subtask. For each
  duplicate seam it may *recommend* MERGE/ADAPT, but the recommendation must state
  the adapter strategy the downstream subtask will use (e.g. "keep
  `viz/api_paperbench_worker._run_pipeline` as a thin wrapper delegating to
  `pipeline.orchestrator.run_pipeline`" rather than "delete `_run_pipeline`").
- The report must reserve **"deprecated"** for external contracts only. Internal
  duplicate/unused code is `MERGE` / `DELETE_CANDIDATE` / `MOVE_TO_LEGACY`, never
  "deprecated".
- Every `DELETE_CANDIDATE` is explicitly non-authoritative here — it is gated on
  the 053→054→055→056 dead-code chain and on 016/057 sign-off.

## 12. Tests to Run

This subtask changes no code, so tests are a **sanity gate** confirming the tree is
still green after (only) a new doc file has been added:

- `python -m compileall .` — confirms no `.py` was accidentally touched/broken.
- `pytest -q` — full suite must pass (unchanged from baseline; heaviest files are
  `ari-core/tests/test_server.py` 1844, `test_gui_errors.py` 1650,
  `test_workflow_contract.py` 1606).
- `ruff check .` — baseline is **661 findings** (341 `F401`, 135 `E402`); this
  subtask must not increase the count (it adds only Markdown).
- Docs gates that may inspect the new report:
  `python scripts/docs/check_doc_links.py` (relevant because the report will *cite*
  the dangling `docs/_archive/refactor_audit.md`; ensure the citation is phrased as
  "referenced-but-missing", not as a live link the checker would follow).
- Frontend (`npm test` / `npm run build` under `ari-core/ari/viz/frontend/`) is
  **not applicable** — this subtask touches no frontend code. (Note: `npm`, not
  `pnpm`; no `pnpm` in this environment.)

If any of `compileall` / `pytest` / `ruff` regresses, the executing session
touched something outside the single report file and must revert.

## 13. Acceptance Criteria

1. The report exists at
   `docs/refactoring/reports/002_legacy_obsolete_duplicate_inventory.md` and no
   other file was created, edited, moved, or deleted.
2. Every item in Section 5 appears in the report with: a real `path:line`, a
   description, the adjacent contract (or "no contract touched"), a verdict from the
   six-value vocabulary, and the owner subtask (where applicable).
3. The **duplicate seams** (two ReAct loops; two pipeline runners; two MCP idioms;
   scattered rubric handling) are each classified with a `MERGE`/`ADAPT`/`REVIEW_REQUIRED`
   verdict and routed to their owner subtask (011 / 012 / 003 / etc.).
4. A **"do NOT statically delete"** table lists the publish `_load_backend`
   dispatch, `_COMPOSITES`, and any dynamic loader — with the exact string keys.
5. A **verified-negatives** section restates: no `sonfigs/`; no root
   `pyproject.toml`; `node_modules/`, `__pycache__/`, `report/scripts/.venv/` all
   untracked (git counts 0); no runtime storage tracked.
6. A **reconciliation table** maps each `004_legacy_obsolete_inventory.md` finding
   to confirmed / moved / resolved / superseded, and lists any new items.
7. A **summary roll-up** gives a count-by-verdict table.
8. No row proposes an edit, rename, or deletion as an action (inventory only); no
   row uses "deprecated" for internal code.
9. `python -m compileall .`, `pytest -q`, and `ruff check .` all pass unchanged
   from baseline.

## 14. Rollback Plan

Trivial and complete: the subtask's only artifact is one new untracked-until-committed
Markdown file.

- To roll back: `git rm docs/refactoring/reports/002_legacy_obsolete_duplicate_inventory.md`
  (or delete the file if not yet committed). If 004 was given an optional pointer
  line, `git checkout -- docs/refactoring/004_legacy_obsolete_inventory.md`.
- No runtime state, no migrations, no config, no schema changed → nothing else to
  undo. The rollback cannot affect the running system, checkpoints, or any
  contract.

## 15. Dependencies

Per the program dependency graph:

- **Predecessors:** none. Subtask 002 has **no incoming edge** — it can run
  independently (it is a Phase-1 inventory that needs no prior subtask).
- **Enables (outgoing edge):** `002 -> 016`. Subtask 016
  (`clean_merge_or_quarantine_legacy_code`, Phase 2, High risk, runtime code
  change = Yes) **depends on** this report and must not start until 002 is complete.
- **Gate role:** 002 is one of the nine inventory subtasks (001, 002, 020, 036,
  045, 053, 059, 060, 067) that MUST precede any runtime code change.
- **Sibling coordination (no hard edge, but must not duplicate analysis):**
  - **001** (`measure_complexity_and_dependencies`) — owns LOC/ruff/import-graph
    baselines; 002 cites 001's numbers rather than re-measuring.
  - **053 → 054 → 055 → 056** (reference-roots → analyzer → dead-code checker →
    classification) — 002 *records* dead-code candidates and the dynamic-root
    allow-list; the 053→056 chain *confirms* them. 057 (delete) consumes 056.
  - **003** (config triple), **005** (storage roots), **011** (ReAct-loop split),
    **012** (pipeline-stage architecture) — receive the duplicate seams that 002
    routes to them.

This is consistent with the provided graph edges (`002 -> 016`) and the inventory
gate list.

## 16. Risk Level

- **Risk: Low.**
- **Changes runtime code? No.** The sole output is a documentation/inventory
  Markdown file under `docs/refactoring/reports/`. No runtime code, imports,
  prompts, configs, workflows, frontend, or directory names are modified.
- Residual risk is limited to *report inaccuracy* (mis-citing a line number or
  mis-classifying a dynamic root as dead). Mitigated by Section 8's read-only
  verification commands, the "do NOT statically delete" table, and the requirement
  that every `DELETE_CANDIDATE` is non-authoritative pending 055/056.

## 17. Notes for Implementer

- **Line numbers drift.** Re-run the Section-8 greps against the live tree before
  writing each row; do not trust the numbers in `004_legacy_obsolete_inventory.md`
  verbatim (that report predates possible edits). Where they differ, cite the live
  line and note the drift in the reconciliation table.
- **The `react_driver.py` path is dormant, not dead.** It is imported by
  `pipeline/orchestrator.py` and `stage_runner.py`, but no `react:` block exists in
  `ari-core/config/*.yaml` today. Classify it `MERGE`/`REVIEW_REQUIRED` (owner 011),
  **never** `DELETE_CANDIDATE` — a workflow could enable it at runtime.
- **Guard the dynamic roots.** `publish/__init__.py:198 _load_backend` and
  `evaluator/llm_evaluator.py:165 _COMPOSITES` are string-dispatched; a naive
  "unused symbol" pass will flag their targets. Capture the exact string keys
  (`ari_registry`/`zenodo`/`gh`; the `_COMPOSITES` keys) verbatim.
- **`docs/_archive/refactor_audit.md` is referenced-but-missing.** Phrase the
  report's mention so `scripts/docs/check_doc_links.py` does not treat it as a live
  link to follow (e.g. use inline code `` `docs/_archive/refactor_audit.md` ``,
  not a Markdown link). Route the fix (create the archive doc *or* remove the
  references) to a docs subtask; 002 only records the dangling reference.
- **Do not confuse the three config dirs and do not invent `sonfigs/`.** Restate
  the trio explicitly: `ari-core/ari/config/` (Python discovery code, incl. the
  unexpectedly large 628-LOC `__init__.py`) vs `ari-core/ari/configs/` (packaged
  defaults + `_loader.py`) vs `ari-core/config/` (rubric/profile/`workflow.yaml`
  data). The merge is 003's job.
- **Storage roots are 004/005's job.** Record the empty root `checkpoints/`, the 7
  stale `workspace/staging/` dirs, and `workspace/bundle.tar.gz` as
  legacy/hygiene items, but note they are all `.gitignore`-covered and untracked
  (no `git rm` needed, no migration cost). Do not propose on-disk cleanup here.
- **Keep it inventory, not action.** No row should read "delete X" or "rename Y" as
  an instruction — every actionable verdict names the *owner subtask* that will do
  the edit under contract-preservation rules.
- **Reserve "deprecated" for external contracts.** The only legitimate internal
  "deprecation" surface is `ari-core/ari/_deprecation.py` (KEEP); everything else
  internal uses the six-value vocabulary.
- **Suggested report skeleton:** (1) Scope & rules honored; (2) Duplicate-logic
  seams; (3) Legacy/obsolete surfaces; (4) Unused/abandoned candidates;
  (5) "Do NOT statically delete" dynamic roots; (6) Vendored/submodule seams;
  (7) Config-triple seam (pointer to 003); (8) Verified negatives; (9)
  Reconciliation vs 004; (10) Summary roll-up (count-by-verdict, top seams by LOC).

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **002** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
