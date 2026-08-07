# Task 07: PromptSpec and Prompt Evolution

> **Status**: planned · **Depends on**: 00, 02, 04, 05, 06 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

ARI's prompts today are committed `.md` templates loaded as raw strings and pinned by four
snapshot layers. This is excellent for reproducibility but leaves no sanctioned way to *evolve*
a prompt: there is no versioned identity beyond a content hash, no lifecycle, no validation
pipeline, and no way for a governance layer to introduce, trial, and adopt a new reviewer or
adversary prompt without hand-editing committed files and re-blessing every golden.

This task designs the **PromptSpec** layer for `ari_rqgm` mode: prompts become versioned,
role-scoped, constraint-carrying objects with a strict lifecycle
(candidate → static validation → constitutional validation → schema dry-run → replay evaluation
→ anchor evaluation → shadow live evaluation → probationary_active → active), and prompt
evolution becomes a governed, budgeted, epoch-boundary-only process. It also defines how the
existing committed prompts become the **v1 founding PromptSpecs** so that `simple_bfts` mode
remains byte-identical to today.

Hard prohibitions this task encodes (SPEC "PromptSpec and prompt evolution" + global
invariants 1–3, 10, 15):

- **No in-place mutation of active prompts.** Prompt text is never overwritten; evolution
  always creates a new `prompt_id` with a new `prompt_hash`.
- **No instant activation.** A candidate can never skip lifecycle stages; clean-room candidates
  (Task 08) in particular are never activated immediately.
- **PromptMutator never writes to the registry.** It emits `PromptCandidate` records only;
  all status changes go through RegistryTransitionEngine (Task 09) and are validated by
  ConstitutionalKernel (Task 04).
- **Active prompts are frozen within an epoch** (invariant 1–2); adoption happens only in the
  epoch-boundary transaction, emergency quarantine excepted.

## 2. Scope

- `PromptSpec` schema: identity, role, status, generation mode, `spec` body
  (role_instruction, constitutional_constraints, input_contract, output_schema, rubric,
  calibration_policy, budget_policy), template reference, placeholder contract, hashes.
- `PromptCandidate` and `PromptCandidateValidation` schemas.
- The nine-stage candidate lifecycle and the validation pipeline that drives it
  (which stages are deterministic, which consume LLM calls, which are budgeted).
- The five mutation families produced by PromptMutator: freeform mutation, threshold tuning,
  schema tightening, specialization, distillation.
- Replay evaluation (against the AdversarialReplayPool from Task 06) and shadow live
  evaluation (sampled side-by-side execution whose output never affects BFTS scores).
- Bootstrap: mapping the 11 existing committed `ari-core/ari/prompts/**/*.md` templates
  (plus, later, skill-side prompt mirrors) to v1 founding PromptSpecs with
  `prompt_hash == hash12(template bytes)` — the existing hash scheme, unchanged.
- On-disk storage of PromptSpecs and evolved prompt bodies (checkpoint-scoped), provenance
  wiring through `record_prompt_use`'s reserved `prompt_version` / `prompt_registry_version`
  fields, and the `GovernedPromptLoader` that resolves role → active PromptSpec in
  `ari_rqgm` mode while degrading to today's `FilesystemPromptLoader` behavior in
  `simple_bfts` mode.
- The missing `expand_prompt` config knob so the BFTS expansion prompt becomes swappable
  like the two selector prompts already are.
- The CI story for runtime-generated prompt bytes (Gate 10 carve-out design).

## 3. Non-goals

- **No implementation.** This is a plan only.
- Registry *state machine mechanics* (who applies transitions, transaction semantics,
  the full transition table incl. warning/probation/quarantine/retired/banned) — Task 09.
  This task defines the candidate-side lifecycle stages and hands promotion decisions to
  Task 09's engine.
- PromptRegistry / ComponentRegistry / EpochState schemas — Task 02. This task only states
  what PromptSpec-specific fields the PromptRegistry must carry.
- Clean-room regeneration (contamination rules, `CleanRoomGenerationRequest`) — Task 08.
  Clean-room candidates enter this task's pipeline at the `candidate` stage like any other.
- Adversarial replay pool construction and `ValidatedAttackRecord` — Task 06. This task only
  consumes replay cases.
- Governance adjudication of candidates (ReplayBoard / AnchorBoard membership, GovernanceReport)
  — Task 05. This task defines what those boards evaluate and what records they produce.
- Meta-evolution of the PromptMutator itself — Task 11.
- Budget numbers and cache-key enforcement — Task 12 (this task references its knobs).
- Evolving anything in the fixed layer: `ConstitutionalKernel`, fixed verifier, metric
  recomputer, audit log, hash registry are never prompt-evolution targets (invariant 16).

## 4. Existing ARI touchpoints

Prompt loading and hashing:

- `ari-core/ari/prompts/_loader.py` — `PromptLoader` Protocol and `FilesystemPromptLoader`;
  `load_versioned(key) -> (text, sha256(text)[:12])`. **This 12-char content hash is already
  the `prompt_hash` primitive**; PromptSpec must reuse it, not introduce a second scheme.
  `FilesystemPromptLoader(base=...)` accepts an alternative root — the hook for
  checkpoint-scoped evolved prompt bodies. `load_versioned`'s `version` parameter exists but
  is unused by callers — the natural pin mechanism for epoch-resolved versions.
- `ari-core/ari/prompts/registry.py` — `PromptEntry(key, path, discovered, version_id,
  placeholders)` and `PromptRegistry`: structurally a proto-PromptSpec (identity + hash +
  placeholder interface). Deliberately not exported via `ari.public.*`, so extending it does
  not touch the public-API contract snapshot.
- `ari-core/ari/prompts/_provenance.py` — `record_prompt_use(...)` → `prompt_trace.jsonl`;
  `PromptUseRecord` has two reserved always-`None` fields, `prompt_version` and
  `prompt_registry_version`, explicitly waiting for a registry layer. `hash12()` here is
  asserted identical to `load_versioned`'s scheme.
- `ari-core/ari/protocols/__init__.py` — re-exports `PromptLoader`; the DI seam a
  `GovernedPromptLoader` must satisfy.

The 11 committed templates that become v1 founding PromptSpecs (all under
`ari-core/ari/prompts/`): `agent/system.md`,
`evaluator/extract_metrics.md`, `evaluator/peer_review.md`,
`orchestrator/bfts_select.md`, `orchestrator/bfts_expand.md`,
`orchestrator/bfts_expand_select.md`, `orchestrator/lineage_decision.md`,
`orchestrator/root_idea_selector.md`, `pipeline/keyword_librarian.md`,
`viz/wizard_chat_goal.md`, `viz/wizard_generate_config.md`.
(Note: `orchestrator/lineage_decision` and `orchestrator/root_idea_selector` are loaded raw
and never `.format`ed — their PromptSpecs must record an empty placeholder contract.)

Config-driven prompt swapping (the tested precedent this task extends):

- `ari-core/ari/config/__init__.py` — `BFTSConfig.select_prompt` and
  `BFTSConfig.expand_select_prompt` are loader keys with documented placeholder contracts;
  swap behavior is pinned by `ari-core/tests/test_bfts_prompt_selection.py`.
- `ari-core/ari/orchestrator/bfts.py` — `select_next_node` / `select_best_to_expand` read those
  config keys; `BFTS.expand` hardcodes `"orchestrator/bfts_expand"` — the gap this task closes
  with a new `expand_prompt` field.
- `ari-core/ari/evaluator/llm_evaluator.py` — `BASE_SYSTEM` / `BASE_SYSTEM_HASH` loaded at
  class definition time; `peer_review.md`'s `{axes_block}`; evaluator prompts are the primary
  evolution target for the reviewer/judge roles.

Snapshot/gating layers every committed prompt change must pass (and which force the
runtime-prompt carve-out design in §5.6):

- `ari-core/tests/test_prompt_extraction.py` — hand-pinned full sha256 rows (`_EXPECTED_HASHES`).
- `ari-core/tests/test_prompt_snapshots.py` + `ari-core/tests/snapshots/prompts/` —
  auto-discovered raw+rendered byte goldens; exact-set equality both directions;
  re-bless via `ARI_UPDATE_PROMPT_SNAPSHOTS=1`; `FIXTURE_KWARGS` / `EXPECTED_FIELDS` mandatory
  per key.
- `ari-core/tests/test_prompt_registry.py` — `_EXPECTED_KEYS` pins the key set (currently 11).
- `report/scripts/snapshot_prompts.py` + `report/scripts/check_prompt_snapshots.py` — Gate 10:
  every `ari-core/ari/prompts/**/*.md` must have a verbatim report-appendix snapshot; hard CI.
- `.github/workflows/prompt-change-review.yml` — Gate 10 + `test_prompt_extraction.py` as hard
  gates; co-change advisory.
- `scripts/check_prompts.py` — flags new *inline* prompt literals; all RQGM prompts
  (including the PromptMutator's own meta-prompts) must be externalized `.md` from day one.
- `ari-core/tests/test_prompt_provenance.py` — META_FILES registration and additive-schema
  conventions for provenance records.

State/persistence conventions the new stores must follow:

- `ari-core/ari/paths.py` — `PathManager.META_FILES` (+ `_TRACE_FILES`): every new
  checkpoint-root filename must be registered or it contaminates node work dirs.
- `ari-core/ari/checkpoint.py` — store-method + module-shim pattern for new snapshot files
  (`save_prompt_versions_json` precedent).
- `ari-core/ari/cli/bfts_loop.py` — end-of-run `prompt_versions.json` rollup (~line 920);
  the "JSONL is truth, snapshot is derived rollup" precedent.
- `ari-core/ari/orchestrator/lineage_decision.py` — `append_decision_log`: the append-only,
  fail-open JSONL audit shape all prompt-evolution records copy.

Skill-side prompts (out of v1 scope but constrained): `ari-skill-evaluator/src/prompts/` and
peers carry mirror loaders with the same `sha256[:12]` scheme; skills must not import ari-core,
so any future governed skill prompts need a mirrored (not imported) PromptSpec reader.

## 5. Proposed design

### 5.1 PromptSpec: prompts as versioned objects

A `PromptSpec` is the unit of prompt identity in `ari_rqgm` mode. It separates:

- **identity**: `prompt_id` (e.g. `reviewer_prompt_v4`), `role`, `version`, lineage
  (`parent_prompt_id`), `generation_mode` (`founding | mutation | clean_room`);
- **bytes**: a `template_ref` pointing at the template file whose bytes define
  `prompt_hash = sha256(bytes)[:12]` (identical to `load_versioned`; a `full_sha256` is also
  stored, matching the `test_prompt_extraction.py` convention);
- **contract**: `input_contract` (required placeholder/context fields), `output_schema`
  (what the LLM must return — e.g. the bare-index reply for selector prompts, the JSON
  contract for reviewer prompts), `constitutional_constraints` (machine-checkable clauses like
  "Do not override fixed verifier failures"), `rubric`, `calibration_policy`, `budget_policy`.

The template bytes stay dumb Markdown compatible with `str.format` single-brace placeholders.
The PromptSpec is metadata *about* the template; rendering behavior is byte-identical to today.
The kernel (Task 04) verifies `prompt_hash` against bytes; the placeholder contract is verified
with the same `string.Formatter`-based extraction `PromptRegistry` already uses.

### 5.2 Founding bootstrap: existing prompts become v1 PromptSpecs

At the first `ari_rqgm` epoch of a run, a deterministic bootstrap generates one founding
PromptSpec per governed committed template:

- `prompt_id = <role>_prompt_v1`, `generation_mode = "founding"`, `status = "active"`
  (founding specs are the sole exception to the lifecycle — they *are* the incumbent, exactly
  as today's behavior; everything else enters at `candidate`).
- `template_ref` = the package prompt key (e.g. `orchestrator/bfts_expand`);
  `prompt_hash` = the existing `hash12` of the committed bytes — so founding specs are
  verifiable against `_EXPECTED_HASHES` and Gate 10 snapshots with zero new hashing.
- `input_contract.required_fields` = the placeholder set from `PromptRegistry.placeholders`
  (empty for the two raw-loaded templates); `output_schema` transcribed from the template's
  documented reply contract (bare index / JSON array of one / judge JSON).
- Role mapping (initial governed set): `orchestrator/bfts_select` + `bfts_expand_select` →
  role `router`; `orchestrator/bfts_expand` → role `generator`; `evaluator/peer_review` +
  `extract_metrics` → role `reviewer`; `orchestrator/lineage_decision` → role `judge`
  (lineage). `agent/system`, `pipeline/keyword_librarian`, and the two `viz/` prompts are
  registered as founding specs but marked `evolvable: false` in v1 (out of evolution scope
  until a later decision). New RQGM roles (adversary, defender, governance judge, prompt
  mutator) get new committed founding templates under `ari-core/ari/prompts/rqgm/`, passing
  the full new-prompt checklist (all four snapshot layers).

Bootstrap is pure (bytes → spec), so it is P2-deterministic and needs no goldens of its own
beyond schema tests.

### 5.3 Candidate lifecycle

```
candidate
  → static_validation          (deterministic, free)
  → constitutional_validation  (deterministic, kernel, free)
  → schema_dry_run             (1 cheap LLM call, budgeted)
  → replay_evaluation          (replay pool cases, budgeted, cached)
  → anchor_evaluation          (fixed anchor cases, budgeted, cached)
  → shadow                     (sampled live side-by-side, budgeted, output discarded)
  → probationary_active        (adopted at epoch boundary, heightened monitoring)
  → active
```

Stage semantics (records for every stage: one `PromptCandidateValidation` appended to the
prompt-evolution log):

1. **static_validation** (deterministic): template parses; placeholder set == declared
   `input_contract`; no forbidden placeholders; `prompt_hash` matches bytes; size within
   `budget_policy.max_tokens` estimate; `scripts/check_prompts.py`-style inline-prompt rules
   honored; for mutation candidates, `parent_prompt_id` exists and is not retired/banned.
2. **constitutional_validation** (deterministic, ConstitutionalKernel): required
   `constitutional_constraints` for the role are present verbatim (e.g. reviewer must carry
   "Do not override fixed verifier failures"); generation provenance is legal (mutator did not
   write to registry; clean-room candidates carry no forbidden-input refs per Task 08);
   same-role separation rules on the generating component.
3. **schema_dry_run**: render the template with the role's fixture kwargs (reusing the
   `FIXTURE_KWARGS` idea from `test_prompt_snapshots.py`), make one LLM call on a synthetic
   input, and deterministically check the reply parses against `output_schema` (bare index /
   JSON keys). Failure is terminal for the candidate.
4. **replay_evaluation**: run the candidate against up to `rqgm.replay.max_cases_per_epoch`
   `AdversarialReplayCase`s (Task 06). Pass criteria come from the case's
   `expected_behavior` for this role (e.g. reviewer must flag the unfair baseline). Results
   are cached under Task 12's `cache_key` so re-evaluation across epochs is free.
5. **anchor_evaluation**: same mechanics against the fixed held-out anchor set (curated,
   never generated by evolving components — AnchorBoard, Task 05). The anchor set guards
   against reward hacking of the replay pool; candidate must not underperform the incumbent
   on anchors (ties favor the incumbent, per the RQGM paper).
6. **shadow**: for `rqgm.shadow.sample_rate` of live calls (capped by
   `max_shadow_calls_per_epoch`), the candidate is invoked alongside the active prompt on the
   same input. The candidate's output is written only to a `ComparisonObservation` record —
   it never reaches BFTS scores, the frontier, memory, or any downstream consumer
   (invariant: shadow output is observation-only).
7. **probationary_active**: adoption happens only inside the epoch-boundary transaction via
   RegistryTransitionEngine (Task 09) after GovernanceOrchestrator's report (Task 05).
   A probationary prompt is fully active for the epoch but flagged for mandatory review at
   the next boundary; regression demotes it and reinstates the incumbent (which was demoted
   to `shadow`-tier standby, never deleted).
8. **active**: normal incumbent status; frozen for the epoch.

Stage order is monotonic; skipping is a constitutional violation the kernel detects from the
validation record chain. All stage evaluations happen at epoch boundaries except shadow
sampling, which runs during the epoch under its own budget.

> **Implementation correction — the six-stage `CandidateValidationPipeline` is NOT the shipped
> production path (recorded 2026-07-17).** The lifecycle above is the design target; it is
> recorded here so no reader assumes the pipeline object runs. In branch `RQGM`,
> `CandidateValidationPipeline` (`ari-core/ari/rqgm/prompt_evolution.py`) is **never instantiated
> in production** — a repo-wide search finds construction sites only in tests — so it is dead for
> **every** role, exploration and paper alike. What actually runs at the epoch boundary is:
>
> - **Quality scoring: `evaluate_candidates`** (`ari-core/ari/rqgm/governance/_adjudication.py:267`)
>   — deterministic board scoring of each candidate over `replay_cases(pool)` and
>   `anchor_cases(pool)` via `board_score`, emitting `replay_score` / `anchor_score` / `case_refs`
>   and `verdict = "pass"` iff `min(available scores) >= CANDIDATE_PASS_THRESHOLD`
>   (`_adjudication.py:312-322`). This is the live analogue of stages 4 (`replay_evaluation`) and
>   5 (`anchor_evaluation`); the board reads *cached* per-case results, it is not the pipeline's
>   monotonic stage machine.
> - **Constitutional legality: the `ConstitutionalKernel`, wired inside `RegistryTransitionEngine`**
>   (`ari-core/ari/rqgm/transition_engine.py` — "builds the adoption request, has it validated by
>   the Task 04 `ConstitutionalKernel`, and commits it"). This is the live analogue of stage 2
>   (`constitutional_validation`) — enforced at the adoption transaction, not as a free-standing
>   pipeline stage.
> - **The `static_validation`, `schema_dry_run`, and `shadow` stages (1, 3, 6) are NOT exercised as
>   a production pipeline.** A candidate with no replay basis (e.g. a passive `utility_policy`
>   document, or a `paper_reviewer` on the bootstrap on-ramp with an empty pool) is admitted via
>   the role-scoped `no_replay_basis` waiver at the decision site
>   (`transition_engine.NO_REPLAY_BASIS_ROLES`), NOT by a synthesized board number.
>
> Consequently §11.6's "co-evolution is expressed entirely via … `CandidateValidationPipeline`" and
> the "1 cheap LLM call" cost of the `schema_dry_run` stage above do not describe shipped behaviour;
> board scoring is deterministic and pool-fed. Do not cite the pipeline object as the live mechanism
> in downstream docs or tests. (Confirmed against branch `RQGM`, ari-core v0.9.1.)

### 5.4 Mutation families (PromptMutator outputs)

PromptMutator (a meta-tier component, Task 11) generates candidates in five bounded modes,
each recorded as `mutation_kind`:

- **freeform_mutation** — rewrite `role_instruction` guided by the epoch's
  `FailureSummary` (abstract, compressed — never raw attack text).
- **threshold_tuning** — change only numeric knobs inside `calibration_policy` /
  `rubric` (e.g. confidence thresholds, all-accept/all-reject guards). Diff is machine-checked
  to touch nothing else (a deterministic static_validation clause).
- **schema_tightening** — narrow `output_schema` (add required fields, tighten types).
  Never widens; static validation rejects loosening.
- **specialization** — derive a variant scoped to a declared context (e.g. HPC-domain
  reviewer) with an explicit applicability predicate in the spec.
- **distillation** — compress an incumbent's instruction to reduce tokens while passing the
  same replay/anchor bar; motivated by `budget_policy`.

Per-epoch caps (Task 12 config, restated here as consumed limits):
`max_candidates_per_role_per_epoch: 1`, `max_total_candidates_per_epoch: 4`,
`max_clean_room_generations_per_epoch: 1`.

### 5.5 GovernedPromptLoader and call-site wiring

A new `GovernedPromptLoader` implements the existing `PromptLoader` Protocol:

```python
class GovernedPromptLoader:  # satisfies ari.protocols.PromptLoader structurally
    def __init__(self, registry_view, fallback: FilesystemPromptLoader): ...
    def load(self, key: str) -> str: ...
    def load_versioned(self, key, version=None) -> tuple[str, str]:
        # ari_rqgm: resolve key -> active PromptSpec for the frozen epoch set;
        #   if the spec's template_ref is checkpoint-scoped, read
        #   {ckpt}/rqgm_prompts/<prompt_id>.md; else delegate to fallback.
        # Byte-identical delegation when no spec governs the key.
```

Wiring (preserve-existing-behavior first):

- `simple_bfts`: `GovernedPromptLoader` is never constructed; the 11 call sites keep
  constructing `FilesystemPromptLoader()` directly, unchanged.
- `ari_rqgm` v1: rather than rewiring all 11 call sites, reuse the **config-key precedent**:
  the epoch freeze resolves each governed role to a loader key, and `BFTSConfig.select_prompt`
  / `expand_select_prompt` / new `expand_prompt` are pointed at the epoch's active keys.
  For evolved (checkpoint-scoped) prompts, keys resolve under a checkpoint prompt root via
  `FilesystemPromptLoader(base=checkpoint_prompt_dir)` inside `GovernedPromptLoader`.
  Evaluator/agent call sites that have no config key yet are adopted incrementally; until
  adopted, their roles are `evolvable: false`.
- Candidate templates **must accept the incumbent's exact placeholder set** for their key
  (the documented `select_prompt` contract); static_validation enforces this, which is what
  makes key-swapping safe.

### 5.6 Runtime-generated prompt bytes: reproducibility and the Gate 10 carve-out

An evolved prompt is the first managed prompt whose bytes are not a committed `.md`. Design:

- Evolved bodies live at `{ckpt}/rqgm_prompts/<prompt_id>.md` (checkpoint-scoped, v0.5.0
  compliant); the directory and the spec store files are registered in
  `PathManager.META_FILES` / node-report blocklists.
- Every use is logged through `record_prompt_use` with `rendered_prompt_hash`, and the
  reserved fields are finally populated: `prompt_version = prompt_id`,
  `prompt_registry_version` = the `registry_version` of the epoch's frozen registry as
  defined by Task 02 §5.4 (`hash12(canonical_json(sorted (prompt_id, role, status,
  prompt_sha256) tuples))`), obtained from Task 02's
  `GovernedPromptRegistry.registry_version()`. Task 02 owns that formula; this task only
  consumes the value and defines no registry-version scheme of its own.
- A per-epoch **prompt dump** (all active + candidate spec metadata and body hashes) is
  written into the epoch record (Task 02), so a run's full prompt lineage is reconstructible
  offline.
- Gate 10 doctrine ("every prompt in the appendix verbatim") gets an explicit carve-out:
  Gate 10 continues to cover exactly `ari-core/ari/prompts/**` (all founding/committed
  templates, including new `rqgm/` ones); runtime-evolved prompts are covered by the
  checkpoint dump + provenance hashes instead. Since default runs (`simple_bfts`) generate no
  evolved prompts, absence of `rqgm_prompts/` == fully-committed prompt trajectory — the
  `bfts_web_provenance.json` P5 pattern applied to prompts. The carve-out is documented in
  the permanent prompt guide when this plan is executed.

### 5.7 Mode behavior summary

| | simple_bfts (default) | ari_rqgm |
|---|---|---|
| Prompt loading | `FilesystemPromptLoader`, byte-identical to today | `GovernedPromptLoader` resolving the epoch-frozen active set |
| PromptSpec store | absent (nothing written) | checkpoint-scoped spec store + evolution log |
| Prompt evolution | disabled | epoch-boundary, budgeted |
| Snapshot tests | all four layers unchanged | unchanged for committed templates; dump+hash provenance for evolved ones |
| `record_prompt_use` | `prompt_version`/`prompt_registry_version` stay `None` | populated |

VirSci: no interaction. VirSci prompts are skill-internal; with `virsci.enabled=false` no
VirSci prompt is registered in the PromptRegistry (SPEC guarantee), and this task adds no
VirSci dependency.

## 6. Data structures / schema changes

All records carry the mandatory envelope: `record_id`, `epoch_id`, `component_id`,
`prompt_hash`, `role`, `created_at`, `source_refs`, `status`. Envelope semantics for this
task's records: `component_id` names the emitting component (the mutator for
`PromptCandidate`; the pipeline-driving governance component for validation and shadow
records) and `prompt_hash` is the hash of the candidate template the record is about. The
record-specific `generated_by` / `evaluated_by` fields carry richer provenance detail *in
addition to* — never instead of — the top-level envelope fields.

**PromptSpec** (stored in the PromptRegistry, Task 02; JSON schema beside
`ari-core/ari/schemas/`):

```json
{
  "prompt_id": "reviewer_prompt_v4",
  "role": "reviewer",
  "version": 4,
  "status": "candidate",
  "generation_mode": "mutation",
  "parent_prompt_id": "reviewer_prompt_v3",
  "template_ref": {"kind": "checkpoint", "key": "rqgm_prompts/reviewer_prompt_v4"},
  "prompt_hash": "a1b2c3d4e5f6",
  "full_sha256": "…64 hex…",
  "evolvable": true,
  "epoch_introduced": "epoch_004",
  "spec": {
    "role_instruction": "...",
    "constitutional_constraints": [
      "Do not override fixed verifier failures.",
      "Do not directly modify frontier scores.",
      "Always separate major and minor issues."
    ],
    "input_contract": {"required_fields": ["proposal", "node_report", "evidence_refs"]},
    "output_schema": {"major_issues": "list", "minor_issues": "list",
      "evidence_refs": "list", "confidence": "float", "recommended_action": "string"},
    "rubric": {"novelty": "...", "evidence_alignment": "...", "overclaim": "...",
      "reproducibility": "..."},
    "calibration_policy": {"all_accept_guard": true, "all_reject_guard": true,
      "confidence_required": true},
    "budget_policy": {"max_tokens": 1200, "max_evidence_refs": 8}
  }
}
```

`template_ref.kind` ∈ `package` (committed key like `orchestrator/bfts_expand`) |
`checkpoint` (evolved body under `{ckpt}/rqgm_prompts/`). Founding specs use `package`.

**PromptCandidate**:

```json
{
  "record_id": "pcand_00017", "epoch_id": "epoch_004",
  "component_id": "prompt_mutator_v2",
  "prompt_hash": "a1b2c3d4e5f6",
  "candidate_id": "reviewer_prompt_v4",
  "role": "reviewer",
  "generated_by": {"component_id": "prompt_mutator_v2",
                   "prompt_hash": "…mutator meta-prompt hash12…"},
  "generation_mode": "mutation",
  "mutation_kind": "schema_tightening",
  "source_prompt_id": "reviewer_prompt_v3",
  "failure_summary_refs": ["fsum_00042"],
  "rationale": "Reviewer missed unsupported speedup claims in 3 validated attacks.",
  "prompt_spec": { "…full PromptSpec as above…" },
  "status": "candidate",
  "created_at": "…", "source_refs": ["adv_case_00042"]
}
```

`source_prompt_id` is **required** for `mutation` and **forbidden** for `clean_room`
(Task 08 contamination rule, kernel-checked).

**PromptCandidateValidation** (one per stage execution; append-only):

```json
{
  "record_id": "pval_00058", "epoch_id": "epoch_004",
  "component_id": "governance_orchestrator",
  "candidate_id": "reviewer_prompt_v4", "role": "reviewer",
  "prompt_hash": "a1b2c3d4e5f6",
  "stage": "replay_evaluation",
  "passed": true,
  "evaluated_by": "governance_orchestrator",
  "case_results": [
    {"case_id": "adv_case_00042", "expected": "flag unfair baseline", "met": true,
     "cache_key": "…", "cached": false}
  ],
  "metrics": {"replay_pass_rate": 0.875, "incumbent_pass_rate": 0.75},
  "details": "…", "created_at": "…",
  "source_refs": ["pcand_00017"], "status": "final"
}
```

**ComparisonObservation** (shadow stage; observation-only, never an accusation —
invariant 6):

```json
{
  "record_id": "cobs_00203", "epoch_id": "epoch_004",
  "component_id": "governance_orchestrator",
  "candidate_id": "reviewer_prompt_v4", "incumbent_id": "reviewer_prompt_v3",
  "role": "reviewer", "prompt_hash": "a1b2c3d4e5f6",
  "input_context_hash": "…", "node_id": "node_017",
  "candidate_output_hash": "…", "incumbent_output_hash": "…",
  "divergence": {"recommended_action": ["revise", "accept"], "confidence_delta": -0.2},
  "created_at": "…", "source_refs": [], "status": "recorded"
}
```

**On-disk layout** (final naming coordinated with Task 02's epoch-state decision; all names
registered in `META_FILES`/`_TRACE_FILES`):

- `{ckpt}/prompt_evolution.jsonl` — append-only truth: PromptCandidate,
  PromptCandidateValidation, ComparisonObservation, adoption/demotion echoes. Fail-open
  writer modeled on `ari/prompts/_provenance.py:record_prompt_use`.
- `{ckpt}/prompt_specs.json` — derived snapshot rollup of the current registry view
  (mirrors `prompt_versions.json` rollup pattern; written best-effort at epoch boundaries and
  run end via a new `ari/checkpoint.py` store method).
- `{ckpt}/rqgm_prompts/<prompt_id>.md` — evolved template bodies.

**Config sketch** (typed fields under Task 01's `RQGMConfig`; consumed limits owned by
Task 12):

```yaml
rqgm:
  prompt_evolution:
    enabled: true                 # only meaningful when ari.mode == ari_rqgm
    max_candidates_per_role_per_epoch: 1
    max_total_candidates_per_epoch: 4
    max_clean_room_generations_per_epoch: 1
    mutation_kinds: [freeform_mutation, threshold_tuning, schema_tightening,
                     specialization, distillation]
bfts:
  expand_prompt: orchestrator/bfts_expand   # NEW knob; default preserves behavior
```

## 7. API / class changes

New module family `ari-core/ari/rqgm/` (kept **out of `ari.public.*`** — the
`PromptRegistry` precedent — so no public-API contract snapshot churn):

```python
# ari/rqgm/prompt_spec.py
@dataclass(frozen=True)
class PromptSpec: ...                       # §6 schema
def founding_spec_from_entry(entry: PromptEntry, role: str, *,
                             evolvable: bool) -> PromptSpec: ...
# Registry version: NOT defined here. The value stamped into provenance comes from
# Task 02's GovernedPromptRegistry.registry_version() (formula owned by 02 §5.4:
# hash12(canonical_json(sorted (prompt_id, role, status, prompt_sha256) tuples))).

# ari/rqgm/prompt_loader.py
class GovernedPromptLoader:                 # satisfies ari.protocols.PromptLoader
    def load(self, key: str) -> str: ...
    def load_versioned(self, key, version=None) -> tuple[str, str]: ...

# ari/rqgm/prompt_evolution.py
class PromptMutator:                        # meta tier; candidates only, no registry writes
    def propose(self, role, incumbent: PromptSpec,
                failure_summaries) -> PromptCandidate: ...
class CandidateValidationPipeline:
    def run_stage(self, candidate, stage) -> PromptCandidateValidation: ...
    # static + constitutional stages are pure functions; dry-run/replay/anchor take an
    # LLM client + budget handle; shadow is driven by the run-loop hook (Task 05).
def record_prompt_evolution_event(checkpoint_dir, record) -> None: ...
    # append-only, lock, no-op without checkpoint, never raises
```

Changes to existing code (all additive):

- `ari-core/ari/config/__init__.py` — add `BFTSConfig.expand_prompt: str =
  "orchestrator/bfts_expand"` (mirrors `select_prompt`); add the
  `rqgm.prompt_evolution` block on `RQGMConfig` (Task 01 owns `RQGMConfig` itself).
- `ari-core/ari/orchestrator/bfts.py` — `BFTS.expand` reads
  `getattr(self.config, "expand_prompt", "orchestrator/bfts_expand")` instead of the
  hardcoded literal (behavior-identical default).
- `ari-core/ari/prompts/_provenance.py` — no schema change needed; `ari_rqgm` call paths pass
  `prompt_version=prompt_id` and
  `prompt_registry_version=<GovernedPromptRegistry.registry_version()>` (Task 02 value)
  through the existing parameters.
- `ari-core/ari/paths.py` — register `prompt_evolution.jsonl`, `prompt_specs.json`,
  `rqgm_prompts/` in `META_FILES`/`_TRACE_FILES` and node-report blocklists.
- No other existing `ari-core/ari/` modules change; registry status transitions are
  Task 09 API, kernel checks are Task 04 API.

New committed founding templates for new roles (each passing the full new-prompt checklist):
`ari-core/ari/prompts/rqgm/prompt_mutator.md`, `rqgm/adversary_*.md` (Task 06 owns content),
`rqgm/defender.md`, `rqgm/governance_judge.md` (Task 05 owns content).

## 8. Migration / compatibility

- **`simple_bfts` is untouched.** No RQGM module is imported on that path; all 11 call sites
  keep constructing `FilesystemPromptLoader()` directly; `expand_prompt` defaults to the
  current hardcoded key, so rendered bytes, hashes, `prompt_trace.jsonl` content, and all four
  snapshot layers are unchanged. `prompt_version`/`prompt_registry_version` remain `None`
  exactly as today.
- **Existing prompts are not moved, renamed, or edited** to become PromptSpecs — founding
  specs reference committed keys; `_EXPECTED_HASHES`, snapshot goldens, and Gate 10 need no
  re-blessing for the bootstrap itself. Only genuinely new `rqgm/` templates add rows/goldens.
- **Single hash scheme**: `prompt_hash` *is* `hash12`; no migration of any recorded hash.
- **Additive persistence only**: new checkpoint files are absence-tolerant (a pre-RQGM
  checkpoint resumes cleanly; an RQGM checkpoint opened by `simple_bfts` ignores the extra
  files). No changes to `tree.json`/`nodes_tree.json`/`results.json`.
- **Resume**: the active prompt set is part of the epoch freeze persisted by Task 02;
  `GovernedPromptLoader` reconstructs its view from the checkpoint, never from in-memory
  state (BFTS in-memory state does not survive resume).
- **Rollback**: disabling `ari_rqgm` (allowed at run start / epoch boundary only, Task 01)
  reverts prompt resolution to committed founding templates; evolved records remain on disk
  as inert provenance (selective-erasure principle: nothing physically deleted).
- **Skill prompts**: unaffected in v1 (`evolvable: false` is not even declared for them —
  they are simply outside the governed set); a future task may mirror the reader.

## 9. Tests

Unit (in `ari-core/tests/`, each new module gets a like-named test file + README Contents
rows for readme-sync):

- `test_rqgm_prompt_spec.py` — schema round-trip; envelope fields; founding bootstrap maps
  each governed committed template to a spec whose `prompt_hash` equals
  `load_versioned(key)[1]` (parity with `_EXPECTED_HASHES` rows); raw-loaded templates get
  empty placeholder contracts; the `prompt_registry_version` stamped through
  `record_prompt_use` equals Task 02's `GovernedPromptRegistry.registry_version()` for the
  same frozen set (parity test only — the formula and its determinism tests are owned by
  Task 02).
- `test_rqgm_prompt_lifecycle.py` — stage order is monotonic (skipping any stage is
  rejected); candidate never reaches `probationary_active` without all six prior stage
  records; founding-spec exception is the only `active`-on-creation path; in-place mutation
  attempts (same `prompt_id`, different bytes) are rejected; PromptMutator API has no
  registry-write surface (AST/attribute test in the style of
  `ari-core/tests/_arch_boundaries.py`).
- `test_rqgm_prompt_loader.py` — `GovernedPromptLoader` satisfies the `PromptLoader`
  Protocol (`isinstance` under `runtime_checkable`); ungoverned keys delegate byte-identically
  to `FilesystemPromptLoader` (compare against `ari-core/tests/snapshots/prompts/` raw
  goldens); checkpoint-scoped `template_ref` resolves under `tmp_path` with
  `ARI_CHECKPOINT_DIR` monkeypatched (repo testing convention).
- `test_rqgm_prompt_validation.py` — static validation catches placeholder drift, oversized
  templates, loosened output schemas (schema_tightening direction check), threshold_tuning
  diffs touching non-numeric fields; constitutional stage rejects missing mandatory
  constraints and `clean_room` candidates carrying `source_prompt_id`; all deterministic
  stages are LLM-free (import scan).
- `test_rqgm_prompt_evolution_records.py` — append-only writer is fail-open (no checkpoint →
  no-op, never raises); new filenames asserted present in `PathManager.META_FILES`
  (`test_new_filenames_are_meta_files` pattern from `test_prompt_provenance.py`); rollup
  snapshot derived deterministically from the JSONL.
- Extend `test_bfts_prompt_selection.py` — new `expand_prompt` config key swaps the expand
  template via the same fake-loader patch; default key preserves current behavior.

Integration / regression:

- `simple_bfts` regression: full existing prompt suites
  (`test_prompt_extraction.py`, `test_prompt_snapshots.py`, `test_prompt_registry.py`,
  `test_prompt_provenance.py`) pass **without modification** except `_EXPECTED_KEYS` /
  `_EXPECTED_HASHES` / goldens rows added for genuinely new committed `rqgm/` templates.
- `ari_rqgm` smoke: bootstrap → one synthetic mutation candidate → static + constitutional +
  dry-run (stub LLM) → replay (stub cases) → shadow record → adoption request handed to a
  stubbed transition engine; assert `prompt_trace.jsonl` rows carry populated
  `prompt_version`/`prompt_registry_version`; assert shadow outputs never appear in
  `node.metrics` or the frontier.
- Budget: candidate caps per role/epoch enforced; shadow call cap enforced (coordination
  with Task 12's budget tests).

CI:

- New committed `rqgm/` templates follow the 7-step new-prompt checklist (hash row, fixtures,
  goldens, `_EXPECTED_KEYS`, Gate 10 snapshot run, READMEs, report mirror) so
  `prompt-change-review.yml` and readme-sync stay green.
- Any new RQGM prompt checker lands Stage-1 advisory first (`continue-on-error` /
  `--warning-only`), per the staged-rollout policy in the workflow headers.

## 10. Risks

- **Gate 10 doctrine break** (highest): runtime-evolved prompts are the first managed prompts
  not in the report appendix. Mitigation: the §5.6 carve-out (checkpoint dump +
  registry-version provenance (Task 02 §5.4) + "absence of `rqgm_prompts/` ==
  fully-committed trajectory" marker semantics);
  must be moved to permanent docs or reviewers will treat evolved prompts as a CI hole.
- **Placeholder-contract drift**: a candidate that renders but changes the reply contract
  (e.g. selector no longer answers with a bare index) breaks `_extract_directions_json`-style
  parsers silently. Mitigation: `output_schema` dry-run stage is terminal-on-failure, and
  deterministic fallbacks (`_select_fallback`, fallback child) already bound the damage.
- **Loader-injection blast radius**: rewiring all 11 direct `FilesystemPromptLoader()`
  constructions at once is high-risk; the config-key route covers only BFTS prompts in v1.
  Accepted: evaluator/agent roles become evolvable in a later increment.
- **Reward hacking of the replay pool**: candidates tuned to replay cases only. Mitigation:
  anchor evaluation with incumbent-favoring ties (paper-faithful), anchor set curated outside
  evolving components (Task 05).
- **Cross-epoch score comparability** (I-11 in the BFTS report): prompt swaps change reviewer
  behavior mid-run; axis re-weighting is now a first-class, governed event on the same epoch
  boundary as a prompt swap (Task 14), and both retire hashes into the same repair pass.
  Mitigation: epoch id on all records; Task 14 owns frontier-side comparability policy;
  probationary monitoring compares within-epoch only.
- **Cost creep**: replay/anchor/shadow all consume LLM calls. Mitigation: hard caps + Task 12
  cache keys; shadow defaults conservative (`sample_rate: 0.2`, ≤10 calls/epoch).
- **Concurrent writers**: shadow observations are produced on worker threads. Mitigation:
  the append-only writer reuses the `record_prompt_use` lock discipline; registry mutations
  happen only on the main thread at epoch boundaries.
- **Kernel bypass**: a buggy pipeline could activate a candidate directly. Mitigation:
  status writes live solely in Task 09's engine; kernel validates every transition
  (invariants 10–11); tests assert PromptMutator/pipeline expose no write path.

## 11. Completion criteria

This task is complete when all of the following hold (concretized from the SPEC's Task 07
criteria):

1. **PromptSpec defined**: the §6 PromptSpec schema (identity, hashes reusing `hash12`,
   `template_ref`, `spec` body with constitutional_constraints / input_contract /
   output_schema / rubric / calibration_policy / budget_policy) is fully specified, including
   the founding-bootstrap mapping for every governed committed template in
   `ari-core/ari/prompts/` and the role/evolvable assignment table.
2. **Lifecycle defined**: the full nine-state lifecycle (candidate → static validation →
   constitutional validation → schema dry-run → replay evaluation → anchor evaluation →
   shadow → probationary_active → active) is specified with per-stage pass criteria, the
   record emitted per stage (`PromptCandidateValidation`, `ComparisonObservation`), stage
   determinism/LLM classification, budget hooks, and the epoch-boundary-only adoption rule.
3. **In-place mutation prohibition stated**: the plan states — and the design structurally
   enforces (immutable specs, new `prompt_id` per change, kernel `prompt_hash` verification,
   status writes only via RegistryTransitionEngine) — that active prompt text is never
   mutated in place and prompt text bytes are never overwritten.
4. **No instant activation stated**: the plan states — and the lifecycle + tests enforce —
   that no candidate (mutation or clean-room) can be activated without passing every stage,
   that PromptMutator cannot write to the registry, and that founding bootstrap is the sole
   documented exception.
5. Supporting deliverables specified: `PromptCandidate` and `PromptCandidateValidation`
   schemas; the five mutation families (mutation, threshold tuning, schema tightening,
   specialization, distillation) with their validation constraints; replay evaluation and
   shadow evaluation mechanics and their attachment points; the `expand_prompt` config
   addition; the on-disk store layout with META_FILES registration; the Gate 10 carve-out
   design; and the §9 test list.

## 12. Deletion criteria

This plan file may be deleted only when all of the following hold:

- The target feature/design is merged into the main branch.
- Corresponding tests have been added.
- CI is green.
- Key design decisions have been moved to permanent docs or code comments.
- No unresolved open questions remain, or they have been moved to another task plan.
- No downstream task depends solely on this plan file.
- INDEX.md task status has been updated to completed/deleted.
- Developers will not be confused by this file's absence.
- The deleted content remains available in git history.

Task-specific criteria (all must additionally hold):

- The PromptSpec schema is implemented (schema file + dataclass + founding bootstrap).
- The candidate→shadow→active lifecycle is represented in the PromptRegistry (Task 02
  structures) and driven end-to-end through the validation pipeline.
- Active prompts are demonstrably not mutated in place (enforced by kernel hash checks and
  covered by tests).
- Replay-evaluation and shadow-evaluation attachment points exist in the codebase (pipeline
  stage hooks wired to the AdversarialReplayPool consumer and the run-loop shadow sampler,
  even if their counterpart tasks are still stubs).
- Tests for all of the above have been added (the §9 suites) and pass in CI.
- The Gate 10 carve-out for runtime-generated prompts, the prompt-hash policy
  (`hash12` single scheme; registry version per Task 02 §5.4's formula, consumed not
  redefined here), and the founding-bootstrap mapping have been migrated to permanent docs
  (schema reference + developer guide + prompt guide).

## 13. Delete-after checklist

Verify before deleting this file:

- [ ] Implementation is complete.
- [ ] Tests exist.
- [ ] CI is green.
- [ ] Key design decisions have been moved to permanent docs.
- [ ] Unfinished items have been moved to another task plan.
- [ ] INDEX.md has been updated.
- [ ] Deleting this plan file will not strand any developer.
- [ ] The deletion reason can be stated in the commit message.
- [ ] PromptSpec schema implemented and founding bootstrap verified hash-identical to the committed templates.
- [ ] Lifecycle states live in the PromptRegistry and transitions flow only through RegistryTransitionEngine.
- [ ] In-place mutation of active prompts is blocked by ConstitutionalKernel checks with tests.
- [ ] Replay and shadow evaluation attachment points exist and are exercised by at least one test each.
- [ ] `simple_bfts` prompt behavior is byte-identical (all four snapshot layers pass unmodified for pre-existing templates).
- [ ] Gate 10 carve-out for runtime-generated prompts documented in permanent docs.
