# Subtask 048: Add Issue Templates For Refactoring

- **Subtask ID:** 048
- **Phase:** Phase 9 — GitHub Integration
- **Classification:** `KEEP` (additive net-new files under `.github/ISSUE_TEMPLATE/`; no existing runtime code, workflow, config, prompt, or directory is modified)
- **Changes runtime code:** **No** (see Section 16 — this subtask adds only GitHub-rendered YAML intake forms under `.github/`)
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`)

> **Planning-phase notice.** This document is a plan for a *future* coding session. Authoring *this* plan changes no runtime code, imports, prompts, configs, workflows, frontend, or directory names — the only file written by authoring it is this `.md` itself. When the subtask it describes is later executed, it creates **only** additive files under `.github/ISSUE_TEMPLATE/` (and no `.py`, no source, no existing-workflow edit). GitHub issue templates are a repo-governance / contributor-intake artifact, not part of the `ari` runtime.

---

## 1. Goal

Add a structured GitHub **Issue Forms** set under `.github/ISSUE_TEMPLATE/` so that contributors filing issues during (and after) the refactoring program are routed into the project's vocabulary and contract discipline at *intake time* — before triage, not after. Concretely:

- A **refactoring-subtask** form that captures the master-prompt classification vocabulary (`KEEP` / `ADAPT` / `MERGE` / `MOVE_TO_LEGACY` / `DELETE_CANDIDATE` / `REVIEW_REQUIRED`), the affected external-contract surfaces, a "changes runtime code (Yes/No)" field, and predecessor-subtask dependencies — mirroring the fields this refactoring program already tracks in `docs/refactoring/007_subtask_index.md` and in each subtask `.md`.
- A **contract-regression** form for reporting a break in one of the protected surfaces (CLI `ari`, `ari.public.*`, MCP tool contracts, dashboard API, checkpoint/config file formats).
- A general **bug-report** form for runtime defects.
- A `config.yml` that disables blank issues and routes **security reports away from public issues** to the private channel already documented in `SECURITY.md`.

The deliverable is a small, self-consistent, GitHub-valid template set. It hosts *human-facing* structure only; the machine-checkable contract gates live in the checker/workflow subtasks (049–052) and are cited, not duplicated, here.

---

## 2. Background

`.github/` today contains **only** `workflows/` — verified via `find .github -type f`, which returns exactly the five workflow files (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`, `refactor-guards.yml`) and nothing else. Confirmed **absent** (each checked directly and again for this plan): `.github/ISSUE_TEMPLATE/` (`ls` → "No such file or directory"), `.github/PULL_REQUEST_TEMPLATE.md`, `.github/dependabot.yml`, `CODEOWNERS`, and `.github/actions/`.

There is therefore **no structured issue intake**. Anyone opening an issue gets GitHub's blank editor, so the refactoring program's own vocabulary (classification verdicts, contract surfaces, "changes runtime code" flag, predecessor dependencies) is not surfaced to reporters and must be reconstructed by hand during triage.

`CONTRIBUTING.md` (416 lines, repo root) documents structure and engineering discipline — including the `## Software-engineering discipline (v0.7+ refactor)` section (line 347), the "Public API — skills only see `ari.public.*`" rule (line 374), the "Prompts and config are external, byte-stable" rule (line 382), the behaviour-preservation contract (line 395), and a `### Deprecation process` (line 408). It is **prose**, not a GitHub-rendered form, and it contains no issue-intake schema. `SECURITY.md` (54 lines) already defines the private vulnerability-reporting channel ("do not open a public issue or pull request"; use the repository **Security** tab → *Report a vulnerability*) — the issue-template `config.yml` must point reporters there rather than let them file security bugs in the public tracker.

This subtask is one of seven that fan out from **045 `inventory_github_workflows`** per the dependency graph (`045 -> 046, 047, 048, 049, 050, 051, 052`) and the canonical index `docs/refactoring/007_subtask_index.md` (Phase 9). Its sibling **047** owns `PULL_REQUEST_TEMPLATE.md`; **052** owns `dependabot.yml` + a GitHub Actions policy (and, per `007`, `CODEOWNERS`). The master design lives in `docs/refactoring/012_github_workflow_integration_plan.md` (§4 "Current PR / Issue Templates", §9 the PR review-checklist policy, §15 the proposed `.github/` layout).

**Numbering-drift note the implementer must respect.** `docs/refactoring/012_github_workflow_integration_plan.md` §15/§16 attributes `ISSUE_TEMPLATE/` to subtask **052** and maps **048** to `check_public_api_contracts.py`. That mapping is *stale*. The authoritative source is `007_subtask_index.md` (and this program's master prompt), which assigns **048 = `add_issue_templates_for_refactoring` (`ISSUE_TEMPLATE/` set)**, **047 = PR template**, **052 = `dependabot.yml` + actions policy**. Follow `007`; do not re-scope this subtask to public-API checking.

---

## 3. Scope

In scope (the files this subtask creates — all under `.github/ISSUE_TEMPLATE/`):

1. `config.yml` — `blank_issues_enabled: false` and a `contact_links` list routing security reports to the `SECURITY.md` channel and general questions to docs/discussions.
2. `refactoring_subtask.yml` — a GitHub **issue form** encoding the refactoring vocabulary (classification dropdown, contract-surface checkboxes, changes-runtime-code dropdown, predecessor-subtask field, rollback/acceptance notes).
3. `contract_regression.yml` — a form to report a break in a protected external contract.
4. `bug_report.yml` — a general runtime-defect form.

Also in scope: choosing the intake format (issue **Forms** in YAML vs legacy Markdown templates — see §7), the default `labels:` per form, and the wording that keeps forms consistent with `CONTRIBUTING.md`, `SECURITY.md`, and the classification vocabulary.

Out of scope: everything in Section 4.

---

## 4. Non-Goals

- **No PR template.** `.github/PULL_REQUEST_TEMPLATE.md` is owned by subtask **047**; do not create it here.
- **No `dependabot.yml`, no `CODEOWNERS`, no `.github/actions/`.** Owned by subtask **052** (and 049 for workflows). All are absent today and stay absent under this subtask.
- **No workflow changes.** The five existing `.github/workflows/*.yml` are `KEEP` and untouched. This subtask adds **no** CI job and **no** local form-schema validator (a validator, if wanted, is a separate tooling subtask — see §7 and §12).
- **No checker scripts.** No `scripts/check_*.py` is created; the machine-checkable contract gates (public-API, viz-schema, import-boundary, etc.) belong to Phase-8/Phase-9 checker subtasks (025–031, 046, 049–051).
- **No label creation as a repository setting.** Issue-form `labels:` reference labels by name; creating labels in the repository (Settings → Labels) is an out-of-band GitHub-UI/API action, not a file in this repo (there is no labels manifest — `find .github -iname "*label*"` → none). See §6/§11 for the silent-drop gotcha.
- **No runtime code, prompt, config, checkpoint, or frontend change** of any kind. No manifest edit (`requirements.txt`, `requirements.lock`, `ari-core/pyproject.toml` untouched). No new dependency installed.
- **No edit to `CONTRIBUTING.md` / `SECURITY.md` / `README*.md`.** The forms *reference* them by relative link; documentation cross-linking updates, if any, belong to the docs subtask (Phase 10, 017), not here.

---

## 5. Current Files / Directories to Inspect

Real repo paths a fresh implementer must read before writing the templates:

**Target directory (create it):**
- `.github/ISSUE_TEMPLATE/` — **does not exist** (verified). This subtask creates it plus the YAML files inside.

**Existing `.github/` (read only — do not edit):**
- `.github/workflows/refactor-guards.yml` (105 lines) — triggers on `pull_request` to **both** `main` and `refactoring` branches (lines 12–16). Relevant because the PR that adds these templates will run this workflow; confirm the additive `.github/ISSUE_TEMPLATE/*.yml` files do not perturb its two jobs (`no-home-ari-writes` pytest sandbox; `no-new-home-ari-refs` diff over `ari-core/ari/**.py` only — the templates are not Python and not under `ari-core/ari/`, so neither job is affected).
- `.github/workflows/docs-sync.yml`, `docs-change-coupling.yml`, `readme-sync.yml`, `pages.yml` — read to confirm **none** references `.github/**` in a trigger path filter (`pages.yml` push filter is `docs/**`, `report/**`, `README.md` only), so adding issue templates triggers no docs build and no Pages deploy.

**Governance docs the forms must stay consistent with (read, cite, do not edit):**
- `SECURITY.md` (54 lines, repo root) — the private vulnerability-reporting channel the `config.yml` `contact_links` must point to (Security tab → *Report a vulnerability*).
- `CONTRIBUTING.md` (416 lines, repo root) — the engineering discipline the forms echo: `## Software-engineering discipline (v0.7+ refactor)` (line 347), "Public API — skills only see `ari.public.*`" (line 374), "Prompts and config are external, byte-stable" (line 382), behaviour-preservation contract (line 395).
- `docs/refactoring/007_subtask_index.md` — **canonical** subtask numbering (Phase 9 rows 045–052); resolves the 012 drift (§2).
- `docs/refactoring/012_github_workflow_integration_plan.md` (§4 templates absent, §9 PR checklist policy, §15 `.github/` layout) — the master design this subtask realizes for the *issue* side.

**Contract surfaces the `contract_regression.yml` form enumerates (read to name them correctly, do not modify):**
- `ari-core/ari/public/` — 9 modules (`claim_gate.py`, `config_schema.py`, `container.py`, `cost_tracker.py`, `llm.py`, `paths.py`, `run_env.py`, `verified_context.py`, `__init__.py`) — the `ari.public.*` surface.
- `ari-core/ari/cli/` — console script `ari = ari.cli:app`.
- `ari-skill-*/src/server.py` (14 skills) — MCP tool contracts.
- `ari-core/ari/viz/routes.py` (1197 lines) + `api_*.py` + `ari-core/ari/viz/frontend/src/services/api.ts` (863 lines) — dashboard API.
- `ari-core/ari/checkpoint.py` and the `config/` + `configs/` YAML formats — checkpoint/config file formats.

**Tooling read to confirm no gate breaks (read only):**
- `scripts/readme_sync.py` — its `SKIP_NAMES` set (lines 35–39) **includes `.github`**, so files added under `.github/ISSUE_TEMPLATE/` are never scanned and never require a `## Contents` README; the `readme-sync.yml` gate is therefore unaffected (confirmed; see §6).

---

## 6. Current Problems

1. **No structured issue intake exists.** `.github/ISSUE_TEMPLATE/` is absent; every issue is a blank editor. The refactoring vocabulary (classification, contract surfaces, changes-runtime-code, dependencies) that this whole program is organized around is not captured at report time.
2. **Security reports can land in the public tracker.** With no `config.yml`, GitHub offers a blank public issue by default. `SECURITY.md` explicitly asks reporters *not* to do this, but nothing steers them to the private channel at the point of filing.
3. **Contract-regression reports are unstructured.** A break in `ari.public.*`, the `ari` CLI, an MCP tool schema, or the dashboard API is exactly what the Phase-9 gates protect — but there is no intake that asks a reporter *which* surface broke, which is the first triage question every time.
4. **Vocabulary drift between reporters and the program.** Because intake is freeform, issues do not use `KEEP` / `ADAPT` / `MERGE` / `MOVE_TO_LEGACY` / `DELETE_CANDIDATE` / `REVIEW_REQUIRED`, so triage has to re-derive the verdict a form could have asked for directly.
5. **Label silent-drop gotcha (design constraint, not a bug to fix in code).** GitHub issue **Forms** apply a form's `labels:` **only if those labels already exist** in the repository; nonexistent labels are silently dropped (this differs from some legacy-template behaviors). The repo has **no** labels manifest (`find .github -iname "*label*"` → none) and GitHub's defaults include `bug`/`enhancement`/`documentation` but **not** `refactoring` or `contract-regression`. The plan must therefore either restrict `labels:` to labels that exist, or explicitly document that `refactoring` / `contract-regression` must be created out-of-band first (§11) — otherwise the forms look correct but silently fail to label.
6. **Numbering drift in the master plan.** `012_github_workflow_integration_plan.md` maps `ISSUE_TEMPLATE/` to subtask 052 and 048 to public-API checking; left unreconciled, an implementer reading only 012 would build the wrong artifact (§2). Not a code problem — a coordination hazard.

---

## 7. Proposed Design / Policy

### 7.1 Format: GitHub Issue **Forms** (YAML), plus `config.yml`

Use **issue forms** (`.github/ISSUE_TEMPLATE/*.yml` with a `body:` array of `input`/`textarea`/`dropdown`/`checkboxes`/`markdown` elements), not legacy Markdown templates. Forms give required fields, dropdowns for the fixed classification vocabulary, and checkboxes for contract surfaces — a much better fit for this program's structured data than freeform Markdown. Each form file carries the standard top-level keys: `name`, `description`, `title` (prefix), `labels`, and `body`.

### 7.2 The template set (4 files — focused, not gold-plated)

```
.github/ISSUE_TEMPLATE/
├── config.yml                 (blank_issues_enabled: false + contact_links)
├── refactoring_subtask.yml    (the core refactoring-program form)
├── contract_regression.yml    (report a break in a protected contract surface)
└── bug_report.yml             (general runtime defect)
```

A `feature_request.yml` is **optional / `REVIEW_REQUIRED`**: the program's focus is refactoring, so it is not part of the core four; add it only if maintainers want a general enhancement channel (it uses the default `enhancement` label, which exists).

### 7.3 `config.yml`

```yaml
blank_issues_enabled: false
contact_links:
  - name: Security vulnerability (private)
    url: https://github.com/<owner>/<repo>/security/advisories/new
    about: >-
      Do NOT open a public issue for security problems. Report privately via the
      Security tab (see SECURITY.md).
  - name: Question / usage help
    url: <docs or Discussions URL>
    about: For usage questions, read the docs first or start a discussion.
```

Notes: `blank_issues_enabled: false` forces reporters through a template. The security `url` mirrors `SECURITY.md`'s private-reporting channel; the `<owner>/<repo>` placeholder and the docs/Discussions URL are filled at implementation time from the repo's actual remote (do not hardcode a guessed org). If GitHub Discussions is not enabled, point the second link at the published docs site instead.

### 7.4 `refactoring_subtask.yml` — the core form

Body elements (types in parentheses):

- **Subtask / area** (`input`, required) — the subtask ID (e.g. `048`) or affected area if not yet numbered.
- **Phase** (`input`, optional) — refactoring phase, e.g. "Phase 9: GitHub Integration".
- **Proposed classification** (`dropdown`, required, single-select) — options **exactly**: `KEEP`, `ADAPT`, `MERGE`, `MOVE_TO_LEGACY`, `DELETE_CANDIDATE`, `REVIEW_REQUIRED`. (Do **not** offer "deprecated" as a verdict for internal code — that word is reserved for external contracts.)
- **Changes runtime code?** (`dropdown`, required) — options: `No`, `Yes`. Mirrors the field every subtask `.md` and `007_subtask_index.md` carries.
- **Affected contract surfaces** (`checkboxes`, optional) — one box each for: CLI `ari`; `ari.public.*`; MCP tool contracts (`ari-skill-*`); dashboard API (`ari/viz` + `services/api.ts`); checkpoint/config file formats; prompt templates (`ari/prompts/**`); docs/README. A checked box signals a protected surface is touched and pulls in the corresponding review policy.
- **Predecessor subtasks / dependencies** (`input`, optional) — predecessor IDs (e.g. "depends on 045"), consistent with the dependency graph.
- **Summary / rationale** (`textarea`, required).
- **Acceptance criteria / rollback sketch** (`textarea`, optional).
- **Self-attestation** (`checkboxes`, required at least implicitly) — "I read `CONTRIBUTING.md` §Software-engineering discipline and `docs/refactoring/012_github_workflow_integration_plan.md`".

Default `labels: [refactoring]` (see §11 re: creating the `refactoring` label first).

### 7.5 `contract_regression.yml`

- **Which contract broke?** (`dropdown`, required) — options: CLI `ari`; `ari.public.*`; MCP tool contract; dashboard API endpoint/schema; checkpoint/output format; config file format.
- **Version / commit observed** (`input`, required) — e.g. `ari-core 0.9.0` or a commit SHA.
- **Expected vs actual** (`textarea`, required).
- **Minimal reproduction** (`textarea`, required).
- Default `labels: [contract-regression]` (create the label first, §11).

### 7.6 `bug_report.yml`

Standard runtime-defect form: **What happened** / **Expected** / **Reproduction** / **Environment** (OS, Python, `ari` version, cloud vs HPC vs laptop profile) / **Logs**. Default `labels: [bug]` (`bug` is a GitHub default label, so it applies without out-of-band creation).

### 7.7 Consistency rules

- Every form's `body` must be **valid GitHub issue-form schema**: at least one non-`markdown` element, unique `id`s within a file, `dropdown` `options` as a non-empty list, `validations: {required: true}` only on non-`markdown` elements.
- Wording references governance docs by **relative repo link** (`../../SECURITY.md`, `../../CONTRIBUTING.md`) so they render on GitHub.
- Do not invent labels beyond `refactoring`, `contract-regression`, `bug` (+ optional `enhancement`); keep the label vocabulary minimal and documented.

---

## 8. Concrete Work Items

1. Create the directory `.github/ISSUE_TEMPLATE/`.
2. Add `.github/ISSUE_TEMPLATE/config.yml` (§7.3), filling the real `<owner>/<repo>` from `git remote get-url origin` and the docs/Discussions URL from the repo's published docs.
3. Add `.github/ISSUE_TEMPLATE/refactoring_subtask.yml` (§7.4) with the exact 6-value classification dropdown and the contract-surface checkboxes.
4. Add `.github/ISSUE_TEMPLATE/contract_regression.yml` (§7.5).
5. Add `.github/ISSUE_TEMPLATE/bug_report.yml` (§7.6).
6. Validate every YAML file parses (well-formedness) locally and conforms to the issue-form schema field rules (§7.7). See §12 for the exact commands.
7. Document — in the PR body, not by editing repo docs — that the `refactoring` and `contract-regression` labels must be created in the repository (Settings → Labels or `gh label create`) **before or with** merge, or the forms will silently drop them (§6/§11).
8. Confirm no existing gate is perturbed: run the standard trio + `readme_sync.py --check` (§12) and confirm the `refactor-guards.yml` jobs are unaffected (the templates are not Python and not under `ari-core/ari/`).
9. Optionally add a `feature_request.yml` **only if** maintainers request it (§7.2) — otherwise leave it out to avoid gold-plating.

---

## 9. Files Expected to Change

**New files (additive — all net-new; `ISSUE_TEMPLATE/` does not exist today):**
- `.github/ISSUE_TEMPLATE/config.yml`
- `.github/ISSUE_TEMPLATE/refactoring_subtask.yml`
- `.github/ISSUE_TEMPLATE/contract_regression.yml`
- `.github/ISSUE_TEMPLATE/bug_report.yml`
- *(optional, only on request)* `.github/ISSUE_TEMPLATE/feature_request.yml`

**Files NOT changed (explicitly):**
- No existing `.github/workflows/*.yml`.
- No `CONTRIBUTING.md`, `SECURITY.md`, `README*.md`.
- No `scripts/**`, no `ari-core/**`, no `ari-skill-*/**`, no frontend, no config/prompt/checkpoint files.
- No repository labels-as-files (none exist; label creation is out-of-band, §11).

---

## 10. Files / APIs That Must Not Be Broken

This subtask touches only additive `.github/ISSUE_TEMPLATE/*.yml` files, so it cannot functionally break any runtime contract. The contracts below are listed to confirm they are **untouched**:

- **CLI** `ari = ari.cli:app` — untouched.
- **Public Python API** `ari.public.*` (9 modules) — untouched.
- **MCP tool contracts** — the 14 `ari-skill-*/src/server.py` servers — untouched.
- **Dashboard API** — `ari/viz/routes.py` + `api_*.py` + `frontend/src/services/api.ts` — untouched.
- **Checkpoint / output / config file formats** — untouched.
- **Existing CI gates** — the five workflows must keep passing:
  - `readme-sync.yml` (`readme_sync.py --check`): unaffected because `.github` is in the script's `SKIP_NAMES` (lines 35–39), so no `## Contents` README is required for the new directory.
  - `refactor-guards.yml`: both jobs unaffected — the new files are not Python and not under `ari-core/ari/`, so neither the pytest sandbox nor the `~/.ari` diff (scoped to `ari-core/ari/**.py`) sees them.
  - `docs-sync.yml`, `docs-change-coupling.yml`, `pages.yml`: none reference `.github/**` in a trigger or check, so all are inert to this change.

---

## 11. Compatibility Constraints

- **Additive-only.** Adding `.github/ISSUE_TEMPLATE/` changes GitHub's *issue-open UX* only; it introduces no runtime behavior and is trivially reversible (§14). No compatibility adapter is needed because no contract is altered.
- **Label pre-existence (hard GitHub constraint).** Issue **Forms** apply `labels:` only for labels that already exist in the repo; unknown labels are silently dropped. `bug` (and `enhancement`) exist as GitHub defaults; **`refactoring`** and **`contract-regression`** do **not** and must be created out-of-band (repo Settings → Labels, or `gh label create refactoring` / `gh label create contract-regression`) as part of landing this subtask. This is a repository setting, not a tracked file (there is no labels manifest, and adding one is out of scope). Document it in the PR body.
- **Placeholder URLs.** `config.yml` `contact_links` must use the repo's real `origin` owner/name and a real docs/Discussions URL; do not commit a guessed org path. If Discussions is disabled, drop or repoint that link.
- **Do not reserve "deprecated" for internal code.** The classification dropdown offers only the six approved verdicts; "deprecated" is not an option — it is reserved for external-contract removals.
- **Coordinate numbering with 007, not 012.** Keep this subtask scoped to issue templates (per `007_subtask_index.md`); the PR template (047) and `dependabot.yml`/actions policy (052) are separate subtasks (§2).

---

## 12. Tests to Run

No Python is added, so the standard trio is a **regression sanity check** (confirming this subtask touched nothing Python) rather than a test of new behavior:

```bash
python -m compileall .        # unchanged; no new .py, must stay green
pytest -q                     # unchanged; issue templates are not exercised by tests
ruff check .                  # unchanged; no Python touched
```

Template-specific validation (the meaningful checks for this subtask):

```bash
# 1. YAML well-formedness for every new template (PyYAML is already available in CI):
python - <<'PY'
import glob, yaml, sys
bad = 0
for f in sorted(glob.glob(".github/ISSUE_TEMPLATE/*.yml")):
    try:
        yaml.safe_load(open(f, encoding="utf-8"))
        print("OK  ", f)
    except Exception as e:
        print("FAIL", f, e); bad = 1
sys.exit(bad)
PY

# 2. Confirm no README-drift gate is triggered (.github is skipped, so this stays green):
python scripts/readme_sync.py --check
```

- **Frontend (`npm test` / `npm run build`):** **N/A** — this subtask adds no frontend files. Do not run.
- **GitHub issue-form schema validation:** there is **no local form-schema validator in this repo** today (adding one is a separate tooling subtask, not this one). Validate the schema by pushing the branch and confirming GitHub's Issues → *New issue* chooser renders all templates without the "There is an error in the template" banner. This manual render check is the authoritative acceptance step for schema correctness.

---

## 13. Acceptance Criteria

1. `.github/ISSUE_TEMPLATE/` exists and contains `config.yml`, `refactoring_subtask.yml`, `contract_regression.yml`, `bug_report.yml`.
2. Every `.yml` under `.github/ISSUE_TEMPLATE/` parses (YAML check in §12 passes) and renders on GitHub with **no** template-error banner.
3. `config.yml` sets `blank_issues_enabled: false` and its `contact_links` route security reports to the `SECURITY.md` private channel.
4. `refactoring_subtask.yml`'s classification dropdown offers **exactly** `KEEP`, `ADAPT`, `MERGE`, `MOVE_TO_LEGACY`, `DELETE_CANDIDATE`, `REVIEW_REQUIRED` (and no "deprecated"), plus a required "Changes runtime code? (No/Yes)" field and contract-surface checkboxes.
5. `contract_regression.yml` enumerates the real protected surfaces (CLI, `ari.public.*`, MCP, dashboard API, checkpoint/config formats).
6. The standard trio (§12) stays green and `scripts/readme_sync.py --check` passes (no new `## Contents` requirement).
7. All five existing workflows still pass on the PR (in particular `refactor-guards.yml`, which runs on PRs to `main`/`refactoring`).
8. The PR body documents the out-of-band creation of the `refactoring` and `contract-regression` labels (§11).
9. No file outside `.github/ISSUE_TEMPLATE/` is modified.

---

## 14. Rollback Plan

Fully additive and self-contained: `git rm -r .github/ISSUE_TEMPLATE/` (and remove the two out-of-band labels via `gh label delete` if desired) restores the prior state exactly. No migration, no data, no runtime dependency is involved, so rollback is a single deletion with zero blast radius on `ari` runtime or any contract surface.

---

## 15. Dependencies

Per the dependency graph and `docs/refactoring/007_subtask_index.md` (Phase 9):

- **Depends on:** **045 `inventory_github_workflows`** (`045 -> 048`). 045 is the Phase-9 inventory that must precede the fan-out subtasks 046–052; it establishes the confirmed-absent `.github/` state and the workflow/idiom conventions this subtask relies on. 045 is one of the nine inventory subtasks (001, 002, 020, 036, 045, 053, 059, 060, 067) that must precede any runtime code change — though note **this** subtask changes no runtime code regardless.
- **Sibling (independent, do not couple):** 046 (CI integration design), **047** (PR template), 049 (contract-check workflows), 050 (docs-sync workflow), 051 (prompt-change review workflow), **052** (`dependabot.yml` + actions policy, and `CODEOWNERS`). This subtask can proceed in parallel with all of them; it shares no files with any sibling.
- **No dependents:** nothing in the graph lists 048 as a predecessor. Optional soft coupling: 052's `CODEOWNERS` can route the labels this subtask introduces, but that is 052's concern, not a blocking dependency.

---

## 16. Risk Level

**Low.**

- **Changes runtime code:** **No.** Only additive `.github/ISSUE_TEMPLATE/*.yml` files are created; no Python, no workflow edit, no config/prompt/checkpoint/frontend change.
- **Blast radius:** GitHub issue-open UX only; no CI gate is added or altered; rollback is a single directory deletion (§14).
- **Residual risks, all low and mitigated:** (a) label silent-drop if `refactoring`/`contract-regression` are not created — mitigated by the PR-body note and §11; (b) issue-form schema typo — caught by the GitHub render check (§12); (c) stale `config.yml` URLs — mitigated by filling the real `origin` owner/name at implementation.

---

## 17. Notes for Implementer

- **Follow `007`, not `012`, for numbering.** This subtask = issue templates. The 012 plan's §15/§16 attribution of `ISSUE_TEMPLATE/` to 052 and of 048 to public-API checking is stale (§2); do not re-scope.
- **Fill placeholders from the real remote.** Use `git remote get-url origin` for the `<owner>/<repo>` in `config.yml`'s security link; use the actual published docs URL (or a Discussions URL only if Discussions is enabled) for the help link.
- **Create the two labels out-of-band.** `gh label create refactoring --description "Refactoring program work item"` and `gh label create contract-regression --description "Break in a protected external contract"` — otherwise the forms' `labels:` are silently dropped (§6/§11). Note this in the PR body.
- **Keep the vocabulary exact.** The classification dropdown must list the six approved verdicts verbatim and must not include "deprecated".
- **Do not add a schema validator or CI job here.** If maintainers want automated issue-form validation, that is a separate tooling subtask (a candidate `scripts/check_issue_templates.py` or a GitHub-provided action) — out of scope for 048.
- **Verify the `.github` skip yourself.** Re-read `scripts/readme_sync.py` lines 35–39 to confirm `.github` is still in `SKIP_NAMES` before relying on the "no README required" claim; if that set ever changes, the `readme-sync.yml` gate could start requiring a `## Contents` file under `.github/`.
- **`sonfigs/` does not exist** and is irrelevant here; the config surface named in `contract_regression.yml` is the real trio `ari-core/ari/config/` (code) vs `ari-core/ari/configs/` (packaged defaults) vs top-level `config/` (rubric data) — but the form only needs to say "config file formats", so no directory naming is baked in.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **048** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
