# Subtask 044: Add Prompt Version Tracking To Run Metadata

- **Subtask ID:** 044
- **Phase:** Phase 7 — Prompt Management
- **Human title:** Add prompt version tracking to run metadata
- **Classification:** `ADAPT` (extends the existing checkpoint/run-metadata format and the existing `FilesystemPromptLoader.load_versioned()` with *additive* provenance fields; no existing field, filename, or symbol is removed or renamed)
- **Changes runtime code:** **Yes** (see Section 16). This is the first Phase-7 subtask in the fan-out that writes to disk at run time; 036/037/042/043 do not.
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`)

> **Planning-phase notice.** This document is a plan for a *future* coding session. Authoring it changes no runtime code, imports, prompts, configs, workflows, frontend, or directory names — the only file created here is this `.md` itself. All file paths, line numbers, and line counts below were verified by direct inspection on 2026-07-01; a fresh implementer should re-verify line numbers (they drift) but the file paths and symbol names are load-bearing.

---

## 1. Goal

Make every ARI run record **which prompt template version produced each LLM call**, so a run is reproducible and auditable at the prompt level. Concretely: capture, for each managed-prompt LLM call in `ari-core`, a provenance record containing `prompt_name`, `template_hash`, and (where a rendered string is available) `rendered_prompt_hash`, plus the `model`, `run_id`, `node_id`, and `phase` context that already exists, and persist those records into the run's checkpoint directory as an **additive** artifact.

The hashing primitive already exists: `FilesystemPromptLoader.load_versioned(key)` returns `(text, sha256(text)[:12])` (`ari-core/ari/prompts/_loader.py:45-49`). Today that method is **never called by any runtime call site** — only by one test (`ari-core/tests/test_prompt_extraction.py:102-107`). This subtask closes the gap between "we can compute a prompt hash" and "we record the prompt hash for every run."

Success = a completed run's checkpoint directory contains a deterministic, machine-stable record of the prompt versions used, and that record survives the existing checkpoint contracts (GUI reads, lineage walks, node-report classification) without breaking them.

## 2. Background

Prompts in ARI are **partially externalized** (see `docs/refactoring/011_prompt_management_plan.md` and subtask 036's inventory). The relevant mechanics:

- **Core loader.** `ari-core/ari/prompts/_loader.py` (49 lines) defines `PromptLoader` (a `Protocol`), `FilesystemPromptLoader`, and `package_prompts_root()`. `load(key)` reads `{base}/{key}.md`; `load_versioned(key)` returns `(text, sha256[:12])`. `__init__.py` (12 lines) re-exports all three; they are also re-exported via `ari-core/ari/protocols/__init__.py`.
- **Core call sites use `load()`, not `load_versioned()`.** All 11 externalized-prompt load sites throw away the hash: `agent/loop.py:51-52`, `evaluator/llm_evaluator.py:255` and `:413`, `orchestrator/bfts.py:475`/`:553`/`:743`, `orchestrator/lineage_decision.py:293`, `orchestrator/root_idea_selector.py:63`, `pipeline/context_builder.py:117`, `viz/api_tools.py:55` and `:127`. Each uses a lazy in-function `from ari.prompts import FilesystemPromptLoader` and then `.load(...)` (sometimes `.load(...).format(...)`).
- **Skills bypass the core loader entirely.** `ari-skill-replicate/src/generator.py:64,77,93` and `ari-skill-replicate/src/auditor.py:130` do `(PROMPTS_DIR / "x.md").read_text()`; `ari-skill-paper-re/src/server.py:66` does `p.read_text()`. No hashing, no versioning. (This is why skill provenance is a Non-Goal for 044 — see Sections 4 and 17.)
- **Run metadata / checkpoint format today.** A checkpoint dir is a flat directory whose ARI-metadata filenames are enumerated by `PathManager.META_FILES` (`ari-core/ari/paths.py:51-76`). The concrete run-provenance surfaces that already exist:
  - `tree.json` — written in `ari-core/ari/cli/bfts_loop.py:882-889` with `run_id`, `experiment_file`, `experiment_file_sha256`, `experiment_file_len`, `created_at`, `nodes`. This is the closest existing precedent for "hash-pinned run provenance" (it already records the *experiment file* hash for post-mortem).
  - `meta.json` — a lineage/launch record written by the GUI-launch path (`ari-core/ari/viz/api_orchestrator.py:244-253`, `ari-core/ari/viz/api_experiment.py:772`) and updated by `ari-core/ari/cli/lineage.py:139`; read by `ari-core/ari/lineage.py:111-123` and `ari-core/ari/viz/api_orchestrator.py:36-44`. **It is not universally written on pure-CLI runs**, so it is *not* a reliable home for per-call provenance.
  - `cost_trace.jsonl` + `cost_summary.json` — per-call JSONL trace + rollup written by `CostTracker` (`ari-core/ari/cost_tracker.py:77-176`). `CallRecord` (`cost_tracker.py:58-75`) is the exact precedent for a per-call, append-only, additive-field-with-`None`-default provenance record. This subtask should mirror that pattern rather than invent a new one.
- **Design source.** `docs/refactoring/011_prompt_management_plan.md` §8.1 already specifies the provenance field set (`prompt_name`, `prompt_version`, `template_hash`, `rendered_prompt_hash`, `prompt_registry_version`, `model_name`, `run_id`, `node_id`) and §8.2 the version-bump discipline. §8.1 explicitly notes "the new work is (a) computing `rendered_prompt_hash` after `.format(...)`, and (b) plumbing the record into the run/checkpoint provenance rather than discarding it." This subtask is the runtime realization of that policy for `ari-core`.

## 3. Scope

In scope:

1. **A provenance recorder in the core prompts package** — a small, deterministic, LLM-call-free helper (proposed home `ari-core/ari/prompts/_provenance.py`) that builds a provenance record from `(prompt_name, template_hash, rendered_text?, model, node_id, phase)` and appends it to a checkpoint-scoped artifact.
2. **Wiring the 11 core call sites** (Section 2) so each emits a provenance record after loading (and, where applicable, after `.format(...)`). Prefer switching each site from `.load(key)` to `.load_versioned(key)` so `template_hash` is captured at the source.
3. **A new additive checkpoint artifact** for the records (proposed `prompt_trace.jsonl`, per-call JSONL, mirroring `cost_trace.jsonl`) plus an optional run-level rollup (`prompt_versions.json`), both written to the checkpoint root.
4. **Registering the new filename(s)** in `PathManager.META_FILES` (`ari-core/ari/paths.py:51-76`) and in the node-report internal-file set (`ari-core/ari/orchestrator/node_report/builder.py:298-302`) so they are treated as ARI metadata (never copied into node work dirs, never surfaced as experiment artifacts).
5. **Tests** proving determinism (same template body → same 12-char hash across machines) and that the record is written and schema-additive.

Out of scope (belongs to other subtasks — see Sections 4, 15):

- The `PromptRegistry` object, manifest, and `render()`/`rendered_prompt_hash` machinery (subtask 038; 011 plan §7). 044 must be implementable on top of the *existing* `load_versioned()` alone, and should *consume* the registry's richer output if/when 038 lands, but must not block on it.
- Routing skill prompts through the loader / adopting `load_versioned` in skills (subtask 040; 011 plan §7.2).
- Snapshot tests / drift detection (subtasks 042/043; already partially covered by `report/scripts/check_prompt_snapshots.py`, verified present).
- Surfacing prompt provenance in the dashboard UI (frontend — not a Phase-7 subtask).

## 4. Non-Goals

- **No new LLM calls, no network, no nondeterminism.** Design principle P2 (determinism) governs this subtask: hashing must be pure `hashlib.sha256(...)[:12]` over UTF-8 bytes, identical across machines (011 plan §8.3). No git-SHA, no timestamps *inside* the hash, no environment-dependent values.
- **Not a prompt editor / override mechanism.** No per-user or per-run prompt mutation.
- **No skill-side provenance in this subtask.** `ari-skill-*` servers bypass the core loader (Section 2). Adding skill provenance requires the MCP-tool-result plumbing described in 011 plan §7.2 and is owned by 038/040. 044 must not import a skill into `ari-core` beyond the already-sanctioned `ari_skill_memory` edge, and must not change any MCP tool contract.
- **No breaking change to `meta.json`, `tree.json`, `cost_trace.jsonl`, or any existing checkpoint file schema.** Every new field/file is additive.
- **No `prompt_registry_version` / `prompt_version` semantic-version field required to be populated** if subtask 038 has not landed. Those fields may be written as `null`/absent until the registry manifest exists; `template_hash` is the mandatory, always-computable field.

## 5. Current Files / Directories to Inspect

All paths are repo-relative to `/home/t-kotama/workplace/ARI`. Line counts verified 2026-07-01.

**Prompt loader (hash source):**
- `ari-core/ari/prompts/_loader.py` (49 lines) — `load_versioned()` at `:45-49` returns `(text, sha256[:12])`. The single existing primitive this subtask activates.
- `ari-core/ari/prompts/__init__.py` (12 lines) — re-exports `FilesystemPromptLoader`, `PromptLoader`, `package_prompts_root`.
- `ari-core/ari/protocols/__init__.py` — also re-exports the loader (`:20`).
- `ari-core/ari/prompts/README.md` — in-package prompt docs (update to describe provenance, additive).

**Core prompt call sites to wire (11):**
- `ari-core/ari/agent/loop.py:51-52` (loop.py is 1630 lines — the ReAct system prompt).
- `ari-core/ari/evaluator/llm_evaluator.py:255` (`evaluator/extract_metrics`) and `:413` (`evaluator/peer_review`, `.format(...)`).
- `ari-core/ari/orchestrator/bfts.py:475`, `:553`, `:743` (`bfts_select`/`bfts_expand_select`/`bfts_expand`, all `.load(...).format(...)`; bfts.py is 845 lines).
- `ari-core/ari/orchestrator/lineage_decision.py:293` (`orchestrator/lineage_decision`).
- `ari-core/ari/orchestrator/root_idea_selector.py:63` (`orchestrator/root_idea_selector`).
- `ari-core/ari/pipeline/context_builder.py:117` (`pipeline/keyword_librarian`).
- `ari-core/ari/viz/api_tools.py:55` (`viz/wizard_chat_goal`) and `:127` (`viz/wizard_generate_config`).

**Run-metadata / checkpoint format surfaces (provenance home + contracts to preserve):**
- `ari-core/ari/cli/bfts_loop.py:870-910` (file is 911 lines) — the `tree.json`/`nodes_tree.json`/`results.json` build+write block; `tree.json` already carries `experiment_file_sha256` (the precedent).
- `ari-core/ari/checkpoint.py` (198 lines) — the single home for `tree.json`/`nodes_tree.json`/`results.json` JSON I/O; new run-level rollup helpers should live here for consistency.
- `ari-core/ari/cost_tracker.py` (448 lines) — `CallRecord` (`:58-75`), `CostTracker.record()` (`:119-147`), `cost_trace.jsonl` append pattern (`:145-146`). The template to copy for `prompt_trace.jsonl`.
- `ari-core/ari/public/cost_tracker.py` (10 lines) — public re-export; consult if the recorder needs a public surface (default: it should NOT — keep internal).
- `ari-core/ari/paths.py` (304 lines) — `PathManager.META_FILES` (`:51-76`), `checkpoint_dir()`, layout docstring (`:8-28`). New filename(s) registered here.
- `ari-core/ari/orchestrator/node_report/builder.py:298-302` — `_INTERNAL_JSON_NAMES` set; add the new artifact if it is JSON.
- `ari-core/ari/lineage.py:111-123` — `meta.json` reader (must keep tolerating extra/absent keys).
- `ari-core/ari/viz/api_orchestrator.py:36-44,244-253` and `ari-core/ari/viz/api_experiment.py:772` — `meta.json` scanners/writers (GUI path).
- `ari-core/ari/cli/lineage.py:100-139` — `meta.json` mutation for lineage.

**Tests / design docs:**
- `ari-core/tests/test_prompt_extraction.py:102-107` — existing `load_versioned` determinism test (extend or mirror).
- `docs/refactoring/011_prompt_management_plan.md` §7 (registry) and §8 (versioning policy, field table) — authoritative design.
- `report/scripts/check_prompt_snapshots.py` (verified present, 3157 bytes) — Gate 10 byte-verifier over `ari-core/ari/prompts/**/*.md`; ensures `template_hash` stability upstream.

**Skill loaders (inspect only — DO NOT wire in 044):**
- `ari-skill-replicate/src/generator.py:64,77,93`, `ari-skill-replicate/src/auditor.py:130`, `ari-skill-paper-re/src/server.py:66`.

## 6. Current Problems

1. **No prompt provenance on any run.** `grep -rn "prompt_version|template_hash|rendered_prompt_hash|prompt_provenance|prompt_trace"` over `ari-core` and `ari-skill-*` (excluding tests) returns **nothing** — confirmed 2026-07-01. A run cannot answer "which prompt text produced this result?"
2. **The hash primitive is dead code at runtime.** `load_versioned()` (`_loader.py:45-49`) is exercised only by `test_prompt_extraction.py:102-107`. All 11 real call sites use `.load()` and discard the hash.
3. **`meta.json` is not a reliable provenance home.** It is written only by the GUI-launch/lineage paths (`viz/api_orchestrator.py`, `viz/api_experiment.py`, `cli/lineage.py`), not on every CLI run, so per-call prompt provenance cannot live there without gaps.
4. **`tree.json` already proves the pattern but only for one hash.** It records `experiment_file_sha256` (`bfts_loop.py:884`) but nothing about the prompts that drove the search.
5. **Mechanism inconsistency (out of scope but must be acknowledged).** Skills produce no hash at all (`read_text()` bypass), so any run that leans on `ari-skill-replicate`/`ari-skill-paper-re` prompts will have *core-only* provenance until 040 lands. 044's record schema must be forward-compatible with later skill records (same field names, `source: "core" | "skill"`).

## 7. Proposed Design / Policy

### 7.1 Provenance record shape (additive, `CallRecord`-style)

A dataclass in `ari-core/ari/prompts/_provenance.py`, modeled on `CallRecord` (`cost_tracker.py:58-75`) — every non-essential field defaults to `None`/`""` so the schema can grow without breaking readers:

| Field | Meaning | Source in 044 | Notes |
| --- | --- | --- | --- |
| `timestamp` | UTC ISO-8601 of the call | recorder | mirrors `CallRecord.timestamp` |
| `prompt_name` | loader key, e.g. `orchestrator/bfts_select` | call site | required |
| `template_hash` | `sha256(raw_template)[:12]` | `load_versioned()` | required, deterministic |
| `rendered_prompt_hash` | `sha256(post-format string)[:12]` | recorder (compute inline) | present only where the site renders a final string |
| `prompt_version` | semantic version of the template | registry manifest (038) | `null` until 038 lands |
| `prompt_registry_version` | manifest version | registry manifest (038) | `null` until 038 lands |
| `model` | model the prompt was sent to | call site / `ari.public.llm` | best-effort; may be `""` |
| `node_id` | BFTS/pipeline node | orchestrator/pipeline context | reuse existing context vars |
| `phase` | pipeline phase | existing context | mirror `CallRecord.phase` |
| `source` | `"core"` (fixed in 044) | recorder | reserves `"skill"` for 040 |

`template_hash` is the mandatory, always-computable field; everything registry-derived is optional and may be absent until 038.

### 7.2 Persistence: a new additive checkpoint artifact

- **Per-call trace:** `prompt_trace.jsonl` at the checkpoint root — append-only JSONL, one record per line, written exactly like `cost_trace.jsonl` (`cost_tracker.py:145-146`: open in `"a"`, `json.dumps(asdict(rec)) + "\n"`, under a lock). Reuse the checkpoint dir resolved from `ARI_CHECKPOINT_DIR` / `PathManager` (`paths.py:238-274`), the same mechanism `CostTracker` uses.
- **Optional run-level rollup:** `prompt_versions.json` at the checkpoint root — `{prompt_name: {template_hash, prompt_version|null, call_count}}`. This is the human-auditable "what prompt versions did this run use" summary. Write via a helper added to `ari-core/ari/checkpoint.py` (keeps JSON layout ownership in one place, consistent with that module's charter).
- Do **not** shoehorn provenance into `meta.json` (unreliable, Section 6.3) or into `tree.json` (would change a GUI-contract file's schema for a per-call concern). Keeping it in dedicated files makes it purely additive.

### 7.3 Recorder API (deterministic, no LLM calls)

```
# ari-core/ari/prompts/_provenance.py  (proposed)
record_prompt_use(prompt_name, template_hash, *, rendered_text=None,
                  model="", node_id="", phase="", checkpoint_dir=None) -> None
```

- Resolves `checkpoint_dir` from `ARI_CHECKPOINT_DIR` when not passed (same env pin as `cost_tracker`/`paths`).
- Computes `rendered_prompt_hash = sha256(rendered_text)[:12]` only when `rendered_text` is given (mirror `load_versioned`'s truncation exactly for consistency).
- No-op safe: if no checkpoint dir is resolvable (e.g. unit test with no run context), it silently returns — matching `CostTracker.init_from_env()`'s tolerant behavior. This keeps the 11 call sites side-effect-free outside a run.
- Thread-safe append (a module-level `threading.Lock`, like `cost_tracker.py:84`) since BFTS runs agents in parallel.

### 7.4 Call-site pattern

At each of the 11 sites, change `loader.load(key)` → `text, template_hash = loader.load_versioned(key)`, keep the existing `.format(...)` where present, then call `record_prompt_use(key, template_hash, rendered_text=<final string when cheap to capture>, model=<known>, node_id=<known>, phase=<known>)`. The edit is byte-preserving for the *prompt text itself* (only the surrounding Python changes), so `report/scripts/check_prompt_snapshots.py` (Gate 10) stays green.

### 7.5 Compatibility with subtask 038

If 038's `PromptRegistry.render()` lands first, prefer routing through it (it returns `rendered_prompt_hash`, `prompt_version`, `prompt_registry_version` directly). 044's recorder accepts those fields as optional inputs, so no rework is needed either ordering. 044 is intentionally implementable with `load_versioned()` alone (its only hard dependency is 036).

## 8. Concrete Work Items

1. **Add `ari-core/ari/prompts/_provenance.py`** with the `PromptUseRecord` dataclass (Section 7.1) and `record_prompt_use(...)` (Section 7.3). Re-export it from `ari-core/ari/prompts/__init__.py` (additive). No new third-party deps (stdlib `hashlib`, `json`, `threading`, `dataclasses` only).
2. **Add a rollup writer to `ari-core/ari/checkpoint.py`** — e.g. `save_prompt_versions_json(checkpoint_dir, mapping)` mirroring `save_results_json` (`checkpoint.py:64-66`), preserving `json.dumps(..., indent=2, ensure_ascii=False)`.
3. **Wire the 11 core call sites** (Section 5): switch `.load()` → `.load_versioned()` and emit `record_prompt_use(...)`. Do this in small, per-file commits so Gate-10 snapshot verification and pytest can localize any regression.
4. **Register the new artifact filenames** in `PathManager.META_FILES` (`paths.py:51-76`) and — if `prompt_versions.json` is added — in `_INTERNAL_JSON_NAMES` (`node_report/builder.py:298-302`). Update the layout docstring in `paths.py:8-28` to list `prompt_trace.jsonl` / `prompt_versions.json`.
5. **Emit the run-level rollup** at run finalization — the natural hook is alongside the existing `tree.json`/`results.json` write in `ari-core/ari/cli/bfts_loop.py:882-910` (read back `prompt_trace.jsonl`, aggregate, call the new checkpoint writer). Keep it best-effort/guarded (a rollup failure must never fail the run — follow the `try/except` posture already used in `bfts_loop.py:892-897`).
6. **Tests** (Section 12): determinism of `template_hash`/`rendered_prompt_hash`; recorder writes valid JSONL; rollup schema; no-op when no checkpoint dir; META_FILES membership of the new names.
7. **Docs** — update `ari-core/ari/prompts/README.md` to describe the provenance artifact (additive, in-package doc; do not touch top-level `README.md`/`docs/` site content, which are governed by the docs-sync gates).

## 9. Files Expected to Change

When subtask 044 is *implemented* (a later coding session — not now):

**New files:**
- `ari-core/ari/prompts/_provenance.py` — recorder + record dataclass.
- `ari-core/tests/test_prompt_provenance.py` — new test module (or extend `ari-core/tests/test_prompt_extraction.py`).

**Modified files (all edits additive / behavior-preserving for existing fields):**
- `ari-core/ari/prompts/__init__.py` — re-export the recorder.
- `ari-core/ari/checkpoint.py` — add `save_prompt_versions_json` (+ optional loader).
- `ari-core/ari/paths.py` — add new filename(s) to `META_FILES`; update layout docstring.
- `ari-core/ari/orchestrator/node_report/builder.py` — add `prompt_versions.json` to `_INTERNAL_JSON_NAMES` (only if JSON rollup is adopted).
- `ari-core/ari/cli/bfts_loop.py` — emit the run-level rollup near the `tree.json` write.
- The 11 core call-site files: `ari-core/ari/agent/loop.py`, `ari-core/ari/evaluator/llm_evaluator.py`, `ari-core/ari/orchestrator/bfts.py`, `ari-core/ari/orchestrator/lineage_decision.py`, `ari-core/ari/orchestrator/root_idea_selector.py`, `ari-core/ari/pipeline/context_builder.py`, `ari-core/ari/viz/api_tools.py`.
- `ari-core/ari/prompts/README.md` — document the new artifact.

**New runtime artifacts written (not source files):** `{checkpoint_dir}/prompt_trace.jsonl`, optionally `{checkpoint_dir}/prompt_versions.json`. These live under `checkpoints/` which is `.gitignore`d (verified: `.gitignore` ignores `checkpoints/`, `workspace/`, `experiments/`), so there is **no git-tracking migration cost** — only on-disk/back-compat concerns.

Explicitly **not** changed: any `ari-skill-*` server, any MCP tool schema, any `.md` prompt template body, any `.github/workflows/*.yml`, any frontend file, any directory name, `requirements*.txt`, `ari-core/pyproject.toml`.

## 10. Files / APIs That Must Not Be Broken

- **CLI contract:** `ari = ari.cli:app`. `ari-core/ari/cli/bfts_loop.py` edits must not change subcommand behavior/exit codes; the rollup write is additive and guarded.
- **Public Python API:** `ari.public.*` (incl. `ari.public.cost_tracker`, `ari.public.paths`). The recorder stays internal (`ari.prompts._provenance`); do not add it to `ari.public.*` in 044.
- **MCP tool contracts:** the 14 `ari-skill-*` servers and `ari-core/ari/mcp/client.py`. Untouched by 044 (skill provenance is 040).
- **Dashboard API + schema:** `ari-core/ari/viz/routes.py` + `api_*.py`, consumed by `frontend/src/services/api.ts`. `meta.json`/`tree.json` schemas that the GUI reads must be unchanged; provenance goes to *new* files, so no endpoint or React contract shifts.
- **Checkpoint format:** existing files (`meta.json`, `tree.json`, `nodes_tree.json`, `results.json`, `cost_trace.jsonl`, `cost_summary.json`) keep identical filenames, key order, and `json.dumps(..., indent=2, ...)` formatting. `ari-core/ari/lineage.py` and `ari-core/ari/viz/api_orchestrator.py` `meta.json` readers must keep tolerating unknown/extra keys (they already do — `try/except json.JSONDecodeError`).
- **`PromptLoader` Protocol / `load_versioned` signature:** `_loader.py:28,45` must keep returning `(text, str)`; do not change the truncation length (12) — `test_prompt_extraction.py:105` and any downstream hash-pin depend on it.
- **README/docs usage & docs-sync gates:** do not edit top-level `README*.md` or `docs/` site content (governed by `readme-sync.yml`, `docs-sync.yml`, `docs-change-coupling.yml`). The in-package `ari-core/ari/prompts/README.md` update must stay consistent with `scripts/readme_sync.py` expectations.
- **Gate 10 snapshot verifier:** `report/scripts/check_prompt_snapshots.py` — do not alter any `.md` template body; 044 changes only Python around the loads.

## 11. Compatibility Constraints

- **Additive-only.** New fields default to `None`/`""`; new files are net-new. No reader anywhere is required to change to parse an old checkpoint.
- **Old checkpoints stay valid.** A pre-044 checkpoint simply lacks `prompt_trace.jsonl`/`prompt_versions.json`; every reader must treat their absence as "no provenance recorded," never as an error. `PathManager.META_FILES` membership only affects copy/surfacing logic, not existence assumptions.
- **Determinism (P1–P5, P2 governing).** Hashes are `sha256(...)[:12]` over UTF-8 bytes, machine-independent (011 plan §8.3). No LLM calls, no clock inside a hash, no git SHA.
- **No new dependency edge.** 044 stays within `ari-core`; the sanctioned `ari-core → ari_skill_memory` edge is not extended, and no `ari-skill-*` is imported.
- **Forward-compatible with 038 and 040.** Record field names match 011 plan §8.1 exactly so the registry (038) can populate `prompt_version`/`prompt_registry_version` and skills (040) can emit `source: "skill"` records into the same `prompt_trace.jsonl` schema without a migration.
- **`sonfigs/` does not exist** — the config trio is `ari-core/ari/config/` (code), `ari-core/ari/configs/` (packaged defaults), `ari-core/config/` (rubric/profile data). Irrelevant to this subtask beyond noting no config-file change is needed.

## 12. Tests to Run

From repo root (`/home/t-kotama/workplace/ARI`), before and after implementation:

- `python -m compileall .` — byte-compile sanity across the tree.
- `pytest -q` — full suite. Targeted subsets during development: `pytest -q ari-core/tests/test_prompt_extraction.py ari-core/tests/test_prompt_provenance.py`, plus any checkpoint/paths tests touched (`pytest -q -k "checkpoint or paths or cost"`).
- `ruff check .` — lint (ruff IS available; `radon`/`vulture`/`pnpm` are NOT — do not introduce them).
- `python report/scripts/check_prompt_snapshots.py` — confirm Gate-10 prompt-snapshot hashes are unchanged (proves no `.md` body drifted).

New tests to add (Section 8.6):
- `template_hash`/`rendered_prompt_hash` determinism (`== sha256(text)[:12]`), matching the existing assertion at `test_prompt_extraction.py:107`.
- Recorder appends a valid JSON line to `prompt_trace.jsonl` in a temp checkpoint dir; no-op (no exception) when no checkpoint dir is resolvable.
- Rollup `prompt_versions.json` schema + `json.dumps(indent=2, ensure_ascii=False)` formatting.
- `"prompt_trace.jsonl"` (and `"prompt_versions.json"` if adopted) are members of `PathManager.META_FILES`.

No frontend work in 044, so `npm test` / `npm run build` under `ari-core/ari/viz/frontend/` are **not required** (the dashboard surface is a separate, later subtask).

## 13. Acceptance Criteria

1. A completed local run writes `{checkpoint_dir}/prompt_trace.jsonl` containing at least one record per core prompt-driven LLM call, each with a non-empty `prompt_name` and a 12-char `template_hash`.
2. `template_hash` for a given unchanged `.md` template is **identical across two machines/checkouts** (determinism), verified by test and by matching `report/scripts/check_prompt_snapshots.py`.
3. All 11 core call sites emit a provenance record (verified by grep for `record_prompt_use(` count == 11+ and by an integration test exercising at least the agent + bfts + evaluator paths).
4. Existing `meta.json`, `tree.json`, `cost_trace.jsonl` schemas are byte-for-byte unchanged for existing fields; a pre-044 checkpoint still loads without error in `ari-core/ari/lineage.py` and `ari-core/ari/viz/api_orchestrator.py`.
5. `python -m compileall .`, `pytest -q`, and `ruff check .` all pass; `check_prompt_snapshots.py` reports no drift.
6. No `ari-skill-*`, MCP schema, dashboard endpoint, `.github/workflows`, frontend file, or directory name is modified.
7. The recorder performs zero LLM/network calls (assert by code inspection + a test that runs it fully offline).

## 14. Rollback Plan

- Runtime artifacts (`prompt_trace.jsonl`, `prompt_versions.json`) are under `.gitignore`d `checkpoints/`, so nothing is committed to git for old runs; deleting the files is a safe, lossless local cleanup.
- The code change is confined to additive Python. Rollback = `git revert` of the 044 commits: (a) remove `_provenance.py` and its re-export, (b) restore the 11 call sites to `.load()` (mechanical — drop the second tuple element and the `record_prompt_use(...)` line), (c) remove the new `META_FILES`/`_INTERNAL_JSON_NAMES` entries and the `checkpoint.py` rollup writer. Because every edit is additive, revert cannot corrupt existing checkpoints.
- Feature-flag option (recommended for staged rollout): gate the recorder on an env var (e.g. default-on `ARI_PROMPT_PROVENANCE`) resolved the same way `cost_tracker.init_from_env()` resolves its config, so provenance can be disabled without a revert if it ever perturbs a run.

## 15. Dependencies

Per the canonical dependency graph and `docs/refactoring/007_subtask_index.md:91`:

- **Hard prerequisite: 036 `inventory_hardcoded_prompts`** (`036 -> 044`). 044 must know the complete, verified set of managed vs. inline vs. vendored prompts before wiring provenance, so it does not attach provenance to a prompt that 036 classifies KEEP_INLINE/vendored. This is 044's only hard, graph-level predecessor.
- **Global gate:** any runtime code change is gated by the nine inventory subtasks (001, 002, 020, 036, 045, 053, 059, 060, 067). Since 044 **changes runtime code** (Section 16), those inventories (esp. 001 architecture, 003/026 import-boundary context, 036 prompt inventory) should be complete first.
- **Recommended-but-not-blocking soft ordering** (044 is designed to not require these):
  - **038 `introduce_prompt_registry_and_loader`** — if landed first, 044 consumes `render()`/`rendered_prompt_hash`/`prompt_version` directly instead of computing `rendered_prompt_hash` inline. Either order works.
  - **042 `add_prompt_snapshot_tests`** — provides drift detection that keeps `template_hash` meaningful; complementary.
- **Enables:** nothing downstream depends on 044 in the graph (it is a leaf of the `036 -> {037…044}` fan-out).

## 16. Risk Level

- **Changes runtime code: YES.** Unlike the sibling Phase-7 planning/test subtasks (036/037/042/043), 044 modifies `ari-core` runtime: a new recorder module, 11 call-site edits, a new checkpoint artifact, and `META_FILES`/`node_report` registrations.
- **Overall risk: MEDIUM** (matches the index's "Medium" for 044). Rationale:
  - *Blast radius* touches hot paths (`agent/loop.py`, `orchestrator/bfts.py`, `pipeline/context_builder.py`), but each edit is small and additive.
  - *Concurrency*: BFTS runs agents in parallel, so the recorder's append must be lock-guarded (mitigated by copying the proven `CostTracker` lock pattern).
  - *Contract exposure*: LOW — provenance lives in new files; no existing schema/endpoint changes.
  - *Determinism*: LOW risk if hashing stays pure (P2), but a careless inclusion of a timestamp/absolute path inside a hash would silently break reproducibility — call this out in review.

## 17. Notes for Implementer

- **Start from `CostTracker`, not from scratch.** `ari-core/ari/cost_tracker.py:58-147` is a working, thread-safe, additive-field, checkpoint-scoped JSONL recorder. `prompt_trace.jsonl` should be its structural twin; reusing the shape also means the two traces line up on `node_id`/`phase`/`model`/`timestamp` for cross-referencing.
- **Prefer `.load_versioned()` over recomputing.** The hash already exists in `_loader.py:45-49`; do not add a second hashing path — that would risk divergent truncation lengths.
- **`rendered_prompt_hash` is best-effort.** Some sites (e.g. `bfts.py:475/553/743`) `.format(...)` inline; capture the rendered string there. Sites that only `.load()` (e.g. `agent/loop.py`) may leave `rendered_prompt_hash=None` — that is acceptable per Section 7.1.
- **Do not touch `.md` bodies.** Gate 10 (`report/scripts/check_prompt_snapshots.py`) byte-verifies templates; any body change fails CI. 044 changes only surrounding Python.
- **Keep it offline and deterministic.** No LLM calls, no network, no wall-clock inside a hash (timestamps go in the record's `timestamp` field, never into `template_hash`/`rendered_prompt_hash`). This is the P2 constraint the 011 plan §8.3 pins.
- **`meta.json` is a trap.** It is tempting but is not written on every run (Section 6.3). Use the dedicated `prompt_trace.jsonl` instead.
- **Skills are explicitly deferred.** If you find yourself editing `ari-skill-replicate`/`ari-skill-paper-re`, stop — that is subtask 040 and requires MCP-tool-result plumbing (011 plan §7.2), not a core edit.
- **Register new filenames everywhere they matter.** Missing them from `PathManager.META_FILES` (`paths.py:51-76`) would cause the provenance files to be physically copied into every node work dir (`experiments/<run>/<node>/`) and surfaced as "artifacts" in the GUI — a correctness bug, not just cosmetics.
- **`sonfigs/` does not exist**; no config directory is involved. The only config-adjacent fact worth remembering is that packaged defaults live in `ari-core/ari/configs/` and rubric data in `ari-core/config/` — neither is touched here.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **044** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
