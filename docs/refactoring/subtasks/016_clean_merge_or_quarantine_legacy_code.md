# Subtask 016: Clean, Merge, or Quarantine Legacy Code

> **Phase 2 — Repository Hygiene.** Risk: **High**. Runtime code change: **Yes**.
> **Depends on:** 002 (`inventory_legacy_obsolete_and_duplicate_code`).
> **Planning date basis:** 2026-07-01, git branch `main`, `ari-core` version `0.9.0`.
>
> This is the **implementation-planning** document for subtask 016. The document
> itself changes no runtime code; it is a self-contained plan a fresh coding
> session can execute. Every path, line number, and count cited below was verified
> by direct inspection of the repository. Where a hypothesized artifact does not
> exist, the plan says **"does not exist"** rather than speculating.

---

## 1. Goal

Take the legacy / obsolete / duplicate code **candidates already inventoried by
subtask 002** (recorded in `docs/refactoring/004_legacy_obsolete_inventory.md`) and
resolve each one in a contract-safe way, using the master vocabulary:
**KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED.**

Concretely this subtask delivers three things:

1. **A quarantine mechanism** the whole refactor can reuse: a dedicated
   `ari-core/ari/_legacy/` namespace, a **re-export-shim pattern** that keeps every
   original import path working, wired to the existing
   `ari-core/ari/_deprecation.py` warning helpers, plus the **missing**
   `DEPRECATION_REMOVAL.md` removal-tracking ledger (currently referenced but
   absent — see §6).
2. **A legacy-routing ledger** that classifies each 002 candidate and records its
   owning subtask and shim requirement, so nothing is silently deleted and nothing
   is double-owned.
3. **The contract-safe subset of merges / relocations that are ready now and are
   not owned by a deeper architecture subtask** — executed here, each behind a
   re-export shim where any importer or contract is touched.

Per the master index (`007_subtask_index.md:63,192-193`): **prefer
`MOVE_TO_LEGACY` over `DELETE` wherever any contract is touched, and keep
re-export shims where the symbol is imported.**

## 2. Background

- Subtask **002** produced the grounded legacy inventory
  (`docs/refactoring/004_legacy_obsolete_inventory.md`, ~620 lines). It classified
  ~24 candidates and **explicitly classified none as `MOVE_TO_LEGACY`** yet,
  because there is **no quarantine location and no shim convention in the repo
  today** (`find ari-core -type d -name '_legacy' -o -name 'legacy'` → none). 016 is
  the subtask that creates that mechanism and actions the ready subset.
- The only sanctioned internal "deprecation" surface is
  `ari-core/ari/_deprecation.py` (**63 LOC**). Its module docstring (line 6) cites
  `DEPRECATION_REMOVAL.md`, and `.github/workflows/refactor-guards.yml:62` cites
  `docs/_archive/refactor_audit.md` — **both files do not exist**
  (`find . -iname 'DEPRECATION_REMOVAL*'` → empty; `ls docs/_archive` → absent).
  These dangling references are the anchor for the removal-ledger deliverable.
- `refactor-guards.yml` maintains an **authoritative allow-list** of the legitimate
  `~/.ari/` shim sites as a `git diff` path-exclude list (lines ~84–96): it names
  `_deprecation.py`, `migrations/`, `core.py`, `paths.py`, `memory_cli.py`,
  `memory/auto_migrate.py`, `memory/file_client.py`,
  `publish/backends/ari_registry.py`, `clone/resolvers/ari.py`,
  `registry/__init__.py`, `viz/state.py`, `viz/api_settings.py`,
  `viz/api_publish.py`. **Any file 016 relocates that is on this list requires a
  matching workflow update** — this is a "scripts called by `.github/workflows`"
  contract surface and must not silently break.
- **Scope-boundary correction:** doc `004`'s internal working map
  (`004_...:36`) loosely routed *large-file decomposition* to "016". That contradicts
  the authoritative index (`007_subtask_index.md:63`), where 016 is
  `clean_merge_or_quarantine_legacy_code` and large-file decomposition is owned by
  the core-architecture (008–014) and viz (015, 021, 062–066) subtasks. **016 does
  not decompose files by size**; it merges/quarantines legacy code. §4 lists the
  hand-offs.

## 3. Scope

**In scope (016 executes):**

1. Create the quarantine namespace `ari-core/ari/_legacy/` (package + `README.md`)
   and a documented **re-export-shim + `DeprecationWarning`** pattern for
   `MOVE_TO_LEGACY` actions.
2. Create `DEPRECATION_REMOVAL.md` (repo-root or `docs/`) as the removal ledger and
   repair the two dangling references to it / to `docs/_archive/refactor_audit.md`
   in `_deprecation.py:6` and `refactor-guards.yml:62`.
3. Relocate the misleadingly-placed live module `ari-core/ari/cli/lineage.py` out of
   the `cli/` package with a re-export shim at `ari.cli.lineage` (ADAPT; see §7/§8).
4. Resolve the two unused `_deprecation.py` helpers (`warn_deprecated_env`,
   `warn_deprecated_field`, **zero call sites**) — record in the ledger; prune only
   if 057's analyzer confirms them dead, otherwise KEEP for API symmetry.
5. Populate the **legacy-routing ledger** for every 002 candidate (KEEP / ADAPT /
   MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE + owning subtask + shim note).

**Out of scope (owned elsewhere — 016 records the routing only):**

- Merging the two ReAct loops (`agent/loop.py` 1630 vs `agent/react_driver.py`
  442) → subtask **011**.
- Merging the duplicated pipeline runner (`pipeline/orchestrator.py::run_pipeline`
  vs `viz/api_paperbench_worker.py:168 _run_pipeline`) → subtask **012** /
  viz-backend **062**.
- MCP server-idiom convergence (10 FastMCP vs 4 low-level `Server`) → skill
  subtasks (contract-sensitive; not touched here).
- Config trio consolidation → **003**; path/checkpoint consolidation → **005/006**.
- Analyzer-confirmed **dead-code deletion** (`WIZARD_ROUTES`, `schemas.load()`,
  unused helpers) → subtask **057** (gated by the 053→056 reference-graph chain).
- `.gitignore` de-duplication + generated-files policy → subtasks **002/033**.

## 4. Non-Goals

- **No large-file splitting.** File size is not a legacy signal; that is 008–014 /
  015/021/062–066. 016 must not split `ari-skill-paper/src/server.py` (2956),
  `ari/agent/loop.py` (1630), `ari/viz/routes.py` (1197), etc.
- **No contract breakage.** No CLI command, `ari.public.*` symbol, MCP tool name /
  `inputSchema` / return envelope, dashboard API endpoint/schema, checkpoint/config
  file format, or documented import path may change semantics. Relocations keep a
  working re-export shim at the old path.
- **No deletion of the migration shims.** `ari/migrations/v05_to_v07/*` and
  `warn_deprecated_path` back an **external** v0.5→v1.0 migration contract and are
  CI-allow-listed; they stay until their scheduled v1.0 removal (recorded in the new
  ledger, not deleted here).
- **No renaming of `ari/config` / `ari/configs`** (breaks documented imports +
  `ari.public.config_schema` re-export) — that is 003.
- **No frontend/TypeScript changes.** The only "wizard" item in scope is the Python
  `WIZARD_ROUTES` literal in `viz/api_wizard.py` (backend), and its deletion is
  routed to 057, not executed here.
- **No new `~/.ari/` references** anywhere outside the existing allow-list.

## 5. Current Files / Directories to Inspect

All paths verified to exist (unless marked). Line numbers are current on `main`.

**Upstream planning inputs**
- `docs/refactoring/004_legacy_obsolete_inventory.md` — the 002 inventory (source of
  every candidate below).
- `docs/refactoring/007_subtask_index.md:63,192-193` — canonical 016 definition and
  the "prefer MOVE_TO_LEGACY / keep shims" rule.

**Deprecation / migration surface (external contract — KEEP, extend ledger)**
- `ari-core/ari/_deprecation.py` (63 LOC): `warn_deprecated_path` (lines 17-34,
  **used**), `warn_deprecated_env` (37-48, **unused**), `warn_deprecated_field`
  (51-63, **unused**). Docstring cites `DEPRECATION_REMOVAL.md` (line 6, **missing**).
- `warn_deprecated_path` call sites (5, all sanctioned): `memory_cli.py:321`,
  `publish/backends/ari_registry.py:49`, `clone/resolvers/ari.py:48`,
  `viz/api_publish.py:45`, `registry/__init__.py:41`.
- `ari-core/ari/migrations/__init__.py`, `ari-core/ari/migrations/v05_to_v07/`
  (`memory.py`, `node_reports.py`, `legacy_axes.py`, READMEs).
  `migrations/v05_to_v07/memory.py:26` = `LEGACY_GLOBAL_PATH = Path.home()/'.ari'/…`
  (the sole legitimate `~/.ari/global_memory.jsonl` accessor).
- `.github/workflows/refactor-guards.yml` — `~/.ari` allow-list at lines ~84–96;
  missing-doc reference at line 62 (`docs/_archive/refactor_audit.md`).

**Relocation candidate (ADAPT with shim)**
- `ari-core/ari/cli/lineage.py` — **not** a Typer command (no `typer`/`@app`/`Typer()`
  in the file); holds `_execute_lineage_decision` / `_load_lineage_decision_config`
  etc. Imported by `ari-core/ari/cli/__init__.py:70` (comment at :67 notes it was
  "extracted to `ari.cli.lineage` in Phase 3A"), and by `cli/run.py`,
  `cli/bfts_loop.py`. Creates a **core→viz** edge at line **151**
  (`from ari.viz.api_orchestrator import _api_launch_sub_experiment`).

**Ledger-only candidates (recorded here, actioned by their owners)**
- `ari-core/ari/viz/api_wizard.py:30` — `WIZARD_ROUTES = {…}` dead literal
  (repo-wide `grep 'WIZARD_ROUTES'` → definition only, zero readers) → 057.
- `ari-core/ari/schemas/__init__.py:11` `load()` / `:18` `schema_path()` — no
  production importer (only `ari-core/ari/schemas/README.md:4` mentions `load`) → 057;
  the `.schema.json` files themselves are a KEEP file-format surface.
- `ari-core/ari/agent/loop.py` (1630) vs `ari-core/ari/agent/react_driver.py` (442)
  → 011.
- `ari-core/ari/pipeline/orchestrator.py::run_pipeline` vs
  `ari-core/ari/viz/api_paperbench_worker.py:168 _run_pipeline` → 012/062.

**Verified negatives (do NOT action as if present)**
- `ari-core/ari/_legacy/` / any `legacy/` package — **does not exist** (016 creates it).
- `DEPRECATION_REMOVAL.md` — **does not exist**.
- `docs/_archive/` (and `docs/_archive/refactor_audit.md`) — **does not exist**.
- `sonfigs/` — **does not exist anywhere**.

## 6. Current Problems

1. **No quarantine mechanism exists.** There is nowhere to move legacy code to, and
   no established shim pattern, so 002 could not classify anything `MOVE_TO_LEGACY`.
   Every deeper subtask that wants to retire code contract-safely needs this
   convention; 016 is where it is defined.
2. **Dangling removal-tracking references.** `_deprecation.py:6` points at a
   `DEPRECATION_REMOVAL.md` that does not exist, and `refactor-guards.yml:62`
   (a workflow script) points at `docs/_archive/refactor_audit.md` that does not
   exist. There is no single ledger recording *what is quarantined and when it is
   removed*.
3. **Two unused deprecation helpers.** `warn_deprecated_env` and
   `warn_deprecated_field` have **zero call sites**; they are either latent API or
   dead weight, and are currently unclassified.
4. **A misleadingly-placed live module.** `ari/cli/lineage.py` is under `cli/` but is
   not a CLI command, and it pulls a **core→viz** dependency (line 151) — a layering
   smell that any import-boundary checker (026) will flag. It should live under the
   orchestrator layer, but four importers make a bare move contract-unsafe.
5. **Ownership ambiguity.** Doc 004's working text loosely routed several
   decomposition items to "016", conflicting with the authoritative index. Without a
   ledger, the same candidate risks being touched by two subtasks (e.g.
   `WIZARD_ROUTES` by both 016 and 057).

## 7. Proposed Design / Policy

### 7.1 Quarantine namespace and shim pattern (the core deliverable)

Create `ari-core/ari/_legacy/` as a package (with `__init__.py` + `README.md`). When
a subtask (016 or later) decides `MOVE_TO_LEGACY` for a module `ari.<pkg>.<mod>`:

1. Move the implementation body into `ari/_legacy/<pkg>_<mod>.py`.
2. Leave a **re-export shim** at the original path `ari/<pkg>/<mod>.py` that
   re-exports every previously public symbol **unchanged** and emits a
   `DeprecationWarning` on import via `ari._deprecation.warn_deprecated_path`
   (or a new `warn_deprecated_module` helper — see 7.3), naming the removal version.
3. Add a row to `DEPRECATION_REMOVAL.md` (module, old path, new path, importers,
   removal version, owning subtask).

The shim guarantees the "keep re-export shims where imported" rule and preserves any
documented import path. `_legacy/` is deliberately private (leading underscore) so it
never becomes a stable surface.

### 7.2 Removal ledger — `DEPRECATION_REMOVAL.md`

Create the file the code already references. It carries two tables:
- **External-contract deprecations** (the existing `~/.ari/` Tier-B fallbacks and
  `warn_deprecated_path` sites, plus the `migrations/v05_to_v07` shims) with their
  scheduled **v1.0** removal.
- **Internal quarantine ledger** (everything moved to `_legacy/` with removal target).

Then repair the dangling references: update `_deprecation.py:6` to point at the real
file, and fix `refactor-guards.yml:62`'s error message to reference an existing doc
(the ledger, or the restored/removed `docs/_archive` note — coordinate with the
docs-sync owner for the `docs/README.md:5,20,86,135` links, which are docs-only).

### 7.3 Deprecation-helper policy

- `warn_deprecated_path` — **KEEP** (5 sanctioned sites; CI-allow-listed).
- `warn_deprecated_env`, `warn_deprecated_field` — **REVIEW_REQUIRED**. Default:
  **KEEP** for API symmetry and record in the ledger as "no current call sites";
  hand the *deletion* decision to 057 once the reference-graph analyzer confirms them
  dead. Optionally add a `warn_deprecated_module` helper for 7.1 shims (additive).

### 7.4 `cli/lineage.py` relocation (ADAPT)

Move the module body to `ari-core/ari/orchestrator/lineage_actions.py` (co-locating
with `orchestrator/lineage_decision.py`, 593 LOC) and leave a re-export shim at
`ari/cli/lineage.py` that re-exports `_execute_lineage_decision`,
`_load_lineage_decision_config`, and the other symbols imported at
`cli/__init__.py:70`. **Preserve the `ari.cli.lineage` import path** so
`cli/run.py`, `cli/bfts_loop.py`, and any monkeypatch delegators keep working. The
core→viz edge (line 151) is **left as-is** in this subtask (still lazily imported)
and flagged in the ledger for the import-boundary checker (026) / viz-service work —
016 relocates and shims; it does not rewrite the viz call.

### 7.5 Ledger-only routing (no code change here)

`WIZARD_ROUTES`, `schemas.load()`, the ReAct-loop merge, and the pipeline-runner
merge are **recorded** in the ledger with their owning subtask (057, 057, 011,
012/062) and shim requirement, but **not modified** by 016. This resolves the
double-ownership ambiguity from §6.5.

## 8. Concrete Work Items

1. **Create `ari-core/ari/_legacy/` package** — `__init__.py` (docstring only) +
   `README.md` documenting the shim pattern from §7.1.
2. **Create `DEPRECATION_REMOVAL.md`** (§7.2) with the external-contract table
   (seed from the `refactor-guards.yml` allow-list and `migrations/v05_to_v07`) and an
   empty-then-populated internal quarantine table.
3. **Add `warn_deprecated_module` helper** to `ari-core/ari/_deprecation.py`
   (additive; mirrors `warn_deprecated_path`) for shim use. Update the docstring
   (line 6) to point at the real `DEPRECATION_REMOVAL.md`.
4. **Relocate `ari/cli/lineage.py`** → `ari/orchestrator/lineage_actions.py` with a
   re-export shim at `ari/cli/lineage.py` (§7.4). Verify importers at
   `cli/__init__.py:70`, `cli/run.py`, `cli/bfts_loop.py` still resolve.
5. **Fix `refactor-guards.yml:62`** to reference an existing doc, and — because the
   relocation in item 4 does **not** move an allow-listed file (`cli/lineage.py` is
   not on the list) — confirm no allow-list entry needs adding. If any *future*
   `MOVE_TO_LEGACY` moves an allow-listed file, add its `_legacy/` path to the list.
6. **Populate the legacy-routing ledger** for all 002 candidates: for each, record
   class (KEEP/ADAPT/MERGE/MOVE_TO_LEGACY/DELETE_CANDIDATE), owning subtask, and shim
   note. Record `warn_deprecated_env`/`warn_deprecated_field` and `WIZARD_ROUTES` /
   `schemas.load()` as DELETE_CANDIDATE → 057; ReAct loops → 011; pipeline runner →
   012/062.
7. **Run the full test + lint gate** (§12) and confirm no contract regression.

## 9. Files Expected to Change

**New files (created by 016):**
- `ari-core/ari/_legacy/__init__.py`
- `ari-core/ari/_legacy/README.md`
- `DEPRECATION_REMOVAL.md` (repo root; or `docs/DEPRECATION_REMOVAL.md` if the
  docs-sync owner prefers — keep the `_deprecation.py` reference consistent with
  wherever it lands)
- `ari-core/ari/orchestrator/lineage_actions.py` (relocated body of `cli/lineage.py`)

**Modified files:**
- `ari-core/ari/_deprecation.py` — docstring fix (line 6); optional additive
  `warn_deprecated_module` helper.
- `ari-core/ari/cli/lineage.py` — becomes a re-export shim to
  `ari.orchestrator.lineage_actions` (import path preserved).
- `.github/workflows/refactor-guards.yml` — fix the missing-doc reference at line 62
  (workflow-contract-sensitive; change only the referenced path/message).

**Unchanged but must be re-verified after the move (importers of `cli/lineage`):**
- `ari-core/ari/cli/__init__.py:70`, `ari-core/ari/cli/run.py`,
  `ari-core/ari/cli/bfts_loop.py`.

**Explicitly NOT changed by 016 (ledger-only; owned by other subtasks):**
- `ari-core/ari/viz/api_wizard.py` (WIZARD_ROUTES → 057)
- `ari-core/ari/schemas/__init__.py` (loader → 057)
- `ari-core/ari/agent/loop.py`, `ari-core/ari/agent/react_driver.py` (→ 011)
- `ari-core/ari/pipeline/orchestrator.py`,
  `ari-core/ari/viz/api_paperbench_worker.py` (→ 012/062)
- `ari-core/ari/migrations/**` (KEEP until v1.0)

## 10. Files / APIs That Must Not Be Broken

- **CLI:** `ari = ari.cli:app` and all subcommands. The `cli/lineage.py` relocation
  must not change any command; `lineage.py` is not itself a command group.
- **Public API:** `ari.public.*` (claim_gate, config_schema, container, cost_tracker,
  llm, paths, run_env, verified_context) — untouched.
- **Import path `ari.cli.lineage`** — must remain importable (re-export shim), since
  `cli/__init__.py:70` and others import from it, and monkeypatch tests may patch it.
- **`ari._deprecation.warn_deprecated_path`** and its 5 call sites — unchanged
  signature/behavior.
- **`ari.migrations.v05_to_v07.*`** and `LEGACY_GLOBAL_PATH` — the external
  v0.5→v1.0 migration contract; not touched.
- **MCP tool contracts** (14 `ari-skill-*` servers), **dashboard API**
  (`viz/routes.py` + `api_*.py` + `websocket.py`), **checkpoint/config file
  formats** — none in scope; must stay byte-compatible.
- **`.github/workflows/refactor-guards.yml` behavior** — the `~/.ari` guard must
  still fail on new violations after the line-62 doc-reference fix; only the
  referenced path/message changes, not the guard logic or allow-list semantics.

## 11. Compatibility Constraints

- **Re-export shims are mandatory** for any `MOVE_TO_LEGACY`/relocation where the
  symbol is imported anywhere (per `007:193`). A shim re-exports the identical public
  names and only *adds* a `DeprecationWarning`.
- **"Deprecated" wording** is reserved for external contracts (CLI, `ari.public.*`,
  MCP tools, dashboard API, documented import paths, `ari-skill` stable interfaces).
  Internal quarantined code is labeled *legacy / moved-to-`_legacy`*, never
  "deprecated", unless it also fronts an external contract.
- **`refactor-guards.yml` allow-list is a contract.** If a later `MOVE_TO_LEGACY`
  relocates an allow-listed `~/.ari` shim file into `_legacy/`, the new path must be
  added to the workflow's path-exclude list in the same change, with justification.
- **No new `~/.ari/` references** outside the existing allow-list.
- **Docs coupling:** `docs-change-coupling.yml` / `docs-sync.yml` /
  `readme-sync.yml` may require a docs touch when code moves; keep the per-directory
  `README.md` in `cli/` and `orchestrator/` consistent with the relocation.

## 12. Tests to Run

Run from the repo root (`/home/t-kotama/workplace/ARI`):

- `python -m compileall .` — byte-compile everything; catches shim/import breakage.
- `ruff check .` — must not introduce new findings. (Baseline is 661 findings /
  341 `F401`; do **not** bundle an unrelated `--fix` sweep into 016 — keep the diff
  scoped to the relocation + new files.)
- `pytest -q` — full suite. Pay special attention to:
  - CLI tests and lineage-decision tests (importers of `ari.cli.lineage`).
  - `ari-core/tests/test_server.py` (1844), `test_workflow_contract.py` (1606),
    `test_pipeline_e2e.py` (1010) — contract-adjacent.
  - Any test that monkeypatches `ari.cli.lineage.*` (the shim must expose the same
    attributes).
- `scripts/run_all_tests.sh` if a broader cross-package pass is wanted.
- **Frontend `npm test` / `npm run build` — NOT required.** 016 touches no
  TypeScript/`frontend/` source (the `WIZARD_ROUTES` item is backend-only and is
  deferred to 057).
- Sanity-run the guard workflow logic locally to confirm the line-62 fix still fails
  on a synthetic `~/.ari` addition and passes otherwise.

## 13. Acceptance Criteria

1. `ari-core/ari/_legacy/` exists with `__init__.py` + `README.md` documenting the
   shim pattern; no production code imports from `_legacy/` except via the shims it
   introduces.
2. `DEPRECATION_REMOVAL.md` exists, is referenced by `_deprecation.py` (no dangling
   reference), and contains both the external-contract table and the internal
   quarantine ledger.
3. `.github/workflows/refactor-guards.yml` no longer references a non-existent doc;
   its guard logic and allow-list semantics are unchanged.
4. `ari/cli/lineage.py` is a re-export shim to `ari/orchestrator/lineage_actions.py`;
   `import ari.cli.lineage` and every symbol used at `cli/__init__.py:70` still
   resolve; `python -m compileall .` and `pytest -q` pass.
5. The legacy-routing ledger classifies **every** 002 candidate with an owning
   subtask; no candidate is left both "actioned by 016" and "owned by another
   subtask".
6. `ruff check .` shows **no new** findings beyond the pre-existing baseline.
7. No CLI/public-API/MCP/dashboard/checkpoint/config contract changed; no new
   `~/.ari/` reference outside the allow-list.

## 14. Rollback Plan

- All changes are additive files + one relocation-behind-shim + one workflow
  one-liner, so rollback is a clean `git revert` of the 016 commit(s).
- If the `cli/lineage.py` relocation surfaces an unexpected importer or monkeypatch
  break: **restore `cli/lineage.py` to its full original body** (revert the move),
  keep `orchestrator/lineage_actions.py` unpopulated/removed, and re-run
  `pytest -q`. The shim design means the fallback is exactly the pre-016 file.
- The new files (`_legacy/`, `DEPRECATION_REMOVAL.md`) are inert if unused; deleting
  them has no runtime effect.
- The `refactor-guards.yml` line-62 change is a message/path edit only; reverting it
  restores the prior (dangling) reference without affecting guard behavior.

## 15. Dependencies

Per the master dependency graph (`002 -> 016`):

- **Hard predecessor: 002** (`inventory_legacy_obsolete_and_duplicate_code`). 016
  consumes its inventory (`004_legacy_obsolete_inventory.md`) and must not start
  until it is complete. 002 is one of the nine inventory subtasks that must precede
  any runtime code change; 016 is a runtime change gated behind it.
- **No other hard edge.** 016 has exactly one predecessor (002) in the graph.

**Soft coordination / hand-off (not graph edges, but must be honored to avoid
double-ownership):**
- **057** (`delete_safe_dead_code_candidates`, gated by 053→054→055→056) — owns the
  *deletion* of analyzer-confirmed dead code (`WIZARD_ROUTES`, `schemas.load()`,
  the two unused `_deprecation` helpers). 016 records these; 057 deletes them and
  should reuse the `_legacy/` shim convention 016 establishes.
- **011** — ReAct-loop merge; **012/062** — pipeline-runner merge; **003** — config
  trio; **005/006** — path/checkpoint consolidation; **015/021/062–066** — viz
  decomposition; **033** — generated-files `.gitignore` policy. 016 routes candidates
  to these owners in the ledger.
- **026** (`add_import_boundary_checker_script`) — will consume the core→viz edge
  note that 016 records for `cli/lineage.py:151`.

## 16. Risk Level

**High — this subtask CHANGES RUNTIME CODE (Yes).**

Although most 016 deliverables are additive (new `_legacy/` package, new ledger doc,
docstring fix), it performs one live relocation (`cli/lineage.py` →
`orchestrator/lineage_actions.py` behind a shim) with four importers and possible
monkeypatch surfaces, and it edits a workflow file (`refactor-guards.yml`) that is a
CI contract. A missed importer or a broken shim would break the `ari` CLI import
graph. The risk is contained by: (a) the re-export shim preserving `ari.cli.lineage`;
(b) `compileall` + full `pytest`; (c) a trivial `git revert` rollback. Everything
riskier (ReAct/pipeline merges, dead-code deletion, config/path moves) is
**deferred**, keeping 016's own diff small and reversible.

## 17. Notes for Implementer

- **Read `004_legacy_obsolete_inventory.md` first** — it is the authoritative source
  of every candidate and already records each one's importers, tests, docs, and
  contract risk. Do not re-derive; extend it into the ledger.
- **Resist scope creep.** The temptation (encouraged by doc 004's loose wording) is
  to start decomposing large files or merging the ReAct loops. Do **not** — those are
  008–014 / 011 / 012 / 062. 016's job is the quarantine *mechanism* plus the small,
  contract-safe, unclaimed subset.
- **The shim is the whole game.** Before moving `cli/lineage.py`, enumerate its
  public symbols (everything imported at `cli/__init__.py:70` plus anything grepped
  as `ari.cli.lineage.<name>` in tests) and re-export **all** of them from the shim.
  A monkeypatch like `monkeypatch.setattr("ari.cli.lineage._execute_lineage_decision", …)`
  must still bind — so the shim should `from ari.orchestrator.lineage_actions import *`
  and also bind the underscore-prefixed names explicitly (star-import skips them).
- **`_legacy/` uses an underscore** so it is never mistaken for a public surface; the
  README must say "no external code should import from `ari._legacy` directly — use
  the shim at the original path."
- **Keep the workflow edit minimal.** In `refactor-guards.yml`, only change the
  line-62 doc reference; do not touch the `git diff` path-exclude allow-list unless a
  move actually relocates an allow-listed file (none do in 016).
- **`sonfigs/` does not exist** — ignore any prompt/legacy text implying it. The
  confusable trio (`ari/config` code / `ari/configs` data / `ari-core/config` rubric
  data) is owned by 003, not 016.
- **Language:** all new prose (ledger, READMEs, commit messages, PR body) in English
  (ARI canonical), per repo convention.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **016** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
