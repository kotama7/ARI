# Subtask 029: Add Public API Contract Checker Script

- **Subtask ID:** 029
- **Phase:** Phase 8 — Quality Scripts
- **Classification:** `KEEP` (net-new guard tooling; the `ari.public.*` surface it protects is `KEEP`/frozen — no runtime code, imports, prompts, configs, workflows, frontend, or directory names are changed)
- **Changes runtime code:** **No** (see Section 16)
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`)
- **Deliverable:** `scripts/check_public_api_contracts.py` (net-new; does **not** exist today)

> **Planning-phase notice.** This document is a plan for a *future* coding session. Authoring it changes no runtime code, imports, prompts, configs, workflows, frontend, or directory names. The only file created by authoring this plan is this `.md` itself. Everything under "Concrete Work Items" and "Files Expected to Change" describes what the **implementer of subtask 029** will do in a later, separate session.

> **Numbering note.** The authoritative subtask index (`docs/refactoring/007_subtask_index.md`, row 76) assigns this checker **029**. The upstream methodology doc `docs/refactoring/009_quality_scripts_plan.md` uses a *local* table (its §…line 243) that labels the same script `028`; that is that document's internal ordering, not the final subtask ID. When in doubt, follow `007_subtask_index.md` — this checker is **029**, and `028` is the *directory-policy* checker (`check_directory_policy.py`).

---

## 1. Goal

Add a deterministic, dependency-light **contract-snapshot gate** — `scripts/check_public_api_contracts.py` — that freezes the exact public API surface exposed under `ari-core/ari/public/` so that later refactoring subtasks (which *do* change runtime code) cannot silently remove, rename, or hollow out a symbol that a skill imports.

The `ari.public.*` package is the single **stable public contract** between the 14 `ari-skill-*` servers and `ari-core` internals: its own `ari-core/ari/public/__init__.py` docstring states "Skills must only import from `ari.public.*`". Today there is **no** automated check over it (confirmed: `grep` for `check_public_api_contracts` across `*.py/*.sh/*.yml/*.md` returns nothing; `009_quality_scripts_plan.md` §5.5 records it as MISSING / net-new). This subtask fills that gap.

Concretely, the checker must:

1. Enumerate the current public surface — the 8 submodules under `ari-core/ari/public/` and the exported names each declares (`__all__`) — into a normalized, machine-readable **snapshot**.
2. Compare the live surface against a **committed snapshot** and fail (staged warning→error) on any **removal or rename** of a submodule or exported symbol.
3. Flag when a public submodule **stops being a thin re-export** (i.e. grows real implementation logic instead of forwarding to an `ari.<module>` internal), which would defeat the "core can refactor internals freely" contract.
4. Provide a `--json` machine-readable report and a deliberate `--update` (regenerate-snapshot) mode, mirroring the `report/scripts/snapshot_prompts.py` regenerate idiom already used in the repo.

The deliverable is **one** new script plus its committed baseline snapshot file. No `ari/` runtime module, no skill, no frontend, no workflow, and no config is modified by this subtask.

**Explicit non-actions of this subtask** (owned elsewhere — do not do them here):
- Do **not** wire the checker into any `.github/workflows/*.yml` (CI integration is subtask **049 add_contract_check_workflows** / **032 add_quality_script_ci_plan**).
- Do **not** enforce the *import direction* "skills import only from `ari.public`" — that AST import-graph gate is subtask **026 add_import_boundary_checker_script** (`check_import_boundaries.py`). 029 snapshots the *surface*; 026 polices the *callers*. They are complementary, not the same tool.
- Do **not** aggregate `--json` outputs into a combined report — that is subtask **031 add_quality_report_generator** (`generate_quality_report.py`).
- Do **not** "fix" the two known quirks of the surface (empty package-level re-export; `ari/__init__.py` having no `__version__`). The checker must **faithfully record** the surface as-is; changing it is a separate runtime-code subtask with a compatibility-adapter obligation.

---

## 2. Background

### 2.1 What `ari.public` is today (verified)

`ari-core/ari/public/` contains **8 re-export submodules + `__init__.py` + `README.md`** (≈148 LOC total of thin re-exports, per `001_current_architecture_report.md`). Each submodule forwards to an `ari.<module>` internal so that core can refactor implementations while the contract stays put. Verified contents:

| Submodule (size) | Re-exports (`__all__`) | Backing internal | Known real consumer(s) |
|---|---|---|---|
| `claim_gate.py` (1351 B) | `run_hard_gate`, `check_emission`, `classify_concept`, `scan_science_data`, `CONCEPT_INVARIANTS` | `ari.pipeline.claim_gate` (+ `.contract`, `.invariants`) | evaluator `server.py:752` (`run_hard_gate`), `:630` (`classify_concept`,`CONCEPT_INVARIANTS`); coding `server.py:492` (`check_emission`); transform `server.py:1028` (`scan_science_data`) |
| `config_schema.py` (658 B) | `ARIConfig`, `BFTSConfig`, `CheckpointConfig`, `EvaluatorConfig`, `LLMConfig`, `LoggingConfig`, `SkillConfig` | `ari.config` | (typed settings; adapter target of subtask 003) |
| `container.py` (362 B) | **dynamic** `getattr(_impl,"__all__",…)` over `ari.container` | `ari.container` | coding `server.py:567` (`config_from_env`, `run_shell_in_container`) |
| `cost_tracker.py` (385 B) | **dynamic** `getattr(_impl,"__all__",…)` over `ari.cost_tracker` (docstring names `bootstrap_skill`/`record`/`init_from_env`) | `ari.cost_tracker` | idea, plot, replicate, evaluator, paper-re, web, vlm, paper, transform — `from ari.public import cost_tracker` |
| `llm.py` (330 B) | `LLMClient` | `ari.llm.client` | (adapter target of subtask 008) |
| `paths.py` (144 B) | `PathManager` | `ari.paths` | (adapter target of subtask 006) |
| `run_env.py` (645 B) | **dynamic** `getattr(_impl,"__all__",…)` over `ari.agent.run_env` (docstring names `capture_env`, `shell_capture_snippet`) | `ari.agent.run_env` | hpc `slurm.py:209` (`shell_capture_snippet`); coding `server.py:581` (`capture_env`) |
| `verified_context.py` (590 B) | `render_grounded_block`, `write_verified_context`, `build_verified_context` | `ari.pipeline.verified_context` | paper `server.py:1478` (`render_grounded_block`) |

`README.md` also points at a human-readable mirror, `docs/reference/public_api.md` (**exists** — verified). `ari-core/ari/public/__init__.py` (1366 B) is **docstring-only**: it lists the sub-modules and rationale but **re-exports nothing at the package top level** — so `from ari.public import LLMClient` fails today; callers must import the submodule (`from ari.public.llm import LLMClient`). This is a recorded fact, not something 029 fixes.

### 2.2 Why a snapshot gate is needed now

Multiple *runtime-changing* subtasks in the plan explicitly promise to keep `ari.public.*` symbols stable via compatibility adapters (per `007_subtask_index.md` "Subtasks That Require Compatibility Adapters"): 003 (`config_schema` import paths), 006 (`paths.PathManager`), 008 (`llm.LLMClient`), 057 (`ari.public.*` live-by-string roots before deletion). Without a machine-checked baseline, those promises are prose. 029 turns the surface into a committed snapshot so each of those subtasks (and any future one) trips a red gate the instant it drops or renames a public symbol.

### 2.3 Existing conventions this script must follow

The repo already has a mature checker family under `scripts/docs/` (all verified by reading source). The shared convention:
- `#!/usr/bin/env python3`; module docstring citing the governing design doc.
- `argparse` with a `--json` machine-readable mode.
- `REPO_ROOT = Path(__file__).resolve().parents[N]` — **N=2** for `scripts/docs/*.py` (two dirs deep), but **N=1** for a top-level `scripts/*.py` like `scripts/readme_sync.py` (verified `parents[1]`). Since this checker lives at `scripts/check_public_api_contracts.py` (one dir deep), it must use `parents[1]`.
- **PyYAML is the only non-stdlib dependency** used by the docs checkers; this checker should be **stdlib-only** (it emits JSON, not YAML) so it adds no dependency.
- Exit `1` on error; **staged rollout** (warning → error) so the gate can land advisory first and be promoted later.

The regenerate-snapshot pattern already exists at `report/scripts/snapshot_prompts.py` (argparse, `--root`) paired with the verifier `report/scripts/check_prompt_snapshots.py` (Gate 10). 029 should mirror that split conceptually: a `--update` mode writes the snapshot; the default mode verifies against it.

---

## 3. Scope

In scope for the subtask implementation:

1. **New script** `scripts/check_public_api_contracts.py` that:
   - Discovers public submodules by walking `ari-core/ari/public/*.py` (excluding `__init__.py`, `README.md`, `__pycache__/`).
   - Extracts each module's exported surface: the names in `__all__`. Because three submodules compute `__all__` **dynamically** (`container.py`, `cost_tracker.py`, `run_env.py` use `getattr(_impl, "__all__", [dir(_impl) …])`), a purely static AST read of the literal `__all__` assignment is **insufficient**; the implementer must resolve these (see §7 for the two allowed strategies).
   - Serializes the surface into a normalized JSON snapshot (sorted, deterministic).
   - In default (verify) mode: loads the committed snapshot, diffs it against the live surface, classifies each delta as `added` / `removed` / `changed`, and exits non-zero (once promoted) on any `removed`/`changed` (rename shows up as removed+added on the same module).
   - Emits `--json` for downstream aggregation (subtask 031).
   - Provides `--update` to regenerate the committed snapshot deliberately.
2. **Committed baseline snapshot** capturing the surface enumerated in §2.1 (exact path decided in §7 / §9; coordinate with subtask 034).
3. **"Thin re-export" health signal:** flag any public submodule whose body does more than forward (heuristic: contains a `def`/`class` definition, or non-import executable logic beyond the `__all__` computation). This is an *advisory* signal by default.
4. **Self-documentation:** module docstring citing `docs/refactoring/009_quality_scripts_plan.md §5.5` and `docs/refactoring/010_contract_preservation_policy.md`; a `--help` usage; and an entry added to `scripts/README.md`'s `## Contents` if the repo's `readme_sync.py` gate requires it (run `scripts/readme_sync.py --check` to confirm).

Out of scope: everything in Section 4.

---

## 4. Non-Goals

- **No runtime-code change.** No file under `ari-core/ari/`, no `ari-skill-*/`, no frontend, no `config/`/`configs/`, no prompt template is edited. In particular `ari-core/ari/public/*.py` is **read-only input**, not a target.
- **No CI wiring.** No `.github/workflows/*.yml` is created or edited (that is 049/032). The 5 existing workflows (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`, `refactor-guards.yml`) are untouched.
- **No import-direction enforcement.** Detecting "which skill imports which `ari.<internal>`" is subtask **026** (`check_import_boundaries.py`); 029 does not build the caller-side import graph.
- **No aggregation.** Combining checker `--json` outputs is subtask **031**.
- **No new dependency.** No `radon`, no `vulture`, no PyPI package. Stdlib only. `requirements.txt`, `requirements.lock`, `ari-core/pyproject.toml` untouched.
- **No "fix" of the known surface quirks.** The empty package-level re-export in `ari/public/__init__.py`, the missing `ari.__version__` in the empty `ari-core/ari/__init__.py`, and the dynamic-`__all__` pattern are **recorded**, not changed.
- **No MCP / dashboard / CLI snapshotting.** Those contracts have their own subtasks (034 fixtures; 030/065 dashboard schema; CLI is guarded elsewhere). 029 covers only `ari.public.*`.
- **No promotion to a hard gate in this subtask.** It lands advisory (warning) first; promotion to error-on-removal is a follow-up decision (see §7 rollout).

---

## 5. Current Files / Directories to Inspect

All paths relative to `/home/t-kotama/workplace/ARI`. **Read-only inputs** unless marked as the deliverable.

**The contract surface (primary input):**
- `ari-core/ari/public/__init__.py` (1366 B, docstring-only) — authoritative rationale text.
- `ari-core/ari/public/claim_gate.py` (1351 B) — static `__all__` (5 names).
- `ari-core/ari/public/config_schema.py` (658 B) — static `__all__` (7 names).
- `ari-core/ari/public/container.py` (362 B) — **dynamic** `__all__` over `ari.container`.
- `ari-core/ari/public/cost_tracker.py` (385 B) — **dynamic** `__all__` over `ari.cost_tracker`.
- `ari-core/ari/public/llm.py` (330 B) — static `__all__` (`LLMClient`).
- `ari-core/ari/public/paths.py` (144 B) — static `__all__` (`PathManager`).
- `ari-core/ari/public/run_env.py` (645 B) — **dynamic** `__all__` over `ari.agent.run_env`.
- `ari-core/ari/public/verified_context.py` (590 B) — static `__all__` (3 names).
- `ari-core/ari/public/README.md` (1275 B) — points to `docs/reference/public_api.md`.

**Backing internals (referenced by the surface; read-only, so the checker can resolve dynamic `__all__`):**
- `ari-core/ari/pipeline/claim_gate/` (+ `contract`, `invariants` submodules), `ari-core/ari/config/`, `ari-core/ari/container.py`, `ari-core/ari/cost_tracker.py`, `ari-core/ari/llm/client.py`, `ari-core/ari/paths.py`, `ari-core/ari/agent/run_env.py`, `ari-core/ari/pipeline/verified_context.py`.

**Human-readable mirror (keep in sync / cross-check, do not rewrite):**
- `docs/reference/public_api.md` (exists).

**Real consumers to sanity-check the snapshot against (read-only):**
- `ari-skill-evaluator/src/server.py` (`:752` `run_hard_gate`, `:630` `classify_concept`/`CONCEPT_INVARIANTS`), `ari-skill-coding/src/server.py` (`:492` `check_emission`, `:567` `config_from_env`/`run_shell_in_container`, `:581` `capture_env`), `ari-skill-transform/src/server.py` (`:1028` `scan_science_data`), `ari-skill-hpc/src/slurm.py` (`:209` `shell_capture_snippet`), `ari-skill-paper/src/server.py` (`:1478` `render_grounded_block`), and the many `from ari.public import cost_tracker` sites (idea/plot/replicate/evaluator/paper-re/web/vlm/paper/transform).

**Convention exemplars to copy (read-only):**
- `scripts/docs/check_doc_sources.py` (7665 B) — docstring/argparse/`--json`/staged-rollout template; `REPO_ROOT = parents[2]`.
- `scripts/docs/check_readme_parity.py`, `scripts/docs/check_ref_coupling.py` — same convention.
- `scripts/readme_sync.py` (14330 B) — a **top-level** `scripts/*.py` using `REPO_ROOT = parents[1]` (the correct index for the new script) and stdlib-only style.
- `report/scripts/snapshot_prompts.py` + `report/scripts/check_prompt_snapshots.py` (Gate 10) — the snapshot / verify + `--update`-style regenerate split to mirror.

**Governing plan docs (cite in the script docstring):**
- `docs/refactoring/009_quality_scripts_plan.md` (§5.5 defines this checker's behavior).
- `docs/refactoring/010_contract_preservation_policy.md` (contract-preservation policy).
- `docs/refactoring/007_subtask_index.md` (row 76; sequencing).

**Deliverable location (currently absent):**
- `scripts/check_public_api_contracts.py` — **to be created**.
- The committed snapshot file — path decided in §9 (coordinate with subtask 034).

---

## 6. Current Problems

Recorded facts that motivate this checker (not tasks for 029 to fix in runtime code):

1. **Zero automated protection of `ari.public.*`.** No script, test, or workflow verifies the surface. A refactor to `ari.pipeline.claim_gate`, `ari.config`, `ari.llm.client`, `ari.paths`, `ari.agent.run_env`, `ari.pipeline.verified_context`, `ari.container`, or `ari.cost_tracker` can drop a re-exported name and break a skill silently at import time (skills are launched by filesystem path, not tested on PyPI publish).
2. **Three submodules compute `__all__` dynamically.** `container.py`, `cost_tracker.py`, `run_env.py` do `from ari.X import *` then `__all__ = getattr(_impl, "__all__", [names…])`. This means the *actual* public names of those modules are whatever the backing internal exports at import time — a static-only checker would under-report them, and a change to the internal's `__all__` (or to `dir()`) silently changes the public surface. The checker must resolve these, and the snapshot must record the *resolved* name set so drift is caught.
3. **`ari.public` package top level exports nothing.** `ari/public/__init__.py` is docstring-only, so the README instruction "import from `ari.public.*`" is only partially honored (`from ari.public import X` fails; `from ari.public.mod import X` works). The snapshot must capture this faithfully (package-level `__all__` = empty) rather than pretend otherwise.
4. **No `ari.__version__`.** `ari-core/ari/__init__.py` is empty; the version lives only in `ari-core/pyproject.toml` (`0.9.0`). So the snapshot cannot key off a programmatic package version — it must record the tool + repo version out-of-band (e.g. read `pyproject.toml`), not `import ari; ari.__version__`.
5. **`docs/reference/public_api.md` can drift from code.** The prose reference is maintained by hand; nothing couples it to the actual surface. 029 can optionally cross-check it (advisory), but must not rewrite it.
6. **Downstream subtasks assume the guard exists.** `007_subtask_index.md` lists 003/006/008/057 as needing `ari.public.*` adapters and the sequencing section says the guard scripts (026 import-boundary, **029 public-API**) "make every later High-risk subtask safe to attempt." Until 029 lands, those adapters are unverified.

---

## 7. Proposed Design / Policy

### 7.1 Snapshot model

Emit a deterministic JSON document, e.g.:

```json
{
  "schema": 1,
  "generated_by": "scripts/check_public_api_contracts.py",
  "ari_core_version": "0.9.0",
  "modules": {
    "ari.public.claim_gate":       {"exports": ["CONCEPT_INVARIANTS","check_emission","classify_concept","run_hard_gate","scan_science_data"], "backing": "ari.pipeline.claim_gate", "thin": true},
    "ari.public.config_schema":    {"exports": ["ARIConfig","BFTSConfig","CheckpointConfig","EvaluatorConfig","LLMConfig","LoggingConfig","SkillConfig"], "backing": "ari.config", "thin": true},
    "ari.public.container":        {"exports": ["<resolved>"], "backing": "ari.container", "thin": true, "all_is_dynamic": true},
    "ari.public.cost_tracker":     {"exports": ["<resolved>"], "backing": "ari.cost_tracker", "thin": true, "all_is_dynamic": true},
    "ari.public.llm":              {"exports": ["LLMClient"], "backing": "ari.llm.client", "thin": true},
    "ari.public.paths":            {"exports": ["PathManager"], "backing": "ari.paths", "thin": true},
    "ari.public.run_env":          {"exports": ["<resolved>"], "backing": "ari.agent.run_env", "thin": true, "all_is_dynamic": true},
    "ari.public.verified_context": {"exports": ["build_verified_context","render_grounded_block","write_verified_context"], "backing": "ari.pipeline.verified_context", "thin": true},
    "ari.public":                  {"exports": [], "backing": null, "thin": true}
  }
}
```

Lists are sorted; keys are sorted on serialization → byte-stable snapshot suitable for a diff gate and for `git diff` review.

### 7.2 How to read the surface — two allowed strategies

The three dynamic-`__all__` modules force a choice; pick **one** and document it:

- **(A) Import-based introspection (recommended).** In a subprocess with `ari-core` on `sys.path` (the repo is editable-installed by `setup.sh`), `import ari.public.<mod>` and read the module's `__all__` (falling back to public `dir()` names when `__all__` is absent). This is the only way to get the *resolved* names for the dynamic modules and matches how skills actually see the surface. Guard with a clear error if `ari` is not importable, and keep it hermetic (no network, no LLM — deterministic per design principle P2). Prefer a subprocess so a heavy import side-effect cannot corrupt the checker process.
- **(B) Static AST + backing-module resolution.** Parse each `ari/public/*.py` with `ast`; for static `__all__` literals read them directly; for `from ari.X import *` + `getattr(_impl,"__all__",…)` patterns, statically resolve `ari.X.__all__` by parsing the backing module. This avoids importing `ari` but must special-case the wildcard/`dir()` fallback and will be more brittle. Acceptable if import is undesirable, but note the fidelity gap for `dir()`-derived names.

Whichever is chosen, the snapshot must record `all_is_dynamic: true` for the three modules so reviewers know those names are backing-module-derived.

### 7.3 Diff / gate semantics

- Classify each module/symbol delta: `added` (new public name — informational), `removed` (name gone — **contract break**), `changed` (module's backing pointer changed, or a module went from thin→non-thin).
- **Removals of an external contract default to error even in warning mode once the gate is promoted** (per `009_quality_scripts_plan.md §5.5`). During initial rollout, run advisory (warning, exit 0) with a prominent banner; a later, explicit step flips removals to `exit 1`.
- Additions never fail (adding a public symbol is backward-compatible), but they should print so the snapshot owner remembers to run `--update` and to update `docs/reference/public_api.md`.

### 7.4 "Thin re-export" heuristic

A public submodule is *thin* iff its module body is limited to: `from __future__` imports, a docstring, `import`/`from … import` statements (including `import … as _impl`), and the single `__all__` assignment. If an AST walk finds a `FunctionDef`/`ClassDef` or other executable statements, mark `thin: false` and emit an advisory finding ("public re-export module `X` grew real logic — `ari.public` must stay a thin contract layer"). This protects the "core can refactor internals freely" guarantee.

### 7.5 CLI surface (argparse)

- `--target ari-core/ari/public` (default; the surface dir).
- `--snapshot <path>` (default: committed baseline path from §9).
- `--update` — regenerate the snapshot in place (deliberate, like `snapshot_prompts.py`), print what changed, exit 0.
- `--json` — machine-readable report to stdout (for subtask 031 aggregation).
- `--strict` — promote warnings (removals / non-thin) to `exit 1` (staged rollout toggle; default advisory).
- Standard `--help`.

### 7.6 Determinism / dependency policy

Stdlib only (`argparse`, `ast`, `json`, `pathlib`, `subprocess`, `sys`, `importlib`). No PyYAML needed (JSON snapshot). No network, no LLM calls (aligns with design principle P2 determinism and the `ari-skill-memory` "no LLM calls" precedent). `REPO_ROOT = Path(__file__).resolve().parents[1]`.

---

## 8. Concrete Work Items

1. **Scaffold** `scripts/check_public_api_contracts.py` with the shebang, a docstring citing `009_quality_scripts_plan.md §5.5` + `010_contract_preservation_policy.md`, `REPO_ROOT = Path(__file__).resolve().parents[1]`, and an `argparse` parser exposing the flags in §7.5.
2. **Implement surface discovery** — walk `{REPO_ROOT}/ari-core/ari/public/*.py`, skip `__init__.py`/dunder/`__pycache__`, and for each module resolve its exported names via the chosen strategy (§7.2). Include the package-level `ari.public` row (currently `exports: []`).
3. **Implement the thin-re-export AST check** (§7.4) and record `thin`/`backing` per module.
4. **Implement snapshot serialization** — sorted, deterministic JSON per §7.1.
5. **Generate the baseline snapshot** with `--update` and commit it (path per §9); verify it matches §2.1 exactly (5+7+dynamic×3+1+1+3 static names, plus resolved dynamic sets).
6. **Implement verify + diff** (§7.3) with `added`/`removed`/`changed` classification, human-readable stdout, `--json`, and the staged `--strict` promotion.
7. **Add a `README` entry** — after creating the script, run `python scripts/readme_sync.py --check`; if it flags `scripts/README.md`, add the one-line `## Contents` entry for the new script (this is the *only* sanctioned edit outside the script + snapshot, and only if the gate requires it).
8. **Cross-check against real consumers** (§5) — confirm every symbol a skill actually imports (`run_hard_gate`, `check_emission`, `classify_concept`, `CONCEPT_INVARIANTS`, `scan_science_data`, `config_from_env`, `run_shell_in_container`, `capture_env`, `shell_capture_snippet`, `render_grounded_block`, and the `cost_tracker` names) appears in the snapshot; if a `dir()`-derived name is missing, revisit the resolution strategy.
9. **Self-test** — run `python -m compileall scripts/check_public_api_contracts.py`, `ruff check scripts/check_public_api_contracts.py`, and a smoke `python scripts/check_public_api_contracts.py --json` from repo root; confirm a deliberately mutated copy of a public module (in a scratch dir, never committed) is detected as `removed`.
10. **(Optional, advisory)** cross-check `docs/reference/public_api.md` mentions each snapshot symbol; report drift as a warning only — do **not** edit the doc.

---

## 9. Files Expected to Change

Created by the subtask **029 implementer** (later session), not by this planning doc:

- **`scripts/check_public_api_contracts.py`** — **NEW** (the deliverable).
- **The committed baseline snapshot** — **NEW**. Recommended path options (pick one; **REVIEW_REQUIRED** — reconcile with subtask **034 add_contract_snapshot_fixtures**, which owns "snapshots for public API / MCP / dashboard endpoints"):
  - `docs/refactoring/reports/public_api_snapshot.json` (co-located with subtask 001's baseline artifacts; keeps generated data out of `scripts/`), **or**
  - a `scripts/contracts/` (new) directory if 034 standardizes fixtures there, **or**
  - a `tests/`-adjacent fixture if 034 wires the snapshot into pytest.
  Until 034 decides, default to `docs/refactoring/reports/public_api_snapshot.json` and leave a `TODO(034)` comment.
- **`scripts/README.md`** — **CONDITIONAL, one line**: add the new script to `## Contents` **only if** `scripts/readme_sync.py --check` flags it (the repo's README-parity gate). No other content change.

**Explicitly NOT changed:** any `ari-core/ari/**`, any `ari-skill-*/**`, any frontend file, any `config/`/`configs/` YAML, any prompt template, any `.github/workflows/*.yml`, `requirements*.txt`, `ari-core/pyproject.toml`, `docs/reference/public_api.md` (read-only cross-check only).

---

## 10. Files / APIs That Must Not Be Broken

This subtask adds a *guard*; it must not perturb any contract. The guard exists to protect these — and the guard's own addition must leave all of them byte-for-byte unchanged:

- **`ari.public.*` surface** — the 8 submodules and every exported name in §2.1. 029 reads them; it must not rename, remove, or "clean up" any of them. The snapshot must record exactly the current names (including the empty package-level export).
- **CLI console script** `ari = ari.cli:app` — untouched (not in scope).
- **MCP tool contracts** — the 14 `ari-skill-*/src/server.py` servers and `ari/mcp/client.py` — untouched (026/034 territory).
- **Dashboard API** (`ari/viz/routes.py` + `api_*.py`, `services/api.ts`) — untouched (030/065 territory).
- **Checkpoint / output / config file formats** — untouched.
- **`ari-skill-*` → `ari-core` stable interface** — the sanctioned `ari-core → ari_skill_memory` edge and the `ari.public.*` import path used by skills must keep working; 029 only observes them.
- **Existing scripts called by workflows** — `scripts/readme_sync.py`, `scripts/docs/*`, `report/scripts/*` — untouched; 029 adds a new file beside them without altering their behavior or the 5 workflows that invoke them.
- **README/docs usage** — `docs/reference/public_api.md` and `ari-core/ari/public/README.md` — read-only.

---

## 11. Compatibility Constraints

- **Additive only.** 029 introduces a new script + a new data file; it removes/renames nothing. No compatibility adapter is required *for 029 itself*.
- **The script must tolerate the surface as it is**, including: the dynamic-`__all__` triple, the empty package-level `__all__`, and the absence of `ari.__version__`. It must not assume a name that isn't there.
- **The snapshot is the compatibility artifact for *others*.** When a later runtime subtask (003/006/008/057, etc.) changes an internal, it must either (a) keep every public symbol re-exported (adapter/shim) so 029 stays green, or (b) deliberately run `--update` **with an explicit ADAPT/compatibility note in that subtask's PR** — a bare `--update` that silently drops a symbol is exactly what the gate is meant to prevent, so `--update` should print removed names loudly.
- **Staged rollout.** Land advisory (warning, exit 0) first so introducing the gate cannot break existing CI; promotion of removals to `exit 1` (`--strict`) is a separate, explicit decision coordinated with 032/049.
- **No dependency drift.** Stdlib-only keeps `requirements.lock` and `ari-core/pyproject.toml` untouched, so no environment compatibility surface is affected.
- **Determinism (P2).** No network/LLM/time-dependent output; two runs on the same tree yield byte-identical snapshots/reports.

---

## 12. Tests to Run

Run from `/home/t-kotama/workplace/ARI` after implementing the script:

- **Compile / syntax:** `python -m compileall scripts/check_public_api_contracts.py` (and `python -m compileall .` for a full smoke pass).
- **Lint:** `ruff check scripts/check_public_api_contracts.py` (`ruff` is available; `radon` is not — do not rely on it). Keep the new file clean.
- **Unit / behavior smoke (manual, deterministic):**
  - `python scripts/check_public_api_contracts.py --update` → regenerates the snapshot; `git diff` shows the expected 8-module + package-level surface.
  - `python scripts/check_public_api_contracts.py` → exits 0 against the freshly written snapshot; `--json` emits well-formed JSON.
  - Copy `ari/public/llm.py` into a scratch dir, delete `LLMClient` from its `__all__`, point `--target` at the scratch copy → the checker reports `removed: ari.public.llm.LLMClient` (and, under `--strict`, exits 1). (Scratch only — never mutate the real file.)
- **Repo-wide test suite (regression — must stay green):** `pytest -q` (respecting `pytest.ini`), and `scripts/run_all_tests.sh` for the per-skill suites. 029 adds no import to `ari`, so these should be unaffected; run them to confirm no accidental import-time side effect.
- **README-parity gate:** `python scripts/readme_sync.py --check` (add the `scripts/README.md` entry only if this flags it).
- **Frontend:** **N/A** — this subtask touches no frontend; do **not** run `npm test`/`npm run build`.

---

## 13. Acceptance Criteria

1. `scripts/check_public_api_contracts.py` exists, is executable-style (`#!/usr/bin/env python3`), stdlib-only, and passes `python -m compileall` + `ruff check`.
2. Running `--update` produces a deterministic, sorted JSON snapshot containing exactly the 8 public submodules **plus** the package-level `ari.public` row, with the exported names from §2.1 — and the three dynamic modules' resolved name sets are captured (flagged `all_is_dynamic: true`).
3. Every symbol a real skill imports today (§5) is present in the snapshot.
4. Default (verify) mode exits 0 against the committed snapshot; a simulated removal (scratch copy) is reported as `removed` and, under `--strict`, exits 1.
5. The thin-re-export check reports all 8 current submodules as `thin: true` (they are pure re-exports today); a synthetic module with a `def`/`class` is reported `thin: false`.
6. `--json` output is valid JSON consumable by a future aggregator (031).
7. No file outside `scripts/check_public_api_contracts.py`, the committed snapshot, and (conditionally) `scripts/README.md` is modified. `git status` shows no change under `ari-core/ari/`, `ari-skill-*/`, `frontend/`, `config*/`, `.github/`, or `docs/reference/`.
8. `pytest -q` and `scripts/run_all_tests.sh` remain green (no regression introduced by adding the script).
9. The script's docstring cites `docs/refactoring/009_quality_scripts_plan.md §5.5` and follows the `scripts/docs/*` convention (argparse, `--json`, staged rollout, `REPO_ROOT = parents[1]`).

---

## 14. Rollback Plan

Trivial and self-contained — this is a purely additive, non-runtime subtask:

1. `git rm scripts/check_public_api_contracts.py` and remove the committed snapshot file.
2. Revert the one-line `scripts/README.md` `## Contents` addition (if it was made) — or re-run `python scripts/readme_sync.py --write` to regenerate it.
3. Confirm no other file changed (`git status` clean under `ari-core/`, `ari-skill-*/`, `.github/`).

Because 029 is not wired into any workflow (CI wiring is 049) and adds no import to `ari`, removing it cannot break CI, the CLI, MCP servers, the dashboard, or any skill. There is nothing to migrate back.

---

## 15. Dependencies

Per the provided **DEPENDENCY GRAPH**, **029 is a root** — it has **no incoming edge**, i.e. **no hard predecessor**. (Confirmed by `007_subtask_index.md`: row 76 lists depends-on `—`; the "Roots" list includes 029; and the Recommended Execution Order places it in Wave 2 as "026, 029 (independent)".) It can start immediately.

- **Runtime-change gate does NOT apply.** The cross-cutting constraint "the nine inventory subtasks (001, 002, 020, 036, 045, 053, 059, 060, 067) must precede any runtime-code change" gates **runtime-code** subtasks. 029 changes **no** runtime code, so it is **not** blocked by that gate and needs none of the nine to complete first.
- **Soft / informational (not blocking):**
  - **001 measure_complexity_and_dependencies** — provides the baseline census and the `ari.public` = 148-LOC inventory; useful context but 029 re-derives its own surface, so not a hard dependency.
  - **034 add_contract_snapshot_fixtures** — owns the snapshot-fixture location for public API / MCP / dashboard. 029 and 034 are both independent roots; **coordinate the snapshot path** (§9) so 029's baseline lives where 034 expects, but neither strictly blocks the other.
- **Downstream consumers (029 enables these; do them later, not here):**
  - **031 add_quality_report_generator** — aggregates 029's `--json`.
  - **049 add_contract_check_workflows** / **032 add_quality_script_ci_plan** — wire 029 into CI.
  - **026 add_import_boundary_checker_script** — complementary guard (caller-side import direction) that, together with 029, "make[s] every later High-risk subtask safe to attempt" (`007_subtask_index.md`).
  - **003 / 006 / 008 / 057** — the runtime subtasks whose `ari.public.*` compatibility promises 029's snapshot will verify once they run.

---

## 16. Risk Level

**Low.**

- **Changes runtime code:** **No.** The subtask adds one stdlib-only script under `scripts/` plus a committed JSON snapshot, and (conditionally) one line in `scripts/README.md`. It imports nothing into `ari` at runtime, edits no `ari-core/ari/**` / `ari-skill-*/**` / frontend / config / prompt / workflow file, and renames no directory.
- **Contract-relevant:** **Yes, but only as a guard.** 029 *codifies* the `ari.public.*` contract; it does not change it (matches `007_subtask_index.md`: "Codify or guard a contract without changing runtime code").
- **Residual risks (all minor):** (a) the dynamic-`__all__` resolution strategy could under- or over-report names — mitigated by cross-checking against real consumers (§8.8) and preferring import-based introspection (§7.2A); (b) landing the gate as a hard error prematurely could block unrelated PRs — mitigated by the staged advisory-first rollout (§7.3); (c) snapshot-path churn vs subtask 034 — mitigated by the REVIEW_REQUIRED coordination note (§9).

---

## 17. Notes for Implementer

- **Follow the house style verbatim.** Copy the shape of `scripts/docs/check_doc_sources.py` (docstring citing a design doc, `argparse`, `--json`, staged warning→error) but set `REPO_ROOT = Path(__file__).resolve().parents[1]` because this script lives at `scripts/`, **one** level under the repo root — *not* `parents[2]` (that index is correct only for `scripts/docs/*.py`). Confirm against `scripts/readme_sync.py:31`.
- **Prefer import-based introspection (§7.2A) in a subprocess.** It is the only faithful way to resolve the dynamic `__all__` in `container.py` / `cost_tracker.py` / `run_env.py`, and it mirrors exactly what a skill sees at `from ari.public.X import …`. Keep it hermetic: no network, no LLM, no writes outside the snapshot (design principle P2 determinism; `ari-skill-memory` sets the "no LLM calls" precedent for deterministic tooling).
- **Record the surface as-is; do not "improve" it.** The empty package-level `__all__` in `ari/public/__init__.py`, the missing `ari.__version__`, and the dynamic-`__all__` pattern are *facts to snapshot*, not bugs to fix in this subtask. Fixing any of them is a separate runtime-code subtask carrying a compatibility-adapter obligation.
- **Version stamping:** there is no `ari.__version__` (empty `ari-core/ari/__init__.py`). Read the version from `ari-core/pyproject.toml` (`version = "0.9.0"`) if you want a stamp — do not `import ari` just for a version.
- **`sonfigs/` does not exist.** The confusable trio is `ari-core/ari/config/` (code locator) vs `ari-core/ari/configs/` (packaged data) vs top-level `ari-core/config/` (rubric data). None of them is part of the `ari.public.*` surface; ignore them for this checker except as prose you may cite.
- **Coordinate the snapshot path with subtask 034** before committing the baseline; if 034 hasn't landed, default to `docs/refactoring/reports/public_api_snapshot.json` and leave a `TODO(034)` marker so the fixture can be relocated without a code change.
- **Do not touch the 5 workflows.** Wiring into CI is 049/032. Landing this script must be a no-op for `docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`, and `refactor-guards.yml`.
- **Cross-check, don't rewrite, `docs/reference/public_api.md`.** If you add a drift warning, keep it advisory; editing that doc is out of scope (docs updates are subtask 017).
- **Reserve "deprecated" for external contracts.** In any comments, do not call internal code "deprecated"; `ari.public.*` *is* an external contract, so it is the one place the word could legitimately apply — but 029 deprecates nothing.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **029** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
