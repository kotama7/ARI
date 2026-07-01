# Subtask 040: Extract Evaluator and LLM-Judge Prompts

> Phase 7: Prompt Management · Group root: **036 inventory_hardcoded_prompts**
> Planning date: 2026-07-01 · ari-core version 0.9.0 · branch `main`
> This is a PLANNING document. No runtime code is modified by writing it.

## 1. Goal

Externalize the **LLM-as-judge / evaluator system prompts** that are still
hard-coded as Python string constants, moving them into `.md` template files
loaded by the existing prompt-loader mechanism, **byte-for-byte identically**,
so prompt text becomes editable and hash-pinnable without touching Python.

Concretely:

- **Core evaluator** (`ari-core/ari/evaluator/llm_evaluator.py`): the two judge
  prompts are **already externalized** (`evaluator/extract_metrics.md`,
  `evaluator/peer_review.md`, loaded via `FilesystemPromptLoader`). For core the
  goal is *verification + closing the last inline gap* (confirm no additional
  static judge prose remains inline), not re-extraction.
- **Skill evaluator** (`ari-skill-evaluator/src/server.py`, 983 L): move the
  **four** inline judge system-prompt constants into skill-local `.md` files
  under a new `ari-skill-evaluator/src/prompts/` directory, loaded through a
  small skill loader that mirrors the core `load_versioned` contract.

The extracted text must be identical to the current constant so evaluation
behavior does not shift; snapshot/hash tests (subtask 042) lock this in.

## 2. Background

ARI already ran a partial prompt-externalization pass (internal phase
"PROMPTS_AND_CONFIG.md" / Phase PC). The core loader lives in
`ari-core/ari/prompts/_loader.py` (~49 L): it defines a `PromptLoader`
`Protocol` and a concrete `FilesystemPromptLoader` whose `load(key)` reads
`{base}/{key}.md` and `load_versioned(key)` returns `(text, sha256[:12])` for
reproducibility pinning. Templates are `.md` filled with Python `str.format(...)`
(single-brace `{name}` placeholders) — confirmed not Jinja/`.j2`.

The **core** evaluator judge prompts were part of that pass:

- `LLMEvaluator.BASE_SYSTEM` is loaded from `evaluator/extract_metrics.md` at
  `llm_evaluator.py:254-255` (a trailing `\n` is trimmed to stay byte-identical
  to the legacy constant).
- `LLMEvaluator._build_system_prompt()` loads `evaluator/peer_review.md` at
  `llm_evaluator.py:412-413` and injects the computed dynamic axes via
  `.format(axes_block=axes_to_prompt_section(...))`.
- Both are already covered by hash rows in
  `ari-core/tests/test_prompt_extraction.py`.

The **skill** evaluator, by contrast, still carries its judge prompts inline as
module-level constants and calls `litellm.acompletion` directly (four call
sites). It does **not** use any prompt loader today — no `src/prompts/`
directory exists in that package. This subtask brings the skill up to the same
externalized, hash-pinned state as core, following the ownership/location policy
recorded in `docs/refactoring/011_prompt_management_plan.md` §5.x–§7.

Precedent for skill-local prompt files already exists in two other skills:
`ari-skill-replicate/src/prompts/*.md` (skeleton/subtree/adversarial_reviewer/
rubric_audit) and `ari-skill-paper-re/src/prompts/replicator.md`, both loaded via
`Path(__file__).parent / "prompts" / "x.md").read_text()`. This subtask reuses
that on-disk convention but standardizes the *loader* on the `load_versioned`
`(text, sha256[:12])` contract so hashes are produced uniformly across packages.

## 3. Scope

In scope:

1. **Core (verification-only):** confirm the two evaluator templates remain the
   sole source of judge prose in `llm_evaluator.py`; classify the residual
   inline `weights_line` prose (`:421-423`) as KEEP_INLINE (dynamic, not a
   static template). No re-extraction unless a NEW static block is found.
2. **Skill (extraction):** move the four inline judge system prompts in
   `ari-skill-evaluator/src/server.py` into `ari-skill-evaluator/src/prompts/`:
   - `_METRIC_EXTRACT_SYS` (`:191`, used at `:214` in `_llm_extract_metric_spec`)
   - `_CLAIMS_EXTRACT_SYS` (`:266`, used at `:410` in `_llm_extract_claims`)
   - `_CONTRACT_FLAGS_SYS` (`:464`, used at `:489` in `_llm_extract_contract_flags`)
   - `_SEMANTIC_SYSTEM_PROMPT` (`:790`, used at `:903` in
     `_tool_evidence_grounded_semantic_review`)
3. Add a minimal skill-local loader helper implementing the `load_versioned`
   contract (`(text, sha256[:12])`), OR reuse `Path.read_text()` per the
   replicate/paper-re precedent — decision recorded in §7.
4. Add snapshot/hash coverage for the extracted skill templates (coordinate with
   subtask 042; if 042 has not landed, add a local hash test in the skill's
   `tests/`).

Out of scope (belongs to other subtasks — see §4).

## 4. Non-Goals

- **Do NOT re-word, merge, or "improve" any prompt text.** Extraction is
  byte-identical only. The observed conceptual overlaps —
  `_METRIC_EXTRACT_SYS` vs core `evaluator/extract_metrics.md`, and the venue
  peer-reviewer prompts in `ari-skill-paper/src/review_engine.py:79,443` vs core
  `evaluator/peer_review.md` — are **MERGE_DUPLICATE / REVIEW_REQUIRED** and are
  explicitly deferred; do not consolidate them here.
- **Do NOT touch other skills' prompts** (paper, plot, vlm, transform, web,
  idea, paper-re). Those are subtask 041 or KEEP_INLINE.
- **Do NOT migrate to Jinja2 / `.md.j2`.** Keep `.md` + `str.format` (plan
  §6.2). None of the four skill prompts require loops/conditionals.
- **Do NOT introduce a core→skill import** to share the loader, and do NOT make
  the skill import an ari-core registry object (would invert the dependency;
  plan §7.2).
- **Do NOT implement the run-metadata prompt-version fields** — that is subtask
  044. This subtask may *emit* a hash via `load_versioned` but does not wire it
  into checkpoint/run provenance.
- **Do NOT build the `PromptRegistry`** (subtask 038) or the `check_prompts.py`
  checker (subtask 043).
- **Do NOT change** the litellm-direct call pattern, retry behavior, timeouts,
  or model routing in either file. Prompt text only.

## 5. Current Files / Directories to Inspect

Core (already externalized — verify, do not re-extract):

- `ari-core/ari/evaluator/llm_evaluator.py` (723 L) — call sites `:254-255`
  (`evaluator/extract_metrics`), `:401-420` (`evaluator/peer_review` +
  `.format(axes_block=...)`), residual dynamic `weights_line` at `:421-423`,
  direct `litellm.acompletion(**kwargs)` at `:585`.
- `ari-core/ari/prompts/evaluator/extract_metrics.md` (16 L) — 5-axis extractor.
- `ari-core/ari/prompts/evaluator/peer_review.md` (11 L) — `{axes_block}`
  placeholder + `claim_implementation_alignment` guidance.
- `ari-core/ari/prompts/evaluator/README.md` — index (add rows if new files).
- `ari-core/ari/prompts/_loader.py` (~49 L) — `FilesystemPromptLoader`,
  `PromptLoader` Protocol, `package_prompts_root()`.
- `ari-core/ari/prompts/__init__.py`, `ari-core/ari/prompts/README.md` — exports
  and human index.
- `ari-core/tests/test_prompt_extraction.py` — sha256 snapshot list (add rows
  only if a new core file is introduced; core is expected to be unchanged).

Skill (extraction target):

- `ari-skill-evaluator/src/server.py` (983 L) — inline constants at `:191`,
  `:266`, `:464`, `:790`; call sites at `:214`, `:410`, `:489`, `:903`; direct
  `litellm.acompletion` at those four sites.
- `ari-skill-evaluator/src/__init__.py` (empty), `ari-skill-evaluator/src/`
  (flat layout: `server.py` + `__init__.py`).
- `ari-skill-evaluator/src/prompts/` — **does not exist** (to be created).
- `ari-skill-evaluator/pyproject.toml` — `[tool.setuptools.packages.find]
  where = ["src"]`; no `package-data` / `MANIFEST.in` today (data-file shipping
  must be confirmed — see §11).
- `ari-skill-evaluator/tests/` — `test_server.py`, `test_s2p_tools.py`,
  `test_metric_spec_claims.py`, `conftest.py`, `README.md`.

Precedent to copy from:

- `ari-skill-replicate/src/prompts/` (`skeleton.md`, `subtree.md`,
  `adversarial_reviewer.md`, `rubric_audit.md`) — loaded via
  `(PROMPTS_DIR / "x.md").read_text()` in `generator.py:64,77,93` /
  `auditor.py:130`.
- `ari-skill-paper-re/src/prompts/replicator.md` — loaded via `server.py:66`.

## 6. Current Problems

1. **Judge prompts are hard-coded in the largest evaluator-skill file.** Four
   multi-line system prompts (`_METRIC_EXTRACT_SYS`, `_CLAIMS_EXTRACT_SYS`,
   `_CONTRACT_FLAGS_SYS`, `_SEMANTIC_SYSTEM_PROMPT`) live as string constants in
   `ari-skill-evaluator/src/server.py`. Editing evaluation behavior requires a
   Python edit, and there is no hash/version to pin a run's judge rubric.
2. **Routed inventory undercount (now corrected).** The area finding cited only
   two skill judge prompts (`:191`, `:790`). Direct inspection on 2026-07-01
   found **four** (adds `_CLAIMS_EXTRACT_SYS:266`, `_CONTRACT_FLAGS_SYS:464`).
   Subtask 036's exhaustive inventory must reflect all four; this subtask
   extracts all four.
3. **Mechanism inconsistency across packages.** Core evaluator prompts use
   `FilesystemPromptLoader.load_versioned` (hashable). The skill uses neither a
   loader nor a hash — inline constants only. Even the two other skills that DO
   externalize (`replicate`, `paper-re`) bypass the versioned contract with
   ad-hoc `read_text()`. The skill evaluator should adopt the `load_versioned`
   `(text, sha256[:12])` shape so hashes are uniform.
4. **Conceptual duplication (deferred, not fixed here).** `_METRIC_EXTRACT_SYS`
   overlaps core `evaluator/extract_metrics.md` in intent (metric extraction)
   but differs in scope (optimize-target selection vs artifact extraction) and
   is not byte-identical — MERGE is REVIEW_REQUIRED, left to a later subtask.
5. **Trailing-newline sensitivity.** The core extraction had to trim a single
   trailing `\n` (`llm_evaluator.py:256-261`, `:416-420`) to keep bytes stable.
   The skill constants are parenthesized string concatenations with **no**
   trailing newline; the `.md` files must be written with no trailing newline
   (or trimmed on load) to keep hashes identical.

## 7. Proposed Design / Policy

### 7.1 Location (extend, don't relocate)

Per plan §6.1: skill prompts stay skill-local. Create
`ari-skill-evaluator/src/prompts/` and add one `.md` per extracted constant:

| Constant (current) | New template key | Consuming function |
|---|---|---|
| `_METRIC_EXTRACT_SYS` (`:191`) | `metric_extract_sys.md` | `_llm_extract_metric_spec` (`:214`) |
| `_CLAIMS_EXTRACT_SYS` (`:266`) | `claims_extract_sys.md` | `_llm_extract_claims` (`:410`) |
| `_CONTRACT_FLAGS_SYS` (`:464`) | `contract_flags_sys.md` | `_llm_extract_contract_flags` (`:489`) |
| `_SEMANTIC_SYSTEM_PROMPT` (`:790`) | `semantic_review_sys.md` | `_tool_evidence_grounded_semantic_review` (`:903`) |

(File names are a proposal; match whatever naming subtask 037/036 standardizes.
Keep them stable once chosen — snapshot tests key on the path.)

### 7.2 Loader mechanism — REVIEW_REQUIRED decision owned by this subtask

Plan §7.2 explicitly assigns to subtask 040 the choice between:

- **(A) copied 15-line helper per skill** implementing `load_versioned(key) ->
  (text, sha256[:12])` over `Path(__file__).parent / "prompts"`, matching the
  core `FilesystemPromptLoader` contract; or
- **(B) plain `Path.read_text()`** matching the existing replicate/paper-re
  precedent (no hash).

**Recommendation: (A).** It is ~15 lines, adds no dependency, keeps the skill
self-contained (no core import), and yields the `sha256[:12]` needed for
snapshot tests (042) and future run-metadata provenance (044). Place the helper
in a new small module (e.g. `ari-skill-evaluator/src/_prompts.py`) or inline in
`server.py`. Do **not** import `ari.prompts` from the skill.

### 7.3 Extraction procedure (per constant, byte-identical)

1. Reconstruct the exact runtime string the Python constant produces
   (concatenated parenthesized literals → one string). Write it verbatim to the
   `.md` file. Ensure the file has **no trailing newline** (the constants have
   none), OR trim one trailing `\n` on load exactly as core does.
2. Replace the constant with a lazy load at first use, e.g.
   `content=_load_prompt("semantic_review_sys")`, preserving the existing
   `{"role": "system", "content": ...}` shape at the call site. Keep any
   f-string/`.format` user-message construction unchanged.
3. Confirm the reconstructed `.md` hashes to the same value the test will pin
   (capture the hash from the current constant *before* editing).

### 7.4 Render engine

Keep `str.format` semantics. Of the four, `_SEMANTIC_SYSTEM_PROMPT`,
`_METRIC_EXTRACT_SYS`, `_CLAIMS_EXTRACT_SYS`, and `_CONTRACT_FLAGS_SYS` are
**static** system prompts (no `{}` substitution today; JSON-schema braces in the
text are literal). If any literal `{`/`}` (JSON braces) exists in the text and
you route through `str.format`, they MUST be escaped as `{{`/`}}` — OR simpler:
use `load()` (raw read) for these static prompts and reserve `.format()` only
for templates with real placeholders. Prefer raw `load()` here to avoid
brace-escaping churn. (Note: all four contain literal JSON `{...}` schema
examples, so raw load is the safe path.)

### 7.5 Classification summary (master vocabulary)

- `_SEMANTIC_SYSTEM_PROMPT`, `_CLAIMS_EXTRACT_SYS`, `_CONTRACT_FLAGS_SYS`:
  **EXTRACT_TEMPLATE** (substantial, static, ARI-authored).
- `_METRIC_EXTRACT_SYS`: **EXTRACT_TEMPLATE** now; **REVIEW_REQUIRED** later for
  possible MERGE with core `evaluator/extract_metrics.md`.
- Core `extract_metrics.md` / `peer_review.md`: **KEEP** (already extracted).
- `llm_evaluator.py:421-423` `weights_line`: **KEEP_INLINE** (dynamic).

## 8. Concrete Work Items

1. **Core verification (no code change expected).** Re-grep
   `ari-core/ari/evaluator/llm_evaluator.py` for any static `"You are ..."` /
   triple-quoted judge prose beyond the two loaded templates. Inspection on
   2026-07-01 found none besides the dynamic `weights_line`. Record this in the
   PR description; make no edit unless a new static block surfaces.
2. **Create** `ari-skill-evaluator/src/prompts/` with four `.md` files, each the
   byte-exact runtime string of the corresponding constant (no trailing newline).
3. **Add loader** (`_prompts.py` helper or inline) implementing
   `load(key) -> str` and `load_versioned(key) -> (text, sha256[:12])` over the
   new directory, resolving via `Path(__file__).parent`.
4. **Rewrite call sites** at `server.py:214, :410, :489, :903` to read from the
   loader instead of the module constants; delete the four constants at `:191,
   :266, :464, :790`. Preserve message-role structure and all surrounding
   `litellm.acompletion(...)` kwargs unchanged.
5. **Update packaging** so `src/prompts/*.md` ships with the wheel: add
   `package-data` (or `[tool.setuptools.package-data]`) / `MANIFEST.in` to
   `ari-skill-evaluator/pyproject.toml` — mirror how `ari-skill-replicate` ships
   its `src/prompts/`. Editable installs (setup.sh) already resolve files by
   path, but wheel builds need explicit inclusion. (Confirm replicate's exact
   mechanism and copy it.)
6. **Snapshot tests.** Add a hash test for the four new skill templates. If
   subtask 042 has landed a shared harness, register the four keys there;
   otherwise add `ari-skill-evaluator/tests/test_prompt_extraction.py` mirroring
   `ari-core/tests/test_prompt_extraction.py` (sha256 of on-disk file == pinned
   value captured from the pre-extraction constant).
7. **Update docs/index.** Add the four files to
   `ari-skill-evaluator/README.md` (or a new `src/prompts/README.md` mirroring
   the core `ari/prompts/README.md` convention) so the readme-sync gate passes.
8. **Run the full check suite** (§12) and confirm evaluator/skill tests are
   green with byte-identical prompt strings.

## 9. Files Expected to Change

Created:

- `ari-skill-evaluator/src/prompts/metric_extract_sys.md`
- `ari-skill-evaluator/src/prompts/claims_extract_sys.md`
- `ari-skill-evaluator/src/prompts/contract_flags_sys.md`
- `ari-skill-evaluator/src/prompts/semantic_review_sys.md`
- `ari-skill-evaluator/src/prompts/README.md` (index; optional but recommended
  for readme-sync parity)
- `ari-skill-evaluator/src/_prompts.py` (small loader helper) — OR inline the
  helper in `server.py` (implementer's choice per §7.2).
- `ari-skill-evaluator/tests/test_prompt_extraction.py` (only if subtask 042's
  shared harness is not yet available).

Modified:

- `ari-skill-evaluator/src/server.py` — remove the four constants (`:191, :266,
  :464, :790`); repoint call sites (`:214, :410, :489, :903`) to the loader.
- `ari-skill-evaluator/pyproject.toml` — add package-data for `src/prompts/*.md`.
- `ari-skill-evaluator/README.md` — list the new prompt files (readme-sync).

Verified-only (expected NO change):

- `ari-core/ari/evaluator/llm_evaluator.py` — inspect only.
- `ari-core/ari/prompts/evaluator/*.md`, `ari-core/tests/test_prompt_extraction.py`
  — unchanged unless a new core template is introduced (not expected).

## 10. Files / APIs That Must Not Be Broken

- **MCP tool contract (ari-skill-evaluator).** `list_tools` exposes
  `make_metric_spec`, `claim_evidence_hard_gate`,
  `evidence_grounded_semantic_review`. Tool names, input schemas, and result
  JSON shapes must be unchanged. Any prompt-hash surfacing (deferred to 044)
  would be an **additive** field only.
- **ari-skill-* → ari-core stable interface.** No new import edge in either
  direction. The skill must not import `ari.prompts`; ari-core must not import
  the skill's new loader.
- **Core public surface.** `ari.evaluator.LLMEvaluator.BASE_SYSTEM` and
  `_build_system_prompt()` behavior/bytes unchanged (core is verify-only).
  `ari.public.*` untouched.
- **Evaluation outputs.** Per-axis scores, `_scientific_score` composite, the
  hard-gate JSON (`correctness_required`, `ceiling_must_be_measured`,
  claims/evidence), and semantic-review JSON (`scores`, `warnings`,
  `suggested_revisions`) must be identical for identical inputs — guaranteed by
  byte-identical prompts + unchanged litellm kwargs.
- **Checkpoint / config formats.** Untouched.
- **Scripts called by `.github/workflows`.** `scripts/readme_sync.py`,
  `scripts/docs/check_readme_parity.py`, and `scripts/run_all_tests.sh` must
  still pass; the new `src/prompts/` dir must be reflected wherever those gates
  enumerate package contents.

## 11. Compatibility Constraints

- **Byte-for-byte prompt equality.** Capture each constant's runtime string and
  its sha256 *before* editing; the on-disk `.md` must reproduce it exactly
  (mind the no-trailing-newline detail, §6.5 / §7.3).
- **Literal JSON braces.** All four prompts embed literal `{...}` JSON schema
  examples. Prefer raw `load()` (no `.format`) so braces need no escaping; if
  `.format` is used, double every literal brace.
- **Data-file shipping (REVIEW_REQUIRED).** `ari-skill-evaluator/pyproject.toml`
  currently declares no `package-data`. Confirm whether MCP servers run from an
  editable source tree (setup.sh) — in which case `Path(__file__).parent`
  resolution already works — versus wheel installs that need explicit
  `package-data`. Copy whatever `ari-skill-replicate` does for its `src/prompts/`
  so both are consistent.
- **No dependency reversal.** The loader helper is copied/local, not shared via
  a core import (plan §7.2). This preserves MCP-package self-containment.
- **Determinism (P2).** No new LLM calls, no network, no nondeterminism.
  `package-relative` file reads only.

## 12. Tests to Run

From repo root `/home/t-kotama/workplace/ARI`:

- `python -m compileall .` — byte-compile all Python (catches syntax errors in
  the edited `server.py` and any new `_prompts.py`).
- `pytest -q` — full suite. Targeted: `ari-skill-evaluator/tests/` (esp.
  `test_server.py`, `test_s2p_tools.py`, `test_metric_spec_claims.py`) and
  `ari-core/tests/test_prompt_extraction.py`.
- `ruff check .` — lint (ruff is available; radon is not).
- New/updated `test_prompt_extraction.py` hash rows for the four skill templates
  must pass (byte-identity gate).
- `scripts/run_all_tests.sh` — repo aggregate runner, if used by CI locally.
- Readme-sync gate: `python scripts/readme_sync.py` (and/or
  `scripts/docs/check_readme_parity.py`) so the new `src/prompts/` listing is
  accepted by `readme-sync.yml`.

No frontend involved — `npm test` / `npm run build` are **not** required for
this subtask.

## 13. Acceptance Criteria

1. The four inline constants (`_METRIC_EXTRACT_SYS`, `_CLAIMS_EXTRACT_SYS`,
   `_CONTRACT_FLAGS_SYS`, `_SEMANTIC_SYSTEM_PROMPT`) no longer exist in
   `ari-skill-evaluator/src/server.py`; the four call sites load from
   `src/prompts/`.
2. Each new `.md` file is byte-identical to the pre-extraction runtime string
   (sha256 match), enforced by a passing snapshot test.
3. `pytest -q`, `python -m compileall .`, and `ruff check .` all pass.
4. `evidence_grounded_semantic_review`, `make_metric_spec`, and
   `claim_evidence_hard_gate` produce identical outputs to pre-change for
   identical inputs (verified by existing skill tests).
5. `src/prompts/*.md` ships with the package (editable + wheel), matching the
   `ari-skill-replicate` mechanism.
6. Core `llm_evaluator.py` is unchanged (verify-only), and its existing
   `test_prompt_extraction.py` rows still pass.
7. No new import edge between ari-core and ari-skill-evaluator; MCP tool schemas
   unchanged.
8. Readme-sync / readme-parity gates pass with the new prompt files listed.

## 14. Rollback Plan

- The change is isolated to `ari-skill-evaluator` plus a verify-only pass on
  core. Revert by restoring the four constants in `server.py`, reverting the
  four call sites, and deleting `src/prompts/*.md`, `_prompts.py`, the new test,
  the pyproject `package-data` block, and README rows — a clean `git revert` of
  the single commit.
- Because prompts are byte-identical, rollback carries **no behavioral risk**:
  pre- and post-change evaluation outputs are identical by construction.
- If a wheel-packaging issue is discovered post-merge (files not shipped), the
  fast mitigation is to keep the editable-install path (already working via
  `Path(__file__).parent`) and treat wheel `package-data` as a follow-up, since
  MCP servers run from source in the standard setup.sh flow.

## 15. Dependencies

Per the DEPENDENCY GRAPH, group **036 → 040**:

- **Hard prerequisite: 036 inventory_hardcoded_prompts.** 036 is one of the nine
  inventory subtasks that MUST precede any runtime code change. 040 changes
  runtime code, so 036's exhaustive hardcoded-prompt census (which must include
  all four skill-evaluator constants — see §6.2) must be complete first.
- **Soft coordination (same Phase-7 group, all fan out from 036):**
  - **037 define_prompt_template_policy** — supplies naming/location/`.md`-vs-`.j2`
    conventions this subtask should follow. If 037 has not landed, follow the
    conventions already recorded in `docs/refactoring/011_prompt_management_plan.md`
    §6–§7.
  - **038 introduce_prompt_registry_and_loader** — if the registry lands first,
    prefer registering the four keys there; the graph does not force 038 before
    040, so 040 may ship with the local `load_versioned` helper independently.
  - **042 add_prompt_snapshot_tests** — owns the shared snapshot harness; 040
    contributes four hash rows. If 042 is not yet available, 040 adds a local
    hash test (§8.6).
  - **044 add_prompt_version_tracking_to_run_metadata** — consumes the
    `sha256[:12]` this subtask makes available; 040 does not implement the
    provenance wiring (additive MCP field decision is flagged, not built).
- No downstream subtask depends on 040 in the graph.

## 16. Risk Level

**Changes runtime code: YES** (rewrites `ari-skill-evaluator/src/server.py` call
sites and packaging; core is verify-only).

**Risk: Medium.** (Consistent with the subtask index: 040 = Medium, changes
runtime = Yes.) The behavioral risk is low because extraction is byte-identical
and guarded by hash tests, but the change touches the live evaluator/judge path
(hard-gate + semantic review consumed by paper-refine), and there is real
packaging risk (data-file shipping) plus the trailing-newline/JSON-brace
foot-guns. Mitigated by: pre-capture hashes, raw `load()` (no brace escaping),
copying the proven `ari-skill-replicate` packaging, and full-suite tests.

## 17. Notes for Implementer

- **Count check:** there are **four** skill-evaluator judge prompts, not two.
  The area finding cited only `:191` and `:790`; direct grep on 2026-07-01
  confirmed `_CLAIMS_EXTRACT_SYS` (`:266`) and `_CONTRACT_FLAGS_SYS` (`:464`) as
  well. Extract all four.
- **Capture hashes first.** Before editing, print
  `hashlib.sha256(<CONSTANT>.encode()).hexdigest()` for each of the four
  constants and pin those values in the test. Do the write, then assert the
  on-disk file reproduces the same hash. This is exactly the pattern in
  `ari-core/tests/test_prompt_extraction.py`.
- **Trailing newline:** the skill constants are parenthesized string
  concatenations with **no** trailing `\n`. Write the `.md` files without a
  trailing newline, or trim one on load, mirroring
  `llm_evaluator.py:256-261` / `:416-420`.
- **Prefer raw `load()` over `.format()`** for these four: every one embeds a
  literal JSON schema (`{"scores": ...}`, `{"metric_keyword": ...}`, etc.).
  Using `str.format` would misread those braces; raw read avoids the problem and
  none of the four has a real `{placeholder}`.
- **Do not touch litellm kwargs.** Each call site uses `temperature=0.0` and a
  model resolved from `ARI_MODEL_EVAL`/`ARI_MODEL`/`ARI_LLM_MODEL`/`gpt-4o-mini`
  env chain. Leave routing, timeout, and JSON-extraction regex exactly as-is.
- **Core is a no-op unless proven otherwise.** The two core evaluator templates
  are already externalized and snapshot-tested; keep the diff to the skill.
  Document the core-verification result in the PR body.
- **`sonfigs/` does not exist** anywhere in the repo — ignore any reference to
  it. The relevant config trio is `ari-core/ari/config/` (code),
  `ari-core/ari/configs/` (packaged defaults), and top-level `config/` (rubric
  data); none is touched by this subtask.
- **Defer the MERGE.** Resist folding `_METRIC_EXTRACT_SYS` into core
  `evaluator/extract_metrics.md`; they are related but not identical
  (optimize-target selection vs artifact extraction). Leave a REVIEW_REQUIRED
  note for a later consolidation subtask.
- **Packaging parity:** confirm and copy `ari-skill-replicate`'s exact
  `pyproject.toml` / `MANIFEST.in` mechanism for shipping `src/prompts/` so the
  two skills stay consistent and the wheel build includes the `.md` files.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **040** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
