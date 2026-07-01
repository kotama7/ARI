# Subtask 049: Add Contract Check Workflows

- **Subtask ID:** 049
- **Phase:** Phase 9 — GitHub Integration
- **Classification:** `ADAPT` (extend `refactor-guards.yml` by appending jobs) + `KEEP`-additive (add one new `contracts.yml`). No existing workflow job is rewritten, renamed, or removed.
- **Changes runtime ARI code:** **No** (no `.py`, no frontend, no prompt, no config, no directory rename). **Changes CI configuration (`.github/workflows/*.yml`): Yes** — this is the subtask that wires the contract checkers into GitHub Actions. See Section 16.
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`)

> **Planning-phase notice.** Authoring *this* document changes no runtime code, no CI YAML, no scripts, no prompts, no configs, and no directory names — the only file created by this planning step is this `.md` itself. Everything below describes what a *future* coding session that executes subtask 049 will do. When executed, subtask 049 *does* create/modify `.github/workflows/` YAML (that is its deliverable); it still writes **no** ARI runtime code and **no** checker `.py` (those are owned by Phase-8 subtasks 025–031).

---

## 1. Goal

Wire the Phase-8 **contract-regression checkers** into GitHub Actions so they run automatically at PR time, using an **additive** layout that leaves all five existing workflows' behavior intact.

Concretely, subtask 049 delivers:

1. A **new** workflow `.github/workflows/contracts.yml` (all PRs to `main`) hosting the external-contract regression gates:
   - `public-api` → `scripts/check_public_api_contracts.py` (owned by subtask **029**)
   - `viz-api-schema` → `scripts/check_viz_api_schema.py` (owned by subtask **030**)
   - `mcp-tool-contracts` → MCP tool-schema check over the 14 `ari-skill-*/src/server.py` servers
   - `quality-report` → `scripts/generate_quality_report.py` (owned by subtask **031**), a `needs:`-gated aggregation job
2. **ADAPT** `.github/workflows/refactor-guards.yml` by **appending** the refactor-invariant / boundary jobs (its two existing jobs are untouched):
   - `import-boundaries` → `scripts/check_import_boundaries.py` (subtask **026**) — the `ari.public.*` + `core↔skill` boundary is itself a contract
   - `directory-policy` → `scripts/check_directory_policy.py` (subtask **028**)
   - `complexity` → `scripts/check_complexity.py` (subtask **025**)
   - `lint` / `dead-code` → `ruff check .` (advisory) and the `ruff --select F401` slice

Every new job **enters at Stage 1 (advisory, `continue-on-error: true`)**. Promotion to a hard gate is a later, one-line PR (Section 7.4), never part of this subtask.

Out of 049's lane (owned elsewhere, do not implement here): docs-sync additions (**050**), the prompt-change review job (**051**), the dashboard-UX job (dashboard phase), and the `.github/` template/config files `PULL_REQUEST_TEMPLATE.md` / `ISSUE_TEMPLATE/` / `dependabot.yml` / `CODEOWNERS` (**047/048/052**).

## 2. Background

CI in this repo is **almost entirely documentation/i18n-oriented**. There are exactly five workflows under `.github/workflows/` (line counts verified 2026-07-01): `docs-change-coupling.yml` (58), `docs-sync.yml` (91), `pages.yml` (64), `readme-sync.yml` (28), `refactor-guards.yml` (105). Of the six CI jobs across them, five gate docs/report/README parity; only `refactor-guards.yml` touches Python source, and only for the `~/.ari/` invariant plus a pytest-under-redirected-`HOME` run. **No workflow runs `ruff`, `compileall`, an import-boundary check, a complexity check, or a public-API/viz-schema/MCP contract check** (confirmed by reading all five). None of the Phase-8 contract checkers are represented in CI today — so subtask 049 has no functional overlap to untangle, only *pattern reuse*.

`.github/` contains **only** `workflows/` (verified via `ls .github/`). Confirmed absent (each checked directly): `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/dependabot.yml`, `CODEOWNERS`, `.github/actions/`. `.github/workflows/contracts.yml` **does not exist** (verified — this subtask creates it).

Two design inputs already exist and 049 must *consume* rather than re-derive them:
- `docs/refactoring/012_github_workflow_integration_plan.md` — §7.3 ("where each new gate runs") and §15 ("proposed workflow structure") specify exactly the additive two-mechanism layout this subtask implements: append refactor-invariant jobs to `refactor-guards.yml` and add one new `contracts.yml` for external-contract gates. §8 defines the staged warning→failure policy.
- `docs/refactoring/009_quality_scripts_plan.md` (32 KB) — §5 specifies each checker's CLI, `--json`, and exit-code contract; §"related subtasks" (rows 025–031) maps checker files to owning subtasks.

Two proven idioms already live in the repo and must be reused verbatim rather than reinvented:
- **Merge-base diff guard.** `refactor-guards.yml` (line 82) computes `base="$(git merge-base origin/${{ github.base_ref || 'main' }} HEAD)"` then `git diff` over a pathspec — the template for diff-scoped checks.
- **Path-exclude allow-list.** The same workflow's `no-new-home-ari-refs` job grandfathers 14 sanctioned legacy `~/.ari/` sites via `':!<path>'` pathspecs, so the check can be strict everywhere else.

Crucially, `docs-change-coupling.yml` (header lines 42–48) documents why `${{ github.event.pull_request.base.sha }}` is **preferred** over `refactor-guards.yml`'s `origin/${{ github.base_ref }}` idiom: `base.sha` "is immutable for this run and always reachable", whereas a remote-tracking ref "can move if the base branch advances mid-run", and "the checker fails CLOSED if this ref ever fails to resolve." Subtask 049 must use `base.sha` for every *new* diff-scoped job.

## 3. Scope

In scope for subtask 049:

1. **Create `.github/workflows/contracts.yml`** (trigger: `pull_request` → `main`; `fetch-depth: 0`; Python 3.13; `pip install pyyaml`) with jobs `public-api` (029), `viz-api-schema` (030), `mcp-tool-contracts`, and `quality-report` (031, `needs:` all checker jobs). Node 20 + `npm ci --prefix ari-core/ari/viz/frontend` only if the viz-schema checker needs a TypeScript parse; otherwise a pure-Python AST/regex parse of `services/api.ts` keeps the job Python-only (checker's choice, per 030).
2. **ADAPT `.github/workflows/refactor-guards.yml`** by *appending* jobs `import-boundaries` (026), `directory-policy` (028), `complexity` (025), and `lint`/`dead-code` (`ruff`). Its two existing jobs (`no-home-ari-writes`, `no-new-home-ari-refs`) are byte-for-byte unchanged. Rationale: `refactor-guards.yml` is the only workflow triggered on the `refactoring` branch, so refactoring branches get these gates before reaching `main`.
3. **Set every new job to Stage 1 (advisory)** via `continue-on-error: true` (or `--strict`-off), so no green PR turns red on landing.
4. **Enforce the diff/base-ref rules** (Section 7.3): `base.sha` + `fetch-depth: 0` for any diff-scoped job; the `':!<path>'` allow-list convention for grandfathering legacy sites.
5. **Wire the aggregation protocol** (Section 7.5): each checker writes `--json` to a per-job path, uploads it as an artifact; `quality-report` downloads them and renders one PR-comment summary.

Out of scope: everything in Section 4.

## 4. Non-Goals

- **No checker implementation.** No `scripts/check_*.py` and no `scripts/generate_quality_report.py` is written or edited — those are owned by subtasks 025/026/028/029/030/031. This subtask references their CLI contract, not their code. (All are verified **absent** at `scripts/` today.)
- **No rewrite of an existing workflow.** `docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml` are `KEEP` and untouched. `refactor-guards.yml`'s existing two jobs are untouched (only new jobs are appended).
- **No docs-sync or prompt-review job.** The code↔doc "must-change-together" gates belong to subtask **050** (`add_docs_sync_workflow`); the prompt-change review job belongs to subtask **051** (`add_prompt_change_review_workflow`).
- **No `.github/` template/config files.** `PULL_REQUEST_TEMPLATE.md`, `ISSUE_TEMPLATE/`, `dependabot.yml`, `CODEOWNERS`, `.github/actions/` stay absent until their owning subtasks (047/048/052).
- **No dependency installation or manifest edit.** `radon`, `vulture`, and `pnpm` are **not** added; `requirements.txt`, `requirements.lock`, and `ari-core/pyproject.toml` are untouched. PyYAML (already used by the docs jobs) is the ceiling; `ruff` is already installed (0.15.2).
- **No promotion of any gate to Hard.** This subtask *schedules* the rollout at Stage 1; it flips no `continue-on-error` to `false`.
- **No `check_docs_source_sync.py` job.** Subtask 027 is a `DELETE_CANDIDATE` (redundant with `check_doc_sources.py` forward + `check_ref_coupling.py` reverse); it gets no CI job here.
- **No push-time source CI.** New gates are PR gates only; `pages.yml` remains the sole push/deploy workflow and must not be disturbed.

## 5. Current Files / Directories to Inspect

Real repo paths the implementer must read before editing any YAML (all verified to exist 2026-07-01 unless marked absent):

**Existing workflows (read to reuse idioms; only `refactor-guards.yml` is edited, and only by appending):**
- `.github/workflows/refactor-guards.yml` (105 lines) — the ADAPT host. Two jobs: `no-home-ari-writes` (pytest under redirected `HOME`, ignoring `test_letta_restart_live.py`, `test_letta_start_scripts.py`, `test_ollama_gpu.py`, `test_dashboard_html.py`) and `no-new-home-ari-refs` (line 82 merge-base idiom + 14-path `':!'` allow-list). Only workflow also triggered on the `refactoring` branch.
- `.github/workflows/docs-change-coupling.yml` (58 lines) — header lines **42–48** document the `base.sha` preference and fail-closed rule; copy that comment style. Hard gate `check_report_cochange.py`, advisory `check_ref_coupling.py`.
- `.github/workflows/docs-sync.yml` (91 lines) — two jobs; the template for a multi-gate hard/advisory job list and `continue-on-error` advisories. Also the `vitepress-build` job shows the Node-20 + `npm ci --prefix docs` pattern to mirror if a frontend parse is needed.
- `.github/workflows/readme-sync.yml` (28 lines) — single stdlib step `python scripts/readme_sync.py --check`; the minimal single-gate pattern.
- `.github/workflows/pages.yml` (64 lines) — only push-triggered/deploy workflow; read only to confirm new PR gates must **not** interfere with it.

**Checker files this subtask wires (all verified ABSENT — owned by Phase-8 subtasks; do not create here):**
- `scripts/check_public_api_contracts.py` (029) · `scripts/check_viz_api_schema.py` (030) · `scripts/check_import_boundaries.py` (026) · `scripts/check_directory_policy.py` (028) · `scripts/check_complexity.py` (025) · `scripts/generate_quality_report.py` (031). (`ls scripts/check_*.py` → "No such file or directory".)

**Existing checker conventions (read for the invocation/JSON pattern the jobs must match):**
- `scripts/docs/` — `check_doc_sources.py`, `check_doc_links.py`, `check_i18n_js.py`, `check_readme_parity.py`, `check_ref_coupling.py` (`--base-ref`, `--strict`), `check_report_cochange.py` (`--base-ref`), `check_site_i18n.py`, `check_translation_freshness.py`. All: `#!/usr/bin/env python3`, `argparse` + `--json`, exit 1 on error, PyYAML-only.
- `scripts/readme_sync.py` — the `--check`/`--write` snapshot pattern the public-API/contract checkers mirror.
- `report/scripts/check_prompt_snapshots.py` (3157 B) — **Gate 10**; the MERGE target for any prompt-snapshot slice (owned by 051, not 049).
- `scripts/run_all_tests.sh` — per-skill pytest (13 hardcoded paths); **not referenced by any workflow** today; an ADAPT candidate but explicitly *deferred* (012 §15), not 049's job.

**Contract surfaces the new gates protect (read to scope the jobs; do not modify):**
- `ari-core/ari/public/` — 9 modules verified: `claim_gate.py`, `config_schema.py`, `container.py`, `cost_tracker.py`, `llm.py`, `paths.py`, `run_env.py`, `verified_context.py`, `__init__.py` (+ `README.md`). Target of `public-api` job (029).
- `ari-core/ari/viz/routes.py` (1197) + `api_*.py` (`api_experiment.py` 929, `api_paperbench.py` 813, `api_workflow.py`, `api_wizard.py`, `api_settings.py`, `api_state.py`, `api_tools.py`, `api_process.py`, `api_publish.py`, `api_orchestrator.py`, `api_memory.py`, `api_ollama.py`, `api_fewshot.py`, `api_paperbench_worker.py`) and `ari-core/ari/viz/frontend/src/services/api.ts` (863 lines, 24877 B). Target of `viz-api-schema` job (030).
- `ari-skill-*/src/server.py` (14 servers) consumed via `ari-core/ari/mcp/client.py`. Target of `mcp-tool-contracts` job.

**Design inputs (read, cite, reconcile — do not edit):**
- `docs/refactoring/012_github_workflow_integration_plan.md` (§7.3 gate placement, §8 staged policy, §15 workflow structure, §16 subtask map).
- `docs/refactoring/009_quality_scripts_plan.md` (§5 per-checker CLI/JSON contract; §"related subtasks").
- `docs/refactoring/007_subtask_index.md` (canonical numbering; row 96: `049 add_contract_check_workflows`, Phase 9, depends 045, Runtime code change **No**).
- `docs/refactoring/reports/` — output dir for the 032/046 CI-integration plan (currently empty); if that plan lands first, treat it as the authoritative wiring spec.

## 6. Current Problems

1. **No source/contract-quality CI at all.** `grep` over the five workflows confirms no `ruff`, `compileall`, complexity, import-boundary, public-API, viz-schema, or MCP-contract gate runs anywhere. The Phase-8 contract checkers, once written, would have nowhere to run without this subtask.
2. **The contract surfaces most at risk during a refactor are ungated.** `ari.public.*` (9 modules), the dashboard API (`viz/routes.py` 1197 + ~14 `api_*.py`) ↔ `services/api.ts` (863) coupling, and the 14 MCP tool schemas can all be broken today with a green CI. 012 §5 records each of these as "regression gate: **No**".
3. **Idiom drift risk.** The one workflow that diff-scopes (`refactor-guards.yml` line 82) uses the inferior `origin/${{ github.base_ref }}` idiom that `docs-change-coupling.yml` (lines 42–48) explicitly critiques. Without discipline, the new jobs will copy the wrong idiom.
4. **No aggregation surface.** Every existing docs checker emits `--json`, but nothing aggregates them; there is no `needs:`/artifact protocol for `generate_quality_report.py` (031) to render a single PR summary until this subtask defines one.
5. **Checkers do not exist yet.** All six wired scripts are absent (Section 5). A job pointing at a missing script fails; therefore this subtask's jobs must be authored so they *only run green once their checker lands* (Section 7.6) — i.e., 049's YAML must be able to be committed at Stage-1 advisory without turning the tree red before 025/026/028/029/030/031 merge.
6. **Numbering ambiguity across planning docs.** `012` §16 uses an older mapping that assigns subtask IDs **045–052** to the checker *scripts* (there, `049` = `check_viz_api_schema.py`). The canonical `007_subtask_index.md` (row 96, matching this subtask's title) assigns checkers to **025–031** and reserves **045–052** for GitHub-integration items — making `049` = `add_contract_check_workflows`. The implementer must follow `007` (Section 15).

## 7. Proposed Design / Policy

All of the following is consistent with `012` §7.3/§8/§15.

### 7.1 Additive layout (no existing workflow rewritten)

Two mechanisms only, both additive:
- **ADAPT `refactor-guards.yml`** by *appending* refactor-invariant / boundary jobs. Its two existing jobs stay byte-for-byte. These run on both `main`- and `refactoring`-targeted PRs (that workflow's existing trigger), giving refactor branches the gates early.
- **Add one NEW `contracts.yml`** (all PRs to `main`) for external-contract regression gates plus the aggregation job. Grouping the contract gates keeps the required-status-check list readable.

Job map (canonical `007` subtask IDs in brackets; see Section 15 for the numbering reconciliation):

```
refactor-guards.yml   (KEEP existing 2 jobs; APPEND):
  + import-boundaries  check_import_boundaries.py   [026]  Stage 1 -> 2
  + directory-policy   check_directory_policy.py    [028]  Stage 1 -> 4
  + complexity         check_complexity.py          [025]  Stage 1 -> 4
  + lint               ruff check .  (advisory)      [025]  Stage 1
  + dead-code          ruff --select F401 (advisory) [025]  Stage 1
contracts.yml         (NEW; all PRs to main):
    public-api           check_public_api_contracts.py [029]  Stage 1 -> 3
    viz-api-schema       check_viz_api_schema.py       [030]  Stage 1 -> 3
    mcp-tool-contracts   MCP tool-schema check          [—]   Stage 1 -> 3
    quality-report       generate_quality_report.py    [031]  needs: * (aggregation)
```

`check_docs_source_sync.py` (027) gets **no job** (`DELETE_CANDIDATE`). Any prompt slice is `MERGE`d into Gate 10 (`report/scripts/check_prompt_snapshots.py`) by subtask 051, not re-implemented here.

### 7.2 Job invocation contract (matches the existing docs jobs)

Each appended/new job:
- Runs on `ubuntu-latest`, `actions/checkout@v4`, `actions/setup-python@v5` with `python-version: "3.13"`, `pip install --upgrade pip pyyaml` (mirrors `docs-change-coupling.yml`). `ruff` is already installed on the runner via the checker's own invocation or `pip install ruff` pinned to 0.15.2 if needed.
- Invokes exactly one `scripts/check_*.py --json <path>` (plus a `--strict` off at Stage 1); relies on the checker's exit code for gating.
- Uploads the per-job JSON as an artifact for `quality-report`.

### 7.3 Diff-scope and base-ref rules

- Diff-scoped jobs (`import-boundaries`, `directory-policy` new-debt slice, `public-api` regression slice) use `git diff <base> HEAD -- '<pathspec>'` with `':!<exclude>'` pathspecs, reusing `refactor-guards.yml`'s allow-list convention for grandfathering legacy sites.
- **Base-ref:** `${{ github.event.pull_request.base.sha }}` for every *new* diff-scoped job — quote the `docs-change-coupling.yml` header rationale (lines 42–48) in a comment. Do **not** copy `refactor-guards.yml`'s `origin/${{ github.base_ref }}` into new jobs (it is the idiom *not* to reuse — say "not preferred", not "deprecated"). Fail CLOSED if the ref fails to resolve.
- `fetch-depth: 0` on any diff-scoped job (matches the three existing diff jobs).

### 7.4 Staged warning→failure policy (from 012 §8)

| Stage | Gates promoted | Mode |
| --- | --- | --- |
| **1 — warning-all** | every new job (all of 7.1) | Advisory (`continue-on-error: true`); establishes the baseline |
| **2 — regression-only-hard** | `import-boundaries`, `public-api` (regression slice) | Hard on diff-scoped *new* violations; legacy grandfathered |
| **3 — contract-breakage-hard** | `viz-api-schema`, `public-api` (full), `mcp-tool-contracts` | Hard on any external-contract break |
| **4 — new-debt-hard** | `complexity`, `directory-policy`, `dead-code` | Hard on *new* debt only (ratchet) |

Invariants: a gate never skips Stage 1; promotion is a one-line flip (`continue-on-error: false` or `--strict`), never a checker or workflow rewrite; `quality-report` renders each gate's current stage and delta-vs-base so reviewers see would-block counts before promotion. **This subtask lands everything at Stage 1**; promotions are separate later PRs.

### 7.5 Aggregation protocol (031)

`quality-report` is a `needs:`-gated job depending on every checker job in `contracts.yml` (and, if the runner topology allows a cross-workflow read, referencing the `refactor-guards.yml` artifacts; otherwise it aggregates only `contracts.yml` jobs and notes the refactor-guards gates separately). It downloads the per-job `--json` artifacts, renders one PR-comment summary, and **never fails the build on content** (it is a reporter) — only on its own execution error.

### 7.6 Safe-to-land-before-checkers rule

Because the six checker scripts do not exist yet (Section 6.5), each job must be authored so committing 049's YAML does not turn a green PR red before 025/026/028/029/030/031 merge. Two acceptable mechanisms (implementer picks one, documented in the workflow comment):
- **(a)** `continue-on-error: true` at Stage 1 makes a missing-script failure non-blocking; or
- **(b)** guard each step with `if [ -f scripts/check_<x>.py ]` so the job is a no-op until its checker lands.
Either way, the *default branch must stay green* the moment 049 merges.

### 7.7 Runtime and DRY

- Python 3.13 + PyYAML for all checker jobs (matches the docs jobs). `ruff` for lint/F401. Node 20 + `npm ci --prefix ari-core/ari/viz/frontend` only if the viz-schema checker requires a TS parse (no `pnpm`).
- **Composite-action opportunity (REVIEW_REQUIRED, optional MERGE):** the "checkout + setup-python 3.13 + `pip install pyyaml`" prelude now repeats across ≥5 workflows; a `.github/actions/setup-python-checks` composite would DRY it. Note it, defer it — `.github/actions/` does not exist today and creating it is not in 049's scope.

## 8. Concrete Work Items

1. **Read** the inputs in Section 5 (five workflows, `012` §7.3/§8/§15, `009` §5, `007` row 96, the contract surfaces).
2. **Create** `.github/workflows/contracts.yml`:
   - `on: pull_request: branches: [main]`; per-job `fetch-depth: 0`, Python 3.13, `pip install pyyaml` (+ `ruff` where needed).
   - Jobs `public-api` (029), `viz-api-schema` (030), `mcp-tool-contracts`, each `continue-on-error: true`, each `--json <artifact-path>` + `actions/upload-artifact@v4`.
   - Job `quality-report` with `needs: [public-api, viz-api-schema, mcp-tool-contracts]`, `actions/download-artifact@v4`, runs `scripts/generate_quality_report.py`, posts one PR comment.
   - Apply the Section 7.6 safe-to-land guard.
3. **Edit** `.github/workflows/refactor-guards.yml` by **appending** jobs `import-boundaries` (026), `directory-policy` (028), `complexity` (025), `lint` + `dead-code` (`ruff`) — **without touching** `no-home-ari-writes` or `no-new-home-ari-refs`. Diff-scoped jobs use `base.sha` (Section 7.3) and copy the `':!<path>'` allow-list style.
4. **Add the `base.sha` rationale comment** (adapted from `docs-change-coupling.yml` lines 42–48) to every new diff-scoped job so future readers do not copy the `origin/<base_ref>` idiom.
5. **Self-verify** (Section 12): `python -m compileall .`, `ruff check .`, `pytest -q` all behave as on clean `main`; the workflow YAML parses; `git diff --name-only` shows only `.github/workflows/contracts.yml` (new) and `.github/workflows/refactor-guards.yml` (appended jobs) — plus this `.md` was already committed in the planning step.
6. **Do not** create any `scripts/check_*.py`, any `.github/` template/config file, or edit any manifest.

## 9. Files Expected to Change

When subtask 049 is executed (a later coding session), the change set is:

- **CREATE** `.github/workflows/contracts.yml` — new external-contract regression workflow (jobs `public-api`, `viz-api-schema`, `mcp-tool-contracts`, `quality-report`). Verified absent today.
- **MODIFY (append-only)** `.github/workflows/refactor-guards.yml` — add jobs `import-boundaries`, `directory-policy`, `complexity`, `lint`, `dead-code`; existing two jobs unchanged.

Authoring *this planning document* changes exactly one file:
- **CREATE** `docs/refactoring/subtasks/049_add_contract_check_workflows.md` (this file).

Explicitly **NOT** changed by subtask 049 (owned elsewhere / later phases):
- `.github/workflows/{docs-change-coupling,docs-sync,pages,readme-sync}.yml` — `KEEP`, untouched.
- `scripts/check_public_api_contracts.py`, `scripts/check_viz_api_schema.py`, `scripts/check_import_boundaries.py`, `scripts/check_directory_policy.py`, `scripts/check_complexity.py`, `scripts/generate_quality_report.py` — owned by 025/026/028/029/030/031.
- `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/`, `.github/dependabot.yml`, `CODEOWNERS`, `.github/actions/` — owned by 047/048/052; all absent today.
- `docs/refactoring/012_github_workflow_integration_plan.md`, `docs/refactoring/009_quality_scripts_plan.md`, `docs/refactoring/007_subtask_index.md` — cited, not edited.
- Anything under `ari-core/`, `ari-skill-*/`, `requirements.txt`, `requirements.lock`, `ari-core/pyproject.toml` — untouched.

## 10. Files / APIs That Must Not Be Broken

The whole purpose of the new gates is to *protect* these surfaces; the workflow YAML must never rename, wrap, or alter them:

- **CLI:** the single console script `ari = ari.cli:app`. New jobs never invoke or shadow it in a way that changes behavior.
- **Public Python API:** `ari.public.*` — the 9 verified modules. The `public-api` job *snapshots* this surface; it must never propose renaming/removing a symbol.
- **MCP tool contracts:** the 14 `ari-skill-*/src/server.py` servers consumed via `ari/mcp/client.py`. The `mcp-tool-contracts` job protects tool names / `inputSchema` / the `{"result"|"error"}` envelope; it does not modify them.
- **Dashboard API:** `ari/viz/routes.py` + `api_*.py` ↔ `ari/viz/frontend/src/services/api.ts` + `websocket.py`. The `viz-api-schema` job asserts endpoint parity; it never edits endpoints.
- **Checkpoint/output/config file formats:** `ari/checkpoint.py`; YAML under `ari-core/ari/configs/` and top-level `config/`.
- **`ari-skill-* → ari-core` stable interfaces** and the single sanctioned `ari-core → ari_skill_memory` core→skill import (allow-listed by `import-boundaries`, not banned).
- **The five existing workflows** and the 12+ `scripts/` entry points they invoke — all `KEEP`; the two existing `refactor-guards.yml` jobs must remain byte-for-byte, and no `scripts/docs/*` or `scripts/readme_sync.py` invocation is altered.
- **The `pages.yml` deploy path** — new PR gates must not gate or block the push→deploy flow.

## 11. Compatibility Constraints

- **Additive-only.** No existing workflow job is rewritten, renamed, merged, or deleted. `refactor-guards.yml` is extended by *appending*; `contracts.yml` is new.
- **Staged rollout is mandatory.** Every new job enters at Stage 1 (Advisory). No gate is born Hard, so no existing green PR turns red the moment 049 merges (reinforced by the Section 7.6 safe-to-land rule).
- **Idiom compatibility.** New diff jobs use `base.sha`; they coexist with `refactor-guards.yml`'s legacy `origin/<base_ref>` job without changing it.
- **Determinism (design principle P2).** No new job may call an LLM or the network — consistent with the existing docs gates and `ari-skill-memory`'s "no LLM calls" declaration.
- **No new required dependency.** PyYAML (already used) is the ceiling; `radon`/`vulture`/`pnpm` stay out of CI, so `requirements*.txt` and `ari-core/pyproject.toml` are unaffected. `ruff` is already installed (0.15.2).
- **`DELETE_CANDIDATE` honored.** No CI job for `check_docs_source_sync.py` (027).
- **Prompt slice MERGE deferred.** Any prompt gate reuses Gate 10 and is owned by 051, not 049.
- **PR-time only.** New gates are `pull_request` gates; `pages.yml` remains the sole push/deploy workflow.

## 12. Tests to Run

Subtask 049 changes only CI YAML (no `.py`, no frontend), so these must behave exactly as on a clean `main` — any change signals an accidental non-YAML edit:

- `python -m compileall .` — must pass unchanged (no Python touched).
- `pytest -q` (or the scoped `pytest ari-core/tests/ -q` that `refactor-guards.yml` runs under a redirected `HOME`, ignoring `test_letta_restart_live.py`, `test_letta_start_scripts.py`, `test_ollama_gpu.py`, `test_dashboard_html.py`) — no behavior change expected.
- `ruff check .` — baseline unchanged (this subtask adds no Python).
- **YAML validity:** parse both changed workflows, e.g. `python -c "import yaml,sys; [yaml.safe_load(open(p)) for p in ['.github/workflows/contracts.yml','.github/workflows/refactor-guards.yml']]"`. Optionally `actionlint` if available (not installed by default — do not add it as a required dep).
- `python scripts/readme_sync.py --check` — `.github/workflows/` has no `## Contents`-indexed README, so this should be unaffected; if a directory README index is touched, run `--write` then re-run `--check`.
- **No frontend build/test applies** (this is not a frontend subtask); `npm test` / `npm run build` are **not** required. (If the viz-schema checker later shells to Node, that dependency belongs to subtask 030, not to this workflow subtask.)
- **Diff assertion:** `git diff --name-only` should list only `.github/workflows/contracts.yml` and `.github/workflows/refactor-guards.yml`.

## 13. Acceptance Criteria

- [ ] `.github/workflows/contracts.yml` exists with jobs `public-api` (029), `viz-api-schema` (030), `mcp-tool-contracts`, and a `needs:`-gated `quality-report` (031).
- [ ] `.github/workflows/refactor-guards.yml` gains jobs `import-boundaries` (026), `directory-policy` (028), `complexity` (025), `lint`, `dead-code`, with its two original jobs byte-for-byte unchanged.
- [ ] Every new job is Stage 1 / Advisory (`continue-on-error: true` or `--strict`-off) and cannot turn a green PR red on landing (Section 7.6 guard present).
- [ ] Every new diff-scoped job uses `${{ github.event.pull_request.base.sha }}` + `fetch-depth: 0`, carries the `base.sha` rationale comment, and does **not** copy the `origin/<base_ref>` idiom.
- [ ] The `quality-report` job reads per-job `--json` artifacts and posts one PR summary; it fails only on its own execution error, never on gate content.
- [ ] No `scripts/*.py`, no `.github/` template/config file, no source, and no manifest is modified (`git diff --name-only` shows only the two workflow files).
- [ ] `check_docs_source_sync.py` (027) has no job; the prompt slice is not implemented here.
- [ ] `python -m compileall .`, `pytest -q`, and `ruff check .` behave identically to clean `main`; both workflows parse as valid YAML.
- [ ] Every repo path cited in the workflows resolves on disk (or is guarded by the Section 7.6 file-existence check for the not-yet-created checkers).

## 14. Rollback Plan

- **Undo `contracts.yml`:** `git rm .github/workflows/contracts.yml`.
- **Undo the `refactor-guards.yml` appends:** revert the single commit / delete the appended job blocks, restoring the file to its 105-line, two-job form. Because the edit is append-only, reverting cannot affect `no-home-ari-writes` or `no-new-home-ari-refs`.
- **No runtime surface to restore:** 049 touches no ARI code, config, prompt, or frontend, so rollback has zero effect on the running product; it only removes CI gates.
- **Green-tree safety on rollback:** since every gate landed at Stage 1 advisory, neither adding nor removing 049's YAML can flip an otherwise-green PR — rollback is risk-free from a CI-blocking standpoint.
- **Downstream note:** if rolled back after 025/026/028/029/030/031 land, those checkers simply stop running in CI until re-wired; their code is unaffected.

## 15. Dependencies

**Graph edge (authoritative):** `045 -> 049`. Subtask 049 depends on **045 `inventory_github_workflows`** — the inventory of the five existing workflows and the confirmed-absent `.github/` files, which 049 builds on. 045 is also one of the nine inventory subtasks that must precede any change in its area (`001, 002, 020, 036, 045, 053, 059, 060, 067`).

**Logical (non-edge) prerequisites the implementer must acknowledge** — these are ordering constraints for the *jobs to run green*, not graph edges:
- The wired checker scripts must exist before their jobs run non-trivially: `check_complexity.py` (025), `check_import_boundaries.py` (026), `check_directory_policy.py` (028), `check_public_api_contracts.py` (029), `check_viz_api_schema.py` (030), `generate_quality_report.py` (031). 049's YAML may land *before* them thanks to the Section 7.6 Stage-1/file-guard rule, but a job pointed at a missing script only becomes meaningful once its checker merges.
- The CI-integration design (subtasks **032 / 046**, both paired as the same "quality-CI integration" work in `007` Phase 9) is the design input 049 implements. If that plan lands in `docs/refactoring/reports/`, treat it as the authoritative wiring spec; otherwise implement 012 §15 directly.
- Sibling Phase-9 workflow subtasks **050** (`add_docs_sync_workflow`) and **051** (`add_prompt_change_review_workflow`) own the docs and prompt jobs respectively; 049 must not implement those.

**Numbering reconciliation (must be respected):** the canonical source is `007_subtask_index.md` — the checker *scripts* are subtasks **025–031** (Phase 8) and the GitHub-integration *items* are **032/045–052** (Phase 9), making **049 = `add_contract_check_workflows`** (row 96, `Runtime code change: No`, `Can run independently: No`, depends 045). The master plan `012` §16 uses an older mapping that assigns the checker scripts to **045–052** (there, `049` would be `check_viz_api_schema.py`); treat `007` + the provided dependency graph as authoritative and follow the canonical mapping. Do **not** edit `012` in this subtask.

## 16. Risk Level

**Low.**

- **Changes runtime ARI code: No.** 049 writes no `.py`, no frontend, no prompt, no config, and renames no directory. `007_subtask_index.md` row 96 records 049 as `Runtime Code Change? No`.
- **Changes CI configuration: Yes (by design).** It creates `.github/workflows/contracts.yml` and appends jobs to `refactor-guards.yml`. This is contract-*adjacent* — the "scripts invoked by `.github/workflows/`" is itself a protected surface — but the edits are additive and the two existing `refactor-guards.yml` jobs are untouched.
- **Blast radius:** two workflow files; append-only for the modified one; a new file for the other. Rollback is a one-file `git rm` plus a job-block revert (Section 14).
- **Residual risk is bounded by staging:** every gate lands at Stage 1 advisory with the Section 7.6 safe-to-land guard, so a mistake in the YAML (or a not-yet-created checker) cannot block PRs. The worst realistic outcome is a noisy-but-non-blocking advisory job, corrected in a follow-up — mitigated by the Section 12 diff/parse assertions and by grounding every path/idiom in the live workflows.

## 17. Notes for Implementer

- **You are wiring, not writing checkers.** If you find yourself creating `scripts/check_*.py` or `scripts/generate_quality_report.py`, stop — those belong to 025/026/028/029/030/031. Your outputs are `.github/workflows/contracts.yml` (new) and appended jobs in `refactor-guards.yml`.
- **Append, never rewrite.** Add jobs to `refactor-guards.yml`; leave `no-home-ari-writes` and `no-new-home-ari-refs` byte-for-byte. Do not touch the other four workflows.
- **Prefer `base.sha`.** Copy the rationale comment from `docs-change-coupling.yml` (lines 42–48) into every new diff job so the next implementer understands *why* not to reuse `refactor-guards.yml` line 82's `origin/<base_ref>`. Call the old idiom "not preferred", never "deprecated" (deprecation is reserved for external contracts).
- **Land everything at Stage 1.** Set `continue-on-error: true` (or `--strict`-off) on all new jobs, and add the Section 7.6 file-existence guard so committing 049 before the checkers exist keeps `main` green. Promotion to Hard is a later, one-line PR — not part of this subtask.
- **Honor the `DELETE_CANDIDATE`.** No job for `check_docs_source_sync.py` (027) — it is redundant with `check_doc_sources.py` (forward) + `check_ref_coupling.py` (reverse).
- **Prompt/docs jobs are not yours.** The docs-sync additions belong to 050; the prompt-change review job (MERGE into Gate 10, `report/scripts/check_prompt_snapshots.py`) belongs to 051.
- **No new dependency.** PyYAML and the already-installed `ruff` (0.15.2) are the ceiling; do not add `radon`, `vulture`, or `pnpm`, and do not touch `requirements*.txt` / `ari-core/pyproject.toml`.
- **Determinism (P2).** No job may call an LLM or the network — same rule as the docs gates and `ari-skill-memory`.
- **`sonfigs` does not exist.** If the `directory-policy` job is discussed, cite the real confusable trio — `ari-core/ari/config/` (locator code), `ari-core/ari/configs/` (packaged defaults), and top-level `config/` (rubric/profile data) — and state no `sonfigs/` directory exists.
- **Follow `007` numbering.** 049 is the *workflow* subtask; the checkers it wires are 025/026/028/029/030/031. Do not be misled by `012` §16's older 045-for-checkers mapping (Section 15).

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **049** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
