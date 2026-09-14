# Task 08: Clean-room Regeneration

> **Status**: planned · **Depends on**: 00, 04, 07, 09 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

When a prompt is impeached and retired (Task 09), ARI-RQGM must never "patch" the retired
prompt. Direct editing propagates the retired prompt's failure modes, overfits the successor
to the specific attacks that killed its predecessor, and destroys the audit story ("which
bytes was the reviewer running?"). This task designs **clean-room regeneration**: a successor
prompt for the same role is generated from scratch, from *abstract* inputs only — role
specification, output schema, constitutional constraints, an abstract failure summary, replay
requirements, and a cost budget — with the retired prompt text, its few-shots, its reasoning
traces, raw attack text, and defense text all **forbidden** as inputs.

The task defines:

1. the `CleanRoomGenerationRequest` and `CleanRoomInputBundle` schemas,
2. the abstract `FailureSummary` contract (what may cross the contamination boundary),
3. the contamination-free policy (forbidden vs allowed inputs) and its three-layer
   enforcement by the ConstitutionalKernel,
4. the rule that clean-room candidates are never activated instantly — they enter the normal
   Task 07 candidate lifecycle at the very beginning.

This implements global invariants 14 ("CleanRoomPromptGenerator cannot read retired prompt
text") and 15 ("PromptMutator/CleanRoomPromptGenerator can generate candidates but cannot
activate them") for the clean-room path.

## 2. Scope

- `CleanRoomGenerationRequest` record schema (trigger, target role, allowed-inputs flags,
  requirements, budget) + its checkpoint-scoped persistence.
- `CleanRoomInputBundle` — the *materialized, closed* input set actually handed to the
  generator, with a canonical hash.
- Abstract `FailureSummary` schema constraints relevant to clean-room (closed failure-class
  vocabulary, ids-only source refs, no verbatim quotes) — the record itself is produced by
  the FailureSummaryCompressor (Task 11).
- Contamination-free policy: the forbidden/allowed input split and the deterministic
  contamination screen (shingle-overlap check) run by the ConstitutionalKernel on both the
  bundle (pre-generation) and the candidate PromptSpec (post-generation).
- Access-prohibition enforcement design: constructive containment (one-shot generation
  harness with no tools/filesystem), capability denial at the sanctioned registry read API,
  and detective blocking checks.
- Generation timing: inside the epoch-boundary window, after
  `registry_transition_engine.apply(transition)`, budget-capped by
  `rqgm.prompt_evolution.max_clean_room_generations_per_epoch`.
- Handoff contract into the Task 07 lifecycle (`status: candidate`,
  `generation_mode: clean_room`, provenance back-links).
- Role-fallback rule so a retirement never leaves a role vacant.

## 3. Non-goals

- The PromptSpec schema and candidate→shadow→active lifecycle itself (Task 07).
- Retirement decisions, `EpochTransition`, and the transition table (Task 09).
- The full ConstitutionalKernel design (Task 04) — this task only *specifies* the two
  clean-room checks and the capability it must enforce.
- AdversarialReplayPool construction and `ValidatedAttackRecord` (Task 06); this task only
  consumes case *ids* and abstract `expected_behavior` fields.
- Evolution of the CleanRoomPromptGenerator itself (Task 11, meta tier).
- OS-level sandboxing / filesystem ACLs. The flat checkpoint layout is readable by any
  process holding `ARI_CHECKPOINT_DIR`; we do not attempt kernel-level isolation (see §5.4
  and §10 for the honest limitation and its mitigations).
- Any change to `simple_bfts` behavior. Nothing in this task runs unless
  `ari.mode: ari_rqgm` is set.

## 4. Existing ARI touchpoints

All paths repo-relative; verified to exist on branch `RQGM`.

| Touchpoint | Relevance |
|---|---|
| `ari-core/ari/prompts/registry.py` (`PromptEntry`, `PromptRegistry`) | Proto-PromptSpec that Task 07 extends; clean-room candidates are registered here with `generation_mode: clean_room`. Kept out of `ari.public.*` (no contract-snapshot churn). |
| `ari-core/ari/prompts/_loader.py` (`FilesystemPromptLoader.load_versioned`) | The single prompt-hash scheme, `sha256(text)[:12]`. Clean-room candidate `prompt_hash` **is** this value — no second scheme. |
| `ari-core/ari/prompts/_provenance.py` (`record_prompt_use`, `hash12`, `PromptUseRecord`) | Template for the append-only clean-room event log (lock, run-pin no-op, never raises, additive dataclass). The generator's rendered meta-prompt is logged here with `phase="governance"`. |
| `ari-core/ari/paths.py` (`PathManager.META_FILES`, `_TRACE_FILES`) | New checkpoint-root filenames (`rqgm_cleanroom.jsonl`) must be registered or they contaminate node work dirs and `node_report.files_changed`. |
| `ari-core/ari/orchestrator/node_report/builder.py` (`_INTERNAL_JSON_NAMES`, blocklists) | Same registration duty for any JSON snapshot this task adds. |
| `ari-core/ari/checkpoint.py` (`save_prompt_versions_json` + module shim) | Pattern for any snapshot writer; clean-room state snapshots (if added) follow it. |
| `ari-core/ari/protocols/stores.py` | Home for a `CleanRoomStore`-style Protocol if the store is abstracted; follows the `TraceStore` Protocol + sibling-module-impl pattern. |
| `ari-core/ari/orchestrator/lineage_decision.py` (`append_decision_log`, fallback-to-safe-default) | The governance-precedent template: restricted enum, deterministic-rule-first, best-effort logging, degrade-never-crash. Clean-room failure handling mirrors it. |
| `ari-core/ari/cli/bfts_loop.py` (`_run_loop`) | The epoch-boundary hook site (head of the outer `while`, per Task 01/05) where pending `clean_room_requests` from the applied `EpochTransition` are processed on the main thread. |
| `ari-core/ari/agent/react_driver.py` (`run_react`) | **Rejected alternative** for the generation harness (see §5.4 decision D1): a ReAct rollout has filesystem tools and could read retired prompt text; cited to document why one-shot generation was chosen. |
| `ari-core/ari/mcp/client.py` (`MCPClient`, 3-retry policy) | **Rejected alternative** for invoking generation: MCP retries re-execute tools, and an LLM generation call is not idempotent. Generation is an in-process call from the boundary transaction instead. |
| `ari-core/ari/core.py` (`build_runtime`) | Where the generator harness gets its `LLMClient` (config-conditional wiring precedent, `ari_rqgm` only). |
| `ari-core/ari/config/__init__.py` (`ARIConfig`, typed config blocks) | `rqgm.clean_room.*` knobs live in the typed `RQGMConfig` block introduced by Task 01 (`load_config` filters unknown top-level keys, so raw YAML blocks are silently dropped otherwise). |
| `ari-core/ari/schemas/node_report.schema.json` | Sibling location for the new `clean_room_request.schema.json` / `clean_room_bundle.schema.json`, loadable via `ari.schemas.load`. |
| `ari-core/ari/cost_tracker.py` (`CallRecord`, `set_default_metadata`) | The generation call is cost-attributed with `phase="governance"`, `skill="clean_room"`, plus the additive `epoch` field from Task 02/12. |
| `ari-core/tests/test_prompt_extraction.py`, `ari-core/tests/test_prompt_snapshots.py`, `report/scripts/check_prompt_snapshots.py`, `scripts/check_prompts.py` | The four gating layers that the generator's **own committed meta-prompt** (`ari-core/ari/prompts/rqgm/clean_room_generator.md`, new) must satisfy: `_EXPECTED_HASHES` row, fixture + goldens, Gate 10 appendix snapshot, no-inline-prompt rule. |

## 5. Proposed design

### 5.1 Trigger and flow

```
RetirementEvent (Task 09)
  → EpochTransition.clean_room_requests[]           (decided by RegistryTransitionEngine)
  → CleanRoomGenerationRequest persisted            (rqgm_cleanroom.jsonl, status=pending)
  → [epoch boundary, after transition.apply()]
      CleanRoomInputBundleAssembler.assemble()       (deterministic, fixed tier)
  → ConstitutionalKernel.validate_clean_room_bundle  (pre-check: closed fields + screen)
  → CleanRoomPromptGenerator.generate(bundle)        (ONE LLM call, no tools, meta tier)
  → ConstitutionalKernel.validate_contamination_free (post-check on candidate text)
  → PromptCandidate registered, status=candidate, generation_mode=clean_room
  → normal Task 07 lifecycle: static → constitutional → schema dry-run → replay
      → anchor → shadow → probationary_active → active
```

Timing: requests are executed in the epoch-boundary window between
`registry_transition_engine.apply(transition)` and `start_next_epoch(...)` (core-algorithm
steps 13→16), on the main thread in `_run_loop`. At most
`rqgm.prompt_evolution.max_clean_room_generations_per_epoch` (default 1) requests execute
per boundary; excess requests remain `pending` and retry at the next boundary.

### 5.2 Contamination-free policy (the input split)

**Forbidden inputs** (must never appear in the generator's context, directly or quoted):

1. retired prompt text (any version of the retired PromptSpec's `spec` text fields),
2. retired prompt few-shot examples,
3. retired prompt reasoning traces (any LLM output produced *by* the retired prompt,
   including its review/attack/defense/judgment text in the audit log),
4. raw attack text (`RawAttackRecord` bodies),
5. target defense text (`DefenderResponse` bodies).

**Allowed inputs** (the complete, closed set — nothing else):

1. role specification (from the committed role-spec catalog, not derived from any retired
   prompt),
2. output schema (the role's `output_schema` from the PromptSpec contract, Task 07),
3. constitutional constraints (the role's non-negotiable constraint list),
4. abstract failure summary (`FailureSummary`, §6.3 — categorical classes, counts,
   behavioral requirements; ids only, no verbatim text),
5. replay requirements (abstract `expected_behavior` strings from
   `ValidatedAttackRecord.expected_behavior`, plus replay case *ids* used only at
   evaluation time — the generator never sees case bodies),
6. cost budget (`budget_policy`).

Rationale for the split: allowed inputs describe *what the role must do*; forbidden inputs
describe *how the failed incumbent did it* or *what specifically defeated it*. Excluding the
latter prevents (a) inheriting the retired prompt's blind spots, and (b) overfitting the
successor to the exact attack strings, which would game the replay evaluation.

### 5.3 Three-layer enforcement of the access prohibition

**Layer A — constructive containment (primary).** The generation harness is a **single
LLM completion**: context = committed meta-prompt (`rqgm/clean_room_generator.md`) +
canonical serialization of the `CleanRoomInputBundle`. No tool loop, no filesystem access,
no memory search, no MCP. Because the bundle is assembled by deterministic fixed-tier code
from a **closed field set** (`additionalProperties: false`), forbidden material cannot enter
the context unless the assembler itself is broken — which Layer C detects. The rendered
context is provenance-logged via `record_prompt_use` with `rendered_prompt_hash`, and
`bundle_hash` is written to the clean-room event log, so the exact input surface is
auditable after the fact.

**Layer B — capability denial at the sanctioned read path.** Retired PromptSpec text remains
on disk (selective erasure deletes nothing, invariant 13) but is readable only through a
guarded registry accessor (`PromptRegistry.get_retired_text(actor, prompt_id)` in the Task
02/07 registry layer). The ComponentRegistry entry for every meta-tier component carries
`can_read_retired_prompt_text: false` (Task 11 schema); `ConstitutionalKernel`'s
AccessGuard (`validate_capability(actor, "read_retired_prompt_text", prompt_id)`) denies
the call and appends a violation event to the audit log. Only two actors hold the
capability: the ConstitutionalKernel's own contamination checker and the human-facing audit
CLI.

**Layer C — deterministic detective check (blocking at admission).** The kernel runs a
contamination screen (§5.5) twice: on the bundle before generation and on the candidate
PromptSpec text after generation. Any hit ⇒ the candidate is recorded with
`status: rejected_contaminated`, never enters the Task 07 lifecycle, and a
`clean_room_violation` event is appended to the audit log. This check is **fail-closed for
candidate admission** but **fail-open for the run**: the BFTS loop continues; the role falls
back per §5.6.

Honest limitation: any process holding `ARI_CHECKPOINT_DIR` can bypass Layer B by reading
files directly. The design therefore makes the *sanctioned* generation path structurally
incapable of contamination (Layer A) and makes contamination *detectable and blocking*
before a candidate can ever be evaluated or activated (Layer C). The kernel itself may read
retired text — it is fixed-tier, deterministic, and emits only booleans/scores, so no text
flows onward; this exemption is stated explicitly in the constitution doc.

### 5.4 Design decisions

- **D1 — one-shot generation, not a ReAct rollout.** `react_driver.run_react` offers
  sandboxed rollouts, but any tool-bearing loop can read checkpoint files and would reduce
  the access prohibition to the detective layer alone. v1 uses a single completion. If a
  future task needs multi-step generation, it must run in a work dir containing *only* the
  bundle, with the file-read tool suppressed — that redesign requires reopening this
  decision in a successor plan.
- **D2 — in-process call, not an MCP tool.** `MCPClient` retries tools 3× on transport
  errors; LLM generation is not idempotent and would burn budget on retries. The harness is
  called directly from the boundary transaction in `_run_loop`, using the runtime's
  `LLMClient` with governance cost metadata. (Consequence: no new MCP tool name, no
  `mcp_tools.json` contract-snapshot regeneration.)
- **D3 — the generator's meta-prompt is a committed `.md`.** It goes through all four
  snapshot layers (§4, last row). The generator's *output* (the candidate PromptSpec) is a
  runtime-generated prompt and rides Task 07's Gate-10 carve-out (checkpoint-scoped
  candidate store + `rendered_prompt_hash` provenance), not this task.
- **D4 — role fallback, never vacancy.** See §5.6.
- **D5 — evaluation-time vs generation-time inputs.** Replay case bodies are used by the
  ReplayBoard (Task 07 lifecycle) to *evaluate* the candidate; the generator sees only case
  ids and abstract requirements. Aggregate replay results fed back into a later regeneration
  attempt must themselves pass the FailureSummary constraints (ids + categories only).

### 5.5 Contamination screen (deterministic)

Pure-stdlib, P2-safe, no LLM, no wall-clock in any hash:

```python
def normalize(text: str) -> str:
    # lowercase, collapse all whitespace runs to single spaces, strip punctuation-only tokens
    ...

def shingles(text: str, k: int = 8) -> set[tuple[str, ...]]:
    toks = normalize(text).split(" ")
    return {tuple(toks[i:i+k]) for i in range(max(0, len(toks) - k + 1))}

def contamination_hits(candidate_text, forbidden_docs, allowlist_docs, *, k=8):
    cand = shingles(candidate_text, k)
    allow = set().union(*(shingles(d, k) for d in allowlist_docs)) if allowlist_docs else set()
    hits = {}
    for doc_id, doc in forbidden_docs.items():
        overlap = (cand & shingles(doc, k)) - allow
        if overlap:
            hits[doc_id] = sorted(overlap)[:5]   # bounded evidence sample
    return hits   # empty dict == clean
```

- **Forbidden corpus**: resolved by the kernel from `RetirementEvent.source_refs` — the
  retired PromptSpec text + few-shots, audit-log outputs produced under the retired
  `prompt_hash`, `RawAttackRecord` bodies, and `DefenderResponse` bodies for the triggering
  cases.
- **Allowlist corpus**: the allowed inputs themselves (role spec, output schema field names,
  constitutional constraint strings, FailureSummary behavioral requirements). Text shared
  with allowed inputs is legitimate and must not trigger a hit.
- **Policy**: `fail_on_any_hit: true` (any surviving k-shingle overlap blocks admission).
  `k=8` tokens is the initial setting; tuning it is a config change, not a code change.
- The same screen validates the `FailureSummary` at creation time (Task 11 wires the call):
  a summary overlapping raw attack text is rejected before it can ever reach a bundle.

### 5.6 Role fallback (no vacancy rule)

The committed baseline templates under `ari-core/ari/prompts/` are the **constitutional
baseline** for each role: they can be displaced from active duty by evolved prompts, but
they are never `banned` and always remain a valid fallback. If a retirement leaves a role
with no `active` prompt and no admissible candidate, the role reverts to its baseline
template for the next epoch (recorded as a `fallback_to_baseline` event). This mirrors
ARI's degrade-never-block discipline and guarantees `simple_bfts` semantics are always
reachable.

## 6. Data structures / schema changes

All records carry the common envelope (Task 02): `record_id, epoch_id, component_id,
prompt_hash, role, created_at, source_refs, status`. `created_at` is metadata only and never
enters any hash.

### 6.1 `CleanRoomGenerationRequest` (`ari/schemas/clean_room_request.schema.json`, new)

```json
{
  "record_id": "cleanroom_req_00042",
  "record_type": "clean_room_generation_request",
  "epoch_id": "epoch_004",
  "component_id": "registry_transition_engine",
  "prompt_hash": null,
  "role": "reviewer",
  "created_at": "2026-07-05T00:00:00Z",
  "source_refs": ["retire_00042", "transition_004_to_005"],
  "status": "pending",
  "trigger": "retirement_event",
  "retirement_event_id": "retire_00042",
  "target_role": "reviewer",
  "allowed_inputs": {
    "role_spec": true,
    "output_schema": true,
    "constitutional_constraints": true,
    "abstract_failure_summary": true,
    "replay_requirements": true,
    "cost_budget": true,
    "retired_prompt_text": false,
    "retired_fewshot_examples": false,
    "retired_prompt_reasoning": false,
    "raw_attack_text": false,
    "target_defense_text": false
  },
  "requirements": [
    "must detect unsupported claims",
    "must cite evidence refs",
    "must distinguish major and minor issues",
    "must calibrate confidence",
    "must not override fixed verifier"
  ],
  "replay_case_ids": ["adv_case_00042"],
  "budget_policy": {"max_tokens": 4000, "max_attempts": 1}
}
```

Schema rules: the five `false` flags are `const: false` in the JSON schema — a request that
sets any of them `true` is schema-invalid and blocked by the kernel before assembly.
`status ∈ {pending, generating, generated, rejected_contaminated, failed, superseded}`.

### 6.2 `CleanRoomInputBundle` (`ari/schemas/clean_room_bundle.schema.json`, new)

```json
{
  "bundle_id": "cleanroom_bundle_00042",
  "request_id": "cleanroom_req_00042",
  "bundle_hash": "<sha256 of canonical JSON: sorted keys, no created_at>",
  "role_spec": "<committed role specification text>",
  "output_schema": {"major_issues": "list", "minor_issues": "list", "evidence_refs": "list",
                    "confidence": "float", "recommended_action": "string"},
  "constitutional_constraints": ["Do not override fixed verifier failures.", "..."],
  "abstract_failure_summary": { "...": "FailureSummary, §6.3" },
  "replay_requirements": ["flag unfair baseline comparison", "include fair baseline and ablation"],
  "cost_budget": {"max_tokens": 4000}
}
```

`additionalProperties: false` — the bundle is the *entire* generator context besides the
committed meta-prompt; a closed field set is what makes Layer A constructive.
`bundle_hash` is computed over the canonical serialization (sorted keys, `ensure_ascii`,
no timestamps) and logged with the generation event.

### 6.3 `FailureSummary` constraints consumed here

Owned by Task 11 (FailureSummaryCompressor); this task pins the contract it must satisfy to
be bundle-admissible:

- `failure_classes`: values from a **closed vocabulary** (e.g. `missed_metric_gaming`,
  `overconfident_acceptance`, `missing_evidence_refs`, `overclaim_pass_through`,
  `calibration_drift`) — enum in the schema, extended only by committing a new enum value.
- `class_counts`, `severity_histogram`: numeric aggregates only.
- `behavioral_requirements`: short imperative strings; screened against the forbidden corpus
  (§5.5) at creation time.
- `source_refs`: record **ids** only — never quoted text.
- `contamination_screen: {passed: true, screen_version: N}` must be present and true.

### 6.4 Persistence

- `{ckpt}/rqgm_cleanroom.jsonl` — append-only event log (request created, bundle assembled
  with `bundle_hash`, generation attempted, screen result with bounded hit evidence,
  candidate registered / rejected, fallback events). Modeled on
  `ari/prompts/_provenance.py` (module lock, run-pin no-op, never raises).
  Registered in `PathManager.META_FILES` + `_TRACE_FILES` + node-report blocklists.
- Requests and candidate PromptSpecs live in the RQGM registry state designed in Tasks
  02/07 (checkpoint-scoped); this task adds no second snapshot file of its own.
- Candidate provenance: `PromptSpec.generation_mode = "clean_room"`,
  `PromptSpec.clean_room_request_id`, and `source_refs = [request_id, retirement_event_id]`.

### 6.5 Config sketch (typed `RQGMConfig`, Task 01)

```yaml
rqgm:
  prompt_evolution:
    max_clean_room_generations_per_epoch: 1     # spec default (Task 12 budget block)
  clean_room:
    generation_backend: one_shot                # v1: one_shot only (D1)
    contamination_screen:
      shingle_k: 8
      fail_on_any_hit: true
    generator_prompt_key: "rqgm/clean_room_generator"
```

No new env vars in v1; no CLI-surface change (keeps the contract-snapshot budget at zero).

## 7. API / class changes

All new code is internal (not `ari.public.*`), constructed only when `ari.mode == ari_rqgm`.

```python
# new module: ari/rqgm/clean_room.py (final home decided with Tasks 04/05 layout)

@dataclass(frozen=True)
class CleanRoomGenerationRequest: ...      # §6.1
@dataclass(frozen=True)
class CleanRoomInputBundle: ...            # §6.2

class CleanRoomInputBundleAssembler:
    """Deterministic, fixed tier. The ONLY writer of bundles."""
    def assemble(self, request, *, prompt_registry, component_registry,
                 failure_summaries) -> CleanRoomInputBundle: ...

class CleanRoomPromptGenerator:
    """Meta tier (evolves under Task 11 constraints). One LLM call, no tools."""
    def __init__(self, llm, prompt_loader, cfg): ...
    def generate(self, bundle: CleanRoomInputBundle) -> "PromptCandidate": ...
    # cannot activate; cannot write registries; returns a candidate object only

def append_cleanroom_event(checkpoint_dir, event: dict) -> bool: ...
def read_cleanroom_log(checkpoint_dir) -> list[dict]: ...
```

ConstitutionalKernel additions (implemented under Task 04, specified here):

```python
class ConstitutionalKernel:
    def validate_clean_room_bundle(self, bundle, request, registries) -> CheckResult:
        """Schema (closed fields, const-false forbidden flags), flag↔field parity,
        FailureSummary admissibility, pre-generation contamination screen."""
    def validate_contamination_free(self, candidate_text, retirement_event,
                                    records) -> CheckResult:
        """Post-generation shingle screen vs the forbidden corpus (§5.5)."""
    # existing (Task 04): validate_capability(actor, action, resource)
    #   → denies action == "read_retired_prompt_text" for any actor whose
    #     ComponentRegistry entry has can_read_retired_prompt_text == false.
```

RegistryTransitionEngine (Task 09) contract touched: it emits
`EpochTransition.clean_room_requests`; it must refuse any transition that would move a
`generation_mode == "clean_room"` prompt from `candidate` to any status other than the next
lifecycle step (no skipping to `active` — invariant 15, kernel-validated).

## 8. Migration / compatibility

- **`simple_bfts` unchanged.** No clean-room module is imported, no file is written, no
  config key is required. A `simple_bfts` run produces no `rqgm_cleanroom.jsonl`.
- **`ari_rqgm` opt-in.** All behavior gated on the Task 01 mode switch; budget default of 1
  generation/epoch bounds cost even when enabled.
- **VirSci-independent.** Clean-room regeneration never touches VirSci; it works identically
  with `proposal_router.generators.virsci.enabled: false` (invariant 19).
- **No physical deletion.** Retired prompt text stays on disk for audit; only access is
  guarded (consistent with selective-erasure semantics, Task 10).
- **Additive persistence.** New filenames registered in `META_FILES`/`_TRACE_FILES`;
  `tree.json`/`nodes_tree.json`/`results.json`/`node_report.json` byte contracts untouched;
  new schemas are new files beside `node_report.schema.json`, not edits to it.
- **Resume-safe.** Requests and events are checkpoint-scoped; a resumed run re-reads
  `pending` requests from the registry state (BFTS in-memory state is not relied on).
- **CI-safe.** The one new committed prompt (`rqgm/clean_room_generator.md`) follows the
  new-prompt checklist (hashes row, snapshot fixtures, Gate 10, README rows); no new MCP
  tool, CLI command, or public symbol, so no other contract snapshots regenerate.

## 9. Tests

Unit (in `ari-core/tests/`, mirroring existing naming; each new file listed in
`ari-core/tests/README.md` for the readme-sync gate):

1. `test_clean_room_request_schema` — valid request passes; any forbidden flag set `true`
   fails; missing envelope fields fail; status enum enforced.
2. `test_clean_room_bundle_assembler` — assembler output contains exactly the closed field
   set; forbidden material planted in registries never appears in a bundle; byte-identical
   bundles (and equal `bundle_hash`) for identical inputs (P2 determinism).
3. `test_contamination_screen` — planted retired-prompt 8-gram in candidate ⇒ hit;
   allowlist subtraction: text shared with constitutional constraints does not trigger;
   normalization (case/whitespace) does not evade the screen; empty corpora ⇒ clean;
   pure-function determinism.
4. `test_clean_room_capability_denied` — AccessGuard denies `read_retired_prompt_text` for
   a meta-tier actor and logs the violation; kernel checker actor is allowed.
5. `test_clean_room_candidate_never_active` — generated candidate has
   `status == "candidate"`; a fabricated transition `candidate → active` for a clean-room
   prompt is rejected by `validate_transition`.
6. `test_clean_room_budget` — second request in one boundary window stays `pending` under
   the default budget; retried next boundary.
7. `test_failure_summary_admissibility` — summary with verbatim attack text fails the
   screen; summary with unknown `failure_classes` value fails schema.
8. `test_cleanroom_files_are_meta_files` — mirrors
   `test_prompt_provenance.py::test_new_filenames_are_meta_files` for
   `rqgm_cleanroom.jsonl`.

Integration:

9. Retirement → request → (stub LLM) generation → candidate registered with full
   provenance chain (`clean_room_request_id`, `source_refs`), event log complete, and the
   provenance-logged generator context hash matches the bundle hash (proves no extra
   context reached the LLM stub).
10. Contaminated stub output ⇒ `rejected_contaminated`, role falls back to baseline, run
    loop continues (fail-open for the run).

Regression / smoke:

11. `simple_bfts` smoke run writes no clean-room files and imports no clean-room module.
12. Prompt-layer gates green after adding `rqgm/clean_room_generator.md` (hash row,
    snapshot goldens, Gate 10, `_EXPECTED_KEYS` bump).

## 10. Risks

- **Detective-layer evasion.** A shingle screen misses paraphrased contamination; k=8 exact
  matching is a floor, not a ceiling. Accepted for v1 because Layer A makes the sanctioned
  path structurally clean; the screen guards against assembler bugs and out-of-band edits.
  Recorded as an open hardening item (semantic-similarity screens would need an LLM and are
  deliberately excluded from the deterministic kernel).
- **False positives.** Short constitutional boilerplate could collide if the allowlist is
  incomplete; mitigation: allowlist = the full allowed-input corpus, and `shingle_k`
  configurable. A blocked-but-clean candidate costs one epoch (fallback covers the role).
- **Successor regression.** A clean-room prompt that cannot see its predecessor may perform
  worse initially. Mitigated by the Task 07 gauntlet (replay + anchor + shadow before
  probationary activation) and by the baseline fallback — a bad candidate never reaches
  `active` untested.
- **Flat-filesystem bypass.** Any tool-bearing agent can read checkpoint files; if a future
  contributor implements generation as a ReAct rollout, Layer A collapses. Guarded by a test
  asserting the harness performs exactly one completion with no tool schema, and by D1 being
  written into the permanent developer guide at deletion time.
- **FailureSummary as a covert channel.** The compressor (LLM, Task 11) could smuggle attack
  text into `behavioral_requirements`. Mitigated by creation-time screening and the closed
  class vocabulary; residual risk noted for Task 13's `clean-room violation` failure
  injection to probe.
- **Budget starvation.** 1 generation/epoch means multiple simultaneous retirements queue
  for several epochs; fallback keeps roles staffed, but recovery latency is a measurable
  cost (Task 13 metric: recovery after selective erasure).

## 11. Completion criteria

This task is complete when all of the following hold:

1. **No-read-retired-prompt constraint defined** — the three-layer enforcement (constructive
   one-shot harness, `can_read_retired_prompt_text=false` capability denial via
   `validate_capability`, deterministic contamination screen) is specified with the kernel
   check signatures in §7, including the explicit kernel-reader exemption and the honest
   flat-filesystem limitation.
2. **Clean-room inputs defined** — the forbidden set (retired prompt text, few-shots,
   reasoning traces, raw attack text, defense text) and the allowed set (role spec, output
   schema, constitutional constraints, abstract failure summary, replay requirements, cost
   budget) are enumerated (§5.2), and enforced structurally by the closed
   `CleanRoomInputBundle` schema (`additionalProperties: false`, const-false forbidden
   flags) in §6.
3. **No instant activation defined** — clean-room candidates enter the Task 07 lifecycle at
   `status: candidate` with `generation_mode: clean_room`, and the transition rule that any
   lifecycle-skipping transition for a clean-room prompt is kernel-rejected is specified
   (§5.1, §7).
4. `CleanRoomGenerationRequest`, `CleanRoomInputBundle`, and the FailureSummary
   admissibility contract are drafted with envelope fields, status enums, and JSON-schema
   homes (§6).
5. The generation harness decision (one-shot in-process call; ReAct and MCP-tool
   alternatives rejected with reasons), timing (epoch-boundary window after
   `transition.apply`), budget cap, and role-fallback rule are documented (§5.4–§5.6).
6. Persistence, META_FILES registration, mode gating, VirSci independence, and the test
   list (§8–§9) are reviewed by the Task 04/07/09 plan owners for interface consistency
   (recorded in INDEX.md).

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

Task-specific criteria (all additionally required):

- `CleanRoomGenerationRequest` schema is implemented (JSON schema + dataclass + tests).
- Retired-prompt access is denied by the ConstitutionalKernel (capability check implemented
  and tested; violation events logged).
- Clean-room candidates are never instantly active (lifecycle entry at `candidate` enforced
  by RegistryTransitionEngine + kernel transition validation, with a test).
- A contamination-free check exists (deterministic screen implemented, run pre- and
  post-generation, blocking at admission, with planted-contamination tests).
- Tests added (the §9 suite, including the `simple_bfts` no-op regression).
- The contamination-free policy and the three-layer enforcement design have been moved to
  the permanent schema reference / developer guide (Task 08 content in the architecture
  overview's governance section).

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

Task-specific items:

- [ ] `clean_room_request.schema.json` / `clean_room_bundle.schema.json` ship beside
      `node_report.schema.json` and load via `ari.schemas.load`.
- [ ] `rqgm_cleanroom.jsonl` is registered in `META_FILES`/`_TRACE_FILES` and the
      node-report blocklists (test passing).
- [ ] `rqgm/clean_room_generator.md` passes all four prompt snapshot layers.
- [ ] The forbidden/allowed input split and the kernel-reader exemption are documented in
      the permanent constitution/governance doc.
- [ ] The one-shot-harness decision (D1) and MCP-retry rationale (D2) are captured as code
      comments or developer-guide text.
- [ ] A `simple_bfts` run demonstrably produces no clean-room files.
