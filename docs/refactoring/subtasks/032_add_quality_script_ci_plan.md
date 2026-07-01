# Subtask 032: Add Quality-Script CI Integration Plan

- **Subtask ID:** 032
- **Phase:** Phase 9 — GitHub Integration
- **Classification:** `KEEP` (additive planning/design deliverable; no target code, workflow, or config file is modified — the CI wiring it specifies is implemented later by other subtasks)
- **Changes runtime code:** **No** (see Section 16 — this subtask produces a Markdown plan only)
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`)

> **Planning-phase notice.** This document is a plan for a *future* coding session. It changes no runtime code, imports, prompts, configs, workflows, frontend, or directory names. The only file created by authoring *this* plan is this `.md` itself. The subtask it describes (032) is itself a **design/planning** subtask: when executed, subtask 032 produces one *additional* Markdown design document (the "Quality-script CI integration plan"), and still writes **no** `.github/` YAML, no `scripts/*.py`, and no source. The actual workflow edits are owned by later subtasks (049/050/051, per Section 15).

---

## 1. Goal

Produce the **authoritative, subtask-actionable CI-integration plan** that specifies exactly how the Phase-8 quality-checker scripts get wired into GitHub Actions — precisely enough that the workflow-implementation subtasks can execute it without further design work, and **without rewriting any of the five existing workflows**.

The Phase-8 checkers this plan wires (all verified **ABSENT** today — every one is net-new):

| Owning subtask | Script (planned path) | Wiring verdict this plan must record |
| --- | --- | --- |
| **025** `add_complexity_checker_script` | `scripts/check_complexity.py` | New job; stdlib LOC/AST only (no `radon`) |
| **026** `add_import_boundary_checker_script` | `scripts/check_import_boundaries.py` | New job; `ari.public.*` boundary + `core↔skill` direction |
| **027** `add_docs_source_sync_checker_script` | `scripts/check_docs_source_sync.py` | **`DELETE_CANDIDATE`** — redundant with `check_doc_sources.py` (forward) + `check_ref_coupling.py` (reverse); do not add a CI job unless a new invariant is proven |
| **028** `add_directory_policy_checker_script` | `scripts/check_directory_policy.py` | New job for the placement/naming slice only; reuse `readme_sync.py` for the listing slice |
| **029** `add_public_api_contract_checker_script` | `scripts/check_public_api_contracts.py` | New job over `ari.public.*` |
| **030** `add_viz_api_schema_checker_script` | `scripts/check_viz_api_schema.py` | New job coupling `viz/routes.py`+`api_*.py` ↔ `services/api.ts` |
| **031** `add_quality_report_generator` | `scripts/generate_quality_report.py` | Aggregation step; reads each checker's `--json`, posts one PR comment |

The single deliverable of subtask 032 is a Markdown plan document under `docs/refactoring/reports/` (that directory exists and is currently empty — verified 2026-07-01). It is the input spec consumed by the workflow-implementation and template subtasks 047–052 (Section 15).

**Explicit non-actions of this subtask** (owned elsewhere — do not do them here):
- Do **not** create or edit any `.github/workflows/*.yml` (owned by 049/050/051).
- Do **not** create any `scripts/check_*.py` or `scripts/generate_quality_report.py` (owned by 025–031).
- Do **not** create `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/`, `.github/dependabot.yml`, or `CODEOWNERS` (owned by 047/048/052 — all four are absent today).
- Do **not** install `radon`, `vulture`, or `pnpm`, and do **not** edit `requirements.txt`/`requirements.lock`/`ari-core/pyproject.toml`.

---

## 2. Background

CI in this repo is **almost entirely documentation/i18n-oriented**. There are exactly five workflows under `.github/workflows/` (line counts verified): `docs-change-coupling.yml` (58), `docs-sync.yml` (91), `pages.yml` (64), `readme-sync.yml` (28), `refactor-guards.yml` (105). Of the six CI jobs across them, five gate docs/report/README parity; only `refactor-guards.yml` touches Python source, and only for the `~/.ari/` invariant plus a pytest-under-sandbox run. **No workflow runs `ruff`, `compileall`, an import-boundary check, a complexity check, or a public-API/viz-schema check** — so none of the Phase-8 checkers are represented in CI, and there is no overlap to untangle beyond *pattern reuse*.

`.github/` contains **only** `workflows/` (verified via `ls .github/` → single entry). Confirmed absent (each checked directly): `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/dependabot.yml`, `CODEOWNERS`, and `.github/actions/` (no local composite actions).

The master GitHub-integration design already exists at `docs/refactoring/012_github_workflow_integration_plan.md` (§7 integration policy, §8 staged warning→failure policy, §15 proposed workflow structure). Subtask 032 is the **subtask-level realization** of that master plan: it turns 012's prose into a concrete, per-job wiring spec that a fresh implementer can follow. This plan must therefore *inherit and cite* 012 rather than re-derive it, and it must reconcile a known numbering discrepancy (Section 15) between 012's §16 table and the canonical subtask index `007_subtask_index.md`.

Two proven idioms already live in the repo and must be reused verbatim rather than reinvented:
- **Merge-base diff guard.** `refactor-guards.yml` (line 82) computes `base="$(git merge-base origin/${{ github.base_ref || 'main' }} HEAD)"` then `git diff` over a pathspec — the template for diff-scoped checks.
- **Path-exclude allow-list.** The same workflow's `no-new-home-ari-refs` job grandfathers 14 sanctioned legacy sites (`_deprecation.py`, `migrations/`, `core.py`, `paths.py`, `memory_cli.py`, `memory/auto_migrate.py`, `memory/file_client.py`, `publish/backends/ari_registry.py`, `clone/resolvers/ari.py`, `registry/__init__.py`, `viz/state.py`, `viz/api_settings.py`, `viz/api_publish.py`, plus `memory/file_client.py`), so the check can be strict everywhere else.

Crucially, `docs-change-coupling.yml` (header lines ~40–47) explicitly documents why `${{ github.event.pull_request.base.sha }}` is **preferred** over `refactor-guards.yml`'s `origin/${{ github.base_ref }}` idiom: `base.sha` is immutable for the run and always reachable, whereas a remote-tracking ref can move mid-run. This plan must mandate `base.sha` for all *new* diff-scoped jobs.

---

## 3. Scope

In scope for subtask 032 (the plan it must produce):

1. **Per-checker CI placement decision.** For each Phase-8 checker (025–031, table in Section 1), decide: (a) does it get its own CI job or MERGE into an existing gate; (b) which workflow hosts it — `refactor-guards.yml` (ADAPT: append a job) vs a **new** `contracts.yml` (external-contract gates); (c) trigger and diff scope; (d) staged-rollout entry stage.
2. **Staged warning→failure policy** for every new job, aligned with 012 §8 (Stage 1 warning-all → Stage 2 regression-only-hard → Stage 3 contract-breakage-hard → Stage 4 new-debt-hard), with the promotion mechanism being a one-line flip (`continue-on-error: false` or `--strict`), never a checker rewrite.
3. **Shared-convention contract** every new checker/job must satisfy so `generate_quality_report.py` can aggregate them: `argparse` + `--json`, `#!/usr/bin/env python3`, `REPO_ROOT = Path(__file__).resolve().parents[1]` (top-level `scripts/`), PyYAML as the only sanctioned non-stdlib dep, deterministic/no-LLM/no-network (design principle P2), exit `1` on error, a `--strict`/level flag for staged rollout.
4. **Base-ref and fetch-depth rules** — `base.sha` + `fetch-depth: 0` for diff-scoped jobs; explicit call-out that `origin/<base_ref>` is deprecated *idiom-wise* for new jobs.
5. **Aggregation wiring** — how `generate_quality_report.py` (031) runs as a `needs:`-gated job consuming per-checker JSON artifacts and renders one PR summary.
6. **DELETE_CANDIDATE and MERGE call-outs** — record that `check_docs_source_sync.py` (027) should get **no** CI job (redundant), and that any prompt-snapshot slice MERGEs into the existing `report/scripts/check_prompt_snapshots.py` (Gate 10) rather than being re-implemented.
7. **Consolidation note** — reconcile 032 with the near-duplicate 046 `design_quality_ci_integration` and with the numbering drift between `012` §16 and `007` (Section 15).

Out of scope: everything in Section 4.

---

## 4. Non-Goals

- **No workflow edits.** No `.github/workflows/*.yml` is created, rewritten, or merged. The five existing workflows are `KEEP`.
- **No checker implementation.** No `scripts/check_*.py` and no `scripts/generate_quality_report.py` is written (025–031 own these). This plan references their *contract*, not their code.
- **No `.github/` template files.** `PULL_REQUEST_TEMPLATE.md`, `ISSUE_TEMPLATE/`, `dependabot.yml`, `CODEOWNERS`, and `.github/actions/` are all absent and stay absent until their owning subtasks (047/048/052).
- **No dependency installation or manifest edit.** `radon`/`vulture`/`pnpm` are not added; `requirements*.txt`/`.lock` and `ari-core/pyproject.toml` are untouched.
- **No promotion of any gate to Hard.** This plan only *schedules* the staged rollout; it does not flip any `continue-on-error`.
- **No runtime code, prompt, config, checkpoint, or frontend change** of any kind.
- **No re-derivation of the master plan.** 012 is cited, not duplicated; where 012 and this subtask disagree on numbering, this plan records the reconciliation (Section 15) rather than editing 012.

---

## 5. Current Files / Directories to Inspect

Real repo paths the implementer must read before writing the plan:

**Existing workflows (all `KEEP` — read to reuse idioms, do not edit):**
- `.github/workflows/refactor-guards.yml` (105 lines) — the ADAPT host; two jobs `no-home-ari-writes` (pytest under redirected `HOME`, ignoring `test_letta_restart_live`, `test_letta_start_scripts`, `test_ollama_gpu`, `test_dashboard_html`) and `no-new-home-ari-refs` (line 82 merge-base idiom + 14-path allow-list). Only workflow triggered on the `refactoring` branch.
- `.github/workflows/docs-change-coupling.yml` (58 lines) — header lines ~40–47 document the `base.sha` preference; hard gate `check_report_cochange.py`, advisory `check_ref_coupling.py`.
- `.github/workflows/docs-sync.yml` (91 lines) — two jobs (`docs-sync` hard/advisory gates; `vitepress-build`). Template for a multi-gate job list and `continue-on-error` advisories.
- `.github/workflows/readme-sync.yml` (28 lines) — single stdlib step `python scripts/readme_sync.py --check`; the minimal single-gate pattern.
- `.github/workflows/pages.yml` (64 lines) — only push-triggered/deploy workflow; read only to confirm the new gates must **not** interfere with it.

**Existing checker conventions (read for the shared-convention contract):**
- `scripts/docs/` — `check_doc_sources.py` (7665 B), `check_doc_links.py`, `check_i18n_js.py`, `check_readme_parity.py`, `check_ref_coupling.py` (`--base-ref`, `--strict`), `check_report_cochange.py`, `check_site_i18n.py`, `check_translation_freshness.py`. All: `#!/usr/bin/env python3`, docstring citing a design doc, `argparse` + `--json`, `REPO_ROOT = Path(__file__).resolve().parents[2]`, exit 1, PyYAML-only, staged warning→error.
- `scripts/readme_sync.py` (14330 B) — the `--check`/`--write` snapshot pattern the public-API and contract checkers should mirror.
- `scripts/git-hooks/pre-commit` (2033 B) — the non-blocking local hook (`readme_sync.py --write`); a candidate host for a fast subset of the new checks (advisory, `exit 0`).
- `scripts/run_all_tests.sh` (2572 B) — per-skill pytest, 13 hardcoded paths; **not referenced by any workflow** — note as an ADAPT candidate but not this subtask's job.
- `report/scripts/check_prompt_snapshots.py` — **Gate 10**, byte-verifies `ari-core/ari/prompts/**/*.md`; the MERGE target for any prompt-snapshot slice.

**Contract surfaces the gates protect (read to scope the checkers, do not modify):**
- `ari-core/ari/public/` — 9 modules verified: `claim_gate.py`, `config_schema.py`, `container.py`, `cost_tracker.py`, `__init__.py`, `llm.py`, `paths.py`, `run_env.py`, `verified_context.py` (+ `README.md`). The `check_public_api_contracts.py` (029) snapshot target.
- `ari-core/ari/viz/routes.py` (1197) + `api_*.py` (`api_experiment.py` 929, `api_paperbench.py` 813, …) and `ari-core/ari/viz/frontend/src/services/api.ts` (863) — the `check_viz_api_schema.py` (030) coupling target.

**Design inputs (read, cite, reconcile — do not edit):**
- `docs/refactoring/012_github_workflow_integration_plan.md` (§6 missing gates, §7 integration policy, §8 staged policy, §15 workflow structure, §16 subtask map).
- `docs/refactoring/007_subtask_index.md` (canonical subtask numbering; Phase 8 rows 025–031, Phase 9 rows 032/045–052).
- `docs/refactoring/reports/` — **empty**; the output directory for this subtask's deliverable.

---

## 6. Current Problems

1. **No source-quality CI at all.** `grep` over the five workflows confirms no `ruff`, `compileall`, complexity, import-boundary, public-API, or viz-schema gate runs anywhere. The Phase-8 checkers, once written (025–031), would have nowhere to run without this plan.
2. **All seven Phase-8 checkers are absent.** Verified: `check_complexity.py`, `check_import_boundaries.py`, `check_directory_policy.py`, `check_public_api_contracts.py`, `check_viz_api_schema.py`, `generate_quality_report.py`, and `check_docs_source_sync.py` do not exist on disk. There is nothing to wire yet — hence the plan must be ready *before or alongside* their creation.
3. **Idiom drift risk.** The one workflow that does diff-scoping (`refactor-guards.yml` line 82) uses the inferior `origin/${{ github.base_ref }}` idiom that `docs-change-coupling.yml` (lines ~40–47) explicitly critiques. Without a written rule, new jobs will copy the wrong idiom.
4. **Redundancy trap.** `check_docs_source_sync.py` (027) duplicates existing forward (`check_doc_sources.py`) + reverse (`check_ref_coupling.py`) coverage. Without an explicit `DELETE_CANDIDATE` verdict, an implementer may add a redundant CI job.
5. **No aggregation contract.** Every existing docs checker emits `--json`, but nothing aggregates them; `generate_quality_report.py` (031) has no defined `needs:`/artifact protocol until this plan fixes one.
6. **Numbering ambiguity.** `012` §16 maps subtask IDs **045–052** to the checkers, while `007_subtask_index.md` maps the checkers to **025–031** and reserves **045–052** for GitHub-integration items (inventory/templates/workflows). A fresh implementer reading only 012 would wire the wrong subtask ownership. This plan must state the canonical mapping (Section 15).
7. **032/046 overlap.** `007` §"Phase 9" literally pairs "**046** `design_quality_ci_integration` / **032** `add_quality_script_ci_plan`" as the same work. Two competing plans are a maintenance hazard; the deliverable must declare one authoritative document.
8. **No push-time source CI.** The only push-triggered workflow is `pages.yml` (docs deploy). All source gating is PR-time only — the plan must respect that (new gates are PR gates, not push gates) so nothing blocks the Pages deploy path.

---

## 7. Proposed Design / Policy

The plan document subtask 032 produces must encode the following, all consistent with `012` §7/§8/§15.

### 7.1 Additive layout (no existing workflow rewritten)

Two mechanisms only, both additive:
- **ADAPT `refactor-guards.yml`** by *appending* jobs for the refactor-invariant gates (complexity, import-boundary, directory-policy, dead-code, `ruff` lint). Its two existing jobs are untouched. Rationale: it is the only workflow triggered on the `refactoring` branch, so refactoring branches get these gates before reaching `main`.
- **Add one NEW `contracts.yml`** (triggered on all PRs to `main`) for external-contract regression gates: public-API, viz-API-schema, MCP tool-contract, prompt-inventory, dashboard-UX, plus the `quality-report` aggregation job. Grouping keeps the required-status-check list readable.

Proposed job map (subtask IDs use the **canonical `007` numbering**, Section 15):

```
refactor-guards.yml  (KEEP existing 2 jobs; APPEND):
  + complexity        check_complexity.py            [025]   Stage 1 -> 4
  + import-boundaries check_import_boundaries.py     [026]   Stage 1 -> 2
  + directory-policy  check_directory_policy.py      [028]   Stage 1 -> 4
  + lint              ruff check . (advisory)        [025]   Stage 1
  (dead-code: ruff --select F401 slice, advisory)            Stage 1
contracts.yml  (NEW; all PRs to main):
    public-api          check_public_api_contracts.py [029]  Stage 1 -> 3
    viz-api-schema      check_viz_api_schema.py       [030]  Stage 1 -> 3
    mcp-tool-contracts  MCP schema check              [—]    Stage 1 -> 3
    quality-report      generate_quality_report.py    [031]  needs: * (aggregation)
```
`check_docs_source_sync.py` (027) gets **no job** (`DELETE_CANDIDATE`). Any prompt-snapshot slice MERGEs into `report/scripts/check_prompt_snapshots.py` (Gate 10) — it is not re-implemented.

### 7.2 Shared-convention contract (every new checker MUST satisfy)

- `#!/usr/bin/env python3`; module docstring citing its owning subtask + this plan.
- `argparse` with `--json`; a `--strict`/level flag driving staged rollout.
- `REPO_ROOT = Path(__file__).resolve().parents[1]` (checkers live at `scripts/` top level, not `scripts/docs/`).
- Pure stdlib where possible; **PyYAML** the only sanctioned non-stdlib dep (already installed in the docs jobs). **No `radon`, no `vulture`, no `pnpm`.**
- Deterministic, **no LLM / no network** (design principle P2 — same constraint `ari-skill-memory` and the docs gates hold).
- Exit `1` on error so CI can gate on exit code.

### 7.3 Diff-scope and base-ref rules

- Diff-scoped jobs use `git diff <base> HEAD -- '<pathspec>'` with `':!<exclude>'` pathspecs (reuse `refactor-guards.yml`'s pattern) and the **14-entry path-exclude allow-list** convention for grandfathering legacy sites.
- **Base-ref:** `${{ github.event.pull_request.base.sha }}` for every *new* diff-scoped job (as `docs-change-coupling.yml`/`docs-sync.yml` do). Do **not** copy `refactor-guards.yml`'s `origin/${{ github.base_ref }}` into new jobs. Fail CLOSED if the ref fails to resolve.
- `fetch-depth: 0` on any diff-scoped job (matches the three existing diff jobs).

### 7.4 Staged warning→failure policy (from 012 §8)

| Stage | Gates | Mode |
| --- | --- | --- |
| **1 — warning-all** | every new gate | Advisory (`continue-on-error: true`); establishes the baseline |
| **2 — regression-only-hard** | `check_import_boundaries.py`, `check_public_api_contracts.py` | Hard on diff-scoped *new* violations; legacy grandfathered |
| **3 — contract-breakage-hard** | `check_viz_api_schema.py`, `check_public_api_contracts.py` (full), MCP tool-contract | Hard on any external-contract break |
| **4 — new-debt-hard** | `check_complexity.py`, `check_directory_policy.py`, dead-code | Hard on *new* debt only (ratchet) |

Invariants: a gate never skips a stage (must spend real calendar time at Stage 1); promotion is a one-line flip, never a checker rewrite; `generate_quality_report.py` renders each gate's current stage and delta-vs-base so reviewers see would-block counts before promotion.

### 7.5 Aggregation protocol (031)

Each checker job runs with `--json`, writing to a per-job path, and uploads it as an artifact. `quality-report` is a `needs:`-gated job (depends on all checker jobs), downloads the artifacts, and renders one PR-comment summary. It never fails the build on content (it is a reporter), only on its own execution error.

### 7.6 Runtime and DRY

- Python 3.13 + PyYAML for the checker jobs (matches the docs jobs); `ruff` for lint/F401; `node 20` + `npm ci --prefix ari-core/ari/viz/frontend` for any frontend gate (no `pnpm`).
- **Composite-action opportunity (REVIEW_REQUIRED, optional MERGE):** the "checkout + setup-python 3.13 + `pip install pyyaml`" prelude repeats across ≥4 workflows; a `.github/actions/setup-python-checks` composite would DRY it. Note it, defer it — `.github/actions/` does not exist today.

---

## 8. Concrete Work Items

The implementer of subtask 032 performs these steps (all produce Markdown; none touch code/YAML):

1. **Read** the inputs in Section 5 (five workflows, `012`, `007`, `scripts/docs/` conventions, `ari/public/`).
2. **Author** the plan document `docs/refactoring/reports/032_quality_script_ci_integration.md` containing:
   - The per-checker placement table (Section 7.1) with canonical `007` subtask IDs and the `DELETE_CANDIDATE`/MERGE verdicts.
   - The shared-convention contract (7.2), diff/base-ref rules (7.3), staged policy table (7.4), aggregation protocol (7.5), runtime/DRY notes (7.6).
   - A **worked YAML sketch** (in a fenced block, non-executable illustration only) of one appended `refactor-guards.yml` job and the new `contracts.yml` skeleton, using `base.sha` + `fetch-depth: 0`, so 049/050/051 can copy it.
   - An explicit **numbering-reconciliation note** (Section 15): checkers = 025–031 (canonical `007`); GitHub items = 032/045–052; flag that `012` §16 uses the older 045–052-for-checkers mapping.
   - A **consolidation recommendation**: declare this document the single authoritative CI-integration plan and record that 046 `design_quality_ci_integration` should reference (MERGE into) it rather than fork a competing plan.
3. **Cross-link** the new plan from `docs/refactoring/012_github_workflow_integration_plan.md`'s §16 only if a later docs subtask edits 012 — this subtask does **not** edit 012; it records the intended back-link as a follow-up note.
4. **Self-verify** the plan changed only Markdown (Section 12) and that every path it cites resolves on disk.
5. **Do not** create YAML, checkers, or `.github/` templates.

---

## 9. Files Expected to Change

Because subtask 032 is a design/planning deliverable, the change set is a **single new Markdown file**:

- **CREATE** `docs/refactoring/reports/032_quality_script_ci_integration.md` — the CI-integration plan (the subtask's deliverable). The `docs/refactoring/reports/` directory exists and is empty today (verified).

Explicitly **NOT** changed by subtask 032 (owned by other subtasks / later phases):
- `.github/workflows/refactor-guards.yml`, `.github/workflows/contracts.yml` (new) — owned by 049 (contract workflows) / the refactor-guards ADAPT owner.
- `.github/workflows/{docs-change-coupling,docs-sync,pages,readme-sync}.yml` — `KEEP`, untouched.
- `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/`, `.github/dependabot.yml`, `CODEOWNERS`, `.github/actions/` — owned by 047/048/052; all absent today.
- `scripts/check_complexity.py`, `scripts/check_import_boundaries.py`, `scripts/check_directory_policy.py`, `scripts/check_public_api_contracts.py`, `scripts/check_viz_api_schema.py`, `scripts/generate_quality_report.py` — owned by 025–031.
- `docs/refactoring/012_github_workflow_integration_plan.md` — cited, not edited.
- Any file under `ari-core/`, `ari-skill-*/`, `requirements*.txt`, `requirements.lock`, `ari-core/pyproject.toml` — untouched.

---

## 10. Files / APIs That Must Not Be Broken

This subtask writes only Markdown, so nothing is broken at execution time. The *plan it emits* must, however, preserve every contract surface (the plan's whole purpose is to protect them, never to change them):

- **CLI:** the single console script `ari = ari.cli:app`. New gates must not alter or wrap it.
- **Public Python API:** `ari.public.*` — the 9 verified modules (`claim_gate`, `config_schema`, `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`, `__init__`). The `check_public_api_contracts.py` gate *snapshots* this surface; it must never propose renaming/removing a symbol.
- **MCP tool contracts:** the 14 `ari-skill-*/src/server.py` servers consumed via `ari/mcp/client.py`. The MCP tool-contract gate protects schemas; it does not modify them.
- **Dashboard API:** `ari/viz/routes.py` + `api_*.py` ↔ `ari/viz/frontend/src/services/api.ts` + `websocket.py`. The viz-schema gate asserts endpoint parity; it never edits endpoints.
- **Checkpoint/output/config file formats:** `ari/checkpoint.py`; YAML under `ari-core/ari/configs/` and top-level `config/`.
- **`ari-skill-* → ari-core` stable interfaces** and the single `ari-core → ari_skill_memory` core→skill import.
- **The five existing workflows** and the 12 `scripts/` entry points they invoke — all `KEEP`, must not be renamed or removed; new jobs are additive.
- **README/docs usage** and the `scripts/` referenced by `.github/workflows/*` (e.g. `readme_sync.py`, `scripts/docs/*`).

---

## 11. Compatibility Constraints

- **Additive-only.** The plan must not schedule any rewrite/merge/deletion of an existing workflow or `scripts/` checker. `refactor-guards.yml` is extended by *appending* jobs; `contracts.yml` is *new*.
- **Staged rollout is mandatory.** Every new gate enters at Stage 1 (Advisory) — no gate is born Hard. This guarantees no existing green PR turns red on day one.
- **Idiom compatibility.** New diff jobs use `base.sha`; they may coexist with `refactor-guards.yml`'s legacy `origin/<base_ref>` job without changing it.
- **Determinism (P2).** No new gate may call an LLM or the network — consistent with the existing docs gates and `ari-skill-memory`.
- **No new required dependency.** PyYAML is the ceiling; `radon`/`vulture`/`pnpm` stay out of CI, so `requirements*.txt` and `ari-core/pyproject.toml` are unaffected.
- **`DELETE_CANDIDATE` honored.** No CI job for `check_docs_source_sync.py` (027) unless a genuinely new invariant is proven, since forward+reverse doc-source coupling already exists.
- **Prompt snapshot MERGE.** The prompt-snapshot slice reuses Gate 10 (`report/scripts/check_prompt_snapshots.py`); it is not duplicated.

---

## 12. Tests to Run

Subtask 032 changes only Markdown, so the following are **smoke checks that must remain unaffected** (each should behave exactly as on a clean `main`; any change signals an accidental non-doc edit):

- `python -m compileall .` — must pass; confirms no `.py` was touched.
- `pytest -q` (or the scoped `pytest ari-core/tests/ -q` that `refactor-guards.yml` runs under a redirected `HOME`) — no behavior change expected.
- `ruff check .` — baseline unchanged (this subtask adds no Python).
- `python scripts/readme_sync.py --check` — if the new `.md` lands in a directory whose `README.md` carries a `## Contents` index (`docs/refactoring/reports/` has none today), run `--write` to regenerate that index and re-run `--check`.
- Markdown-only diff assertion: `git diff --name-only` should list **only** `docs/refactoring/reports/032_quality_script_ci_integration.md`.
- No frontend build/test applies (this is not a frontend subtask); `npm test`/`npm run build` are **not** required.

---

## 13. Acceptance Criteria

- [ ] `docs/refactoring/reports/032_quality_script_ci_integration.md` exists and is the single authoritative CI-integration plan for the Phase-8 checkers.
- [ ] The plan enumerates all seven checkers (025–031) with a per-checker CI verdict: own-job vs MERGE vs `DELETE_CANDIDATE`, host workflow, trigger, diff-scope, and staged-rollout entry stage.
- [ ] The plan mandates `${{ github.event.pull_request.base.sha }}` + `fetch-depth: 0` for new diff jobs and explicitly flags `origin/<base_ref>` as the idiom **not** to copy.
- [ ] The plan records the additive layout (ADAPT `refactor-guards.yml` by appending; NEW `contracts.yml`) and states the five existing workflows are `KEEP`/untouched.
- [ ] The plan encodes the Stage 1→4 warning→failure policy with the one-line-promotion invariant.
- [ ] The plan defines the `generate_quality_report.py` aggregation protocol (per-job `--json` artifacts → one `needs:`-gated PR-comment job).
- [ ] The plan states the canonical subtask numbering (checkers = 025–031; GitHub items = 032/045–052) and flags the `012` §16 mismatch.
- [ ] The plan records the 032↔046 consolidation recommendation.
- [ ] No `.github/` file, no `scripts/*.py`, no source, and no manifest is modified (`git diff --name-only` shows only the one `.md`).
- [ ] `python -m compileall .`, `pytest -q`, and `ruff check .` behave identically to clean `main`.
- [ ] Every repo path cited in the plan resolves on disk.

---

## 14. Rollback Plan

Trivial: the subtask adds exactly one Markdown file and touches nothing else.

- **Undo:** `git rm docs/refactoring/reports/032_quality_script_ci_integration.md` (or revert the single commit). No workflow, script, config, or source change accompanies it, so there is nothing else to unwind and no runtime surface to restore.
- **No CI impact from rollback:** because 032 wires nothing into `.github/`, removing the plan cannot break any pipeline; it only removes the design input that later subtasks consume.
- **Downstream note:** if the plan is rolled back after 049/050/051 have begun implementing against it, those subtasks lose their spec but their (already-committed) YAML is unaffected — coordinate re-authoring before re-attempting the wiring.

---

## 15. Dependencies

**Per the provided dependency graph, subtask 032 has NO explicit predecessor or successor edge** — it is a graph root with no children. The graph's relevant edges are:
- `001 -> 025, 031` (complexity checker and quality-report generator depend on the baseline census).
- `020 -> 030` (viz-API-schema checker depends on the viz/dashboard contract inventory).
- `045 -> 046, 047, 048, 049, 050, 051, 052` (all GitHub-integration *implementation* items fan out from the workflow inventory 045).

Because 032 is a **plan** (not an implementation) and carries no edge, it **can be authored independently** and **need not wait** for the checkers to exist. It is also **not a runtime change**, so it is not gated by the nine inventory subtasks (`001, 002, 020, 036, 045, 053, 059, 060, 067`).

Logical (non-edge) relationships the plan should acknowledge:
- The plan *describes wiring for* checkers 025–031; those checkers must exist before their CI **jobs can actually run** (a Stage-1 job pointing at a non-existent script would fail). 032 only writes the spec, so this is an ordering constraint on 049/050/051, not on 032.
- The workflow-**implementation** subtasks 046–052 all depend on `045` (inventory) per the graph and should consume this plan as their design input.
- `check_complexity.py` (025) and `generate_quality_report.py` (031) additionally depend on `001` (baseline); `check_viz_api_schema.py` (030) depends on `020` (viz inventory) — the plan's staged rollout for those gates must not assume they are ready before their own predecessors.

**Numbering reconciliation (must be stated in the deliverable):** the canonical source is `007_subtask_index.md` — checkers are **025–031**, GitHub-integration items are **032/045–052**. The master plan `012_github_workflow_integration_plan.md` §16 uses an older mapping that assigns the checkers to **045–052**; treat `007` + the dependency graph above as authoritative and flag the `012` §16 drift as a known discrepancy (do not edit 012 in this subtask).

**Consolidation:** 032 `add_quality_script_ci_plan` and 046 `design_quality_ci_integration` are paired as the same work in `007` (Phase 9). Recommend 032's deliverable be the single authoritative plan and 046 reference (MERGE into) it.

---

## 16. Risk Level

**Low.** Rationale:
- **Changes runtime code: No.** The subtask produces one Markdown design document. It writes no `.py`, no YAML, no config, no prompt, no frontend, and no directory rename. `007_subtask_index.md` row 79 records 032 as `Runtime Code Change? No`, `Can Run Independently? Yes`, `Risk Low`.
- **Blast radius:** a single new file under `docs/refactoring/reports/`; rollback is a one-file `git rm` (Section 14).
- **Residual risk is purely advisory:** the plan could specify wiring inconsistent with the eventual checkers or misstate subtask numbering — mitigated by grounding every claim in `007`/`012` and by the Section 12 diff assertion. Because 032 wires nothing into CI itself, a mistake in the plan cannot break any pipeline; it can only mislead a later implementer, who will re-verify against the live workflows.

---

## 17. Notes for Implementer

- **You are writing a plan, not a pipeline.** If you find yourself editing `.github/workflows/` or creating `scripts/check_*.py`, stop — that work belongs to 049/050/051 and 025–031. Your only output is `docs/refactoring/reports/032_quality_script_ci_integration.md`.
- **Reuse, do not reinvent.** Lift the merge-base + path-exclude idioms from `refactor-guards.yml` and the `--json`/`REPO_ROOT`/PyYAML convention from `scripts/docs/`. Your YAML sketch is *illustrative* (a fenced block), never a committed workflow.
- **Prefer `base.sha`.** Quote the `docs-change-coupling.yml` header (lines ~40–47) rationale so the next implementer understands *why* not to copy `refactor-guards.yml` line 82's `origin/<base_ref>`.
- **Honor the DELETE_CANDIDATE.** Do not give `check_docs_source_sync.py` (027) a CI job; state the redundancy with `check_doc_sources.py` + `check_ref_coupling.py`.
- **MERGE the prompt-snapshot slice** into Gate 10 (`report/scripts/check_prompt_snapshots.py`); do not schedule a second snapshot checker.
- **`sonfigs` does not exist.** The confusable trio is `ari-core/ari/config/` (code) vs `ari-core/ari/configs/` (packaged defaults) vs top-level `config/` (rubric data). If the directory-policy gate is discussed, cite the real trio and state that no `sonfigs/` directory exists.
- **Do not use "deprecated" for internal code.** Reserve it for external contracts (public API, CLI, MCP, dashboard API, documented import paths, ari-skill stable interfaces). For the `origin/<base_ref>` idiom, say "not preferred / not to be copied", not "deprecated".
- **Every gate is deterministic (P2).** No LLM, no network — same rule as `ari-skill-memory` and the docs gates.
- **State the numbering reconciliation prominently** (Section 15) so no reader confuses `012` §16's 045-for-checkers mapping with the canonical `007` 025–031 mapping.
- **Stage everything at 1 first.** Make explicit that promotion to Hard is a later, one-line PR, never part of the initial wiring — this is what keeps the whole rollout non-breaking.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **032** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
