# Subtask 057: Delete Safe Dead Code Candidates

> Phase 2: Repository Hygiene · Depends on 056 (chain 053 → 054 → 055 → 056 → 057
> → 058) · Risk: **High** · Runtime code change: **Yes** (this is the **only**
> deletion step in the whole dead-code stream).
>
> This document is a **planning artifact only**. Writing it changes no runtime
> code, imports, prompts, configs, workflows, frontend, or directory names. The
> only file this task creates is this `.md`. The deletion work it describes lands
> in a later, gated implementation session, one small revertible PR at a time.
>
> **Scope anchor:** `ari-core` version `0.9.0`, git branch `main`, planning date
> `2026-07-01`. All paths are repository-relative to `/home/t-kotama/workplace/ARI`.
>
> **Vocabulary.** Directory/module decisions use the master set KEEP / ADAPT /
> MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED. Symbol-level
> dead-code decisions use the finer set defined in `013_reference_graph_and_dead_code_plan.md`
> §7: SAFE_DELETE_CANDIDATE / QUARANTINE_CANDIDATE / TEST_ONLY / DOCS_ONLY /
> DYNAMIC_REFERENCE_RISK / PUBLIC_CONTRACT / REVIEW_REQUIRED. **Only
> `SAFE_DELETE_CANDIDATE` is ever deleted, and only here.**

## 1. Goal

Physically remove — from the working tree, in small independently revertible PRs —
**only** the source symbols and files that the 053→056 chain has classified as
`SAFE_DELETE_CANDIDATE` and that a human reviewer has confirmed in `056`'s
`dead_code_candidates.md`. A `SAFE_DELETE_CANDIDATE` is an `orphan` node with **no
inbound edge under any edge kind** (static import, static call, dynamic string
key, dynamic path, MCP dispatch, cross-language HTTP, test, or docs) that is not a
contract surface and not inside any dynamic seam
(`013_reference_graph_and_dead_code_plan.md` §7).

Concretely, the deletion set is expected to be **small** and dominated by two
sub-categories (grounded expectation from `013` §7, not a commitment):

1. **File/symbol orphans** — fully-superseded internal helper modules or top-level
   functions/classes/constants that no root reaches. Each removal drops whole
   `def`/`class`/module bodies and updates any `__init__.py` that named them.
2. **Ruff-surfaced micro-dead-code** — a bounded subset of the `ruff 0.15.2`
   baseline (`661` findings; `F401` unused-import = **341**, `F841` unused-variable
   = **39**, `F811` redefined-while-unused = **8**) that the classifier confirms
   are genuinely unreachable. This is *not* a blanket `ruff --fix`: many `F401`
   findings are intentional re-export shims in `__init__.py` files and
   `TYPE_CHECKING` imports (PUBLIC_CONTRACT / structural), which must **not** be
   stripped (see §7.3).

The success shape: the deleted nodes are gone, `check_dead_code.py` (the `055`
checker) re-runs green with **no new orphan introduced**, the full test suite and
all CI gates stay green, and **not a single byte of any external contract**
(console script `ari`, `ari.public.*`, MCP tool names/schemas/envelope, dashboard
REST/WS endpoints/schema, checkpoint/config file formats, `ari-skill-*` → `ari-core`
interfaces, CI-invoked scripts) changes.

## 2. Background

### 2.1 Where this subtask sits

The dead-code stream is a strict linear chain (per the master dependency graph and
`007_subtask_index.md:100-105`):

| ID | Name | Deliverable | Deletes code? |
|----|------|-------------|---------------|
| 053 | `inventory_reference_roots` | Root-set inventory (incl. the dynamic roots static analysis misses) | No |
| 054 | `add_reference_graph_analyzer` | `analyze_references.py` → `reference_graph.json` | No |
| 055 | `add_dead_code_candidate_checker` | `check_dead_code.py` (classifier, `--report`/`--check`) | No |
| 056 | `classify_unused_functions_and_files` | reviewed `dead_code_candidates.md` (the authoritative input to 057) | No (relocates QUARANTINE only) |
| **057** | **`delete_safe_dead_code_candidates`** | **removal of confirmed-dead code** | **Yes (only here)** |
| 058 | `add_dead_code_checker_to_quality_report` | dead-code section in the quality report | No |

`057` is the single mutating tail of that chain. Its methodology, the root set
(R1–R12), the dynamic-edge sources (§5 of `013`), the classification table, and the
gated deletion workflow are fully specified in
`docs/refactoring/013_reference_graph_and_dead_code_plan.md` — **read that document
first**; this subtask executes its §9 step 4 verbatim.

> Naming note (minor doc drift, reconcile at implementation time): `013` §10 folds
> the QUARANTINE (`MOVE_TO_LEGACY`) relocation into "056" and describes 057 as
> "execute deletions". `007_subtask_index.md` labels 056 `classify_unused_functions_and_files`.
> These are consistent in intent: **056 produces the reviewed classification and
> performs any QUARANTINE relocation; 057 deletes only the reviewed
> `SAFE_DELETE_CANDIDATE` rows.** 057 never relocates and never quarantines.

### 2.2 Why deletion is gated and separated from analysis

ARI is import-driven at its extensibility seams: a naive "no `import X` → delete X"
pass would be actively dangerous. The verified dynamic seams that make a symbol
live **without any static import edge** are (all confirmed on disk this planning
run):

- **String-keyed publish backends.** `ari-core/ari/publish/__init__.py:198`
  `_load_backend(name)` (also called at `:115` and `:164`) lazy-imports one of four
  modules **by string** — the directory
  `ari-core/ari/publish/backends/` contains exactly `ari_registry.py`, `gh.py`,
  `local_tarball.py`, `zenodo.py` (plus `__init__.py`, `README.md`). **None of the
  four has a static importer**; a pure import graph flags them dead, yet they are
  the live `ari publish` implementation. Keys are mirrored as an enum in
  `ari-core/ari/schemas/publish.schema.json`.
- **Evaluator composites.** `ari-core/ari/evaluator/llm_evaluator.py:165`
  `_COMPOSITES: dict[str, "callable"]`, consumed by string at `:280`/`:286`
  (validated against `sorted(_COMPOSITES)` at `:283`). The mapped callables are
  string-key targets.
- **Prompt keys → `.md` files** via `ari-core/ari/prompts/_loader.py`
  `FilesystemPromptLoader.load(key)` (`:41`) / `load_versioned` (`:45`). The `.md`
  templates under `ari-core/ari/prompts/{agent,evaluator,orchestrator,pipeline,viz}/`
  are referenced by **no import** — they are live data reached by string.
- **Rubric / profile DATA** under top-level `ari-core/config/`
  (`paperbench_rubrics/*.yaml`, 23 `reviewer_rubrics/*.yaml`,
  `profiles/{cloud,hpc,laptop}.yaml`, `reviewer_rubrics/fewshot_examples/neurips/*.json`)
  selected at runtime by identifier (`ari paper --rubric`, `--profile`, and the
  `ARI_RUBRIC` env side effect). No `import` references them.
- **MCP tool dispatch** across a subprocess boundary: the 14 `ari-skill-*/src/server.py`
  handlers are reachable only by their **string tool name** over stdio via
  `ari-core/ari/mcp/client.py` `MCPClient.call_tool(...)`. A handler that looks
  unreferenced inside its package is in fact the live contract surface.
- **Cross-language HTTP/WS** edges from `ari-core/ari/viz/frontend/src/services/api.ts`
  (863 LOC) to `ari-core/ari/viz/routes.py` (1197) + the 14 `ari/viz/api_*.py`
  handlers — invisible to any single-language graph.
- **TEST_ONLY reachability.** `ari-core/ari/schemas/__init__.py` `load(name)`
  (`:11`) / `schema_path(name)` (`:18`) have **no production importer** (only
  `tests/` reach the schema files, by direct path). The loader functions are
  TEST_ONLY — deleting them would break tests; they are **not**
  `SAFE_DELETE_CANDIDATE`.

The unifying rule: **absence of a static import edge is necessary but not
sufficient evidence of deadness.** 057 trusts only the `check_dead_code.py`
classification *after* the §5 dynamic overlay, plus a second human/tool
confirmation at deletion time.

### 2.3 State of the input artifact (verified)

`docs/refactoring/reports/` is currently **empty** — `reference_graph.json` and
`dead_code_candidates.md` **do not exist yet**; they are produced by `054`/`055`
and reviewed in `056`. Therefore this planning doc **cannot and must not enumerate
the exact final list of files to delete** (that would be fabrication). It instead
(a) names the categories provably *excluded* from deletion, (b) specifies the
per-candidate deletion procedure and its gates, and (c) fixes the acceptance and
rollback criteria a fresh session will apply once `056` hands it a concrete list.

## 3. Scope

In scope (implementation phase, not this planning doc):

- **Delete only rows classified `SAFE_DELETE_CANDIDATE` in `056`'s reviewed
  `docs/refactoring/reports/dead_code_candidates.md`.** Each row carries `file`,
  `symbol`, `loc`, `classification`, `reachable_from` (empty for orphans),
  `evidence`, and a one-line rationale (`013` §6.2).
- For a **symbol orphan** (top-level `def`/`class`/constant): remove the symbol
  body and any now-dangling private helpers it solely used; update any `__init__.py`
  / `__all__` that named it; remove the now-`F401` imports the deletion orphans.
- For a **file/module orphan**: `git rm` the module; remove every import of it and
  any `__init__.py` re-export; confirm no `dynamic.*` edge (§2.2) pointed at it.
- For **ruff micro-dead-code** confirmed by the classifier (`F401`/`F841`/`F811`
  rows that are *not* re-export shims or `TYPE_CHECKING` imports): remove the
  specific unused import/local. Prefer surgical, per-file edits over a blanket
  `ruff --fix` (§7.3).
- **Re-run `check_dead_code.py`** after each deletion PR to confirm the node is
  gone and **no new orphan** was created (e.g. a helper that becomes unreachable
  once its only caller is deleted — either delete it in the same PR if it is now a
  fresh `SAFE_DELETE_CANDIDATE`, or stop and re-review).
- Update any **non-contract** doc/comment that references a deleted internal symbol
  (README module maps under the affected package, in-file docstrings), coordinating
  with `scripts/docs/check_doc_sources.py` and `scripts/readme_sync.py` so their
  gates stay green.

Out of scope: everything in Section 4.

## 4. Non-Goals

- **Do NOT delete anything not on `056`'s reviewed `SAFE_DELETE_CANDIDATE` list.**
  No opportunistic "this looks unused" removals. If the tooling did not confirm it
  orphan, it stays.
- **Do NOT delete any `DYNAMIC_REFERENCE_RISK` node.** Explicitly protected: the
  four `ari-core/ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py`
  modules, the `_COMPOSITES` callables (`evaluator/llm_evaluator.py:165`), every
  prompt `.md` under `ari-core/ari/prompts/`, every rubric/profile file under
  `ari-core/config/`, and any memory-backend class gated by `ARI_MEMORY_BACKEND`.
- **Do NOT delete `TEST_ONLY` symbols** (e.g. `ari.schemas.load`/`schema_path`) —
  removing them breaks tests. They are `056`/human-triage territory, not 057.
- **Do NOT delete `PUBLIC_CONTRACT` surfaces.** The empty `ari-core/ari/__init__.py`
  and the docstring-only `ari-core/ari/public/__init__.py` are **not** dead — they
  are structural contract shells owned by the public-API stream, not 057.
- **Do NOT perform QUARANTINE / `MOVE_TO_LEGACY` relocation** — that is `056` (per
  `013` §9 step 3). 057 only *deletes*; it never moves a file into a legacy zone.
- **Do NOT delete frontend code.** Per `013` §8.4, frontend dead-code output feeds
  the component-splitting subtasks, **not** deletion. No file under
  `ari-core/ari/viz/frontend/` is a 057 deletion target. (`node_modules/` hygiene is
  subtask 033's territory; the dead-code tooling ignores it entirely.)
- **Do NOT run a blanket `ruff check --fix` / `--unsafe-fixes`** across the repo.
  341 `F401` findings include intentional `__init__.py` re-exports and
  `TYPE_CHECKING` imports; a blanket fix would strip PUBLIC_CONTRACT re-exports.
  Only remove imports/locals the classifier individually confirms dead (§7.3).
- **Do NOT rename or move directories, or restructure packages.** 057 is subtractive
  only. Config consolidation (`config/`/`configs/`/top-level `config/`) is subtask
  003; there is **no `sonfigs/`** directory anywhere in the repo — do not invent one.
- **Do NOT change any external contract** to make a deletion "fit" (e.g. dropping a
  CLI flag, an MCP tool, or a dashboard key). If a candidate touches a contract, it
  is reclassified out of `SAFE_DELETE_CANDIDATE` and the workflow stops (§9 firewall
  in `013`).

## 5. Current Files / Directories to Inspect

**Authoritative input (produced upstream; must exist before 057 starts):**

| Path | Role in 057 |
| --- | --- |
| `docs/refactoring/reports/dead_code_candidates.md` | The reviewed candidate list from `056`. **The only source of what may be deleted.** Currently absent (dir is empty) — a hard precondition. |
| `docs/refactoring/reports/reference_graph.json` | The `054` graph (`schema_version`, `nodes`, `edges` with `evidence`, `collisions`). Used to re-confirm each candidate is a true `orphan` before deleting. |
| `docs/refactoring/013_reference_graph_and_dead_code_plan.md` | The governing methodology (roots R1–R12, dynamic seams §5, classification §7, deletion workflow §9). |

**Protected dynamic seams to re-verify before any deletion (read-only, must NOT be
deleted):**

| Path (verified) | Why protected |
| --- | --- |
| `ari-core/ari/publish/__init__.py` (`_load_backend` at `:198`, callers `:115`,`:164`) | String dispatcher; its four targets have no static importer. |
| `ari-core/ari/publish/backends/{ari_registry.py, gh.py, local_tarball.py, zenodo.py}` | `dynamic.string_key` targets — DYNAMIC_REFERENCE_RISK, KEEP. |
| `ari-core/ari/schemas/publish.schema.json` | Mirrors the backend-name enum; contract data. |
| `ari-core/ari/evaluator/llm_evaluator.py` (`_COMPOSITES` at `:165`, use `:280-286`) | String-keyed composite callables. |
| `ari-core/ari/prompts/_loader.py` + `ari-core/ari/prompts/{agent,evaluator,orchestrator,pipeline,viz}/*.md` | Prompt keys → `.md`; live data reached by string. |
| `ari-core/config/` (`paperbench_rubrics/*.yaml`, 23 `reviewer_rubrics/*.yaml`, `profiles/*.yaml`, `reviewer_rubrics/fewshot_examples/neurips/*.json`) | Rubric/profile DATA selected by identifier. |
| `ari-core/ari/mcp/client.py` (`MCPClient.call_tool`) + 14 `ari-skill-*/src/server.py` | MCP tool dispatch across stdio; server handlers are the live contract. |
| `ari-core/ari/schemas/__init__.py` (`load` `:11`, `schema_path` `:18`) | TEST_ONLY loader — never `SAFE_DELETE_CANDIDATE`. |
| `ari-core/ari/__init__.py` (empty), `ari-core/ari/public/__init__.py` (docstring-only) | Structural PUBLIC_CONTRACT shells. |

**Deletion-surface universe the classifier draws from (candidates come from here,
but only the reviewed subset is touched):**

- `ari-core/ari/**/*.py` — core Python (30,277 LOC total; `viz` 8,131, `pipeline`
  3,900, `agent` 3,303, `orchestrator` 2,996, `cli` 2,582, top-level `.py` 2,796,
  `public` only 148).
- `ari-skill-*/src/**/*.py` — 14 skill packages (~25.5k LOC), **only if `054`
  extended the graph to skills**; a skill-internal helper may be an orphan while its
  `@mcp.tool`/`Tool(name=…)` handlers stay live by dispatch.
- The `_deprecation.py` back-compat helper (`ari-core/ari/_deprecation.py`) and
  `ari-core/ari/migrations/` — QUARANTINE-class if ever flagged; **not** deleted by
  057 (migration/format-adjacent).

**Gate infrastructure to keep green (read for the exact commands, do not edit):**

- `scripts/run_all_tests.sh` (multi-package runner; one `pytest` process per skill).
- `.github/workflows/refactor-guards.yml` (no new `~/.ari/` refs outside the
  allowed shim sites; pytest under a redirected `HOME` asserting `$HOME/.ari` stays
  empty).
- `.github/workflows/{docs-sync.yml, readme-sync.yml, docs-change-coupling.yml}`
  and `scripts/git-hooks/pre-commit` (invokes `scripts/readme_sync.py --write`).

## 6. Current Problems

1. **No deletion has a safe input yet.** `docs/refactoring/reports/` is empty; the
   `SAFE_DELETE_CANDIDATE` list does not exist. 057 is blocked on `053→056` and
   cannot begin until `dead_code_candidates.md` is reviewed.
2. **Static-only deletion is unsafe here.** Six distinct dynamic seams (§2.2) make
   liveness invisible to an import graph. Any deletion that skips the `054` dynamic
   overlay risks removing live code (e.g. a publish backend) that a bare import
   walker would call "unused."
3. **Ruff findings are not uniformly deletable.** The `341` `F401` unused-imports
   include intentional re-export shims (`__init__.py` public surfaces) and
   `TYPE_CHECKING` imports. A blanket `ruff --fix` would strip PUBLIC_CONTRACT
   re-exports and break `import ari.public.<x>` call sites. The signal must be
   filtered by the classifier, not applied wholesale.
4. **Cascade orphans.** Deleting a symbol can turn its only-caller helper into a
   fresh orphan (or a fresh `F401`). Without a re-scan after each PR, the tree can
   drift into a new dead-code state that the deletion itself created.
5. **Cross-skill MCP name collisions (`013` §5.3).** `MCPClient._tool_registry`
   flattens tool names into one namespace ("last skill wins"). A handler that looks
   unreferenced could be a collision victim, not dead. 057 must rely on the
   `(skill, tool_name)`-keyed graph + collision report, never on bare name lookup.
6. **High blast radius on a mistake.** Unlike the ADAPT refactors elsewhere in the
   program, deletion is not behavior-preserving by construction — a wrong delete is
   a functional regression, mitigated only by the gates and per-PR revertibility.

## 7. Proposed Design / Policy

**Classification of this subtask's action:** 057 executes **DELETE_CANDIDATE →
delete** for `SAFE_DELETE_CANDIDATE` nodes only. Every protected class
(PUBLIC_CONTRACT, DYNAMIC_REFERENCE_RISK, TEST_ONLY, DOCS_ONLY,
QUARANTINE_CANDIDATE, REVIEW_REQUIRED) is **KEEP / not-057**. Nothing internal is
called "deprecated" — that term is reserved for external contracts.

### 7.1 The deletion gate (per candidate)

A row is deletable **iff all** of the following hold at deletion time (a
re-verification, not a re-derivation of trust):

1. It is classified `SAFE_DELETE_CANDIDATE` in the reviewed `dead_code_candidates.md`.
2. Its node in `reference_graph.json` has **zero `edges_in`** under every edge kind
   (`static.import`, `static.call`, `dynamic.string_key`, `dynamic.path`,
   `dynamic.mcp`, `cross_lang.http`), and empty `reachable_from`.
3. It is **not** listed in any §2.2 dynamic seam and not `PUBLIC_CONTRACT`,
   `TEST_ONLY`, or `DOCS_ONLY`.
4. A fast repo-wide **string grep** for the symbol/module name (and its
   dotted-import path) returns only its own definition site and, at most, the
   references being deleted in the same PR. Any surprising hit → stop, reclassify
   `REVIEW_REQUIRED`.

If any check fails, the candidate is **downgraded**, never force-deleted.

### 7.2 PR granularity and ordering

- **One coherent deletion group per PR**, branched off `main` (never committed to
  `main` directly per repo policy), small enough to review by eye and to `git
  revert` atomically.
- Group by locality: delete a module and its now-dead imports together; delete a
  symbol and the private helpers it *solely* used together.
- Order **leaf-first**: delete symbols with no dependents before the helpers they
  used, so each PR leaves the tree in a compiling, test-green state.
- Each PR runs the full gate (§12) and re-runs `check_dead_code.py` (§7.4).

### 7.3 Ruff micro-dead-code policy (surgical, not blanket)

- **Never** run `ruff check --fix .` or `--unsafe-fixes` across the repo in 057.
- For each `F401`/`F841`/`F811` row the classifier confirms dead, remove that
  specific import/local by hand (or a path-scoped `ruff check --fix
  --select F401 <single_file>` when the reviewer has confirmed that file has no
  re-export role).
- **Exclusions (keep):** imports in a package `__init__.py` that re-export a public
  name; names in `__all__`; imports inside `if TYPE_CHECKING:`; imports whose only
  purpose is a registration side-effect. These are PUBLIC_CONTRACT / structural and
  are `# noqa`-worthy, not deletions. The classifier (`055`) must tag them
  PUBLIC_CONTRACT so they never reach 057.

### 7.4 Re-scan / no-new-orphan invariant

After applying a deletion PR and before opening it: re-run
`python scripts/check_dead_code.py --report` (the `055` checker) and diff the
candidate set. The deleted node must be **absent**, and the count of
`SAFE_DELETE_CANDIDATE` must not *increase*. If the deletion created a fresh orphan
(a cascade), either fold it into the same PR (if trivially and safely dead) or stop
and route it back through review. The `--check` mode's budget must not regress
upward.

### 7.5 Contract firewall (must hold at every deletion)

Reproduced from `013` §9. If a candidate deletion would touch any of these, it is
reclassified out of `SAFE_DELETE_CANDIDATE` and the workflow **stops**:

- console script `ari = ari.cli:app`; every `ari.public.*` symbol;
- all CLI command names, flags, and their `ARI_*` env side effects;
- every MCP tool name + `inputSchema` + `{"result"|"error"}` envelope +
  `mcp__<skill>__<tool>` naming;
- all `viz` dashboard endpoints/schema consumed by `services/api.ts`;
- checkpoint (`ari/checkpoint.py`) and config YAML file formats;
- the `ari-skill-*` → `ari-core` stable interfaces;
- scripts invoked by `.github/workflows/*`.

## 8. Concrete Work Items

1. **Precondition check.** Confirm `docs/refactoring/reports/dead_code_candidates.md`
   and `reference_graph.json` exist and are the reviewed `056` outputs. If absent,
   **stop** — 057 is blocked on the chain.
2. **Freeze the deletion set.** Extract every `SAFE_DELETE_CANDIDATE` row into an
   ordered checklist (leaf-first, grouped by locality). Record for each: file,
   symbol/module, LOC, evidence line, and the `reference_graph.json` node id.
3. **Per-candidate re-verify** (§7.1): zero `edges_in`, not in a §2.2 seam, grep
   returns only the definition + same-PR references. Downgrade anything that fails.
4. **Delete in small PRs** (§7.2): for symbol orphans, remove the body + solely-used
   private helpers + orphaned imports; for module orphans, `git rm` + drop imports +
   `__init__.py` re-exports. Apply the surgical ruff cleanup (§7.3) only for
   classifier-confirmed rows.
5. **Re-scan** (§7.4): re-run `check_dead_code.py --report`; assert the node is gone
   and no new orphan appeared; resolve any cascade in the same PR or escalate.
6. **Run the full gate** (§12): `python -m compileall .`, `ruff check .`, the full
   test suite via `scripts/run_all_tests.sh` (and `pytest -q` for the core subset),
   plus the `refactor-guards.yml` / `docs-sync.yml` / `readme-sync.yml` gates.
7. **Doc/README hygiene:** update only *non-contract* references to a deleted
   internal symbol (package README module maps, docstrings); run
   `scripts/readme_sync.py --check` and `scripts/docs/check_doc_sources.py` so their
   gates pass. Never edit a documented public-usage snippet to "fix" a deletion.
8. **Record before/after** counts per classification for the `058` quality-report
   rollup (deletion is auditable): number of nodes deleted, LOC removed, ruff-finding
   delta.
9. **Open one revertible PR per group**, off `main`, with the evidence
   (`reference_graph.json` node id + grep proof) in the PR body.

## 9. Files Expected to Change

**Input-driven — the exact set is defined by `056`'s reviewed
`dead_code_candidates.md`, which does not exist yet (`docs/refactoring/reports/` is
empty).** This planning doc therefore fixes the *shape* of the change, not a
fabricated file list:

- **Deleted (subtractive):** the specific `ari-core/ari/**/*.py` (and possibly
  `ari-skill-*/src/**/*.py`) files/symbols on the reviewed `SAFE_DELETE_CANDIDATE`
  list — expected to be a **small** set dominated by superseded internal helpers and
  ruff-confirmed micro-dead-code (`013` §7). Any whole-module removals are `git rm`.
- **Edited (to keep the tree compiling after a deletion):** the `__init__.py` files
  and call sites that imported a deleted symbol; the specific lines carrying a
  classifier-confirmed `F401`/`F841`/`F811`; package-local `README.md` module maps
  and in-file docstrings that named a deleted internal symbol.
- **Possibly edited:** `docs/refactoring/reports/dead_code_candidates.md` and the
  `058` quality report, to record before/after counts (audit trail).

**Must NOT change under any circumstance** (a deletion that would force a change
here is reclassified and dropped):

- `ari-core/ari/publish/__init__.py`, `ari-core/ari/publish/backends/*` (four
  string-dispatched modules), `ari-core/ari/schemas/publish.schema.json`;
- `ari-core/ari/evaluator/llm_evaluator.py` `_COMPOSITES`;
- `ari-core/ari/prompts/**` (`.md` templates + `_loader.py`);
- `ari-core/config/**` (rubric/profile DATA);
- any `ari-skill-*/src/server.py` MCP tool handler; `ari-core/ari/mcp/client.py`;
- `ari-core/ari/schemas/__init__.py` (`load`/`schema_path`, TEST_ONLY);
- `ari-core/ari/__init__.py`, `ari-core/ari/public/__init__.py`;
- `ari-core/ari/cli/**` command names/flags; `ari-core/ari/checkpoint.py` format;
- `ari-core/ari/viz/frontend/**` (frontend is out of deletion scope);
- any script invoked by `.github/workflows/*`.

## 10. Files / APIs That Must Not Be Broken

- **Console script + CLI:** `ari = ari.cli:app`; all subcommand names, flags, and
  `ARI_*` env side effects (`ari/cli/{commands,run,bfts_loop,lineage,migrate,projects}.py`,
  the guarded `memory`/`ear`/`registry` sub-typers registered at
  `ari/cli/__init__.py:82-100`).
- **Public Python API:** every `ari.public.*` submodule and re-exported symbol
  (`claim_gate, config_schema, container, cost_tracker, llm, paths, run_env,
  verified_context`) — 148 LOC of frozen surface.
- **MCP contract:** all 14 `ari-skill-*/src/server.py` tool names + `inputSchema` +
  `{"result"|"error"}` envelope + `mcp__<skill>__<tool>` naming; `MCPClient`
  (`ari/mcp/client.py`).
- **Dashboard API:** every endpoint path + method + JSON/WS shape in
  `ari/viz/routes.py` + the 14 `ari/viz/api_*.py` + `websocket.py`, consumed by
  `ari/viz/frontend/src/services/api.ts`.
- **Checkpoint & config formats:** `ari/checkpoint.py` I/O + `META_FILES`; YAML under
  `ari-core/config/` and `ari-core/ari/configs/`; the dynamic seams of §2.2.
- **`ari-skill-*` → `ari-core` stable interfaces**, including `ari-core`'s direct
  import of `ari_skill_memory`.
- **CI-invoked scripts:** `scripts/readme_sync.py`, `scripts/run_all_tests.sh`, and
  the `scripts/docs/*` checkers wired into the 5 workflows.

## 11. Compatibility Constraints

- **Subtractive, not transformative.** 057 removes; it never renames, moves, or
  rewrites behavior. No public signature changes, no directory renames, no config
  key changes. (Config consolidation is subtask 003; there is **no `sonfigs/`**.)
- **Evidence-gated.** No deletion without (a) a `SAFE_DELETE_CANDIDATE` row and (b)
  a zero-inbound-edge node with `evidence` in `reference_graph.json`, per `013`
  §6.1's falsifiability rule ("dynamic edges without evidence are not permitted").
- **Ruff cleanup is surgical** (§7.3): no blanket `--fix`/`--unsafe-fixes`; keep
  `__init__.py` re-exports, `__all__`, `TYPE_CHECKING`, and registration-side-effect
  imports.
- **No new runtime dependencies.** `radon` is not installed and 057 does not need
  it; `ruff 0.15.2`, `compileall`, `pytest`, `node`/`npm` (no `pnpm`) only.
- **No new `~/.ari/` references** (`refactor-guards.yml`): a deletion must not
  introduce one, and must not delete an *allowed* shim site listed in that workflow
  (`_deprecation.py`, `migrations/`, `paths.py`, the memory/publish/clone/registry/viz
  shim files) — those are migration surfaces, not dead code.
- **Determinism-adjacent (P2):** the `check_dead_code.py` re-scan must be
  deterministic (stable node ordering, no LLM calls) so "no new orphan" is a
  reproducible assertion, not a flaky one.
- **Term discipline:** internal code removed here is *deleted dead code*, never
  "deprecated" (reserved for external contracts).

## 12. Tests to Run

Baseline gate — run **before and after each deletion PR**; must be green after:

- `python -m compileall .` — catches any dangling import / syntax breakage from a
  removed symbol or module.
- `ruff check .` — must not regress; the `F401`/`F841` count should *drop* (never
  rise) after a deletion PR.
- `pytest -q` (core subset) **and** `bash scripts/run_all_tests.sh` (full
  multi-package suite — one `pytest` process per skill, per the runner's design) —
  the authoritative "nothing live was deleted" signal. Heaviest guards live in
  `ari-core/tests/` (`test_server.py` 1844, `test_gui_errors.py` 1650,
  `test_workflow_contract.py` 1606, `test_wizard.py` 1133); a deletion that removes
  a live symbol surfaces here.

Dead-code-specific gate (unique to this subtask):

- `python scripts/check_dead_code.py --report` (the `055` checker) re-run after the
  deletion: the deleted node must be **absent** and `SAFE_DELETE_CANDIDATE` count
  must not increase (§7.4). If `055` shipped a `--check` budget mode, it must pass.

CI gates that must stay green (do not rewrite them):

- `.github/workflows/refactor-guards.yml` — pytest under a redirected `HOME`
  asserting `$HOME/.ari` stays empty, plus the "no new `~/.ari/` refs" diff guard.
- `.github/workflows/{docs-sync.yml, readme-sync.yml, docs-change-coupling.yml}` —
  via `scripts/readme_sync.py --check` and the `scripts/docs/*` checkers, in case a
  deleted internal symbol was named in a README module map.

Frontend (`npm test` / `npm run build`): **not applicable** — 057 deletes **no**
file under `ari-core/ari/viz/frontend/` (frontend dead code is out of deletion scope
per `013` §8.4). If a future review ever surfaced a frontend orphan, it would be a
separate subtask, and only then would `npm test`/`npm run build` apply.

## 13. Acceptance Criteria

1. Every deleted file/symbol was a `SAFE_DELETE_CANDIDATE` row in `056`'s reviewed
   `dead_code_candidates.md`; **nothing** outside that list was removed.
2. No `DYNAMIC_REFERENCE_RISK`, `PUBLIC_CONTRACT`, `TEST_ONLY`, `DOCS_ONLY`, or
   `QUARANTINE_CANDIDATE` node was deleted; the §2.2 protected seams are byte-intact.
3. `python -m compileall .` and `ruff check .` are clean; the `F401`/`F841`/`F811`
   counts did not rise (they dropped or held).
4. `pytest -q` and `bash scripts/run_all_tests.sh` pass with **no edits to any test
   assertion** and no test deleted to make a removal "pass."
5. `check_dead_code.py --report` (and `--check` budget, if present) confirms each
   deleted node is gone and **no new orphan** was introduced.
6. No external contract changed: console script, `ari.public.*`, MCP tool
   names/schemas/envelope, dashboard REST/WS endpoints/shapes, checkpoint/config
   formats, and CI-invoked scripts are all unchanged (`refactor-guards.yml`,
   `docs-sync.yml`, `readme-sync.yml` green).
7. Each deletion is an independently revertible PR branched off `main`, with the
   `reference_graph.json` node id and grep evidence in the PR body.
8. `058`'s quality report can record before/after dead-code counts and LOC removed.

## 14. Rollback Plan

- **Atomic, per-group revert.** Each deletion lands as its own small PR/commit off
  `main`, so any removal that proves premature is undone by a single `git revert` of
  that commit — restoring the file/symbol byte-for-byte. Keeping module-deletion and
  ruff-cleanup as separate commits lets one be reverted without the other.
- **No data migration, no format change.** 057 touches only source code, never
  checkpoint/config file formats or on-disk runtime storage, so a rollback cannot
  corrupt existing checkpoints, settings, or workspace data.
- **Detection before merge.** A wrong deletion of a *live* symbol surfaces as a
  `compileall`/import error, a failing `scripts/run_all_tests.sh`, or a
  `check_dead_code.py` "new orphan" regression — all in CI before merge, not in
  production.
- **Post-merge safety net.** Because the deleted code is preserved in git history
  and the deletions are small and localized, a regression discovered later (e.g. a
  dynamic seam the graph missed) is recovered by reverting the specific PR and
  reclassifying the node `DYNAMIC_REFERENCE_RISK` so it is never re-proposed.
- **Escalation path.** If two consecutive deletion PRs produce cascade orphans or
  gate failures, pause 057 and route the affected nodes back to `056` review — do
  not keep force-deleting.

## 15. Dependencies

Per the master dependency graph (`053 -> 054 -> 055 -> 056 -> 057 -> 058`):

- **Directly depends on: 056** (`classify_unused_functions_and_files`). 056 produces
  and human-reviews `docs/refactoring/reports/dead_code_candidates.md` — the **only**
  authoritative source of what 057 may delete — and performs any `QUARANTINE` /
  `MOVE_TO_LEGACY` relocation. 057 must not start until that review is complete.
- **Transitively depends on: 055** (`add_dead_code_candidate_checker` →
  `check_dead_code.py`, re-run by 057 for the no-new-orphan gate), **054**
  (`add_reference_graph_analyzer` → `reference_graph.json`, the evidence base), and
  **053** (`inventory_reference_roots` → the R1–R12 root set incl. dynamic roots).
- **Global precondition — inventory subtasks that must precede *any* runtime code
  change:** `001, 002, 020, 036, 045, 053, 059, 060, 067`. Because 057 **is** a
  runtime code change (deletion), it lands only after all nine baseline/inventory
  subtasks, consistent with the master rule. `053` is both a direct-chain ancestor
  and one of the nine.
- **Downstream: 058** (`add_dead_code_checker_to_quality_report`) consumes 057's
  before/after deletion counts to populate the quality report's dead-code section;
  058 depends on 057 (and on 055).
- **Coordinates with (not blocked by):** the QUARANTINE holding-zone naming is owned
  by the directory-policy stream (subtask 003 / 016); 057 only *deletes* and never
  relocates, so it does not need that zone to exist.

## 16. Risk Level

**Risk: High.** **Does this subtask change runtime code? Yes** — 057 physically
removes source files/symbols from the working tree. (Writing *this planning
document* changes no runtime code.)

Risk drivers: deletion is the one action in this stream that is **not**
behavior-preserving by construction — a wrong delete is a functional regression, and
ARI's six dynamic seams (string-keyed publish backends, `_COMPOSITES`, prompt/rubric
DATA, MCP stdio dispatch, cross-language HTTP, TEST_ONLY loaders) make some live code
invisible to a naive import graph. Mitigations that pull the *residual* risk down:
(a) 057 deletes **only** the reviewed `SAFE_DELETE_CANDIDATE` set — expected to be
small and dominated by superseded helpers and ruff micro-dead-code (`013` §7); (b) a
per-candidate re-verification (zero inbound edges + grep proof); (c) the contract
firewall that reclassifies any contract-touching candidate out of scope; (d) the
full `scripts/run_all_tests.sh` suite plus the `check_dead_code.py` no-new-orphan
re-scan on every PR; and (e) small, independently revertible PRs with no data-format
change. The label is High (not Medium) because the *action class* is destructive,
even though the *executed set* is intentionally the safest slice of it.

## 17. Notes for Implementer

- **Do not start without the input.** `docs/refactoring/reports/dead_code_candidates.md`
  must exist and be the *reviewed* `056` output. Today the directory is empty — 057
  is blocked. Do not hand-roll a candidate list from a raw import scan.
- **Trust the dynamic overlay, not your intuition.** The four
  `ari/publish/backends/*` modules, `_COMPOSITES`, every `ari/prompts/**.md`, and the
  23 `config/reviewer_rubrics/*.yaml` files *look* unreferenced but are live by
  string. If a candidate is in a §2.2 seam, it is not a deletion — full stop.
- **`ari.schemas.load`/`schema_path` are TEST_ONLY, not dead.** They have no
  production importer but are exercised by `tests/`; deleting them breaks the suite.
  Same trap for anything reachable only from `ari-core/tests/`.
- **Never blanket-`ruff --fix`.** 341 `F401` findings include `ari.public`-style
  re-exports and `TYPE_CHECKING` imports; a wholesale fix strips PUBLIC_CONTRACT.
  Remove only classifier-confirmed imports/locals, file by file (§7.3).
- **Watch for cascade orphans.** After deleting a symbol, its only-caller helper may
  become newly dead. Re-run `check_dead_code.py`; fold a trivially-dead cascade into
  the same PR, or stop and re-review — never let 057 *create* dead code.
- **Respect MCP name flattening.** Use the `(skill, tool_name)`-keyed graph and the
  `013` §5.3 collision report; a handler that looks unreferenced may be a collision
  victim in the flat namespace, not dead.
- **Keep the guard shim sites.** `refactor-guards.yml` lists legitimate `~/.ari/`
  touch points (`_deprecation.py`, `migrations/`, `paths.py`, memory/publish/clone/
  registry/viz shims). Those are migration surfaces — do not delete them as "dead,"
  and do not introduce a new `~/.ari/` reference.
- **Small PRs, off `main`.** One coherent deletion group each, leaf-first,
  independently revertible, with node-id + grep evidence in the body. This is how a
  missed dynamic edge stays a one-line `git revert` instead of an outage.
- **`sonfigs/` does not exist.** The confusable trio is `ari-core/ari/config/`
  (code), `ari-core/ari/configs/` (packaged defaults), and top-level
  `ari-core/config/` (rubric/profile DATA). 057 touches none of the
  config-consolidation concerns (subtask 003).
- **Frontend is out of scope for deletion.** No file under
  `ari-core/ari/viz/frontend/` is a 057 target; `npm test`/`npm run build` are N/A.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **057** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
