# Subtask 027: Add Docs Source Sync Checker Script

> Phase 8 — Quality Scripts
> Deliverable name (from `007_subtask_index.md` row 74): `check_docs_source_sync.py`
> Classification: **REVIEW_REQUIRED** (the script itself is a **DELETE_CANDIDATE / MERGE** candidate — see §7)
> Changes runtime code: **No** (see §16)

---

## 1. Goal

Decide and, if justified, implement a docs↔source **synchronization** checker that
catches drift the two existing gates do **not** already catch, without duplicating
them. The two existing gates are:

- `scripts/docs/check_doc_sources.py` (223 lines) — **forward** direction: every
  doc's front-matter `sources[].path` resolves on disk; `role` is in the vocabulary
  `{implementation, schema, config, prompt, test, vendor, doc}`; optional coverage
  gate under `--require-all`.
- `scripts/docs/check_ref_coupling.py` (182 lines) — **reverse, PR-diff** direction:
  a source changed on the branch must bump the referencing doc's `last_verified`
  (advisory by default; `--strict` → error).

The primary deliverable of this subtask is therefore a **decision gate** followed by
one of two narrow outcomes:

- **Outcome A (KEEP, minimal):** ship `scripts/check_docs_source_sync.py` covering
  **only** the one distinct dimension identified in §7 (trunk-state / already-merged
  staleness), delegating path-existence and PR-diff coupling to the existing pair.
- **Outcome B (MERGE / DELETE_CANDIDATE):** fold that dimension into
  `check_ref_coupling.py` as a new mode and record `check_docs_source_sync.py` as a
  DELETE_CANDIDATE that is never created. This is the outcome recommended by
  `009_quality_scripts_plan.md` §5.3.

Either outcome lands **advisory-only** (`--warning-only`, no hard CI gate) per the
Phase 8 warning-mode-first policy.

## 2. Background

`009_quality_scripts_plan.md` §4 (line 80) and §5.3 (lines 116–120) classify the
proposed `check_docs_source_sync.py` as **REVIEW_REQUIRED → likely MERGE /
DELETE_CANDIDATE** because "both directions are already covered." `007_subtask_index.md`
(row 74) nonetheless created **subtask 027** to formally resolve that review, while
`009_quality_scripts_plan.md` line 251 states the script is "intentionally **not
assigned a build subtask**." This planning doc reconciles the discrepancy: subtask
027 is the *review-and-resolve* task, and its acceptance criteria (§13) allow the
"create nothing" outcome as a first-class result.

The docs-source-sync **surface** is the per-doc YAML front-matter block, e.g. (from
`check_ref_coupling.py` docstring, lines 6–12):

```yaml
---
sources:
  - path: ari-core/ari/orchestrator
    role: implementation
last_verified: 2026-05-26
---
```

Ground-truth from the docs investigation (planning date 2026-07-01): **every declared
`sources[].path` currently resolves** — there is *no* front-matter path drift today —
and the published VitePress content is en 42 md / ja 41 / zh 41 (the single gap,
`reference/internal_boundaries.md`, is en-only by design). So a checker whose only job
is "declared paths resolve" would be green on day one and redundant with
`check_doc_sources.py`.

The house style for `scripts/docs/*` checkers (all confirmed by reading source):
`#!/usr/bin/env python3`, a module docstring citing a design doc, `argparse` + `--json`,
`REPO_ROOT = Path(__file__).resolve().parents[2]`, PyYAML as the only non-stdlib dep,
`exit 1` on error / `SystemExit(2)` on missing PyYAML, and a staged warning→error
rollout. `009_quality_scripts_plan.md` §7 (line 218) specifies that **new** source-code
gates live at `scripts/` top level (alongside `readme_sync.py`, 350 lines) with
`REPO_ROOT = ...parents[1]`, *not* under `scripts/docs/`.

## 3. Scope

- Perform the §7 decision gate: confirm whether a docs↔source sync dimension exists
  that is covered by **neither** `check_doc_sources.py` **nor** `check_ref_coupling.py`.
- Implement **exactly one** of Outcome A or Outcome B (§7), plus its allowlist/baseline
  and unit tests.
- Add the checker's documentation stub to `scripts/README.md` and (if Outcome A) the
  `scripts/docs/README.md`-style checker inventory in `docs/README.md` §"Source
  traceability", consistent with how the existing checker family is listed.
- Optionally emit a follow-up note (not an edit here) recommending an **advisory**
  `continue-on-error` wiring into `.github/workflows/docs-sync.yml`, matching the
  existing advisory steps `check_translation_freshness.py` / `check_doc_links.py`.

## 4. Non-Goals

- **No** new hard CI gate. This subtask does not turn any docs-sync check red on main.
- **No** re-implementation of forward path-existence (owned by `check_doc_sources.py`)
  or PR-diff reverse coupling (owned by `check_ref_coupling.py`). Duplicating either is
  explicitly forbidden by `009_quality_scripts_plan.md` §5.3.
- **No** change to the front-matter schema, the `role` vocabulary, or any doc content.
- **No** change to VitePress config, `docs/.vitepress/`, translation-parity policy, or
  the report/PDF sync (`sync_report_pdf.sh`).
- **No** fixing of the known, already-documented advisory drift (broken
  `_archive/refactor_audit.md` markdown links; the `ARI_AGENT_ENV_PATH` →
  `~/.ari/agent.env` prose in `reference/environment_variables.md:211`). Those are
  `check_doc_links` (advisory) / content-review concerns, out of scope here.
- **No** runtime-code, import, prompt, config, or frontend change (see §16).
- Does **not** address the `config/` vs `configs/` placement policy — that is subtask
  028 (`check_directory_policy.py`).

## 5. Current Files / Directories to Inspect

Existing gates and conventions (all real, verified):

- `scripts/docs/check_doc_sources.py` (223 lines) — forward path/role/coverage gate.
  Key surfaces: `VALID_ROLES` (lines 38–46), `EXEMPT_FILES` / `EXEMPT_DIR_SEGMENTS`
  (lines 51–60), `split_front_matter()` (76–87), `check_doc()` (105–166),
  `collect_docs()` (169–177).
- `scripts/docs/check_ref_coupling.py` (182 lines) — reverse PR-diff coupling gate.
  Key surfaces: `git()` (49–53), `parse_doc()` → `(sources, last_verified)` (68–94),
  `english_docs()` (101–105), `matches()` (108–110), the diff/merge-base logic (122–157).
- `scripts/readme_sync.py` (350 lines) — the top-level `scripts/` checker whose style
  and `REPO_ROOT = ...parents[1]` new checkers follow.
- `scripts/docs/` siblings for house style: `check_doc_links.py` (4892 B),
  `check_readme_parity.py`, `check_translation_freshness.py`, `check_site_i18n.py`,
  `check_report_cochange.py`, `check_i18n_js.py`.
- `scripts/README.md` (1507 B) and `scripts/docs/README.md` — where a new checker is
  indexed.

Data the checker reads (do not modify):

- `docs/**/*.md` front-matter (`sources:` + `last_verified:`). Published content:
  en 42 / ja 41 / zh 41 md. Exempt from `sources`: `docs/README.md`, the three
  `index.md` locale homes, and everything under `_archive/`, `node_modules/`,
  `.vitepress/` (see `check_doc_sources.py` lines 51–60).
- `.github/workflows/docs-sync.yml` — the workflow whose hard/advisory step layout an
  optional future wiring would mirror (hard: `check_doc_sources.py`; advisory:
  `check_translation_freshness.py`, `check_doc_links.py`).

Planning references:

- `docs/refactoring/009_quality_scripts_plan.md` §4 (line 80), §5.3 (116–120),
  §7 (lines 218–220, 251), §Open-questions (261–262).
- `docs/refactoring/007_subtask_index.md` rows 74–75, Phase 8 section (316–333).

Confirmed **absent** (net-new if Outcome A): `scripts/check_docs_source_sync.py`,
`scripts/quality/` directory. There is **no** `sonfigs/` anywhere in the repo (the token
in upstream prompts is a typo, not a real path).

## 6. Current Problems

1. **Redundancy risk.** A naive `check_docs_source_sync.py` that re-scans front-matter
   `sources[].path` for existence duplicates `check_doc_sources.py` verbatim, and a
   PR-diff re-verification duplicates `check_ref_coupling.py`. Both are already wired
   (`check_doc_sources.py` is a hard gate in `docs-sync.yml`). A duplicate adds
   maintenance burden with zero new coverage (`009_quality_scripts_plan.md` §5.3).
2. **The genuine gap the pair leaves open (the one thing worth building):**
   `check_ref_coupling.py` is a **diff gate** — it only fires when a source and its doc
   are touched *within the same branch/PR* (it needs `--base-ref`, default `origin/main`,
   and diffs `merge-base..HEAD`). It therefore **cannot** detect *already-merged*
   staleness: a source that was modified on `main` after a doc's `last_verified` in some
   earlier, already-merged PR that forgot to bump the date. That drift is invisible to
   both existing gates (`check_doc_sources.py` only checks path existence, not recency).
   No full-tree, trunk-state staleness check exists.
3. **Naming/assignment inconsistency.** `007_subtask_index.md` assigns subtask 027 while
   `009_quality_scripts_plan.md` line 251 says the script is deliberately unassigned.
   The implementer needs an explicit resolution (this doc provides it: 027 is the
   *review* task; "create nothing" is a valid completion).
4. **Layout drift risk.** If created under `scripts/docs/` it would inherit
   `parents[2]`; the correct home per `009_quality_scripts_plan.md` §7 is `scripts/`
   top level with `parents[1]`. Getting this wrong silently breaks `REPO_ROOT`.

## 7. Proposed Design / Policy

### 7.1 Decision gate (do this first)

Enumerate every docs↔source invariant and mark who owns it:

| Invariant | Owner today | Gap? |
| --- | --- | --- |
| Declared `sources[].path` resolves on disk | `check_doc_sources.py` (hard) | no |
| `role` in vocabulary | `check_doc_sources.py` | no |
| Coverage (every live doc declares `sources`) | `check_doc_sources.py --require-all` | no |
| Source changed *in this PR* → doc `last_verified` bumped | `check_ref_coupling.py` (advisory / `--strict`) | no |
| **Source last-modified on `main` is newer than doc `last_verified` (already-merged drift)** | **nobody** | **YES** |
| ja/zh `last_verified` ≥ en | `check_translation_freshness.py` | no |
| Broken markdown links (incl. `_archive`) | `check_doc_links.py` (advisory) | no |

The single uncovered dimension is **trunk-state staleness** (row in bold). Everything
else is covered; a checker touching those rows is redundant → DELETE_CANDIDATE for that
scope.

### 7.2 Outcome A — minimal standalone checker (KEEP the new file only for the gap)

Create `scripts/check_docs_source_sync.py` that implements **only** trunk-state
staleness and nothing else:

- Convention: `#!/usr/bin/env python3`; module docstring citing this subtask and
  `009_quality_scripts_plan.md` §5.3; `argparse`; PyYAML-only; **`REPO_ROOT =
  Path(__file__).resolve().parents[1]`** (top-level `scripts/`, like `readme_sync.py`).
- **Reuse, do not fork:** import `split_front_matter` / `parse_doc` semantics from
  `check_ref_coupling.py` (either import the module via `sys.path` insertion of
  `scripts/docs`, or factor a tiny shared helper — but keep this subtask's footprint to
  one new file; a shared `scripts/quality/_common.py` is subtask 031's concern, do not
  introduce it here).
- Algorithm: for each English master doc with `sources` + a `last_verified` date, for
  each declared source path `s`, compute the **last commit date** touching `s`
  (`git log -1 --format=%cs -- <s>`; for a directory source this is the newest commit
  under it). If that date is **strictly after** `last_verified`, report the doc as
  *stale* (finding: doc, `last_verified`, source, source's last-commit date).
- Only English masters are evaluated (mirrors `check_ref_coupling.py`; ja/zh staleness
  is `check_translation_freshness.py`'s job).
- Flags (mirror the family + the §7 CLI contract of `009_quality_scripts_plan.md`):
  `--json`, `--warning-only` (force exit 0; **default posture**), and an
  allowlist/baseline so the current ~124 doc↔source pairs that are already stale-by-date
  do not turn into red CI on day one. Exit convention: `0` clean or `--warning-only`;
  `1` findings above baseline when not warning-only; `2` missing PyYAML (matches
  `check_doc_sources.py`'s `SystemExit(2)`).
- **Allowlist/baseline:** freeze the current findings into
  `scripts/check_docs_source_sync.allow.yaml` (a `known-offenders` list keyed by
  `doc + source`), so the checker starts green and only future *new* staleness can be
  ratcheted later via a `--fail-on-regression`-style comparison.
- **Landed advisory only.** If wired at all, add an advisory `continue-on-error: true`
  step to `docs-sync.yml` — but wiring the workflow is a **follow-up**, out of this
  subtask's runtime-safe scope.

### 7.3 Outcome B — MERGE into `check_ref_coupling.py` (recommended by 009 §5.3)

If review concludes a *separate file* is not warranted, add a `--trunk` (a.k.a.
`--full-history`) mode to `check_ref_coupling.py` that performs the §7.2 algorithm
instead of the merge-base diff, keeping one file responsible for the reverse direction.
Then record `check_docs_source_sync.py` as **DELETE_CANDIDATE** in
`007_subtask_index.md` / `009_quality_scripts_plan.md` and create **no** new script.
Note: this edits `check_ref_coupling.py`, which is CI-wired (advisory in
`docs-change-coupling.yml`); guard the new mode behind the explicit flag so the default
`--base-ref` behavior is byte-for-byte unchanged.

### 7.4 Policy statement

The implementer **must** pick A or B and record the rationale in the doc's §17 log and
in `009_quality_scripts_plan.md` §5.3 / §Open-questions (line 262). "Neither dimension
is worth a gate → DELETE_CANDIDATE, create nothing but update the two planning docs" is
an acceptable third resolution and satisfies §13.

## 8. Concrete Work Items

1. Run the §7.1 decision gate; write the conclusion (A / B / drop) into §17 and into
   `009_quality_scripts_plan.md` §5.3.
2. **If Outcome A:**
   1. Create `scripts/check_docs_source_sync.py` implementing §7.2 (trunk-state
      staleness only). `REPO_ROOT = parents[1]`. `--json`, `--warning-only`.
   2. Generate the baseline `scripts/check_docs_source_sync.allow.yaml` from the current
      tree so the checker exits 0 by default.
   3. Add unit tests under `scripts/tests/` (or the repo's script-test location — see
      §12) with a temp git repo fixture: doc newer than source (clean), source newer
      than `last_verified` (stale), allowlisted stale pair (suppressed), doc without
      `last_verified` (skipped), doc without `sources` (skipped).
   4. Index the checker in `scripts/README.md` and the `docs/README.md` §"Source
      traceability" checker list.
3. **If Outcome B:**
   1. Add a `--trunk` mode to `scripts/docs/check_ref_coupling.py`, default behavior
      unchanged; extend that file's tests.
   2. Mark `check_docs_source_sync.py` DELETE_CANDIDATE in `007_subtask_index.md`
      (row 74) and `009_quality_scripts_plan.md` (§4 table / §5.3), create no new file.
4. Do **not** wire any hard CI gate. Optionally draft (not commit) the advisory
   `docs-sync.yml` step text in §17 for a future subtask.
5. Run the §12 gates from repo root.

## 9. Files Expected to Change

**Outcome A (new-file path):**
- `scripts/check_docs_source_sync.py` — **NEW** (net-new; confirmed absent today).
- `scripts/check_docs_source_sync.allow.yaml` — **NEW** frozen baseline.
- `scripts/tests/test_check_docs_source_sync.py` (or repo script-test location) — **NEW**.
- `scripts/README.md` — index the new checker (1-line entry).
- `docs/README.md` — add to the §"Source traceability" checker family list.
- `docs/refactoring/009_quality_scripts_plan.md` — record the §5.3 resolution.

**Outcome B (merge path):**
- `scripts/docs/check_ref_coupling.py` — add `--trunk` mode (default unchanged).
- test file for `check_ref_coupling.py` (extend existing / add new).
- `docs/refactoring/007_subtask_index.md` (row 74) + `009_quality_scripts_plan.md` —
  record DELETE_CANDIDATE; **no** new `scripts/check_docs_source_sync.py`.

No other files change. **No** file under `ari-core/`, no workflow YAML edit in this
subtask (advisory wiring is a follow-up).

## 10. Files / APIs That Must Not Be Broken

- **CLI `ari` / `ari.public.*` / MCP `ari-skill-*` / dashboard API / checkpoint & config
  formats** — untouched; this is `scripts/` tooling only.
- `scripts/docs/check_doc_sources.py` — must keep passing (hard gate in `docs-sync.yml`);
  do not alter its forward semantics.
- `scripts/docs/check_ref_coupling.py` — under Outcome B, its default `--base-ref`
  behavior and its advisory role in `docs-change-coupling.yml` must be byte-identical
  when the new flag is absent.
- `.github/workflows/docs-sync.yml`, `readme-sync.yml`, `docs-change-coupling.yml`,
  `pages.yml`, `refactor-guards.yml` — the 5 workflows must not be rewritten; no hard
  gate added.
- Front-matter schema (`sources:` list of `{path, role}` + `last_verified`) — read-only;
  no doc content or schema change.

## 11. Compatibility Constraints

- New tooling is **additive** and **advisory** by default (`--warning-only`); it can
  never fail an unrelated PR at introduction (Phase 8 warning-mode-first policy,
  `009_quality_scripts_plan.md` §Guiding-principles line 18).
- The checker consumes existing front-matter as-is; no new required front-matter keys,
  so all 42 en / 41 ja / 41 zh docs remain valid without edits.
- Use PyYAML only (already the sole non-stdlib dep across the checker family and
  installed in `docs-sync.yml`). Do not add dependencies (`radon`, `vulture`, etc. are
  not installed and out of scope).
- Git invocation must degrade gracefully when a base/history is unavailable (mirror
  `check_ref_coupling.py`'s `try/except subprocess.CalledProcessError`, lines 122–130):
  fail **open** in advisory mode, exit 0.
- `REPO_ROOT = parents[1]` for a top-level `scripts/` file — do **not** copy the
  `scripts/docs/` `parents[2]` convention.

## 12. Tests to Run

From repo root:

- `python -m compileall scripts` (and `scripts/docs` if Outcome B) — syntax check.
- `python -m compileall .` — whole-tree syntax sanity.
- `ruff check .` — lint (ruff is available; keep the new file clean — the repo has a
  large pre-existing ruff-finding backlog, so scope lint attention to changed files).
- `pytest -q scripts/tests/test_check_docs_source_sync.py` (Outcome A) or the
  `check_ref_coupling` test (Outcome B). If the repo has no `scripts/tests/` yet, place
  tests where `run_all_tests.sh` / `pytest.ini` will collect them and note the location
  in §17.
- `pytest -q` — full suite must stay green (this subtask adds only tooling).
- Manual smoke: `python scripts/check_docs_source_sync.py --json` (Outcome A) exits 0
  with the frozen allowlist; `python scripts/docs/check_doc_sources.py` and
  `python scripts/docs/check_ref_coupling.py --json` still pass unchanged.

Frontend (`npm test` / `npm run build`): **not applicable** — no frontend change.

## 13. Acceptance Criteria

- The §7.1 decision gate is documented with an explicit A/B/drop resolution recorded in
  this doc's §17 **and** in `009_quality_scripts_plan.md` §5.3.
- If a script/mode is produced, it covers **only** the trunk-state-staleness dimension
  and provably does **not** duplicate `check_doc_sources.py` (forward) or the default
  `check_ref_coupling.py` (PR-diff reverse) — reviewer can point to the specific
  finding class each tool owns.
- The checker (or new mode) exits **0** on the current tree by default (frozen
  allowlist / `--warning-only`); it is not wired as a hard CI gate.
- `--json` output is present and machine-parseable (aggregator-ready for subtask 031).
- All §12 gates pass; the existing `check_doc_sources.py` and `check_ref_coupling.py`
  behavior is unchanged.
- No runtime code, no workflow hard gate, no `ari-core/` file, no doc-content change.

## 14. Rollback Plan

- Outcome A: `git rm scripts/check_docs_source_sync.py`,
  `scripts/check_docs_source_sync.allow.yaml`, the test file; revert the 1-line
  `scripts/README.md` / `docs/README.md` index entries. Because nothing imports the
  script and no workflow references it, removal is inert and cannot affect runtime, CI
  hard gates, or the `ari` package.
- Outcome B: `git revert` the `check_ref_coupling.py` change; the `--trunk` mode is
  behind an explicit flag, so reverting restores byte-identical default behavior. Revert
  the planning-doc DELETE_CANDIDATE note.
- No data migration, no checkpoint/config impact, no user-visible surface to roll back.

## 15. Dependencies

Per the authoritative dependency graph (`003 -> 027`) and `007_subtask_index.md` row 74:

- **Depends on: subtask 003** (`consolidate_config_configs_sonfigs`). Rationale: 003
  finalizes the `ari-core/ari/config/` (locator code) vs `ari-core/ari/configs/`
  (packaged defaults) vs top-level `ari-core/config/` (rubric data) layout and confirms
  **no `sonfigs/`**. Docs declare `sources[].path` pointing at these config files;
  building this checker's frozen baseline (§7.2) **after** the config layout is final
  avoids an immediately-stale allowlist. The staleness algorithm itself is
  layout-agnostic, so the dependency is an **ordering/baseline** constraint, not a code
  coupling.
- **Transitive:** subtask 003 is a runtime-code change and is itself gated by the
  inventory subtasks **001** (`measure_complexity_and_dependencies`) and **002**
  (`inventory_legacy_obsolete_and_duplicate_code`). This subtask (027) is **not** a
  runtime-code change, so it does not directly require the full inventory gate beyond
  what 003 already pulls in.
- **Sibling (no ordering):** subtask 028 (`add_directory_policy_checker_script`) also
  depends on 003; 027 and 028 are independent of each other.
- **Enables:** subtask 031 (`add_quality_report_generator`) can consume this checker's
  `--json` output once it exists (031 depends on 001, not on 027; consumption is
  best-effort).

## 16. Risk Level

**Low.**

- **Changes runtime code: No.** The deliverable is a standalone `scripts/` tool (or an
  advisory-flag addition to an existing `scripts/docs/` tool). It is not part of the
  `ari` Python package, is not imported by any runtime module, and is not wired into any
  workflow as a hard gate in this subtask. This matches `007_subtask_index.md` row 74
  (runtime-code-change = **No**).
- Blast radius is a single new file (Outcome A) or one flag-guarded mode (Outcome B).
  The main risk is **building a redundant duplicate** — mitigated by the §7.1 decision
  gate and the §13 non-duplication acceptance criterion. The secondary risk is a git
  subprocess edge case (shallow clone / renamed source path) — mitigated by fail-open
  advisory behavior mirroring `check_ref_coupling.py`.

## 17. Notes for Implementer

- **Start with the decision gate, not with code.** The strong prior from
  `009_quality_scripts_plan.md` §5.3 is that a *new competing script is redundant*. Only
  the trunk-state-staleness slice (§6.2 / §7.1) is genuinely uncovered. If you cannot
  articulate a finding that neither existing tool produces, the correct completion is
  **drop** (update the two planning docs, create nothing).
- Prefer **Outcome B (merge into `check_ref_coupling.py` via `--trunk`)** if a distinct
  dimension is confirmed — it is the plan-recommended shape and keeps the "reverse
  direction" in one file. Choose Outcome A only if you want the trunk check to run
  independently of the PR-diff check in CI.
- Reuse `check_ref_coupling.py`'s `parse_doc()` (lines 68–94) and `split_front_matter()`
  (56–65) rather than re-deriving front-matter parsing; keep behavior identical
  (English masters only; skip docs lacking `sources` or `last_verified`).
- Watch the `REPO_ROOT` depth: **`parents[1]`** for a top-level `scripts/` file vs the
  `parents[2]` used inside `scripts/docs/` (`check_doc_sources.py` line 62). A wrong
  depth silently mis-roots every path.
- The current tree has **no front-matter path drift** and PDFs/i18n are in sync; expect
  the *staleness* baseline to be non-empty simply because `last_verified` dates predate
  routine source commits. Freeze that into the allowlist so the checker starts green;
  do **not** attempt to "fix" dates by bumping `last_verified` across docs (that is a
  content-review task, out of scope).
- Record the chosen outcome and rationale here and in `009_quality_scripts_plan.md`
  §Open-questions line 262 ("whether the review yields a genuine new dimension").
- Draft (do not commit) advisory workflow wiring for a follow-up:
  a `continue-on-error: true` step in `.github/workflows/docs-sync.yml` alongside the
  existing advisory `check_translation_freshness.py` / `check_doc_links.py` steps.
- Reminder on vocabulary: this is REVIEW_REQUIRED work; the candidate file is a
  DELETE_CANDIDATE / MERGE target — do not use the word "deprecated" (reserved for
  external contracts), and do not touch any external contract surface (CLI, `ari.public`,
  MCP, dashboard API, checkpoint/config formats).

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **027** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
