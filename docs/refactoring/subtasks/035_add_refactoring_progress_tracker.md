# Subtask 035: Add Refactoring Progress Tracker

> Phase 10: Docs and Tests · Risk: Low · Runtime code change: **No** (see Section 16) · Depends on: — (root; no incoming graph edge)
>
> Planning document only. Nothing here modifies runtime code, imports, prompts,
> configs, workflows, frontend, or directory names. It hands a fresh coding
> session an executable plan whose sole output is a documentation/status
> artifact under `docs/refactoring/`. All paths are repository-real and verified
> against the tree at planning date 2026-07-01 (ari-core 0.9.0, branch `main`).

## 1. Goal

Create the single **living status ledger** for the ARI refactoring program: one
Markdown tracker that records, for each of the **73 subtasks** defined in
`docs/refactoring/007_subtask_index.md` (IDs `001`–`073`, no gaps — verified), a
mutable **execution status** (not-started / in-progress / blocked / in-review /
done / deferred), its owning PR/commit, and a last-updated stamp — on top of the
immutable scope/dependency metadata that already lives in the 007 index.

The deliverable answers, at a glance, the three questions the numbered planning
docs cannot: *what is done, what is in flight, and what is unblocked next* — while
respecting the dependency graph and the nine inventory gates (`001, 002, 020, 036,
045, 053, 059, 060, 067`) that must precede any runtime-code change.

Per the authoritative ledger, `035 add_refactoring_progress_tracker` is a Phase-10
row (`007_subtask_index.md:82`) with **Risk = Low**, **Runtime Code Change = No**,
**Can-Run-Independently = Yes**, and **Depends = —**; the master plan describes it
as the "progress doc for this program" (`000_master_refactoring_plan.md:373`) and a
Phase-10 member alongside `017, 018, 034` (`:363`). This is a
documentation-tracking subtask: it **changes no runtime code**, it writes a status
artifact, and it introduces no script, gate, or CI step.

## 2. Background

- **Placement.** 035 is one of four Phase-10 ("Docs and Tests") members —
  `017, 018, 034, 035` (`007_subtask_index.md:363`, `000_master_refactoring_plan.md:363`).
  Its index row (`007_subtask_index.md:82`) is:
  `| 035 | add_refactoring_progress_tracker | 10 | Low | — | Progress-tracker doc | No | Yes |`.
  It is a **root** in the dependency graph (no incoming edge — listed among the
  roots at `000_master_refactoring_plan.md:510` and scheduled in "Wave 2 …
  independent" at `:528`).
- **What already exists as planning surface** (verified `ls`):
  - `docs/refactoring/007_subtask_index.md` (38,684 B) — the **authoritative
    73-row ledger**: ID, name, phase, risk, `Depends`, deliverable, Runtime-Code-Change,
    Can-Run-Independently, plus the full dependency graph and a "Recommended
    Execution Order" (waves) at `:517-533`. This is the single source of truth for
    subtask **scope and ordering**.
  - `docs/refactoring/000_master_refactoring_plan.md` (41,473 B) — phases, roots,
    inventory-gate constraint (`:512-513`), execution waves.
  - `docs/refactoring/{001..014}_*.md` — the 15 area/design reports.
  - `docs/refactoring/subtasks/*.md` — the per-subtask planning docs, **being
    populated in parallel** at planning time (a growing subset; e.g. `001`–`027`,
    `029`, `030`, `031` present in one snapshot). This directory is the natural
    place a reader looks to see "is subtask N planned yet", but it carries **no
    status** — a present file only means the *plan* was written, not that the code
    landed.
  - `docs/refactoring/reports/` — **present, empty** (verified `ls`); designated as
    the report/roll-up home (subtask 019's `final_quality_report.*` lands here, per
    `019_final_quality_report.md:97-99`).
- **The gap this subtask fills.** There is today **no single artifact that records
  execution state.** The 007 index encodes *dependencies* but is deliberately
  static (it is not rewritten as subtasks land); the `subtasks/*.md` files encode
  *plans* but not *completion*; `CHANGELOG.md` (129,594 B) records shipped user-facing
  changes but is not keyed by subtask ID and does not show "unblocked-next". A
  maintainer coordinating a 73-subtask, 11-phase program has no dashboard.
- **Downstream consumer.** Subtask 019 (the terminal Final Quality Report)
  explicitly plans to "update the progress tracker (subtask 035 deliverable, if
  present) to mark the program done"
  (`019_final_quality_report.md:107-108`, `:296-297`, `:314-315`). So 035's output
  is a named input to 019 — the tracker must have a stable, discoverable path.
- **Vocabulary note.** This subtask introduces an *execution-status* vocabulary
  (§7.3). Keep it distinct from the master-prompt **code-classification** vocabulary
  (`KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED`),
  which describes what happens to a *code artifact*, not the *progress* of a
  subtask. The tracker may optionally carry a subtask's dominant code-classification
  as an extra column, but "done" ≠ "KEEP".

## 3. Scope

In scope (pure documentation/status artifact, zero runtime code change):

- **Create the tracker** `docs/refactoring/reports/progress.md`: a one-row-per-subtask
  table covering all 73 subtask IDs from `007_subtask_index.md`, with a mutable
  **Status** column plus **Owner/PR**, **Last-updated**, and a free-text **Notes**
  column, and a small **phase rollup** and **inventory-gate status** summary at the
  top.
- **Optionally create a machine-readable mirror** `docs/refactoring/reports/progress.json`
  (stable schema, one object per subtask) so a later CI/aggregator step (e.g. 019
  or a quality subtask) can read status without parsing Markdown.
- **Seed the initial statuses** from ground truth *observable at execution time*:
  which `subtasks/*.md` plans exist (planning done ≠ code done), and which subtask
  PRs/commits have merged (read `git log`). Anything not evidenced is `not-started`.
- **Define and document the update protocol** (§7.6) so the tracker stays a living
  document: which field flips when a subtask PR lands, and the single invariant that
  the tracker's row-set equals the 007 index's row-set.
- Add a one-line cross-link **into** `docs/refactoring/000_master_refactoring_plan.md`
  and/or `007_subtask_index.md` pointing at the tracker (OPTIONAL, doc prose only —
  see §9).

## 4. Non-Goals

- **Do NOT duplicate the 007 index as a second source of truth.** The tracker
  mirrors the index's *identity* columns (ID, name, phase, `Depends`) for
  readability but adds **only** the mutable status dimension. Scope/ordering changes
  are made in `007_subtask_index.md`, never invented in the tracker.
- **Do NOT build a generator or validator script.** No `scripts/*.py`,
  no `scripts/docs/*.py`. Auto-generating or gate-checking the tracker is *tooling*
  and belongs to the quality-script subtasks (025–031, 043, 054–058) — building one
  here would cross into their territory and would add runtime/tooling code. If a
  "tracker rows == index rows" validator is ever wanted, it is a **REVIEW_REQUIRED**
  follow-up folded into an existing checker subtask, not part of 035.
- **Do NOT add a CI step or workflow.** The five existing workflows
  (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`,
  `refactor-guards.yml`) are not touched. Workflow integration is the Phase-9
  cluster (`045 → 046–052`).
- **Do NOT add VitePress `sources:` front-matter** to the tracker.
  `docs/refactoring/**` is a planning workspace, **not published** VitePress content
  (per `017_update_docs_and_examples.md:71,495-500`); adding `sources:` front-matter
  would create a coverage obligation under the (currently-off) `check_doc_sources.py
  --require-all` flag. The tracker is a plain Markdown table.
- **Do NOT modify runtime code, imports, prompts, configs, frontend, workflows, or
  directory names.** The footprint is confined to `docs/refactoring/reports/` plus
  the optional one-line cross-link edits in §9.
- **Do NOT use the word "deprecated"** for any internal subtask/code state; it is
  reserved for external contracts. A subtask that removes internal code is tracked as
  `done` with a `MOVE_TO_LEGACY`/`DELETE_CANDIDATE` classification note, never
  "deprecated".
- **Do NOT invent status.** A subtask with no merged PR and no landed artifact is
  `not-started`, never "done". If evidence is ambiguous, mark `in-progress` with a
  note, not a guess.

## 5. Current Files / Directories to Inspect

Tracker target (write here):

- `docs/refactoring/reports/` — **exists, empty** (verified `ls`). Sibling of the
  numbered planning docs and of `docs/refactoring/subtasks/`. Also the home of
  subtask 019's `final_quality_report.*` (`019_final_quality_report.md:97-99,141-143`).

Source-of-truth inputs the tracker mirrors (read, do not edit except the optional
cross-link):

| Path | What to read from it |
| --- | --- |
| `docs/refactoring/007_subtask_index.md` (38,684 B) | The 73 subtask rows (`:82` is the 035 row); the `Depends` column; the dependency graph and "Recommended Execution Order" waves (`:517-533`); the roots list and inventory-gate constraint. **The tracker's row set must equal this file's row set.** |
| `docs/refactoring/000_master_refactoring_plan.md` (41,473 B) | Phase membership (Phase 10 = `017,018,034,035` at `:363`); roots (`:510`); the nine inventory gates (`:512-513`); wave scheduling (`:528`). |
| `docs/refactoring/subtasks/*.md` | Which per-subtask **plans** exist (a growing set, populated in parallel). Presence = plan-written, **not** code-landed. Use only as a weak "planning-done" signal. |
| `docs/refactoring/{001..014}_*.md` | Area/design reports; not per-subtask, but the tracker header may link the relevant area report per phase. |
| `CHANGELOG.md` (129,594 B) | Shipped user-facing changes; **not keyed by subtask ID** — use only as corroborating evidence when deciding a subtask is `done`. |

Evidence sources for seeding status (read-only):

- `git log --oneline` / `git log --grep='<subtask-id>'` — the primary evidence that a
  subtask's code actually merged (vs. just being planned).
- Presence of a subtask's *deliverable* on disk (e.g. `scripts/check_import_boundaries.py`
  for 026 — **does not exist** today; `scripts/generate_quality_report.py` for 031 —
  **does not exist** today; both confirmed absent per `019_final_quality_report.md:147-159`).

Gate-avoidance checks (confirm the tracker trips no existing gate):

- `scripts/readme_sync.py` — its `--check` gate only validates directories that
  **already contain a `README.md`** (it `rglob`s `README.md` and checks each one's
  `## Contents` block; `readme_sync.py:227`). `docs/refactoring/`, `docs/refactoring/reports/`,
  and `docs/refactoring/subtasks/` have **no `README.md`** (verified `ls`), so adding
  `progress.md` there does **not** create a readme-sync obligation and does not need a
  companion `README.md`. Confirm this still holds at execution time.
- `.github/workflows/docs-sync.yml`, `docs-change-coupling.yml`, `readme-sync.yml`,
  `refactor-guards.yml`, `pages.yml` — confirm none of them scan `docs/refactoring/**`
  as published content (`refactor-guards.yml` is the `~/.ari` diff-grep + HOME-write
  guard; a status doc with no `~/.ari` reference and no HOME write is inert to it).

## 6. Current Problems

1. **No execution-state artifact exists.** `007_subtask_index.md` encodes
   *dependencies* but is static; `subtasks/*.md` encode *plans* but not *completion*;
   `CHANGELOG.md` records shipped changes but is not keyed by subtask ID. There is no
   single place that shows done / in-flight / unblocked-next for the 73 subtasks.
2. **"Plan exists" is silently conflated with "done".** A reader browsing
   `docs/refactoring/subtasks/` sees `NNN_*.md` files and may assume the work landed;
   in reality those are planning docs written ahead of implementation (this very
   subtask, 035, is being planned before any tracker exists).
3. **Dependency readiness is hard to compute by hand.** Whether a subtask is
   *unblocked* requires cross-referencing its `Depends` value and the nine inventory
   gates against the *current* completion set — a join no existing artifact performs.
4. **Subtask 019 has an unmet input.** 019 plans to update "the subtask-035 progress
   tracker (if it exists)" (`019_final_quality_report.md:107-108,314-315`) — but no
   such tracker exists yet, so 019 cannot mark the program done against a real file.
5. **Numbering drift risk.** Two planning docs already disagree on some
   subtask→script numbers (documented at `019_final_quality_report.md:54-65`). A
   tracker that re-encodes scope would add a *third* place to drift; the design (§7.4)
   avoids this by making the tracker status-only and pinning the 007 index as
   authoritative for identity/scope.

## 7. Proposed Design / Policy

**Classification of the 035 deliverable itself: KEEP** — a net-new status artifact
under `docs/refactoring/reports/`; no existing file is superseded, adapted, merged,
moved, or deleted. The tracker *records* other subtasks' classifications; it does not
apply any.

### 7.1 Files and placement

Produce, under the existing empty `docs/refactoring/reports/`:

- `docs/refactoring/reports/progress.md` — the human-readable living tracker
  (**required deliverable**).
- `docs/refactoring/reports/progress.json` — a machine-readable mirror, one object
  per subtask (**recommended**; enables 019 / future CI to read status without
  parsing Markdown).

Rationale for `reports/`: it is the already-designated roll-up home (019 writes there)
and it is **not** under readme-sync or VitePress-publish coverage (§5), so the tracker
introduces no gate obligation. (Alternative placements considered and rejected:
`docs/refactoring/PROGRESS.md` — pollutes the numbered-planning-doc namespace;
repo-root — would be VitePress/readme-sync adjacent. Pick `reports/progress.md`.)

### 7.2 Tracker table schema

One row per subtask ID `001`–`073`. Columns:

| Column | Source / meaning | Mutable? |
| --- | --- | --- |
| `ID` | subtask id, zero-padded (`035`) | no (from 007 index) |
| `Name` | `add_refactoring_progress_tracker` | no (from 007 index) |
| `Phase` | integer phase (10) | no (from 007 index) |
| `Depends` | the `Depends` value verbatim (`—` or predecessor id) | no (from 007 index) |
| `Runtime code change` | Yes/No (from index column) | no (from 007 index) |
| **`Status`** | one of the §7.3 vocabulary | **yes** |
| **`Owner / PR`** | PR number or merge SHA, or `—` | **yes** |
| **`Last updated`** | ISO date of the last status flip | **yes** |
| **`Classification`** | dominant code-classification (`KEEP`/`ADAPT`/…) or `—` for doc-only | yes (optional) |
| **`Notes`** | blockers, links, REVIEW_REQUIRED flags | **yes** |

The identity columns are a *read-only mirror* of the 007 index for legibility; the
five bold columns are the tracker's own state. To keep the mirror honest, add an
explicit header line: "Identity columns (ID/Name/Phase/Depends/Runtime) mirror
`007_subtask_index.md`; if they disagree, the index wins."

### 7.3 Status vocabulary (execution state)

A small, closed set — **distinct** from the code-classification vocabulary:

- `not-started` — no plan-implementation work merged (default seed).
- `in-progress` — a branch/PR is open or partial work landed.
- `blocked` — a `Depends` predecessor or an inventory gate is not yet `done`.
- `in-review` — implementation complete, PR under review.
- `done` — merged and its deliverable is present/verified on disk.
- `deferred` — intentionally postponed (record why in Notes).

Add a legend mapping each status to its definition at the top of `progress.md`.

### 7.4 Single-source-of-truth discipline

- **The 007 index owns identity, phase, dependencies, and ordering.** The tracker
  owns **only** status. This prevents a third numbering source (§6.5).
- **Row-set invariant:** the tracker must contain exactly the 73 subtask IDs present
  in `007_subtask_index.md` — no more, no fewer. If the index gains/loses a subtask,
  the tracker is updated in the same change.
- If a tracker identity cell ever disagrees with the index, the index is correct and
  the tracker is fixed (never the reverse).

### 7.5 Rollups

At the top of `progress.md`, above the big table, include:

- **Phase rollup** — for each populated phase (the master plan populates phases up
  through 11; `007_subtask_index.md:382-390` records phases 12/13 as "does not
  exist" here): counts of `done / in-progress / blocked / not-started` and a
  `done/total` fraction.
- **Inventory-gate status** — an explicit line for each of the nine gates (`001, 002,
  020, 036, 045, 053, 059, 060, 067`; `000_master_refactoring_plan.md:512-513`)
  showing done/not, because *every* runtime-code-change subtask is transitively
  blocked until these are `done`.
- **Unblocked-next** — a short list of `not-started` subtasks whose `Depends`
  predecessor(s) and applicable inventory gates are all `done` (computed by hand or
  from `progress.json`).

### 7.6 Update protocol (keeps it a living doc)

Document, inside `progress.md` itself, the rule for keeping it current:

1. When a subtask's implementation PR merges, flip its `Status` to `done`, set
   `Owner / PR` to the merge SHA/PR number, and stamp `Last updated`.
2. When a PR opens, set `in-progress` (or `in-review` once ready).
3. Re-evaluate every `blocked` row whose predecessor just went `done`; promote to
   `not-started`/`in-progress` and refresh **Unblocked-next**.
4. Keep `progress.md` and `progress.json` in lock-step (both updated in the same
   commit) — mirror the tri-file lock-step discipline the docs subsystem already uses.
5. **Determinism (design principle P2):** all status values are derived from
   observable evidence (merged SHA, deliverable-on-disk), not inference; no LLM/network
   calls are involved in maintaining the tracker.

### 7.7 `progress.json` shape (recommended)

A stable, flat schema so downstream tooling can consume it:

```json
{
  "generated": "2026-07-01",
  "source_of_truth": "docs/refactoring/007_subtask_index.md",
  "subtasks": [
    {"id": "035", "name": "add_refactoring_progress_tracker", "phase": 10,
     "depends": [], "runtime_code_change": false,
     "status": "in-progress", "owner": "", "last_updated": "2026-07-01",
     "classification": "KEEP", "notes": ""}
  ]
}
```

The Markdown table and JSON must be mutually consistent (same 73 ids, same statuses).

### 7.8 Warning-mode posture

The tracker is **advisory**: it records state; it does not fail CI (there is no gate
for it, by design — §4). It never *blocks* a subtask; it only *reports* that a
subtask is blocked by its dependencies.

## 8. Concrete Work Items

1. **Enumerate the 73 subtask rows** from `docs/refactoring/007_subtask_index.md`
   (IDs `001`–`073`, verified no gaps) into the tracker's identity columns
   (ID/Name/Phase/Depends/Runtime). Do not add or drop any id.
2. **Seed status from evidence.** For each id: default `not-started`; upgrade to
   `done` only if a merged PR/commit (`git log`) and, where applicable, the
   deliverable on disk confirm it; mark `in-progress`/`in-review` for open work; mark
   `blocked` where a `Depends` predecessor or an applicable inventory gate is not yet
   `done`. Record evidence in Notes. Do not treat a present `subtasks/NNN_*.md` as
   `done` (it means the plan exists, not the code).
3. **Compute the rollups** (§7.5): phase `done/total`, the nine inventory-gate lines,
   and the Unblocked-next list.
4. **Write `docs/refactoring/reports/progress.md`** — legend + rollups + the 73-row
   table + the §7.6 update protocol embedded at the bottom.
5. **Write `docs/refactoring/reports/progress.json`** (recommended) mirroring the
   table; verify row-count and per-id status parity with the Markdown.
6. **(Optional) Add a one-line cross-link** into
   `docs/refactoring/000_master_refactoring_plan.md` (and/or `007_subtask_index.md`)
   pointing readers at `reports/progress.md`. Keep it to a single sentence; do not
   restructure those docs.
7. **Self-verify** (§12) and confirm `git status` shows only files under
   `docs/refactoring/reports/` (plus the optional one-line cross-link edits).

## 9. Files Expected to Change

Created by this subtask (status artifacts):

- `docs/refactoring/reports/progress.md` — **new**, the living tracker (required).
- `docs/refactoring/reports/progress.json` — **new**, machine-readable mirror
  (recommended).

Optionally edited (documentation prose only, single-line cross-link, no runtime code):

- `docs/refactoring/000_master_refactoring_plan.md` — optional one-line pointer to the
  tracker.
- `docs/refactoring/007_subtask_index.md` — optional one-line pointer to the tracker.

Explicitly **NOT** changed: any file under `ari-core/ari/**`, `ari-skill-*/**`,
`ari-core/ari/viz/frontend/**`, `.github/workflows/**`, `scripts/**` (no generator or
validator is built), `config/`, `configs/`, prompt templates, `CHANGELOG.md` (035 does
not write a changelog entry — that is 019's optional completion note), or any
checkpoint/output/config format. No new per-directory `README.md` is needed
(`docs/refactoring/reports/` is not under readme-sync coverage — §5).

## 10. Files / APIs That Must Not Be Broken

035 writes only a status doc, so nothing *should* break — but the subtask must not
touch any preserved contract while reading ground truth:

- **CLI `ari`** (`ari = ari.cli:app`, typer) — subcommands in
  `ari-core/ari/cli/{commands,run,bfts_loop,lineage,migrate,projects}.py`. Untouched.
- **`ari.public.*`** — `claim_gate, config_schema, container, cost_tracker, llm,
  paths, run_env, verified_context`. Untouched.
- **14 `ari-skill-*` MCP servers** (`src/server.py` each) and their tool contracts;
  the sanctioned `ari-core → ari_skill_memory` import edge. Untouched.
- **Dashboard API** — `ari-core/ari/viz/routes.py` + `api_*.py` + `websocket.py`
  consumed by `frontend/src/services/api.ts`; base port 8765. Untouched.
- **Checkpoint / config / output formats** — `ari-core/ari/checkpoint.py`; YAML under
  `ari-core/config/` + `ari-core/ari/configs/`. The config trio (`ari/config/` code
  vs `ari/configs/` packaged data vs top-level `config/` rubric data) is **not**
  restructured here. **No `sonfigs/` directory exists** — that upstream token is a
  typo, not a path in this repo; the tracker must not reference it.
- **Existing docs gates** — `scripts/docs/*.py`, `scripts/readme_sync.py`, and every
  script called by `.github/workflows/*` — all untouched (035 adds no script and no
  workflow step). The tracker carries no `sources:` front-matter, so
  `check_doc_sources.py` is unaffected.

## 11. Compatibility Constraints

- The tracker is a **purely additive documentation artifact** under
  `docs/refactoring/reports/`. It introduces no import, no code path, no schema, and
  therefore needs **no compatibility adapter**.
- **No top-level `pyproject.toml` exists** — the core manifest is
  `ari-core/pyproject.toml` and is not touched; no `requirements*.txt`, workflow, or
  prompt file is modified.
- **Identity mirror must not fork the source of truth.** The tracker's identity
  columns duplicate `007_subtask_index.md` for readability only; the index remains
  authoritative (§7.4). Do not "correct" scope/dependencies in the tracker.
- **No VitePress `sources:` front-matter** (§4): `docs/refactoring/**` is an
  unpublished planning workspace; adding `sources:` would create a coverage
  obligation under the (off-by-default) `check_doc_sources.py --require-all`.
- **No `README.md` needed** for `reports/`: `scripts/readme_sync.py --check` only
  gates directories that already contain a `README.md` (`readme_sync.py:227`), and
  `reports/` has none — so the `readme-sync.yml` workflow stays green with no new file.
- **Determinism (P2):** statuses are evidence-derived and reproducible; no LLM/network
  calls in producing or maintaining the tracker.
- **"deprecated" stays reserved for external contracts** — internal subtask states use
  the §7.3 vocabulary and the code-classification vocabulary only.

## 12. Tests to Run

From repo root (`/home/t-kotama/workplace/ARI`):

- `python -m compileall .` — must remain clean; confirms 035 made no accidental `.py`
  edit (no runtime code is touched).
- `pytest -q` — full core suite (`ari-core/tests/`) must stay green; a green run
  confirms no accidental non-doc edit. (Optionally `scripts/run_all_tests.sh` for the
  per-skill suites.)
- `ruff check .` — lint stays at baseline; `ruff` **is** available, `radon` is **not**
  installed. No new `.py` should change the ruff count.
- **Gate-avoidance confirmations** (the ones that actually validate 035 stayed inert):
  - `python scripts/readme_sync.py --check` — must stay green; adding
    `reports/progress.md` must **not** introduce a readme-sync failure (no
    `README.md` in `reports/`).
  - `python scripts/docs/check_doc_sources.py` — unaffected (tracker has no `sources:`).
  - `python scripts/docs/check_doc_links.py` — if the optional cross-link is added,
    confirm the link to `reports/progress.md` resolves (advisory markdown-link mode).
  - Confirm `refactor-guards.yml`'s invariant still holds (no new `~/.ari` reference;
    no HOME write) — the tracker contains neither.
- **Internal consistency check** (manual or a throwaway one-liner, not a committed
  script): the tracker's 73 ids equal the id set in `007_subtask_index.md`, and
  `progress.md` statuses match `progress.json`.
- **No `npm test` / `npm run build`** is required — 035 touches no frontend code.

## 13. Acceptance Criteria

1. `docs/refactoring/reports/progress.md` exists, is committed, and contains **exactly
   73 subtask rows** whose id set equals that of `007_subtask_index.md` (no missing or
   extra ids) — including this subtask's own `035` row.
2. Each row carries a `Status` from the §7.3 closed vocabulary, an `Owner / PR` (SHA or
   `—`), and a `Last updated` date; identity columns (ID/Name/Phase/Depends/Runtime)
   match the 007 index verbatim.
3. The header contains: a status legend, a per-phase `done/total` rollup, the
   nine-inventory-gate status lines (`001, 002, 020, 036, 045, 053, 059, 060, 067`),
   and an Unblocked-next list; and the update protocol (§7.6) is embedded.
4. No status is fabricated: any `done` row is backed by a merged PR/commit and/or a
   deliverable on disk; a present `subtasks/NNN_*.md` plan is **not** treated as `done`.
5. If `progress.json` is produced, it mirrors the table exactly (same 73 ids, same
   statuses) and validates as JSON.
6. `python -m compileall .`, `pytest -q`, and `ruff check .` are green/at-baseline;
   `python scripts/readme_sync.py --check` passes; **`git status` shows only files
   under `docs/refactoring/reports/`** plus the optional one-line cross-link edits —
   zero runtime, prompt, config, workflow, or frontend files changed.
7. The tracker contains **no** `sources:` front-matter, **no** reference to a
   nonexistent `sonfigs/` directory, and **no** claim that any preserved contract
   (§10) changed.

## 14. Rollback Plan

Trivial and risk-free — the change set is confined to documentation artifacts:

1. `git rm docs/refactoring/reports/progress.md docs/refactoring/reports/progress.json`
   (whichever were added), or `git revert` the single commit.
2. Revert the optional one-line cross-link edits in
   `000_master_refactoring_plan.md` / `007_subtask_index.md`.

Because 035 touches no runtime code, no data/format migration is involved and rollback
cannot affect the running system. Re-running §12 after rollback returns the
pre-tracker state.

## 15. Dependencies

- **No explicit graph edge.** The provided DEPENDENCY GRAPH lists no `X -> 035` edge;
  035 is a **root** (`000_master_refactoring_plan.md:510`), matching its index row
  `Depends = —` and `Can-Run-Independently = Yes` (`007_subtask_index.md:82`). It is
  therefore **not hard-blocked** by any subtask and is scheduled in "Wave 2 … 004,
  032, 033, 034, 035 (independent)" (`000_master_refactoring_plan.md:528`).
- **Inventory-gate note.** The nine inventory subtasks that MUST precede any *runtime*
  code change — `001, 002, 020, 036, 045, 053, 059, 060, 067`
  (`000_master_refactoring_plan.md:512-513`) — do **not** gate 035, because 035 makes
  **no runtime code change** (index column = No). The tracker *reports on* those gates
  (§7.5) but does not depend on them to be created.
- **Soft/logical relationship (creatable early, maintained throughout).** The tracker
  is most *useful* once other subtasks are landing, but it can and should be created
  early (Wave 2) so it exists to record progress from the start. Its initial statuses
  are simply mostly `not-started`.
- **Downstream consumer (out-of-graph but real): subtask 019.** The Final Quality
  Report plans to read/update the 035 tracker to mark the program done
  (`019_final_quality_report.md:107-108,296-297,314-315`). So 035 should exist before
  019 runs; 019 is otherwise sequenced last. No other subtask depends on 035.

## 16. Risk Level

**Low** (matches `007_subtask_index.md:82`). **Runtime code change: No.** 035 writes a
status document (plus an optional JSON mirror and a one-line cross-link); it does not
alter dispatch, data, imports, or any contract. Residual risks are entirely about
*tracker correctness*, not system behavior: (a) fabricating a `done` status —
mitigated by §7.6/§13.4 ("evidence-derived, never inferred"; a present plan file is
not "done"); (b) forking the source of truth by editing scope in the tracker —
mitigated by §7.4 (identity is a read-only mirror; the 007 index wins); (c)
accidentally editing a runtime/config/prompt file while reading `git log` — mitigated
by §13.6 (`git status` must show only `docs/refactoring/reports/**`). All three are
caught by §12/§13.

## 17. Notes for Implementer

- **This subtask writes a document, not a tool.** If you find yourself writing a
  `scripts/*.py` generator/validator, you have crossed into quality-script territory
  (025–031/043/054–058) — stop. 035's only outputs are `reports/progress.md` (+ the
  optional `progress.json` and one-line cross-link).
- **The 007 index is the source of truth; the tracker is status-only.** Copy the
  73 ids and their identity columns from `007_subtask_index.md`, then add status.
  Never "fix" scope or dependencies in the tracker — if they look wrong, fix the index
  (a different concern) and re-mirror.
- **`subtasks/*.md` is being populated in parallel.** At planning snapshot the
  directory held a *growing subset* of the 73 plans (e.g. `001`–`027`, `029`–`031` in
  one observation). Presence of a plan file means the *plan* was written, **not** that
  the code landed — seed such rows from `git log` evidence, defaulting to
  `not-started`/`in-progress`, never `done` on plan-presence alone.
- **Seed from `git log`, not from optimism.** Use merged SHAs and deliverable-on-disk
  checks (e.g. `scripts/check_import_boundaries.py` for 026 and
  `scripts/generate_quality_report.py` for 031 are **absent** today —
  `019_final_quality_report.md:147-159` — so those subtasks are `not-started`).
- **The `sonfigs/` trap.** The upstream master prompt references a `sonfigs/`
  directory; it **does not exist** in this repo. The real, correctly-separated trio is
  `ari-core/ari/config/` (locator code), `ari-core/ari/configs/` (packaged defaults),
  and top-level `ari-core/config/` (rubric/profile data). Do not reference `sonfigs/`
  in the tracker.
- **No gate obligation is created** as long as you (a) put the file in
  `docs/refactoring/reports/`, (b) add no `sources:` front-matter, and (c) add no
  `README.md` there. Confirm `scripts/readme_sync.py --check` and the docs gates stay
  green after writing.
- **Keep the JSON and Markdown in lock-step** if you produce both — same 73 ids, same
  statuses — so subtask 019 can consume either without surprise.
- **Watch the footprint.** Before committing, run `git status` and confirm the diff is
  confined to `docs/refactoring/reports/**` (and the optional one-line cross-link).
  Any `ari-core/`, `ari-skill-*/`, `scripts/`, or `frontend/` change means you
  overstepped — revert it.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **035** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
