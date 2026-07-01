# Subtask 018: Add Tests For Architecture Boundaries

> **Phase:** 10 — Docs and Tests.
> **Repo:** `/home/t-kotama/workplace/ARI` (branch `main`, `ari-core` version `0.9.0`).
> **Planning date:** 2026-07-01. **Author role:** senior software architect.
> **Runtime code change:** **No** (adds/extends `pytest` test modules and one test helper only).
> **Companion documents:** [`003 — Dependency Boundary Report`](../003_dependency_boundary_report.md)
> (defines boundaries **B1–B11**), [`026 — import-boundary checker`](../007_subtask_index.md)
> (`scripts/check_import_boundaries.py`, the CI-side static-analysis counterpart — does not
> exist yet), [`010 — Contract Preservation Policy`](../010_contract_preservation_policy.md).

---

## 1. Goal

Encode the ARI **architecture boundaries** as executable `pytest` guards so that a boundary
violation fails `pytest -q` (in-process, on every PR) rather than being caught only by prose
review. Concretely:

1. **Keep** the boundary guards that already exist (they are green today) and register them in
   a single index so their coverage is auditable.
2. **Add** in-process guards for the boundaries from report `003` that currently have **no
   test**: B2 (core ↛ skill), the core→viz inversion, B5 (evaluator independence), B6 (model
   backend independence).
3. For boundaries that are **still violated** at the time of writing, add the guard in
   `xfail(strict=False)` form with a `reason=` pointing at the ADAPT subtask that will fix it,
   so the guard auto-flips to a real green check the moment the fix lands — no test rewrite
   needed.
4. Add a **meta/index test** asserting that every boundary B1–B11 is either covered by a live
   guard or explicitly waived with a documented reason, so a future boundary can never be
   silently unguarded.

This subtask **adds coverage only**; it does not move, rename, or repoint any runtime module.

## 2. Background

Report `003` (640 lines) defines the target dependency map and 11 boundaries B1–B11, each
tagged KEEP / ADAPT / MERGE / REVIEW_REQUIRED. Several of these already have partial `pytest`
enforcement inside the in-process safe set `ari-core/tests/` (per `pytest.ini`, `testpaths =
ari-core/tests`):

- **B1** (skill → only `ari.public.*`) is guarded twice:
  `ari-core/tests/test_public_api_boundary.py` (126 lines, AST walker with a line-pinned
  `_GRANDFATHERED` waiver) and `ari-core/tests/test_skill_public_contract.py` (117 lines,
  regex scanner understanding `except ImportError:` fallbacks, plus an allowlist-rot test).
- **B9** (prompts externalized) is partially guarded by
  `ari-core/tests/test_prompt_extraction.py` (sha256 hash pins for each extracted
  `ari/prompts/<key>.md`).
- Runtime-path hygiene (related to B8) is guarded by
  `ari-core/tests/test_no_user_home_writes.py` (57 lines; no `$HOME/.ari/` writes on import)
  and enforced in CI by `.github/workflows/refactor-guards.yml`.
- Viz response-shape drift (B3/B4 wire contract) is guarded by
  `ari-core/tests/test_api_schema_contract.py` (108 lines) and `test_api_paperbench.py`.

The gaps are the **direction rules that have no in-process guard at all**: nothing asserts that
`ari-core/ari/**` does not import `ari-skill-*` (B2), nothing catches the known core→viz
inversion at `ari/cli/lineage.py:151`, and nothing pins evaluator/model-backend independence
(B5/B6). This subtask fills those gaps.

**Relationship to subtask 026.** `026` designs `scripts/check_import_boundaries.py`, a
standalone static-analysis CLI meant for staged CI modes (warning → regression → strict, per
B11). `018` is the **in-process `pytest` surface** of the same rules: it runs in the default
`pytest ari-core/tests` process that every contributor and `refactor-guards.yml` already runs.
The two share rule *definitions* but are deliberately separate enforcement surfaces; keep their
allow/waiver lists conceptually parallel. `018` does not depend on `026` shipping first.

## 3. Scope

In scope (all under `ari-core/tests/`, plus a test-only helper):

- A shared AST import-scanner helper reused by the new guards (a **test** module, not a runtime
  module): `ari-core/tests/_arch_boundaries.py`.
- New guard: **B2** — `ari-core/ari/**` must not `import ari_skill_*`, with the single
  sanctioned exception `ari_skill_memory` (report `003` §11).
- New guard: **core→viz direction** — non-viz `ari-core` code must not import `ari.viz.*`,
  except the sanctioned `viz` CLI command entry point.
- New guard: **B5** — `ari/evaluator/**` must not import `ari.cli`, `ari.viz`, or file-layout
  modules; and its LLM calls should route through `LLMClient` rather than `litellm` directly.
- New guard: **B6** — `ari/llm/**` (model-backend layer) must not import `ari.viz`,
  `ari.evaluator`, or `ari.cli`.
- A **meta/index test** mapping B1–B11 → the guard module (or explicit waiver) that covers it.
- A short section in `ari-core/tests/README.md` documenting the boundary-guard family and the
  `xfail`→green ratchet convention.

## 4. Non-Goals

- **No runtime code changes.** This subtask does not fix any boundary violation; it only makes
  violations visible. The fixes are the ADAPT subtasks (B1 → 008/009/013 public-API widening;
  B7 core→viz → 011/012; B3 → 021–024/062; B5/B6 → 008/009). Guards for still-violated
  boundaries are `xfail`, not deletions of the offending code.
- **No `scripts/check_import_boundaries.py`.** That is subtask `026`; do not create it here.
- **No frontend import-boundary tests.** B4 (`frontend/` → `src/types` + `services/api.ts`
  only) is *Respected* today and its dedicated guard belongs to the dashboard cluster
  (`065 add_dashboard_contract_and_schema_tests` / `063`). `018` is the Python/`pytest`
  surface only; `npm test`/`npm build` are not part of this subtask.
- **No rewrite of the existing B1 guards.** `test_public_api_boundary.py` and
  `test_skill_public_contract.py` stay as-is (KEEP). Optionally they *may* later be re-pointed
  at the shared helper — noted as a follow-up MERGE, not required here.
- **No new CI workflow.** CI staging (B11) is subtask `032`/`046`/`049`; the new tests simply
  run inside the existing `refactor-guards.yml` `pytest ari-core/tests/` step.
- **No cross-skill server imports.** Guards must scan skill/core files as text via `ast.parse`,
  never `import` a skill `src/server.py` (see the single-process hazard in `pytest.ini`).

## 5. Current Files / Directories to Inspect

Existing boundary/contract guards (KEEP — read before adding, to avoid duplication):

- `ari-core/tests/test_public_api_boundary.py` (126 lines) — B1 AST walker + `_GRANDFATHERED`.
- `ari-core/tests/test_skill_public_contract.py` (117 lines) — B1 regex scanner + allowlist +
  `test_allowlist_entries_still_exist` rot check.
- `ari-core/tests/test_no_user_home_writes.py` (57 lines) — `$HOME/.ari/` write guard (B8).
- `ari-core/tests/test_prompt_extraction.py` — B9 externalized-prompt sha256 pins.
- `ari-core/tests/test_api_schema_contract.py` (108 lines) — viz REST response-shape contract.
- `ari-core/tests/README.md` (8.4 KB) — test-suite conventions; add the boundary-guard section.
- `ari-core/pytest.ini` — `testpaths = ari-core/tests`, `--import-mode=importlib`,
  `asyncio_mode = auto` (the constraints the new tests must live within).

Boundary definitions and known violation sites (to translate into assertions):

- `docs/refactoring/003_dependency_boundary_report.md` — §2 target map, §3–§14 per-boundary,
  §16 status summary table (the authoritative B1–B11 list), §15 checker design constraints.
- `ari-core/ari/cli/lineage.py:151` — `from ari.viz.api_orchestrator import
  _api_launch_sub_experiment` (the **core→viz inversion**; guard must catch this, `xfail`).
- `ari-core/ari/cli/commands.py:169` — the `viz` command entry that legitimately imports
  `ari.viz` to launch the dashboard (the **sanctioned** core→viz edge; must be allow-listed).
- `ari-core/ari/evaluator/llm_evaluator.py:24` (`import litellm`) and `:585`
  (`await litellm.acompletion(...)`) — the B5/B6 provider leak (guard the litellm-direct part
  with `xfail` referencing 008/009).
- Core sites importing the sanctioned skill (12 files under `ari-core/ari/`; report `003` §16
  cites "13 sites"): `ari/agent/loop.py`, `ari/cli/commands.py`, `ari/cli/run.py`,
  `ari/memory/auto_migrate.py`, `ari/memory_cli.py`, `ari/memory/letta_client.py`,
  `ari/pipeline/orchestrator.py`, `ari/pipeline/verified_context.py`, `ari/viz/api_memory.py`,
  `ari/viz/checkpoint_lifecycle.py`, `ari/viz/node_work_api.py`, `ari/viz/routes.py` — all
  `ari_skill_memory` only, so the B2 guard should **pass** today with `ari_skill_memory`
  allow-listed.
- `ari-core/ari/public/__init__.py` and the 8 `ari/public/*.py` submodules — the stable surface
  the guards reference as "allowed skill→core target."

Directories the new guards walk: `ari-core/ari/**` and the 14 `ari-skill-*/src/**`,
`ari-skill-*/tests/**` (via `Path.rglob("*.py")`, text-only).

## 6. Current Problems

1. **Direction rules are unguarded.** B2 (core ↛ skill except `ari_skill_memory`) and the
   core→viz inversion have zero in-process tests; a regression (e.g. a new `import ari_skill_web`
   in `ari/pipeline/`) would pass `pytest -q` silently.
2. **The known core→viz inversion is invisible to the suite.** `ari/cli/lineage.py:151` reaches
   *up* into `ari.viz.api_orchestrator` (report `003` §9); nothing fails because of it.
3. **Evaluator/model-backend independence (B5/B6) is asserted only in prose.** The
   `litellm.acompletion` call at `llm_evaluator.py:585` bypasses `LLMClient`; no test records
   that this is a tolerated-but-tracked leak.
4. **Duplicated scanner logic.** `test_public_api_boundary.py` and `test_skill_public_contract.py`
   each re-implement an `ari.*` import scanner (one AST, one regex). New guards would add a third
   copy unless a shared helper is introduced.
5. **No coverage map.** There is no single place asserting "every boundary B1–B11 has a guard."
   A newly added boundary in report `003` could ship with no test and nobody would notice.
6. **No ratchet convention for known-violated boundaries.** There is no agreed pattern for a
   guard that should currently fail (violation present) but must turn green once the ADAPT lands.

## 7. Proposed Design / Policy

**P1 — AST/text scan, never import.** Every new guard reads source files with
`ast.parse(path.read_text())` (matching `test_public_api_boundary.py`'s proven approach). No
guard imports an `ari-skill-*/src/server.py`; this preserves the single-process safety that
`pytest.ini` documents. Core-only guards (B5/B6, core→viz) may `import` core modules where an
import graph is easier to assert, but must still avoid importing skill servers.

**P2 — One shared helper.** Add `ari-core/tests/_arch_boundaries.py` exposing:
`repo_root() -> Path`; `iter_py(root: Path) -> Iterator[Path]`;
`ari_imports(path: Path) -> list[tuple[int, str]]` (dotted `ari.*` / `ari_skill_*` targets with
line numbers, mirroring `test_public_api_boundary._ari_imports`); and
`in_except_importerror(lines, i) -> bool` (fallback-shim detection). The leading underscore keeps
it out of pytest collection. New guards import from it; existing B1 guards are left untouched
(re-pointing them is an optional later MERGE, tracked in the index test's comment).

**P3 — Allowlist + waiver model (parallel to 026).** Each guard carries an explicit, commented
allow/waiver set:
- B2 guard: allowed core→skill target is exactly `ari_skill_memory` (report `003` §11). Any
  other `ari_skill_*` import under `ari-core/ari/**` fails.
- core→viz guard: allowed importer of `ari.viz.*` from outside `ari/viz/` is exactly the `viz`
  CLI command in `ari/cli/commands.py`. `ari/cli/lineage.py:151` is a **waiver** (`xfail`).

**P4 — `xfail(strict=False)` ratchet for live violations.** Boundaries still violated at write
time get a guard decorated `@pytest.mark.xfail(strict=False, reason="B7 core→viz inversion at
ari/cli/lineage.py:151 — fixed by subtask 011/012")`. `strict=False` means the suite stays green
while the violation exists; when the ADAPT lands the test XPASSes (visible in `-rX` output), and
the implementer of that ADAPT removes the marker to convert it to a hard guard. Document this
convention in `tests/README.md`.

**P5 — Boundary coverage index.** Add `test_architecture_boundary_index.py` with a table
`_BOUNDARY_GUARDS: dict[str, str]` mapping each of `B1..B11` to either the guard module filename
that covers it or a sentinel `"waived: <reason>"` (e.g. B10/B11 are CI/scripts concerns owned by
026/032, not `pytest`-testable). One test asserts all of B1–B11 are present as keys (catches a
new boundary with no entry); a second asserts each non-waived value names a file that exists in
`ari-core/tests/`.

**P6 — Additive only, contract-safe.** No guard imports change; no `ari.public.*` symbol, CLI
name, MCP tool name, dashboard endpoint, or file format is touched. The guards only *read*.

## 8. Concrete Work Items

1. **Create `ari-core/tests/_arch_boundaries.py`** — the shared, non-collected helper (P2).
   Cover it indirectly through the guards; no standalone test needed.
2. **Create `ari-core/tests/test_core_does_not_import_skills.py`** (B2). Walk
   `ari-core/ari/**/*.py`; parse imports; fail on any `import ari_skill_*` /
   `from ari_skill_* import ...` whose top-level package is not `ari_skill_memory`. Expected
   result today: **pass** (the 12 sites are all `ari_skill_memory`). Include a second test
   asserting the sanctioned edge *exists* somewhere (so the guard can't rot into a vacuous pass).
3. **Create `ari-core/tests/test_core_viz_direction.py`** (core→viz inversion). Walk
   `ari-core/ari/**` excluding `ari/viz/**`; fail on any `ari.viz.*` import whose file is not the
   allow-listed `ari/cli/commands.py` `viz`-command site. Mark the assertion covering
   `ari/cli/lineage.py:151` with `xfail(strict=False, reason=... subtask 011/012)`; structure the
   test so the `lineage.py` offender is isolated in its own `xfail` case while the general rule
   (which passes) is a separate non-xfail case.
4. **Create `ari-core/tests/test_evaluator_independence.py`** (B5). Assert `ari/evaluator/**`
   does not import `ari.cli`, `ari.viz`, `ari.paths`, `ari.checkpoint` (passes today). Add a
   separate `xfail(strict=False, reason=... subtask 008/009)` case pinning the direct
   `litellm` import/`acompletion` leak at `ari/evaluator/llm_evaluator.py:24/585`.
5. **Create `ari-core/tests/test_model_backend_independence.py`** (B6). Assert `ari/llm/**` does
   not import `ari.viz`, `ari.evaluator`, or `ari.cli` (expected pass; confirm during
   implementation and `xfail` any surprise).
6. **Create `ari-core/tests/test_architecture_boundary_index.py`** (P5) — the coverage map.
7. **Extend `ari-core/tests/README.md`** — add an "Architecture-boundary guards" subsection:
   the B1–B11 → guard mapping, the `_arch_boundaries.py` helper, and the P4 `xfail`→green ratchet
   rule (violations are fixed by ADAPT subtasks, not by editing the guard).
8. **Verify** with the Section 12 commands; confirm no pre-existing test regresses and the new
   `xfail` cases report as `xfailed` (not `failed`).

## 9. Files Expected to Change

**New files (all under the in-process safe set):**

- `ari-core/tests/_arch_boundaries.py` — shared AST scanner helper (test-only, not collected).
- `ari-core/tests/test_core_does_not_import_skills.py` — B2 guard.
- `ari-core/tests/test_core_viz_direction.py` — core→viz direction guard (+ `lineage.py` xfail).
- `ari-core/tests/test_evaluator_independence.py` — B5 guard (+ litellm-leak xfail).
- `ari-core/tests/test_model_backend_independence.py` — B6 guard.
- `ari-core/tests/test_architecture_boundary_index.py` — B1–B11 coverage-map meta test.

**Modified file:**

- `ari-core/tests/README.md` — new "Architecture-boundary guards" subsection.

**Explicitly NOT changed:** any file under `ari-core/ari/**`, `ari-skill-*/src/**`,
`ari-core/ari/viz/frontend/**`, any `config/` / `configs/` YAML, any `.github/workflows/*.yml`,
`scripts/**`, or the existing B1 guards `test_public_api_boundary.py` /
`test_skill_public_contract.py`.

## 10. Files / APIs That Must Not Be Broken

The new tests only read source and assert on imports; none of the frozen contracts are touched.
Confirm the guards do **not** assert anything that would force a contract-breaking change:

- Console script `ari = ari.cli:app` and all CLI command names / option flags / env-var side
  effects (`ari-core/pyproject.toml:33`, `ari/cli/__init__.py`). The `viz` command's import of
  `ari.viz` must remain **allowed** by the core→viz guard.
- Public Python API `ari.public.*` — the guards reference it as the *allowed* target; they must
  not require narrowing it.
- MCP tool contracts (bare snake_case names, `inputSchema`, `{"result"|"error"}` envelope,
  `mcp__<skill>__<tool>` naming, `ari/mcp/client.py`). The B1 guards already treat `ari.mcp` as
  public; do not change that.
- Dashboard API endpoint paths + response shapes (`ari/viz/routes.py` + `api_*.py`,
  `frontend/src/services/api.ts`).
- Checkpoint / output / config file formats (`ari/checkpoint.py`, YAML under `config/` and
  `ari/configs/`).
- The `ari-skill-* → ari-core` stable interface (`ari.public.*`) and the sanctioned
  `ari-core → ari_skill_memory` edge (report `003` §11) — the B2 guard must allow-list the
  latter, not forbid it.
- The existing green guards (`test_public_api_boundary.py`, `test_skill_public_contract.py`,
  `test_no_user_home_writes.py`, `test_prompt_extraction.py`, `test_api_schema_contract.py`)
  must continue to pass unchanged.

## 11. Compatibility Constraints

- Guards are **additive**; they widen test coverage without altering any importable surface.
- Because report `003` classifies B1/B2/B5/B6 as KEEP or KEEP+ADAPT (not DELETE), the guards
  encode the *existing* respected direction plus explicit waivers — they never demand a
  contract-breaking move. Any boundary whose fix would touch a frozen contract is handled by its
  ADAPT subtask via a compatibility adapter (widened `ari.public.*`), not by this subtask.
- `xfail(strict=False)` guarantees the suite is green before the corresponding ADAPT lands, so
  `018` can be merged independently of 008–014 without turning CI red.
- The helper `_arch_boundaries.py` uses only the standard library (`ast`, `pathlib`) — no new
  dependency is added to `ari-core/pyproject.toml` (`radon` is not installed; `ruff` is
  available but not needed at test time).
- The guards must respect `--import-mode=importlib` and the single-process constraint: text-scan
  skill files, never import them.

## 12. Tests to Run

From the repo root `/home/t-kotama/workplace/ARI`:

```bash
python -m compileall ari-core/tests            # syntax check the new test modules
pytest ari-core/tests -q                       # in-process safe set (the 018 guards live here)
pytest ari-core/tests -q -rX                   # confirm the new xfail cases report as XFAIL/XPASS
ruff check ari-core/tests                       # lint the new test files
```

Targeted runs while developing:

```bash
pytest ari-core/tests/test_core_does_not_import_skills.py \
       ari-core/tests/test_core_viz_direction.py \
       ari-core/tests/test_evaluator_independence.py \
       ari-core/tests/test_model_backend_independence.py \
       ari-core/tests/test_architecture_boundary_index.py -q -rX
```

Full multi-package suite (skills each in their own process — must stay green):

```bash
bash scripts/run_all_tests.sh
```

`npm test` / `npm run build`: **not applicable** — `018` adds no frontend code (B4 frontend
boundary tests are deferred to subtasks 063/065). The CI job in
`.github/workflows/refactor-guards.yml` already runs `pytest ari-core/tests/`, so the new guards
execute in CI with no workflow edit.

## 13. Acceptance Criteria

1. `pytest ari-core/tests -q` passes with the new guards present; the still-violated boundaries
   report as `xfailed` (not `failed`), verifiable via `-rX`.
2. B2 guard (`test_core_does_not_import_skills.py`) **passes** today and would **fail** if a
   non-`ari_skill_memory` skill import were added under `ari-core/ari/**` (validate by a scratch
   local edit, then revert — do not commit the edit).
3. core→viz guard flags exactly `ari/cli/lineage.py:151` as the waived offender and allows the
   `viz` command's `ari.viz` import in `ari/cli/commands.py`.
4. B5 guard passes for the CLI/viz/layout rules and `xfail`s the `litellm`-direct leak at
   `llm_evaluator.py:24/585` with a reason naming subtask 008/009.
5. B6 guard passes (or its surprise offenders are `xfail`-documented with a subtask reference).
6. `test_architecture_boundary_index.py` enumerates all of B1–B11, each mapped to a real guard
   file or an explicit `"waived: ..."` reason; the test fails if a boundary key is missing or a
   named guard file does not exist.
7. All pre-existing tests still pass; `ruff check ari-core/tests` and
   `python -m compileall ari-core/tests` are clean.
8. `ari-core/tests/README.md` documents the guard family and the `xfail`→green ratchet.
9. No file outside `ari-core/tests/` is modified; `git status` shows only the six new test files
   and the README edit.

## 14. Rollback Plan

Fully reversible — the change is test-only and additive:

1. `git rm` the six new files under `ari-core/tests/` (`_arch_boundaries.py` and the five
   `test_*.py` guards).
2. `git checkout -- ari-core/tests/README.md` to revert the doc subsection.
3. Re-run `pytest ari-core/tests -q` to confirm the suite returns to its pre-018 state.

No runtime module, config, workflow, or contract was touched, so rollback cannot affect any
shipped behavior. If a single guard proves flaky, it can be removed in isolation (or marked
`skip` with a reason) without affecting the others, since each guard is a self-contained file.

## 15. Dependencies

**Hard graph edges:** none. In the provided dependency graph, **018 has no predecessor edge**
(the subtask index `007` §Table footnote 3 confirms this and marks 018 "Can Run Independently =
Yes"). 018 is **not** a runtime change, so it is *not* gated by the nine inventory subtasks
(001, 002, 020, 036, 045, 053, 059, 060, 067).

**Soft / logical ordering (not encoded as graph edges — do not invent them):**

- Consumes the boundary definitions authored in `003_dependency_boundary_report.md` (B1–B11);
  read it first.
- Runs rules parallel to subtask `026` (`scripts/check_import_boundaries.py`). 018 does **not**
  require 026 to ship first; keep their allow/waiver lists conceptually aligned.
- The `xfail` markers reference the ADAPT subtasks that will flip them green:
  B7 core→viz inversion → **011/012**; B5/B6 evaluator/model-backend leak → **008/009**;
  B2 `ari_skill_memory` sprawl centralization → **013**; B1 widening → **008/009/013**;
  B3 viz thinning → **021–024 / 062**. 018 does not block on these — it precedes them as the
  green guard they turn on.
- Sibling in Phase 10: `034 add_contract_snapshot_fixtures` (snapshots for `ari.public.*`, MCP
  schemas, dashboard endpoints) — complementary, no ordering requirement.

Report `007` §"Recommended Execution Order" places 018 late/terminal (boundary tests follow the
Phase-3 extractions) as **soft** ordering; because its violated-boundary guards are `xfail`, it
can nonetheless be merged at any time without breaking CI.

## 16. Risk Level

**Low.** Runtime code change: **No** — this subtask adds `pytest` guard modules and one
test-only helper, plus a README subsection. It imports no skill servers, changes no contract, and
uses only the standard library. The only residual risk is a guard that is too strict and fails on
a legitimate edge; this is mitigated by (a) the explicit allowlist/waiver model (P3), (b)
`xfail(strict=False)` for known violations (P4), and (c) validating each guard against the cited
real offender/allowed sites before committing. Consistent with subtask index `007`: 018 is Low
risk, non-runtime.

## 17. Notes for Implementer

- **Reuse the proven pattern.** `test_public_api_boundary.py:47-63` (`_ari_imports`) is the
  reference AST walker; lift its logic into `_arch_boundaries.py` and extend it to also surface
  `ari_skill_*` targets. Do not re-`import` skill code — parse text.
- **Path anchoring.** Existing guards compute the repo root as
  `Path(__file__).resolve().parents[2]` (see `test_skill_public_contract.py:22`) or
  `.parent.parent.parent` (`test_public_api_boundary.py:26`). Match that so the helper works both
  under `pytest ari-core/tests` and `bash scripts/run_all_tests.sh`.
- **`viz` command allow-list.** When writing the core→viz guard, confirm the current line of the
  `viz` command in `ari/cli/commands.py` (facts cite `:169`) and allow-list by *file*, not line,
  to avoid line-drift churn; reserve line pinning for the single `lineage.py:151` waiver.
- **Count discrepancy to expect.** Report `003` §16 says "13 sites" import `ari_skill_memory`;
  a file-level scan finds **12 files** under `ari-core/ari/`. Both are the sanctioned edge — the
  B2 guard counts *files/imports that are not `ari_skill_memory`*, so this discrepancy does not
  affect the pass/fail outcome. Do not "fix" the count.
- **xfail hygiene.** Use `strict=False` so the suite stays green pre-ADAPT; add `-rX` in the
  README's suggested command so XPASS (a landed fix) is visible. Instruct the ADAPT subtask
  owners (via the `reason=` string) to delete the marker when their fix lands.
- **Keep the index test honest.** `test_architecture_boundary_index.py` should assert file
  existence for each non-waived guard so a renamed/removed guard is caught; hardcode B10/B11 as
  `"waived: CI/scripts concern — subtask 026/032/046"` (they are not `pytest`-testable).
- **Do not touch the existing B1 guards.** They are green and line-pinned; re-pointing them at
  the shared helper is an optional future MERGE, out of scope here — note it in a code comment
  only.
- **`sonfigs` note.** There is no `sonfigs/` directory anywhere in the repo (report `003` §1.5);
  do not add any guard referencing it.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **018** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
