# Subtask 051: Add Prompt Change Review Workflow

> Phase 9: GitHub Integration · Risk: Low · Changes ARI runtime code: **No** (adds one
> CI workflow YAML) · Depends on: 045 (`inventory_github_workflows`) · Enabled-by root
> fan-out `045 -> 046..052`.
>
> Planning document only. Nothing in this file modifies runtime code, imports, prompts,
> configs, workflows, frontend, or directory names. It hands a fresh coding session an
> executable plan to add a **PR-time prompt-change review workflow** under
> `.github/workflows/` that wires ARI's already-existing prompt-integrity assets into
> CI. All paths and line counts are repository-real and verified against the tree at
> planning date **2026-07-01** (ari-core `0.9.0`, branch `main`).

## 1. Goal

Add a single, clearly-named GitHub Actions workflow —
`.github/workflows/prompt-change-review.yml` — that fires on pull requests which touch
**prompt-bearing files** and enforces ARI's existing prompt-integrity contract at
review time. Concretely, when a PR edits an externalized prompt template, this workflow
must:

1. **Fail closed** if an externalized prompt under `ari-core/ari/prompts/**/*.md`
   changed but its Gate-10 appendix snapshot under
   `report/shared/appendix/prompts/**/*.md` was not regenerated to match (byte + SHA-256
   mismatch). This wires the existing but **currently-unwired** checker
   `report/scripts/check_prompt_snapshots.py` (93 lines) into CI for the first time.
2. **Fail closed** if an externalized prompt changed but its pinned SHA-256 row in
   `ari-core/tests/test_prompt_extraction.py` (107 lines) was not updated — surfaced as
   a dedicated, fast, prompt-scoped `pytest` step instead of being buried inside the
   ~1,545-test suite that `refactor-guards.yml` already runs.
3. **Warn (advisory)** when a template `.md` changed in the PR but neither its appendix
   snapshot nor its SHA row moved in the same PR — a co-change signal that a prompt edit
   needs a snapshot regeneration and (per `docs/refactoring/011_prompt_management_plan.md`
   §9) a manual `prompt_version` bump and reviewer attention.

The workflow gives prompt reviewers a crisp, isolated CI signal ("this PR changed an
LLM prompt; here is whether the snapshot/version contract held") that today does not
exist as a distinct check. It does **not** implement new checker logic: it composes
assets that already ship in the repo (`check_prompt_snapshots.py`,
`test_prompt_extraction.py`, `FilesystemPromptLoader.load_versioned`) plus the proven
`base.sha` diff idiom from `.github/workflows/docs-change-coupling.yml`.

## 2. Background

**Prompts are already partially externalized and already snapshot-pinned — but the
snapshot-integrity checker never runs in CI.** Verified assets at planning date:

- **Loader:** `ari-core/ari/prompts/_loader.py` (49 lines) defines
  `FilesystemPromptLoader`; `load_versioned(key)` returns `(text, sha256[:12])` for
  reproducibility pinning (`_loader.py:45-49`).
- **Externalized templates (11 `.md` + 5 per-dir READMEs)** under
  `ari-core/ari/prompts/`: `agent/system.md`; `evaluator/{extract_metrics,peer_review}.md`;
  `orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,root_idea_selector}.md`;
  `pipeline/keyword_librarian.md`; `viz/{wizard_chat_goal,wizard_generate_config}.md`.
- **Pytest snapshot test:** `ari-core/tests/test_prompt_extraction.py` (107 lines) pins
  a SHA-256 per externalized key (`_EXPECTED_HASHES`, e.g. `agent/system`,
  `orchestrator/lineage_decision`, `pipeline/keyword_librarian`, `orchestrator/bfts_select`,
  …) and asserts the on-disk body still hashes to the recorded value. This test **does**
  run in CI today, but only transitively via `refactor-guards.yml:56` (`pytest
  ari-core/tests/ -q`).
- **Gate 10 checker (UNWIRED):** `report/scripts/check_prompt_snapshots.py` (93 lines)
  verifies that every `report/shared/appendix/prompts/**/*.md` snapshot body equals the
  bytes of the source `ari-core/ari/prompts/**/*.md` file named in its
  `% snapshot-from: <rel>@<sha256> @ commit <c>` header, and that the recorded SHA-256
  matches. It exits non-zero on any mismatch/missing source/missing snapshot. **It is
  referenced only in `report/CLAUDE.md:100`, `report/README.md`, and
  `report/scripts/README.md` — it is invoked by NO `.github/workflows/` file** (verified
  by `grep -rn check_prompt_snapshots .github/`).
- **Snapshot regenerator:** `report/scripts/snapshot_prompts.py` (91 lines) rebuilds the
  `report/shared/appendix/prompts/{agent,evaluator,orchestrator,pipeline,viz}/` mirror.
- **Skill-local prompts (bypass the core loader & snapshots):**
  `ari-skill-paper-re/src/prompts/replicator.md` and
  `ari-skill-replicate/src/prompts/{adversarial_reviewer,skeleton,rubric_audit,subtree}.md`,
  loaded via ad-hoc `Path.read_text()` (no versioning/snapshot). Flagged
  **REVIEW_REQUIRED** in `011_prompt_management_plan.md`; **out of scope** for 051's hard
  gate (they have no snapshot to check yet), but the advisory co-change diff can name
  them for visibility.
- **Contributor contract:** `CONTRIBUTING.md` (416 lines) §385-399 already codifies the
  rule: every core LLM call loads from `ari/prompts/<area>/<purpose>.md`, "The prompt
  file is byte-equivalent to the inline original; pin the sha256 in
  `ari-core/tests/test_prompt_extraction.py` so silent edits surface as a CI failure"
  (`CONTRIBUTING.md:385-389`), and "verify `sha256(inline_orig) == sha256(loaded_template)`
  before merge" (`:398-399`). This is prose guidance, not an enforced PR-scoped gate.

**Current CI surface (from subtask 045's inventory).** `.github/` contains only
`workflows/` with five files: `refactor-guards.yml` (105 lines), `docs-sync.yml` (91),
`pages.yml` (64), `docs-change-coupling.yml` (58), `readme-sync.yml` (28). All gating is
docs/i18n-oriented except `refactor-guards.yml` (the `~/.ari/` invariant + a pytest
sandbox). **No workflow runs a prompt-integrity check by name.** Two diff idioms coexist:
`refactor-guards.yml:82` uses the mutable `git merge-base origin/${{ github.base_ref }}`
ref; `docs-change-coupling.yml:41-47` critiques that and uses the immutable
`github.event.pull_request.base.sha`. **051 must use `base.sha`.**

**Why a dedicated workflow rather than relying on `refactor-guards.yml`.** The SHA
snapshot test is already inside the big pytest run, but (a) the Gate-10 appendix
checker (`check_prompt_snapshots.py`) is *not* in CI at all, so a template edit that
skips the appendix regeneration is silently mergeable today; and (b) prompt reviewers
have no isolated signal — a failing `test_prompt_extraction.py` is one red dot among
1,545 tests. Subtask 051 closes gap (a) and improves gap (b) with a path-filtered,
purpose-named workflow.

## 3. Scope

In scope (implementation of 051, when a coding session executes this plan):

- **Create one workflow:** `.github/workflows/prompt-change-review.yml`.
- **Trigger:** `pull_request` to `main` (and `refactoring`, matching
  `refactor-guards.yml:13-16`), with `paths:` filtered to prompt-bearing files so the
  workflow only spends CI minutes when a prompt or its snapshot/test changed.
- **Hard gate — appendix snapshot integrity:** invoke the existing
  `report/scripts/check_prompt_snapshots.py --root .` (byte + SHA-256 equality between
  `report/shared/appendix/prompts/**` and `ari-core/ari/prompts/**`).
- **Hard gate — pinned-hash snapshot test:** run `pytest
  ari-core/tests/test_prompt_extraction.py -q` (fast, prompt-scoped).
- **Advisory gate — prompt co-change coupling:** using
  `github.event.pull_request.base.sha`, diff `ari-core/ari/prompts/**/*.md`; when a
  template changed but neither its `report/shared/appendix/prompts/**` snapshot nor its
  SHA row in `ari-core/tests/test_prompt_extraction.py` changed in the same PR, emit a
  warning (`continue-on-error: true`). Mirrors the co-change idea of
  `scripts/docs/check_report_cochange.py`, implemented inline in YAML (no new script) or,
  optionally, via a small dedicated helper (§7).
- **Optional advisory hook (guarded by file existence):** if
  `scripts/docs/check_prompts.py` (subtask 043) exists at run time, run its
  inline-prompt-inventory slice as `continue-on-error: true`. Guard with a shell
  `if [ -f scripts/docs/check_prompts.py ]` so 051 has **no hard dependency** on 043
  landing.
- Register the new report/workflow only insofar as `readme-sync.yml` requires (the
  `.github/workflows/` directory has no `readme_sync`-managed `## Contents` index today;
  confirm before touching anything — see §11).

Out of scope (belongs to other subtasks):

- Writing or modifying `report/scripts/check_prompt_snapshots.py`,
  `snapshot_prompts.py`, or `ari-core/tests/test_prompt_extraction.py` — those are
  Phase-7 prompt subtasks (042 `add_prompt_snapshot_tests`, 043 `add_prompt_checker_script`)
  and the report toolchain. 051 only *calls* them.
- Building `scripts/docs/check_prompts.py` (the inline-prompt inventory) — subtask 043.
- Extracting still-inline prompts (`ari-skill-paper/src/server.py:542,1487,1638,1660,2544`,
  `ari-skill-evaluator/src/server.py:191,790`, `ari/agent/loop.py`, …) — subtasks
  039/040/041.
- Adding a snapshot mechanism for skill-local prompts (`ari-skill-*/src/prompts/**`) —
  prompt-management follow-up (011 §REVIEW_REQUIRED), not 051.
- The general contract-check workflow (`check_import_boundaries.py`, etc.) — subtask 049.
- Extending `docs-sync.yml` — subtask 050. PR/issue templates — 047/048. Dependabot /
  actions policy — 052.
- Deciding staged blocking-vs-advisory promotion policy across all checkers — subtask
  046 / `012_github_workflow_integration_plan.md` §Stage 1-3.

## 4. Non-Goals

- **Do not** modify any of the five existing workflow files. 051 is purely additive.
- **Do not** change any ARI runtime code, prompt template, config, or directory name.
- **Do not** edit `report/scripts/check_prompt_snapshots.py`,
  `report/scripts/snapshot_prompts.py`, or `ari-core/tests/test_prompt_extraction.py`.
- **Do not** re-implement snapshot verification. Per `012` §11 (line 239) and `011`
  §7-item-7, MERGE into / reuse the existing Gate-10 checker — never a parallel copy.
- **Do not** hard-depend on subtask 043's `check_prompts.py`; wire it advisory-and-guarded
  or omit it.
- **Do not** promote the co-change coupling check to a hard gate on day one — start it
  `continue-on-error: true` (Stage-1 warning-all, per `012` §Stage 1).
- **Do not** use the mutable `git merge-base origin/<base_ref>` idiom; use
  `github.event.pull_request.base.sha` (rationale: `docs-change-coupling.yml:41-47`).
- **Do not** add or touch `report/**` content, `docs/` site content, or README variants
  beyond a `readme-sync`-mandated index line (which likely does not apply here).
- No `sonfigs/` directory exists anywhere in the repo; do not target it (see §17).

## 5. Current Files / Directories to Inspect

All paths repository-real, verified 2026-07-01.

**Prompt-integrity assets this workflow composes (read; do NOT modify):**

- `/home/t-kotama/workplace/ARI/report/scripts/check_prompt_snapshots.py` (93 lines) —
  Gate-10 appendix snapshot checker; `--root <repo-root>`; compares
  `report/shared/appendix/prompts/**` to `ari-core/ari/prompts/**` via
  `% snapshot-from:` headers. **Currently invoked by no workflow.**
- `/home/t-kotama/workplace/ARI/report/scripts/snapshot_prompts.py` (91 lines) — the
  regenerator authors run locally when a template legitimately changes.
- `/home/t-kotama/workplace/ARI/ari-core/tests/test_prompt_extraction.py` (107 lines) —
  pinned SHA-256 snapshot test (`_EXPECTED_HASHES`).
- `/home/t-kotama/workplace/ARI/ari-core/ari/prompts/_loader.py` (49 lines) —
  `FilesystemPromptLoader` + `load_versioned`.
- `/home/t-kotama/workplace/ARI/ari-core/ari/prompts/` — 11 externalized `.md` templates
  (the diff subject of the advisory co-change gate).
- `/home/t-kotama/workplace/ARI/report/shared/appendix/prompts/`
  (`agent/ evaluator/ orchestrator/ pipeline/ viz/` + `README.md`) — the snapshot mirror
  the hard gate validates.
- `/home/t-kotama/workplace/ARI/CONTRIBUTING.md` (416 lines) §385-399 — the human-authored
  version of the same contract; keep the workflow's failure messages consistent with it.

**Skill-local prompts (context; NOT part of the hard gate):**

- `/home/t-kotama/workplace/ARI/ari-skill-paper-re/src/prompts/replicator.md`
- `/home/t-kotama/workplace/ARI/ari-skill-replicate/src/prompts/{adversarial_reviewer,skeleton,rubric_audit,subtree}.md`

**Existing workflows to read for pattern reuse (do NOT modify):**

- `/home/t-kotama/workplace/ARI/.github/workflows/docs-change-coupling.yml` (58 lines) —
  the canonical `github.event.pull_request.base.sha` co-change idiom
  (`docs-change-coupling.yml:41-58`), hard + advisory (`continue-on-error`) structure.
- `/home/t-kotama/workplace/ARI/.github/workflows/refactor-guards.yml` (105 lines) —
  reuse (a) `fetch-depth: 0` + install order (`ari-skill-memory` then `ari-core`) if the
  pytest step needs the package importable, and (b) the path-exclude/allow-list
  convention; but replace its mutable `origin/<base_ref>` idiom (`:82`) with `base.sha`.
- `/home/t-kotama/workplace/ARI/.github/workflows/docs-sync.yml` (91 lines) — reference
  for a two-job hard/advisory layout and Python `3.13` setup.

**Companion planning docs (read for alignment; do NOT modify):**

- `/home/t-kotama/workplace/ARI/docs/refactoring/subtasks/045_inventory_github_workflows.md`
  — the frozen CI baseline this subtask builds on.
- `/home/t-kotama/workplace/ARI/docs/refactoring/011_prompt_management_plan.md`
  (esp. §7-item-7 "Lint + snapshot completeness gate", §9 prompt_version bump, §10 CI
  wiring at lines 493-496) — the prompt-side policy 051 enforces.
- `/home/t-kotama/workplace/ARI/docs/refactoring/012_github_workflow_integration_plan.md`
  §11 (lines 235-242) — the "MERGE the snapshot slice into Gate 10" directive.
  **Discrepancy to reconcile (see §17):** `012` §304-305 / §330-331 uses an older
  numbering (there 050 = `check_prompts` inline slice, 051 = `check_dashboard_ux`); the
  authoritative per-subtask table `007_subtask_index.md:98` assigns
  **051 = `add_prompt_change_review_workflow`**. Treat `007` as canonical.
- `/home/t-kotama/workplace/ARI/docs/refactoring/007_subtask_index.md:92-99` — Phase-9
  table and the `045 -> 046..052` edges.

**Confirmed absent (record, do not create):** `.github/workflows/prompt-change-review.yml`
(this subtask's deliverable — does not exist yet, verified via
`ls .github/workflows/`); no prompt-related workflow of any name exists today.

## 6. Current Problems

Observations that motivate 051, each grounded in a file/line. These are the gaps 051
closes, not pre-existing defects to "fix" elsewhere.

1. **Gate 10 is documented but never enforced.**
   `report/scripts/check_prompt_snapshots.py` is described as "gate 10" in
   `report/CLAUDE.md:100` but is invoked by **no** `.github/workflows/` file (verified by
   `grep -rn check_prompt_snapshots .github/` → only doc hits). A PR that edits
   `ari-core/ari/prompts/agent/system.md` without regenerating
   `report/shared/appendix/prompts/agent/system.md` is silently mergeable today.
2. **The prompt SHA test has no isolated review signal.**
   `ari-core/tests/test_prompt_extraction.py` runs only inside
   `refactor-guards.yml:56`'s ~1,545-test `pytest ari-core/tests/ -q`. A prompt reviewer
   cannot tell at a glance whether *this* PR's failure is a prompt-hash drift. → 051
   surfaces it as a named, path-filtered job.
3. **No co-change enforcement between template, appendix snapshot, and SHA row.** The
   three artifacts that must move together (`ari/prompts/<key>.md`,
   `report/shared/appendix/prompts/<key>.md`, the `_EXPECTED_HASHES` row) have no PR-time
   coupling check analogous to `scripts/docs/check_report_cochange.py`. A partial edit
   currently fails only if it happens to break the byte/SHA equality — but the *advisory*
   nudge to also bump `prompt_version` (`011` §9) is absent.
4. **The mutable diff idiom is still present in `refactor-guards.yml:82`.** New workflows
   must not copy `git merge-base origin/<base_ref>`; the immutable
   `github.event.pull_request.base.sha` (`docs-change-coupling.yml:41-47`) is the
   in-tree-preferred form. **REVIEW_REQUIRED** to migrate the old file — but that is
   046/049 work, not 051; 051 simply uses the correct idiom from the start.
5. **Skill-local prompts have no snapshot at all.**
   `ari-skill-{paper-re,replicate}/src/prompts/**` load via ad-hoc `read_text()` with no
   hash pin (`011` REVIEW_REQUIRED). 051's hard gate cannot cover them (nothing to
   compare against); it may name them in the advisory diff for visibility only.

## 7. Proposed Design / Policy

**Deliverable:** one new file `.github/workflows/prompt-change-review.yml`. It composes
existing assets; it introduces **no** new Python runtime code and (in the minimal
variant) no new script.

### 7.1 Trigger and path filter

```yaml
on:
  pull_request:
    branches: [main, refactoring]
    paths:
      - 'ari-core/ari/prompts/**'
      - 'ari-skill-*/src/prompts/**'
      - 'report/shared/appendix/prompts/**'
      - 'ari-core/tests/test_prompt_extraction.py'
      - '.github/workflows/prompt-change-review.yml'
```

Rationale: the workflow only needs to run when a prompt, its snapshot, its pinned-hash
test, or the workflow itself changed. Because the source-template path is in the filter,
a PR that edits a template but *forgets* the snapshot still triggers the run (the source
path matched) and then fails the hard gate — exactly the case we must catch.

### 7.2 Jobs (recommended layout)

- **Job `prompt-snapshots` (hard gate).** `runs-on: ubuntu-latest`,
  `actions/checkout@v4`, `actions/setup-python@v5` (Python `3.13`, matching every other
  workflow). Steps:
  1. `python report/scripts/check_prompt_snapshots.py --root .` — Gate 10, first time in
     CI. Stdlib-only (`argparse`, `hashlib`, `re`, `pathlib`); no `pip install` needed.
  2. `pip install -e ari-skill-memory && pip install -e ari-core` (install order per
     `refactor-guards.yml:39-40`, because `ari-core` imports `ari_skill_memory`), then
     `pytest ari-core/tests/test_prompt_extraction.py -q`. The test imports only
     `ari.prompts.FilesystemPromptLoader` + `hashlib`, so the install can be trimmed to
     the minimum that makes `import ari.prompts` succeed; verify locally.
- **Job `prompt-cochange` (advisory, `continue-on-error: true`).**
  `fetch-depth: 0`. Using `BASE="${{ github.event.pull_request.base.sha }}"`, compute the
  changed set with `git diff --name-only "$BASE" HEAD`. For every changed
  `ari-core/ari/prompts/**/*.md`, WARN (do not fail) if neither the paired
  `report/shared/appendix/prompts/<same-rel>.md` nor
  `ari-core/tests/test_prompt_extraction.py` is also in the changed set. Emit a
  `::warning::` with the remediation ("run `python report/scripts/snapshot_prompts.py`
  and bump the sha row + `prompt_version` per CONTRIBUTING.md §385-399").
- **Optional Job/step `inline-prompt-inventory` (advisory, guarded).**
  `if [ -f scripts/docs/check_prompts.py ]; then python scripts/docs/check_prompts.py
  --json; fi` under `continue-on-error: true`. No-op until subtask 043 lands.

### 7.3 Master-vocabulary classification

| Component | Class | Rationale |
| --- | --- | --- |
| `report/scripts/check_prompt_snapshots.py` | **KEEP** (wire into CI) | Existing Gate-10 checker, reused verbatim; 051 only invokes it. |
| `ari-core/tests/test_prompt_extraction.py` | **KEEP** (surface as job) | Existing SHA-pin test; 051 runs it prompt-scoped for a clear signal. |
| `github.event.pull_request.base.sha` idiom | **KEEP / preferred** | Immutable; per `docs-change-coupling.yml:41-47`. |
| `git merge-base origin/<base_ref>` idiom (`refactor-guards.yml:82`) | **REVIEW_REQUIRED** | Do not copy; migration of the old file is 046/049, not 051. |
| Inline co-change diff logic (YAML) vs a new `scripts/docs/check_prompt_cochange.py` | **REVIEW_REQUIRED** | Minimal variant inlines it; a small script is optional and would reuse `check_report_cochange.py`'s structure. Prefer inline to keep 051 script-free and Low-risk. |
| `scripts/docs/check_prompts.py` (043) | **ADAPT (guarded)** | Advisory, existence-guarded; no hard dependency. |
| Skill-local `ari-skill-*/src/prompts/**` | **REVIEW_REQUIRED** | No snapshot yet; advisory-name only, out of hard gate. |
| New `.github/workflows/prompt-change-review.yml` | **net-new (does not exist)** | The sole deliverable. |

### 7.4 Rollout posture

Per `012` §Stage 1 (warning-all first): the appendix snapshot integrity and the SHA test
are **hard from day one** — they are deterministic byte/hash comparisons with zero
false-positive risk and already codified in `CONTRIBUTING.md:385-399`. The co-change
coupling nudge and the optional inline-inventory start **advisory**
(`continue-on-error: true`) and may be promoted later by subtask 046's staged-rollout
decision. Determinism (design principle P2): every step is a static byte/hash/`git diff`
comparison — **no LLM calls** — consistent with the prompt-plan's P2 note (`012:242`).

## 8. Concrete Work Items

1. Read `045_inventory_github_workflows.md` and the three existing workflows named in §5
   to lock the house conventions (Python `3.13`, `fetch-depth: 0`, `base.sha`,
   hard/advisory split).
2. Confirm the hard-gate assets still exist and behave: run
   `python report/scripts/check_prompt_snapshots.py --root .` and
   `pytest ari-core/tests/test_prompt_extraction.py -q` locally; both must currently pass
   on `main` (baseline green before adding the gate).
3. Author `.github/workflows/prompt-change-review.yml` with the trigger + path filter of
   §7.1 and the jobs of §7.2. Use `github.event.pull_request.base.sha` for any diff.
4. Implement the advisory co-change check **inline in YAML** (minimal, script-free) using
   `git diff --name-only "$BASE" HEAD` and a small shell/`python -c` loop that maps
   `ari-core/ari/prompts/<rel>.md` → its expected snapshot path and the SHA-test file.
   Mark it `continue-on-error: true`.
5. Add the existence-guarded advisory hook for `scripts/docs/check_prompts.py` (043) so
   the workflow is forward-compatible without a hard dependency.
6. Trim the `pip install` in the pytest job to the minimum that makes `import ari.prompts`
   succeed (the test needs only the loader), following the install order in
   `refactor-guards.yml:39-40`.
7. Ensure failure messages point authors to the fix: `report/scripts/snapshot_prompts.py`
   (regenerate appendix) + update the `_EXPECTED_HASHES` row in
   `ari-core/tests/test_prompt_extraction.py` + `prompt_version` bump per
   `CONTRIBUTING.md:385-399` / `011` §9.
8. Verify the workflow does **not** trigger on unrelated PRs (path filter) and **does**
   trigger + fail when a template changes without its snapshot (construct a throwaway
   local branch to sanity-check the `git diff` logic; do not push it).
9. Reconcile the numbering discrepancy noted in §5/§17 (record it; do not edit `012`).
10. Confirm no `readme_sync`-managed index covers `.github/workflows/` before/after adding
    the file (§11); if one unexpectedly does, regenerate it with
    `python scripts/readme_sync.py --write`.

## 9. Files Expected to Change

**Created (the only net-new file):**

- `/home/t-kotama/workplace/ARI/.github/workflows/prompt-change-review.yml` — the new
  PR-time prompt-change review workflow.

**Optional (only if the co-change gate is factored into a script instead of inline YAML —
NOT recommended for the minimal Low-risk variant):**

- `/home/t-kotama/workplace/ARI/scripts/docs/check_prompt_cochange.py` — a small
  stdlib-only helper mirroring `scripts/docs/check_report_cochange.py`'s `--base-ref`
  interface. If added, it is advisory-only and reuses the `base.sha` idiom.

**Possibly touched (index bookkeeping only, if — and only if — one applies):**

- A `readme_sync`-managed `## Contents` index that happens to enumerate
  `.github/workflows/`. Verify with `python scripts/readme_sync.py --check`; at planning
  date `.github/` has no per-directory README, so this is expected to be a no-op.

**Explicitly NOT changed:** any existing `.github/workflows/*.yml`;
`report/scripts/check_prompt_snapshots.py`; `report/scripts/snapshot_prompts.py`;
`ari-core/tests/test_prompt_extraction.py`; any `ari-core/` or `ari-skill-*/` runtime
code, prompt template, or config; `report/**` snapshot content; `docs/` site content;
any README variant.

## 10. Files / APIs That Must Not Be Broken

051 adds a CI workflow; it must not perturb any contract:

- **The five existing workflows** — `refactor-guards.yml`, `docs-sync.yml`, `pages.yml`,
  `docs-change-coupling.yml`, `readme-sync.yml` — remain byte-identical.
- **`report/scripts/check_prompt_snapshots.py` CLI** — invoked with the exact
  `--root <repo-root>` contract it already exposes; not modified.
- **`ari-core/tests/test_prompt_extraction.py`** — run, not edited; its `_EXPECTED_HASHES`
  format is a test contract other subtasks (039-044) append to.
- **CLI `ari`** (`ari = ari.cli:app`), **`ari.public.*`**, the 14 **MCP `ari-skill-*/src/server.py`
  tool contracts**, the **dashboard API** (`ari/viz/routes.py` + `api_*.py` +
  `websocket.py`), **checkpoint/config file formats**, and **`ari-skill-* → ari-core`
  interfaces** — all untouched; 051 changes no runtime code.
- **Prompt templates & loader** — `ari-core/ari/prompts/**/*.md` and `_loader.py`
  (`load_versioned`) are read/validated, never edited.
- **Documented import paths / README usage** — unchanged.

No compatibility adapter is required because 051 changes no runtime behavior. The only
new external surface is a CI job; it is additive and (for the co-change/inline-inventory
parts) advisory.

## 11. Compatibility Constraints

- **No runtime behavior change**, so CLI / `ari.public.*` / MCP / dashboard API / file
  formats / skill→core interfaces are trivially preserved.
- **The new workflow must not redden unrelated PRs.** The `paths:` filter (§7.1) keeps it
  dormant unless a prompt/snapshot/test file changes. Confirm the filter globs match the
  real tree (`ari-skill-*/src/prompts/**` matches both existing skill prompt dirs).
- **The hard gate must be green on `main` before it is added.** Run
  `check_prompt_snapshots.py --root .` and the SHA test on the current tip first; if they
  are red on `main` today, that is a pre-existing prompt-plan defect (fix belongs to
  042/043, not 051) — do not add a hard gate over a red baseline.
- **Adding a workflow can trip `readme-sync.yml`** *only if* a `readme_sync`-managed index
  lists `.github/workflows/`. At planning date it does not (no `.github/**/README.md`);
  verify with `python scripts/readme_sync.py --check` and regenerate with `--write` if
  the situation has changed.
- **Idiom compatibility:** use `github.event.pull_request.base.sha`. Do not reintroduce
  the `origin/<base_ref>` merge-base pattern the tree already critiques
  (`docs-change-coupling.yml:41-47`).
- **Forward compatibility with 043:** the optional `check_prompts.py` step must be
  existence-guarded so the workflow is valid whether or not 043 has landed.

## 12. Tests to Run

This subtask adds a CI workflow (YAML) and no ARI `.py`, so the runtime gates are for
hygiene/no-regression and must be unaffected:

- `python -m compileall .` — must pass (no `.py` added/changed by 051).
- `pytest -q` — from repo root; must pass unchanged. (CI's `refactor-guards.yml` runs
  `pytest ari-core/tests/ -q` under a redirected `HOME`, ignoring
  `test_letta_restart_live`, `test_letta_start_scripts`, `test_ollama_gpu`,
  `test_dashboard_html`; mirror those ignores if reproducing that job locally.)
- `ruff check .` — must pass unchanged (ruff IS available; radon is NOT installed — do not
  rely on it).
- **Prompt-integrity self-check (the assets the new workflow wires):**
  `python report/scripts/check_prompt_snapshots.py --root .` and
  `pytest ari-core/tests/test_prompt_extraction.py -q` — both must pass on the baseline
  before the hard gate is added.
- **Workflow lint / dry validation:** validate the YAML parses (e.g. `python -c "import
  yaml,sys; yaml.safe_load(open('.github/workflows/prompt-change-review.yml'))"`); if
  `actionlint` is available, run it (it is not guaranteed installed — do not block on it).
- **Docs/CI index self-check:** `python scripts/readme_sync.py --check` — expected green
  and unaffected (`.github/workflows/` has no managed index today).
- **Frontend `npm test` / `npm run build` are NOT applicable** — 051 adds no frontend
  code (the frontend lives at `ari-core/ari/viz/frontend/`, untouched here).
- Optional end-to-end sanity: on a throwaway local branch, edit one
  `ari-core/ari/prompts/**/*.md` without regenerating its appendix snapshot and confirm
  the hard gate would fail; edit both and confirm it passes. Do not push the throwaway
  branch.

## 13. Acceptance Criteria

- [ ] `.github/workflows/prompt-change-review.yml` exists, parses as valid YAML, and is
  the only file created (plus, at most, an optional `scripts/docs/check_prompt_cochange.py`
  if the co-change gate was scripted rather than inlined).
- [ ] Trigger is `pull_request` to `main` and `refactoring`, with a `paths:` filter
  covering `ari-core/ari/prompts/**`, `ari-skill-*/src/prompts/**`,
  `report/shared/appendix/prompts/**`, `ari-core/tests/test_prompt_extraction.py`, and the
  workflow file itself.
- [ ] A **hard** job runs `python report/scripts/check_prompt_snapshots.py --root .`
  (Gate 10 now enforced in CI for the first time).
- [ ] A **hard** job runs `pytest ari-core/tests/test_prompt_extraction.py -q` as a
  prompt-scoped signal.
- [ ] An **advisory** (`continue-on-error: true`) co-change check uses
  `github.event.pull_request.base.sha` and warns when a template `.md` changed without its
  paired appendix snapshot or its `_EXPECTED_HASHES` SHA row changing in the same PR.
- [ ] Any optional `scripts/docs/check_prompts.py` (043) invocation is
  existence-guarded and advisory — the workflow is valid whether or not 043 exists.
- [ ] No mutable `git merge-base origin/<base_ref>` idiom is used.
- [ ] None of the five existing workflows, `check_prompt_snapshots.py`,
  `snapshot_prompts.py`, `test_prompt_extraction.py`, or any runtime `ari-core/` /
  `ari-skill-*/` file was modified.
- [ ] Failure messages direct authors to `report/scripts/snapshot_prompts.py`, the
  `_EXPECTED_HASHES` update, and the `prompt_version` bump per `CONTRIBUTING.md:385-399`.
- [ ] `python -m compileall .`, `pytest -q`, `ruff check .`, and
  `python scripts/readme_sync.py --check` all pass; the two prompt-integrity assets pass
  on the baseline.
- [ ] The `012` numbering discrepancy (§5/§17) is recorded, not silently reconciled by
  editing `012`.

## 14. Rollback Plan

Trivial and low-risk — the subtask is additive CI config only:

1. `git rm .github/workflows/prompt-change-review.yml` (and the optional
   `scripts/docs/check_prompt_cochange.py` if it was added).
2. No existing workflow, script, prompt, or runtime file was modified, so there is
   nothing else to restore. A single `git revert <commit>` fully reverses the subtask.
3. Because the added gate only runs on prompt-touching PRs, even leaving it in place has
   no effect on unrelated PRs; removal has no downstream impact on the other Phase-9
   subtasks (046-052) beyond the prompt slice.

## 15. Dependencies

Per the DEPENDENCY GRAPH (`045 -> 046, 047, 048, 049, 050, 051, 052`) and
`007_subtask_index.md:92-99`:

- **Upstream (must precede 051):** **045** (`inventory_github_workflows`) — the frozen CI
  baseline. 045 is itself a root inventory (`Depends = —`) and one of the nine inventories
  that gate any runtime code change (`001, 002, 020, 036, 045, 053, 059, 060, 067`). The
  graph encodes **no other hard predecessor** for 051.
- **Soft/recommended (not graph-hard, but reduces rework):** the Phase-7 prompt subtasks
  under root **036** — especially **042** (`add_prompt_snapshot_tests`, which formalizes
  the `test_prompt_extraction.py` surface 051 runs) and **043** (`add_prompt_checker_script`,
  whose `check_prompts.py` 051 hooks in advisory-and-guarded). 051 is designed to work
  **before** 043 lands (the hook is existence-guarded), so 043 is not a blocker.
- **Sibling context (not blocking):** **046** (`design_quality_ci_integration`) sets the
  staged blocking-vs-advisory policy; 051 follows its Stage-1 default (advisory for the
  co-change/inventory parts) but does not wait on it. **049/050/052** are independent
  Phase-9 leaves.
- **Downstream:** none. 051 is a Phase-9 leaf (nothing depends on it in the graph).

No subtask other than 045 must complete before 051 begins.

## 16. Risk Level

**Low. Changes ARI runtime code: No.** 051 adds one CI workflow YAML that composes
assets already in the repo (`report/scripts/check_prompt_snapshots.py`,
`ari-core/tests/test_prompt_extraction.py`) and one `base.sha` `git diff`. It touches no
`.py`, no prompt template, no config, no directory name, and none of the five existing
workflows. The hard gates are deterministic byte/hash comparisons already codified in
`CONTRIBUTING.md:385-399`, so false positives are near-zero. The main realistic failure
modes are: (a) a `paths:` glob that under- or over-matches (mitigated by the §12 e2e
sanity check), and (b) adding a hard gate over a red baseline (mitigated by the §11/§12
requirement to confirm both assets pass on `main` first). Worst case, revert one file.

## 17. Notes for Implementer

- **Wire, don't reinvent.** The whole point of 051 is that Gate 10
  (`report/scripts/check_prompt_snapshots.py`) already exists but runs in **no**
  workflow, and the SHA test (`test_prompt_extraction.py`) is buried in the big pytest
  run. Reuse both verbatim (`012:239` "MERGE the snapshot slice into Gate 10 — do not
  re-implement"). Do not write a second snapshot verifier.
- **Use `github.event.pull_request.base.sha`.** Rationale is written in-tree at
  `docs-change-coupling.yml:41-47`: `base.sha` is immutable for the run and always
  reachable; the `origin/<base_ref>` merge-base in `refactor-guards.yml:82` can move
  mid-run. Do not copy the old idiom; migrating it is REVIEW_REQUIRED work for 046/049.
- **Keep the co-change gate advisory and script-free.** The minimal Low-risk variant
  implements it inline in YAML with `git diff --name-only "$BASE" HEAD` +
  `continue-on-error: true`. Only add `scripts/docs/check_prompt_cochange.py` if a reviewer
  prefers a tested helper; if so, mirror `scripts/docs/check_report_cochange.py`'s
  `--base-ref` interface and stdlib-only, PyYAML-optional convention.
- **Do not hard-depend on 043.** Guard the `check_prompts.py` step with
  `if [ -f scripts/docs/check_prompts.py ]` and `continue-on-error: true`. 043's
  inline-prompt inventory is Stage-1 advisory by design (`012:240-242`, `011` §7-item-7).
- **Skill-local prompts are out of the hard gate.** `ari-skill-{paper-re,replicate}/src/prompts/**`
  have no snapshot to compare against (they bypass the loader, `011` REVIEW_REQUIRED). At
  most name them in the advisory diff; do not fail on them.
- **Point authors at the fix.** On failure, echo the remediation: regenerate with
  `python report/scripts/snapshot_prompts.py`, update the `_EXPECTED_HASHES` row in
  `ari-core/tests/test_prompt_extraction.py`, and bump `prompt_version` per
  `CONTRIBUTING.md:385-399` and `011` §9. This matches the contributor contract already
  in the tree.
- **Reconcile the numbering discrepancy — do not silently edit `012`.**
  `012_github_workflow_integration_plan.md` §304-305 / §330-331 was written against an
  older mapping (there 050 = `check_prompts`, 051 = `check_dashboard_ux`). The
  authoritative per-subtask table `007_subtask_index.md:98` says
  **051 = `add_prompt_change_review_workflow`** and `050 = add_docs_sync_workflow`. Follow
  `007`; record the `012` mismatch as a REVIEW_REQUIRED note for whoever owns `012`.
- **Reserve "deprecated" for external contracts.** For the mutable-idiom cleanup in
  `refactor-guards.yml`, use REVIEW_REQUIRED / ADAPT — not "deprecated".
- **No `sonfigs/` anywhere.** The master-prompt "config/configs/sonfigs" concern is a
  hypothesized typo; the repo has `ari-core/ari/config/` (code that locates config),
  `ari-core/ari/configs/` (packaged default DATA), and top-level `ari-core/config/`
  (rubric/profile DATA). Irrelevant to 051; state "does not exist" for `sonfigs/` if asked.
- **Baseline-green before hard gate.** Run `check_prompt_snapshots.py --root .` and the
  SHA test on `main` first; only add the hard job if both are green today.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **051** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
