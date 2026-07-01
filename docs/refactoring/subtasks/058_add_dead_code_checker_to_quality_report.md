# Subtask 058: Add Dead Code Checker To Quality Report

- **Phase:** Phase 8 — Quality Scripts
- **Subtask ID:** 058
- **Title (index):** `add_dead_code_checker_to_quality_report`
- **Primary deliverable:** extend the aggregator `scripts/generate_quality_report.py`
  (created by Subtask 031) with a dedicated **dead-code section** that ingests the
  JSON emitted by `scripts/check_dead_code.py` (created by Subtask 055), renders
  per-classification counts, and records the **before/after reduction** around the
  Subtask 057 deletion so the retirement is auditable (`docs/refactoring/013_reference_graph_and_dead_code_plan.md`
  §9 step 5, §6.3).
- **Runtime code change:** **No** (dev/CI tooling only — see Section 16).
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core`
  version `0.9.0`, from `ari-core/pyproject.toml`).
- **Canonical language:** English.
- **Classification vocabulary:** module/file decisions use the master set
  `KEEP` / `ADAPT` / `MERGE` / `MOVE_TO_LEGACY` / `DELETE_CANDIDATE` /
  `REVIEW_REQUIRED`. Symbol-level dead-code decisions use the finer set defined
  in `013_reference_graph_and_dead_code_plan.md` §7: `SAFE_DELETE_CANDIDATE` /
  `QUARANTINE_CANDIDATE` / `TEST_ONLY` / `DOCS_ONLY` / `DYNAMIC_REFERENCE_RISK` /
  `PUBLIC_CONTRACT` / `REVIEW_REQUIRED`. The word "deprecated" is reserved for
  external contracts only (public API, CLI, MCP, dashboard API, documented import
  paths, `ari-skill-*` stable interfaces).

---

## 1. Goal

Make the repository's single consolidated quality report **dead-code aware**. This
subtask does **not** build a new checker and does **not** delete any code; it wires
the output of the already-built dead-code detector (`scripts/check_dead_code.py`,
Subtask 055) into the already-built aggregator (`scripts/generate_quality_report.py`,
Subtask 031) and adds the reporting logic that turns raw candidate counts into an
auditable, before/after "dead-code reduction" view for the Subtask 057 deletion.

Concretely, after this subtask a maintainer running the aggregator sees a
**dead-code section** containing:

1. Per-classification candidate counts using the `013` §7 vocabulary
   (`SAFE_DELETE_CANDIDATE`, `QUARANTINE_CANDIDATE`, `TEST_ONLY`, `DOCS_ONLY`,
   `DYNAMIC_REFERENCE_RISK`, `PUBLIC_CONTRACT`, `REVIEW_REQUIRED`).
2. A **before/after delta** against a frozen pre-deletion snapshot, so the effect
   of Subtask 057's `SAFE_DELETE_CANDIDATE` removals is visible as a number
   (e.g. `SAFE_DELETE_CANDIDATE: 14 → 0`).
3. A stable JSON roll-up of the above (so the report itself can be diffed/ratcheted
   over time, exactly like every other checker's contribution).

Classification of this deliverable: **KEEP (net-new reporting glue)**. It creates no
runtime surface, installs no dependency, and per `007_subtask_index.md:105` is
Risk **Low**, runtime-change **No**.

Success = a fresh coding session, with 031 and 055 already merged, can run
`python scripts/generate_quality_report.py --format markdown` and see a dead-code
section whose per-classification counts match `scripts/check_dead_code.py --format json`,
and whose "before/after" delta correctly reflects the frozen snapshot, with the
aggregator still degrading gracefully when the dead-code checker is absent.

## 2. Background

ARI has two mature, deterministic gate families but historically **no source-code
quality suite and no aggregated report**:

- **`scripts/docs/`** (10 files) — documentation/i18n gates. House convention
  (verified in `scripts/docs/check_doc_sources.py`): `#!/usr/bin/env python3`, a
  module docstring citing a design doc, `argparse`, `REPO_ROOT =
  Path(__file__).resolve().parents[N]`, PyYAML as the only non-stdlib dependency,
  a `--json` flag, `SystemExit(2)` on usage/environment error, staged
  warning→error rollout, no LLM/network (design principle P2, determinism).
- **`report/scripts/`** — LaTeX/HTML report-build gates (`Gate N` convention).
- **`scripts/` top level** — `scripts/readme_sync.py` (14,330 B; `REPO_ROOT =
  Path(__file__).resolve().parents[1]` at line 31), `scripts/run_all_tests.sh`,
  `scripts/git-hooks/pre-commit`.

`docs/refactoring/009_quality_scripts_plan.md` designs an 11-checker source-quality
suite plus one aggregator. The **dead-code chain** is specified separately in
`docs/refactoring/013_reference_graph_and_dead_code_plan.md`, realized by this
sequence of subtasks (authoritative titles from `007_subtask_index.md:100-105`):

| Subtask | Title | Deliverable | Deletes code? |
|---|---|---|---|
| 053 | `inventory_reference_roots` | reference-roots inventory (root entrypoints, §3) | No |
| 054 | `add_reference_graph_analyzer` | `scripts/analyze_references.py` → `reference_graph.json` (§6.1) | No |
| 055 | `add_dead_code_candidate_checker` | `scripts/check_dead_code.py` → `dead_code_candidates.md` + JSON (§6.2, §8.3) | No |
| 056 | `classify_unused_functions_and_files` | human dead-code classification report (§9 step 2) | No |
| 057 | `delete_safe_dead_code_candidates` | removal of reviewed `SAFE_DELETE_CANDIDATE` nodes (§9 step 4) | **Yes (only here)** |
| **058** | **`add_dead_code_checker_to_quality_report`** | **dead-code section in `generate_quality_report.py` (§6.3, §9 step 5)** | **No** |

`013` §9 step 5 states the intent verbatim: *"Report (058). `generate_quality_report.py`
records before/after counts per classification so the reduction is auditable."*
`007_subtask_index.md:337` restates it: *"058 add_dead_code_checker_to_quality_report
— folds [the dead-code] checker into 031's report."*

**Numbering trap (must read).** Three planning docs use *different provisional
numberings* for these scripts; only `007_subtask_index.md` and this subtask's master
dependency graph are authoritative:

- `009_quality_scripts_plan.md` §7 (`:247-249`) says `043 = analyze_references.py`,
  `055 = check_dead_code.py`, **`058 = generate_quality_report.py`**.
- `013_reference_graph_and_dead_code_plan.md` §10 says `053 = analyze_references`,
  `055 = check_dead_code`, **`058 = generate_quality_report`**.
- **Authoritative** (`007_subtask_index.md`): `054 = analyze_references.py`,
  `055 = check_dead_code.py`, **`031 = generate_quality_report.py`**, and
  **`058 = add_dead_code_checker_to_quality_report` (this subtask) = the dead-code
  section added to 031's report.**

So where `009`/`013` say "058 = generate_quality_report", read it as "031 builds the
aggregator; 058 adds the dead-code section to it." **Do not edit `009` or `013`** in
this subtask (planning docs are out of scope for edits here); Subtask 031 already
recorded the same reconciliation (`docs/refactoring/subtasks/031_add_quality_report_generator.md`
§2 "ID / naming note").

**Tooling baseline (verified live 2026-07-01):** Python **3.13.2**; **ruff 0.15.2
installed**; **radon NOT installed** (`import radon` → `ModuleNotFoundError`);
**vulture NOT installed** (`import vulture` → `ModuleNotFoundError`);
`compileall`/`pytest` available; `node`+`npm` available (**no pnpm**). ARI ruff
baseline (in `ari-core`): **661 findings**, of which `F401` unused-import **341**,
`F841` unused-variable **39**, `F811` redefined-while-unused **8** — the signal
`check_dead_code.py` (055) already leans on. No `radon`/`vulture` is added by this
subtask.

## 3. Scope

In scope (dev/CI tooling only):

1. **Extend `scripts/generate_quality_report.py`** (created by 031) with a
   dead-code section:
   - Ingest the `scripts/check_dead_code.py` JSON payload through the aggregator's
     existing checker-collection mechanism (`--target` dir of JSON, or
     `--run-checkers` subprocess mode — both already implemented by 031).
   - Add a renderer that groups the checker's `findings[]` by the `013` §7
     classification (carried on each finding's `kind`/`severity` field per the
     §3 common JSON schema) and emits per-classification counts.
   - Add a **before/after delta** for the dead-code section using 031's existing
     `--baseline` mechanism plus a frozen pre-deletion snapshot (Section 7.3),
     so the report shows `SAFE_DELETE_CANDIDATE: <before> → <after>` etc.
2. **Register `check_dead_code` in the aggregator config**
   `scripts/quality/generate_quality_report.yaml` (created by 031) as a
   `required: false` entry, so its absence remains non-fatal (graceful
   degradation) but its presence is picked up automatically.
3. **Freeze the pre-deletion snapshot.** Store the dead-code counts *before*
   Subtask 057's deletion as a committed baseline
   (`docs/refactoring/reports/dead_code_baseline.json`) so the "before" side of the
   delta is reproducible. This is a data artifact, not runtime code.
4. **Extend the aggregator's test** (`ari-core/tests/test_quality_report_generator.py`,
   created by 031) with synthetic `check_dead_code` JSON fixtures covering: valid
   per-classification counts, absent checker (`status: unavailable`), malformed
   JSON (`status: error`), and a before/after delta against a fixture snapshot.
5. **Keep README-sync green.** If any new file is added under `scripts/` or
   `docs/refactoring/reports/` that a directory README must list, update the
   relevant `## Contents` block (Section 11).

Out of scope (owned by sibling subtasks; do **not** implement here):

- **Building `scripts/check_dead_code.py`** — Subtask 055 (`013` §8.3). 058 only
  *consumes* its JSON.
- **Building `scripts/analyze_references.py`** and the dynamic-edge overlay —
  Subtasks 054 (`013` §8.1/§8.2).
- **Building `scripts/generate_quality_report.py`** itself — Subtask 031. 058
  *extends* it.
- **Deleting any code** — Subtask 057 is the only deletion step (`013` §9 step 4).
  058 measures the outcome; it removes nothing.
- **Quarantine / `MOVE_TO_LEGACY` mechanics** — Subtask 056 (`013` §9 step 3).
- **Wiring the report into CI as a hard gate** — a separate, later decision
  (`009_quality_scripts_plan.md` §6; `013` §8.3 keeps dead-code advisory).

## 4. Non-Goals

- **No runtime code changes.** No edits to anything under `ari-core/ari/`,
  `ari-skill-*/`, the React frontend (`ari-core/ari/viz/frontend/`), prompts,
  `ari-core/config/`, `ari-core/ari/configs/`, `ari-core/ari/config/`, checkpoint
  formats, or `.github/workflows/`.
- **No deletion, no quarantine, no file moves.** 058 never removes or relocates a
  symbol; that is 057/056.
- **No new checker.** 058 adds *reporting glue*, not a new detector. It must not
  re-derive reachability or re-run ruff — it reads `check_dead_code.py`'s JSON.
- **No new runtime dependency.** `radon`/`vulture` remain uninstalled and unadded;
  the aggregator stays stdlib + PyYAML only (PyYAML `pyyaml>=6.0`, already a core
  dep in `ari-core/pyproject.toml`).
- **No LLM calls, no network** (preserves the `scripts/docs/` determinism
  convention and design principle P2 — same inputs ⇒ same report).
- **No hard CI gate** and **no workflow edits** in this subtask. Any promotion to
  a ratchet/gate is a separate, explicitly-scoped subtask.
- **No `pnpm`** and **no frontend build**. 058 touches no TS/TSX; `npm test` /
  `npm run build` are not applicable.
- **No edits to the planning docs** `009_quality_scripts_plan.md` /
  `013_reference_graph_and_dead_code_plan.md` (the numbering trap in Section 2 is
  reconciled in-place here, not fixed upstream).

## 5. Current Files / Directories to Inspect

All paths are repository-relative to `/home/t-kotama/workplace/ARI`. State marked
where relevant.

**The two scripts 058 glues together (both created by *earlier* subtasks — read
their delivered form, do not re-create):**
- `scripts/generate_quality_report.py` — **does not exist yet** (created by Subtask
  031). Its spec: `docs/refactoring/subtasks/031_add_quality_report_generator.md`
  §7 (CLI flags `--target`/`--config`/`--output`/`--format markdown|json`/
  `--run-checkers`/`--baseline`/`--warning-only`/`--fail-on-regression`; aggregated
  JSON roll-up schema with `report`, `version`, `checkers[]`, `areas[]`, `totals`,
  `regression`). 058 extends this file.
- `scripts/check_dead_code.py` — **does not exist yet** (created by Subtask 055).
  Its spec: `013_reference_graph_and_dead_code_plan.md` §8.3 (consumes
  `reference_graph.json`, applies §7 precedence, emits `dead_code_candidates.md` +
  a `--format json` payload matching the `009` §3 common schema; `--report` default,
  `--check` ratchet mode). 058 consumes its JSON.
- `scripts/quality/generate_quality_report.yaml` — **does not exist yet** (created
  by 031). 058 registers a `check_dead_code` entry (`required: false`).
- `scripts/quality/` — **does not exist yet** (bootstrapped by the first-landing
  Phase 8 checker, e.g. Subtask 025 or 031). 058 does not create it; it edits the
  config already inside it.

**House-style references (the convention the 031/055 authors copied; read to keep
058's additions consistent):**
- `scripts/docs/check_doc_sources.py` (7,665 B) — canonical checker shape:
  shebang, docstring citing a design doc, `argparse`, `--json`,
  `REPO_ROOT = Path(__file__).resolve().parents[2]`, `SystemExit(2)` on missing
  PyYAML, staged rollout.
- `scripts/docs/check_ref_coupling.py` (6,488 B) — `--base-ref origin/main`
  diff-gate pattern (reference for any delta framing).
- `scripts/readme_sync.py` (14,330 B) — top-level `REPO_ROOT =
  Path(__file__).resolve().parents[1]` (line 31); the aggregator uses the same
  `parents[1]`.
- `scripts/README.md` (4,913 B) — the `## Contents` block enforced by
  `readme-sync.yml`.

**Design inputs (read before implementing):**
- `docs/refactoring/013_reference_graph_and_dead_code_plan.md` — §6.3 (report
  output), §7 (classification vocabulary), §8.3 (`check_dead_code.py` JSON), §9
  (deletion/quarantine workflow; step 5 = 058), §10 (subtask table).
- `docs/refactoring/subtasks/031_add_quality_report_generator.md` — §7 (aggregator
  CLI + JSON schema + graceful-degradation policy), §2 (numbering note), §9 (files),
  §11 (compatibility).
- `docs/refactoring/009_quality_scripts_plan.md` — §3 (common per-checker JSON
  schema `{checker, version, target, summary, findings[]}`), §5.10
  (`check_dead_code.py`), §5.11 (aggregator), §6 (warning-mode-first rollout).
- `docs/refactoring/007_subtask_index.md` — rows `053`–`058` (`:100-105`), Phase 8
  notes (`:318-337`), dependency edge `053 -> 054 -> 055 -> 056 -> 057 -> 058`
  (`:437`, `:492`).

**Output / snapshot destination:**
- `docs/refactoring/reports/` — **exists, currently empty** (`ls` → only `.`/`..`).
  This is where 031 writes the Markdown roll-up and where 058 stores the frozen
  `dead_code_baseline.json` "before" snapshot.

**Confirmed absent (state explicitly, do not chase or fabricate):**
- `scripts/generate_quality_report.py`, `scripts/check_dead_code.py`,
  `scripts/analyze_references.py`, `scripts/quality/` — all absent today (verified
  by `ls`). They are delivered by predecessor subtasks; 058 assumes 031 + 055 have
  landed (Section 15).
- No `radon`, no `vulture`. No `sonfigs/` directory anywhere (the confusable trio
  is `ari-core/ari/config/` code vs `ari-core/ari/configs/` packaged defaults vs
  top-level `ari-core/config/` rubric data — none touched here). No top-level
  `pyproject.toml`.

## 6. Current Problems

1. **The aggregator has no dead-code awareness.** Subtask 031 ships
   `generate_quality_report.py` with a generic per-checker table but no
   classification-aware rendering: dead-code candidates would appear only as an
   opaque `finding_count`, losing the `013` §7 distinction between a
   `SAFE_DELETE_CANDIDATE` and a `DYNAMIC_REFERENCE_RISK` — the single most
   decision-relevant axis for the retirement work.
2. **The 057 deletion is unauditable without a before/after.** `013` §9 step 5
   requires the report to show *"before/after counts per classification so the
   reduction is auditable."* Nothing today freezes the pre-deletion counts, so
   after 057 removes the `SAFE_DELETE_CANDIDATE` nodes there is no artifact proving
   how many were removed or that no new orphan was introduced.
3. **False-positive risk is invisible in a flat count.** ARI is import-driven at
   its extensibility seams (registry/factory string keys, config/rubric paths,
   prompt keys, MCP tool dispatch, cross-language HTTP to `viz` — `013` §5). A flat
   "N dead symbols" number hides which are `DYNAMIC_REFERENCE_RISK`/`PUBLIC_CONTRACT`
   (must never be deleted) versus genuinely `SAFE_DELETE_CANDIDATE`. The report must
   surface the classification split, not a total.
4. **Config drift if the checker is not registered.** Unless
   `check_dead_code` is added to `generate_quality_report.yaml`, the aggregator
   will silently report it as `unavailable` forever (031's graceful-degradation
   default), so the dead-code section would never populate even after 055 lands.
5. **README-sync coupling.** Adding a new file (the frozen snapshot, or any
   `scripts/` artifact) can trip `readme-sync.yml` (`python scripts/readme_sync.py
   --check`, exit 1 on missing/extra listed paths) unless the owning directory
   README's `## Contents` is updated in the same change.

## 7. Proposed Design / Policy

Extend 031's aggregator; add no new script. Follow the `013` §6.3/§9 report spec
and 031's §7 CLI/JSON contract.

**7.1 Ingestion (reuse, do not re-derive).** The dead-code data enters through
031's *existing* checker-collection path: either a pre-generated
`scripts/check_dead_code.py --format json` file in the `--target` directory, or a
`--run-checkers` subprocess invocation. 058 adds a `check_dead_code` entry to
`scripts/quality/generate_quality_report.yaml`:

```yaml
# appended to the checkers: list created by Subtask 031
- name: check_dead_code
  path: scripts/check_dead_code.py
  argv: ["--format", "json"]
  weight: 1
  required: false          # absence ⇒ status: unavailable, never fatal
```

058 must **not** run `analyze_references.py` or ruff itself; the aggregator
"detects nothing itself" (`009` §5.11) — it reads the checker's JSON only.

**7.2 Classification-aware rendering.** Add a dead-code renderer that groups the
incoming `findings[]` by the `013` §7 vocabulary. The common `009` §3 schema
carries the classification on a per-finding field (`kind` and/or `severity` — the
exact field is defined by 055's `check_dead_code.py`; 058 reads whichever 055
emits and must not require a schema change). Output, in both formats:

- **Markdown** — a dead-code subsection with a per-classification table
  (`classification · count · Δ vs baseline`) covering all seven buckets, plus a
  one-line "safe-to-delete surviving human review: N" headline. Kept PR-comment-sized.
- **JSON** — folded into 031's roll-up under the existing `checkers[]` entry for
  `check_dead_code`, plus a dedicated `dead_code` object:

  ```json
  "dead_code": {
    "by_classification": {
      "SAFE_DELETE_CANDIDATE": 0, "QUARANTINE_CANDIDATE": 0,
      "TEST_ONLY": 0, "DOCS_ONLY": 0, "DYNAMIC_REFERENCE_RISK": 0,
      "PUBLIC_CONTRACT": 0, "REVIEW_REQUIRED": 0
    },
    "baseline": "docs/refactoring/reports/dead_code_baseline.json",
    "delta": { "SAFE_DELETE_CANDIDATE": 0 }
  }
  ```

  The roll-up keeps its own top-level `"version"` (031 §7); if this added `dead_code`
  object ever changes shape incompatibly, bump that integer.

**7.3 Before/after delta (the 058 core).** Freeze the pre-057 counts once, into
`docs/refactoring/reports/dead_code_baseline.json`, produced by running
`scripts/check_dead_code.py --format json` on the tree *before* Subtask 057's
deletion PR. The aggregator computes `delta = current − baseline` per classification
and renders it in the dead-code table. Reuse 031's existing `--baseline` flag/plumbing
where possible; if the whole-report baseline and the dead-code snapshot must differ,
add a narrowly-scoped `--dead-code-baseline <file>` that defaults to the frozen path.
The expected end-state after 057 lands: `SAFE_DELETE_CANDIDATE` drops to `0` (or to
the residual reviewed-but-kept set), and every other bucket is unchanged — the
report makes that drop explicit.

**7.4 Graceful degradation (inherited, must be preserved).** When
`check_dead_code.py` is absent, unparseable, or exits outside `{0,1}`, the section
renders `status: unavailable`/`error` with a reason and the aggregator still emits a
valid report (031 §7 "graceful degradation policy"). The dead-code section must
never be the thing that crashes the aggregator.

**7.5 Exit convention (unchanged from 031 §7).** `0` = clean or `--warning-only`
(the default posture while new); `1` = regression under `--fail-on-regression`
(here: a net-new `SAFE_DELETE_CANDIDATE` above baseline, if a maintainer opts into
the ratchet); `2` = usage/environment error. 058 does not introduce a hard gate;
the dead-code section is advisory (`013` §8.3, `009` §5.10 — internal-quality
checkers "may stay advisory indefinitely").

**7.6 Rollout.** Advisory only. No workflow is edited. The dead-code section is
informational; promotion of `--fail-on-regression` for dead code to a hard CI gate
is a separate, later subtask.

## 8. Concrete Work Items

Assumes Subtasks 031 (aggregator) and 055 (`check_dead_code.py`) are merged
(Section 15). If either is missing, 058 cannot be completed — stop and flag.

1. Read `013` §6.3/§7/§8.3/§9, `031` §7/§9, and the delivered
   `scripts/generate_quality_report.py` + `scripts/check_dead_code.py` to learn
   the exact JSON field carrying the `013` §7 classification.
2. **Extend `scripts/generate_quality_report.py`:**
   - Add a `render_dead_code(result, baseline)` helper that groups
     `check_dead_code`'s `findings[]` by classification into the seven `013` §7
     buckets and computes the per-bucket delta vs the frozen snapshot.
   - Emit the `dead_code` object in `render_json(...)` and the dead-code subsection
     in `render_markdown(...)`. Both must appear even when all counts are zero.
   - Load the frozen snapshot from
     `docs/refactoring/reports/dead_code_baseline.json` (default), overridable via
     `--dead-code-baseline` if the whole-report `--baseline` is inadequate.
   - Preserve the graceful-degradation path: no `check_dead_code` JSON ⇒
     `status: unavailable`, section still renders.
3. **Register the checker** in `scripts/quality/generate_quality_report.yaml`
   (append the `check_dead_code` entry from 7.1, `required: false`).
4. **Freeze the baseline:** run `python scripts/check_dead_code.py --format json`
   on the pre-057 tree and commit the result to
   `docs/refactoring/reports/dead_code_baseline.json`. (If 058 runs after 057 has
   already deleted, reconstruct the "before" snapshot from 057's PR artifact / the
   pre-deletion commit; note the source commit in the JSON.)
5. **Extend the aggregator test**
   (`ari-core/tests/test_quality_report_generator.py`) with `check_dead_code`
   fixtures: (a) valid per-classification counts render the seven buckets;
   (b) absent checker ⇒ `unavailable`, report still valid; (c) malformed JSON ⇒
   `error`, no raise; (d) delta vs a fixture baseline is computed correctly;
   (e) `--format json` round-trips the `dead_code` object; (f) `--warning-only`
   forces exit 0.
6. **Keep gates green:** if any file was added under a README-governed directory
   (e.g. `docs/refactoring/reports/dead_code_baseline.json`, or a new `scripts/`
   file), update the owning `## Contents` (or run `python scripts/readme_sync.py
   --write` and stage the result). Ensure edited `.py` files are ruff-clean so
   `ruff check .` does not rise above the 661 baseline.
7. **Self-run (smoke):**
   - `python scripts/generate_quality_report.py --format markdown` with a fixture
     `check_dead_code` JSON present → dead-code section shows the seven buckets and
     the delta.
   - `python scripts/generate_quality_report.py --format json` → valid JSON with the
     `dead_code` object.
   - Same commands with **no** `check_dead_code` JSON → section renders
     `unavailable`, exit 0.
8. Run the Section-12 gates; confirm nothing outside the intended file set changed.

## 9. Files Expected to Change

Runtime code: **none**.

Modified (dev/CI tooling + data, all created by predecessor subtasks):
- `scripts/generate_quality_report.py` — add the dead-code renderer, the
  `dead_code` JSON object, and the before/after delta (created by Subtask 031).
- `scripts/quality/generate_quality_report.yaml` — register the `check_dead_code`
  entry (`required: false`) (created by Subtask 031).
- `ari-core/tests/test_quality_report_generator.py` — add `check_dead_code`
  fixtures/assertions (created by Subtask 031).

Created (data / non-runtime):
- `docs/refactoring/reports/dead_code_baseline.json` — frozen pre-057
  per-classification snapshot (the "before" side of the delta).

Updated only if README-sync requires it (non-runtime):
- The `## Contents` of whichever directory README governs any newly added file
  (e.g. a `docs/refactoring/reports/README.md` if the reports dir is README-governed,
  or `scripts/README.md` if a new `scripts/` file is added). Confirm with
  `python scripts/readme_sync.py --check`.

Explicitly **not** changed:
- `ari-core/pyproject.toml` (no `[tool.ruff]`, no new dep).
- Any of `.github/workflows/{docs-change-coupling,docs-sync,pages,readme-sync,refactor-guards}.yml`.
- `scripts/check_dead_code.py`, `scripts/analyze_references.py` (owned by 055/054).
- The planning docs `009_quality_scripts_plan.md`, `013_reference_graph_and_dead_code_plan.md`.
- Anything under `ari-core/ari/`, `ari-skill-*/`, the frontend, `ari-core/config/`,
  `ari-core/ari/configs/`, `ari-core/ari/config/`, prompts.

## 10. Files / APIs That Must Not Be Broken

This subtask edits a read-only reporting script plus a data snapshot and touches no
runtime surface, so it breaks nothing directly. It must nonetheless preserve the
full contract firewall (`013` §9 "Contract firewall"):

- **CLI** `ari = ari.cli:app` — untouched; the aggregator adds no `ari` subcommand
  and imports nothing from the `ari` package. Invoked only as
  `python scripts/generate_quality_report.py`.
- **`ari.public.*`** (frozen 148-LOC surface: `claim_gate`, `config_schema`,
  `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`) — not
  imported, not modified.
- **MCP tool contracts** (14 `ari-skill-*/src/server.py`) — the dead-code checker
  *reads* these; 058 only reads the checker's JSON. No tool name/`inputSchema`/
  envelope changes.
- **Dashboard API** (`ari/viz/routes.py` + `api_*.py` + `websocket.py`, consumed by
  `frontend/src/services/api.ts`) — untouched.
- **Checkpoint / output / config file formats** — untouched; the aggregator writes
  only its own report (stdout or `--output`) plus the frozen snapshot under
  `docs/refactoring/reports/`.
- **`009` §3 per-checker JSON schema** (`checker/version/target/summary/findings[]`)
  — 058 is a *consumer*; it must read the schema as-is and must not require
  `check_dead_code.py` (055) to deviate from it.
- **031's aggregated roll-up schema** — 058 *adds* a `dead_code` object; it must not
  rename/remove existing keys (`report`, `version`, `checkers[]`, `areas[]`,
  `totals`, `regression`). Bump the roll-up `"version"` only if the addition is
  breaking (it should be additive).
- **Scripts invoked by `.github/workflows/`** — the `readme_sync.py --check` gate
  (`readme-sync.yml`) must stay green; the `refactor-guards.yml` `~/.ari` diff-grep
  and HOME-write pytest guard must stay green (write nothing to `$HOME`, reference
  no `~/.ari`). The other three workflows are not touched.

No external contract is deprecated or changed by this subtask.

## 11. Compatibility Constraints

- **Additive-only aggregator change.** The `dead_code` object and the dead-code
  Markdown subsection are *added*; no existing 031 field is renamed/removed, so any
  consumer of 031's roll-up keeps working. Keep the roll-up `"version": 1` unless
  the change is breaking.
- **Graceful degradation preserved.** With 055 not yet merged, the aggregator must
  still run and report `check_dead_code` as `unavailable` (031 §7). 058 must not make
  the dead-code section a hard prerequisite for producing a report.
- **`readme-sync.yml` gate.** `python scripts/readme_sync.py --check` fails (exit 1)
  on any directory README `## Contents` omission. If
  `docs/refactoring/reports/dead_code_baseline.json` (or any new file) lands in a
  README-governed directory, update that README in the same change.
- **`refactor-guards.yml` gate.** No `~/.ari` reference; no `$HOME` writes. All
  output stays inside the repo (`docs/refactoring/reports/` or `--output`).
  Determinism (P2): no network, no LLM — same tree ⇒ same report.
- **No new dependency.** stdlib + PyYAML only; `radon`/`vulture` remain uninstalled.
  ruff (0.15.2) is invoked by 055, not by 058.
- **House style.** Match `scripts/docs/` and 031: `argparse`, `--format json`,
  `REPO_ROOT = Path(__file__).resolve().parents[1]`, `SystemExit(2)` on env error,
  warning-first posture. Consistency is a review criterion.
- **Ratchet, if opted into, is advisory.** `--fail-on-regression` for a net-new
  `SAFE_DELETE_CANDIDATE` is available but not wired to CI here (`013` §8.3, `009`
  §5.10).

## 12. Tests to Run

From repo root `/home/t-kotama/workplace/ARI`:

```bash
# 1. Everything still byte-compiles (edited aggregator + test included)
python -m compileall .

# 2. Lint — the edited script must stay ruff-clean; repo baseline is 661 findings
#    in ari-core and must not rise
ruff check .
ruff check scripts/generate_quality_report.py

# 3. Aggregator unit test (dead-code fixtures added by this subtask)
pytest -q ari-core/tests/test_quality_report_generator.py

# 4. Full suite regression sanity
pytest -q

# 5. README-sync gate (the gate readme-sync.yml runs)
python scripts/readme_sync.py --check

# 6. Aggregator self-run — dead-code section present, then graceful-absent path
python scripts/generate_quality_report.py --format markdown
python scripts/generate_quality_report.py --format json
```

No frontend build is involved (058 touches no TS/TSX), so `npm test` /
`npm run build` under `ari-core/ari/viz/frontend/` are **not** applicable (and this
environment has `npm`, not `pnpm`).

If `compileall` / `pytest` / `ruff check .` regress beyond the 661 baseline, the
session touched something outside the intended file set and must revert.

## 13. Acceptance Criteria

1. `scripts/generate_quality_report.py` renders a **dead-code section** in both
   `--format markdown` and `--format json`, grouping candidates into the seven
   `013` §7 classifications (`SAFE_DELETE_CANDIDATE`, `QUARANTINE_CANDIDATE`,
   `TEST_ONLY`, `DOCS_ONLY`, `DYNAMIC_REFERENCE_RISK`, `PUBLIC_CONTRACT`,
   `REVIEW_REQUIRED`).
2. The section shows a **before/after delta** per classification against
   `docs/refactoring/reports/dead_code_baseline.json`; with the post-057 tree,
   `SAFE_DELETE_CANDIDATE` shows its reduction (e.g. `→ 0`) and other buckets are
   unchanged.
3. `scripts/quality/generate_quality_report.yaml` registers `check_dead_code`
   (`required: false`); the aggregator picks it up automatically when present and
   reports it `unavailable` (report still valid) when absent.
4. The `dead_code` object is additive: 031's roll-up keys (`report`, `version`,
   `checkers[]`, `areas[]`, `totals`, `regression`) are unchanged; the roll-up
   `"version"` is unchanged (additive) or deliberately bumped if breaking.
5. `ari-core/tests/test_quality_report_generator.py` covers valid / absent /
   malformed `check_dead_code` inputs and the delta computation, and passes.
6. `python -m compileall .`, `pytest -q`, and `ruff check .` pass with the ruff
   count **≤ 661** (no new lint debt); `python scripts/readme_sync.py --check`
   passes.
7. `git diff --name-only` shows only the files in Section 9. No runtime code,
   config, prompt, workflow, frontend, or directory under `ari-core/ari/` /
   `ari-skill-*/` / the frontend was created, edited, moved, renamed, or deleted.
   The word "deprecated" is not applied to any internal code.

## 14. Rollback Plan

Trivial and complete — the subtask's footprint is an additive edit to one script,
one config entry, one test, and one committed data file, none imported by runtime
code:

- `git checkout -- scripts/generate_quality_report.py
  scripts/quality/generate_quality_report.yaml
  ari-core/tests/test_quality_report_generator.py` to drop the dead-code additions.
- `git rm docs/refactoring/reports/dead_code_baseline.json` to remove the snapshot.
- `git checkout -- <README>` (or re-run `python scripts/readme_sync.py --write`) to
  restore any `## Contents` block.

No runtime state, no migrations, no config-format change, no schema break, no
workflow change → nothing else to undo. Rollback cannot affect the running system,
checkpoints, MCP tools, the dashboard, or any preserved contract. (Rolling back 058
does **not** un-delete anything — Subtask 057 owns the deletion and is reverted
independently.)

## 15. Dependencies

Per the program dependency graph (`053 -> 054 -> 055 -> 056 -> 057 -> 058`;
`007_subtask_index.md:437`, `:492`):

- **Direct predecessor (hard, incoming graph edge): `057 -> 058`.** Subtask 057
  (`delete_safe_dead_code_candidates`) performs the only deletion; 058 records the
  before/after reduction it produces. 058 must not finish before 057 is complete
  (though the "before" snapshot in Section 7.3/8.4 is frozen from the *pre-057*
  tree).
- **Transitive predecessors (the full linear chain):**
  `053 (inventory_reference_roots) -> 054 (analyze_references.py) -> 055
  (check_dead_code.py) -> 056 (classify) -> 057 (delete) -> 058`. Of these, **055
  is also a direct data producer** for 058: 058 ingests `scripts/check_dead_code.py`'s
  JSON. Because 055 is a graph ancestor of 058, this is consistent with the provided
  edges — no extra edge is needed.
- **Un-encoded but real co-requisite: Subtask 031.** 058 *extends*
  `scripts/generate_quality_report.py`, which is **created by Subtask 031**
  (`add_quality_report_generator`), and edits `scripts/quality/generate_quality_report.yaml`
  and `ari-core/tests/test_quality_report_generator.py`, also created by 031.
  The provided dependency graph does **not** list a `031 -> 058` edge, but the
  authoritative index does (`007_subtask_index.md:337` "folds ... into 031's report";
  `docs/refactoring/subtasks/031_add_quality_report_generator.md:464-465` "Downstream
  extender: 058 ... so 031 precedes 058"). **Treat 031 as a hard prerequisite in
  practice**: if `scripts/generate_quality_report.py` does not exist, 058 has nothing
  to extend. 031 in turn depends on `001` (`001 -> 031`), the complexity/dependency
  measurement.
- **Gate context.** `053` is one of the nine inventory subtasks that must precede
  any runtime code change (`001, 002, 020, 036, 045, 053, 059, 060, 067`;
  `007_subtask_index.md:513`). `057` (deletion) *is* a runtime code change (High
  risk). **058 itself is not a runtime code change** — it adds reporting glue — so
  it neither blocks nor is blocked by the runtime-editing cohort beyond its 057/031
  prerequisites.
- **No outgoing edge from 058** in the provided graph — it is a terminal node of the
  dead-code chain (a soft input to the program-wide `019 final_quality_report`, which
  aggregates all prior outputs, but that is not a build-order edge on 058).

This is consistent with the provided graph edge `057 -> 058` and the inventory gate
list; the only relationship *not* captured by the provided edge list is the
practical `031 -> 058` prerequisite, flagged explicitly above.

## 16. Risk Level

- **Risk: Low.** (Consistent with `007_subtask_index.md:105`: Risk Low.)
- **Changes runtime code? No.** The deliverables are an additive edit to the dev
  aggregator (`scripts/generate_quality_report.py`), one config entry
  (`scripts/quality/generate_quality_report.yaml`), a test
  (`ari-core/tests/test_quality_report_generator.py`), and a committed data snapshot
  (`docs/refactoring/reports/dead_code_baseline.json`). None is imported by the
  `ari` package, any `ari-skill-*` server, the CLI, the dashboard, or any of the 5
  workflows. The aggregator is read-only reporting and modifies no runtime code,
  imports, prompts, configs, workflows, frontend, or directory names.
- Residual risks, all contained: (a) the classification field 055 emits differing
  from what 058 expects — mitigated by reading whichever field 055 defines and
  keeping graceful degradation; (b) the frozen snapshot being taken from the wrong
  commit, making the delta misleading — mitigated by recording the source commit in
  the JSON and by the fixture-based delta test; (c) forgetting a README update and
  failing `readme-sync.yml` — mitigated by the Section-12 `readme_sync --check`
  gate; (d) shipping a non-ruff-clean edit and raising the 661 baseline — mitigated
  by the Section-12 ruff gate. All are caught by the standard gates before merge.

## 17. Notes for Implementer

- **Extend, do not re-create.** 058 owns *no new script*. `generate_quality_report.py`
  is 031's; `check_dead_code.py` is 055's; `analyze_references.py` is 054's. If any
  of these is missing at start, stop and confirm the predecessor landed — do not
  scaffold a stand-in (that would collide with the real subtask's deliverable).
- **Mind the numbering trap.** `009` §7 and `013` §10 say "058 =
  generate_quality_report"; that is a provisional numbering. The authoritative map
  (`007_subtask_index.md`) is `031 = generate_quality_report`, `055 = check_dead_code`,
  **`058 = the dead-code section added to 031's report`**. Section 2 has the full
  table. Do not "fix" the planning docs.
- **Read the delivered 055 JSON before coding the renderer.** The exact field
  carrying the `013` §7 classification (`kind` vs `severity` vs a custom key) is set
  by 055; consume whatever it emits and do not force a schema change on 055.
- **Freeze the "before" snapshot deliberately.** Run `check_dead_code.py --format
  json` on the pre-057 tree, commit it to
  `docs/refactoring/reports/dead_code_baseline.json`, and record the source commit
  hash inside the file. This is the one artifact that makes 057's reduction
  auditable; without it the delta is meaningless.
- **Additive JSON only.** Fold the `dead_code` object in alongside 031's existing
  keys; never rename/remove them. Keep the roll-up `"version"` unless you truly break
  the shape.
- **Graceful degradation is non-negotiable.** The aggregator must still emit a valid
  report when `check_dead_code.py` is absent or emits garbage. Write and test the
  "checker unavailable" path first, then the populated path — mirror 031's approach.
- **Advisory, no CI wiring.** Do not edit any workflow. The dead-code section is
  informational; a hard `--fail-on-regression` gate for dead code is a separate,
  later, explicitly-scoped subtask (`013` §8.3, `009` §5.10).
- **Keep the README gate green in the same commit.** After adding the snapshot file,
  run `python scripts/readme_sync.py --write`, stage any updated `## Contents`, then
  verify `--check` exits 0 — otherwise `readme-sync.yml` fails on the PR.
- **Match the house style.** Mirror `scripts/docs/check_doc_sources.py` and the 031
  aggregator: `argparse`, `--format json`, `REPO_ROOT = Path(__file__).resolve().parents[1]`,
  `SystemExit(2)` on env error, no LLM/network. Consistency with the existing checker
  family is a review criterion.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **058** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
