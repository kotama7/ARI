# Subtask 045: Inventory GitHub Workflows

> Phase 9: GitHub Integration · Risk: Low · Runtime code change: **No** · Depends on: — (root inventory) · Enables: 046, 047, 048, 049, 050, 051, 052
>
> Planning document only. Nothing here modifies runtime code, imports, prompts,
> configs, workflows, frontend, or directory names. It hands a fresh coding session
> an executable plan to produce a **read-only inventory** of the repository's CI/CD
> surface under `.github/` (plus the scripts those workflows invoke). All paths and
> line counts are repository-real and verified against the tree at planning date
> **2026-07-01** (ari-core `0.9.0`, branch `main`).

## 1. Goal

Produce a **complete, verifiable inventory** of the ARI GitHub Actions CI/CD surface
so that the seven downstream Phase-9 subtasks (046–052) can add or extend workflows
**without duplicating, contradicting, or breaking** what already runs. Concretely,
045 delivers one reference artifact that enumerates, for the current `.github/`
tree:

1. every workflow file (path, line count, byte size),
2. per workflow: trigger event(s) + branch/path filters, jobs, runners, Python/Node
   versions, `fetch-depth`, permissions, concurrency, and the exact commands each
   step runs,
3. every external script/action a workflow invokes, plus a confirmation the target
   exists on disk (all 12 script targets verified present at planning date),
4. the two proven diff-guard idioms already in the tree (`git merge-base
   origin/<base_ref>` vs `github.event.pull_request.base.sha`) and which files use
   which,
5. the `~/.ari/` path-exclude allow-list embedded in `refactor-guards.yml` (14
   entries) that downstream contract-check workflows should reuse verbatim,
6. the components **confirmed absent** today (`ISSUE_TEMPLATE/`,
   `PULL_REQUEST_TEMPLATE.md`, `dependabot.yml`, `CODEOWNERS`, `.github/actions/`),
   which are the net-new deliverables of 047/048/052,
7. a coverage gap table: what the current CI does **not** check (ruff, compileall,
   import boundaries, complexity, public-API/viz-schema/prompt contracts), which are
   the deliverables of 046/049/050/051.

This inventory is the **frozen baseline** that subtasks 046–052 build on. 045 writes
**no runtime code and no workflow YAML**; its only output is a reference document (or
data file) under `docs/refactoring/reports/`. Per
`docs/refactoring/007_subtask_index.md:92` and `:339-360`, 045 is one of the nine
inventory subtasks that must precede any runtime code change, and is the **root** of
the Phase-9 fan-out (`045 -> 046..052`, index `:430-436`).

## 2. Background

The companion planning document `docs/refactoring/012_github_workflow_integration_plan.md`
already describes the *policy* for integrating the refactoring quality gates into
`.github/`. Subtask 045 is the **executable inventory** that 012 references and that
046–052 consume: it turns the prose into a single machine-checkable reference so a
fresh coding session need not re-read every YAML file.

Verified structure at planning date (`find .github -type f`): `.github/` contains
**only** `workflows/`, with exactly five files. Confirmed with `wc -l` and `ls -la`:

| Workflow | Lines | Bytes | Trigger(s) | Touches Python source? |
| --- | ---: | ---: | --- | --- |
| `.github/workflows/refactor-guards.yml` | 105 | 4565 | `pull_request` → `main` **and** `refactoring` | Yes (`~/.ari/` guard + pytest sandbox) |
| `.github/workflows/docs-sync.yml` | 91 | 4335 | `pull_request` → `main` | No (docs/i18n + VitePress build) |
| `.github/workflows/pages.yml` | 64 | 2047 | `push` → `main` (paths: `docs/**`, `report/**`, `README.md`) + `workflow_dispatch` | No (Pages deploy) |
| `.github/workflows/docs-change-coupling.yml` | 58 | 2648 | `pull_request` → `main` | No (report co-change) |
| `.github/workflows/readme-sync.yml` | 28 | 937 | `pull_request` → `main` | No (README `## Contents` parity) |

Total: **346 lines** across 5 files.

Key characteristics of the current surface (all verified by reading the files):

- **All quality gating is documentation/i18n-oriented.** Five of the six PR-time jobs
  check docs/report/README parity. Only `refactor-guards.yml` touches Python, and
  only for the post-checkpoint-scoping `~/.ari/` invariant plus a pytest sandbox run.
- **No workflow runs `ruff`, `python -m compileall`, import-boundary, complexity, or
  public-API/viz-schema/prompt checks.** None of the checkers proposed in Phase 8
  (`check_import_boundaries.py`, `check_public_api_contracts.py`,
  `check_viz_api_schema.py`, `check_complexity.py`, `check_directory_policy.py`,
  `check_prompts.py`) is represented in CI today — so 046/049/050/051 add net-new
  coverage with **no functional overlap** to remove, only pattern reuse.
- **No push-triggered CI except `pages.yml`.** All gating is PR-time. No
  scheduled/cron workflows, no matrix builds, no reusable/called workflows, no local
  composite actions (`.github/actions/` absent).
- **Two diff-guard idioms coexist** and are explicitly compared in-tree:
  `refactor-guards.yml:82` uses `git merge-base origin/${{ github.base_ref || 'main'
  }} HEAD`; `docs-change-coupling.yml:41-47` critiques that idiom in a comment and
  uses the immutable `github.event.pull_request.base.sha` instead. `docs-sync.yml`
  uses `fetch-depth: 0` for the same co-change reason. Downstream new workflows (049,
  050, 051) should prefer `base.sha`.

Prior context relevant to the `~/.ari/` guard: v0.5.0 made ARI checkpoint-scoped (no
more `~/.ari/`); `refactor-guards.yml` enforces that invariant. The
`ari-skill-memory` JSONL store now lives at `{ARI_CHECKPOINT_DIR}/memory_store.jsonl`.

## 3. Scope

In scope (read-only inventory only):

- All five workflow files under `.github/workflows/`.
- The 12 external targets those workflows invoke, and confirmation each exists:
  `scripts/docs/check_report_cochange.py`, `scripts/docs/check_ref_coupling.py`,
  `scripts/docs/check_doc_sources.py`, `scripts/docs/check_i18n_js.py`,
  `scripts/docs/check_site_i18n.py`, `scripts/docs/check_doc_links.py`,
  `scripts/docs/check_readme_parity.py`, `report/scripts/check_i18n.py`,
  `scripts/docs/check_translation_freshness.py`, `scripts/docs/sync_report_pdf.sh`,
  `scripts/docs/assemble_site.sh`, `scripts/readme_sync.py`. (All 12 verified present
  at planning date.)
- The Actions marketplace actions each workflow pins (`actions/checkout@v4`,
  `actions/setup-python@v5`, `actions/setup-node@v4`, `actions/configure-pages@v5`,
  `actions/upload-pages-artifact@v3`, `actions/deploy-pages@v4`) and their version
  pins.
- The `~/.ari/` path-exclude allow-list in `refactor-guards.yml:84-96` (14 file/dir
  entries) and the two ignored-test lists (`refactor-guards.yml:57-60`).
- The set of `.github/` components confirmed **absent** (§6).
- A CI-coverage gap table mapping absent checks to the downstream subtasks that add
  them.

Out of scope (belongs to other subtasks):

- Designing the quality-CI integration policy → subtask **046**
  (`design_quality_ci_integration`) and planning doc `012`.
- Writing `PULL_REQUEST_TEMPLATE.md` → subtask **047**.
- Writing `ISSUE_TEMPLATE/` → subtask **048**.
- Adding contract-check workflow(s) → subtask **049**.
- Extending `docs-sync.yml` → subtask **050**.
- Adding a prompt-change review workflow → subtask **051**.
- Adding `dependabot.yml` + a local-actions policy → subtask **052**.
- Any change to the checker scripts themselves (Phase 8 subtasks 025–035).

## 4. Non-Goals

- **Do not** create, edit, delete, or rename any file under `.github/`.
- **Do not** add, remove, or reorder any workflow trigger, job, step, or action pin.
- **Do not** modify any `scripts/**` file or any checker referenced by a workflow.
- **Do not** author `PULL_REQUEST_TEMPLATE.md`, `ISSUE_TEMPLATE/`, `dependabot.yml`,
  `CODEOWNERS`, or `.github/actions/` — that is 047/048/052 work. 045 only records
  that they are absent.
- **Do not** change the `~/.ari/` allow-list, the ignored-test list, or either
  diff-guard idiom. 045 records them; 049 reuses them.
- **Do not** decide which checkers become blocking vs advisory — that staged-rollout
  policy is 046/012 work.
- **Do not** touch `docs/`, `report/`, README variants, or any runtime code.
- No `sonfigs/` directory exists anywhere in the repo; do not target it. (See §17.)

## 5. Current Files / Directories to Inspect

All paths repository-real, verified 2026-07-01.

**Workflows (the primary inventory subject):**

- `/home/t-kotama/workplace/ARI/.github/workflows/refactor-guards.yml` (105 lines) —
  two jobs: `no-home-ari-writes` (pytest under redirected `HOME`, 4 ignored tests)
  and `no-new-home-ari-refs` (merge-base diff grep with 14-entry path allow-list).
- `/home/t-kotama/workplace/ARI/.github/workflows/docs-sync.yml` (91 lines) — two
  jobs: `docs-sync` (6 hard doc gates + 2 advisory) and `vitepress-build`
  (`sync_report_pdf.sh --check` → `npm ci --prefix docs` → `docs:build`).
- `/home/t-kotama/workplace/ARI/.github/workflows/pages.yml` (64 lines) — `build`
  (Node 20, VitePress build + `assemble_site.sh` → `_site/`) and `deploy`
  (`deploy-pages@v4`); the only deploy workflow, the only push-triggered workflow.
- `/home/t-kotama/workplace/ARI/.github/workflows/docs-change-coupling.yml` (58
  lines) — one job `change-coupling`: hard `check_report_cochange.py`, advisory
  `check_ref_coupling.py` (`continue-on-error: true`).
- `/home/t-kotama/workplace/ARI/.github/workflows/readme-sync.yml` (28 lines) — one
  job `contents-in-sync`: `python scripts/readme_sync.py --check`.

**Scripts invoked by the workflows (confirm existence, do not modify):**

- `/home/t-kotama/workplace/ARI/scripts/docs/check_report_cochange.py`
- `/home/t-kotama/workplace/ARI/scripts/docs/check_ref_coupling.py`
- `/home/t-kotama/workplace/ARI/scripts/docs/check_doc_sources.py`
- `/home/t-kotama/workplace/ARI/scripts/docs/check_i18n_js.py`
- `/home/t-kotama/workplace/ARI/scripts/docs/check_site_i18n.py`
- `/home/t-kotama/workplace/ARI/scripts/docs/check_doc_links.py`
- `/home/t-kotama/workplace/ARI/scripts/docs/check_readme_parity.py`
- `/home/t-kotama/workplace/ARI/scripts/docs/check_translation_freshness.py`
- `/home/t-kotama/workplace/ARI/scripts/docs/sync_report_pdf.sh`
- `/home/t-kotama/workplace/ARI/scripts/docs/assemble_site.sh`
- `/home/t-kotama/workplace/ARI/report/scripts/check_i18n.py`
- `/home/t-kotama/workplace/ARI/scripts/readme_sync.py`

**Companion / index references (read for alignment, do not modify):**

- `/home/t-kotama/workplace/ARI/docs/refactoring/012_github_workflow_integration_plan.md`
  — Phase-9 integration policy (§2 already lists the same five workflows and absent
  components).
- `/home/t-kotama/workplace/ARI/docs/refactoring/007_subtask_index.md:92-99`,
  `:339-360`, `:430-436` — Phase-9 subtask table, prose, and dependency edges.
- `/home/t-kotama/workplace/ARI/docs/refactoring/009_quality_scripts_plan.md` — the
  Phase-8 checker catalog whose CI wiring 046/049/050/051 will consume.

**Confirmed-absent components to record (checked directly; each "No such file or
directory"):** `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md` (and
lowercase `pull_request_template.md`), `.github/dependabot.yml`, `CODEOWNERS`
(checked `.github/`, repo root, and `docs/`), `.github/actions/`.

**Output artifact (the only file this subtask creates):**

- `/home/t-kotama/workplace/ARI/docs/refactoring/reports/045_github_workflow_inventory.md`
  (proposed path; a `.json`/`.yaml` sibling is acceptable if a machine-readable form
  is preferred — mirror the convention used by the 020/036 inventory reports if they
  exist).

## 6. Current Problems

These are **observations to record in the inventory**, not defects for 045 to fix
(fixes belong to 046–052). Each is grounded in a specific file/line.

1. **CI coverage is docs-only for source code.** No workflow runs `ruff`,
   `python -m compileall`, import-boundary, complexity, or public-API/viz-schema/
   prompt checks. The only Python-touching job is `refactor-guards.yml`, scoped to
   `~/.ari/` writes + a pytest sandbox. → gap filled by 046/049/050/051.
2. **Two inconsistent diff-guard idioms coexist.** `refactor-guards.yml:82` uses
   `git merge-base origin/${{ github.base_ref || 'main' }} HEAD`, which resolves a
   remote-tracking ref that can move mid-run; `docs-change-coupling.yml:41-47`
   explicitly critiques this and uses the immutable `github.event.pull_request.base.sha`.
   → 045 records both; new workflows (049/050/051) should standardize on `base.sha`.
   **REVIEW_REQUIRED** (do not "fix" `refactor-guards.yml` in 045).
3. **`pages.yml:21` path filter lists `README.md` only**, not `README.ja.md` /
   `README.zh.md`. Unconfirmed whether intentional; a push that edits only a
   translated README would not trigger a Pages rebuild. → record as an open question
   for 050; **REVIEW_REQUIRED**, do not change here.
4. **No structured contributor intake.** `ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`
   absent — no place for a review checklist to live. → 047/048.
5. **No automated dependency hygiene.** `dependabot.yml` absent; action pins are
   maintained by hand (`checkout@v4`, `setup-python@v5`, etc.). → 052.
6. **No reviewer routing.** `CODEOWNERS` absent, so contract-sensitive paths
   (`ari/public/**`, `ari/viz/routes.py`, MCP `ari-skill-*/src/server.py`) have no
   automatic reviewer assignment. → 052 (or 046 policy).
7. **Duplicated inline setup.** Every workflow re-declares checkout/setup-python/
   setup-node steps; no `.github/actions/` composite action factors them out. → 052
   (actions policy).
8. **Two coexisting checkpoint dirs unrelated to CI but adjacent:** root-level
   `checkpoints/` (appears legacy) vs `workspace/checkpoints/`. Not a workflow
   concern; note only if the inventory touches storage-path CI (it does not today).

## 7. Proposed Design / Policy

045 produces **one inventory artifact** and classifies each existing component with
the master vocabulary. No YAML changes.

**Classification of the five existing workflows (all KEEP — they enforce real,
documented contracts):**

| Workflow | Class | Rationale |
| --- | --- | --- |
| `refactor-guards.yml` | **KEEP** | Enforces the `~/.ari/` post-checkpoint-scoping invariant; its two patterns (merge-base diff + path allow-list) are the reuse template for 049. |
| `docs-sync.yml` | **KEEP** (ADAPT target for 050) | 6 hard doc gates + VitePress build. 050 extends, never duplicates. |
| `pages.yml` | **KEEP** | Only deploy path; self-documents its own rollback (`pages.yml:13-16`). |
| `docs-change-coupling.yml` | **KEEP** | Tri-language report co-change; canonical `base.sha` idiom to copy. |
| `readme-sync.yml` | **KEEP** | Per-directory `## Contents` parity; stdlib-only. |

**Classification of the coexisting diff-guard idioms:** `base.sha`
(`docs-change-coupling.yml`, `docs-sync.yml` via `fetch-depth: 0`) = **KEEP /
preferred**; `origin/<base_ref>` merge-base (`refactor-guards.yml:82`) =
**REVIEW_REQUIRED** (leave as-is in 045; 046 decides whether to migrate).

**Classification of absent components:** `ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`,
`dependabot.yml`, `CODEOWNERS`, `.github/actions/` = **net-new** (record as "does not
exist"; creation is 047/048/052, not 045).

**Inventory artifact structure (recommended sections):**

1. Workflow summary table (path, lines, bytes, trigger, jobs, runner, Py/Node
   version, `fetch-depth`, permissions, concurrency).
2. Per-workflow step-by-step command list (verbatim `run:` commands, with hard-gate
   vs advisory `continue-on-error` marked).
3. Script-invocation map: workflow → script → "exists: yes/no" (all 12 = yes today).
4. Action-pin table: action → version → workflow(s) using it.
5. The `~/.ari/` allow-list (14 entries, `refactor-guards.yml:84-96`) and the 4
   ignored tests (`:57-60`), copied verbatim for 049 reuse.
6. Diff-idiom table (which file uses `base.sha` vs `origin/<base_ref>`).
7. Absent-components table (§6 items 4–7).
8. CI-coverage gap table mapping missing checks → downstream subtask.

The artifact should be **regenerable/verifiable** (a small read-only helper or a
documented `find`/`wc`/`grep` recipe) so `readme-sync.yml` and any future audit can
confirm it has not drifted. If a script is written, place it under `scripts/` and do
not wire it into any workflow (wiring is 046+).

## 8. Concrete Work Items

1. Read all five workflow files end to end and transcribe: trigger events, branch/
   path filters, job names, `runs-on`, `fetch-depth`, `permissions`, `concurrency`,
   Python/Node versions, and every `run:` command (mark `continue-on-error: true`
   steps as advisory).
2. Build the script-invocation map and confirm each of the 12 targets exists on disk
   (`test -e`), recording result. (At planning date all 12 exist.)
3. Build the action-pin table (`actions/checkout@v4`, `setup-python@v5`,
   `setup-node@v4`, `configure-pages@v5`, `upload-pages-artifact@v3`,
   `deploy-pages@v4`).
4. Copy the `~/.ari/` path-exclude allow-list (`refactor-guards.yml:84-96`, 14
   entries) and the 4 ignored-test `--ignore` flags (`:57-60`) into the artifact
   verbatim, labeled as the reuse template for subtask 049.
5. Record the two diff-guard idioms with file:line citations and the in-tree critique
   at `docs-change-coupling.yml:41-47`.
6. Verify and record the confirmed-absent components (`find`/`ls` each; all "No such
   file or directory" at planning date): `ISSUE_TEMPLATE/`,
   `PULL_REQUEST_TEMPLATE.md`, `dependabot.yml`, `CODEOWNERS`, `.github/actions/`.
7. Build the CI-coverage gap table: for each absent check (ruff, compileall, import
   boundaries, complexity, public-API, viz-schema, prompts, dependabot, PR/issue
   templates, CODEOWNERS), name the downstream subtask that adds it (046/047/048/
   049/050/051/052) and confirm no functional overlap with an existing job.
8. Record the `pages.yml:21` `README.md`-only path filter and the
   `refactor-guards.yml` `origin/<base_ref>` idiom as **REVIEW_REQUIRED** open
   questions (do not resolve here).
9. Write the artifact to `docs/refactoring/reports/045_github_workflow_inventory.md`
   (matching the 020/036 report convention if present).
10. Add the new report to the appropriate `docs/refactoring/` README `## Contents`
    index if one is managed by `readme-sync.py` (run `python scripts/readme_sync.py
    --check` to confirm, `--write` to regenerate; this is the only sanctioned
    non-report edit).
11. Cross-check the finished artifact against
    `012_github_workflow_integration_plan.md` §2 and `007_subtask_index.md:339-360`
    for consistency; note any discrepancy in the artifact rather than editing those
    docs.

## 9. Files Expected to Change

**Created (single new inventory artifact):**

- `/home/t-kotama/workplace/ARI/docs/refactoring/reports/045_github_workflow_inventory.md`
  — the inventory itself (or a `.json`/`.yaml` companion if a machine-readable form
  is preferred).

**Possibly touched (index bookkeeping only, if managed):**

- The `## Contents` index of `/home/t-kotama/workplace/ARI/docs/refactoring/reports/README.md`
  (or `docs/refactoring/README.md`) — **only** to register the new report, and only
  via `python scripts/readme_sync.py --write`, so `readme-sync.yml` stays green.

**Explicitly NOT changed:** any file under `.github/workflows/`, any `scripts/**`
file, any workflow-invoked checker, any runtime code under `ari-core/` or
`ari-skill-*/`, any README variant content, `report/**`, or `docs/` site content.

## 10. Files / APIs That Must Not Be Broken

This subtask is read-only inventory; it must not perturb any contract. The following
are recorded as protected surfaces the *downstream* Phase-9 work must preserve, and
which 045 itself must not alter:

- **`.github/workflows/` behavior** — every existing trigger, job, step, and action
  pin stays byte-identical after 045. The 12 workflow-invoked scripts
  (`scripts/docs/*.py`, `scripts/readme_sync.py`, `report/scripts/check_i18n.py`,
  `scripts/docs/*.sh`) are a documented contract (a workflow calls them by exact
  path) — do not rename or move them.
- **CLI `ari`** (`ari = ari.cli:app`) — untouched.
- **`ari.public.*`** stable Python API — untouched.
- **MCP tool contracts** — the 14 `ari-skill-*/src/server.py` servers — untouched.
- **Dashboard API** — `ari/viz/routes.py` + `api_*.py` endpoints + `websocket.py` —
  untouched.
- **Checkpoint / output / config file formats** (`ari/checkpoint.py`, YAML under
  `config/` + `configs/`) — untouched.
- **`ari-skill-* → ari-core` stable interfaces** — untouched.
- **README / docs usage** — the inventory is a new report; existing docs are not
  edited beyond the sanctioned `readme_sync` index update.

No compatibility adapter is required because 045 changes no runtime behavior.

## 11. Compatibility Constraints

- **No runtime behavior changes**, so all public contracts (CLI, `ari.public.*`, MCP,
  dashboard API, file formats, skill→core interfaces) are trivially preserved.
- The inventory artifact **must not** cause any existing workflow to fail. In
  particular, adding a file under `docs/refactoring/reports/` can trip
  `readme-sync.yml` (`readme_sync.py --check` fails CI until the new file is listed in
  its directory README). Run `python scripts/readme_sync.py --check` locally before
  opening the PR and regenerate with `--write` if needed.
- The artifact must remain **consistent with**
  `012_github_workflow_integration_plan.md` §2 and `007_subtask_index.md:339-360`
  (same five workflows, same line counts, same absent-component list). If a
  discrepancy is found, record it in the artifact; do not silently diverge and do not
  edit those planning docs from 045.
- Downstream reuse contract: the `~/.ari/` allow-list and diff-idiom recorded here
  are copied verbatim from `refactor-guards.yml`; if that file changes before 049
  runs, re-verify. Prefer citing `file:line` so drift is detectable.

## 12. Tests to Run

This subtask produces documentation, so the runtime gates are for hygiene/no-regression
only (they should be unaffected since no code changes):

- `python -m compileall .` — must pass (no `.py` added or changed by 045; expect
  no new failures).
- `pytest -q` — from repo root; must pass unchanged. (CI's `refactor-guards.yml`
  runs `pytest ari-core/tests/ -q` under a redirected `HOME`, ignoring
  `test_letta_restart_live`, `test_letta_start_scripts`, `test_ollama_gpu`,
  `test_dashboard_html`; mirror those ignores if reproducing that job locally.)
- `ruff check .` — must pass unchanged (ruff IS available in this environment; radon
  is NOT installed, so do not rely on it).
- **Docs/CI gate self-check** (because the artifact lands under `docs/refactoring/`):
  `python scripts/readme_sync.py --check` — must be green after the artifact is
  registered in its directory README.
- **Frontend `npm test`/`npm run build` are NOT applicable** — 045 adds no frontend
  code (the frontend lives at `ari-core/ari/viz/frontend/` with `vitest`/`vite build`
  scripts, but this subtask does not touch it).
- Optional sanity for the inventory itself: re-run the `find .github -type f` /
  `wc -l .github/workflows/*.yml` / `test -e` recipe used to build the artifact and
  confirm the numbers match what the artifact records (5 files; 346 total lines; 12
  scripts present).

## 13. Acceptance Criteria

- [ ] A single inventory artifact exists at
  `docs/refactoring/reports/045_github_workflow_inventory.md` (or agreed sibling
  format).
- [ ] It enumerates all five workflows with correct line counts (105 / 91 / 64 / 58 /
  28; total 346) and byte sizes (4565 / 4335 / 2047 / 2648 / 937).
- [ ] For each workflow it records trigger(s), branch/path filters, job names,
  runner, Python/Node version, `fetch-depth`, permissions, concurrency, and every
  `run:` command with hard-gate vs advisory (`continue-on-error`) marked.
- [ ] It lists all 12 workflow-invoked scripts and confirms each exists on disk.
- [ ] It records the 6 action pins and their versions.
- [ ] It reproduces the 14-entry `~/.ari/` allow-list
  (`refactor-guards.yml:84-96`) and the 4 ignored tests (`:57-60`) verbatim, labeled
  for 049 reuse.
- [ ] It records both diff-guard idioms with `file:line` citations and the in-tree
  critique at `docs-change-coupling.yml:41-47`.
- [ ] It records the confirmed-absent components (`ISSUE_TEMPLATE/`,
  `PULL_REQUEST_TEMPLATE.md`, `dependabot.yml`, `CODEOWNERS`, `.github/actions/`) as
  "does not exist".
- [ ] It contains a CI-coverage gap table mapping each absent check to its downstream
  subtask (046–052) with a no-overlap confirmation.
- [ ] It flags the `pages.yml:21` `README.md`-only path filter and the
  `refactor-guards.yml` `origin/<base_ref>` idiom as **REVIEW_REQUIRED** open
  questions.
- [ ] No file under `.github/`, `scripts/`, `ari-core/`, or `ari-skill-*/` was
  modified.
- [ ] `python -m compileall .`, `pytest -q`, `ruff check .`, and `python
  scripts/readme_sync.py --check` all pass.

## 14. Rollback Plan

Trivial and low-risk, since the subtask is additive documentation only:

1. `git rm docs/refactoring/reports/045_github_workflow_inventory.md`.
2. Revert the single `## Contents` index line if `readme_sync.py --write` added one
   (or re-run `python scripts/readme_sync.py --write` after the removal).
3. No workflow, script, or runtime file was changed, so there is nothing else to
   undo and no CI behavior to restore. A single `git revert <commit>` fully reverses
   the subtask.

## 15. Dependencies

Per the DEPENDENCY GRAPH and `007_subtask_index.md:92-99, :430-436`:

- **Upstream (must precede 045):** none. 045 is a **root inventory** subtask (index
  `:92` lists Depends = "—") and one of the nine inventories that gate all runtime
  code change (`001, 002, 020, 036, 045, 053, 059, 060, 067`).
- **Downstream (depend on 045; 045 must precede them):** `046`
  (design_quality_ci_integration), `047` (add_pr_template_quality_checklist), `048`
  (add_issue_templates_for_refactoring), `049` (add_contract_check_workflows), `050`
  (add_docs_sync_workflow), `051` (add_prompt_change_review_workflow), `052`
  (add_dependabot_and_actions_policy). Graph edge: `045 -> 046, 047, 048, 049, 050,
  051, 052`.
- **Companion planning docs (read, not blocking):**
  `012_github_workflow_integration_plan.md` (integration policy),
  `009_quality_scripts_plan.md` (checker catalog consumed by 046/049/050/051),
  `007_subtask_index.md` (Phase-9 table + edges).

No other subtask must complete before 045 begins.

## 16. Risk Level

**Low.** Changes runtime code: **No.** This subtask reads existing YAML/scripts and
writes one Markdown report. The only CI-visible side effect is that the new report
must be registered in its directory README so `readme-sync.yml` stays green
(mitigated by running `readme_sync.py --check`/`--write`). No workflow, script,
public API, CLI, MCP, dashboard, or file format is touched. Worst realistic failure
is a stale/inaccurate inventory, which is caught by the §12 re-verification recipe and
cross-check against `012`/`007`.

## 17. Notes for Implementer

- **Ground everything in `file:line`.** The downstream subtasks (especially 049) copy
  the `~/.ari/` allow-list and diff idiom verbatim, so cite `refactor-guards.yml:84-96`
  and `:57-60` precisely; if that file changes before 049, the citation makes drift
  obvious.
- **Do not "fix" the two open questions in 045.** The `origin/<base_ref>` idiom in
  `refactor-guards.yml:82` and the `README.md`-only path filter in `pages.yml:21` are
  **REVIEW_REQUIRED** — record them; resolution is 046/050 work.
- **`base.sha` is the preferred idiom.** When 049/050/051 are written they should use
  `github.event.pull_request.base.sha` (immutable) per the in-tree rationale at
  `docs-change-coupling.yml:41-47`, not the mutable remote-tracking ref.
- **No `sonfigs/` anywhere.** The master prompt's "config/configs/sonfigs" concern is
  a hypothesized typo; the repo has `ari-core/ari/config/` (code that locates config),
  `ari-core/ari/configs/` (packaged default DATA), and top-level `ari-core/config/`
  (rubric/profile DATA). This trio is unrelated to `.github/`; mention only if the
  inventory happens to reference a directory-policy checker. State "does not exist"
  for `sonfigs/`.
- **All 12 workflow-invoked scripts exist today** — but assert it in the artifact
  (`test -e` each) rather than asserting from memory, so a future move is caught.
- **Reserve "deprecated" for external contracts.** For the `origin/<base_ref>` idiom
  and any internal cleanup, use REVIEW_REQUIRED / ADAPT, not "deprecated".
- **Registering the report can break CI.** `readme-sync.yml` runs
  `readme_sync.py --check`, which fails until the new report is listed in its
  directory README. This is the single most likely way to redden the PR; handle it
  with `--write` before pushing.
- **Keep the artifact regenerable.** Prefer a documented `find .github -type f` +
  `wc -l` + `grep`/`test -e` recipe (or a read-only helper under `scripts/`, NOT
  wired into any workflow) so future audits can confirm the inventory has not drifted
  from the tree.
- **Cross-check, do not overwrite.** If the inventory disagrees with
  `012_github_workflow_integration_plan.md` §2 or `007_subtask_index.md`, record the
  discrepancy in the new artifact; those planning docs are owned by other subtasks.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **045** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
