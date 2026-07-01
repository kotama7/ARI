# Subtask 028: Add Directory Policy Checker Script

- **Subtask ID:** 028
- **Phase:** Phase 8 — Quality Scripts
- **Deliverable:** `scripts/check_directory_policy.py`
- **Classification:** `KEEP` (net-new checker, the *placement/naming* slice not covered by `readme_sync.py`)
- **Changes runtime code:** **No** (see Section 16)
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`)

> **Planning-phase notice.** This document is a plan for a *future* coding session. Authoring it changes no runtime code, imports, prompts, configs, workflows, frontend, or directory names — the only file created is this `.md`. Everything under "Concrete Work Items" and "Files Expected to Change" describes what the **implementer of subtask 028** will do in a later, separate session.

---

## 1. Goal

Add a new repository-hygiene checker, **`scripts/check_directory_policy.py`**, that enforces the one dimension no existing gate covers: **where files are allowed to live and what directories may be named**. Concretely it must:

1. Assert the confusable **config trio** stays correctly separated and correctly named — `ari-core/ari/config/` (Python *locator* code), `ari-core/ari/configs/` (packaged default *data*), and top-level `ari-core/config/` (rubric/profile *data*) — and that **no `sonfigs/` directory is ever introduced** (verified absent today; the "sonfigs" token in upstream prompts is a typo, not a real path).
2. Ban re-introduction of removed/legacy directories and new top-level storage-dir collisions (e.g. a second root-level checkpoint dir, given root `checkpoints/` already coexists with `workspace/checkpoints/`).
3. Flag tracked files that violate placement policy (with an allowlist of current known exceptions so the gate starts advisory and ratchets).

The checker is **complementary, not duplicative**: `scripts/readme_sync.py` already enforces that every managed directory README *enumerates* its files; this script owns the orthogonal *placement/naming* dimension. Its classification is `KEEP (new slice)` per `docs/refactoring/009_quality_scripts_plan.md` §5.4.

**Explicit non-actions of this subtask** (owned elsewhere — do not do them here):
- Do **not** move, rename, merge, or delete the config trio (that is subtask **003 — `consolidate_config_configs_sonfigs`** and the `docs/refactoring/005_directory_consolidation_plan.md` chain). This subtask only *guards* the layout; it never mutates it.
- Do **not** wire the checker into any GitHub workflow. CI integration is a separate subtask (`docs/refactoring/012_github_workflow_integration_plan.md` assigns the `directory-policy` job to subtask **047**; the umbrella CI plan is subtask **032**).
- Do **not** implement the other Phase-8 checkers (`check_complexity.py`/025, `check_import_boundaries.py`/026, `check_docs_source_sync.py`/027, `check_public_api_contracts.py`/029, `check_viz_api_schema.py`/030, `generate_quality_report.py`/031).

---

## 2. Background

The quality-scripts inventory (`docs/refactoring/009_quality_scripts_plan.md`) and the master plan item **ST-3-1** (`docs/refactoring/000_master_refactoring_plan.md:140`) both call for a placement/naming policy gate over the config trio, stating explicitly that `sonfigs/` does not exist. A `grep` over `*.py/*.sh/*.yml/*.md` confirms **no `check_directory_policy.py` exists today** (verified: `ls scripts/check_directory_policy.py` → *No such file*; `grep -rln directory_policy scripts/` → empty) — this is a net-new file.

**What already exists (and what it does NOT cover):**
- `scripts/readme_sync.py` (351 lines, pure stdlib, no LLM/network) enforces that each managed `README.md` `## Contents` block *lists every file/subdir beneath it*. Its `--check` mode is the CI gate wired by `.github/workflows/readme-sync.yml`. It is an **enumeration** gate — it says nothing about whether a file is in the *right place* or a directory has a policy-legal *name*.
- `scripts/docs/*` checkers (e.g. `check_doc_sources.py`, 224 lines) validate docs↔source coupling, not repository structure.
- `.github/workflows/refactor-guards.yml` greps added lines for `~/.ari` references and asserts pytest writes no `$HOME/.ari` — a *content* ban, not a *placement* policy.

So the placement/naming dimension is genuinely **MISSING**; `readme_sync.py` is a `PARTIAL OVERLAP` only (`009_quality_scripts_plan.md:81`). This subtask fills exactly that gap and nothing more.

**Cross-doc numbering note (reconcile, do not be confused by).** The canonical index `docs/refactoring/007_subtask_index.md:75` and this master prompt both map **028 = `add_directory_policy_checker_script` → `check_directory_policy.py`, Phase 8, Low risk, depends on 003, runtime-change No**. The narrative in `009_quality_scripts_plan.md` §5.4 happens to label the same checker "subtask 027" (its local numbering is offset). **Follow the 007 index / this prompt: this is subtask 028.** The design content of `009` §5.4 is still the authoritative *specification*.

---

## 3. Scope

In scope for the subtask implementation:

1. **Create `scripts/check_directory_policy.py`** following the established checker convention (see §7): `#!/usr/bin/env python3`, module docstring citing the design doc, `argparse` with `--json`, `REPO_ROOT = Path(__file__).resolve().parents[1]` (top-level `scripts/`, matching `readme_sync.py`), non-zero exit on error, staged warning→error rollout. **Pure stdlib preferred** (matching `readme_sync.py`); PyYAML only if a YAML policy sidecar is adopted (see §7, `REVIEW_REQUIRED`).
2. **Encode the config-trio placement/naming rule** — the three real directories must exist with their real roles; a fourth confusable sibling (`sonfigs/`, or a new `sonfig*`/`config*` collision) is a violation.
3. **Encode legacy/duplicate-dir bans** — no new top-level storage dir beyond the known `checkpoints/` + `workspace/{checkpoints,experiments,staging}/` set; flag reintroduction of any directory 003/005 remove once those land.
4. **Encode a forbidden-tracked-artifact rule with an allowlist** — operate over the **git-tracked universe** (`git ls-files`) so the gate does not false-positive on git-ignored on-disk artifacts; an allowlist captures current known exceptions so the checker passes clean on today's tree and only fails on *new* violations.
5. **Emit both human (Markdown/text) and `--json` output**, mirroring the sibling checkers so subtask **031 — `generate_quality_report.py`** can aggregate it later.
6. **Update `scripts/README.md` `## Contents`** to list the new script (required to keep the `readme-sync` CI gate green — see §9).

Out of scope: everything in Section 4.

---

## 4. Non-Goals

- **No config-trio mutation.** No move/rename/merge/delete of `ari-core/ari/config/`, `ari-core/ari/configs/`, or `ari-core/config/`. That is subtask 003 / the `005_directory_consolidation_plan.md` chain. This checker is read-only over the tree.
- **No CI wiring.** No edit to any of the 5 workflows (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`, `refactor-guards.yml`). The `directory-policy` job is subtask 047; the CI umbrella is subtask 032.
- **No other checkers.** Do not create `check_complexity.py`, `check_import_boundaries.py`, `check_docs_source_sync.py`, `check_public_api_contracts.py`, `check_viz_api_schema.py`, `check_prompts.py`, `check_dashboard_ux.py`, `analyze_references.py`, `check_dead_code.py`, or `generate_quality_report.py`.
- **No enumeration logic.** Do not re-implement `readme_sync.py`'s "every dir README lists its files" check; delegate that dimension to it.
- **No dependency install.** Stay in the stdlib(+PyYAML) lane the other checkers use. No `radon`/`vulture`/graph libs.
- **No source, prompt, checkpoint, or frontend change.** Contract surfaces in Section 10 are read-only.
- **No hard-fail on pre-existing debt.** Known exceptions (e.g. root `checkpoints/`, on-disk git-ignored `node_modules/`) are allowlisted; the gate starts advisory (warning) and ratchets to error only on *new* violations.

---

## 5. Current Files / Directories to Inspect

All paths relative to `/home/t-kotama/workplace/ARI`. These are **read-only inputs**.

**The convention to imitate (checker house style):**
- `scripts/readme_sync.py` (351 lines) — the closest sibling: top-level `scripts/`, `REPO_ROOT = Path(__file__).resolve().parents[1]` (line 31), pure stdlib, `argparse` mutually-exclusive `--check`/`--write` (lines 339–346), exit 1 on drift, `SKIP_NAMES`/`SKIP_SUFFIXES`/`SKIP_RELPATHS` constants (lines 35–48) as the reusable ignore vocabulary.
- `scripts/docs/check_doc_sources.py` (224 lines) — the `scripts/docs/` idiom: `#!/usr/bin/env python3`, docstring citing a design doc, `argparse` + `--json`, `REPO_ROOT = Path(__file__).resolve().parents[2]`, `Finding` class with `level ∈ {error,warning,coverage}`, `return 1 if errors else 0`, PyYAML as the only non-stdlib dep.
- `scripts/README.md` — a **managed README** (`## Contents` present); it recursively lists `scripts/`, `scripts/docs/`, `scripts/fewshot/`. Adding a new script here trips `readme-sync` until this file lists it.

**The config trio to guard (verified real; see `docs/refactoring/005_directory_consolidation_plan.md`):**
- `ari-core/ari/config/` — Python **code** (locator): `finder.py` (146 lines), `__init__.py` (~628 LOC of Pydantic models + `auto_config()`), `README.md`.
- `ari-core/ari/configs/` — packaged **data** + loader: `defaults.yaml`, `model_prices.yaml`, `_loader.py` (58 lines: `ConfigLoader` Protocol + `FilesystemConfigLoader`), `__init__.py`, `README.md`.
- `ari-core/config/` — shipped rubric/profile/workflow **data**: `default.yaml`, `workflow.yaml` (23,661 bytes), `profiles/{cloud,hpc,laptop}.yaml`, `paperbench_rubrics/{generic,nature,neurips,sc}.yaml`, `reviewer_rubrics/*.yaml` (23 venues: acl, aer, ahr, apsr, chi, cvpr, econometrica, generic_conference, iclr, icml, icra, journal_generic, nature, neurips, osdi, philreview, pmla, qje, sc, siggraph, stoc, usenix_security, workshop) + `reviewer_rubrics/fewshot_examples/neurips/*.json`, `README.md`.
- **`sonfigs/` — DOES NOT EXIST** (`find -iname '*sonfig*'` → nothing). Confirm absence as the anchor of the naming rule.

**Storage/legacy-dir facts to encode as bans:**
- Root `checkpoints/` (empty, legacy) coexists on disk with `workspace/checkpoints/`, `workspace/experiments/`, `workspace/staging/`. `.gitignore` ignores root `checkpoints/` (line 26), `experiments/` (31), `workspace/` (70), `ari-core/experiments/` (83), `ari-core/checkpoints/` (84) — so **none of these are tracked** (`git ls-files` returns zero under them). The policy is: no *new* top-level storage dir beyond this known set.
- `ari-core/ari/viz/frontend/node_modules/` — **exists on disk but is git-ignored and NOT tracked** (`git ls-files … node_modules` → 0; `git check-ignore` confirms ignored). See the correction in §6/§17: a git-tracked scan will not see it, so it belongs in the allowlist/working-tree-scan section only, not the tracked-file rule.

**Policy/design sources to cite in the script docstring:**
- `docs/refactoring/009_quality_scripts_plan.md` §5.4 (the spec), `docs/refactoring/005_directory_consolidation_plan.md` (`check_directory_policy.py` referenced at lines 152, 169, 340, 366, 376), `docs/refactoring/000_master_refactoring_plan.md:140` (ST-3-1), `docs/refactoring/007_subtask_index.md:75` (this subtask row).

**Gate/workflow context (read-only, not edited here):**
- `.github/workflows/readme-sync.yml` (runs `python scripts/readme_sync.py --check`), `.github/workflows/refactor-guards.yml` (the diff/allow-list idiom a future CI wiring may reuse), `.gitignore`.

---

## 6. Current Problems

Recorded facts that motivate the checker (not tasks for this subtask to *fix* in source):

1. **No placement/naming gate exists.** The confusable trio `config/` (code) vs `configs/` (packaged data) vs top-level `config/` (rubric data) is enforced by *nothing*. A refactor could accidentally create a fourth `configs`-like dir, or a typo could introduce `sonfigs/`, and no gate would notice. `readme_sync.py` only checks that whatever dirs exist have their files *listed*, not that they are *legal*.
2. **`sonfigs/` is a live source of confusion.** Upstream prompts repeatedly reference a `sonfigs/` directory that has never existed (`find` confirms absence). A checker that asserts its absence turns a recurring documentation myth into a machine-checked invariant.
3. **Two coexisting checkpoint roots.** Root `checkpoints/` (empty, legacy) sits beside `workspace/checkpoints/`. Without a gate, a third divergent storage dir could appear silently; the consolidation plan (`005`) wants exactly one canonical run-dir home.
4. **Stale "committed `node_modules`" claim — corrected here.** Prior planning context asserted `node_modules/` is *committed/tracked* (a hygiene issue). **Direct verification contradicts this:** `git ls-files | grep -c node_modules` → **0**, and `git check-ignore ari-core/ari/viz/frontend/node_modules` confirms it is **git-ignored**. It exists on disk (a build artifact) but is untracked. The checker must therefore scan the **git-tracked** universe by default (so it does not false-positive on ignored on-disk dirs), and treat working-tree-only artifacts as an *optional*, allowlisted, working-tree scan.
5. **No aggregatable structural signal.** Subtask 031's `generate_quality_report.py` wants `--json` from every checker; today there is no structural-policy JSON to aggregate.

---

## 7. Proposed Design / Policy

**Principle: guard placement/naming over the tracked tree, mutate nothing, stay pure-stdlib, start advisory.**

1. **Location & shape.** New file `scripts/check_directory_policy.py` (top-level `scripts/`, a sibling of `readme_sync.py` — **not** `scripts/docs/`, which is doc-lint-specific). `#!/usr/bin/env python3`; docstring cites `009_quality_scripts_plan.md` §5.4 + `005_directory_consolidation_plan.md`; `REPO_ROOT = Path(__file__).resolve().parents[1]`; `argparse` with `--json` and `--target` (default `REPO_ROOT`); default (human) output plus `--json`; `return 1` when any *error*-level violation exists (staged: warnings do not fail until promoted). Reuse the `Finding(doc/path, level, message)` shape from `check_doc_sources.py` with `level ∈ {error, warning}`.
2. **Rule A — config-trio placement/naming.** Assert the three canonical dirs exist and keep their role separation: `ari-core/ari/config/` (must contain Python `.py`, i.e. code), `ari-core/ari/configs/` (must contain the packaged data files `defaults.yaml`/`model_prices.yaml`), top-level `ari-core/config/` (must contain the rubric/profile YAML). Assert **no `sonfigs/`** and no *new* sibling whose name is a near-collision of `config`/`configs` under `ari-core/ari/` or the repo root (case-insensitive `config`-family match against an allowlist of the three legal names). This rule must be written to survive subtask 003: after 003 lands its consolidated layout, the *encoded canonical set* is updated to 003's result (see §15) — the checker always encodes the **current landed** policy, never a speculative one.
3. **Rule B — storage/legacy-dir bans.** Allowlist the known storage set (`checkpoints/`, `workspace/`, `workspace/{checkpoints,experiments,staging}/`, `ari-core/checkpoints/`, `ari-core/experiments/`); flag any *new* top-level dir matching a storage/checkpoint/experiment/staging name outside that allowlist. Because these are all `.gitignore`d, this rule reasons about *directory names present on disk under version-controlled parents* or, more robustly, about `.gitignore` entries + newly-tracked paths — keep it conservative (warning-level) to avoid noise.
4. **Rule C — forbidden tracked artifacts.** Over `git ls-files`, flag tracked paths that policy forbids (e.g. a tracked `node_modules/`, `.venv/`, `dist/`, `build/`, `__pycache__/`, `*.pyc`, `.egg-info/`). Seed an **allowlist** with today's actual state so the gate passes clean now (today: none of these are tracked — node_modules is ignored — so the allowlist may start empty and the rule is a pure forward guard).
5. **Delegation.** Do **not** re-implement enumeration; if a directory-listing question arises, defer to `readme_sync.py`. Reuse its `SKIP_NAMES`/`SKIP_SUFFIXES` vocabulary conceptually (copy the constants, do not import cross-script unless a shared helper is introduced — `REVIEW_REQUIRED`).
6. **Policy source: embedded constants vs YAML sidecar — `REVIEW_REQUIRED`.** Preferred default: encode rules as **module-level constants** (like `readme_sync.py`'s `SKIP_*`), keeping the script pure-stdlib and dependency-free. If a `--config` YAML sidecar is wanted (as `009` §5.4 sketches), it introduces PyYAML (already used by `scripts/docs/`) **and** a new data file that itself needs a home under policy — decide deliberately. Recommendation: start with embedded constants; add `--config` only if a second consumer needs it.
7. **Staged rollout.** Default posture: **warnings, exit 0**, on the current tree (which is clean for Rules A/C). A `--strict` flag (or a later promotion by subtask 047) turns new violations into errors (exit 1). This mirrors the warning→error convention across `scripts/docs/` checkers.
8. **Self-consistency.** The new script must not itself violate the policy it enforces (it lives at the legal `scripts/` location; it introduces no new config-family dir).

---

## 8. Concrete Work Items

1. **Author `scripts/check_directory_policy.py`.** Header, docstring citing the design docs, `REPO_ROOT = parents[1]`, `argparse` (`--json`, `--target`, `--strict`), `Finding` dataclass/class with `level` and `as_dict()`, `main(argv) -> int`.
2. **Implement Rule A (config trio).** Constants `CONFIG_TRIO = {"ari-core/ari/config", "ari-core/ari/configs", "ari-core/config"}` and `CONFIG_FAMILY_ALLOWED = {"config", "configs"}`; scan for any dir whose lowercased name is in the config family (or matches `sonfig*`) that is not one of the three legal paths → error/warning. Assert each legal dir exists and holds its expected file *kind* (code vs YAML data).
3. **Implement Rule B (storage/legacy bans).** Constant `STORAGE_ALLOWLIST`; flag new top-level `checkpoints`/`experiments`/`staging`/`workspace`-family dirs outside it (warning-level).
4. **Implement Rule C (forbidden tracked artifacts).** Enumerate `git ls-files` (subprocess or `Path` walk of tracked paths); flag tracked `node_modules`/`.venv`/`dist`/`build`/`__pycache__`/`*.pyc`/`*.egg-info` against an `ARTIFACT_ALLOWLIST` (seeded empty — verified none tracked today).
5. **Wire `--json` output.** `{"scanned": N, "errors": [...], "warnings": [...]}` shaped like `check_doc_sources.py` so subtask 031 can aggregate.
6. **Run the checker against the current tree** and confirm it reports **zero errors** (Rules A and C are clean today; Rule B should be clean given the allowlist). Adjust allowlists so the current tree passes without weakening the forward guard.
7. **Update `scripts/README.md` `## Contents`.** Run `python scripts/readme_sync.py --write`, then hand-edit the new `check_directory_policy.py` bullet's `TODO` into a one-line description (per `readme_sync.py`'s no-LLM policy). Re-stage only `scripts/README.md`.
8. **(Optional) add a focused smoke test.** The repo has **no established test location for `scripts/` checkers** (they are validated by CI invocation), so the minimum is a self-contained `--check`/`--strict` run in the acceptance step. If a test is added, mirror the closest precedent; do not invent a new test tree — `REVIEW_REQUIRED`.
9. **Verify guardrails** (§12): `python -m compileall .`, `ruff check .` (script must be clean), `pytest -q` unchanged, `python scripts/readme_sync.py --check` green, `python scripts/check_directory_policy.py --json` exit 0.

---

## 9. Files Expected to Change

**Created:**
- `scripts/check_directory_policy.py` — the new placement/naming policy checker (pure stdlib; PyYAML only if the `--config` sidecar option in §7 is chosen).
- *(optional, `REVIEW_REQUIRED`)* `scripts/directory_policy.yaml` — only if the YAML-sidecar option is adopted instead of embedded constants. Default plan: **not created** (embed constants).
- *(optional)* a focused smoke test — only if a suitable precedent location is confirmed; default plan: none (validated via CI invocation).

**Modified:**
- `scripts/README.md` — add the `check_directory_policy.py` entry to `## Contents` (required for the `readme-sync` gate). Regenerate with `scripts/readme_sync.py --write`, then fill the new bullet's `TODO` by hand.

**Explicitly NOT changed** (guardrail): no file under `ari-core/ari/`, `ari-skill-*/`, `ari-core/config/`, `ari-core/ari/config/`, `ari-core/ari/configs/`, `docs/` (site), `report/`, or `ari-core/ari/viz/frontend/`. No `.github/workflows/*` (CI wiring is 047/032). No `requirements*.txt`, no `pyproject.toml`. This subtask does **not** move or rename the config trio (subtask 003).

---

## 10. Files / APIs That Must Not Be Broken

This subtask only *adds* a script and *lists* it in one README, so breakage is prevented by construction — but the checker reads these contract surfaces and must never edit them:

- **CLI contract:** single console script `ari = ari.cli:app`; the Typer command tree under `ari-core/ari/cli/`.
- **Public Python API:** `ari.public.*` (`claim_gate`, `config_schema`, `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`). In particular the checker must not touch `ari.public.config_schema` or the config loaders (`ari/config/finder.py`, `ari/configs/_loader.py`).
- **MCP contract:** the 14 `ari-skill-*/src/server.py` tool names/schemas; `ari/mcp/client.py`.
- **Dashboard API:** `ari/viz/routes.py` + `api_*.py` + `websocket.py`, consumed by `frontend/src/services/api.ts`.
- **Checkpoint / config file formats:** `ari/checkpoint.py`; every YAML under `ari-core/config/` and `ari-core/ari/configs/` (read-only; the checker asserts *placement*, never rewrites content).
- **Core↔skill stable interface:** `ari-core -> ari_skill_memory`.
- **Scripts invoked by workflows:** `scripts/readme_sync.py`, `scripts/docs/*` — must keep working; the new README edit must keep `readme_sync.py --check` green.

No compatibility adapter is needed because nothing is altered — only a new, additive gate is introduced.

---

## 11. Compatibility Constraints

- **Additive only (design principle P5).** One new script + one README listing edit; nothing is removed or renamed.
- **Determinism (P2).** The checker must be deterministic: no network, no LLM, stable ordering of findings (sort by path), fixed exit semantics. This matches the `ari-skill-memory` "no LLM calls" stance and the `readme_sync.py` "never calls an LLM/API" contract.
- **Dependency lane.** Stay pure-stdlib (preferred) or stdlib+PyYAML (the only non-stdlib dep the sibling `scripts/docs/` checkers use). No new package in `requirements.txt`/`requirements.lock`.
- **`readme-sync` gate.** Because `scripts/README.md` carries a `## Contents` block, adding the script **will** fail `.github/workflows/readme-sync.yml` until the README lists it — so the README edit (§9) is mandatory, not optional.
- **Staged rollout.** Default advisory (warnings, exit 0) so the checker's introduction cannot block unrelated PRs; promotion to a hard/error gate is deferred to subtask 047 (`012_github_workflow_integration_plan.md`).
- **No `~/.ari/` references introduced** (honors `refactor-guards.yml` guard 1) — trivially satisfied.
- **No self-violation.** The script sits at the policy-legal `scripts/` path and introduces no config-family directory.

---

## 12. Tests to Run

This subtask changes no runtime code, so "tests" are smoke + gate checks:

1. **Syntax/compile smoke:** `python -m compileall .` — must pass (includes the new script).
2. **Lint:** `ruff check .` — the new `scripts/check_directory_policy.py` must be clean (no new findings attributable to it).
3. **Behavior gate (unchanged):** `pytest -q` (core, honoring `pytest.ini`); optionally `bash scripts/run_all_tests.sh`. Outcomes must be **identical** to the pre-subtask baseline — the checker touches no importable runtime code.
4. **README gate:** `python scripts/readme_sync.py --check` — must pass **after** the `scripts/README.md` edit (proves the new script is correctly listed).
5. **The checker itself:** `python scripts/check_directory_policy.py --json` → exit **0** on the current tree (zero errors); `--strict` likewise clean today. Optionally craft a throwaway temp tree (a fake `sonfigs/` under a scratch dir passed via `--target`) to confirm it *does* flag a violation — do this in the scratchpad, not in the repo.
6. **Frontend:** `npm test` / `npm run build` are **not required** — this is not a frontend subtask.

---

## 13. Acceptance Criteria

1. `scripts/check_directory_policy.py` exists, is `#!/usr/bin/env python3`, uses `argparse` with `--json` (and `--target`, `--strict`), `REPO_ROOT = Path(__file__).resolve().parents[1]`, cites the design docs in its docstring, and returns non-zero only on error-level violations.
2. **Rule A** detects the config trio's separation, asserts each of `ari-core/ari/config/`, `ari-core/ari/configs/`, `ari-core/config/` exists with its expected file kind, and flags any `sonfigs/` or new config-family sibling.
3. **Rule B** flags new top-level storage dirs outside the `checkpoints/`+`workspace/*` allowlist; **Rule C** flags forbidden *tracked* artifacts (node_modules/.venv/dist/build/pycache/pyc/egg-info) with an allowlist seeded to today's (clean) state.
4. The checker operates on the **git-tracked** universe by default and therefore does **not** false-positive on the git-ignored on-disk `ari-core/ari/viz/frontend/node_modules/` (correction verified in §6).
5. Running the checker on the current tree yields **0 errors** (and Rule B/C warnings, if any, are only for allowlisted pre-existing items).
6. `--json` emits an aggregatable object (`scanned`/`errors`/`warnings`) shaped compatibly with the other `--json` checkers (for subtask 031).
7. `scripts/README.md` `## Contents` lists `check_directory_policy.py`, and `python scripts/readme_sync.py --check` passes.
8. `python -m compileall .`, `ruff check .`, and `pytest -q` are all green with no change to existing test outcomes.
9. The config trio was **not** moved/renamed; no workflow was edited; no runtime module changed.

---

## 14. Rollback Plan

Trivial and complete — the subtask adds one script and one README listing:

```bash
git -C /home/t-kotama/workplace/ARI rm scripts/check_directory_policy.py
git -C /home/t-kotama/workplace/ARI checkout -- scripts/README.md   # revert the ## Contents edit
```

Because no runtime code, config, workflow, or dependency was touched, removal restores the exact pre-subtask state (verify with an empty `git status` and a green `scripts/readme_sync.py --check`). There is no behavior to revert and no migration to undo. If a `directory_policy.yaml` sidecar was created, `git rm` it too.

---

## 15. Dependencies

Per the provided DEPENDENCY GRAPH (`A -> B` means A must precede / enables B):

- **Upstream (must precede 028): `003 -> 028`.** Subtask **003 — `consolidate_config_configs_sonfigs`** (`007_subtask_index.md:50`; Phase 2, High risk, runtime-change **Yes**) defines the *canonical* config layout. Subtask 028 encodes that layout as the policy it guards. **Rationale for the edge:** if the checker were authored before 003, it would freeze the *pre-consolidation* trio, then immediately conflict with 003's landed result. The implementer must therefore read 003's final layout (or, if 003 has not yet merged, encode the current verified trio — which 003 preserves conceptually via an import shim — and leave a `# TODO: sync with subtask 003 canonical layout` marker). The sibling subtask **027 — `add_docs_source_sync_checker_script`** also depends on 003 (`003 -> 027, 028`) but is otherwise unrelated.
- **Downstream (depend on 028): none in the provided graph.** The graph lists no `028 -> …` edge.
- **Informational consumers (NOT formal graph edges):** the CI-integration plan (`012_github_workflow_integration_plan.md`) assigns the `directory-policy` GitHub job to subtask **047**, and the quality-report aggregator **031 — `generate_quality_report.py`** consumes every checker's `--json`. Neither is a blocking edge for 028; they are why 028 must emit `--json` and stay CI-friendly.
- **Inventory-gate note:** 028 is **not** in the "must precede any runtime code change" set (001, 002, 020, 036, 045, 053, 059, 060, 067) and does not itself change runtime code — so that gate does not constrain it. (Its upstream 003 *does* change runtime code and is itself gated by that inventory set.)

This ordering is consistent with the DEPENDENCY GRAPH and the `007_subtask_index.md:75` row (`028 … depends on 003`).

---

## 16. Risk Level

**Risk: Low.** **Changes runtime code: No.**

- The subtask adds one stdlib-only checker under `scripts/` and edits one README's `## Contents`. It mutates no runtime code, imports, prompts, configs, workflows, directory names, or dependencies.
- Residual risks: (a) forgetting the `scripts/README.md` edit → `readme-sync` CI fails (caught by acceptance criterion 7); (b) over-strict rules false-positive on the current tree → mitigated by seeding allowlists from verified state and defaulting to advisory (warnings, exit 0); (c) scanning the working tree instead of the tracked universe → would falsely flag git-ignored `node_modules/` (explicitly corrected in §6, guarded by criterion 4).
- Matches `007_subtask_index.md:75`: Phase 8, risk **Low**, runtime-code-change **No**, inventory **No**.

---

## 17. Notes for Implementer

- **Run everything from the repo root** `/home/t-kotama/workplace/ARI`; agent threads reset cwd between shells — use absolute paths.
- **You are subtask 028**, not 027. The `009_quality_scripts_plan.md` §5.4 spec labels this checker "027" due to a local numbering offset; the canonical index (`007_subtask_index.md:75`) and this prompt say **028 → `check_directory_policy.py`**. Use `009` §5.4 for *design*, the index for *identity*.
- **`sonfigs/` is a phantom.** Verified absent (`find -iname '*sonfig*'` → nothing). The whole point of Rule A is to assert it *stays* absent. The real trio is `ari/config/` (code) vs `ari/configs/` (packaged data) vs top-level `config/` (rubric data).
- **Correct the `node_modules` myth.** Prior context claimed it is *committed*; it is **git-ignored and untracked** (`git ls-files | grep -c node_modules` → 0). Scan `git ls-files` by default so you do not false-positive on it; only an explicit opt-in working-tree scan should consider on-disk-but-ignored dirs.
- **Sit beside `readme_sync.py`, not in `scripts/docs/`.** The docs subdir is for VitePress/report doc lints; this is a repo-structure gate. `REPO_ROOT = parents[1]` (not `parents[2]`).
- **Delegate enumeration.** Do not reimplement "every dir README lists its files" — that is `readme_sync.py`. Copy its `SKIP_NAMES`/`SKIP_SUFFIXES` vocabulary as your ignore set if useful; a shared-helper import across scripts is `REVIEW_REQUIRED`.
- **Adding the script trips `readme-sync`.** `scripts/README.md` has a `## Contents` block; run `python scripts/readme_sync.py --write`, then replace the new bullet's `TODO` with a one-liner by hand (that tool never writes prose).
- **Start advisory.** Default to warnings/exit-0 so the checker's debut cannot block unrelated PRs. Promotion to a hard gate is subtask 047's job, not yours — do **not** edit any workflow.
- **Embed rules, prefer stdlib.** Follow `readme_sync.py`'s zero-dependency posture; only reach for PyYAML if you deliberately choose the `--config` sidecar (which then needs its own policy-legal home — a small irony to weigh).
- **Emit `--json`.** Subtask 031 aggregates it; keep the shape parallel to `check_doc_sources.py`'s `{"scanned","errors","warnings"}`.
- **Test the negative in scratch, not in the repo.** To prove the checker *fires*, point `--target` at a temp tree containing a fake `sonfigs/` under the scratchpad — never create a violating dir inside the repo.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **028** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
