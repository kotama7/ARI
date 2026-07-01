# Subtask 031: Add Quality Report Generator

> Phase 8: Quality Scripts · Risk: Low · Runtime code change: **No**
> Delivers the net-new aggregator script `scripts/generate_quality_report.py`.

---

## 1. Goal

Add a single **aggregator** script, `scripts/generate_quality_report.py`, that merges
the machine-readable JSON emitted by the individual quality checkers (the Phase 8 family:
`check_complexity.py`, `check_import_boundaries.py`, `check_directory_policy.py`,
`check_public_api_contracts.py`, `check_dead_code.py`, …) plus the reusable JSON already
produced by the existing `scripts/docs/*` checkers, into **one consolidated report** in
two forms:

- a **Markdown** roll-up (human triage: per-checker summary, per-area LOC/finding
  breakdown, regression delta vs a stored previous run) suitable for a PR comment or for
  saving under `docs/refactoring/reports/`, and
- a **JSON** roll-up (stable, machine-readable) so the report itself can be diffed and
  ratcheted over time.

Today every checker emits `--json` (the building blocks exist) but **nothing aggregates
them** — verified: `grep -rn "generate_quality_report" .github/workflows/ scripts/` returns
nothing, and `scripts/generate_quality_report.py` does not exist. This subtask fills that
gap and nothing else.

Classification of this deliverable: **KEEP (net-new)** — confirmed in
`docs/refactoring/009_quality_scripts_plan.md` §5.11 and the §4 overlap matrix ("Nearest
existing coverage: none").

---

## 2. Background

ARI has two mature, deterministic gate families but **no source-code quality suite and no
aggregated quality report**:

- **`scripts/docs/`** (10 files) — documentation / i18n gates. House convention (verified by
  reading `scripts/docs/check_doc_sources.py` lines 1-40): `#!/usr/bin/env python3`, a module
  docstring citing a design doc, `argparse`, `REPO_ROOT = Path(__file__).resolve().parents[N]`,
  PyYAML as the only non-stdlib dependency, `--json` flag, `SystemExit(2)` on
  usage/environment error, staged warning→error rollout. No LLM calls, no network
  (aligns with design principle P2, determinism).
- **`report/scripts/`** — LaTeX/HTML report-build gates (`Gate N` convention, e.g.
  `check_prompt_snapshots.py` = Gate 10).
- **`scripts/` top level** — `readme_sync.py` (per-dir README `## Contents` drift;
  `REPO_ROOT = Path(__file__).resolve().parents[1]`, verified at
  `scripts/readme_sync.py:31`), `run_all_tests.sh` (per-skill pytest isolation),
  `git-hooks/pre-commit` (runs `readme_sync --write`, non-blocking).

`docs/refactoring/009_quality_scripts_plan.md` designs an 11-checker source-quality suite
plus one aggregator, all sharing a common CLI contract (§3 of that plan): canonical flags
`--target / --config / --output / --format markdown|json / --warning-only /
--fail-on-regression`, an allowlist/baseline model, and a **stable per-checker JSON schema**
(§3, verbatim):

```json
{
  "checker": "str",
  "version": 1,
  "target": "str",
  "summary": { "...counts..." : 0 },
  "findings": [
    { "id": "str", "severity": "str", "file": "str", "line": 0,
      "kind": "str", "message": "str", "allowlisted": false }
  ]
}
```

`generate_quality_report.py` is the consumer of that schema — the "only checker a
maintainer needs to run for a full picture" (`009_quality_scripts_plan.md` §5.11).

**ID / naming note (must read before starting):** the authoritative subtask assignment is
`docs/refactoring/007_subtask_index.md` (verified): row **031 = `add_quality_report_generator`
→ `generate_quality_report.py`, Phase 8, Risk Low, Depends 001, runtime change No**
(`007_subtask_index.md:78`), and its Phase 8 note (`007_subtask_index.md:335`): *"031
add_quality_report_generator — every checker already emits `--json`; nothing aggregates
them. Depends on 001."* An **earlier draft**, `009_quality_scripts_plan.md` §7 (lines
246/249), used a *different provisional numbering* (031 = `check_dashboard_ux.py`, 058 =
`generate_quality_report.py`). **Follow the 007 index and this document's master prompt:
031 is the aggregator.** Where `009` says "058" for the aggregator, read it as "031". Do not
"fix" `009` in this subtask (planning docs are out of scope for edits here).

---

## 3. Scope

In scope:

1. Create `scripts/generate_quality_report.py` — a new, standalone, stdlib+PyYAML-only
   Python 3.13 aggregator conforming to the `scripts/docs/` house style and the
   `009_quality_scripts_plan.md` §3 CLI contract.
2. Create its default config `scripts/quality/generate_quality_report.yaml` (the
   `scripts/quality/` directory does **not** exist yet — verified `ls scripts/quality` →
   "No such file or directory"; this subtask or the first-landing Phase 8 checker creates
   it). The config declares which checkers to include, their invocation, and optional
   weightings.
3. Create/update `scripts/README.md` `## Contents` entry (or add a `scripts/quality/README.md`)
   so the `readme-sync.yml` gate stays green (see Section 11).
4. Add a focused unit test under `ari-core/tests/` (or a `scripts/`-local test) exercising
   the merge/roll-up logic against synthetic checker-JSON fixtures.

Explicitly consuming, but tolerant of absence: the Phase 8 checkers
(025/026/027/028/029/057→058) and any `scripts/docs/*` checker that emits JSON. The
aggregator must **degrade gracefully** when a checker is not yet implemented (skip with a
"not available" note, never crash), because at delivery time most Phase 8 checkers do not
exist yet.

---

## 4. Non-Goals

- **No runtime code change.** Do not touch anything under `ari-core/ari/**`,
  `ari-skill-*/**`, the React frontend (`ari-core/ari/viz/frontend/**`), prompts, configs,
  workflows-as-runtime, or directory names. This is a pure dev/CI tooling addition.
- **Do not implement the individual checkers here.** `check_complexity.py` (025),
  `check_import_boundaries.py` (026), `check_directory_policy.py` (028),
  `check_public_api_contracts.py` (029), `check_dead_code.py` (057) are separate subtasks.
  031 only *aggregates* their JSON.
- **Do not add a hard CI gate.** Per `009_quality_scripts_plan.md` §3 "Wiring rule" and §6,
  no checker (including the aggregator) is added to `.github/workflows/*` in its delivering
  subtask beyond `continue-on-error: true` (advisory). Wiring the report into CI is a
  separate, later decision. This subtask ships the script + test only; **it does not modify
  any of the 5 existing workflows**.
- **Do not install new tooling** (no radon, no vulture). radon is NOT installed
  (`python -c "import radon"` → ModuleNotFoundError); the aggregator must not depend on it.
- **Do not compute metrics itself.** The aggregator "detects nothing itself"
  (`009_quality_scripts_plan.md` §5.11); it only reads checker JSON. Any LOC/area numbers it
  reports come from checker output or a trivial `wc -l`-equivalent stdlib walk — never from
  an external analyzer.
- **Do not rename or move existing scripts** (`readme_sync.py`, `scripts/docs/*`).

---

## 5. Current Files / Directories to Inspect

Read these before implementing (all paths verified to exist unless marked):

Convention / templates to copy:
- `scripts/docs/check_doc_sources.py` (7,665 B) — canonical checker: docstring-cites-design-doc,
  `argparse`, `--json`, role vocabulary, `SystemExit(2)` on missing PyYAML, staged rollout.
- `scripts/docs/check_ref_coupling.py` (6,488 B) — diff-gate pattern with `--base-ref`,
  `--strict`, `--json`; fail-closed semantics for reference.
- `scripts/readme_sync.py` (14,330 B) — top-level-script `REPO_ROOT` convention
  (`parents[1]`, line 31), `--check`/`--write`, pure stdlib.
- `scripts/README.md` (4,913 B) — the `## Contents` list that `readme-sync.yml` enforces;
  a new script must be added here.
- `scripts/docs/README.md` (1,507 B) — per-dir README format reference.

Design / spec:
- `docs/refactoring/009_quality_scripts_plan.md` (32,801 B) — §3 CLI contract + JSON schema,
  §4 overlap matrix, §5.11 aggregator spec, §6 warning-mode rollout, §7 subtask assignment.
- `docs/refactoring/007_subtask_index.md` — row 031 (`:78`) + Phase 8 notes (`:316-337`) +
  dependency edge `001 -> 031` (`:404`, `:459`).
- `docs/refactoring/001_current_architecture_report.md` (68,212 B) — the baseline
  measurements 031 depends on (per-area LOC: `viz` 8,131 = 27% of core, `public/` 148, per-skill
  totals; ruff baseline 661 findings / 341 F401). The aggregator's "per-area breakdown"
  should be consistent with these numbers.
- `docs/refactoring/002_complexity_measurement_plan.md` (31,912 B) — measurement policy the
  complexity checker (025) follows; informs what fields 031 will receive.

Directories:
- `scripts/` — target directory for the new script (top level, alongside `readme_sync.py`).
- `scripts/quality/` — **does NOT exist** (net-new dir for configs/allowlists; verified).
- `docs/refactoring/reports/` — exists, currently **empty** (`ls` → only `.`/`..`); a natural
  default `--output` destination for the Markdown roll-up.
- `.github/workflows/` — 5 files (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`,
  `readme-sync.yml`, `refactor-guards.yml`); **read-only in this subtask** (no wiring).

Tooling baseline (verified 2026-07-01): Python **3.13.2**; **ruff 0.15.2 installed**;
**radon NOT installed**; `compileall`/`pytest` available; `node`+`npm` available (no pnpm).

---

## 6. Current Problems

1. **No aggregation.** Each checker's JSON is a silo. A maintainer must run and eyeball N
   separate JSON blobs to understand repo health; nothing rolls them into one view
   (`009_quality_scripts_plan.md` §5.11, "nothing aggregates today even though every checker
   emits JSON").
2. **No regression baseline for the whole suite.** Individual checkers each carry their own
   allowlist (`scripts/quality/<name>.allow.yaml`, per §3), but there is no single roll-up
   whose delta ("+3 new complexity offenders, −12 F401 after a `ruff --fix`") a reviewer can
   read at a glance.
3. **No area-weighted picture.** `viz` is 8,131 LOC (27% of core), `public/` is 148 LOC; skill
   `src` totals ≈25.5k LOC. Findings are only meaningful against these denominators, and no
   tool currently attaches findings to areas.
4. **Heterogeneous checker maturity at delivery time.** Most Phase 8 checkers will not exist
   when 031 lands, so any naive "invoke all checkers" aggregator would crash. The design must
   tolerate missing/partial inputs — a problem no existing script has had to solve.
5. **Report destination undefined.** `docs/refactoring/reports/` exists but is empty; there is
   no convention yet for where the human-readable quality report is written or how it is named.

---

## 7. Proposed Design / Policy

**Placement.** `scripts/generate_quality_report.py` (top level, next to `readme_sync.py`),
per the `009` §3 house rule "every new checker in `scripts/` (top level, alongside
`readme_sync.py`)". `REPO_ROOT = Path(__file__).resolve().parents[1]` (matches
`readme_sync.py:31`).

**Language / deps.** Python 3.13, **stdlib + PyYAML only** (PyYAML solely for reading the
YAML config). No LLM calls, no network, deterministic (P2). Guard the PyYAML import with the
same pattern as `check_doc_sources.py` (`SystemExit(2)` if absent).

**CLI contract** (subset of `009` §3 that applies to an aggregator; accept-and-ignore the
rest for uniformity):

| Flag | Meaning for the aggregator |
|---|---|
| `--target <dir>` | Directory containing pre-generated per-checker JSON files to merge. If omitted and `--run-checkers` is set, invoke the configured checkers with `--format json` and collect their stdout. |
| `--config <file>` | YAML listing which checkers to include, how to invoke each, and optional weightings. Default: `scripts/quality/generate_quality_report.yaml`. |
| `--output <file>` | Write the report to a file instead of stdout. Default stdout. |
| `--format markdown\|json` | `markdown` = human roll-up (default); `json` = machine roll-up. |
| `--run-checkers` | Optional: invoke each configured checker itself (subprocess, `--format json`) rather than reading a `--target` dir of JSON. Missing/failed checkers are recorded as `status: unavailable`, never fatal. |
| `--baseline <file>` | Previous JSON roll-up to diff against, for regression deltas. |
| `--warning-only` | Force exit 0 regardless of content (default posture while new). |
| `--fail-on-regression` | Exit 1 only if the merged report shows net-new findings vs `--baseline`. |

**Exit convention** (matches `scripts/docs/`): `0` = clean or `--warning-only`; `1` =
regression detected under `--fail-on-regression` (not `--warning-only`); `2` =
usage/environment error (missing PyYAML, unreadable config).

**Aggregated JSON roll-up schema** (superset that embeds each checker's §3 payload):

```json
{
  "report": "quality",
  "version": 1,
  "generated_at": "<ISO-8601 UTC>",
  "repo_root": "<abs>",
  "checkers": [
    { "checker": "check_complexity", "status": "ok|unavailable|error",
      "summary": { "...": 0 }, "finding_count": 0, "allowlisted_count": 0 }
  ],
  "areas": [
    { "area": "ari-core/ari/viz", "loc": 8131, "finding_count": 0 }
  ],
  "totals": { "checkers_run": 0, "checkers_unavailable": 0,
              "findings": 0, "new_vs_baseline": 0 },
  "regression": { "baseline": "<path|null>", "new_findings": [] }
}
```

**Markdown roll-up** = (a) a header with timestamp + repo, (b) a per-checker summary table
(checker · status · findings · allowlisted · Δ vs baseline), (c) a per-area breakdown table
(area · LOC · findings) whose LOC column is consistent with
`001_current_architecture_report.md` (viz 8,131 / public 148 / …), and (d) an optional
"New since baseline" section. Keep it PR-comment-sized.

**Graceful degradation policy (core requirement).** For every configured checker: if the
JSON file is absent (`--target` mode) or the subprocess is missing / exits ≠{0,1} /
emits unparseable JSON (`--run-checkers` mode), record `status: unavailable` (or `error`)
with the reason and continue. The aggregator must produce a valid report from **zero**
available checkers (useful even before any Phase 8 checker lands).

**Schema-version tolerance.** Read each incoming payload's `version`; if it is a version the
aggregator does not understand, mark that checker `status: error` with a "schema vX
unsupported" note rather than crashing.

**Default config** `scripts/quality/generate_quality_report.yaml`: a list of checker entries
`{ name, module_or_path, argv, weight, required: false }`. Ship it referencing the Phase 8
checkers with `required: false` so absence is expected. Ship a sibling
`scripts/quality/README.md` documenting the directory (keeps `readme-sync.yml` green).

---

## 8. Concrete Work Items

1. **Write `scripts/generate_quality_report.py`**
   - Shebang `#!/usr/bin/env python3`; module docstring citing
     `docs/refactoring/009_quality_scripts_plan.md` §5.11 and this subtask.
   - `REPO_ROOT = Path(__file__).resolve().parents[1]`.
   - Guarded `import yaml` → `SystemExit(2)` if missing (copy `check_doc_sources.py` lines
     ~28-36 verbatim in spirit).
   - `argparse` with the flags in Section 7.
   - `load_config(path) -> list[CheckerSpec]`.
   - `collect(specs, target, run_checkers) -> list[CheckerResult]` implementing the graceful
     degradation policy (subprocess via `subprocess.run` with a timeout; catch
     `FileNotFoundError`, `json.JSONDecodeError`, non-zero exit; never raise).
   - `compute_areas(repo_root) -> list[AreaRow]` — a trivial stdlib `rglob("*.py")` LOC walk
     for the fixed area list (`ari-core/ari/<subdir>`, per-skill `src`), excluding
     `__pycache__`; numbers must line up with `001_current_architecture_report.md`.
   - `merge(results, areas, baseline) -> ReportModel`.
   - `render_json(model)` and `render_markdown(model)`.
   - `main()` returning the exit code per the convention.
2. **Write `scripts/quality/generate_quality_report.yaml`** — default checker list
   (all `required: false`) + optional weights. Create the `scripts/quality/` directory.
3. **Write `scripts/quality/README.md`** — one-line-per-file `## Contents` block matching the
   `scripts/docs/README.md` format (satisfies `readme-sync.yml`).
4. **Update `scripts/README.md`** `## Contents` — add a bullet for
   `generate_quality_report.py` (and the `quality/` subdir) so the readme-sync gate stays
   green.
5. **Add a test** (`ari-core/tests/test_quality_report_generator.py` or a `scripts/` test) that
   feeds synthetic per-checker JSON fixtures (valid, missing, malformed, unknown-version) into
   the merge/render functions and asserts: (a) zero-checker run still yields a valid report,
   (b) a malformed/missing checker becomes `status: unavailable|error` without raising,
   (c) `--format json` round-trips a stable schema, (d) regression delta vs a baseline is
   computed correctly, (e) `--warning-only` forces exit 0.
6. **Self-check**: run `python scripts/generate_quality_report.py --format markdown` and
   `--format json` from repo root; confirm both produce a valid report with zero checkers
   present (graceful path) and non-zero when a fixture `--target` dir is supplied.

---

## 9. Files Expected to Change

Created (new):
- `scripts/generate_quality_report.py` — the aggregator (net-new).
- `scripts/quality/generate_quality_report.yaml` — default aggregator config (net-new; new dir).
- `scripts/quality/README.md` — per-dir README for the new `scripts/quality/` dir (net-new).
- `ari-core/tests/test_quality_report_generator.py` — unit test (net-new; final name at
  implementer's discretion, may live `scripts/`-local instead).

Modified (minimal, gate-driven only):
- `scripts/README.md` — add `## Contents` entry for the new script + `quality/` subdir
  (required by `readme-sync.yml`).

Not changed (assert during review): everything under `ari-core/ari/**`, `ari-skill-*/**`,
`ari-core/ari/viz/frontend/**`, `.github/workflows/**`, `config/`, `configs/`, `prompts/`,
all runtime YAML. (Note: **there is no `sonfigs/` directory** anywhere in the repo — the
confusable trio is `ari-core/ari/config/` (code) vs `ari-core/ari/configs/` (packaged
defaults) vs top-level `config/` (rubric data); none of them are touched here.)

---

## 10. Files / APIs That Must Not Be Broken

This subtask adds an isolated dev/CI script and touches no contract surface. Nonetheless,
verify the following remain untouched (they are contracts preserved across the whole refactor):

- **CLI**: `ari = ari.cli:app` (typer) and its subcommands — unaffected (no import into `ari`).
- **Public Python API**: `ari.public.*` (`claim_gate, config_schema, container, cost_tracker,
  llm, paths, run_env, verified_context`) — the aggregator must not import from `ari` at all.
- **MCP tool contracts**: the 14 `ari-skill-*` `src/server.py` servers — unaffected.
- **Dashboard API**: `ari/viz/routes.py` + `api_*.py` endpoints and `services/api.ts` — unaffected.
- **Checkpoint / output / config file formats**: `ari/checkpoint.py`, YAML under `config/` +
  `configs/` — read-nothing, write-nothing.
- **Existing gate scripts**: `scripts/readme_sync.py`, `scripts/docs/*`, `report/scripts/*`,
  `scripts/run_all_tests.sh` — not renamed, not moved, not modified (except the additive
  `scripts/README.md` `## Contents` bullet).
- **The 5 workflows** (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`,
  `readme-sync.yml`, `refactor-guards.yml`) — not rewritten, not extended in this subtask.
- **The §3 per-checker JSON schema** (`checker/version/target/summary/findings[...]`) — the
  aggregator is a *consumer* and must not require any deviation from it; it reads that schema
  as-is so future checkers stay decoupled.

No external contract is deprecated or changed by this subtask.

---

## 11. Compatibility Constraints

- **`readme-sync.yml` gate.** This workflow runs `scripts/readme_sync.py --check`, which fails
  (exit 1) if any directory README's `## Contents` omits a tracked file. Adding
  `scripts/generate_quality_report.py`, `scripts/quality/generate_quality_report.yaml`, and
  `scripts/quality/README.md` **requires** updating `scripts/README.md` and creating
  `scripts/quality/README.md` so the gate stays green. Run `python scripts/readme_sync.py
  --check` locally before finishing.
- **`refactor-guards.yml` gate.** It greps for `~/.ari` re-introduction and runs a HOME-write
  pytest guard. The new script must not reference `~/.ari` or write to `$HOME`; keep all output
  under the repo (e.g. `docs/refactoring/reports/` or `--output`). Determinism (P2): no network,
  no LLM.
- **House style.** Match `scripts/docs/` exactly: `argparse`, `--json`/`--format json`,
  `REPO_ROOT` via `parents[N]`, PyYAML-only extra dep, `SystemExit(2)` on env error, staged
  warning-first posture (`--warning-only` default). This keeps the script auto-discoverable by a
  future `run-all-quality-checks` orchestration without special-casing.
- **JSON schema stability.** The aggregated roll-up carries its own `"version": 1`; any future
  breaking change to the roll-up shape must bump that integer (so downstream consumers, e.g. a
  later CI comment step, can guard on it).
- **`scripts/run_all_tests.sh`** hardcodes 13 test paths and is **not** referenced by any
  workflow. If the test is placed under `ari-core/tests/`, it is already covered by that path;
  do not add a new path to `run_all_tests.sh` unless the test lives outside those 13 dirs.

---

## 12. Tests to Run

From repo root `/home/t-kotama/workplace/ARI`:

```bash
# 1. Everything still byte-compiles (new script included)
python -m compileall scripts/ ari-core/ari

# 2. Lint the new script to the ruff baseline (ruff 0.15.2 available; do not
#    add new findings — the repo baseline is 661 in ari-core, keep scripts clean)
ruff check scripts/generate_quality_report.py

# 3. Unit test for the aggregator
pytest -q ari-core/tests/test_quality_report_generator.py
#    (or the scripts-local test path chosen in Section 9)

# 4. Full test suite regression sanity
pytest -q

# 5. The script runs and self-reports with zero checkers present (graceful path)
python scripts/generate_quality_report.py --format markdown
python scripts/generate_quality_report.py --format json

# 6. README-sync gate stays green after adding the script + quality/ dir
python scripts/readme_sync.py --check
```

No frontend build is involved (this subtask does not touch `ari-core/ari/viz/frontend/`), so
`npm test` / `npm run build` are **not** required for 031.

---

## 13. Acceptance Criteria

1. `scripts/generate_quality_report.py` exists, is executable-style (`#!/usr/bin/env python3`),
   stdlib+PyYAML only, no `ari` import, no network, no LLM.
2. `python scripts/generate_quality_report.py --format markdown` and `--format json` both
   succeed with **zero** checkers available and emit a valid, non-empty report (graceful
   degradation proven).
3. Given a `--target` dir of synthetic per-checker JSON (valid + missing + malformed +
   unknown-version), the aggregator merges the valid ones, marks the rest
   `unavailable`/`error`, and never raises.
4. `--baseline` produces a correct "new since baseline" delta; `--fail-on-regression` exits 1
   only on net-new findings; `--warning-only` forces exit 0.
5. `python -m compileall scripts/ ari-core/ari` passes; `ruff check
   scripts/generate_quality_report.py` reports **0** findings; `pytest -q` passes with the new
   test included.
6. `python scripts/readme_sync.py --check` passes (READMEs updated).
7. `.github/workflows/*` are byte-for-byte unchanged; no file under `ari-core/ari/**` or
   `ari-skill-*/**` or the frontend is modified (`git diff --name-only` shows only the files in
   Section 9).
8. The Markdown per-area LOC column is consistent with
   `docs/refactoring/001_current_architecture_report.md` (e.g. `viz` 8,131, `public` 148).

---

## 14. Rollback Plan

Fully reversible; no runtime coupling:

1. `git rm scripts/generate_quality_report.py scripts/quality/generate_quality_report.yaml
   scripts/quality/README.md ari-core/tests/test_quality_report_generator.py` (and `rmdir
   scripts/quality` if empty).
2. Revert the additive `## Contents` bullet in `scripts/README.md`.
3. Re-run `python scripts/readme_sync.py --check` to confirm the tree is green again.

Because the aggregator is not wired into any workflow and imports nothing from `ari`, removal
cannot affect the CLI, the dashboard, MCP servers, or any existing gate.

---

## 15. Dependencies

Per the refactor dependency graph (`001 -> 031`) and `007_subtask_index.md:78,404,459`:

- **Hard predecessor: 001 — `measure_complexity_and_dependencies`.** 001 establishes the
  baseline measurements (per-area LOC, ruff baseline 661/341-F401, complexity policy) that the
  aggregator's per-area breakdown and regression framing rely on. 001 is also one of the
  inventory subtasks that must precede any runtime code change; 031 itself is **not** a runtime
  change, but it consumes 001's output. **031 must not start before 001 is complete.**
- **Soft / consumes-JSON-from (not blocking; graceful-degradation covers absence):** the other
  Phase 8 checkers — 025 (`check_complexity.py`), 026 (`check_import_boundaries.py`),
  028 (`check_directory_policy.py`), 029 (`check_public_api_contracts.py`), and the
  `scripts/docs/*` checkers that emit JSON. 031 can land before these exist; it simply reports
  them as `unavailable` until they arrive.
- **Downstream extender:** 058 (`add_dead_code_checker_to_quality_report`) folds subtask 057's
  dead-code checker into 031's report (`007_subtask_index.md:337`), so **031 precedes 058**.
- No other subtask blocks or is blocked by 031. It shares predecessor 001 with subtask 025
  (`001 -> 025, 031`); 025 and 031 are independent siblings and may proceed in parallel once 001
  lands.

---

## 16. Risk Level

**Low.**

- **Changes runtime code? No.** This subtask adds standalone dev/CI tooling under `scripts/`
  plus a test; it imports nothing from the `ari` package, modifies no runtime module, prompt,
  config, workflow, or frontend file, and renames no directory. The only edit to an existing
  file is an additive `## Contents` bullet in `scripts/README.md` (gate-driven).
- Consistent with `007_subtask_index.md:78` (Risk **Low**, runtime-change **No**).
- Residual risks are contained: (a) forgetting the README update trips `readme-sync.yml`
  (mitigated by Section 12 step 6); (b) a non-graceful subprocess call could crash on missing
  checkers (mitigated by the explicit degradation policy + fixture tests). Both are caught by
  the acceptance tests before merge.

---

## 17. Notes for Implementer

- **Copy, don't invent, the house style.** `scripts/docs/check_doc_sources.py` is the closest
  template: the guarded `import yaml → SystemExit(2)`, the `argparse` shape, the `--json`
  emitter, and the design-doc-citing docstring. `scripts/readme_sync.py:31` gives the exact
  `REPO_ROOT = Path(__file__).resolve().parents[1]` for a top-level script.
- **Aggregator, not analyzer.** Per `009_quality_scripts_plan.md` §5.11 the script "detects
  nothing itself." Resist the temptation to compute complexity/import-graph metrics here — that
  belongs to 025/026. The only self-computed numbers are per-area LOC (a trivial stdlib walk),
  and even those should match 001's report.
- **Design for empty input first.** At delivery most Phase 8 checkers will not exist. Write and
  test the zero-checker path before the multi-checker path; it is both the MVP and the
  correctness anchor.
- **Numbering trap.** If you open `009_quality_scripts_plan.md` and see "058 =
  generate_quality_report", that is the earlier provisional numbering — the authoritative map is
  `007_subtask_index.md` (031 = aggregator). Do not edit `009` in this subtask.
- **Default output destination.** `docs/refactoring/reports/` exists and is empty — a sensible
  default for the Markdown roll-up (e.g. `docs/refactoring/reports/quality_report.md`), but keep
  it behind `--output` so the script is side-effect-free by default (stdout).
- **Do not wire CI.** Section 4 / §3 "Wiring rule": no workflow change in this subtask. A later,
  separate subtask decides whether to add an advisory (`continue-on-error: true`) step.
- **radon is absent** — never `import radon`. **ruff 0.15.2 is present** and is the only lint the
  new file must satisfy (0 findings).
- Keep the file well under the plan's soft LOC gates (>500 warn / >800 review); an aggregator of
  this shape fits comfortably in ~250-400 LOC.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **031** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
