# Subtask 026: Add Import Boundary Checker Script

> **Phase:** Phase 8 — Quality Scripts
> **Repo:** `/home/t-kotama/workplace/ARI` · branch `main` · `ari-core` version `0.9.0` · planning date `2026-07-01`
> **Primary output:** `scripts/check_import_boundaries.py` (net-new; **does not exist** today)
> **Runtime code change:** No (adds a new static-analysis script + its config/allowlist under `scripts/`; touches no runtime code, imports, prompts, runtime config, workflows, or frontend)
> **Classification of the artifact:** KEEP (net-new checker) — see `docs/refactoring/009_quality_scripts_plan.md` §4 and `docs/refactoring/003_dependency_boundary_report.md` §15.

---

## 1. Goal

Deliver `scripts/check_import_boundaries.py`: a deterministic, AST-based static-analysis tool that enforces the ARI module-layering contract described in `docs/refactoring/003_dependency_boundary_report.md`, specifically:

- **B1** — every `ari-skill-*/src/**` module may import from `ari-core` **only** via `ari.public.*` (and `ari.protocols.*`); any other `ari.<internal>` segment crossing the skill→core seam is a violation.
- **B2** — `ari-core/ari/**` must not import any `ari-skill-*` package, with the **single sanctioned exception** of `ari_skill_memory` (the first core→skill dependency, v0.6.0, editable-installed by `setup.sh`).

The checker ships in **warning mode first** (default posture `--warning-only`, exit 0), with a frozen allowlist/baseline seeded with the currently-known violations, so it makes the boundaries *measurable* without turning historical debt into red CI. It only **reads**; it never edits code, and it must not itself propose breaking the frozen skill→core interface (the fixes it drives happen in later runtime subtasks by *widening* `ari.public.*`).

## 2. Background

`ari-core/ari/public/__init__.py` (28 lines, docstring-only) literally states: *"Skills must only import from `ari.public.*`. This package is a thin re-export layer over the corresponding `ari.<module>` internals so core can refactor implementations freely while the contract stays put."* It enumerates the 8 exported submodules: `claim_gate`, `config_schema`, `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`. A sibling frozen surface, `ari-core/ari/protocols/` (`__init__.py`, `evaluator.py`, `README.md`), re-exports `PromptLoader` and the evaluator Protocol.

The contract is **declared but unenforced**. The nearest analog in the repo is `.github/workflows/refactor-guards.yml`, whose `no-new-home-ari-refs` job does a `git diff … | grep -E '~/\.ari'` against the merge base — that is a *content ban* on `~/.ari/` string literals, **not** an import-graph check. There is no gate anywhere that parses imports and asserts the `ari.public.*` / core→skill boundary. `grep` over `*.py/*.sh/*.yml/*.md` (excluding `node_modules/`, `docs/refactoring/`) confirms `check_import_boundaries.py` is **absent**; it is a net-new file (009 plan §1, verified negative).

The companion report `docs/refactoring/003_dependency_boundary_report.md` §3, §4, §15 already measured the exact seed violation set (see §6) and specifies this script as the "primary enforcement artifact for boundaries B1, B2, and the §11 exception." The subtask index (`docs/refactoring/007_subtask_index.md` line 73) records 026 as Phase 8, Low risk, **Depends On `—`**, Runtime Code Change **No**, Can Run Independently **Yes**.

## 3. Scope

In scope:

- Create `scripts/check_import_boundaries.py` following the established `scripts/docs/` house style (`#!/usr/bin/env python3`, module docstring citing a design doc, `argparse`, `REPO_ROOT = Path(__file__).resolve().parents[1]`, PyYAML as the only non-stdlib dependency, staged warn→error rollout, exit `2` on usage/environment error).
- Implement **B1** (skill → only `ari.public.*` / `ari.protocols.*`) and **B2** (core ↛ skill, except `ari_skill_memory`) as AST import-graph rules.
- Provide a machine-readable `--json` / `--format json` emitter (the building block consumed by the future aggregator `generate_quality_report.py`, subtask 031) and a human `markdown` emitter.
- Add a YAML config (`scripts/quality/check_import_boundaries.yaml`) for allowed-edge rules and a frozen allowlist (`scripts/quality/check_import_boundaries.allow.yaml`) seeded with the 7 known edges (§6) and the `ari_skill_memory` exception.
- Add a unit test (`scripts/tests/test_check_import_boundaries.py`, new) that asserts the checker catches every seed edge and passes on a clean fixture tree.

Out of scope (see §4).

## 4. Non-Goals

- **Do NOT fix any of the 7 seed violations.** Repointing `idea→ari.lineage`, `paper-re→ari.clone`, `transform→ari.orchestrator`/`ari.publish`, and the `coding`/`hpc` private fallbacks at `ari.public.*` is the **B1/B2 ADAPT runtime work** (later subtasks, gated by the inventory subtasks). This subtask only *detects* them.
- **Do NOT widen `ari.public.*`** (adding `ari.public.lineage`/`clone`/`publish`/`node_selection` shims) — that is a runtime, contract-*widening* change owned by the B1 ADAPT subtask.
- **Do NOT wire the checker into any `.github/workflows/*` file.** CI integration (advisory `continue-on-error` first) is subtask **032 (`add_quality_script_ci_plan`)**. The 5 existing workflows (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`, `refactor-guards.yml`) are not rewritten here.
- **Do NOT implement the symbol-level `ari.public.*` snapshot** — that is subtask **029 (`check_public_api_contracts.py`)**. This checker works at *module-segment* granularity.
- **Do NOT implement the dashboard-API↔frontend coupling check** — that is subtask **030 (`check_viz_api_schema.py`)**. (The intra-core `ari-core → ari.viz` direction, e.g. `ari/cli/lineage.py:151`, MAY be exposed here as an *optional, off-by-default* rule; see §7.5.)
- **No LLM calls, no network, no non-deterministic behavior** (design principle P2).
- **Do NOT modify any `ari-skill-*` code, `ari-core` code, prompts, runtime config, or the frontend.**

## 5. Current Files / Directories to Inspect

Contract surfaces the checker reasons about (all verified present):

- `ari-core/ari/public/__init__.py` (28 lines, docstring-only) — the B1 contract statement + 8 submodule names.
- `ari-core/ari/public/` — `claim_gate.py`, `config_schema.py`, `container.py`, `cost_tracker.py`, `llm.py`, `paths.py`, `run_env.py`, `verified_context.py` (8 submodules; the allowed skill→core import roots).
- `ari-core/ari/protocols/` — `__init__.py`, `evaluator.py`, `README.md` (second allowed root; re-exports `PromptLoader`).
- The 14 skill packages `ari-skill-{benchmark,coding,evaluator,hpc,idea,memory,orchestrator,paper,paper-re,plot,replicate,transform,vlm,web}/src/**` — the B1 scan targets.
- `ari-core/ari/**` — the B2 scan target.
- `setup.sh` and `ari-core/pyproject.toml` (44 lines; lines 27–31 comment) — document why `ari_skill_memory` is imported by core but not declared as a dependency (B2 exception).

Seed-violation source files (verified present at the cited lines on 2026-07-01):

- `ari-skill-idea/src/server.py:614` — `from ari.lineage import (`
- `ari-skill-paper-re/src/server.py:146` — `from ari.clone import clone, CloneError`
- `ari-skill-transform/src/server.py:681`, `:2083` — `from ari.orchestrator import node_selection as _ns`
- `ari-skill-transform/src/server.py:2433`, `:2451` — `from ari.publish import publish/promote, PublishError`
- `ari-skill-coding/src/server.py:569` — private fallback `from ari.container import config_from_env, run_shell_in_container`
- `ari-skill-coding/src/server.py:583` — private fallback `from ari.agent.run_env import capture_env`
- `ari-skill-hpc/src/slurm.py:211` — `from ari.agent.run_env import shell_capture_snippet`

House-style references (read before writing):

- `scripts/docs/check_doc_sources.py` (header lines 1–55) — the canonical docstring/`argparse`/`--json`/`SystemExit(2)`/PyYAML-guard idiom.
- `scripts/readme_sync.py` (header) — top-level `scripts/` file using `REPO_ROOT = Path(__file__).resolve().parents[1]` and stdlib-only, `--check`/`--write` exit convention.
- `.github/workflows/refactor-guards.yml` — the nearest analog (content ban, not an import graph) and the merge-base diff pattern.
- Design docs to cite in the module docstring: `docs/refactoring/003_dependency_boundary_report.md` §3/§4/§15 and `docs/refactoring/009_quality_scripts_plan.md` §5.2.

Directories that **do not exist yet** and are created by this subtask: `scripts/quality/` (new config/allowlist home, per 009 plan §3) and `scripts/tests/` (new; no `scripts/tests/` exists today).

## 6. Current Problems

1. **The B1 contract is declared but unenforced.** `ari.public.__init__` says skills must import only from `ari.public.*`, yet 4 confirmed cross-seam edges + 3 private-fallback edges exist with nothing to catch them or block new ones. Seed set (from `003_dependency_boundary_report.md` §3/§16, re-verified 2026-07-01):

   | # | Skill | Violating import | Location | Category |
   |---|-------|------------------|----------|----------|
   | 1 | idea | `from ari.lineage import …` | `ari-skill-idea/src/server.py:614` | cross-seam (ADAPT) |
   | 2 | paper-re | `from ari.clone import clone, CloneError` | `ari-skill-paper-re/src/server.py:146` | cross-seam (ADAPT) |
   | 3 | transform | `from ari.orchestrator import node_selection` | `ari-skill-transform/src/server.py:681, 2083` | cross-seam (ADAPT) |
   | 4 | transform | `from ari.publish import publish/promote, PublishError` | `ari-skill-transform/src/server.py:2433, 2451` | cross-seam (ADAPT) |
   | 5 | coding | private fallback `from ari.container import …` | `ari-skill-coding/src/server.py:569` | private fallback (primary already `ari.public.container`) |
   | 6 | coding | private fallback `from ari.agent.run_env import capture_env` | `ari-skill-coding/src/server.py:583` | private fallback (primary already `ari.public.run_env`) |
   | 7 | hpc | `from ari.agent.run_env import shell_capture_snippet` | `ari-skill-hpc/src/slurm.py:211` | cross-seam (public symbol exists) |

2. **The B2 exception is sanctioned but sprawled.** `ari_skill_memory` is imported from ~13 `ari-core/ari/**` sites (e.g. `agent/loop.py`, `pipeline/`, `viz/`), several outside the `ari/memory/` seam. Without a checker, a *new* `import ari_skill_*` in core would go unnoticed.

3. **`try/except ImportError` masks the imports from naive tooling.** Every skill→core touch is an in-function guarded import (e.g. `from ari.public import cost_tracker` in evaluator/idea/paper/paper-re/plot/replicate/vlm/web/transform). A grep-based check either misses in-function imports or trips on comments (e.g. the frontend `settingsConstants.ts:36` comment-style false positive noted in the report). **AST parsing is required.**

4. **No aggregation-ready signal exists.** Nothing emits a stable JSON edge list the future `generate_quality_report.py` (031) can roll up.

## 7. Proposed Design / Policy

A single stdlib-`ast` + PyYAML script. Deterministic, no LLM, no network (P2).

### 7.1 CLI contract (aligned with 009 plan §3)

```
scripts/check_import_boundaries.py
  --target <path>          # restrict scan subtree (default: repo root)
  --config <file>          # default: scripts/quality/check_import_boundaries.yaml
  --allow <file>           # default: scripts/quality/check_import_boundaries.allow.yaml
  --output <file>          # write report to file instead of stdout
  --format markdown|json   # default: markdown
  --json                   # alias for --format json (keeps scripts/docs/ parity)
  --warning-only           # force exit 0 (DEFAULT posture while new)
  --fail-on-regression     # exit 1 only on findings NOT in the allowlist (ratchet mode)
```

Exit convention (matches `check_doc_sources.py`): `0` = clean, `--warning-only`, or `--fail-on-regression` with no net-new debt; `1` = findings above threshold; `2` = usage/environment error (e.g. missing PyYAML → `SystemExit(2)`).

### 7.2 Discovery & parsing

- Enumerate skill packages by globbing `ari-skill-*/src/**/*.py` (14 packages); enumerate core by `ari-core/ari/**/*.py`.
- Parse each file with `ast.parse`; walk `ast.Import` and `ast.ImportFrom` nodes at **all** depths (module top-level **and** inside functions/`try` blocks — the guarded imports in §6 note 3 are real imports and MUST be reported). For `ast.ImportFrom`, resolve `node.module`; treat `level > 0` (relative) imports as intra-package (never a cross-seam violation).
- Record each import as an edge `{source_file, lineno, imported_module, kind}`. Comments and strings are ignored for free (AST does not see them), eliminating the `settingsConstants.ts` class of false positive.

### 7.3 Rule B1 — skill → only `ari.public.*` / `ari.protocols.*`

For any file under `ari-skill-*/src/**`, an import whose top segments are `ari.<seg>`:
- **Allowed** iff `<seg>` ∈ {`public`, `protocols`} (i.e. `ari.public.*`, `ari.protocols.*`), or the import is `ari_skill_*` (skill importing another skill is a *separate* rule — flag as cross-skill, off by default; the report lists no cross-skill edges today).
- **Violation** otherwise (any other `ari.<internal>` segment). This catches seed edges 1–7.

The allowed roots list is config-driven (`allowed_skill_import_roots: [ari.public, ari.protocols]`) so widening `ari.public.*` in a later subtask needs no code change here.

### 7.4 Rule B2 — core ↛ skill (except `ari_skill_memory`)

For any file under `ari-core/ari/**`, an import whose top segment matches `ari_skill_*`:
- **Allowed** iff the package is `ari_skill_memory` (config: `sanctioned_core_to_skill: [ari_skill_memory]`). Optional stricter mode (`restrict_memory_edge_to: ari/memory/**`) flags `ari_skill_memory` imports **outside** `ari/memory/` — off by default so it does not fail on today's 13-site sprawl; enabled by the B2 ADAPT subtask once centralization lands.
- **Violation** for any other `import ari_skill_*` from core.

### 7.5 Optional intra-core rules (off by default, config-gated)

The report (§15 item 4) notes two adjacent directions the same AST graph can assert; expose them behind config flags so this subtask stays scoped and does not overlap 029/030:

- `forbid_core_to_viz_from_cli: false` — flags `ari-core/ari/cli/**` importing `ari.viz.*` (catches `ari/cli/lineage.py:151` → `from ari.viz.api_orchestrator import _api_launch_sub_experiment`). Default off; owned conceptually by the B3/B7 pipeline work.
- Symbol-level public-API assertions are explicitly **out of scope** (subtask 029).

### 7.6 Allowlist / baseline model

- `--allow` YAML holds `known` edges keyed by a stable identity `"<repo_rel_file>::<imported_module>"` with an optional `note`. Findings on allowlisted identities are reported as `known` (not `new`) and never fail `--fail-on-regression`.
- Seed the allowlist with the 7 B1 edges (§6) and the `ari_skill_memory` core→skill edge, each with a `note` pointing at the owning ADAPT subtask. This is the mechanism that keeps historical debt out of CI while blocking *new* debt (009 plan §6, staged rollout).

### 7.7 Output schema

JSON follows the shared checker schema (009 plan §3): `{ "checker": "check_import_boundaries", "version": 1, "target": <str>, "summary": {"b1": n, "b2": n, "known": n, "new": n}, "findings": [ {"id", "rule": "B1|B2", "file", "line", "imported_module", "severity", "allowlisted": bool} ] }`. Markdown = a triage table (rule, skill/package, imported module, file:line, known/new).

## 8. Concrete Work Items

1. Create `scripts/check_import_boundaries.py` with the `scripts/docs/` header idiom, `REPO_ROOT = Path(__file__).resolve().parents[1]`, PyYAML import guard emitting `SystemExit(2)`, and the `argparse` surface in §7.1.
2. Implement AST discovery/parsing (§7.2): a `collect_imports(path) -> list[Edge]` that walks `ast.Import`/`ast.ImportFrom` at all depths, resolving relative-import levels.
3. Implement rule B1 (§7.3) and rule B2 (§7.4) over the skill and core file sets; classify each edge as `allowed` / `known` / `new`.
4. Implement the optional intra-core rule (§7.5) behind a default-off config flag.
5. Implement the allowlist loader (§7.6) and the `--fail-on-regression` gate (net-new only).
6. Implement Markdown + JSON emitters (§7.7) and `--output`/`--warning-only` handling with the exit convention.
7. Create `scripts/quality/check_import_boundaries.yaml` (allowed roots, sanctioned edge, rule toggles) and `scripts/quality/check_import_boundaries.allow.yaml` seeded with the 8 known edges from §6/§7.6.
8. Create `scripts/tests/test_check_import_boundaries.py`: (a) a fixture tree with a clean skill and a violating skill asserts B1 fires on the bad edge and not the good one; (b) a fixture asserts B2 allows `ari_skill_memory` and flags any other `ari_skill_*` from core; (c) a repo-level smoke test asserts the checker reports **exactly** the 7 seed edges when run with an *empty* allowlist, and **zero `new`** findings with the seeded allowlist.
9. Add a `## Contents` entry so `scripts/README.md` / `scripts/quality/README.md` / `scripts/tests/README.md` stay in sync with `scripts/readme_sync.py --check` (run `readme_sync.py --write` to generate; fill any `— TODO`).

## 9. Files Expected to Change

Created by this subtask (all net-new; none exists today):

- `scripts/check_import_boundaries.py` — the checker.
- `scripts/quality/check_import_boundaries.yaml` — rule config (new `scripts/quality/` directory).
- `scripts/quality/check_import_boundaries.allow.yaml` — frozen allowlist/baseline (8 seed entries).
- `scripts/tests/test_check_import_boundaries.py` — unit + smoke tests (new `scripts/tests/` directory).
- `scripts/quality/README.md`, `scripts/tests/README.md` — per-directory READMEs (`## Contents` convention) required by `readme_sync.py --check`.
- `scripts/README.md` — updated `## Contents` (regenerated by `readme_sync.py --write`).

Explicitly **not** changed: any `ari-core/ari/**`, any `ari-skill-*/src/**`, any prompt template, any runtime YAML under `ari-core/config*/` or `ari-core/ari/config*/`, any `.github/workflows/*`, and any file under `ari-core/ari/viz/frontend/`.

## 10. Files / APIs That Must Not Be Broken

This subtask adds a read-only script and **cannot** break a runtime contract, but the design must *preserve them conceptually* (never propose breaking them in this doc):

- **CLI** `ari = ari.cli:app` and all subcommands/flags — untouched.
- **`ari.public.*`** (8 submodules; the very contract this checker guards) — the checker reads it, must not modify or narrow it. Widening it is a later runtime subtask.
- **`ari.protocols.*`** — the second allowed skill→core root; untouched.
- **MCP tool contracts** (14 `ari-skill-*/src/server.py`, bare snake_case names, `{"result"|"error"}` envelope, `mcp__<skill>__<tool>` naming) — untouched; the checker parses imports, not tool registrations.
- **Dashboard API** (`ari/viz/routes.py` + `api_*.py`, port 8765) and **checkpoint/output/config file formats** — untouched.
- **`ari-skill-* → ari-core` stable interface** and the sanctioned `ari-core → ari_skill_memory` edge — the checker *enforces* these; it must never be used to justify a breaking rename/removal without a compatibility-adapter note.
- **Scripts already invoked by workflows** (`scripts/readme_sync.py`, `scripts/docs/check_*`) — untouched; the new READMEs must keep `readme_sync.py --check` green.

## 11. Compatibility Constraints

- **Contract classification vocabulary:** the artifact is **KEEP** (net-new). It *drives* future **ADAPT** work (B1: widen `ari.public.*` with `lineage`/`clone`/`publish`/`node_selection` shims; B2: centralize the `ari_skill_memory` edge). It must not encode any **DELETE_CANDIDATE**/**MERGE**/**MOVE_TO_LEGACY** action on runtime code.
- The word **"deprecated"** is reserved for external contracts; do not apply it to the internal seed violations (they are internal-import *violations*, to be ADAPTed).
- **Contract-widening, not breaking:** the allowed-roots list is config-driven precisely so that adding `ari.public.lineage`/etc. in a later subtask is backward-compatible and needs no edit to this checker.
- **Determinism (P2):** stdlib `ast` + PyYAML only; no LLM, no network, stable sort order in output so runs are reproducible and diff-friendly.
- **Tooling constraints:** `radon`/`vulture` are NOT installed (irrelevant here — no complexity/dead-code analysis); `ruff` IS available but not required; `node`/`npm` available, **no `pnpm`** (irrelevant — Python-only checker). Do not add new third-party runtime dependencies.
- **Rollout:** warning-mode-first. This subtask does not flip any gate to blocking and does not touch CI (subtask 032 owns wiring).

## 12. Tests to Run

From the repo root:

- `python -m compileall scripts/check_import_boundaries.py` — byte-compile the new script; also `python -m compileall .` for the tree.
- `pytest -q scripts/tests/test_check_import_boundaries.py` — the new unit/smoke tests (see §8 item 8). Also run `pytest -q ari-core/tests/` to confirm no regression (this subtask touches no runtime code, so it must stay green).
- `ruff check .` — lint the new script (keep it clean; the checker itself must not add ruff findings).
- Manual acceptance run: `python scripts/check_import_boundaries.py --format json --allow /dev/null` must list **exactly** the 7 seed edges of §6; `python scripts/check_import_boundaries.py --fail-on-regression` (with the seeded allowlist) must exit `0`.
- `python scripts/readme_sync.py --check` — the new READMEs and `## Contents` entries must be in sync.

(No `npm test`/`npm run build` — this is not a frontend subtask.)

## 13. Acceptance Criteria

1. `scripts/check_import_boundaries.py` exists, is byte-compilable, ruff-clean, and follows the `scripts/docs/` house style (shebang, docstring citing `003`/`009`, `argparse`, `REPO_ROOT = parents[1]`, `SystemExit(2)` on missing PyYAML).
2. Run against the repo with an **empty** allowlist, the checker reports **exactly** the 7 seed B1/private-fallback edges of §6 (idea:614, paper-re:146, transform:681/2083/2433/2451, coding:569/583, hpc/slurm:211) and **zero** false positives from comments or `try/except`-guarded imports.
3. B2 reports **zero** violations for `ari_skill_memory` (sanctioned) and would flag any other `import ari_skill_*` from `ari-core/ari/**` (proven by the fixture test).
4. With the seeded allowlist, `--fail-on-regression` exits `0`; adding a *new* forbidden edge to a fixture makes it exit `1`.
5. `--warning-only` always exits `0`; `--json`/`--format json` emit the schema in §7.7; `--format markdown` emits the triage table.
6. `pytest -q` (new tests + `ari-core/tests/`), `python -m compileall .`, `ruff check .`, and `readme_sync.py --check` all pass.
7. No `.github/workflows/*`, no `ari-core/ari/**`, no `ari-skill-*/src/**`, no frontend, and no runtime config file is modified.

## 14. Rollback Plan

The change is purely additive and read-only, so rollback is trivial and risk-free:

- `git rm scripts/check_import_boundaries.py scripts/quality/check_import_boundaries.yaml scripts/quality/check_import_boundaries.allow.yaml scripts/tests/test_check_import_boundaries.py` (and the two new READMEs), then `python scripts/readme_sync.py --write` to drop the `## Contents` entries, and revert `scripts/README.md`.
- Because nothing imports the script at runtime and it is not wired into any workflow, removal cannot affect `ari`, the dashboard, MCP skills, or any test outside `scripts/tests/`. No data migration or contract impact.

## 15. Dependencies

Per the provided **DEPENDENCY GRAPH**, there is **no `X -> 026` edge** — 026 has no predecessor subtask, matching the subtask index (`007_subtask_index.md` line 73: Depends On `—`, Can Run Independently **Yes**). It is one of the "independent checkers … that can start immediately" (`007_subtask_index.md` line 581).

- **Hard prerequisites:** none. The "inventory subtasks that MUST precede any runtime code change" (001, 002, 020, 036, 045, 053, 059, 060, 067) do **not** gate 026, because 026 is **not** a runtime code change (Section 16).
- **Informational input (not a blocker):** `docs/refactoring/003_dependency_boundary_report.md` (a planning doc, already written) supplies the seed violation set and the checker rules; and `001_current_architecture_report.md` / the 001 import-graph baseline are useful context but not required (no graph edge from 001 to 026).
- **Downstream consumers (depend on this):** subtask **032** (`add_quality_script_ci_plan`) may wire this checker into CI as advisory; subtask **031** (`generate_quality_report.py`, which depends on 001) aggregates its JSON; and the future **B1/B2 ADAPT** runtime subtasks rely on this checker running green in warning mode to make their fixes measurable (report §17 sequencing: "026 checker in *warning* mode … makes B1/B2 measurable" is step 1).

## 16. Risk Level

**Low.** **Runtime code change: No.** The subtask adds a standalone, read-only static-analysis script plus its YAML config/allowlist and a test module under `scripts/`. It imports nothing from `ari-core`/`ari-skill-*` at runtime, is not referenced by any of the 5 workflows, and cannot alter `ari` CLI, the dashboard, MCP tools, checkpoint/config formats, or the frontend. The only failure mode is the checker itself being wrong (false positives/negatives), which is contained by the seed-edge acceptance test and the warning-mode-first posture. Matches the index rating (Phase 8, Risk **Low**).

## 17. Notes for Implementer

- **Parse with AST, never grep.** Guarded imports (`try/except ImportError`) and in-function imports are the norm on the skill→core seam (e.g. `from ari.public import cost_tracker` across 9 skills); grep would either miss them or trip on the `settingsConstants.ts:36` comment. `ast.walk` over the whole module catches every real import and ignores comments/strings automatically.
- **Relative imports are safe.** Handle `ast.ImportFrom` with `node.level > 0` as intra-package; do not attempt to resolve them to `ari.*`.
- **`import ari` vs `from ari.x import y`.** For `import ari.lineage` record top segment chain `ari.lineage`; for `from ari.lineage import foo` record module `ari.lineage`. Both must be classified by the same segment logic.
- **Distinguish `ari` (core) from `ari_skill_*` (skills).** B1 keys on the `ari.` package; B2 keys on the `ari_skill_` prefix. `ari_skill_memory` is the sole sanctioned core→skill package (`pyproject.toml` lines 27–31 explain why it is imported but not declared).
- **Seed the allowlist, don't hardcode exceptions in logic.** The 7 B1 edges and the `ari_skill_memory` edge live in `check_import_boundaries.allow.yaml` with `note` fields pointing at the owning ADAPT subtasks, so the baseline shrinks by editing YAML as fixes land — never by editing the checker.
- **Keep `ari.public` / `ari.protocols` roots config-driven.** When the B1 ADAPT subtask adds `ari.public.lineage`/`clone`/`publish`/`node_selection`, no code change to this checker should be needed — the new segments are still under `ari.public`.
- **Stay warning-mode by default.** `--warning-only` should be the effective posture until the CI-plan subtask (032) decides otherwise; do not exit non-zero on the pre-existing seed set.
- **Cite the design docs in the module docstring** (`docs/refactoring/003_dependency_boundary_report.md` §3/§4/§15; `docs/refactoring/009_quality_scripts_plan.md` §5.2) to match the `scripts/docs/` convention of a docstring pointing at its spec.
- **Do not create `scripts/quality/` or `scripts/tests/` config that collides with future subtasks** — `scripts/quality/` will host sibling checkers (025/027/028/029/030/031); name files with the `check_import_boundaries` prefix so 031's aggregator can discover them unambiguously.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **026** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
