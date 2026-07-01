# Subtask 050: Add Docs Sync Workflow

- **Subtask ID:** 050
- **Phase:** Phase 9 — GitHub Integration
- **Canonical name (from `007_subtask_index.md` row 97):** `add_docs_sync_workflow` ("Docs-sync workflow additions")
- **Classification:** `ADAPT` (extend the existing `.github/workflows/docs-sync.yml`; do **not** create a second, duplicate docs workflow)
- **Changes runtime code:** **No** (see Section 16 — this subtask only edits `.github/workflows/*.yml` and, at most, adds an *advisory* step calling an already-owned checker script; no `ari-core`/`ari-skill-*` Python, no frontend, no prompts, no configs)
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`)

> **Planning-phase notice.** This document is a plan for a *future* coding session. Authoring *this* plan changes no runtime code, workflow, script, prompt, config, or frontend file — the only artifact produced by writing this document is this `.md` itself. When the described work item (050) is later *executed*, it edits `.github/workflows/docs-sync.yml` (and possibly `pages.yml`) additively; it must not rewrite the five existing workflows wholesale and must not create the redundant `check_docs_source_sync.py` (that decision is owned by subtask 027).

> **Numbering-discrepancy note (read before you start).** The canonical subtask index `007_subtask_index.md` (row 97 and the Phase 9 narrative, line 356) names **050 = `add_docs_sync_workflow`** = "Docs-sync workflow additions". The master GitHub-integration plan `012_github_workflow_integration_plan.md` §16 (line 330) and §15 (line 304) *mis-attribute* 050 to `check_prompts.py` / "prompts-inventory"; that is an internal inconsistency in 012, not the intent for this subtask. The `check_prompts.py` prompt-change work is subtask **051** (`add_prompt_change_review_workflow`). **This document follows the canonical index and the task assignment: 050 is the docs-sync workflow subtask.** Flag the 012 discrepancy for correction when 012 is next revised (out of scope here).

---

## 1. Goal

Extend the repository's **existing** documentation CI so that the documentation/i18n/report-parity invariants that matter *during and after the refactor* are gated on every PR — **without adding a second, overlapping docs workflow** and **without duplicating any check that `docs-sync.yml`, `docs-change-coupling.yml`, or `readme-sync.yml` already runs**.

Concretely, subtask 050 delivers a small, additive set of edits to `.github/workflows/docs-sync.yml` (the one workflow whose remit is documentation *content* sync) that:

1. **Resolve the `docs/refactoring/**` planning-tree interaction with `check_doc_sources.py`** so that the refactoring planning docs (this very file and its ~50 siblings) do not silently degrade the checker's coverage signal, and so a future promotion to `--require-all` is safe.
2. **Prepare the advisory→hard promotion path** for the two checks that are advisory today only because of *known, documented* markdown-tree drift owned by other subtasks (`check_doc_links.py` markdown mode; `check_translation_freshness.py`), so those gates flip to hard the moment the drift is cleared.
3. **Wire the outcome of subtask 027** (`check_docs_source_sync.py`) into this workflow **only if** subtask 027 lands its "Outcome A" (a genuinely new invariant). If 027 lands its DELETE_CANDIDATE outcome, this subtask records "no step added" and adds nothing.

The overarching verdict is **ADAPT**: the docs-sync workflow already exists and is the most mature CI surface in the repo; 050 extends it, it does not replace it.

## 2. Background

CI in this repo is almost entirely documentation/i18n-oriented. There are exactly **five** workflows under `.github/workflows/` (line counts verified): `docs-change-coupling.yml` (58), `docs-sync.yml` (91), `pages.yml` (64), `readme-sync.yml` (28), `refactor-guards.yml` (105). Of these, only `refactor-guards.yml` touches Python source (the `~/.ari/` invariant + a pytest-under-sandbox run). Confirmed **absent** today (each checked directly): `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/dependabot.yml`, `CODEOWNERS`, `.github/actions/`.

`docs-sync.yml` (91 lines) is the workflow this subtask owns. It has **two jobs**, both triggered on `pull_request` to `main`:

- **Job `docs-sync`** — `fetch-depth: 0`, Python 3.13, installs only PyYAML. Runs six **hard** gates (fail the PR):
  - `scripts/docs/check_doc_sources.py` (223 lines) — every live doc's front-matter `sources[].path` resolves.
  - `scripts/docs/check_i18n_js.py` (119) — landing/docs i18n JS key-set parity.
  - `scripts/docs/check_site_i18n.py` (206) — HTML-site i18n integrity (orphan `t-`ids, en→ja/zh co-change, version single-source).
  - `scripts/docs/check_doc_links.py --html-only` (147) — every href/src in `docs/*.html` resolves.
  - `scripts/docs/check_readme_parity.py` (122) — root `README.{md,ja,zh}` share one heading shape.
  - `report/scripts/check_i18n.py` (124) — report `{en,ja,zh}` structural parity (Gate 6).
  - and two **advisory** (`continue-on-error: true`) steps: `check_translation_freshness.py` (175) and `check_doc_links.py` (markdown mode, no `--html-only`).
- **Job `vitepress-build`** — separate runner, Node 20, npm cache keyed on `docs/package-lock.json`. Runs `scripts/docs/sync_report_pdf.sh --check` → `npm ci --prefix docs` → `npm run --prefix docs docs:build`. Hard-gates that the VitePress build succeeds and the triple report PDFs are in sync before the Pages deploy.

The master GitHub-integration design already exists at `docs/refactoring/012_github_workflow_integration_plan.md`. Its §10 ("Documentation Update Enforcement", lines 224–231) states the operative policy verbatim: **"Enforcement stays at PR time (`docs-sync.yml`, `docs-change-coupling.yml`, `readme-sync.yml`). No new documentation workflow is needed; new code↔doc assertions attach to the contract jobs in `contracts.yml`."** That single sentence draws this subtask's scope boundary: **050 tightens the docs workflow that already exists; it does not build code↔doc contract coupling (that is subtask 049's `contracts.yml`).**

Two documented drift items sit in the docs tree today and are the *reason* two checks are advisory-only:

- **`docs/_archive/` is missing but still linked.** Verified: `ls docs/_archive` → "No such file or directory", yet `docs/README.md` links `_archive/refactor_audit.md` at **lines 86 and 135** (and mentions `_archive/` at lines 5, 20). VitePress `srcExclude: '**/_archive/**'` and `check_doc_sources.py`'s `EXEMPT_DIR_SEGMENTS = ("_archive", "node_modules", ".vitepress")` keep the hard gates green; the broken markdown links are only caught by `check_doc_links.py` **markdown mode**, which is advisory → silent drift. Fixing the links is owned by **subtask 017** (`update_docs_and_examples`).
- **`reference/environment_variables.md:211`** documents an `ARI_AGENT_ENV_PATH` fallback to `~/.ari/agent.env` that contradicts the same file's v0.5.0-removal note (line 19). Also owned by **subtask 017**; this subtask only observes it.

Both are **REVIEW_REQUIRED** for the docs subtask; 050 must not fix them, but must sequence its advisory→hard promotions *after* they are fixed.

## 3. Scope

**In scope (this subtask):**

- Additive edits to `.github/workflows/docs-sync.yml`: at most one new advisory step, plus a `--require-all`-readiness change gated on the planning-tree exemption below.
- Deciding and implementing how `docs/refactoring/**/*.md` (planning workspace) interacts with `check_doc_sources.py` — either (a) add an exemption segment, or (b) leave it as non-failing "coverage"-level and explicitly forbid `--require-all` until it is handled. **This is a workflow/checker-config decision, not a change to the checker's public CLI contract** (see Section 10).
- Recording the promotion sequencing for `check_doc_links.py` (markdown) and `check_translation_freshness.py` from advisory to hard, contingent on subtask 017.
- Conditionally wiring subtask 027's checker as an advisory step, per 027's outcome.
- A REVIEW_REQUIRED note on the `pages.yml` path filter (`['docs/**','report/**','README.md']`) omitting `README.ja.md`/`README.zh.md`.

**Out of scope (owned elsewhere — do not do here):**

- Any code↔doc contract-coupling gate for `docs/reference/public_api.md`, `rest_api.md`, `mcp_tools.md`, `internal_boundaries.md` → owned by **subtask 049** (`add_contract_check_workflows`, `contracts.yml`). See 012 §10 line 229/231 and §12–§13.
- Creating `check_docs_source_sync.py` → its create/merge/delete decision is **subtask 027**; do not pre-empt it.
- Fixing the `docs/_archive` links or the `ARI_AGENT_ENV_PATH` note → **subtask 017**.
- Any `.github/` template files (`PULL_REQUEST_TEMPLATE.md`, `ISSUE_TEMPLATE/`, `dependabot.yml`, `CODEOWNERS`) → subtasks 047/048/052.
- The `refactor-guards.yml`, `docs-change-coupling.yml`, `readme-sync.yml`, and `pages.yml` *jobs* themselves (except the single `pages.yml` path-filter note) — do not rewrite them.
- Installing new tooling (`radon`, `vulture`, `pnpm`) or editing `requirements*.txt` / `ari-core/pyproject.toml`.

## 4. Non-Goals

- **Not** a new standalone documentation workflow file. 012 §10 line 231 is explicit that none is needed; adding one would duplicate `docs-sync.yml`'s trigger and jobs.
- **Not** a code↔doc "must-change-together" gate — that pattern (mirroring `check_report_cochange.py`) is applied to the contract reference docs by subtask 049, not here.
- **Not** a rewrite or reordering of the existing six hard gates in `docs-sync.yml`. They are green today and protect real invariants.
- **Not** a change to any checker script's behavior or CLI. If a new invariant is truly needed, it is owned by 027 (docs-source-sync) or 049 (contracts), not by this workflow subtask.
- **Not** a change to the `vitepress-build` job's build command, Node version, or PDF-sync step.
- **Not** an unconditional promotion of the two advisory checks — promotion is *sequenced after* subtask 017 clears the drift; doing it now would break every open PR.

## 5. Current Files / Directories to Inspect

Workflow (the file this subtask edits):

- `/home/t-kotama/workplace/ARI/.github/workflows/docs-sync.yml` — 91 lines; two jobs `docs-sync` + `vitepress-build`.

Adjacent workflows (read for pattern reuse; do **not** edit except the `pages.yml` note):

- `/home/t-kotama/workplace/ARI/.github/workflows/docs-change-coupling.yml` — 58 lines; source of the preferred `${{ github.event.pull_request.base.sha }}` diff idiom (header lines 41–47).
- `/home/t-kotama/workplace/ARI/.github/workflows/pages.yml` — 64 lines; path filter line 21 = `['docs/**', 'report/**', 'README.md']`.
- `/home/t-kotama/workplace/ARI/.github/workflows/readme-sync.yml` — 28 lines.
- `/home/t-kotama/workplace/ARI/.github/workflows/refactor-guards.yml` — 105 lines; the `git merge-base origin/<base_ref>` idiom (inferior; do not copy the ref choice).

Checker scripts invoked by (or candidates for) this workflow:

- `/home/t-kotama/workplace/ARI/scripts/docs/check_doc_sources.py` — 223 lines. **Critical to inspect:** it enumerates docs via `docs_dir.rglob("*.md")` (line 172); `EXEMPT_FILES` (lines 51–57) and `EXEMPT_DIR_SEGMENTS = ("_archive", "node_modules", ".vitepress")` (line 60); default missing-front-matter finding is level `"coverage"` (non-failing), promoted to `"error"` only under `--require-all` (lines 111–117, 184–188).
- `/home/t-kotama/workplace/ARI/scripts/docs/check_doc_links.py` — 147 lines; `--html-only` skips `check_markdown()` (lines 127, 131–132).
- `/home/t-kotama/workplace/ARI/scripts/docs/check_translation_freshness.py` — 175 lines.
- `/home/t-kotama/workplace/ARI/scripts/docs/check_ref_coupling.py` — 182 lines (reverse coupling; run by `docs-change-coupling.yml`, not this workflow — context only).
- `/home/t-kotama/workplace/ARI/scripts/docs/README.md` — the checker-family index.

Drift evidence (read-only, owned by subtask 017):

- `/home/t-kotama/workplace/ARI/docs/README.md` — lines 5, 20, 86, 135 reference the missing `docs/_archive/`.
- `/home/t-kotama/workplace/ARI/docs/reference/environment_variables.md` — line 211 (`ARI_AGENT_ENV_PATH` fallback) vs line 19 (v0.5.0 removal).

Planning-tree interaction target:

- `/home/t-kotama/workplace/ARI/docs/refactoring/` — `000_master_refactoring_plan.md`, `001`–`014` reports, and `subtasks/*.md` (all start with `# Subtask …`, i.e. **no `sources:` front-matter**; confirmed for `001_measure_complexity_and_dependencies.md` and `000_master_refactoring_plan.md`). None are in `EXEMPT_FILES` or `EXEMPT_DIR_SEGMENTS`.

Cross-referenced planning docs:

- `/home/t-kotama/workplace/ARI/docs/refactoring/012_github_workflow_integration_plan.md` — §10 (lines 224–231) draws the scope boundary.
- `/home/t-kotama/workplace/ARI/docs/refactoring/007_subtask_index.md` — row 97 + Phase 9 narrative (lines 339–359).
- `/home/t-kotama/workplace/ARI/docs/refactoring/subtasks/027_add_docs_source_sync_checker_script.md` — the checker whose outcome may add one advisory step here.
- `/home/t-kotama/workplace/ARI/docs/refactoring/subtasks/032_add_quality_script_ci_plan.md` — the CI-wiring plan (subtask 032).

## 6. Current Problems

1. **Planning-tree coverage leak (confirmed).** `check_doc_sources.py` scans `docs/**/*.md` via `rglob`, and `docs/refactoring/` is **not** exempt. Every planning `.md` (this file included) has no `sources:` front-matter, so each produces a `"coverage"`-level finding. Today that is non-failing (default mode), so the hard gate stays green — but it (a) pollutes the coverage report with ~65 intentional non-docs, and (b) makes any future `--require-all` promotion of `check_doc_sources.py` **fail hard on the entire planning workspace**. The ground-truth "interaction … under `--require-all` is unconfirmed" is now **confirmed**: it would flip these to `"error"`.
2. **Two invariants stuck advisory by unrelated drift.** `check_doc_links.py` markdown mode and `check_translation_freshness.py` are advisory *only* because of the documented `docs/_archive` broken links and the docs-expansion `last_verified` backlog. As written, the workflow header (lines 21–26) says they "warn for now and can be promoted once that backlog is cleared" — but there is no recorded promotion trigger tied to the owning subtask (017), so the promotion may never happen.
3. **`pages.yml` path filter may under-trigger on translated READMEs.** Line 21 filters `push` to `README.md` only; edits to `README.ja.md`/`README.zh.md` do not trigger a Pages rebuild. Whether intentional is **unconfirmed** (ground-truth flagged this). Root READMEs are not part of the VitePress `srcDir`, so the practical impact is limited, but it is a real asymmetry to record.
4. **Risk of duplication.** The subtask title ("Add Docs Sync Workflow") reads like "create a workflow"; the actual correct action is **extend the existing one**. A fresh session could wrongly author a second workflow that re-runs the same six checkers — exactly the anti-pattern 012 §10 forbids.

## 7. Proposed Design / Policy

**Verdict: ADAPT `docs-sync.yml`. Do not create a new workflow.** Three additive, low-risk changes, each independently revertable:

### 7.1 Resolve the planning-tree interaction (enables safe `--require-all` later)

Pick **one** of two equivalent-safety options; **Option A is recommended** (least surprising, mirrors the existing exemption mechanism):

- **Option A (recommended) — exempt the planning tree in the checker's data, not its logic.** Add `"refactoring"` to `EXEMPT_DIR_SEGMENTS` in `check_doc_sources.py` (line 60), matching the existing `_archive`/`node_modules`/`.vitepress` pattern. This is a **one-line data edit to a script already owned by the docs-checker family**, and it is segment-matched so `docs/refactoring/...` (and any future locale mirror) is covered. **Caveat:** this technically edits a `scripts/` file, not just the workflow — see Section 10 for why it is contract-safe (the checker's CLI/exit-code contract is unchanged; only the exempt set grows). If the reviewing session wants to keep 050 strictly workflow-only, use Option B.
- **Option B (workflow-only) — never pass `--require-all`, and document why.** Leave the checker untouched; add a comment in `docs-sync.yml` next to the `check_doc_sources.py` step recording that `--require-all` must **not** be enabled until the `docs/refactoring/**` tree is exempted (Option A) or given front-matter. This keeps 050 to a pure `.github/` edit (Changes-runtime-code: No, unambiguously) at the cost of leaving the coverage report noisy.

Whichever is chosen, the **default-mode invocation stays exactly as today** (`python scripts/docs/check_doc_sources.py`, no flag) so no currently-green PR changes status.

### 7.2 Record the advisory→hard promotion triggers (sequenced, not executed now)

Do **not** flip the two advisory steps in this subtask. Instead, encode the trigger in the workflow header comment so the promotion is a mechanical follow-up:

- `check_doc_links.py` (markdown) → promote to **hard** (drop `continue-on-error: true`, or merge into the `--html-only` step by dropping the flag) **only after subtask 017 fixes the `docs/_archive/refactor_audit.md` links in `docs/{,, ja/, zh/}README.md`** (lines 86, 135 + locale mirrors). Verify locally with `python scripts/docs/check_doc_links.py` returning 0 before flipping.
- `check_translation_freshness.py` → promote to hard **only after the docs-expansion `last_verified` backlog is cleared** (also 017's remit). Until then it stays advisory.

The promotion itself is a trivial YAML edit; making it a *documented, gated* follow-up (rather than doing it blind) is the deliverable.

### 7.3 Conditionally wire subtask 027's checker

- **If subtask 027 lands Outcome A** (ships `scripts/check_docs_source_sync.py` covering the one distinct trunk-state-staleness dimension), add it as an **advisory** step (`continue-on-error: true`) in the `docs-sync` job, invoked with the merge-base idiom `--base-ref "${{ github.event.pull_request.base.sha }}"` if it is diff-scoped (per 012 §7 and `docs-change-coupling.yml`'s documented preference over `origin/<base_ref>`).
- **If subtask 027 lands its DELETE_CANDIDATE outcome**, add **nothing**; record in this subtask's completion note that the step was intentionally omitted because the invariant is already covered by `check_doc_sources.py` (forward) + `check_ref_coupling.py` (reverse).

### 7.4 `pages.yml` path-filter note (REVIEW_REQUIRED, do not silently change)

Record the `README.ja.md`/`README.zh.md` omission (line 21) as a REVIEW_REQUIRED item. **Do not** change it as part of 050 without confirming intent; if a maintainer confirms it should trigger rebuilds, the one-line fix is `paths: ['docs/**', 'report/**', 'README.md', 'README.ja.md', 'README.zh.md']`. Left as a note because `pages.yml` is the sole deploy workflow and changing its trigger is higher-blast-radius than the `docs-sync` edits.

### 7.5 Idiom discipline

Any new diff-scoped step must use `${{ github.event.pull_request.base.sha }}` (immutable for the run; reachable in the fetched history), **not** `refactor-guards.yml`'s `origin/${{ github.base_ref }}` (can move mid-run). `docs-sync.yml`'s `docs-sync` job already sets `fetch-depth: 0`, so no checkout change is needed for a merge-base step.

## 8. Concrete Work Items

1. **Decide 7.1 Option A vs B** and apply it:
   - Option A: add `"refactoring"` to `EXEMPT_DIR_SEGMENTS` in `scripts/docs/check_doc_sources.py` line 60; add a one-line comment referencing this subtask.
   - Option B: add an explanatory comment in `docs-sync.yml` next to the `check_doc_sources.py` step; make no script change.
2. **Add the sequencing comments** to the `docs-sync.yml` header (or inline at the two advisory steps) recording the 7.2 promotion triggers and their owning subtask (017). No behavior change.
3. **Gate on subtask 027 (7.3):** if 027 shipped Outcome A, add one advisory step calling `scripts/check_docs_source_sync.py` (diff-scoped via `base.sha` if applicable); otherwise add nothing and note the omission.
4. **Add the 7.4 REVIEW_REQUIRED note** about `pages.yml`'s README locale filter — as a comment or in this subtask's completion record; do **not** change `pages.yml` behavior without maintainer confirmation.
5. **Validate** per Section 12: `python -m compileall .`, `ruff check scripts/docs/check_doc_sources.py` (if Option A touched it), run every `docs-sync`-invoked checker locally with the repo clean and confirm each still exits 0, and validate the edited YAML parses (e.g. `python -c "import yaml,sys;yaml.safe_load(open('.github/workflows/docs-sync.yml'))"`).
6. **Confirm no duplication:** grep the final `.github/workflows/` to prove there is still exactly one docs-content workflow and that no checker is invoked in two hard steps.

## 9. Files Expected to Change

Primary (always):

- `/home/t-kotama/workplace/ARI/.github/workflows/docs-sync.yml` — additive: header/inline promotion-trigger comments; conditionally one advisory step (7.3); conditionally an Option-B comment (7.1).

Conditional (only if the corresponding option/outcome is chosen):

- `/home/t-kotama/workplace/ARI/scripts/docs/check_doc_sources.py` — **only under 7.1 Option A**: one-line addition of `"refactoring"` to `EXEMPT_DIR_SEGMENTS` (line 60) + a comment. Not touched under Option B.

Explicitly **not** changed by this subtask:

- `/home/t-kotama/workplace/ARI/.github/workflows/pages.yml` — behavior unchanged (7.4 is a note only, unless a maintainer confirms the filter fix separately).
- `docs-change-coupling.yml`, `readme-sync.yml`, `refactor-guards.yml` — untouched.
- Any `ari-core/ari/**`, `ari-skill-*/**`, `docs/**/*.md` content, `report/**`, or frontend file.
- `scripts/check_docs_source_sync.py` — created (or not) by subtask 027, never by 050.

## 10. Files / APIs That Must Not Be Broken

- **The five existing workflows' contracts.** `docs-sync.yml`'s two jobs, their six hard gates, and the `vitepress-build` build must keep passing on a clean `main`. The edits are additive; no existing step is removed or reordered.
- **Scripts invoked by `.github/workflows/`** are a protected contract surface. Under 7.1 Option A, `check_doc_sources.py`'s **CLI, exit codes, `--require-all`/`--json` flags, and finding levels stay identical**; only the exempt-directory *set* grows (a superset change that can only reduce findings, never add a failure). This is the same class of edit as the existing `EXEMPT_DIR_SEGMENTS` entries and does not break `docs-sync.yml`, `readme_sync.py` consumers, or local usage documented in `scripts/docs/README.md`.
- **Root README triples** (`README.md`/`README.ja.md`/`README.zh.md`) and their `check_readme_parity.py` heading-shape gate — untouched.
- **The docs `sources:` front-matter contract** — untouched; 7.1 only changes which files are *exempt from requiring* it, never the schema.
- **Pages deploy** (`pages.yml` → `github-pages`) — untouched (7.4 is note-only).

No external contract (CLI `ari`, `ari.public.*`, MCP tool schemas, dashboard API endpoints/schema, checkpoint/config formats, `ari-skill-* → ari-core` interfaces) is anywhere near this subtask's blast radius; it is confined to CI docs gating.

## 11. Compatibility Constraints

- **Additive-only.** Every change must be revertable to the current `docs-sync.yml` by deleting the added lines; no green PR may flip to red as a result of this subtask (the two advisory checks stay advisory until 017 clears the drift).
- **No new dependencies.** The `docs-sync` job installs only PyYAML; keep it that way. No `radon`/`vulture`/`pnpm`; no `requirements*.txt` or `pyproject.toml` edits.
- **`base.sha`, not `origin/<base_ref>`.** Any diff-scoped step reuses `${{ github.event.pull_request.base.sha }}` (per `docs-change-coupling.yml` header lines 41–47).
- **Do not create a second docs workflow** (012 §10 line 231). One docs-content workflow only.
- **Contract-doc coupling stays in subtask 049's `contracts.yml`**, not here — respect the 012 §10/§12/§13 boundary so the two subtasks do not both try to own code↔doc gates.
- **Do not pre-empt subtask 027** — the `check_docs_source_sync.py` create/merge/delete decision is 027's; 050 only *wires* whatever 027 produces.

## 12. Tests to Run

From the repo root (`/home/t-kotama/workplace/ARI`):

- `python -m compileall .` — byte-compile sanity (relevant if 7.1 Option A edits `check_doc_sources.py`).
- `ruff check .` — lint (repo has ruff available; `radon` is not installed and must not be required). At minimum `ruff check scripts/docs/check_doc_sources.py` if Option A was taken.
- `pytest -q` — full suite; must stay green (no runtime code changed). Note the `refactor-guards.yml` CI ignores four env-specific tests (`test_letta_restart_live`, `test_letta_start_scripts`, `test_ollama_gpu`, `test_dashboard_html`); local runs may skip those too.
- **Workflow-specific validation (the substance of this subtask):**
  - YAML parse: `python -c "import yaml; yaml.safe_load(open('.github/workflows/docs-sync.yml'))"`.
  - Re-run every checker the `docs-sync` job invokes and confirm each exits 0 on a clean tree: `python scripts/docs/check_doc_sources.py`; `python scripts/docs/check_i18n_js.py`; `python scripts/docs/check_site_i18n.py`; `python scripts/docs/check_doc_links.py --html-only`; `python scripts/docs/check_readme_parity.py`; `python report/scripts/check_i18n.py`.
  - Confirm the advisory checks' *current* status is unchanged: `python scripts/docs/check_doc_links.py` (markdown; expected to still report the `_archive` drift until 017) and `python scripts/docs/check_translation_freshness.py`.
- **Not applicable:** `npm test` / `npm run build`. This is not a frontend subtask; the `vitepress-build` job's `npm run --prefix docs docs:build` is unchanged and need not be re-exercised locally unless the `vitepress-build` job is touched (it is not).

## 13. Acceptance Criteria

1. `.github/workflows/` still contains exactly **five** workflows; **no** new docs workflow file was created.
2. `docs-sync.yml`'s six hard gates and the `vitepress-build` job are unchanged in behavior and still pass on a clean `main`.
3. The `docs/refactoring/**` planning-tree interaction is resolved by exactly one of 7.1 Option A (checker `EXEMPT_DIR_SEGMENTS` includes `"refactoring"`, verified by re-running the checker and seeing no `docs/refactoring/*` coverage findings) or 7.1 Option B (a comment forbidding `--require-all` until the tree is handled). The default-mode invocation is byte-identical to before.
4. The advisory→hard promotion triggers for `check_doc_links.py` (markdown) and `check_translation_freshness.py` are documented in the workflow, each naming subtask 017 as the blocking prerequisite; **neither check was promoted in this subtask.**
5. Subtask 027's outcome is honored: an advisory `check_docs_source_sync.py` step exists **iff** 027 shipped Outcome A; otherwise no such step exists and the omission is recorded.
6. The `pages.yml` README-locale path-filter asymmetry is recorded as a REVIEW_REQUIRED note; `pages.yml` behavior is unchanged.
7. `python -m compileall .`, `ruff check .` (or the scoped file), and `pytest -q` pass; the edited YAML parses; every `docs-sync` checker still exits 0 on a clean tree.
8. `git diff` is confined to `.github/workflows/docs-sync.yml` (and, under Option A only, `scripts/docs/check_doc_sources.py`). No other file changed.

## 14. Rollback Plan

Every change is additive and independently revertable:

- **Workflow edits:** `git checkout .github/workflows/docs-sync.yml` restores the 91-line original. The added advisory step (if any) and comments are contiguous, deletable lines.
- **7.1 Option A script edit:** removing `"refactoring"` from `EXEMPT_DIR_SEGMENTS` (one line) reverts `check_doc_sources.py` to its 223-line original; because the change only *grew* the exempt set, reverting can only *add back* previously-silenced coverage findings — it cannot turn a green hard gate red.
- **Subtask 027 step:** if 027 is later reverted, delete the single advisory step; nothing else depends on it (it is `continue-on-error: true`).
- No data migration, no checkpoint/config format touched, so rollback is a pure `git revert` of this subtask's commit with zero runtime impact.

## 15. Dependencies

Per the authoritative dependency graph (`045 -> 046, 047, 048, 049, 050, 051, 052`):

- **Hard predecessor:** **045** (`inventory_github_workflows`) — 050 cannot start until the five existing workflows are inventoried and classified. 045 is one of the nine inventory subtasks that must precede any runtime-adjacent change (`001, 002, 020, 036, 045, 053, 059, 060, 067`).
- **Coordination / soft dependencies (not edges in the graph, but must be respected):**
  - **032** (`add_quality_script_ci_plan`) — the CI-wiring plan; 050 realizes the docs-workflow slice of it.
  - **027** (`add_docs_source_sync_checker_script`) — its Outcome A/DELETE decision determines whether 7.3 adds a step. 050 must run *after* 027 resolves, or be re-touched when 027 lands.
  - **017** (`update_docs_and_examples`) — must clear the `docs/_archive` links and the `ARI_AGENT_ENV_PATH` note *before* the 7.2 advisory→hard promotions can execute (which are themselves a follow-up, not part of 050).
  - **049** (`add_contract_check_workflows`) — owns `contracts.yml` and all code↔doc contract coupling; 050 must not encroach on that boundary.
- **Successors:** none in the graph depend on 050; it is a leaf under 045.

## 16. Risk Level

**Low.** Rationale:

- **Changes runtime code: No.** The primary artifact is a `.github/workflows/*.yml` edit (CI configuration, not shipped runtime code). The one conditional script touch (7.1 Option A) is a single-line, superset-only edit to the exempt set of a docs checker — it changes no runtime behavior of `ari-core`/`ari-skill-*`, no import, no prompt, no config format, no frontend. If a session prefers zero script edits, 7.1 Option B keeps this subtask *entirely* within `.github/`.
- The edits are additive and revertable (Section 14); the two advisory checks stay advisory, so no open PR flips red.
- Blast radius is confined to docs CI gating; no external contract surface is within reach.
- The only non-trivial judgment calls (Option A vs B; whether 027 shipped Outcome A; the `pages.yml` filter) are all recorded as explicit, reversible decisions with safe defaults.

## 17. Notes for Implementer

- **Read `012_github_workflow_integration_plan.md` §10 (lines 224–231) first.** It is the binding scope statement: docs enforcement stays in the *existing* three PR-time workflows; no new docs workflow; code↔doc contract coupling belongs to `contracts.yml` (049). If you find yourself authoring a new `.yml` for docs, stop — that is the wrong path.
- **The title says "Add" but the correct verb is "Extend."** There is already a `docs-sync.yml`. Verify with `ls .github/workflows/` before doing anything.
- **Confirm the numbering discrepancy noted at the top** with a maintainer if 012 is being revised in parallel: 012 §16/§15 mis-attribute 050 to `check_prompts.py`; the canonical index (`007_subtask_index.md` row 97 + line 356) and this task assignment say 050 = `add_docs_sync_workflow`. Prompt-change review is subtask **051**.
- **Prefer 7.1 Option A** unless the review policy for this batch mandates zero `scripts/` edits — the checker already has the exact `EXEMPT_DIR_SEGMENTS` mechanism, and using it is cleaner than a "never pass `--require-all`" comment that a future editor may not see.
- **Do not flip the advisory checks in this subtask.** They are advisory for a documented reason (subtask 017's drift). Promoting them now would fail every open PR against the `docs/_archive` links. Encode the trigger; let 017 land; the flip is a one-line follow-up.
- **Diff-scoped steps use `base.sha`.** The `docs-sync` job already has `fetch-depth: 0`, so a merge-base step needs no checkout change — but only add one if subtask 027 actually ships a diff-scoped checker.
- **When done, grep to prove no duplication:** confirm no checker script name appears in two *hard* steps across `.github/workflows/`, and that `docs-sync.yml` is still the only docs-content workflow.
- The `docs/refactoring/` tree is a **planning workspace, not part of the published VitePress IA** (not a Diátaxis category, excluded from the sidebar). That is precisely why exempting it from `check_doc_sources.py` is correct, not a loss of coverage.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **050** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
