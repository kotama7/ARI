# Subtask 046: Design Quality-CI Integration

> Planning/design document (refactoring workstream, **Phase 9: GitHub Integration**).
> **Planning only — this subtask writes no runtime code, workflow, script, prompt, config, or frontend file.** Its deliverable is the authoritative *integration design* that later subtasks (047–052, plus the Phase-8/other checker-owning subtasks) execute against.
> Verified against the repository on planning date **2026-07-01** (git branch `main`, `ari-core` version `0.9.0`). Every path, line count, and workflow behavior below was read from the tree; where a component does not exist it is stated as "does not exist".

## 1. Goal

Produce a single, authoritative **Quality-CI Integration Design** so that the CI-plumbing subtasks (047–052) and the checker-owning subtasks (025–031, 043, 054, 055, 058, 073) can be implemented without re-litigating *where* each quality checker runs, *how* it is promoted from advisory to blocking, and *which contract surfaces* it protects. Concretely the design must:

1. Map every proposed `scripts/check_*` / `generate_quality_report.py` checker to a **host workflow + job name + rollout stage**, using the *actual* checker-owner subtask numbers from `007_subtask_index.md` (not the draft numbers in `012_github_workflow_integration_plan.md` §15 — see §6.4 for the reconciliation).
2. Fix the **staged rollout policy** (Stage 1 warning-all → Stage 4 new-debt-fails) as the single source of truth every gate inherits, driven by a `--strict`/level flag rather than per-workflow rewrites.
3. Standardize the **diff idioms** every new gate reuses: the merge-base diff guard and the path-exclude allow-list already proven in `refactor-guards.yml`, and the `github.event.pull_request.base.sha` base-ref preference already proven in `docs-change-coupling.yml`.
4. Define the **`--json` artifact + aggregation contract** so `generate_quality_report.py` (subtask 031) can render one PR comment from every gate's output.
5. Enumerate the **contract surfaces the design protects and must never propose breaking**: CLI `ari`, `ari.public.*`, MCP tool contracts, dashboard API, checkpoint/config formats, `ari-skill-* → ari-core` interfaces, README/docs usage, and the scripts invoked by `.github/workflows/`.

The deliverable is **this `.md` file**. There is no code change in subtask 046. Classification vocabulary used throughout: **KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED**.

## 2. Background

The ARI refactoring workstream adds a family of static-analysis and contract checkers under `scripts/`. Today **none of them run in CI**: all quality gating is documentation/i18n/report-oriented, and the only Python-source-touching workflow (`refactor-guards.yml`) checks a single invariant (no `~/.ari/` writes/refs) plus a sandboxed `pytest`. A checker that never runs at PR time is worthless, so the Phase-9 GitHub-integration cluster (045–052) exists to wire the checkers into `.github/`.

Within that cluster the work splits into three tiers:

- **045 `inventory_github_workflows`** (dependency of this subtask) — inventories the current `.github/` surface: five workflows, twelve wired checker scripts, and the confirmed-absent templates. Its facts are the input to this design.
- **046 `design_quality_ci_integration`** (this subtask) — the *design/glue*: it decides host workflow, job, and stage for each checker, and freezes the shared idioms and the aggregation contract. Runtime code change: **No**.
- **047–052** — the *implementers*: PR template (047), issue templates (048), contract-check workflow(s) (049), docs-sync workflow additions (050), prompt-change review workflow (051), dependabot + actions/CODEOWNERS policy (052). Each depends on 045; each is implemented against this design.

The phase-level plan `docs/refactoring/012_github_workflow_integration_plan.md` (339 lines) already sketches this integration at the phase altitude. Subtask 046 is the *hand-off-ready* per-subtask design derived from it; subtask **032 `add_quality_script_ci_plan`** is a closely related sibling ("Quality-script CI integration plan", index row 79) — §6.5 notes how 046 and 032 divide labor to avoid duplication.

## 3. Scope

**In scope (design decisions this document freezes):**

- The checker → host-workflow → job → stage mapping table (§7.2).
- The four-stage rollout policy and its promotion mechanism (§7.3).
- The shared CI idioms new gates must reuse: merge-base diff, path-exclude allow-list, `base.sha` base-ref, `fetch-depth: 0` (§7.4).
- The runtime/tooling constraints every gate must satisfy: Python 3.13 + PyYAML, `ruff` 0.15.2, `node`+`npm`; **no `radon`, no `pnpm`** (§7.5).
- The `--json` output + aggregation contract feeding `generate_quality_report.py` (§7.6).
- The required-status-check evolution and contract-preservation guardrails (§7.7–§7.8).
- The reconciliation of the conflicting subtask numbering between `007_subtask_index.md` and `012_...plan.md` §15 (§6.4).

**Out of scope (owned by other subtasks; only referenced here):**

- Writing/modifying any `.github/workflows/*.yml`, `.github/` template, `dependabot.yml`, or `CODEOWNERS` — owned by 049/050/051/052 and 047/048.
- Authoring any `scripts/check_*.py` / `generate_quality_report.py` — owned by 025–031, 043, 054, 055, 058, 073.
- The `check_docs_source_sync.py` redundancy decision at the checker level (owned by 027; this design only records it as **DELETE_CANDIDATE** for CI-wiring purposes).
- Frontend `node_modules/` de-vendoring, `run_all_tests.sh` CI wiring, and the `docs/_archive/` / `ARI_AGENT_ENV_PATH` doc-drift items — all REVIEW_REQUIRED, deferred (see §6.3, §10).

## 4. Non-Goals

- **Not** rewriting or merging any of the five existing workflows. They are **KEEP**.
- **Not** promoting any new gate straight to blocking — every gate enters at Stage 1 (advisory).
- **Not** introducing `radon` or `pnpm` as a CI dependency.
- **Not** changing any external contract (CLI `ari`, `ari.public.*`, MCP tools, dashboard API/schema, checkpoint/config formats, `ari-skill-*→ari-core` interfaces, README/docs usage). This design only *guards* those surfaces; it never proposes breaking them, and any future breaking change must ship a compatibility adapter.
- **Not** creating a scheduled/cron, reusable/called, or matrix workflow in this subtask (a composite-action DRY opportunity is noted as REVIEW_REQUIRED only, §7.8).
- **Not** the word "deprecated" for any internal code; that term is reserved for external contracts.

## 5. Current Files / Directories to Inspect

All read-only in this subtask. Line counts verified via `wc -l` on 2026-07-01.

**Existing CI surface (`.github/workflows/`):**

| Path | LOC | Role / relevance to this design |
| --- | --- | --- |
| `.github/workflows/refactor-guards.yml` | 105 | **Only** Python-source-touching workflow; triggers on `main` **and** `refactoring`. Source of the two reusable idioms (merge-base diff, 14-entry path-exclude allow-list). Proposed **ADAPT host** for refactor-invariant gates. |
| `.github/workflows/docs-change-coupling.yml` | 58 | Uses `--base-ref "${{ github.event.pull_request.base.sha }}"`; header (lines 41–47) documents why `base.sha` beats `origin/<base_ref>`. Template for base-ref idiom. |
| `.github/workflows/docs-sync.yml` | 91 | Runs six doc checkers (hard) + two advisory; `vitepress-build` job (Node 20, `npm ci --prefix docs`). Template for advisory (`continue-on-error: true`) tier. |
| `.github/workflows/pages.yml` | 64 | Only non-PR trigger (`push` to `main`, path-filtered); the sole deploy workflow. KEEP, untouched. |
| `.github/workflows/readme-sync.yml` | 28 | `python scripts/readme_sync.py --check`; the `--check`/`--write` snapshot pattern this design reuses for contract snapshots. |

**Confirmed ABSENT** (each checked directly; all "No such file or directory"):

| Component | Status | Implementer subtask |
| --- | --- | --- |
| `.github/PULL_REQUEST_TEMPLATE.md` (and `pull_request_template.md`) | does not exist | 047 |
| `.github/ISSUE_TEMPLATE/` | does not exist | 048 |
| `.github/dependabot.yml` | does not exist | 052 |
| `CODEOWNERS` (checked `.github/`, repo root, `docs/`) | does not exist | 052 |
| `.github/actions/` (local composite actions) | does not exist | REVIEW_REQUIRED (§7.8) |

**Existing quality tooling this design wires or reuses:**

| Path | LOC | Role |
| --- | --- | --- |
| `scripts/readme_sync.py` | 350 | `--check`/`--write` per-dir README snapshot; already gated by `readme-sync.yml`. Pattern reused by contract snapshots. |
| `scripts/docs/check_report_cochange.py` | 113 | Hard diff-gate; the "must-change-together" pattern reused for code↔doc coupling. |
| `scripts/docs/check_ref_coupling.py` | 182 | Advisory diff-gate (`--base-ref`, `--strict`); template for staged rollout. |
| `report/scripts/check_prompt_snapshots.py` | 93 | **Gate 10** — byte-verifies `ari-core/ari/prompts/**/*.md` snapshots. `check_prompts.py` (043) **MERGE**s its snapshot slice here, does not duplicate. |
| `scripts/run_all_tests.sh` | 78 | Per-skill `pytest` (13 hardcoded paths); **not referenced by any workflow** — ADAPT candidate, deferred (§10). |

**Checker scripts this design assigns to CI (all net-new; owned by other subtasks — verified none exist under `scripts/` today):** `check_complexity.py` (025), `check_import_boundaries.py` (026), `check_docs_source_sync.py` (027, redundant), `check_directory_policy.py` (028), `check_public_api_contracts.py` (029), `check_viz_api_schema.py` (030), `generate_quality_report.py` (031), `check_prompts.py` (043), `analyze_references.py` (054), `check_dead_code.py` (055), dashboard-UX regression checks / React-i18n parity (073), dashboard build+CI (066).

**Contract-surface roots the design protects (read-only, cited for the gates):** `ari-core/ari/public/` (9 modules: `claim_gate.py`, `config_schema.py`, `container.py`, `cost_tracker.py`, `llm.py`, `paths.py`, `run_env.py`, `verified_context.py`, `__init__.py`), `ari-core/ari/viz/routes.py` (1197) + `ari/viz/api_*.py`, `ari-core/ari/viz/frontend/src/services/api.ts` (863), `ari-skill-*/src/server.py` consumed via `ari-core/ari/mcp/client.py`.

## 6. Current Problems

### 6.1 No Python-quality gate exists in CI

None of the eleven-plus proposed checkers is represented in any workflow. `ruff` is available on the runners (0.15.2) but **no workflow invokes it**; `python -m compileall` is likewise unused. The only source-touching gate is the `~/.ari/` invariant in `refactor-guards.yml`. Result: import-boundary, complexity, public-API, viz-schema, prompt-inventory, dead-code, and dashboard-UX regressions can all merge undetected.

### 6.2 No home for the review-policy surfaces

`PULL_REQUEST_TEMPLATE.md`, `ISSUE_TEMPLATE/`, `dependabot.yml`, and `CODEOWNERS` all **do not exist**. The machine-checkable half of the review policy (the CI gates) has nowhere to be surfaced to authors, and there is no automatic reviewer routing for contract-sensitive paths (`ari/public/**`, `ari/viz/**`, `ari-skill-*/src/server.py`).

### 6.3 Overlap/redundancy that CI wiring must respect

- `check_docs_source_sync.py` (027) **duplicates** existing coverage in *both* directions — `check_doc_sources.py` (forward) + `check_ref_coupling.py` (reverse). CI wiring verdict: **DELETE_CANDIDATE** — do not add a workflow job for it unless subtask 027 proves a genuinely new invariant.
- The snapshot slice of `check_prompts.py` (043) **OVERLAPS** `report/scripts/check_prompt_snapshots.py` (Gate 10). CI wiring verdict: **MERGE** into Gate 10; only the *inline-prompt inventory* slice is new and gets its own advisory job.
- `check_directory_policy.py` (028) **PARTIALLY OVERLAPS** `readme_sync.py` (already gated). Only the placement/naming slice (`ari-core/ari/config/` code vs `ari-core/ari/configs/` packaged data vs top-level `ari-core/config/` rubric data) is new. **No `sonfigs/` directory exists** — the design must never target that non-existent path.

### 6.4 Conflicting subtask numbering between the phase plan and the index

`012_github_workflow_integration_plan.md` §15 (lines 285–306) brackets checker scripts against subtask numbers that **conflict with the authoritative `007_subtask_index.md`**. Examples: §15 writes `check_import_boundaries.py [subtask 046]` and `check_complexity.py [subtask 045]`, but the index assigns `check_import_boundaries.py` → **026**, `check_complexity.py` → **025**, and **046** → the *design* (this document), **045** → the *workflow inventory*. **The index (007) is authoritative.** This design uses the index numbers everywhere and treats §15's bracketed numbers as a stale draft to be ignored. Fixing §15 itself is a docs-hygiene item for the plan's owner, not this subtask.

### 6.5 Relationship to sibling subtask 032

Index row 79 defines **032 `add_quality_script_ci_plan`** ("Quality-script CI integration plan", dependency `—`, tier "Yes" = precedes runtime). It covers the same territory as this design. Division of labor: **032** is the *plan* (rationale, tier ordering, which checkers become jobs at all) and can start immediately (no predecessor); **046** is the *design* that additionally consumes 045's concrete `.github/` inventory to fix host-workflow/job/stage assignments and the shared idioms. Where they touch, 046 defers to 032 on *whether* a checker is wired and owns *where/how* it is wired. Neither should silently restate the other; cross-reference instead.

### 6.6 Base-ref idiom drift risk

`refactor-guards.yml` uses `git merge-base origin/${{ github.base_ref || 'main' }} HEAD`; `docs-change-coupling.yml`/`docs-sync.yml` use `${{ github.event.pull_request.base.sha }}`. The header of `docs-change-coupling.yml` (lines 41–47) explicitly critiques the `origin/<base_ref>` idiom as inferior because the remote-tracking ref can move mid-run while `base.sha` is immutable. Without a frozen decision, new gates would copy whichever neighbor they were pasted from. This design mandates `base.sha` (§7.4).

## 7. Proposed Design / Policy

The design is deliberately **additive and staged**. It keeps all five existing workflows, reuses the two proven diff idioms, prefers `base.sha`, avoids `radon`/`pnpm`, and promotes every new gate warning-first.

### 7.1 Two-host topology

- **`refactor-guards.yml` — ADAPT (append jobs; the existing two jobs are untouched).** It is the only workflow triggered on the `refactoring` branch, so refactor-*invariant* gates belong here to catch regressions before they reach `main`. Assigned jobs: `lint`, `import-boundaries`, `directory-policy`, `complexity`, `dead-code`.
- **`contracts.yml` — NEW (created by subtask 049; runs on all PRs to `main`).** External-*contract*-regression gates belong here, grouped so the required-status-check list stays readable. Assigned jobs: `public-api`, `mcp-tool-contracts`, `viz-api-schema`, `prompts-inventory`, `dashboard-ux`, and a terminal `quality-report` aggregation job (`needs:` all of the above).
- **`docs-sync.yml` — ADAPT/extend (subtask 050), not replace.** New code↔doc "must-change-together" assertions (e.g. a `viz` endpoint change forcing a `docs/reference/rest_api.md` edit) attach to the contract jobs, not to a new docs workflow. The redundant `check_docs_source_sync.py` (027) is **not** wired.
- **Five existing workflows stay KEEP.** No file among them is deleted or merged.

### 7.2 Canonical checker → host → job → stage mapping

Subtask numbers are the authoritative `007_subtask_index.md` values (see §6.4). "Owner" = the subtask that writes the checker; "Wiring" = the Phase-9 subtask that adds the workflow/job.

| Checker (owner subtask) | Host workflow (wiring subtask) | Job name | Rollout stage path |
| --- | --- | --- | --- |
| `ruff check` lint (wiring: 032/049) | `refactor-guards.yml` (ADAPT) | `lint` | Stage 1 (advisory, stays) |
| `check_complexity.py` (025) | `refactor-guards.yml` (ADAPT) | `complexity` | Stage 1 → 4 (new-debt fails) |
| `check_import_boundaries.py` (026) | `refactor-guards.yml` (ADAPT) | `import-boundaries` | Stage 1 → 2 (regression fails) |
| `check_directory_policy.py` (028) | `refactor-guards.yml` (ADAPT) | `directory-policy` | Stage 1 → 4 |
| `check_dead_code.py` (055) + `analyze_references.py` (054) | `refactor-guards.yml` (ADAPT) | `dead-code` | Stage 1 → 4 |
| `check_public_api_contracts.py` (029) | `contracts.yml` (NEW, 049) | `public-api` | Stage 1 → 2 → 3 |
| MCP tool-contract check (029 scope) | `contracts.yml` (NEW, 049) | `mcp-tool-contracts` | Stage 1 → 3 |
| `check_viz_api_schema.py` (030) | `contracts.yml` (NEW, 049) | `viz-api-schema` | Stage 1 → 3 |
| `check_prompts.py` inline-inventory slice (043) | `contracts.yml` (NEW, 051) | `prompts-inventory` | Stage 1 (advisory, stays) |
| `check_prompts.py` snapshot slice (043) | **MERGE into Gate 10** — `report/scripts/check_prompt_snapshots.py` (already gated) | (existing) | already Hard |
| dashboard-UX / React-i18n parity (073) + build (066) | `contracts.yml` (NEW, 051) | `dashboard-ux` | Stage 1 (advisory, stays) |
| `generate_quality_report.py` (031) + dead-code section (058) | `contracts.yml` (NEW, 049) | `quality-report` (`needs: *`) | aggregation, non-gating |
| `check_docs_source_sync.py` (027) | **NOT wired** (redundant, §6.3) | — | DELETE_CANDIDATE |

### 7.3 Four-stage rollout policy (single source of truth)

Every gate inherits this escalation. Promotion is a **one-line change** — flip `continue-on-error` off, or pass `--strict` — never a checker rewrite. A gate **never skips a stage** and must spend real calendar time at Stage 1 to establish a baseline, exactly as the docs advisory checks (`check_ref_coupling.py`, `check_translation_freshness.py`, markdown link check) still sit today.

| Stage | Scope | Mode | Rationale |
| --- | --- | --- | --- |
| **1 — warning-all** | Every new gate (`complexity`, `import-boundaries`, `directory-policy`, `public-api`, `viz-api-schema`, `prompts-inventory`, `dashboard-ux`, `dead-code`, `lint`) | All **Advisory** (`continue-on-error: true`) | Surface the full existing debt without blocking any PR; snapshot a baseline. |
| **2 — regression-only** | `import-boundaries`, `public-api` | **Hard** on regressions only (diff-scoped via §7.4); pre-existing violations grandfathered | Protect the load-bearing `ari.public.*` boundary and `core↔skill` direction; new violations fail while legacy ones are allowed. |
| **3 — external-contract breakage** | `public-api` (full), `viz-api-schema`, `mcp-tool-contracts`, prompt snapshot slice (via Gate 10) | **Hard** on any break of an external contract surface | Breaking the dashboard API, `ari.public.*`, or an MCP tool schema breaks downstream consumers; blocking once Stage 1/2 drove the baseline to zero. |
| **4 — new-debt-fails** | `complexity`, `directory-policy`, `dead-code` | **Hard** on new debt only (diff-scoped): a changed file may not exceed its budget / add a placement violation / introduce dead code | Ratchet: existing debt allowed, PRs may not add more; the whole tree is never re-litigated. |

`generate_quality_report.py` renders, per gate, the current stage and the delta vs. the base branch (e.g. "3 new complexity violations — Stage 4 would block") so reviewers see the effect before a gate is promoted.

### 7.4 Shared CI idioms (mandatory for new gates)

1. **Merge-base diff guard.** Diff-scoped gates use `git diff <base> HEAD -- '<pathspec>'` with `':!<exclude>'` pathspecs, as proven in `refactor-guards.yml` job `no-new-home-ari-refs`.
2. **Path-exclude allow-list.** The 14-entry allow-list in `no-new-home-ari-refs` (`_deprecation.py`, `migrations/`, `core.py`, `paths.py`, `memory_cli.py`, `memory/auto_migrate.py`, `memory/file_client.py`, `publish/backends/ari_registry.py`, `clone/resolvers/ari.py`, `registry/__init__.py`, `viz/state.py`, `viz/api_settings.py`, `viz/api_publish.py`) is the template for sanctioning known-legacy sites so a checker can be strict everywhere else.
3. **Base-ref = `${{ github.event.pull_request.base.sha }}`** everywhere a diff is needed — **not** `origin/${{ github.base_ref }}` (§6.6). New checkers accept a `--base-ref` flag (as `check_report_cochange.py`/`check_ref_coupling.py` already do) and the workflow passes `base.sha`.
4. **`fetch-depth: 0`** for any diff-scoped job (matches `refactor-guards.yml`, `docs-change-coupling.yml`).
5. **`--check`/`--write` snapshot convention** for contract gates (`public-api`, MCP): a checked-in signature snapshot regenerated with `--write`, verified with `--check`, mirroring `readme_sync.py` and Gate 10.

### 7.5 Runtime / tooling constraints

- **Python 3.13 + PyYAML** (matches the docs jobs) — PyYAML is the only sanctioned non-stdlib dependency.
- **`ruff` 0.15.2** for the `lint` job and the `ruff --select F401` unused-import slice of `dead-code`.
- **`node` 20 + `npm ci --prefix ari-core/ari/viz/frontend`** for the `dashboard-ux` job.
- **Forbidden:** `radon` (not installed — the complexity checker must be a stdlib AST/LOC counter) and `pnpm` (the repo uses `npm ci` against lockfiles).
- **Deterministic, no LLM/network calls** in any gate (design principle P2; `ari-skill-memory` and these gates are explicitly LLM-free).

### 7.6 `--json` output + aggregation contract

- Every checker exposes a `--json` flag emitting a stable object: at minimum `{ "checker": <name>, "stage": <int>, "status": "pass|warn|fail", "violations": [ ... ], "baseline_delta": <int> }`.
- Each diff-scoped gate additionally reports `new` vs `preexisting` violation counts so Stage 2/4 ratchets and the PR-comment delta can be computed.
- Each gate uploads its JSON as a build artifact; the terminal `quality-report` job (`needs:` every gate) runs `generate_quality_report.py`, reads all artifacts, and posts **one** PR comment. The aggregation job is **non-gating** — it never fails the PR; the individual gates own pass/fail.

### 7.7 Required-status-check evolution

- **At Stage 1**, no new job is a required status check (all advisory). Only the existing required checks (docs/report/readme/`~/.ari` gates) remain blocking.
- **Promotion to a required check** happens in lockstep with the Stage 2/3/4 flip and is recorded in the branch-protection settings, one gate at a time. This design lists the *intended* required set once every gate reaches its terminal stage: `import-boundaries`, `public-api`, `viz-api-schema`, `mcp-tool-contracts`, `complexity`, `directory-policy`, `dead-code`. `lint`, `prompts-inventory`, `dashboard-ux`, and `quality-report` stay advisory/non-gating.

### 7.8 Contract-preservation guardrails and do-not-do list

- Every contract gate exists to **protect** its surface, never to change it. Intentional changes must ship a compatibility adapter (re-export shim for `ari.public.*`) plus the co-changed reference doc (`docs/reference/public_api.md`, `rest_api.md`, `mcp_tools.md`) in the same PR.
- **Do not** rewrite/merge the five existing workflows (KEEP).
- **Do not** wire `check_docs_source_sync.py` (redundant, §6.3).
- **Do not** add `radon` or `pnpm` to any job.
- **Do not** promote any gate straight past Stage 1.
- **Composite-action DRY (REVIEW_REQUIRED, deferred):** the "checkout + setup-python 3.13 + pip install pyyaml" prelude repeats across four workflows; extracting `.github/actions/setup-python-checks` is an optional MERGE that changes no behavior — a hygiene item, not this subtask.

## 8. Concrete Work Items

All items produce content **inside this `.md`** (design decisions), not code. A fresh coding session executing subtask 046:

1. **W1 — Freeze the mapping table (§7.2).** Confirm every checker's owner subtask against `007_subtask_index.md` at execution time (numbers may have shifted); update the table if the index changed. Flag any checker with no owner subtask as REVIEW_REQUIRED.
2. **W2 — Freeze the four-stage policy (§7.3)** and its one-line promotion mechanism; confirm the advisory-tier precedent still holds by re-reading `docs-sync.yml` (`continue-on-error` blocks) and `docs-change-coupling.yml`.
3. **W3 — Freeze the shared idioms (§7.4)** by re-reading `refactor-guards.yml` (allow-list, merge-base) and the `docs-change-coupling.yml` header (base-ref rationale); reproduce the exact allow-list so implementers copy, not reinvent.
4. **W4 — Freeze the tooling constraints (§7.5):** re-verify `ruff --version` (expect 0.15.2), that `radon` is absent, and that `docs/` uses `npm ci` (no `pnpm`).
5. **W5 — Specify the `--json` + aggregation contract (§7.6)** as the interface subtask 031 implements and every checker emits.
6. **W6 — Record the required-status-check evolution (§7.7)** and the contract-preservation guardrails (§7.8).
7. **W7 — Reconcile numbering (§6.4)** and the 032/046 division (§6.5) so implementers are not misled by `012_...plan.md` §15.
8. **W8 — Hand-off matrix:** produce the per-implementer requirements table (§9 "governed" table) so 047–052 know exactly what to build.

## 9. Files Expected to Change

**In this subtask (046):**

| Path | Change |
| --- | --- |
| `docs/refactoring/subtasks/046_design_quality_ci_integration.md` | **Created** — this design document (the only file written) |

No other file — no `.py`, `.yaml`, `.yml`, `.ts`, `.md` (other than this one), workflow, template, or config — is created or modified in subtask 046.

**Files/artifacts this design GOVERNS in downstream subtasks (informational; NOT changed here):**

| Target path | Governed decision | Implementer subtask |
| --- | --- | --- |
| `.github/workflows/refactor-guards.yml` | ADAPT: append `lint`, `import-boundaries`, `directory-policy`, `complexity`, `dead-code` jobs | 049 (wiring), checkers 025/026/028/055 |
| `.github/workflows/contracts.yml` | NEW: `public-api`, `mcp-tool-contracts`, `viz-api-schema`, `prompts-inventory`, `dashboard-ux`, `quality-report` jobs | 049, 051 |
| `.github/workflows/docs-sync.yml` | ADAPT/extend with code↔doc "must-change-together" assertions | 050 |
| `.github/PULL_REQUEST_TEMPLATE.md` | NEW: hosts the review checklist tied to the gates | 047 |
| `.github/ISSUE_TEMPLATE/` | NEW: bug/feature/refactor intake | 048 |
| `.github/dependabot.yml`, `CODEOWNERS` | NEW: dependency updates + reviewer routing for `ari/public/**`, `ari/viz/**`, `ari-skill-*/src/server.py` | 052 |
| `scripts/check_complexity.py`, `check_import_boundaries.py`, `check_directory_policy.py`, `check_public_api_contracts.py`, `check_viz_api_schema.py`, `check_prompts.py`, `check_dead_code.py`, `analyze_references.py`, `generate_quality_report.py` | Must satisfy the `--json`/`--base-ref`/`--strict` contract (§7.4–§7.6) | 025–031, 043, 054, 055, 058, 073 |
| `report/scripts/check_prompt_snapshots.py` (Gate 10) | MERGE target for the prompt snapshot slice (no duplication) | 043 |

## 10. Files / APIs That Must Not Be Broken

This design *guards* these; it proposes no change to any of them.

- **CLI `ari`** — single console script `ari = ari.cli:app`; subcommands in `ari-core/ari/cli/{commands,run,bfts_loop,lineage,migrate,projects}.py`.
- **`ari.public.*`** — the nine modules under `ari-core/ari/public/` (stable skill re-export layer). The `public-api` gate snapshots these; it never mutates them.
- **MCP tool contracts** — the 14 `ari-skill-*/src/server.py` tool surfaces, consumed via `ari-core/ari/mcp/client.py`. The `mcp-tool-contracts` gate protects the schemas.
- **Dashboard API** — `ari-core/ari/viz/routes.py` (1197) + `api_*.py` + `websocket.py`, consumed by `ari-core/ari/viz/frontend/src/services/api.ts` (863). The `viz-api-schema` gate couples them; it never edits endpoints.
- **Checkpoint/output/config file formats** — `ari-core/ari/checkpoint.py`, YAML under `ari-core/config/` + `ari-core/ari/configs/`.
- **`ari-skill-* → ari-core` stable interfaces** and **README/docs usage**.
- **Scripts invoked by `.github/workflows/`** — the twelve checker scripts wired today; none is renamed or removed by this design.
- **The five existing workflows** — KEEP, unmodified except the explicit `refactor-guards.yml`/`docs-sync.yml` ADAPTs owned by 049/050 (append-only; existing jobs untouched).
- **REVIEW_REQUIRED / not fixed here:** `ari-core/ari/viz/frontend/node_modules/` is committed to git (vendored-deps hygiene issue); `scripts/run_all_tests.sh` is not wired to any workflow; `docs/_archive/refactor_audit.md` links are broken; `reference/environment_variables.md:211` documents a removed `~/.ari/agent.env` fallback. These are flagged, not addressed by 046.

## 11. Compatibility Constraints

- **Additive-only.** Nothing in the design deletes or rewrites an existing workflow, script, or template. New jobs are append-only; new workflows (`contracts.yml`) run alongside the existing five.
- **Warning-first.** Every new gate lands at Stage 1 (`continue-on-error: true`) so no PR is newly blocked on day one. Promotion is a reviewed one-line flip.
- **Idiom compatibility.** New gates reuse the merge-base + allow-list + `base.sha` idioms so they behave identically to the proven `refactor-guards.yml`/`docs-change-coupling.yml` gates.
- **Tooling compatibility.** Gates depend only on tools already present (Python 3.13, PyYAML, `ruff` 0.15.2, `node`+`npm`); `radon`/`pnpm` are forbidden so no runner provisioning changes.
- **Contract compatibility.** Any future intentional change to a guarded surface must ship a compatibility adapter + co-changed reference doc in the same PR (§7.8); the gate is the enforcement point, not an excuse to break the contract.
- **Numbering compatibility.** The design uses `007_subtask_index.md` numbers; if the index is re-numbered before execution, W1 re-confirms the mapping (§8).

## 12. Tests to Run

This subtask changes no code, so the checks are documentation-integrity and no-regression guards, run from the repo root:

- `python -m compileall .` — confirms no `.py` was accidentally touched (must remain green; this subtask edits none).
- `pytest -q` — full suite must remain green (no runtime change expected). For parity with CI, `refactor-guards.yml` runs `pytest ari-core/tests/ -q` under a redirected `HOME`, ignoring `test_letta_restart_live`, `test_letta_start_scripts`, `test_ollama_gpu`, `test_dashboard_html`.
- `ruff check .` — must not report new findings attributable to this subtask (it adds no code).
- `python scripts/readme_sync.py --check` — the `docs/refactoring/subtasks/` directory README `## Contents` index must list this new file (run `--write` locally, then re-`--check`); this is the same gate `readme-sync.yml` enforces.
- Advisory doc checks that touch `docs/`: `python scripts/docs/check_doc_links.py --md-only` (this file introduces only intra-repo references; broken links would surface here).
- Frontend `npm test` / `npm run build`: **N/A** — subtask 046 touches no frontend code.

## 13. Acceptance Criteria

1. `docs/refactoring/subtasks/046_design_quality_ci_integration.md` exists and follows the 17-section template.
2. The checker → host-workflow → job → stage mapping (§7.2) is complete: every net-new checker has a host workflow, a job name, and a stage path, using authoritative `007_subtask_index.md` numbers; the numbering conflict with `012_...plan.md` §15 is explicitly reconciled (§6.4).
3. The four-stage rollout policy (§7.3) is specified with its one-line promotion mechanism, and no gate is assigned a starting stage other than Stage 1.
4. The shared idioms (§7.4) reproduce the exact `refactor-guards.yml` 14-entry allow-list and mandate `base.sha` over `origin/<base_ref>` with the documented rationale.
5. The `--json` + aggregation contract (§7.6) and required-status-check evolution (§7.7) are specified precisely enough for subtasks 031 and 049/050/051/052 to implement without further design questions.
6. Every guarded contract surface (§10) is listed with the gate that protects it, and none is proposed for a breaking change.
7. The redundant `check_docs_source_sync.py` is recorded as **not wired** (DELETE_CANDIDATE); the `check_prompts.py` snapshot slice is recorded as **MERGE into Gate 10**.
8. `python scripts/readme_sync.py --check` passes with this file listed; `python -m compileall .`, `pytest -q`, and `ruff check .` remain green (no code changed).

## 14. Rollback Plan

Trivial and self-contained: the subtask creates exactly one Markdown file.

- **To revert:** `git rm docs/refactoring/subtasks/046_design_quality_ci_integration.md`, then `python scripts/readme_sync.py --write` to drop the entry from the directory README `## Contents`, and commit.
- No runtime code, workflow, script, template, config, prompt, or frontend file is touched, so there is **no runtime state to roll back** and no downstream consumer breaks from removing the design (the implementers 047–052 would simply lack their design input until it is re-authored).
- Because the design is advisory-until-implemented, deleting it cannot break CI: no workflow references it.

## 15. Dependencies

Per the refactoring dependency graph (`045 -> 046, 047, 048, 049, 050, 051, 052`):

- **Hard predecessor (blocks start):** **045 `inventory_github_workflows`** — supplies the concrete `.github/` inventory (five workflows, twelve wired checkers, confirmed-absent templates) that this design assigns hosts/jobs against. 046 cannot be finalized before 045.
- **This subtask enables (downstream consumers of the design):** **047** (PR template), **048** (issue templates), **049** (contract-check workflows / `contracts.yml`), **050** (docs-sync additions), **051** (prompt-change review workflow), **052** (dependabot + CODEOWNERS/actions policy) — all of which also depend on 045 and are siblings of 046.
- **Checker-owning subtasks whose output this design wires (coordination, not blocking):** 025 (`check_complexity.py`), 026 (`check_import_boundaries.py`), 027 (`check_docs_source_sync.py`, DELETE_CANDIDATE), 028 (`check_directory_policy.py`), 029 (`check_public_api_contracts.py` + MCP), 030 (`check_viz_api_schema.py`), 031 (`generate_quality_report.py`), 043 (`check_prompts.py`), 054 (`analyze_references.py`), 055 (`check_dead_code.py`), 058 (dead-code section of the report), 066 (dashboard build+CI), 073 (dashboard-UX regression checks). These may proceed in parallel; the design only fixes *how* their outputs are wired.
- **Related sibling plan (soft, not in the graph):** **032 `add_quality_script_ci_plan`** — see §6.5 for the division of labor.
- **Parent phase plan (context, not a graph edge):** `docs/refactoring/012_github_workflow_integration_plan.md`.
- Consistent with the inventory-gate rule that runtime code changes are gated behind 001, 002, 020, 036, 045, 053, 059, 060, 067: 046 is downstream of the 045 gate and itself makes **no** runtime change.

## 16. Risk Level

- **Overall risk: LOW.** Matches `007_subtask_index.md` row 93 (Phase 9, Risk **Low**).
- **Changes runtime code: NO.** This subtask produces a single design `.md` and touches no `.py`, `.yaml`, `.yml`, `.ts`, workflow, template, config, prompt, or directory name. (`007_subtask_index.md` row 93 marks 046 "Runtime code change: No".)
- The only risk is *design* risk — a wrong host/stage assignment — which is realized only when the implementers (047–052) and checker owners act on it. That risk is contained by: (a) warning-first staging (§7.3) so a mis-assigned gate cannot block PRs, (b) the additive-only rule (§7.8) so no existing gate is destabilized, and (c) W1's execution-time re-confirmation of the index numbering (§8).

## 17. Notes for Implementer

- **Read first, in order:** `007_subtask_index.md` (rows 72–99 for the checker/CI cluster), `012_github_workflow_integration_plan.md` (§7–§16 for the phase-level rationale — but treat its §15 bracketed subtask numbers as stale, per §6.4), and the five files in `.github/workflows/`. Then re-verify the tooling facts in W4.
- **The index (007) wins every numbering conflict.** Do not propagate `012_...plan.md` §15's `[subtask NNN]` brackets.
- **Do not write any workflow, script, or template in this subtask.** If you feel the urge to author `contracts.yml` or a `check_*.py`, that belongs to 049/050/051/052 and 025–031/043/054/055 — this subtask only designs their wiring. Section 9's "governed" table is the hand-off.
- **Reproduce, don't paraphrase, the `refactor-guards.yml` allow-list** (§7.4 item 2) so implementers copy the exact 14 paths.
- **Freeze `base.sha`** as the base-ref idiom and cite the `docs-change-coupling.yml` header (lines 41–47) rationale so no implementer regresses to `origin/<base_ref>`.
- **Coordinate with 032** (§6.5) before finalizing so the plan-vs-design split is clean and neither doc restates the other.
- **`sonfigs/` does not exist** — the directory-policy slice targets the real trio (`ari-core/ari/config/` code, `ari-core/ari/configs/` packaged data, top-level `ari-core/config/` rubric data). Never reference `sonfigs/`.
- After writing, run `python scripts/readme_sync.py --write` so the `docs/refactoring/subtasks/README.md` `## Contents` index picks up this file, then `--check` to confirm, mirroring the `readme-sync.yml` gate.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **046** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
