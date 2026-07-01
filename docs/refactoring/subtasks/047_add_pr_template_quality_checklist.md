# Subtask 047: Add PR Template Quality Checklist

- **Subtask ID:** 047
- **Phase:** Phase 9 — GitHub Integration
- **Classification:** `KEEP` (net-new, additive `.github/` template; no runtime code, imports, prompts, configs, workflows, frontend, or directory names are changed)
- **Changes runtime code:** **No** (see Section 16)
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`)
- **Deliverable:** `.github/PULL_REQUEST_TEMPLATE.md` (net-new; does **not** exist today)

> **Planning-phase notice.** This document is a plan for a *future* coding session. Authoring it changes no runtime code, imports, prompts, configs, workflows, frontend, or directory names. The only file created by authoring this plan is this `.md` itself. Everything under "Concrete Work Items" and "Files Expected to Change" describes what the **implementer of subtask 047** will do in a later, separate session.

> **Numbering note (read first — two docs disagree on what "047" owns).** The authoritative subtask index `docs/refactoring/007_subtask_index.md` (row 94) assigns **047 = `add_pr_template_quality_checklist`**, deliverable `.github/PULL_REQUEST_TEMPLATE.md`, phase 9, depends-on **045**. The Phase-9 narrative in the same index (lines 352–354) confirms "**047 add_pr_template_quality_checklist / 048 add_issue_templates_for_refactoring** — net-new files (both absent)." **However**, the governing integration doc `docs/refactoring/012_github_workflow_integration_plan.md` §15/§16 uses a *divergent local numbering* in its workflow-layout table: there "047" is mislabeled as `check_directory_policy.py` and the `.github/` templates (including `PULL_REQUEST_TEMPLATE.md`) are attributed to "subtask 052". **Follow `007_subtask_index.md`.** This subtask is the **PR template**; the substance of what the template must contain is 012 **§9 "Pull Request Review Checklist Policy"** (lines 209–222), which explicitly opens: "Because `PULL_REQUEST_TEMPLATE.md` does not exist (§4), the checklist policy first requires creating that file." When you cite 012, cite §4 and §9 (content), not §15/§16 (subtask-attribution table, which is internally renumbered).

---

## 1. Goal

Add a single, additive GitHub-rendered file — `.github/PULL_REQUEST_TEMPLATE.md` — that pre-fills every new pull request's body with a **contract-preservation self-attestation checklist** plus a small structured header (summary, subtask ID, classification, test evidence). The template surfaces, at PR-open time, the exact contract surfaces the refactor must not silently break, so authors self-certify before requesting review.

Today there is **no** PR template anywhere in the ARI repo's own `.github/` (verified: `find .github -type f` returns only the 5 workflow files; `.github/PULL_REQUEST_TEMPLATE.md` and `.github/pull_request_template.md` are both absent). `CONTRIBUTING.md` (416 lines) documents the engineering discipline in prose (§ "Software-engineering discipline (v0.7+ refactor)", lines 347–416) but it is **not** a GitHub-rendered form and is never shown in the PR compose box. Consequently the review-checklist policy (012 §9) currently has **nowhere to be surfaced to authors**. This subtask fills that gap with the lowest-risk change in the entire integration plan: one markdown file, no code, no CI behavior change.

The deliverable is **one** new markdown file. No `ari/` runtime module, no skill, no frontend, no `.github/workflows/*.yml`, and no config is modified.

**Explicit non-actions of this subtask** (owned elsewhere — do not do them here):
- Do **not** create `ISSUE_TEMPLATE/` — that is subtask **048 `add_issue_templates_for_refactoring`** (`007_subtask_index.md` row 95).
- Do **not** create `dependabot.yml`, `CODEOWNERS`, or an actions-policy file — that is subtask **052 `add_dependabot_and_actions_policy`** (`007_subtask_index.md` row 99). CODEOWNERS reviewer-routing is the *complementary* mechanism to the checklist (012 §9 final paragraph) but is explicitly **REVIEW_REQUIRED** and out of 047's scope.
- Do **not** wire anything into CI. The 5 existing workflows are untouched; the contract-check workflows are subtask **049 `add_contract_check_workflows`**.
- Do **not** author the checker scripts the checklist references (`check_public_api_contracts.py`, `check_viz_api_schema.py`, etc.). Those are Phase-8 subtasks; the template must reference them **as "if applicable" self-attestation prose**, not as hard preconditions (many do not exist yet — see §7.4).

---

## 2. Background

### 2.1 Current `.github/` surface (verified)

`/home/t-kotama/workplace/ARI/.github/` contains **only** `workflows/`, with exactly 5 files (confirmed by `find .github -type f`):

| File | Trigger (summary) |
| --- | --- |
| `.github/workflows/docs-change-coupling.yml` | `pull_request` → `main`; tri-language report co-change gate |
| `.github/workflows/docs-sync.yml` | `pull_request` → `main`; doc-source/i18n/README-parity gates + VitePress build |
| `.github/workflows/pages.yml` | `push` → `main` (paths `docs/**`,`report/**`,`README.md`) + `workflow_dispatch`; Pages deploy |
| `.github/workflows/readme-sync.yml` | `pull_request` → `main`; per-directory README `## Contents` parity |
| `.github/workflows/refactor-guards.yml` | `pull_request` → `main` **and** `refactoring`; `~/.ari/` invariant + pytest sandbox |

**Confirmed ABSENT** (each checked directly): `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/pull_request_template.md`, `.github/dependabot.yml`, `CODEOWNERS` (checked `.github/`, repo root, `docs/`), `.github/actions/`.

> **One decoy to ignore.** A vendored third-party copy exists at `ari-skill-idea/vendor/virsci/agentscope-main/.github/pull_request_template.md` (and `.../PULL_REQUEST_TEMPLATE.md`, `.../ISSUE_TEMPLATE/*.md`). That belongs to the bundled `agentscope` upstream, **not** to ARI. It is not read by GitHub for ARI PRs (GitHub only reads the repo-root, `.github/`, or `docs/` template locations). Do **not** copy, edit, or reference it.

### 2.2 What the checklist must encode (012 §9, verified)

`012_github_workflow_integration_plan.md` §9 (lines 209–222) specifies the exact self-attestation items. Each item names a **contract surface** that the refactor must not silently break, with the fallback action if it *is* changed:

1. **CLI surface** unchanged, or change documented in `docs/reference/cli_reference.md` and the root README CLI table (README `## CLI Commands`, lines ~316–328 — verified: table of `ari run`/`resume`/`paper`/… commands).
2. **`ari.public.*`** unchanged, or `check_public_api_contracts.py` snapshot updated with justification (§13).
3. **MCP tool contracts** (`ari-skill-*/src/server.py`) unchanged, or the skill's tool-schema change documented in `docs/reference/mcp_tools.md`.
4. **Dashboard API** (`ari/viz/routes.py` + `api_*.py`) unchanged, or `services/api.ts` and `docs/reference/rest_api.md` updated in the same PR (§12).
5. **Checkpoint/config file formats** unchanged, or a migration under `ari-core/ari/migrations/` is included.
6. **Prompt templates** — any inline prompt moved to `ari/prompts/<area>/<purpose>.md` with the Gate 10 sha256 snapshot updated (012 §11; `CONTRIBUTING.md` §385–399, verified: "The prompt file is byte-equivalent to the inline original; pin the sha256 in `ari-core/tests/test_prompt_extraction.py`").
7. **Docs `sources:` front-matter and per-directory README `## Contents`** updated (already CI-enforced by `docs-sync.yml`/`readme-sync.yml`; §10).
8. **No new `~/.ari/` references** outside the sanctioned allow-list (already CI-enforced by `refactor-guards.yml`, job `no-new-home-ari-refs`).

012 §9 stresses the checklist is **advisory to humans**; the machine-checkable items (2, 4, 7, 8) are separately backed by CI gates so the template is never the sole line of defense. All eight referenced `docs/reference/*.md` files were verified to exist (`cli_reference.md`, `mcp_tools.md`, `rest_api.md`, `public_api.md`, `environment_variables.md`, `skills.md`).

### 2.3 Why now, and why this is the safest item in the plan

012 §4 (lines 95–101) classifies introducing `PULL_REQUEST_TEMPLATE.md` as **`KEEP`-as-new / additive** and calls it "the lowest-risk item in this whole plan — it changes no code and no CI behavior." It is a *prerequisite* for the checklist policy (§9) and for the review-policy gates (§10–§14) to have any author-facing surface. The refactoring workstream is exactly the period when contract surfaces are most at risk (prompt externalization, `ari.public.*` adapters, viz route splits), so a PR-open reminder has outsized value.

### 2.4 House conventions this file must follow

- **Language:** clear technical **English** (ARI canonical). Translated prose lives in `docs/ja/` and `docs/zh/`; a GitHub PR template is a single canonical English form and is *not* i18n-mirrored (there is no per-language PR template mechanism, and the docs-sync i18n gates scan `docs/` and `report/`, not `.github/`).
- **Tone/structure:** mirror the existing engineering-discipline prose in `CONTRIBUTING.md` (the five load-bearing rules) so the template reads as the PR-time echo of that document.
- **GitHub rendering:** `- [ ]` lines render as interactive checkboxes in the PR body; `<!-- HTML comments -->` render invisibly (ideal for author instructions). The single default file `.github/PULL_REQUEST_TEMPLATE.md` auto-fills every new PR's body with no query-string needed.

---

## 3. Scope

In scope for the subtask implementation:

1. **New file** `.github/PULL_REQUEST_TEMPLATE.md` containing:
   - A short **header** block: one-line summary prompt; optional refactoring subtask ID field; a **classification** line using the master vocabulary (`KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED`); and a "type of change" hint.
   - The **8-item contract-preservation checklist** transcribed from 012 §9 (§2.2 above), each item phrased as "unchanged, **or** <documented fallback>".
   - A **test-evidence** block prompting the author to paste the results of `python -m compileall .`, `pytest -q`, and `ruff check .` (and `npm test`/`npm run build` under `ari-core/ari/viz/frontend/` for frontend PRs) — matching the CONTRIBUTING testing section (lines 98–128, 296–333).
   - HTML-comment instructions telling authors to delete inapplicable sections and that machine-checkable items are additionally enforced by CI.
2. **Cross-reference** from the template to `CONTRIBUTING.md` (the authoritative prose) and to `docs/refactoring/012_github_workflow_integration_plan.md §9`.
3. **Verification** that the new file does not trip any existing PR-time gate (readme-parity, docs-sync) — see §12.

Out of scope: everything in Section 4.

---

## 4. Non-Goals

- **No runtime-code change.** No file under `ari-core/ari/`, no `ari-skill-*/`, no frontend, no `config/`/`configs/`, no prompt template, no `.github/workflows/*.yml` is edited.
- **No `ISSUE_TEMPLATE/`.** That is subtask **048**.
- **No `dependabot.yml`, no `CODEOWNERS`, no `.github/actions/`.** Those are subtask **052** (`dependabot.yml` + actions policy; CODEOWNERS is REVIEW_REQUIRED there).
- **No CI wiring / no new workflow.** A PR template is picked up by GitHub automatically; it is not a workflow. Contract-check workflows are subtask **049**.
- **No authoring of the checker scripts** the checklist mentions (`check_public_api_contracts.py`, `check_viz_api_schema.py`, `check_prompts.py`, `check_directory_policy.py`, …). Those are Phase-8 subtasks; the template references them as optional self-attestation, not as hard preconditions.
- **No i18n mirror.** No `docs/ja/` / `docs/zh/` counterpart is created (a PR template is not a documentation page and is not covered by the site i18n gates).
- **No editing of `CONTRIBUTING.md` content**, beyond (optionally, REVIEW_REQUIRED) a single cross-link line pointing readers to the new template — see §9. The engineering-discipline rules themselves are not restated or moved.
- **No `sonfigs/` anything.** `sonfigs/` does not exist in the repo; the real confusable trio is `ari-core/ari/config/` (code) vs `ari-core/ari/configs/` (packaged data) vs top-level `ari-core/config/` (rubric data). It is irrelevant to this subtask beyond the checklist's checkpoint/config-format item.

---

## 5. Current Files / Directories to Inspect

All paths relative to `/home/t-kotama/workplace/ARI`. **Read-only inputs** unless marked as the deliverable.

**Governing plan / policy (cite in the template and the PR body):**
- `docs/refactoring/012_github_workflow_integration_plan.md` — **§4** (lines 95–101, "there are none" + KEEP-as-new classification) and **§9** (lines 209–222, the exact 8 checklist items). Ignore §15/§16 subtask attribution (see numbering note).
- `docs/refactoring/007_subtask_index.md` — row 94 (this subtask's identity + `depends-on 045`); Phase-9 narrative (lines 339–360).
- `docs/refactoring/000_master_refactoring_plan.md` — classification vocabulary (`KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED`).

**Content sources for the template body (read-only):**
- `CONTRIBUTING.md` (416 lines) — esp. "Software-engineering discipline (v0.7+ refactor)" (lines 347–416: separation of concerns; Protocols over concretes; `ari.public.*`-only imports; external byte-stable prompts/config with sha256 pin at lines 385–399; behaviour-preservation contract incl. `ari --help` diff-identical). Also the "Running tests" (98–128) and "Testing" (296–333) sections for the test-evidence block.
- `README.md` — `## CLI Commands` table (lines ~316–328) referenced by checklist item 1.

**Contract-surface anchors the checklist names (read-only, to confirm paths):**
- `docs/reference/cli_reference.md`, `docs/reference/mcp_tools.md`, `docs/reference/rest_api.md`, `docs/reference/public_api.md` — all **exist** (verified).
- `ari-core/ari/public/` (the `ari.public.*` surface), `ari-core/ari/viz/routes.py` (1197 LOC) + `ari-core/ari/viz/api_*.py`, `ari-core/ari/viz/frontend/src/services/api.ts` (863 LOC), `ari-skill-*/src/server.py` (14 servers), `ari-core/ari/prompts/`, `ari-core/ari/migrations/`.
- `ari-core/tests/test_prompt_extraction.py` (Gate 10 sha256 pin, cited by checklist item 6) and `ari-core/tests/test_public_api_boundary.py` (the `ari.public.*` CI enforcement point named in CONTRIBUTING rule 3).

**Existing CI to confirm the template does not collide with (read-only):**
- `.github/workflows/refactor-guards.yml` — the `~/.ari/` guard behind checklist item 8.
- `.github/workflows/readme-sync.yml` → `scripts/readme_sync.py` — per-directory README `## Contents` parity (must confirm adding `.github/PULL_REQUEST_TEMPLATE.md` does not require a README entry; `.github/` has no `README.md` `## Contents` index today).
- `.github/workflows/docs-sync.yml` + `scripts/docs/check_doc_sources.py` — doc front-matter gate (scans `docs/`, not `.github/`; confirm).

**Convention exemplar to ignore (decoy):**
- `ari-skill-idea/vendor/virsci/agentscope-main/.github/pull_request_template.md` — vendored upstream; **not** ARI's; do not copy.

**Deliverable location (currently absent):**
- `.github/PULL_REQUEST_TEMPLATE.md` — **to be created**.

---

## 6. Current Problems

Recorded facts that motivate this template (not runtime bugs for 047 to "fix"):

1. **The review-checklist policy has no home.** 012 §9 defines an 8-item contract self-attestation but §4 confirms `PULL_REQUEST_TEMPLATE.md` does not exist, so the policy is prose in a planning doc that no PR author ever sees at compose time.
2. **`CONTRIBUTING.md` is not surfaced at PR-open.** The five engineering-discipline rules (lines 347–416) are exactly the invariants most at risk during the refactor, yet GitHub never renders `CONTRIBUTING.md` into the PR body; authors must remember to open it.
3. **Machine gates cover only part of the surface.** Only `refactor-guards.yml` (item 8) and the docs/README gates (item 7) are enforced today. Items 1–6 (CLI, `ari.public.*`, MCP schemas, dashboard API, checkpoint/config formats, prompt externalization) have **no** CI gate yet (the Phase-8 checkers are unbuilt), so a human self-attestation checklist is currently the *only* practical guard for those surfaces — which makes this template disproportionately valuable right now.
4. **No structured PR metadata.** Without a template, PRs carry free-form bodies; there is no consistent place to record the refactoring subtask ID, the KEEP/ADAPT/… classification, or the test-evidence paste that reviewers need.
5. **A vendored decoy exists.** `ari-skill-idea/vendor/virsci/...` ships its own PR template, which can mislead a grep-only search into thinking ARI already has one. It does not.

---

## 7. Proposed Design / Policy

### 7.1 File location and GitHub semantics

Create exactly one file: `.github/PULL_REQUEST_TEMPLATE.md` (uppercase, in `.github/`). GitHub auto-populates the compose box of **every** new PR from this single default file with no `?template=` query string required. Do **not** use the multi-template directory form (`.github/PULL_REQUEST_TEMPLATE/<name>.md`): that form requires a query parameter to select a template and does **not** auto-fill the default compose box, which defeats the "surface the checklist to every author" goal. One default template is the correct, lowest-friction choice and matches 012 §15's `.github/PULL_REQUEST_TEMPLATE.md` layout entry.

### 7.2 Template structure (recommended)

A single markdown document, roughly:

```markdown
<!-- Thanks for contributing to ARI. Fill in the sections below and delete any
     that do not apply. Machine-checkable items are ALSO enforced by CI; this
     checklist is your self-attestation, not the only line of defense. See
     CONTRIBUTING.md and docs/refactoring/012_github_workflow_integration_plan.md §9. -->

## Summary
<!-- What does this PR do and why? One or two sentences. -->

## Refactoring context (delete if N/A)
- Subtask: <!-- e.g. 047; see docs/refactoring/subtasks/ -->
- Classification: <!-- KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED -->

## Type of change
- [ ] Bug fix   - [ ] Feature   - [ ] Refactor (behaviour-preserving)   - [ ] Docs   - [ ] CI/tooling

## Contract-preservation checklist
<!-- Tick each box. "unchanged" is the happy path; otherwise confirm the fallback. -->
- [ ] CLI surface unchanged, or change documented in `docs/reference/cli_reference.md` and the root README CLI table.
- [ ] `ari.public.*` unchanged, or the public-API snapshot updated with justification (see check_public_api_contracts.py when available).
- [ ] MCP tool contracts (`ari-skill-*/src/server.py`) unchanged, or the tool-schema change documented in `docs/reference/mcp_tools.md`.
- [ ] Dashboard API (`ari/viz/routes.py` + `api_*.py`) unchanged, or `services/api.ts` and `docs/reference/rest_api.md` updated in the same PR.
- [ ] Checkpoint/config file formats unchanged, or a migration under `ari-core/ari/migrations/` is included.
- [ ] Prompts: any inline LLM prompt moved to `ari/prompts/<area>/<purpose>.md` with the sha256 snapshot updated (`ari-core/tests/test_prompt_extraction.py`).
- [ ] Docs `sources:` front-matter and per-directory README `## Contents` updated (CI-enforced).
- [ ] No new `~/.ari/` references outside the sanctioned allow-list (CI-enforced by refactor-guards.yml).

## Test evidence
<!-- Paste the relevant results. -->
- [ ] `python -m compileall .`
- [ ] `pytest -q`  (or the CONTRIBUTING per-package command)
- [ ] `ruff check .`
- [ ] Frontend only: `npm test` + `npm run build` under `ari-core/ari/viz/frontend/`
```

Exact wording is the implementer's call so long as the **eight checklist items match 012 §9 verbatim in meaning** and the vocabulary/paths are the real ones verified in §2.2/§5.

### 7.3 Advisory-to-humans, backed-by-CI framing

Per 012 §9, the checklist is **advisory to humans**. The template must say so in an HTML comment: ticking a box is a self-attestation; items 2/4/7/8 are *additionally* enforced by CI (once the Phase-8 checkers land), so an unticked-but-actually-fine PR is still gated by machines where it matters. This prevents the template from becoming a false sense of security or a merge-blocker on its own (a PR template cannot fail CI; only workflows can).

### 7.4 Handle not-yet-existing checkers gracefully

Several referenced tools do **not** exist yet (`check_public_api_contracts.py`, `check_viz_api_schema.py`, `check_prompts.py` are unbuilt Phase-8 deliverables — confirmed: `grep` for them across the repo returns nothing but planning docs). The template must therefore reference them as **conditional / "when available"** prose, never as a hard "you must have run X" precondition. Phrase item 2 as "…snapshot updated with justification" and mention the script name parenthetically, so the checklist is valid *today* (self-attestation) and stays valid once 049 wires the scripts into CI. Avoid dead links to files that do not exist.

### 7.5 English-only, no i18n mirror

The template is a single canonical English form. Do not create `docs/ja`/`docs/zh` counterparts and do not add it to any i18n parity list — the docs-sync i18n gates (`check_i18n_js.py`, `check_site_i18n.py`) scan `docs/` and the frontend i18n bundles, not `.github/`. Confirm this by reading `docs-sync.yml` before committing.

### 7.6 Classification of the change

**`KEEP`** (additive net-new). The template *guards* contracts; it changes none. It matches 012 §4's "**`KEEP`**-as-new, additive" classification and the master vocabulary. No `ADAPT`/`MERGE`/`MOVE_TO_LEGACY`/`DELETE_CANDIDATE` applies; the one `REVIEW_REQUIRED` sub-decision (whether to add a CONTRIBUTING cross-link line) is called out in §9.

---

## 8. Concrete Work Items

1. **Read 012 §4 and §9** and transcribe the eight checklist items (§2.2) with the *verified* real paths (`docs/reference/{cli_reference,mcp_tools,rest_api}.md`, `ari/viz/routes.py`+`api_*.py`, `services/api.ts`, `ari/prompts/<area>/<purpose>.md`, `ari-core/ari/migrations/`, the `refactor-guards.yml` `~/.ari/` guard).
2. **Author** `.github/PULL_REQUEST_TEMPLATE.md` per §7.2 — header (summary, subtask ID, classification with the master vocabulary), type-of-change, the 8-item contract checklist, and the test-evidence block referencing `python -m compileall .` / `pytest -q` / `ruff check .` (+ frontend `npm` commands).
3. **Add HTML-comment guidance** (§7.3) stating the checklist is advisory-to-humans and that items 2/4/7/8 are additionally CI-enforced; instruct authors to delete inapplicable sections.
4. **Reference, don't hard-require, unbuilt checkers** (§7.4): mention `check_public_api_contracts.py` / viz-schema checks as "when available"; do not create dead links.
5. **Cross-link** to `CONTRIBUTING.md` and `docs/refactoring/012_github_workflow_integration_plan.md §9` from within the template (comment or a "See also" line).
6. **Verify no parity gate trips:** run `python scripts/readme_sync.py --check` (confirm `.github/` needs no `## Contents` entry) and skim `docs-sync.yml`/`check_doc_sources.py` to confirm `.github/*.md` is out of their scan scope.
7. **Render check:** open a scratch draft PR (or use GitHub's preview) to confirm checkboxes render interactively and HTML comments are invisible; confirm the file auto-fills the compose box.
8. **(Optional, REVIEW_REQUIRED)** add a **single** cross-link line to `CONTRIBUTING.md` pointing readers to the new PR template — only if the maintainer wants the two documents linked. This is the one sanctioned edit outside `.github/PULL_REQUEST_TEMPLATE.md`; skip it if in doubt.
9. **Self-check:** `python -m compileall .`, `ruff check .`, `pytest -q` should all be unaffected (a markdown file changes no Python); run them to prove no regression (see §12).

---

## 9. Files Expected to Change

Created by the subtask **047 implementer** (later session), not by this planning doc:

- **`.github/PULL_REQUEST_TEMPLATE.md`** — **NEW** (the deliverable; the only required file).
- **`CONTRIBUTING.md`** — **CONDITIONAL, one line, REVIEW_REQUIRED**: an optional "See `.github/PULL_REQUEST_TEMPLATE.md` for the PR checklist" cross-link. No engineering-discipline content is moved or restated. Skip unless explicitly wanted.
- **`scripts/README.md` / any `## Contents` index** — **NOT expected**: `.github/` has no per-directory `README.md` with a `## Contents` index, so `scripts/readme_sync.py` should not require an entry. Confirm with `--check`; only touch if the gate unexpectedly flags it.

**Explicitly NOT changed:** any `ari-core/ari/**`, any `ari-skill-*/**`, any frontend file (`ari-core/ari/viz/frontend/**`), any `config/`/`configs/` YAML, any prompt template under `ari/prompts/**`, any `.github/workflows/*.yml` (all 5 untouched), `requirements*.txt`, `ari-core/pyproject.toml`, and the vendored `ari-skill-idea/vendor/virsci/**` templates.

---

## 10. Files / APIs That Must Not Be Broken

This subtask adds a *human-facing form*; it must perturb no contract and no automation:

- **All external contract surfaces** — CLI `ari` (`ari.cli:app`), `ari.public.*`, MCP tool contracts (14 `ari-skill-*/src/server.py`), dashboard API (`ari/viz/routes.py` + `api_*.py`, `services/api.ts`, `websocket.py`), checkpoint/output/config file formats, `ari-skill-* → ari-core` stable interfaces, README/docs usage — are **untouched** (the template only *names* them for author attestation).
- **The 5 existing workflows** — `docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`, `refactor-guards.yml` — remain byte-identical; adding a PR template is invisible to them (none scan `.github/*.md`; `pages.yml`'s path filter is `docs/**`,`report/**`,`README.md`).
- **`scripts/readme_sync.py` parity** — the new file must not break the per-directory README `## Contents` gate (verify `--check` stays green).
- **Existing PR behavior** — GitHub replaces the *empty default* compose body with the template; it does not block, auto-close, or alter any PR. Authors can still edit/delete template sections freely.

---

## 11. Compatibility Constraints

- **Additive only.** 047 introduces one markdown file (and optionally one CONTRIBUTING cross-link line); it removes/renames nothing. No compatibility adapter is required.
- **No behavior change to automation.** A PR template is consumed by GitHub's compose UI, not by any workflow, script, or the `ari` runtime. There is no schema, no import, no CLI, no API surface to keep stable.
- **Forward-compatible with the unbuilt CI gates.** By phrasing checker references as "when available" (§7.4), the template stays correct both before and after subtasks 049/048/046/etc. land — no rewrite needed when those checkers appear.
- **Determinism / P2:** the file is static text; it triggers no LLM call, no network, no nondeterminism (consistent with the ARI design-principle P2 and the `ari-skill-memory` "no LLM calls" precedent for tooling).
- **The vendored virsci PR template is unrelated** and must not be touched or merged with ARI's; the two do not interact.

---

## 12. Tests to Run

Run from `/home/t-kotama/workplace/ARI` after creating the file. Because the deliverable is a markdown file, the Python/lint gates should be *no-ops* — run them to prove no regression, not because the template contains code:

- **Compile / syntax:** `python -m compileall .` (must stay green; a `.md` adds no Python).
- **Test suite (regression):** `pytest -q` (respecting `pytest.ini`); and `scripts/run_all_tests.sh` for the per-skill suites. Expect no change — the template imports nothing.
- **Lint:** `ruff check .` (`ruff` is available; `radon` is not — do not rely on it). No Python changed, so no new findings should appear.
- **README-parity gate:** `python scripts/readme_sync.py --check` — confirm adding `.github/PULL_REQUEST_TEMPLATE.md` requires **no** `## Contents` entry (there is no `.github/README.md` index). Fix only if it unexpectedly flags.
- **Docs-sync sanity (read-only reasoning):** confirm `scripts/docs/check_doc_sources.py`, `check_i18n_js.py`, `check_site_i18n.py`, and `check_readme_parity.py` scan `docs/`/`report/`/frontend i18n only, so `.github/*.md` is out of scope (no i18n mirror expected).
- **Markdown lint (optional):** if a markdown linter is available, lint the template; otherwise a manual GitHub-preview render (interactive checkboxes visible; HTML comments hidden) is sufficient.
- **Frontend:** **N/A** — this subtask touches no frontend; do **not** run `npm test` / `npm run build`. (The `npm` commands appear only *inside* the template as author guidance for frontend PRs.)

---

## 13. Acceptance Criteria

1. `.github/PULL_REQUEST_TEMPLATE.md` exists and auto-fills the body of a newly opened PR (verified via GitHub preview/draft).
2. The template contains all **eight** contract-preservation checklist items from 012 §9 (§2.2), each with the correct verified path(s), rendered as interactive `- [ ]` checkboxes.
3. The template includes a header (summary + refactoring subtask ID + a classification line using `KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED`) and a test-evidence block referencing `python -m compileall .`, `pytest -q`, `ruff check .` (and the frontend `npm` commands for frontend PRs).
4. The template states, in an HTML comment, that the checklist is advisory-to-humans and that the machine-checkable items are additionally CI-enforced; instructions to delete inapplicable sections are present.
5. References to not-yet-existing checkers are phrased as "when available" with no dead links (§7.4).
6. It cross-links `CONTRIBUTING.md` and `docs/refactoring/012_github_workflow_integration_plan.md §9`.
7. No file outside `.github/PULL_REQUEST_TEMPLATE.md` (and, if chosen, one `CONTRIBUTING.md` cross-link line) is modified. `git status` shows no change under `ari-core/ari/`, `ari-skill-*/`, `ari-core/ari/viz/frontend/`, `config*/`, `.github/workflows/`, or the vendored `virsci` tree.
8. `python -m compileall .`, `pytest -q`, `ruff check .`, and `python scripts/readme_sync.py --check` all remain green (no regression).
9. Written in clear technical English; no i18n mirror created.

---

## 14. Rollback Plan

Trivial and self-contained — purely additive, non-runtime:

1. `git rm .github/PULL_REQUEST_TEMPLATE.md`.
2. If the optional cross-link line was added to `CONTRIBUTING.md`, revert that single line.
3. Confirm `git status` is otherwise clean and `python scripts/readme_sync.py --check` stays green.

Because the template is not wired into any workflow and adds no Python, removing it cannot break CI, the CLI, MCP servers, the dashboard, or any skill. GitHub simply reverts to an empty default PR body. There is nothing to migrate back.

---

## 15. Dependencies

Per the provided **DEPENDENCY GRAPH** (`045 -> 046, 047, 048, 049, 050, 051, 052`) and `007_subtask_index.md` row 94 (`depends-on 045`), **047's single hard predecessor is 045 `inventory_github_workflows`**. 045 is the Phase-9 inventory that establishes the current `.github/` surface (5 workflows, all absent templates) this template plugs into; it must land first so 047 builds on a verified inventory rather than re-deriving it.

- **Runtime-change gate does NOT apply.** The cross-cutting rule "the inventory subtasks (001, 002, 020, 036, 045, 053, 059, 060, 067) must precede any **runtime-code** change" gates *runtime* subtasks. 047 changes **no** runtime code, so that gate is not the constraint here — but 045 is still a direct hard predecessor via the dependency graph, so 047 waits on 045 regardless.
- **Sibling / soft coordination (not blocking):**
  - **046 `design_quality_ci_integration`** — designs the CI wiring; 047 hosts the human-facing checklist that 046's gates back. Author 047 consistent with 046's staged-rollout framing, but 046 does not block 047.
  - **048 `add_issue_templates_for_refactoring`** — the other net-new `.github/` intake form; same `depends-on 045`. Keep tone/structure consistent; independent otherwise.
  - **052 `add_dependabot_and_actions_policy`** — owns `dependabot.yml` + actions policy (and, REVIEW_REQUIRED, `CODEOWNERS`, the checklist's complementary reviewer-routing mechanism). 047 must **not** pre-empt 052's files.
- **Downstream / forward references (047 enables, do not do here):**
  - **049 `add_contract_check_workflows`** — turns the checklist's machine-checkable items (2/4/7/8) into enforced CI jobs; the template's "when available" phrasing (§7.4) is what lets those references go live without a template rewrite.
  - The Phase-8 checker subtasks (`check_public_api_contracts.py`, `check_viz_api_schema.py`, `check_prompts.py`, `check_directory_policy.py`, …) whose script names the checklist references conditionally.

---

## 16. Risk Level

**Low.**

- **Changes runtime code:** **No.** The subtask adds one markdown file under `.github/` (plus, optionally, one cross-link line in `CONTRIBUTING.md`). It imports nothing into `ari`, edits no `ari-core/ari/**` / `ari-skill-*/**` / frontend / config / prompt / `.github/workflows/**` file, and renames no directory.
- **Contract-relevant:** **Yes, but only as a human guard.** The template *reminds* authors about contract surfaces; it changes none and enforces nothing on its own (it cannot fail CI — only workflows can).
- **Residual risks (all minor):** (a) checklist wording could drift from 012 §9 — mitigated by transcribing the eight items verbatim (§2.2); (b) referencing an unbuilt checker as a hard requirement would create a dead link — mitigated by the "when available" phrasing (§7.4); (c) accidentally using the multi-template directory form would stop auto-fill — mitigated by using the single `.github/PULL_REQUEST_TEMPLATE.md` file (§7.1); (d) confusing the vendored `virsci` template for ARI's — mitigated by the explicit decoy note (§2.1/§5).

---

## 17. Notes for Implementer

- **Follow `007_subtask_index.md`, not 012 §15/§16, for what "047" is.** 047 is the **PR template** (`.github/PULL_REQUEST_TEMPLATE.md`); the *content* comes from 012 **§9** (and §4). 012's §15/§16 table renumbers subtasks locally (there "047" is `check_directory_policy.py` and templates are "052") — that is a different numbering, not your task. See the numbering note at the top.
- **Use the single default file, uppercase, in `.github/`.** `.github/PULL_REQUEST_TEMPLATE.md` auto-fills every PR. Do **not** use `.github/PULL_REQUEST_TEMPLATE/<name>.md` (that needs a `?template=` query string and won't auto-fill).
- **Transcribe the eight checklist items verbatim from 012 §9** with the verified real paths (all `docs/reference/*.md` targets exist; `ari/viz/routes.py`+`api_*.py`; `services/api.ts`; `ari/prompts/<area>/<purpose>.md`; `ari-core/ari/migrations/`; the `refactor-guards.yml` `~/.ari/` guard).
- **Advisory-to-humans, backed-by-CI.** State this explicitly (012 §9). A PR template cannot gate a merge; it is a self-attestation. The machine enforcement lives in workflows (existing `refactor-guards.yml`/`docs-sync.yml`/`readme-sync.yml`, plus the future Phase-8/subtask-049 gates).
- **Reference unbuilt checkers as "when available."** `check_public_api_contracts.py`, `check_viz_api_schema.py`, `check_prompts.py`, `check_directory_policy.py` do **not** exist yet — do not link to nonexistent files or imply they must have been run.
- **English only, no i18n mirror.** The docs i18n gates scan `docs/`/`report/`/frontend bundles, not `.github/`; do not create `docs/ja`/`docs/zh` copies or add the template to any parity list.
- **Ignore the vendored virsci template** at `ari-skill-idea/vendor/virsci/agentscope-main/.github/` — it is bundled third-party content, not ARI's, and GitHub does not read it for ARI PRs.
- **Keep it short and skimmable.** Mirror the concise, rule-per-bullet style of `CONTRIBUTING.md` §347–416 so authors actually read it; delete-if-N/A guidance keeps the rendered body from being noise on trivial PRs.
- **Reserve "deprecated" for external contracts.** In any comment inside the template, do not label internal code "deprecated"; that word is only for external contracts (public API, CLI, MCP, dashboard API, documented import paths, ari-skill stable interfaces).
- **Don't touch the 5 workflows.** Adding this template must be a no-op for `docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`, and `refactor-guards.yml`.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **047** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
