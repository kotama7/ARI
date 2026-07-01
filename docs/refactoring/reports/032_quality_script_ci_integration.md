# 032 — Quality-Script CI Integration Plan (authoritative)

> **Deliverable of subtask** `docs/refactoring/subtasks/032_add_quality_script_ci_plan.md`
> (§9 → this single Markdown file). **Planning only.** Authoring this document
> changes **no** runtime code, **no** `.github/workflows/*.yml`, **no**
> `scripts/*.py`, **no** config, prompt, frontend, or directory name. The only
> file it creates is this one.
>
> It turns the prose of `012_github_workflow_integration_plan.md` (§7/§8/§15) into
> a concrete, per-job wiring spec that the workflow-implementation subtasks (049
> contract workflows / 050 docs-sync / 051 prompt-review, plus the refactor-guards
> ADAPT owner) can execute **without further design work** and **without
> rewriting any of the five existing workflows**.
>
> **Repo baseline:** `/home/t-kotama/workplace/ARI` · git branch
> `whole_refactoring` · `ari-core` version `0.9.0` · verified against the working
> tree **2026-07-01**. Every path/line cited below was read from the tree; absent
> paths are written "does not exist" (never invented). CI facts are cross-checked
> against the frozen inventory `docs/refactoring/reports/045_github_workflow_inventory.md`.
>
> Classification vocabulary: **KEEP / ADAPT / MERGE / MOVE_TO_LEGACY /
> DELETE_CANDIDATE / REVIEW_REQUIRED**. The word "deprecated" is reserved for
> external contracts only; the `origin/<base_ref>` idiom is described as
> "not preferred / do not copy", not "deprecated".

---

## 1. Purpose and status of this plan

The refactoring workstream adds a family of source-quality checkers under
`scripts/` (Phase 8, subtasks 025–031). They are worthless unless they run at PR
time. This document is the **single authoritative** spec for how they are wired
into GitHub Actions:

- which checker gets its own CI job vs MERGEs into an existing gate vs gets
  **no** job (DELETE_CANDIDATE);
- which workflow hosts each job (ADAPT `refactor-guards.yml` by appending, or the
  NEW `contracts.yml`);
- the trigger, diff-scope, base-ref idiom, and staged-rollout entry stage per job;
- the shared checker/job convention that lets `generate_quality_report.py`
  aggregate them;
- the aggregation `needs:`/artifact protocol.

This plan is **additive and staged**. It keeps all five existing workflows
(KEEP), reuses the two proven diff-guard idioms already in the repo, prefers
`base.sha` over `origin/<base_ref>`, avoids `radon`/`vulture`/`pnpm`, and promotes
every new gate warning-first through Stages 1→4. It proposes **no** breaking
change to any contract surface; each surface is instead given a CI gate that
*protects* it.

**This subtask writes only this Markdown file.** The actual YAML edits are owned
by 049/050/051; the checker scripts by 025–031; the `.github/` template files by
047/048/052. The YAML in §9 below is an **illustrative sketch in a fenced block,
never a committed workflow**.

---

## 2. Grounded CI baseline (what exists today)

From reading all five workflows and the frozen inventory (045):

- `.github/` contains **only** `workflows/`, with **exactly five** files:
  `refactor-guards.yml` (105 L), `docs-sync.yml` (91 L), `pages.yml` (64 L),
  `docs-change-coupling.yml` (58 L), `readme-sync.yml` (28 L).
- All gating today is **documentation / i18n / report-oriented**. Only
  `refactor-guards.yml` touches Python source, and only for the `~/.ari/`
  invariant (`refactor-guards.yml:83-105`) plus a sandboxed
  `pytest ari-core/tests/` run (`:48-65`). **No workflow runs `ruff`,
  `compileall`, an import-boundary check, a complexity check, or a
  public-API / viz-schema check** — so none of the Phase-8 checkers are
  represented in CI and there is **no overlap to untangle beyond pattern reuse**.
- Only `pages.yml` is push-triggered (and the only deploy workflow); every other
  gate is PR-time to `main`. `refactor-guards.yml` is the **only** workflow that
  also targets the `refactoring` branch (`refactor-guards.yml:12-16`).
- Confirmed **absent** (each checked directly, 2026-07-01):
  `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`,
  `.github/dependabot.yml`, `CODEOWNERS`, `.github/actions/`, and
  `.github/workflows/contracts.yml`. There is **no `sonfigs/` directory anywhere**
  (the confusable trio is `ari-core/ari/config/` code, `ari-core/ari/configs/`
  packaged defaults, top-level `ari-core/config/` rubric data).
- Tooling on the runners (verified): `ruff` **is** available (0.15.2); `radon`,
  `vulture` are **not** installed; `python -m compileall` / `pytest` are
  available; `node`+`npm` are available; **`pnpm` is not used**. New checkers must
  therefore avoid `radon`/`vulture`/`pnpm` as hard dependencies.

All seven Phase-8 checker scripts are **absent today** (verified in 009/012/045);
every new job is additive.

---

## 3. Per-checker CI placement table (canonical 007 numbering)

The seven Phase-8 checkers (subtask IDs per the canonical `007_subtask_index.md`
Summary Table, which `032` §1 mirrors — see the numbering reconciliation in §11):

| Subtask | Script (planned path) | CI verdict | Host workflow | Trigger / diff-scope | Entry stage |
| --- | --- | --- | --- | --- | --- |
| **025** | `scripts/check_complexity.py` | **own job** (`complexity`) | ADAPT `refactor-guards.yml` (append) | PR → `main`+`refactoring`; diff-scoped to changed `**.py` via merge-base | Stage 1 → 4 |
| **026** | `scripts/check_import_boundaries.py` | **own job** (`import-boundaries`) | ADAPT `refactor-guards.yml` (append) | PR → `main`+`refactoring`; diff-scoped | Stage 1 → 2 |
| **027** | `scripts/check_docs_source_sync.py` | **NO job — DELETE_CANDIDATE** | — (not wired) | — | — |
| **028** | `scripts/check_directory_policy.py` | **own job** (`directory-policy`), placement/naming slice only | ADAPT `refactor-guards.yml` (append) | PR → `main`+`refactoring`; repo-wide (cheap tree scan) | Stage 1 → 4 |
| **029** | `scripts/check_public_api_contracts.py` | **own job** (`public-api`) | NEW `contracts.yml` | PR → `main`; `--check` snapshot + diff-scoped regression | Stage 1 → 3 |
| **030** | `scripts/check_viz_api_schema.py` | **own job** (`viz-api-schema`) | NEW `contracts.yml` | PR → `main`; diff-scoped to `viz/**` + `frontend/services/**` | Stage 1 → 3 |
| **031** | `scripts/generate_quality_report.py` | **aggregation job** (`quality-report`, `needs: *`) | NEW `contracts.yml` | PR → `main`; consumes per-job JSON, never gates on content | reporter (no stage) |

Supporting advisory jobs (not standalone Phase-8 checker subtasks, kept advisory):

| Job | Backed by | Host | Verdict / stage |
| --- | --- | --- | --- |
| `lint` | `ruff check .` | ADAPT `refactor-guards.yml` (append) | advisory, Stage 1 (may stay advisory indefinitely) |
| `dead-code` | `ruff --select F401` slice | ADAPT `refactor-guards.yml` (append) | advisory, Stage 1 (full `check_dead_code.py` is a later phase, not a Phase-8 032 concern) |
| `mcp-tool-contracts` | MCP tool `name`/`inputSchema`/`{result|error}` envelope snapshot | NEW `contracts.yml` | Stage 1 → 3; **no owning script subtask yet** (`[—]`) — flagged REVIEW_REQUIRED, grouped with 048 |

**Focus five (named in the 032 task brief):** `check_complexity` (025),
`check_import_boundaries` (026) → `refactor-guards.yml`;
`check_public_api_contracts` (029), `check_viz_api_schema` (030),
`generate_quality_report` (031) → `contracts.yml`. The remaining two (027
DELETE_CANDIDATE, 028 own job) are covered above for completeness (§13 requires
all seven enumerated).

**027 `check_docs_source_sync.py` — DELETE_CANDIDATE, no CI job.** It duplicates
existing coverage in **both** directions: `scripts/docs/check_doc_sources.py`
(forward: declared `sources:` resolve) + `scripts/docs/check_ref_coupling.py`
(reverse: a changed source bumps the referencing doc's `last_verified`). An
implementer must **not** add a redundant CI job unless a genuinely new invariant
is first proven (none is known today). Do not create the script.

**Prompt-snapshot slice — MERGE into Gate 10.** Any prompt-snapshot verification
reuses the existing `report/scripts/check_prompt_snapshots.py` (**Gate 10**, which
byte-verifies `ari-core/ari/prompts/**/*.md`); it is **not** re-implemented. The
inline-prompt inventory slice (`check_prompts.py`) is a separate later subtask
(051 prompt-review workflow), out of this plan's Phase-8 scope.

---

## 4. Additive layout (no existing workflow rewritten)

Two mechanisms only, both additive (mirrors 012 §15):

1. **ADAPT `refactor-guards.yml` by *appending* jobs** for the refactor-invariant
   gates (`complexity` [025], `import-boundaries` [026], `directory-policy` [028],
   `lint`, `dead-code`). Its two existing jobs (`no-home-ari-writes`,
   `no-new-home-ari-refs`) are **untouched**. Rationale: it is the only workflow
   triggered on the `refactoring` branch (`refactor-guards.yml:12-16`), so
   refactoring branches get these gates **before** reaching `main`.

2. **Add one NEW `contracts.yml`** (triggered on all PRs to `main`) for the
   external-contract regression gates (`public-api` [029],
   `viz-api-schema` [030], `mcp-tool-contracts`) plus the `quality-report` [031]
   aggregation job. Grouping the contract gates keeps the required-status-check
   list readable. `contracts.yml` **does not exist today** (verified) — it is net
   new, owned by subtask 049.

The five existing workflows are all **KEEP / untouched**:
`refactor-guards.yml` (extended by append only), `docs-sync.yml`, `pages.yml`,
`docs-change-coupling.yml`, `readme-sync.yml`. Nothing above deletes, renames, or
merges an existing workflow file or any of the 12 `scripts/` entry points those
workflows invoke.

---

## 5. Shared-convention contract (every new checker/job MUST satisfy)

So `generate_quality_report.py` (031) can aggregate heterogeneous checkers, and so
CI/pre-commit can host them uniformly, every new `scripts/check_*.py` follows the
house style already set by `scripts/docs/` (verified: each is
`#!/usr/bin/env python3`, docstring citing a design doc, `argparse`,
`REPO_ROOT = Path(__file__).resolve().parents[N]`, PyYAML-only, staged
warn→error):

- `#!/usr/bin/env python3`; module docstring citing its owning subtask **and this
  plan**.
- `argparse` with `--json` (machine output for the aggregator) and a
  `--strict`/level flag that turns warnings into failures — the promotion
  mechanism §7 relies on.
- `REPO_ROOT = Path(__file__).resolve().parents[1]` — checkers live at `scripts/`
  top level (one level up), **not** under `scripts/docs/` (which uses
  `parents[2]`).
- Pure stdlib where possible; **PyYAML** is the only sanctioned non-stdlib dep
  (already installed in the docs jobs). **No `radon`, no `vulture`, no `pnpm`.**
- **Deterministic — no LLM, no network** (design principle P2; the same
  constraint the docs gates and `ari-skill-memory` hold).
- Exit `1` on findings-above-threshold (so CI can gate on exit code), `0` when
  clean or advisory (`--warning-only`), `2` on usage/environment error — matching
  `scripts/docs/check_doc_sources.py`'s `SystemExit(2)` convention.
- Each checker also reads a frozen **allowlist/baseline** keyed by stable identity
  (file path, `module→module` edge, symbol qualname, endpoint name), so
  pre-existing debt is reported as `known` and never fails `--fail-on-regression`.
  (Allowlist/config placement — `scripts/quality/<name>.yaml` — is owned by the
  checker subtasks 025–031, not this plan.)

---

## 6. Diff-scope and base-ref rules

New diff-scoped jobs **reuse, not reinvent**, the two idioms already proven in the
tree:

1. **Merge-base diff guard.** `git diff <base> HEAD -- '<pathspec>'` with
   `':!<exclude>'` pathspecs — the pattern from `refactor-guards.yml:83-96`.
2. **Path-exclude allow-list.** The `no-new-home-ari-refs` job grandfathers
   sanctioned legacy sites so the check can be strict everywhere else. Reproduced
   **verbatim** below (grounded from `refactor-guards.yml:83-96`) for 049 to copy
   — **1 base include pathspec** (`:83`) + **13 `:!` exclude pathspecs**
   (`:84-96`):

   ```
   # base include pathspec (:83)
   git diff "$base" HEAD -- 'ari-core/ari/**.py' \
   # 13 exclude pathspecs (:84-96)
     ':!ari-core/ari/_deprecation.py' \
     ':!ari-core/ari/migrations/' \
     ':!ari-core/ari/core.py' \
     ':!ari-core/ari/paths.py' \
     ':!ari-core/ari/memory_cli.py' \
     ':!ari-core/ari/memory/auto_migrate.py' \
     ':!ari-core/ari/memory/file_client.py' \
     ':!ari-core/ari/publish/backends/ari_registry.py' \
     ':!ari-core/ari/clone/resolvers/ari.py' \
     ':!ari-core/ari/registry/__init__.py' \
     ':!ari-core/ari/viz/state.py' \
     ':!ari-core/ari/viz/api_settings.py' \
     ':!ari-core/ari/viz/api_publish.py' \
   ```

   > **Grounding note (carried from 045 §8 discrepancy #1):** `012` §3.1 and
   > subtask 045's prose call this a **"14"-entry** allow-list; the file actually
   > has **13** `:!` excludes (`grep -nE "^\s*':!" refactor-guards.yml` → 13). The
   > "14" is only reached by counting the base **include** pathspec on line 83
   > alongside the 13 excludes (1 include + 13 excludes = 14 pathspecs). Ground
   > truth = 13 excludes. Do **not** "fix" the workflow here; re-verify against
   > these exact `file:line` citations if `refactor-guards.yml` changes before 049
   > runs. **REVIEW_REQUIRED** for whoever next edits those prose counts.

3. **Base-ref selection — mandate `base.sha` for every NEW diff job.** Use
   `${{ github.event.pull_request.base.sha }}` (as `docs-change-coupling.yml:51`
   and `:57-58` do). **Do NOT** copy `refactor-guards.yml:82`'s
   `base="$(git merge-base origin/${{ github.base_ref || 'main' }} HEAD)"` idiom
   into new jobs. The in-tree rationale is documented verbatim at
   `docs-change-coupling.yml:41-47`: `base.sha` "is immutable for this run and
   always reachable in the fetched history … Preferred over the
   `origin/<base_ref>` pattern in refactor-guards.yml, which resolves a
   remote-tracking ref that can move if the base branch advances mid-run." New
   jobs **fail CLOSED** if the ref fails to resolve.

4. **`fetch-depth: 0`** on any diff-scoped job (matches the three existing diff
   jobs: `refactor-guards.yml:24`/`:72`, `docs-sync.yml:44`,
   `docs-change-coupling.yml:33`).

> The appended `refactor-guards.yml` jobs (§4) run in the *same file* as the
> legacy `origin/<base_ref>` job; they must still use `base.sha` for their own new
> diff steps. The legacy job is KEEP and is **not** modified — the two idioms
> coexist; only *new* steps adopt `base.sha`.

---

## 7. Staged warning → failure policy (from 012 §8)

Every new gate escalates through four stages, driven by each checker's
`--strict`/level flag, **not** by editing many workflow lines. This mirrors how
the docs advisories (`check_ref_coupling.py`, `check_translation_freshness.py`,
markdown `check_doc_links.py`) were rolled out — each currently sits at the
advisory tier via `continue-on-error: true`, awaiting promotion.

| Stage | Gates | Mode |
| --- | --- | --- |
| **1 — warning-all** | every new gate (`complexity`, `import-boundaries`, `directory-policy`, `public-api`, `viz-api-schema`, `mcp-tool-contracts`, `lint`, `dead-code`) | **Advisory** (`continue-on-error: true`); surfaces full existing debt, establishes the baseline snapshot, blocks nothing |
| **2 — regression-only-hard** | `check_import_boundaries.py` [026], `check_public_api_contracts.py` [029] | **Hard on diff-scoped *new* violations only** (merge-base idiom, §6); pre-existing violations stay grandfathered |
| **3 — contract-breakage-hard** | `check_viz_api_schema.py` [030], `check_public_api_contracts.py` [029] (full), `mcp-tool-contracts` | **Hard on any external-contract break** (dashboard API ↔ `services/api.ts`, `ari.public.*`, MCP tool schema) once Stage 1/2 have driven the baseline to zero |
| **4 — new-debt-hard** | `check_complexity.py` [025], `check_directory_policy.py` [028], `dead-code` | **Hard on *new* debt only** (ratchet): a changed file may not exceed its LOC/complexity budget, add a placement violation, or introduce dead code. Diff-scoped so the whole tree is never re-litigated |

**Invariants:**

- **A gate never skips a stage** — it must spend real calendar time at Stage 1
  (baseline) before promotion, exactly as the docs advisory checks did.
- **Promotion is a one-line change** (flip `continue-on-error: false`, or pass
  `--strict`), **never a checker rewrite** — so promotion PRs are trivially
  reviewable and are their own separate, later subtask.
- **This plan schedules the rollout; it flips nothing.** No gate is born Hard;
  no `continue-on-error` is flipped by 032 or by the initial wiring (049–051).
  `generate_quality_report.py` renders each gate's current stage and its
  delta-vs-base so reviewers see would-block counts (e.g. "3 new complexity
  violations — Stage 4 would block") *before* any gate is promoted.

---

## 8. Aggregation protocol (`generate_quality_report.py`, 031)

- **Each checker job** runs its checker with `--format json` (or `--json`),
  writes the report to a per-job path, and uploads it as a build artifact
  (`actions/upload-artifact`).
- **`quality-report`** is a `needs:`-gated job (depends on all checker jobs in its
  workflow), downloads their artifacts, merges the stable JSON schema
  (`{checker, version, target, summary, findings[]}`), and renders **one**
  PR-comment summary (per-gate stage + delta-vs-base). It is a **reporter**: it
  never fails the build on checker *content*, only on its own execution error.

- **Cross-workflow limitation (REVIEW_REQUIRED for 049).** GitHub Actions
  `needs:` cannot span workflows, and `download-artifact` cannot directly reach
  another workflow-run's artifacts without extra plumbing. The `contracts.yml`
  `quality-report` job can `needs:` only the **contracts.yml** checker jobs
  (`public-api`, `viz-api-schema`, `mcp-tool-contracts`); the refactor-invariant
  gates live in `refactor-guards.yml` (a separate workflow). Two options — 049
  picks one:
  - **Option A (recommended):** the `quality-report` job re-invokes the fast,
    stdlib, network-free refactor-invariant checkers itself with `--format json`
    to fold their findings into the single report. Acceptable because those
    checkers are deterministic and cheap (LOC/AST scans, P2-compliant); the cost
    is recomputation, not correctness.
  - **Option B:** a separate `workflow_run`-triggered aggregation consumes the
    completed `refactor-guards.yml` run's uploaded artifacts. More faithful to a
    pure artifact model but adds a second trigger surface — flagged
    **REVIEW_REQUIRED**, deferred.

---

## 9. Worked YAML sketch (ILLUSTRATIVE ONLY — do not commit as a workflow)

The block below is a **non-executable illustration** for 049/050/051 to copy from.
It is intentionally *not* a file under `.github/workflows/`; authoring 032 commits
**no** YAML. It shows (a) one appended `refactor-guards.yml` job using `base.sha`
+ `fetch-depth: 0`, and (b) the `contracts.yml` skeleton with the aggregation job.

```yaml
# ── (a) APPENDED to .github/workflows/refactor-guards.yml — existing 2 jobs untouched ──
  complexity:                               # subtask 025, Stage 1 -> 4
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }            # enables merge-base diff
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: python -m pip install --upgrade pip pyyaml
      - name: Complexity / LOC budget (advisory at Stage 1)
        continue-on-error: true             # flip to false to promote (Stage 4)
        run: |
          base="${{ github.event.pull_request.base.sha }}"   # NOT origin/<base_ref>
          python scripts/check_complexity.py \
            --base-ref "$base" --format json --output complexity.json
      - uses: actions/upload-artifact@v4
        with: { name: quality-complexity, path: complexity.json }
  # import-boundaries (026, Stage 1->2), directory-policy (028, Stage 1->4),
  # lint (ruff, advisory), dead-code (ruff --select F401, advisory): same shape.

# ── (b) NEW .github/workflows/contracts.yml — all PRs to main ──
name: contracts
on:
  pull_request:
    branches: [main]
jobs:
  public-api:                               # subtask 029, Stage 1 -> 3
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: python -m pip install --upgrade pip pyyaml
      - name: ari.public.* contract snapshot (advisory at Stage 1)
        continue-on-error: true
        run: python scripts/check_public_api_contracts.py --check --format json --output public_api.json
      - uses: actions/upload-artifact@v4
        with: { name: quality-public-api, path: public_api.json }
  viz-api-schema:      # subtask 030, Stage 1 -> 3 (diff-scoped to viz/** + frontend/services/**)
    runs-on: ubuntu-latest
    steps: [ "...same prelude...", "python scripts/check_viz_api_schema.py --base-ref \"${{ github.event.pull_request.base.sha }}\" --format json --output viz_api.json" ]
  mcp-tool-contracts:  # no owning script subtask yet ([—]); REVIEW_REQUIRED, Stage 1 -> 3
    runs-on: ubuntu-latest
    steps: [ "..." ]
  quality-report:                           # subtask 031, aggregation (reporter only)
    needs: [public-api, viz-api-schema, mcp-tool-contracts]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4  # same-workflow artifacts only (see §8)
      - run: python scripts/generate_quality_report.py --input . --format markdown
      # posts one PR comment; never fails the build on checker content
```

Structural rules the sketch encodes: `base.sha` everywhere a diff is needed;
`fetch-depth: 0` on diff jobs; Python 3.13 + PyYAML prelude (matching the docs
jobs); `ruff` for lint/F401; `node 20` + `npm ci --prefix ari-core/ari/viz/frontend`
for any frontend gate (no `pnpm`); each checker `--format json` + artifact upload
so `quality-report` can aggregate.

---

## 10. Do-not-do list (for the wiring implementers)

- Do **not** rewrite or merge the five existing workflows — all KEEP.
- Do **not** create `scripts/check_docs_source_sync.py` (027) or give it a CI job
  — redundant with `check_doc_sources.py` + `check_ref_coupling.py` (§3).
- Do **not** re-implement prompt-snapshot verification — MERGE into Gate 10
  (`report/scripts/check_prompt_snapshots.py`).
- Do **not** add `radon`, `vulture`, or `pnpm` to any job; do **not** edit
  `requirements*.txt`, `requirements.lock`, or `ari-core/pyproject.toml`.
- Do **not** promote any new gate straight to Hard — every gate enters at Stage 1.
- Do **not** copy `refactor-guards.yml:82`'s `origin/<base_ref>` idiom into new
  jobs — use `base.sha` (§6).
- Do **not** add push-time source CI: the only push-triggered workflow is
  `pages.yml` (docs deploy). All new source gates are **PR gates**, so nothing
  blocks the Pages deploy path.
- **Composite-action opportunity (REVIEW_REQUIRED, optional MERGE, deferred):**
  the "checkout + setup-python 3.13 + `pip install pyyaml`" prelude repeats across
  ≥4 workflows; a `.github/actions/setup-python-checks` composite would DRY it.
  `.github/actions/` does not exist today — note it, defer it (out of scope here).
- **`scripts/run_all_tests.sh` (per-skill pytest, 13 hardcoded paths) is not
  referenced by any workflow** — an ADAPT candidate for a test-integration
  subtask, **not** this plan's job.

---

## 11. Carried-forward REVIEW_REQUIRED notes + numbering reconciliation

### 11.1 Two REVIEW_REQUIRED items carried from the 045 inventory

Both are **flagged, not resolved here** (resolution belongs to 046/049/050):

1. **`refactor-guards.yml:82` `origin/<base_ref>` merge-base idiom.** The one
   existing diff-scoped source job uses `git merge-base origin/${{ github.base_ref
   || 'main' }} HEAD` — a mutable remote-tracking ref. Preferred replacement is
   `${{ github.event.pull_request.base.sha }}` (§6; rationale documented in-tree at
   `docs-change-coupling.yml:41-47`). This plan mandates `base.sha` for all *new*
   jobs and leaves the legacy job untouched (KEEP). Whether to also migrate the
   legacy job is 046/049 work. **REVIEW_REQUIRED.**
2. **`pages.yml:21` README-only path filter.** The push trigger filters
   `paths: ['docs/**', 'report/**', 'README.md']` (`pages.yml:19-21`) — it names
   `README.md` only, **not** `README.ja.md` / `README.zh.md`. A push that edits
   only a translated README would not trigger a Pages rebuild. Intent unconfirmed;
   resolution is subtask 050 (`add_docs_sync_workflow`) work, **not** this plan's.
   The new source gates in §3–§4 do **not** touch `pages.yml`. **REVIEW_REQUIRED.**

### 11.2 Canonical subtask numbering (state prominently)

The canonical source is **`docs/refactoring/007_subtask_index.md`** (its Summary
Table), which subtask `032` §1 mirrors exactly:

- **Checkers = 025–031:** 025 `check_complexity`, 026 `check_import_boundaries`,
  027 `check_docs_source_sync` (DELETE_CANDIDATE), 028 `check_directory_policy`,
  029 `check_public_api_contracts`, 030 `check_viz_api_schema`,
  031 `generate_quality_report`.
- **GitHub-integration items = 032/045–052:** 032 `add_quality_script_ci_plan`
  (this doc), 045 `inventory_github_workflows`, 046 `design_quality_ci_integration`,
  047 PR template, 048 issue templates, 049 contract-check workflows,
  050 docs-sync, 051 prompt-change review, 052 dependabot/actions.

**Known discrepancies (recorded, not "fixed"; the sibling docs are not edited):**

- **`012` §16 (primary flag).** The master GitHub-integration plan
  `012_github_workflow_integration_plan.md` §15/§16 uses an *older* mapping that
  assigns the checkers to **045–052** (e.g. `check_complexity`/`dead_code`/
  `generate_quality_report` → "045", `check_import_boundaries` → "046", templates
  → "052"). A fresh implementer reading only 012 would wire the wrong subtask
  ownership. **Treat 007 + the dependency graph as authoritative; flag the
  `012` §16 drift as a known discrepancy. Do not edit 012 in this subtask.** (This
  same drift is independently recorded in 045 §9 discrepancy #2.)
- **`009` §10 (secondary flag).** `009_quality_scripts_plan.md` §10 uses a *third*
  mapping (027 `check_directory_policy`, 028 `check_public_api_contracts`,
  029 `check_viz_api_schema`, 030 `check_prompts`, 031 `check_dashboard_ux`,
  058 `generate_quality_report`). It conflicts with 007/032 on 027–031. **007 +
  032 §1 are authoritative for this plan**; 009 §10 is noted for honesty, not
  adopted. (This does not affect the five focus checkers named in the 032 brief,
  which map identically under both.)

### 11.3 032 ↔ 046 consolidation recommendation

`007` Phase 9 pairs "**046** `design_quality_ci_integration` / **032**
`add_quality_script_ci_plan`" as the same work; two competing plans are a
maintenance hazard. **Recommendation:** this document
(`docs/refactoring/reports/032_quality_script_ci_integration.md`) is the **single
authoritative** CI-integration plan for the Phase-8 checkers. Subtask 046 should
**reference / MERGE into** this document rather than fork a competing plan. A
back-link from `012` §16 to this plan should be added **only** if a later docs
subtask edits 012 — 032 does **not** edit 012; it records the intended back-link
as a follow-up note.

---

## 12. Preserved contracts (this plan guards, never breaks)

Authoring 032 writes only Markdown, so nothing is broken at execution time. The
*wiring it specifies* must preserve every contract surface — the gates exist to
protect these, never to change them:

- **CLI** `ari = ari.cli:app` — new gates must not alter or wrap it.
- **`ari.public.*`** — 9 verified modules (`claim_gate.py`, `config_schema.py`,
  `container.py`, `cost_tracker.py`, `__init__.py`, `llm.py`, `paths.py`,
  `run_env.py`, `verified_context.py`) under `ari-core/ari/public/`. The
  `public-api` gate *snapshots* this surface; it never proposes renaming/removing
  a symbol.
- **MCP tool contracts** — the 14 `ari-skill-*/src/server.py` servers consumed via
  `ari-core/ari/mcp/client.py`; tool `name`, `inputSchema`, and the
  `{"result"|"error"}` envelope. The `mcp-tool-contracts` gate protects schemas;
  it does not modify them.
- **Dashboard API** — `ari-core/ari/viz/routes.py` (+ `api_experiment.py`,
  `api_paperbench.py`, …) ↔ `ari-core/ari/viz/frontend/src/services/api.ts` +
  `websocket.py`. The `viz-api-schema` gate asserts endpoint parity; it never
  edits endpoints.
- **Checkpoint / output / config file formats** — `ari-core/ari/checkpoint.py`;
  YAML under `ari-core/ari/configs/` and top-level `ari-core/config/`.
- **`ari-skill-* → ari-core` stable interface** and the single
  `ari-core → ari_skill_memory` core→skill import edge (allowlisted, not banned).
- **The five existing workflows** and the 12 `scripts/` entry points they invoke —
  all KEEP; new jobs are additive.
- **README / docs usage** and the `scripts/` referenced by `.github/workflows/*`
  (e.g. `scripts/readme_sync.py`, `scripts/docs/*`).

---

## 13. Non-goals of subtask 032

- **No workflow edits.** No `.github/workflows/*.yml` is created, rewritten, or
  merged (owned by 049/050/051). The YAML in §9 is illustrative only.
- **No checker implementation.** No `scripts/check_*.py` /
  `scripts/generate_quality_report.py` is written (owned by 025–031).
- **No `.github/` template files.** `PULL_REQUEST_TEMPLATE.md`, `ISSUE_TEMPLATE/`,
  `dependabot.yml`, `CODEOWNERS`, `.github/actions/` stay absent (owned by
  047/048/052).
- **No dependency install / manifest edit.** `radon`/`vulture`/`pnpm` not added;
  `requirements*.txt`/`.lock`/`ari-core/pyproject.toml` untouched.
- **No promotion of any gate to Hard**; no `continue-on-error` flipped.
- **No runtime code, prompt, config, checkpoint, frontend, or directory-name
  change.**
- **No re-derivation of 012.** 012 is cited/reconciled, never duplicated or
  edited.

---

## 14. Self-verification (per subtask §12/§13)

- **Single-file contribution.** Subtask 032 creates exactly one file — this
  report. It touches no `.github/` YAML, no `scripts/*.py`, no source, no manifest.
  (Any other untracked entries in the working tree — e.g. the pre-existing
  `docs/refactoring/HANDOFF_PROMPTS.md`, or concurrent sibling-subtask outputs
  such as 026/029's `scripts/check_*.py` — are not produced by 032.)
- **Baselines unchanged** (this subtask adds no `.py`): `python -m compileall .`,
  `pytest -q`, and `ruff check .` behave identically to clean `main`.
- **`readme_sync.py`.** This file lands in `docs/refactoring/reports/`, whose
  `README.md` carries **no** `## Contents` heading (curated/unmanaged README);
  `scripts/readme_sync.py` therefore never enumerates files here and no parent
  managed README descends into it — adding this report introduces **no** new
  `readme_sync --check` drift (consistent with 045 §12).
- **Every cited path resolves on disk** (verified 2026-07-01): the five workflows;
  `refactor-guards.yml:82`/`:83-96`; `docs-change-coupling.yml:41-47`/`:51`;
  `pages.yml:19-21`; the 9 `ari.public.*` modules; `report/scripts/check_prompt_snapshots.py`
  (Gate 10); `ari-core/ari/viz/routes.py`, `api_experiment.py`, `api_paperbench.py`,
  `frontend/src/services/api.ts`; `ari-core/ari/mcp/client.py`; `scripts/docs/*`;
  `scripts/readme_sync.py`; `scripts/git-hooks/pre-commit`; `scripts/run_all_tests.sh`.
  `contracts.yml` and the seven checker scripts are correctly written as
  **does not exist / net-new** (this plan proposes, does not create, them).

---

## 15. Retirement Condition

This report is the deliverable of a **temporary planning artifact** (subtask 032).
It may be archived or deleted (`git rm`) only after **all** of the following are
verified against primary sources (repository state, merged diff, index) — never on
assumption:

1. The **§13 Acceptance Criteria** of
   `docs/refactoring/subtasks/032_add_quality_script_ci_plan.md` are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **032** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read the subtask's own conditions and check each against the current
repository — see the canonical policy in `docs/refactoring/007_subtask_index.md`
("Document Retirement Policy").
