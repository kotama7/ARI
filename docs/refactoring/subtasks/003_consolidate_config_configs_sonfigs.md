# Subtask 003: Consolidate the `config` / `configs` Directory Namespace

- **Phase:** Phase 2 — Repository Hygiene
- **Planning date:** 2026-07-01
- **Repo:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core` version 0.9.0)
- **Author role:** senior software architect
- **Status:** PLANNING ONLY — this document changes no runtime code. It is the executable design for a later, gated coding session.
- **Runtime code change when executed?** **Yes** (see Section 16). This subtask is therefore gated by the inventory subtasks — see Section 15.

> **Naming note carried through the whole plan.** There is **NO `sonfigs/` directory** anywhere in the repo. `find -iname '*sonfig*'` returns nothing (re-verified 2026-07-01). The subtask slug `consolidate_config_configs_sonfigs` inherits a typo from the master prompt; "sonfigs" **does not exist**. The real target is the confusable **trio**: `ari-core/ari/config/` (Python code), `ari-core/ari/configs/` (packaged data + loader), and top-level `ari-core/config/` (shipped rubric/profile/workflow data).

---

## 1. Goal

Remove the standing hazard created by three similarly-named config directories whose names differ by a single character (`config` vs `configs`) and whose jobs are unrelated (code vs packaged-data vs shipped-rubric-data). Concretely:

1. Establish **one canonical accessor** for the shipped config-data root, and route every call site through it (today there are two accessor functions pointing at two different trees, plus ~15 inline path reconstructions that bypass both).
2. Adopt a **documented placement policy** ("code stays in `config/`, shipped data lives in one clearly-labelled home") that a later `check_directory_policy.py` gate (subtask 028) can enforce.
3. Ship the consolidation behind **import shims and a path seam** so that none of the frozen contracts (public API re-exports, YAML formats, doc-source paths, CLI, dashboard endpoints) break.

The named deliverable in `docs/refactoring/007_subtask_index.md` (row 003) is **"Consolidated config layout + import shim."**

## 2. Background

`ari-core` currently spreads configuration across three directories whose names collide:

| Directory | Kind | Real contents (verified) |
|---|---|---|
| `ari-core/ari/config/` | Python **code** | `finder.py` (145 LOC — workflow/profile YAML discovery), `__init__.py` (628 LOC — Pydantic models `ARIConfig`/`LLMConfig`/`BFTSConfig`/`SkillConfig`/`CheckpointConfig`/`LoggingConfig`/`EvaluatorConfig`, `load_config()`, `auto_config()`, `consolidation_enabled()`, `_discover_skills()`, `apply_bfts_env_overrides()`), `README.md` |
| `ari-core/ari/configs/` | packaged **data + loader** | `_loader.py` (58 LOC — `ConfigLoader` Protocol + `FilesystemConfigLoader` + `package_configs_root()`), `__init__.py` (11 LOC — re-exports loader), `defaults.yaml` (393 B — only `models.lineage_decision_default`), `model_prices.yaml` (1.1 KB), `README.md` |
| `ari-core/config/` | shipped **rubric/profile/workflow data** (sibling of the `ari/` package, NOT inside it) | `default.yaml` (2.1 KB), `workflow.yaml` (23.6 KB, `{{checkpoint_dir}}` templating), `profiles/{cloud,hpc,laptop}.yaml`, `paperbench_rubrics/{generic,nature,neurips,sc}.yaml`, `reviewer_rubrics/*.yaml` (23 venues), `reviewer_rubrics/fewshot_examples/neurips/*.json`, plus per-dir `README.md` |

Two independent module-name axes make this confusing to humans and easy to mis-import: `ari.config` (code) vs `ari.configs` (data). Two accessor functions return two different physical roots: `ari.config.finder.package_config_root()` → `ari-core/config/` (finder.py:28-42, walks up 3 levels), and `ari.configs._loader.package_configs_root()` → `ari-core/ari/configs/` (_loader.py:16-18). Two files named `default.yaml` and `defaults.yaml` hold unrelated content. And ~15 call sites reconstruct the sibling `config/` path inline with **inconsistent relative depths** instead of calling the finder.

This subtask is the runtime-change follow-through to the read-only inventory in `docs/refactoring/005_directory_consolidation_plan.md` (which classified the trio and named `configs/` as the intended "templates/presets" data home) and must respect the contract policy in `docs/refactoring/010_contract_preservation_policy.md`.

## 3. Scope

**In scope:**
- Introduce and adopt a single canonical accessor for the shipped config-data root; migrate the ~15 inline `Path(__file__)...parent.../ "config"` reconstructions to it.
- Adopt a documented directory-placement policy for config code vs config data.
- Fix the `default.yaml` / `defaults.yaml` near-collision (REVIEW_REQUIRED decision — rename or merge, Section 7).
- Provide import shims / re-export seams so `from ari.config import …` and `from ari.configs import …` keep working across the change.
- Update the affected README front-matter `path:` lists and reference docs (en + ja + zh mirrors) so the doc-sync gate stays green.

**Out of scope (belongs to other subtasks):** the runtime **storage** namespace (`checkpoints/`, `workspace/`, `experiments/`, `staging/` and the flat-checkpoint layout) — that is subtasks 004/005/006. This subtask touches config *data/code* directories only, not run-output directories.

## 4. Non-Goals

- **No** rename of the `ari.config` Python package. It is imported ~40+ times and is re-exported by the public `ari.public.config_schema`; renaming it would break a public contract. KEEP the name.
- **No** change to any YAML/JSON **schema** or key names inside the config files. Only file/dir *location and name* may change, and only behind a compat seam.
- **No** change to `workflow.yaml`'s `{{checkpoint_dir}}` templating or the output-path set it drives (that is storage-side, subtasks 004/005).
- **No** removal of the `ConfigLoader` Protocol or `FilesystemConfigLoader` (they are a `ari.protocols` contract).
- **No** creation of the `check_directory_policy.py` / `check_docs_source_sync.py` gates — those are downstream subtasks 028 / 027 that *depend on* this one.
- **No** invention of a `sonfigs/` directory; it does not exist and must not be created.

## 5. Current Files / Directories to Inspect

Config **code** (`ari-core/ari/config/`):
- `ari-core/ari/config/__init__.py` (628 LOC) — Pydantic models, env overrides, `load_config`, `auto_config` (workspace-root default at `__init__.py:588`), `consolidation_enabled` (`__init__.py:366`), `_discover_skills`.
- `ari-core/ari/config/finder.py` (145 LOC) — `package_config_root()` (:28-42), `find_workflow_in_dir()`, `find_workflow_yaml()` (4-tier search, :60-100), `find_profile_yaml()`, `load_workflow_config()`.
- `ari-core/ari/config/README.md`

Config **data + loader** (`ari-core/ari/configs/`):
- `ari-core/ari/configs/_loader.py` (58 LOC) — `package_configs_root()` (:16-18), `ConfigLoader` Protocol, `FilesystemConfigLoader` (`.yaml→.yml→.json`).
- `ari-core/ari/configs/__init__.py` (11 LOC), `ari-core/ari/configs/defaults.yaml`, `ari-core/ari/configs/model_prices.yaml`, `ari-core/ari/configs/README.md`

Shipped **rubric/profile/workflow data** (`ari-core/config/`):
- `ari-core/config/default.yaml`, `ari-core/config/workflow.yaml`, `ari-core/config/README.md`
- `ari-core/config/profiles/{cloud,hpc,laptop}.yaml` + `README.md`
- `ari-core/config/paperbench_rubrics/{generic,nature,neurips,sc}.yaml` + `README.md`
- `ari-core/config/reviewer_rubrics/*.yaml` (acl, aer, ahr, apsr, chi, cvpr, econometrica, generic_conference, iclr, icml, icra, journal_generic, nature, neurips, osdi, philreview, pmla, qje, sc, siggraph, stoc, usenix_security, workshop) + `README.md` + `reviewer_rubrics/fewshot_examples/neurips/*.json`

Packaging / contract anchors:
- `ari-core/pyproject.toml` — `[tool.hatch.build.targets.wheel] packages = ["ari"]` (line 42-43); no `MANIFEST.in`, no `force-include`.
- `ari-core/ari/public/config_schema.py` (re-exports the 7 Pydantic models — public API).
- `ari-core/ari/protocols/__init__.py:21` (re-exports `ConfigLoader` from `ari.configs._loader`).

Call sites that reconstruct the sibling `config/` path **inline** (bypassing the finder) — the migration surface:
- `ari-core/ari/core.py:38` (`reviewer_rubrics`), `:257-258` (`workflow.yaml`/`pipeline.yaml`)
- `ari-core/ari/cli/run.py:90-91` (already uses `package_config_root()`), `:140` (`profiles`), `:245`, `:400`, `:429`, `:561` (`workflow.yaml`)
- `ari-core/ari/cli/bfts_loop.py:97` (2-level), `:241` (3-level) — inconsistent depth in the same file
- `ari-core/ari/cli/projects.py:156`, `ari-core/ari/cli/lineage.py:58-59`, `:78`
- `ari-core/ari/pipeline/orchestrator.py:333`, `ari-core/ari/pipeline/stage_runner.py:384` (path embedded in a *generated* script string)
- `ari-core/ari/viz/routes.py:376`, `:612`
- `ari-core/ari/viz/api_workflow.py:276-277`, `:308-309`, `:392-393`, `:427-428`, `:450`, `:452` (mixes 3-level and 4-level fallbacks)

Doc-source `path:` front-matter that tracks these dirs (must stay in sync — en/ja/zh):
- `docs/reference/configuration.md` (front-matter tracks `ari-core/ari/config/__init__.py` and `ari-core/ari/configs`)
- `docs/reference/public_api.md` (documents the `ari.config` re-exports)
- `docs/reference/file_formats.md:363` (references a **non-existent** `ari-core/ari/configs/workflow.default.yaml` — see Section 6)
- `docs/concepts/bfts.md`, `docs/concepts/publication-lifecycle.md`, `docs/guides/cookbook.md` (front-matter track `ari-core/config/workflow.yaml`, `ari-core/config/profiles`) — plus their `ja/` and `zh/` mirrors.

## 6. Current Problems

**P1 — Single-character name collision.** `ari.config` (code) vs `ari.configs` (data) differ by one `s`. A typo silently imports the wrong package; humans conflate them constantly.

**P2 — Two accessor functions, two roots.** `finder.package_config_root()` → `ari-core/config/`; `_loader.package_configs_root()` → `ari-core/ari/configs/`. Nothing signals which is canonical; there is no single seam a future move can pivot on.

**P3 — Inline path reconstructions bypass the finder.** ~15 call sites hardcode `Path(__file__)...parent.../ "config"` with **inconsistent depths**:
- `bfts_loop.py:97` uses `.parent.parent` → resolves to `ari-core/ari/config/workflow.yaml`, i.e. the **code** directory, which contains **no** `workflow.yaml` (latent wrong-path fallback); the same file at `:241` uses `.parent.parent.parent` → the correct `ari-core/config/workflow.yaml`.
- `api_workflow.py` mixes `.parent.parent.parent / "config"` (→ `ari-core/config`, correct) with `.parent.parent.parent.parent / "config"` (→ repo-root `config/`, which **does not exist**).
These divergences are direct evidence that the missing single accessor causes real fragility.

**P4 — `default.yaml` vs `defaults.yaml`.** Two files whose names differ by one letter, in two different directories, holding unrelated content: `ari-core/config/default.yaml` (BFTS + checkpoint/logging defaults) vs `ari-core/ari/configs/defaults.yaml` (only `models.lineage_decision_default`). Classic confusion trap.

**P5 — The sibling `config/` tree is not inside the wheel.** `pyproject.toml` ships only `packages = ["ari"]` and has no `MANIFEST.in` / `force-include`. `ari-core/config/` is a **sibling** of `ari/`, so it is not packaged into the wheel; the code reaches it via `parent.parent.parent / "config"`, which only resolves under the editable/source install that `setup.sh` performs. This works today but is a packaging fragility — moving the data *inside* the `ari/` package would fix it as a side effect. (REVIEW_REQUIRED: confirm no non-editable install path depends on this before relying on the fix.)

**P6 — Doc drift.** `docs/reference/file_formats.md:363` states "Bundled defaults live in `ari-core/ari/configs/workflow.default.yaml`" — that path **does not exist** (verified). `docs/reference/public_api.md:50` says the names track `ari/config.py` — there is no `ari/config.py`, it is `ari/config/__init__.py`. The consolidation should correct these so the doc-sync gate (`scripts/docs/check_doc_sources.py`, `check_ref_coupling.py`) reflects reality.

## 7. Proposed Design / Policy

**Guiding rule (from 005): the code package keeps a distinct name; shipped config *data* gets one clearly-labelled home.**

### 7.1 Canonical placement policy
- **Config CODE home = `ari-core/ari/config/`.** KEEP. Pydantic models + `finder.py`. Name unchanged (public-contract-adjacent).
- **Config DATA home = `ari-core/ari/configs/`.** This is the single, in-package (therefore in-wheel, fixing P5) home for all shipped config data. Over the migration it absorbs the contents of the sibling `ari-core/config/` tree.
- **`ari-core/config/` = MOVE_TO_LEGACY, then DELETE_CANDIDATE.** Its data moves under `ari/configs/`. During the transition the directory is preserved and `finder.package_config_root()` keeps resolving there until every reference is repointed; it is deleted only after references reach zero and one release cycle of the shim has passed.

> Rationale for choosing `configs/` (data) as the survivor rather than renaming: `ari.config` is the widely-imported, public-API-adjacent **code** name and must not move; `ari.configs` is already the *data* namespace and is inside the `ari` package, so promoting it to the single data home both resolves P5 and matches the 005 policy without touching the public import surface.

### 7.2 Single accessor seam (mandatory, low-risk, do this first)
Make `ari.config.finder.package_config_root()` the **only** way any code locates the shipped config-data root, and migrate all inline reconstructions (Section 5 list) to call it. This is a pure refactor with **no behavior change** while `package_config_root()` still returns `ari-core/config/`. It is the pivot that later lets the physical data move be a **one-line change** inside `finder.py`. Correct the two latent-bug depths (`bfts_loop.py:97`, the 4-level `api_workflow.py` fallbacks) as part of this migration so behavior converges on the correct directory. For the generated-script string in `stage_runner.py:384`, emit a call to the accessor rather than a hardcoded `parents[1] / 'config'`.

### 7.3 `default.yaml` / `defaults.yaml` disambiguation (REVIEW_REQUIRED)
When the data lands under one home, the `default.yaml` + `defaults.yaml` pair becomes a same-directory collision. Resolve by renaming the tiny `configs/defaults.yaml` (single key `models.lineage_decision_default`) to an unambiguous name (e.g. `model_defaults.yaml`) **or** merging its one key into `default.yaml`. Whichever is chosen, update the loader key used by `FilesystemConfigLoader.load("...")` callers (`cost_tracker.py:19`, `orchestrator/lineage_decision.py:316`) and keep the old key resolvable for one release via the loader's search list.

### 7.4 Import / path shims (compatibility)
- Keep `from ari.config import …` and `from ari.configs import …` working unchanged — the code package name does not move, so no shim is needed for `ari.config`; for `ari.configs`, the loader API (`ConfigLoader`, `FilesystemConfigLoader`, `package_configs_root`) is preserved.
- `finder.package_config_root()` and `_loader.package_configs_root()` both remain importable; after the move they may resolve to the same physical tree, but neither symbol is removed within this subtask.
- Preserve `ari.public.config_schema` and `ari.protocols.ConfigLoader` re-exports verbatim.

### 7.5 Phasing
- **Phase A (safe, no behavior change):** 7.2 accessor migration + depth-bug fixes + doc corrections (P6). Shippable on its own.
- **Phase B (gated data move):** physical move of `ari-core/config/` contents under `ari/configs/`, flip `package_config_root()` to the new location, apply 7.3 disambiguation, update doc `path:` front-matter, add `MANIFEST.in`/package-data as needed so wheels ship the data. Phase B is the "High risk" runtime change and is gated per Section 15.

## 8. Concrete Work Items

1. **Inventory-freeze cross-check.** Confirm subtasks 001, 002 (and the other inventory gates) have produced their baselines; capture the current `ari.config`/`ari.configs` import graph and the inline-`config` call-site list as the migration checklist.
2. **Phase A — accessor seam.** Migrate every inline `parent.../ "config"` reconstruction (Section 5 list) to `ari.config.finder.package_config_root()` (add `find_profile_yaml`/`find_workflow_in_dir` usage where a subdir is addressed). No functional change while the accessor still points at `ari-core/config/`.
3. **Phase A — depth-bug convergence.** Fix `bfts_loop.py:97` (2-level → correct root) and the 4-level `api_workflow.py` fallbacks so all call sites resolve to the single root.
4. **Phase A — generated-script fix.** Update `stage_runner.py:384` so the emitted script calls the accessor instead of hardcoding `parents[1] / 'config'`.
5. **Phase A — doc corrections (P6).** Fix `file_formats.md:363` (non-existent `workflow.default.yaml`) and `public_api.md:50` (`ari/config.py` → `ari/config/__init__.py`) in en + ja + zh.
6. **Phase B — decide + apply data home.** Adopt `ari/configs/` as the data home; `git mv` the `ari-core/config/` tree under it (or place a compat shim), preserving subdir structure (`profiles/`, `paperbench_rubrics/`, `reviewer_rubrics/`, `fewshot_examples/`).
7. **Phase B — flip the seam.** Change `finder.package_config_root()` to return the new location (one line); verify `_loader.package_configs_root()` and `package_config_root()` relationship.
8. **Phase B — `default.yaml`/`defaults.yaml` disambiguation** per 7.3, with loader-key back-compat.
9. **Phase B — packaging.** Add `MANIFEST.in` or `[tool.hatch.build]` data inclusion so the moved data ships in the wheel (closes P5); verify with a test build.
10. **Phase B — doc `path:` front-matter sync.** Update every front-matter `path:` entry pointing at `ari-core/config/...` (configuration.md, bfts.md, publication-lifecycle.md, cookbook.md, + ja/zh mirrors) and each dir `README.md`.
11. **Run the full gate set** (Section 12) after each phase.

## 9. Files Expected to Change

Runtime code (accessor migration + seam flip):
- `ari-core/ari/config/finder.py` (accessor is the seam; one-line target change in Phase B)
- `ari-core/ari/core.py` (:38, :257-258)
- `ari-core/ari/cli/run.py` (:140, :245, :400, :429, :561), `ari-core/ari/cli/bfts_loop.py` (:97, :241), `ari-core/ari/cli/projects.py` (:156), `ari-core/ari/cli/lineage.py` (:58-59, :78)
- `ari-core/ari/pipeline/orchestrator.py` (:333), `ari-core/ari/pipeline/stage_runner.py` (:384)
- `ari-core/ari/viz/routes.py` (:376, :612), `ari-core/ari/viz/api_workflow.py` (:276-277, :308-309, :392-393, :427-428, :450, :452)
- `ari-core/ari/configs/_loader.py` and/or `ari-core/ari/configs/__init__.py` (only if the loader key changes in 7.3)

Data / packaging (Phase B):
- Move: `ari-core/config/**` → under `ari-core/ari/configs/` (all `.yaml`/`.json`/`README.md`)
- `ari-core/pyproject.toml` (data inclusion) and/or new `ari-core/MANIFEST.in`
- Rename or merge: `ari-core/ari/configs/defaults.yaml`

Docs (must ship in the same change):
- `ari-core/ari/config/README.md`, `ari-core/ari/configs/README.md`, `ari-core/config/README.md` (and its subdir READMEs)
- `docs/reference/configuration.md`, `docs/reference/public_api.md`, `docs/reference/file_formats.md`, `docs/concepts/bfts.md`, `docs/concepts/publication-lifecycle.md`, `docs/guides/cookbook.md` — plus `docs/ja/**` and `docs/zh/**` mirrors of each.

## 10. Files / APIs That Must Not Be Broken

- **Public Python API:** `ari.public.config_schema` re-exports (`ARIConfig`, `BFTSConfig`, `CheckpointConfig`, `EvaluatorConfig`, `LLMConfig`, `LoggingConfig`, `SkillConfig`). ADAPT only; keep symbols identical.
- **`ari.protocols.ConfigLoader`** re-exported from `ari.configs._loader` (`protocols/__init__.py:21`). KEEP.
- **Internal-but-widely-used imports:** `from ari.config import load_config, auto_config, SkillConfig, BFTSConfig, LLMConfig, ARIConfig, consolidation_enabled, apply_bfts_env_overrides` (CLI, pipeline, orchestrator, llm/client, mcp/client, viz, tests) and `from ari.configs import FilesystemConfigLoader` (`cost_tracker.py:19`, `lineage_decision.py:316`). KEEP importable.
- **`ari.config.finder`** public functions (`package_config_root`, `find_workflow_in_dir`, `find_workflow_yaml`, `find_profile_yaml`, `load_workflow_config`) — used by CLI/pipeline/viz. KEEP signatures.
- **YAML/JSON config formats** under `ari-core/config/` and `ari-core/ari/configs/` (workflow.yaml templating, rubric schema, profile keys). No schema change.
- **CLI `ari` console script**, **MCP tool contracts** (14 `ari-skill-*/src/server.py`), **Dashboard API** (`viz/routes.py` + `api_*.py` consumed by `frontend/src/services/api.ts`) — none of these read the config *directory path* directly, but `api_workflow.py`/`routes.py` locate `workflow.yaml`, so their behavior must be unchanged.
- **Doc-source gate:** every `path:` front-matter entry currently resolving to a real file must still resolve after the move.

## 11. Compatibility Constraints

- The `ari.config` package name is frozen (public-adjacent). Do **not** rename it; do **not** introduce a real `ari.configs`→`ari.config` alias that could shadow either.
- All existing imports remain valid without caller edits: the code package stays put; the data package keeps its loader API.
- The single-accessor migration (Phase A) must be behavior-preserving: while `package_config_root()` still points at `ari-core/config/`, no resolved path may change except the two latent-bug fixes (which move a *wrong* resolution to the *correct* one — call this out in the PR).
- Phase B keeps a compatibility seam: either leave `ari-core/config/` as a shim that re-exports paths, or keep both `package_config_root()` and `package_configs_root()` resolving to the new home for one release. The word "deprecated" applies only to the external-facing `ari-core/config/` documented path, not to internal modules.
- Loader key back-compat: if `configs/defaults.yaml` is renamed, `FilesystemConfigLoader` must still resolve the old key for one release.
- Wheel-packaging change (Phase B, item 9) must be verified by an actual build; do not assume hatchling picks up sibling data.

## 12. Tests to Run

Run after **each** phase from the repo root:

```
python -m compileall .
ruff check .
pytest -q
```

Targeted suites most likely to catch a regression (config imports + workflow discovery):
- `ari-core/tests/test_bfts.py`, `test_bfts_diversity.py`, `test_bfts_frontier_score.py` (`from ari.config import BFTSConfig`)
- `ari-core/tests/test_model_passthrough.py`, `test_default_provider.py` (`LLMConfig`)
- `ari-core/tests/test_gui_env_propagation.py` (`ARIConfig`, `apply_bfts_env_overrides`, `load_config`)
- `ari-core/tests/test_verified_context_wiring.py` (`consolidation_enabled`)
- `ari-core/tests/test_event_loop_and_csv.py` (`SkillConfig`)
- `ari-core/tests/test_workflow_contract.py` (workflow.yaml discovery/contract), `test_server.py`, `test_wizard.py`
- `ari-core/tests/test_idea_integration.py`

Doc / hygiene gates (these enforce the `path:` front-matter and README parity that this subtask edits):
- `python scripts/docs/check_doc_sources.py`
- `python scripts/docs/check_ref_coupling.py`
- `python scripts/docs/check_doc_links.py`
- `python scripts/readme_sync.py` (and `scripts/docs/check_readme_parity.py`)
- `bash scripts/run_all_tests.sh` (aggregate)

Packaging check (Phase B only): build the wheel and confirm the moved data is inside it (e.g. `python -m build ari-core` if available, or the project's documented build path) — closes P5.

Frontend `npm test`/`npm run build` are **not** applicable (no frontend files change).

## 13. Acceptance Criteria

1. `python -m compileall .`, `ruff check .`, and `pytest -q` all pass after each phase.
2. Zero call sites reconstruct the config-data path inline; a grep for `parent.parent.parent / "config"` (and its 2-/4-level variants) over `ari-core/ari/` returns only the accessor definition in `finder.py`. The `bfts_loop.py:97` and 4-level `api_workflow.py` fallbacks resolve to the correct root.
3. `from ari.config import …`, `from ari.configs import FilesystemConfigLoader`, `ari.public.config_schema`, and `ari.protocols.ConfigLoader` all import unchanged.
4. Exactly one canonical shipped-config-data home exists; `package_config_root()` is the single documented accessor for it. If Phase B lands, the data lives under `ari/configs/` and ships in the built wheel.
5. No `default.yaml`/`defaults.yaml` same-directory collision; the renamed/merged key is loader-resolvable with back-compat.
6. All doc `path:` front-matter and READMEs (en/ja/zh) point at real files; `check_doc_sources.py` / `check_ref_coupling.py` / `check_readme_parity.py` pass. P6 doc-drift items are corrected.
7. No `sonfigs/` directory is created anywhere.

## 14. Rollback Plan

- **Phase A** is a pure refactor: revert the accessor-migration commit (`git revert`) to restore inline reconstructions. No data or schema touched, so rollback is total and safe.
- **Phase B** (data move + packaging): rollback = revert the move commit(s). Because the seam is a single accessor, reverting `finder.package_config_root()` and the `git mv` restores the old resolution atomically. Since **all runtime storage is git-ignored** and this subtask touches only tracked config *data* (not run outputs), there is **no on-disk user-data migration to undo** — only the repo tree.
- Keep the compat shim (`ari-core/config/` re-export or dual-resolving accessor) in place for one full release before deleting the legacy directory, so a partial rollback never leaves a caller unable to find config.
- Land Phase A and Phase B as **separate** commits/PRs so either can be reverted independently.

## 15. Dependencies

Per the provided dependency graph, node 003 has **no incoming edge** — it is a root in the explicit graph and enables its successors:

```
003 -> 027   (add_docs_source_sync_checker_script)
003 -> 028   (add_directory_policy_checker_script)
```

So **027 and 028 depend on 003** and must run after it. 028 in particular is designed to enforce the config code-vs-data placement policy defined in Section 7.1.

However, 003 **is a runtime code change** (Section 16). By the project rule *"Inventory subtasks that MUST precede any runtime code change"*, 003 is gated by: **001, 002, 020, 036, 045, 053, 059, 060, 067**. Do not begin the runtime edits until those inventory/baseline subtasks have produced their reports (esp. 001 complexity/dependency baseline and 002 legacy/duplicate inventory). This matches `007_subtask_index.md`, which marks 003 as "Can Run Independently? No" for exactly this reason (it has no predecessor *edge*, but is a gated runtime change).

Phase-2 neighbors to coordinate with (shared directory namespace, no hard graph edge): **004** (runtime-path policy — reconciles the `workspace/checkpoints` vs `./checkpoints` disagreement), **005/006** (storage consolidation). Design input for this subtask: `docs/refactoring/005_directory_consolidation_plan.md` (config-triple classification) and `docs/refactoring/010_contract_preservation_policy.md`.

## 16. Risk Level

- **Risk: High.**
- **Changes runtime code: Yes.** Phase A rewires ~15 call sites (behavior-preserving except two latent-bug fixes); Phase B moves shipped config data, flips the accessor, and changes wheel packaging. The high rating comes from the breadth of call sites, the public-API/loader adjacency, the `default.yaml`/`defaults.yaml` disambiguation, and the packaging (P5) change. Splitting into Phase A (safe) and Phase B (gated) is the primary risk control.

## 17. Notes for Implementer

- **"sonfigs" is a typo — never create it.** Re-verify with `find -iname '*sonfig*'` (returns nothing) before starting so no one adds it by reflex.
- Do Phase A first and ship it alone; it delivers most of the anti-confusion value (the single accessor) at near-zero risk and makes Phase B a one-line pivot.
- When migrating call sites, watch the **depth traps**: from `ari-core/ari/core.py` the root is `.parent.parent` (2 levels), but from `ari-core/ari/cli/*.py` and `ari-core/ari/viz/*.py` it is `.parent.parent.parent` (3 levels). This exact inconsistency is why the accessor exists — route everything through `finder.package_config_root()` and stop counting `..`.
- `stage_runner.py:384` embeds the path inside a **generated script string** — the generated code runs in a subprocess, so it must import and call the accessor there too, not inline a hardcoded relative path.
- The doc-sync gates fail hard on stale `path:` front-matter; edit the en canonical **and** the ja/zh mirrors in the same commit, and run `check_doc_sources.py` / `check_readme_parity.py` locally before pushing.
- Tooling note: `radon` is NOT installed and `ruff` IS; there is no `pnpm` (use `npm`). No top-level `pyproject.toml` exists — the manifest is `ari-core/pyproject.toml`.
- Confirm P5 empirically before relying on the "move fixes packaging" claim: build a wheel and inspect whether `ari-core/config/` is currently absent and whether the moved `ari/configs/**` data is present after Phase B.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **003** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
