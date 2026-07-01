# 012 — GitHub Workflow Integration Plan

> Planning document (refactoring workstream). **Planning only — no runtime code, workflow, script, prompt, config, or frontend changes are made by this document.** It describes how the ARI refactoring quality gates should be wired into `.github/` on top of the five workflows that already exist, and how the proposed `scripts/check_*` checkers (subtasks 045–052) should be integrated **incrementally**, never as a wholesale replacement.
>
> Verified against the repository on planning date **2026-07-01** (git branch `main`, `ari-core` version `0.9.0`). Every path, line count, and workflow behavior below was read from the tree; where a component does not exist it is stated as "does not exist".

## 1. Purpose

The ARI refactoring effort adds a family of static-analysis and contract checkers under `scripts/` (see §6–§7). Those checkers are worthless unless they run automatically at PR time. This document specifies the **integration policy**: which checkers become CI jobs, in what order they are promoted from advisory to blocking, how they reuse the two proven diff-guard patterns already present in the repo, and which contract surfaces they must protect.

The plan is deliberately **additive**. The repository already has a mature, docs-oriented CI surface (5 workflows, 12 checker scripts wired in). Nothing here proposes rewriting those workflows. Instead it:

1. Inventories the current `.github/` surface and CI coverage (§2–§5).
2. Identifies the quality gates that are **absent** today (§6).
3. Defines a staged rollout policy so new gates land as warnings first and only escalate to hard failures once the tree is clean (§7–§8).
4. Specifies review-policy gates for the contract surfaces most at risk during a refactor: PR review checklist (§9), documentation enforcement (§10), prompts (§11), viz/dashboard API (§12), public API (§13), dashboard UX (§14).
5. Proposes the concrete workflow file layout (§15) and maps the work to refactoring subtasks 045–052 (§16).

Classification vocabulary used throughout: **KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED**.

Contract surfaces that must **not** be broken by any later implementation phase (this document only guards them, never proposes changing them): CLI `ari`, `ari.public.*`, MCP tool contracts (`ari-skill-*` servers), dashboard API endpoints/schema (`ari/viz/routes.py` + `api_*.py`), checkpoint/output/config file formats, `ari-skill-* → ari-core` stable interfaces, README/docs usage, and the scripts invoked by `.github/workflows/`.

## 2. Current `.github/` Structure

Verified with `find .github -type f`. The `.github/` directory contains **only** `workflows/`, with exactly five files:

```
.github/
└── workflows/
    ├── docs-change-coupling.yml    (58 lines)
    ├── docs-sync.yml               (91 lines)
    ├── pages.yml                   (64 lines)
    ├── readme-sync.yml             (28 lines)
    └── refactor-guards.yml         (105 lines)
```

**Confirmed ABSENT** (each checked directly; all "No such file or directory"):

| Component | Status | Consequence |
| --- | --- | --- |
| `.github/ISSUE_TEMPLATE/` | does not exist | No structured bug/feature/refactor intake |
| `.github/PULL_REQUEST_TEMPLATE.md` (and `pull_request_template.md`) | does not exist | No standard PR body; review checklist (§9) has nowhere to live |
| `.github/dependabot.yml` | does not exist | No automated dependency/security update PRs |
| `CODEOWNERS` (checked `.github/`, repo root, `docs/`) | does not exist | No automatic reviewer routing for contract-sensitive paths |
| `.github/actions/` (local composite actions) | does not exist | Every workflow re-declares checkout/setup steps inline; no shared setup |

There are **no scheduled/cron workflows, no reusable/called workflows, no matrix builds, and no local composite actions**. The only non-PR trigger is `pages.yml` (`push` to `main`, path-filtered). All quality gating is otherwise PR-time.

> Note on the "sonfigs" concern raised in the master prompt: **no `sonfigs/` directory exists anywhere in the repo.** It is a hypothesized typo and is called out here so no subtask targets a non-existent path. The real, confusable trio is `ari-core/ari/config/` (Python code that *locates* config files), `ari-core/ari/configs/` (packaged default DATA: `defaults.yaml`, `model_prices.yaml`), and top-level `ari-core/config/` (rubric/profile DATA). Any directory-policy checker (§6) must reference these three actual paths, not "sonfigs".

## 3. Current Workflows

All five workflows were read in full. Their behavior:

### 3.1 `refactor-guards.yml` (105 lines) — the key overlap candidate

- **Trigger:** `pull_request` to `main` **and** `refactoring`. This is the **only** workflow that targets the `refactoring` branch, so it is the natural host for refactoring-specific gates.
- **Job `no-home-ari-writes`:** installs deps (`requirements.txt`, editable `ari-skill-memory` then `ari-core`, plus `scipy numpy pandas pytest pytest-asyncio pytest-mock respx`), then runs `pytest ari-core/tests/ -q` under a redirected `HOME="$RUNNER_TEMP/fake_home"`, ignoring four tests (`test_letta_restart_live`, `test_letta_start_scripts`, `test_ollama_gpu`, `test_dashboard_html`). Fails if `$HOME/.ari` is created. Enforces the post-checkpoint-scoping invariant (no runtime writes to `~/.ari/`).
- **Job `no-new-home-ari-refs`:** `fetch-depth: 0`; computes `base=$(git merge-base origin/${{ github.base_ref || 'main' }} HEAD)`, then `git diff "$base" HEAD -- 'ari-core/ari/**.py'` with an explicit path-exclude allow-list of **14** sanctioned sites (`_deprecation.py`, `migrations/`, `core.py`, `paths.py`, `memory_cli.py`, `memory/auto_migrate.py`, `memory/file_client.py`, `publish/backends/ari_registry.py`, `clone/resolvers/ari.py`, `registry/__init__.py`, `viz/state.py`, `viz/api_settings.py`, `viz/api_publish.py`), greps added lines matching `Path\.home\(\).*\.ari|~/\.ari`, and excludes comment lines. Enforces: no *new* `~/.ari/` references outside the shim/deprecation allow-list.

This file is the single Python-source-touching workflow. It is **KEEP** — it must not be rewritten. It contributes two reusable idioms (see §7): (a) the merge-base diff guard, and (b) the path-exclude allow-list convention. It does **not** check public API, import boundaries, viz schema, complexity, or directory placement, so the proposed contract checkers do **not** overlap it functionally.

### 3.2 `docs-change-coupling.yml` (58 lines)

- **Trigger:** `pull_request` to `main`; `fetch-depth: 0`, Python 3.13, installs `pyyaml`.
- **Hard gate:** `scripts/docs/check_report_cochange.py --base-ref "${{ github.event.pull_request.base.sha }}"` — tri-language `report/{en,ja,zh}` paired-file co-change (`chapters/*.tex`, `strings.tex`, `main.tex` must move together; generated PDFs/`.bib`/`shared/` exempt). Fails CLOSED.
- **Advisory (`continue-on-error: true`):** `scripts/docs/check_ref_coupling.py --base-ref <base.sha>` — when a doc `sources:` file changes, its `last_verified` should bump.
- **Load-bearing detail:** the header comment (lines 41–47) explicitly documents that `github.event.pull_request.base.sha` is *preferred* over the `origin/<base_ref>` idiom in `refactor-guards.yml`, because `base.sha` is immutable for the run while a remote-tracking ref can move if the base branch advances mid-run. New workflows in §15 MUST adopt `base.sha`.

### 3.3 `docs-sync.yml` (91 lines) — two jobs

- **Trigger:** `pull_request` to `main`; `fetch-depth: 0`, Python 3.13, `pyyaml`.
- **Job `docs-sync` hard gates:** `check_doc_sources.py`; `check_i18n_js.py`; `check_site_i18n.py`; `check_doc_links.py --html-only`; `check_readme_parity.py`; `report/scripts/check_i18n.py` (Gate 6 tri-language structural parity).
- **Job `docs-sync` advisory (`continue-on-error: true`):** `check_translation_freshness.py`; `check_doc_links.py` (markdown mode).
- **Job `vitepress-build` (separate runner, Node 20, npm cache on `docs/package-lock.json`):** `bash scripts/docs/sync_report_pdf.sh --check` → `npm ci --prefix docs` → `npm run --prefix docs docs:build`. Enforces that the VitePress build succeeds and report PDFs are in sync before the Pages deploy.

### 3.4 `pages.yml` (64 lines)

- **Trigger:** `push` to `main` filtered to `paths: ['docs/**','report/**','README.md']`, plus `workflow_dispatch`. Permissions `pages: write`, `id-token: write`; `concurrency: pages`, `cancel-in-progress: false`.
- **Job `build`:** Node 20 → `sync_report_pdf.sh` (no `--check`; actually syncs) → `npm ci --prefix docs` → `docs:build` → `assemble_site.sh` (builds `_site/`: bespoke landing at root + VitePress at `/docs/`) → `configure-pages@v5` + `upload-pages-artifact@v3` (`path: _site`).
- **Job `deploy`** (`needs: build`): `actions/deploy-pages@v4` to `github-pages`. Only deploy workflow.
- **Observation (unconfirmed intent):** the path filter references `README.md` only, not `README.ja.md`/`README.zh.md`. Whether intentional is not confirmed; flagged for the docs-enforcement subtask, not for this integration plan to change.

### 3.5 `readme-sync.yml` (28 lines)

- **Trigger:** `pull_request` to `main`; Python 3.13, stdlib-only.
- **Single step:** `python scripts/readme_sync.py --check` — per-directory README `## Contents` indexes must match the filesystem (PATH structure only, not descriptions). Fixed locally via `--write`.

### 3.6 Coverage summary

- All quality gating today is **documentation/i18n/report-oriented** (5 of 6 PR jobs). Only `refactor-guards.yml` touches Python source, and only for the `~/.ari/` invariant plus a sandboxed pytest run.
- **No workflow runs `ruff`, `compileall`, import-boundary, complexity, public-API, viz-schema, prompt, or dashboard-UX checks.** None of the proposed checkers in §6 are represented in CI today.
- `scripts/run_all_tests.sh` (runs each skill's pytest in its own process; 13 hardcoded paths) is **not referenced by any workflow** — `refactor-guards.yml` runs its own inline `pytest ari-core/tests/` instead. This is a MERGE/ADAPT candidate for the test-integration subtask, noted in §15.

## 4. Current PR / Issue Templates

**There are none.** Verified absent (§2): `.github/PULL_REQUEST_TEMPLATE.md`, `.github/pull_request_template.md`, and `.github/ISSUE_TEMPLATE/`.

`CONTRIBUTING.md` (416 lines, repo root) documents repository structure and conventions (including the prompt-snapshot convention at lines 385–399: a template must load from `ari/prompts/<area>/<purpose>.md` and `sha256(inline_orig) == sha256(loaded_template)` is asserted before merge). It does **not** contain a PR checklist or issue intake form, and it is prose, not a GitHub-rendered template.

Implication: the Pull Request Review Checklist Policy (§9) and the review-policy gates (§10–§14) currently have **nowhere to be surfaced to authors** at PR-open time. Introducing `PULL_REQUEST_TEMPLATE.md` (classification: **KEEP-as-new**, additive) is a prerequisite for the checklist policy and is the lowest-risk item in this whole plan — it changes no code and no CI behavior.

## 5. Current CI Coverage

Consolidated matrix of what is enforced today. "Hard" = fails the PR; "Advisory" = `continue-on-error: true`.

| Concern | Enforced? | Where | Mode |
| --- | --- | --- | --- |
| Report tri-language co-change | Yes | `docs-change-coupling.yml` → `check_report_cochange.py` | Hard |
| Source→doc `last_verified` bump | Yes | `docs-change-coupling.yml` → `check_ref_coupling.py` | Advisory |
| Declared doc `sources:` resolve | Yes | `docs-sync.yml` → `check_doc_sources.py` | Hard |
| i18n JS key parity | Yes | `docs-sync.yml` → `check_i18n_js.py` | Hard |
| HTML-site i18n integrity | Yes | `docs-sync.yml` → `check_site_i18n.py` | Hard |
| HTML link integrity | Yes | `docs-sync.yml` → `check_doc_links.py --html-only` | Hard |
| Root README heading parity | Yes | `docs-sync.yml` → `check_readme_parity.py` | Hard |
| Report Gate 6 structural parity | Yes | `docs-sync.yml` → `report/scripts/check_i18n.py` | Hard |
| Translation freshness | Yes | `docs-sync.yml` → `check_translation_freshness.py` | Advisory |
| Markdown link integrity | Yes | `docs-sync.yml` → `check_doc_links.py` | Advisory |
| VitePress build + PDF sync | Yes | `docs-sync.yml` job `vitepress-build` | Hard |
| Per-dir README `## Contents` sync | Yes | `readme-sync.yml` → `readme_sync.py --check` | Hard |
| No new `~/.ari/` refs in core | Yes | `refactor-guards.yml` job `no-new-home-ari-refs` | Hard |
| No `~/.ari/` writes during pytest | Yes | `refactor-guards.yml` job `no-home-ari-writes` | Hard |
| **Python lint (`ruff`)** | **No** | — | — |
| **Import compiles (`compileall`)** | **No** | — | — |
| **Import boundaries (public API / core↔skill)** | **No** | — | — |
| **Complexity / LOC budget** | **No** | — | — |
| **`ari.public.*` contract regression** | **No** | — | — |
| **viz API ↔ frontend `services/api.ts` schema** | **No** | — | — |
| **MCP tool contract regression** | **No** | — | — |
| **Prompt externalization / inventory** | **Partial** | `report/scripts/check_prompt_snapshots.py` (Gate 10) — snapshot only | — |
| **Dashboard UX / React i18n parity** | **No** | — | — |
| **Dead code** | **No** | — | — |
| **Dependency updates (dependabot)** | **No** | — | — |

Tooling availability on the runners/dev boxes (verified): `ruff` **is** available (0.15.2), `radon` is **not** installed, `python -m compileall` / `pytest` are available, `node`+`npm` are available, **`pnpm` is not** used (`docs/` uses `npm ci` against `package-lock.json`). Any new checker must therefore avoid `radon` and `pnpm` as hard dependencies.

## 6. Missing Quality Gates

The refactoring workstream proposes eleven checker scripts. A `grep` over `*.py/*.sh/*.yml/*.md` confirms **none of the eleven names exist today** — all are net-new. Their overlap with existing coverage, which decides whether each becomes its own CI job or MERGEs into an existing gate:

| Proposed checker | Status vs existing | Integration verdict |
| --- | --- | --- |
| `check_complexity.py` | MISSING (no LOC/cyclomatic gate; `radon` not installed) | New job; must not depend on `radon` — use a stdlib AST/LOC counter |
| `check_import_boundaries.py` | MISSING; nearest analog is the `~/.ari/` diff-grep (a content ban, not an import graph) | New job; guards `ari.public` boundary + `core↔skill` direction |
| `check_docs_source_sync.py` | **OVERLAP** — already covered by `check_doc_sources.py` (forward) + `check_ref_coupling.py` (reverse) | **DELETE_CANDIDATE** unless it adds a genuinely new direction; do not duplicate |
| `check_directory_policy.py` | **PARTIAL OVERLAP** with `readme_sync.py` (README-lists-files). No placement/naming policy exists (`config/` vs `configs/` vs top-level `config/`) | New job for the placement/naming slice only; reuse `readme_sync.py` for the listing slice |
| `check_public_api_contracts.py` | MISSING; no gate/snapshot over `ari.public.*` | New job (§13) |
| `check_viz_api_schema.py` | MISSING; no gate coupling `viz/routes.py`+`api_*.py` to frontend `services/api.ts` | New job (§12) |
| `check_prompts.py` | **OVERLAP** on the snapshot slice — `report/scripts/check_prompt_snapshots.py` (Gate 10) already byte-verifies `ari-core/ari/prompts/**/*.md`. It does NOT inventory hardcoded inline prompts in `agent/loop.py`/`*/server.py` | New job for the **inline-prompt inventory** only (§11); MERGE the snapshot slice into Gate 10 |
| `check_dashboard_ux.py` | MISSING; only `check_i18n_js.py` exists (landing JS), not React `i18n/{en,ja,zh}.ts` | New job (§14) |
| `analyze_references.py` | MISSING as a code cross-reference analyzer; name collides conceptually with `check_ref_coupling.py` (doc↔source) but neither analyzes code refs | New analysis tool; feeds dead-code + import-boundary jobs, not a gate itself |
| `check_dead_code.py` | MISSING (no `vulture`; `ruff F401` available but unwired) | New job; can lean on `ruff --select F401` for the unused-import slice |
| `generate_quality_report.py` | MISSING; every checker already emits `--json`, but nothing aggregates them | New aggregation step; renders a single PR summary from the per-checker JSON |

Naming caution repeated: `check_docs_source_sync.py` is the only proposed name that **duplicates existing coverage in both directions**. The integration decision is to **not create it** unless subtask design proves a new invariant; the honest verdict is redundant-with-`check_doc_sources.py`+`check_ref_coupling.py`.

## 7. Integration Policy for `scripts/check_*`

### 7.1 Conventions every new checker inherits (KEEP)

The `scripts/docs/` checkers share a proven convention that new `scripts/check_*` files MUST follow, because CI, the pre-commit hook, and `generate_quality_report.py` all depend on it:

- `#!/usr/bin/env python3`, module docstring citing the design doc, `argparse` with a `--json` flag.
- `REPO_ROOT = Path(__file__).resolve().parents[N]` (docs checkers use `parents[2]`; a `scripts/check_*` at `scripts/` top level uses `parents[1]`).
- Pure stdlib where possible; **PyYAML** is the only sanctioned non-stdlib dependency already installed in the docs jobs. No `radon`, no `pnpm`.
- Exit `1` on error; **staged rollout** built in (a `--strict` or level flag that turns warnings into failures — this is how the docs checkers were promoted and is the mechanism §8 relies on).
- Deterministic, no LLM/network calls (aligns with design principle P2; `ari-skill-memory` and these gates are explicitly LLM-free).

### 7.2 Two reusable idioms from existing workflows

New diff-scoped checkers MUST reuse, not reinvent:

1. **Merge-base diff guard.** `refactor-guards.yml` proved `git diff <base> HEAD -- '<pathspec>'` with `':!<exclude>'` pathspecs. New checkers that only care about *changed* files (import boundaries, new-debt) use this.
2. **Path-exclude allow-list.** The 14-entry allow-list in `no-new-home-ari-refs` is the template for sanctioning known-legacy sites (e.g. `ari-core/ari/migrations/`, `_deprecation.py`) so a checker can be strict everywhere else.
3. **Base-ref selection.** Use `${{ github.event.pull_request.base.sha }}` (as `docs-change-coupling.yml`/`docs-sync.yml` do), **not** `origin/${{ github.base_ref }}` — the header of `docs-change-coupling.yml` (lines 41–47) documents why: `base.sha` is immutable for the run.

### 7.3 Where each new gate runs

- **`refactor-guards.yml` is the host for refactor-invariant gates** because it is the only workflow triggered on the `refactoring` branch. Import-boundary, directory-policy, complexity, dead-code, and new-debt checkers are ADAPT-into-`refactor-guards.yml` (as added jobs), not new top-level workflows, so refactoring branches get them before they reach `main`.
- **Contract-regression gates** (public API, viz schema, MCP) warrant a **new** dedicated workflow (`contracts.yml`, §15) because they must run on all PRs to `main`, and grouping them keeps the required-status-check list readable.
- **Aggregation** (`generate_quality_report.py`) runs last as a `needs:`-gated job that reads the per-job JSON artifacts and posts one PR comment.

### 7.4 Do-not-do list

- Do **not** rewrite or merge the five existing workflows. They are KEEP.
- Do **not** create `check_docs_source_sync.py` (redundant, §6).
- Do **not** add `radon` or `pnpm` to any job.
- Do **not** move the docs checkers; the docs jobs are stable.
- Do **not** promote any new gate straight to Hard — every new gate enters at the Stage 1 warning tier (§8).

## 8. Warning vs Failure Policy

New gates escalate through four stages. This mirrors how the docs checkers were rolled out (`check_ref_coupling.py`, `check_translation_freshness.py`, and markdown link checking all currently sit at the advisory tier via `continue-on-error: true`, awaiting promotion). The escalation is driven by each checker's `--strict`/level flag, not by editing many workflow lines.

| Stage | Scope | Mode | Rationale |
| --- | --- | --- | --- |
| **Stage 1 — warning-all** | Every new checker (`check_complexity`, `check_import_boundaries`, `check_directory_policy`, `check_public_api_contracts`, `check_viz_api_schema`, `check_prompts` inline slice, `check_dashboard_ux`, `check_dead_code`) | All **Advisory** (`continue-on-error: true`) | Surface the full existing debt without blocking any PR. Establishes a baseline snapshot for each gate. |
| **Stage 2 — import-boundary + public-API regression** | `check_import_boundaries.py`, `check_public_api_contracts.py` | **Hard** on *regressions only* (diff-scoped via §7.2 merge-base idiom); pre-existing violations stay Advisory | These two protect the load-bearing `ari.public.*` boundary and `core↔skill` direction. New violations must fail even while legacy ones are grandfathered. |
| **Stage 3 — dashboard / public-API / MCP breakage** | `check_viz_api_schema.py`, `check_public_api_contracts.py` (full), `check_prompts.py` (snapshot slice via Gate 10), MCP tool-contract check | **Hard** on any breakage of an external contract surface | Breaking the dashboard API (`viz/routes.py`↔`services/api.ts`), `ari.public.*`, or an MCP tool contract breaks downstream consumers; these become blocking once Stage 1/2 have driven the baseline to zero. |
| **Stage 4 — new-debt failures** | `check_complexity.py`, `check_directory_policy.py`, `check_dead_code.py` | **Hard** on *new debt only* (a changed file may not exceed its budget / add a placement violation / introduce dead code) | Ratchet: existing debt is allowed, but a PR may not add more. Uses the diff-scoped merge-base idiom so the whole tree is never re-litigated. |

Two invariants for this policy:

- **A gate never skips a stage.** It must spend real calendar time at Stage 1 (baseline) before it can be promoted, exactly as the docs advisory checks did.
- **Promotion is a one-line change** (flip `continue-on-error` off, or pass `--strict`), never a checker rewrite — so promotion PRs are trivially reviewable.

`generate_quality_report.py` renders, per gate, the current stage and the delta versus the base branch, so reviewers can see "3 new complexity violations (Stage 4 would block)" before a gate is actually promoted.

## 9. Pull Request Review Checklist Policy

Because `PULL_REQUEST_TEMPLATE.md` does not exist (§4), the checklist policy first requires creating that file (additive, no-code change). The template's checklist encodes the contract surfaces so authors self-attest before requesting review:

- [ ] CLI surface unchanged, or change is documented in `docs/reference/cli_reference.md` and root README CLI table (README lines ~318–328).
- [ ] `ari.public.*` unchanged, or `check_public_api_contracts.py` snapshot updated with justification (§13).
- [ ] MCP tool contracts (`ari-skill-*/src/server.py`) unchanged, or the skill's tool schema change is documented in `docs/reference/mcp_tools.md`.
- [ ] Dashboard API (`ari/viz/routes.py` + `api_*.py`) unchanged, or `services/api.ts` and `docs/reference/rest_api.md` updated in the same PR (§12).
- [ ] Checkpoint/config file formats unchanged, or a migration under `ari-core/ari/migrations/` is included.
- [ ] Prompt templates: any inline prompt moved to `ari/prompts/<area>/<purpose>.md` with the Gate 10 sha256 snapshot updated (§11, CONTRIBUTING.md §385–399).
- [ ] Docs `sources:` front-matter and per-directory README `## Contents` updated (already CI-enforced; §10).
- [ ] No new `~/.ari/` references outside the sanctioned allow-list (already CI-enforced by `refactor-guards.yml`).

The checklist is **advisory to humans**; the machine-checkable items are backed by the CI gates so the template never becomes the sole line of defense. A CODEOWNERS file (absent today, §2) is the complementary mechanism: routing `ari-core/ari/public/**`, `ari-core/ari/viz/**`, and `ari-skill-*/src/server.py` to designated reviewers is **REVIEW_REQUIRED** and proposed as part of subtask 052.

## 10. Documentation Update Enforcement

Documentation coupling is the **most mature** part of CI already (§5), so the policy here is mostly "reuse, do not duplicate":

- **KEEP** the existing forward+reverse doc-source coupling: `check_doc_sources.py` (declared `sources:` resolve) + `check_ref_coupling.py` (changed source bumps `last_verified`). This is why `check_docs_source_sync.py` is a DELETE_CANDIDATE (§6).
- **ADAPT (extend), not replace:** the refactor introduces new contract docs (`docs/reference/public_api.md`, `docs/reference/rest_api.md`, `docs/reference/mcp_tools.md`, `docs/reference/internal_boundaries.md`). The public-API and viz-schema gates (§12–§13) should additionally assert that a change to the *contract* forces a change to its *reference doc* — the same "must-change-together" pattern as `check_report_cochange.py`, applied to code↔doc instead of lang↔lang.
- **Known drift to hand to the docs subtask, not to fix here:** `docs/_archive/refactor_audit.md` is still linked from `docs/README.md` (TOC line 86, parity-matrix line 135) but the directory was removed; the broken links are only caught by the *advisory* markdown-link check, so they drift silently. And `reference/environment_variables.md:211` documents an `ARI_AGENT_ENV_PATH` fallback to `~/.ari/agent.env` that contradicts the same file's v0.5.0-removal note (line 19). Both are REVIEW_REQUIRED for the docs subtask; this integration plan only flags them.
- Enforcement stays at PR time (`docs-sync.yml`, `docs-change-coupling.yml`, `readme-sync.yml`). No new documentation workflow is needed; new code↔doc assertions attach to the contract jobs in `contracts.yml` (§15).

## 11. Prompt Change Review Policy

Prompts are **partially externalized** already: `ari-core/ari/prompts/` holds `.md` templates (agent/system, evaluator/{extract_metrics,peer_review}, orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,root_idea_selector}, pipeline/keyword_librarian, viz/{wizard_chat_goal,wizard_generate_config}) loaded via `_loader.py`, and `report/scripts/check_prompt_snapshots.py` (**Gate 10**) byte-verifies those snapshots. Skills carry their own prompts (`ari-skill-paper-re/src/prompts/`, `ari-skill-replicate/src/prompts/`).

Policy:

- **MERGE the snapshot slice into Gate 10.** Do **not** re-implement snapshot verification in `check_prompts.py`; call/extend the existing Gate 10 checker.
- **New scope for `check_prompts.py`:** inventory **hardcoded inline prompts** that still live in the large server/loop/pipeline files — `ari-skill-paper/src/server.py` (2956 LOC), `ari-skill-transform/src/server.py` (2465), `ari/agent/loop.py` (1630), `ari-skill-orchestrator/src/server.py` (1043), `ari-skill-evaluator/src/server.py` (983), `ari/pipeline/orchestrator.py` (913). This inventory is Stage 1 (warning-all) — it reports the externalization backlog, it does not block.
- **CONTRIBUTING.md §385–399** already codifies the sha256 assertion (`sha256(inline_orig) == sha256(loaded_template)` before merge). The PR checklist (§9) surfaces it; Gate 10 enforces it. `check_prompts.py` only adds the *discovery* half (finding un-externalized prompts), which is genuinely new.
- Determinism: the inline-prompt scan is a static string/AST heuristic — **no LLM calls** — consistent with P2.

## 12. Viz / Dashboard API Contract Review Policy

The dashboard is the largest untested contract surface: `ari/viz/routes.py` (1197 LOC) plus ~20 `api_*.py` modules (`api_experiment.py` 929, `api_paperbench.py` 813, and the rest) expose HTTP/SSE endpoints consumed by the React frontend through `ari/viz/frontend/src/services/api.ts` (863 LOC) and `websocket.py`. **No CI gate couples the two today** (§5).

Policy (`check_viz_api_schema.py`, new):

- Assert that the set of endpoint paths declared in `viz/routes.py` + `api_*.py` matches the set consumed by `services/api.ts`. A backend endpoint removed/renamed without a matching `services/api.ts` edit is a **Stage 3 Hard** failure (dashboard breakage).
- Assert co-change with `docs/reference/rest_api.md` (README REST endpoint table, lines ~285–302; port 8765 is the documented constant, consistent across README/quickstart/rest_api/viz — verified).
- Reuse the merge-base diff idiom (§7.2) so only PRs that touch `viz/` or `frontend/services/` pay the cost.
- **Contract preservation:** this gate exists to *protect* the dashboard API endpoints/schema, never to propose changing them. Any intentional endpoint change must ship the `services/api.ts` + `rest_api.md` update in the same PR (the "must-change-together" pattern from §10).
- Frontend hygiene note (REVIEW_REQUIRED, not this gate's job): `ari/viz/frontend/node_modules/` is committed to git — a vendored-deps tracking issue to be handled by a separate hygiene subtask.

## 13. Public API Compatibility Review Policy

`ari.public.*` is the **stable re-export layer for skills** (introduced v0.7.1): `ari-core/ari/public/` holds `claim_gate`, `config_schema`, `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context` (9 files). Skills and `docs/reference/public_api.md` depend on these names. **No gate or snapshot protects them today** (§5).

Policy (`check_public_api_contracts.py`, new):

- Maintain a checked-in **signature snapshot** of `ari.public.*` (public symbol names + signatures) under `scripts/` or a data file, regenerated with `--write` and verified with `--check`, mirroring the `readme_sync.py --check/--write` and Gate 10 snapshot patterns.
- **Stage 2:** new *regressions* (a removed/renamed public symbol) fail on diff; pre-existing surface is the baseline.
- **Stage 3:** any breaking change to `ari.public.*` fails Hard unless the PR includes a compatibility adapter (re-export shim) **and** updates `docs/reference/public_api.md` + `docs/reference/compatibility.md`.
- **Grounding correction:** `docs/reference` correctly declares sources `ari-core/ari/pipeline/verified_context.py` and `ari-core/ari/pipeline/claim_gate`. Note the master-prompt skeleton's placement of these under `ari/public/` is imprecise: `ari/public/verified_context.py` **does** exist, but `ari/public/claim_gate` as a standalone module was not separately verified here — the checker's symbol list must be generated from the actual package, not from the skeleton.
- MCP boundary: the same policy extends to `ari-skill-* → ari-core` stable interfaces and MCP tool schemas (`ari-skill-*/src/server.py` consumed via `ari/mcp/client.py`). A dedicated MCP tool-contract check is grouped with this job in `contracts.yml` (§15), also Stage 3.

## 14. Dashboard UX Review Policy

Only `check_i18n_js.py` exists, and it covers the **landing-page** JS (`docs/i18n/landing.{en,ja,zh}.js`) — **not** the React app's i18n (`ari/viz/frontend/src/i18n/{en,ja,zh}.ts`, ~444 lines each). The dashboard UX has no automated gate (§5).

Policy (`check_dashboard_ux.py`, new, Stage 1 warning-all):

- **React i18n key parity** across `src/i18n/{en,ja,zh}.ts` — the same key-set/duplicate-key invariant `check_i18n_js.py` enforces for landing JS, applied to the app locales. This is the highest-value UX check and the closest analog to existing tooling.
- **Component-size budget** for the oversized frontend files as a warning-only ratchet: `Results/resultSections.tsx` (1590 LOC), `Wizard/StepResources.tsx` (1160), `Settings/SettingsPage.tsx` (1049), `Workflow/WorkflowPage.tsx` (964), `Workflow/workflowNodes.tsx` (770). Shares the `check_complexity.py` LOC counter (§6) rather than a second implementation.
- **Test presence** advisory: flag new page-level components lacking a `__tests__/` sibling (existing examples: `PaperBench/__tests__/PaperBenchWizard.test`, `PaperImportDialog.test`).
- Stays advisory (Stage 1) indefinitely unless a subtask decides to promote React i18n parity to Stage 3 alongside the landing-JS gate. Uses `node`+`npm` only (no `pnpm`).

## 15. Proposed Workflow Structure

**Additive layout.** The five existing workflows are unchanged (KEEP). Two changes: extend `refactor-guards.yml` with refactor-invariant jobs, and add one new `contracts.yml` for external-contract regression gates. Optional additive `.github/` files fill the absent-template gaps.

```
.github/
├── PULL_REQUEST_TEMPLATE.md          ← NEW (additive; hosts §9 checklist)          [subtask 052]
├── ISSUE_TEMPLATE/                    ← NEW (additive; bug / feature / refactor)     [subtask 052]
├── dependabot.yml                     ← NEW (additive; pip + npm + actions)          [subtask 052]
├── CODEOWNERS                         ← NEW (additive; route public/, viz/, skills)  [subtask 052]
└── workflows/
    ├── docs-change-coupling.yml       ← KEEP (unchanged)
    ├── docs-sync.yml                  ← KEEP (unchanged)
    ├── pages.yml                      ← KEEP (unchanged)
    ├── readme-sync.yml                ← KEEP (unchanged)
    ├── refactor-guards.yml            ← ADAPT (append jobs; existing 2 jobs untouched)
    │     + job: import-boundaries      (check_import_boundaries.py)   Stage 1→2       [subtask 046]
    │     + job: directory-policy       (check_directory_policy.py)    Stage 1→4       [subtask 047]
    │     + job: complexity             (check_complexity.py)          Stage 1→4       [subtask 045]
    │     + job: dead-code              (check_dead_code.py, ruff F401) Stage 1→4       [subtask 045]
    │     + job: lint                   (ruff check, advisory)         Stage 1         [subtask 045]
    └── contracts.yml                  ← NEW (all PRs to main)
          job: public-api               (check_public_api_contracts.py) Stage 1→3      [subtask 048]
          job: viz-api-schema           (check_viz_api_schema.py)       Stage 1→3      [subtask 049]
          job: mcp-tool-contracts       (MCP schema check)              Stage 1→3      [subtask 048]
          job: prompts-inventory        (check_prompts.py inline slice) Stage 1        [subtask 050]
          job: dashboard-ux             (check_dashboard_ux.py)         Stage 1        [subtask 051]
          job: quality-report (needs: *) (generate_quality_report.py)   aggregation    [subtask 045]
```

Structural rules for the new/adapted jobs:

- **Base-ref:** `${{ github.event.pull_request.base.sha }}` everywhere a diff is needed (§7.2/§3.2), never `origin/<base_ref>`.
- **Fetch depth:** `fetch-depth: 0` for any diff-scoped job (matches `refactor-guards.yml`, `docs-change-coupling.yml`).
- **Runtime:** Python 3.13 + PyYAML (matches the docs jobs); `ruff` for lint/F401; `node 20` + `npm ci --prefix ari-core/ari/viz/frontend` for the dashboard-ux job (no `pnpm`, no `radon`).
- **JSON artifacts:** each checker runs with `--json` and uploads its result so `quality-report` can aggregate into a single PR comment.
- **Composite action opportunity:** the "checkout + setup-python 3.13 + pip install pyyaml" prelude is repeated across four workflows today. Extracting a `.github/actions/setup-python-checks` composite action is an optional MERGE (DRY) that reduces duplication without changing behavior — REVIEW_REQUIRED, low priority, deferred to a hygiene subtask.
- **`run_all_tests.sh` integration:** the untriggered `scripts/run_all_tests.sh` (per-skill pytest, 13 paths) is an ADAPT candidate — wire it into a new `contracts.yml` job or a matrix so skill-level tests run in CI, resolving the gap that `refactor-guards.yml` only tests `ari-core/tests/`. Deferred to the test-integration subtask, not this document.
- **No wholesale replacement:** nothing above deletes or merges an existing workflow file.

## 16. Related Subtasks

This integration plan coordinates with refactoring subtasks **045–052**. Note: `docs/refactoring/subtasks/` and `docs/refactoring/reports/` are currently **empty** (verified 2026-07-01) — the subtask numbers below are the planned work items this document feeds into, not yet-authored files. Each subtask owns the checker(s) and this document owns their CI wiring.

| Subtask | Owns | This plan requires from it | Stage target |
| --- | --- | --- | --- |
| **045** | `check_complexity.py`, `check_dead_code.py`, `generate_quality_report.py`, `ruff` lint wiring | stdlib LOC/AST complexity (no `radon`); `--json`; aggregation reads per-checker JSON | 1 → 4 |
| **046** | `check_import_boundaries.py` | `ari.public` boundary + `core↔skill` direction graph; merge-base diff scope | 1 → 2 |
| **047** | `check_directory_policy.py` | placement/naming policy for `config/` vs `configs/` vs top-level `config/` (the real trio; **no `sonfigs/`**); reuse `readme_sync.py` for the listing slice | 1 → 4 |
| **048** | `check_public_api_contracts.py`, MCP tool-contract check | signature snapshot of `ari.public.*` + MCP tool schemas; `--check`/`--write` | 1 → 3 |
| **049** | `check_viz_api_schema.py` | endpoint parity `viz/routes.py`+`api_*.py` ↔ `services/api.ts`; co-change with `rest_api.md` | 1 → 3 |
| **050** | `check_prompts.py` (inline-inventory slice) | MERGE snapshot slice into Gate 10; new inline-prompt discovery over large server/loop files | 1 |
| **051** | `check_dashboard_ux.py` | React i18n `{en,ja,zh}.ts` parity + component-size budget; `node`+`npm` only | 1 |
| **052** | `.github/` templates: `PULL_REQUEST_TEMPLATE.md`, `ISSUE_TEMPLATE/`, `dependabot.yml`, `CODEOWNERS` | additive files hosting §9 checklist + reviewer routing; no code change | n/a |

Explicitly **out of scope** for this document (deferred, REVIEW_REQUIRED): `analyze_references.py` (feeds 045/046, not a standalone gate); the `check_docs_source_sync.py` DELETE_CANDIDATE (redundant, §6/§10); frontend `node_modules/` de-vendoring (§12); `run_all_tests.sh` CI wiring (§15); the `docs/_archive/` and `ARI_AGENT_ENV_PATH` documentation-drift items (§10) which belong to the docs subtask.

---

**Summary of guarantees.** This plan is additive and staged. It keeps all five existing workflows, reuses the two proven diff-guard idioms from `refactor-guards.yml`, prefers `base.sha` over `origin/<base_ref>`, avoids `radon`/`pnpm`, does not create the redundant `check_docs_source_sync.py`, and promotes every new gate warning-first through Stages 1→4. No external contract (CLI `ari`, `ari.public.*`, MCP tools, dashboard API, checkpoint/config formats, `ari-skill-*→ari-core` interfaces, README/docs usage, workflow-invoked scripts) is proposed for a breaking change here; each is instead given a CI gate that *protects* it.

## Retirement Condition

This is a **program-level planning document**, not a per-subtask artifact. It
stays live for the duration of the refactoring program and may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources — never on assumption:

1. Every subtask this document governs is marked **DONE** in
   `docs/refactoring/007_subtask_index.md`, **or** this document has been
   explicitly **superseded** by a named replacement (the superseding document
   must reference this file by name).
2. Any conclusions worth keeping have been folded into the permanent
   documentation / architecture.

Before any `git rm`, re-read this document's own conditions and check each one
against the current repository. See the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
