# Task 11: Meta-agent Evolution

> **Status**: planned · **Depends on**: 00, 07, 08, 09 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

Tasks 07 and 08 introduce components that *produce* prompt candidates: the PromptMutator
(mutates existing PromptSpecs), the CleanRoomPromptGenerator (regenerates retired roles from
abstract failure summaries), plus their supporting selectors (ReplayCaseSelector,
FailureSummaryCompressor). These meta-agents are themselves prompt-defined and therefore
degrade, drift, and game their objectives like any other prompt-defined component — a stale
PromptMutator that produces near-copies, or a ReplayCaseSelector that cherry-picks easy cases,
silently corrupts the entire evolution pipeline.

This task makes the meta layer (Layer 2) an evolution target **under strictly narrower
authority than the institutional layer**. The core danger is that meta-evolution is
self-referential: a component that writes the components that write the components. Without a
hard authority boundary, meta-evolution is an unaudited path to self-modification — exactly
what the Gödel-machine literature warns against and what the Constitutional design exists to
prevent. The design principle (SPEC, global invariant 18) is:

> Governance agents may evolve, but their authority cannot expand.

This task extends that invariant to the meta tier — per the SPEC's Task 11 intent, meta
agents likewise may evolve, but their **authority cannot expand**.

Concretely this task delivers: (a) the `tier` field and capability flags on ComponentRegistry
entries; (b) the meta-agent authority matrix and its deterministic enforcement via
ConstitutionalKernel; (c) the rule that every meta-agent output is a *candidate*, never an
activation; (d) sandbox/shadow evaluation for meta-agent candidates; (e) a constitutional cap
on the one existing ungoverned meta-level channel in ARI today (`make_metric_spec` rewriting
evaluator weights mid-run).

## 2. Scope

- Define the three-tier model on ComponentRegistry (Task 02 schema): `fixed`,
  `institutional`, `meta`, with per-entry capability flags.
- Define the meta-agent authority matrix (MAY / MAY-NOT) and map every MAY-NOT to a
  deterministic ConstitutionalKernel check (Task 04 `validate_capability` /
  `validate_role_separation` extensions).
- Define `MetaAgentOutputRecord` and the invariant that all meta outputs enter the system as
  candidates routed through the Task 07/08 candidate pipelines and the Task 09
  RegistryTransitionEngine — never as direct state changes.
- Define which meta components evolve in v1: **PromptMutator, CleanRoomPromptGenerator,
  ReplayCaseSelector, FailureSummaryCompressor** (the SPEC's evolving set). The other Layer-2
  components (PolicyMutator, CandidateSelector, AnchorCaseSelector, PromptDistiller) are
  registered with `tier: meta` but frozen (no candidates generated for them) in v1.
- Design sandbox evaluation (offline replay of historical meta-tasks) and shadow evaluation
  (parallel no-effect execution at epoch boundaries) for meta candidates, with fitness derived
  deterministically from the downstream fate of previously produced candidates.
- Design read-only registry views and a sandboxed invocation harness so meta-agents are
  *structurally* unable to reach registries, the audit log, the hash registry, or retired
  prompt text (defense in depth: no handle + capability check + access guard).
- Design the constitutional cap on `make_metric_spec` under `ari_rqgm` mode (open question
  assigned to this task by Task 00 / the shared map): a node agent must not be able to rewrite
  the epoch-frozen weight regime.
- Decide (and record) the position on a duck-typed `MCPClient` Protocol for type-checkable
  governance/sandbox proxies.
- Config surface: `rqgm.meta_evolution.*` budgets and switches, all inert unless
  `ari.mode: ari_rqgm`.

## 3. Non-goals

- No implementation in this task plan (design only; implementation happens when the task is
  executed, gated by its completion criteria).
- Not the PromptSpec schema, mutation operators, or the candidate lifecycle — Task 07.
- Not clean-room input filtering or the retired-prompt access-guard mechanics — Task 08
  (this task *consumes* that guard and adds the meta-tier capability flags on top).
- Not the transition table or epoch-boundary transaction — Task 09 (meta candidates ride the
  same `EpochTransition`; this task only forbids meta-agents from touching it).
- Not the GovernanceOrchestrator facade or its submodule structure — Task 05 (the meta
  evolution step is invoked from its epoch-boundary sequence; only the meta-specific step is
  designed here).
- Not ConstitutionalKernel internals — Task 04 (this task specifies the *inputs* to
  `validate_capability`: the flag vocabulary and the authority-non-expansion rule).
- No evolution of the fixed tier, ever (global invariants 16–17).
- No change to `simple_bfts` behavior; no new CLI surface; nothing enabled by default.
- VirSci: entirely unrelated to this task; meta-evolution must work identically with
  `proposal_router.generators.virsci.enabled: false`.

## 4. Existing ARI touchpoints

All paths repo-relative; verified to exist on branch `RQGM`.

| Touchpoint | Relevance to this task |
|---|---|
| `ari-core/ari/prompts/registry.py` — `PromptEntry`, `PromptRegistry` | Proto-PromptSpec (key, path, `version_id = sha256[:12]`, placeholders). Meta-agent PromptSpecs extend this per Task 07; the meta tier adds registry-entry fields, not a new hash scheme. Kept out of `ari.public.*` (no contract-snapshot churn). |
| `ari-core/ari/prompts/_provenance.py` — `record_prompt_use`, `hash12`, `PromptUseRecord` | Every meta-agent LLM call must log here. The reserved always-`None` fields `prompt_version` / `prompt_registry_version` carry epoch id / registry version with zero schema break. |
| `ari-core/ari/prompts/_loader.py` — `FilesystemPromptLoader(base=...)` | Alternative-root loading is how sandbox/shadow meta candidates are loaded from a checkpoint-scoped candidate directory without touching committed templates. |
| `ari-core/ari/agent/react_driver.py` — `run_react(..., sandbox=, allow_paths=, final_tool=)` | The existing sandboxed, path-validated, final-tool-terminated agent harness. The meta-agent sandbox harness is a thin wrapper over this (see §5.5); `_validate_paths_in_args` is the enforcement precedent for keeping retired prompt text out of reach. |
| `ari-core/ari/mcp/client.py` — `MCPClient.call_tool`, `_tool_registry`, `to_claude_mcp_config` | Single choke point for every skill invocation. The meta sandbox passes a filtering proxy with the same duck-type; note callers also read `mcp._COW_TOOLS` (see `tool_manager`). No `MCPClient` Protocol exists yet (`ari-core/ari/protocols/__init__.py` explicitly defers it) — decision in §5.7. |
| `ari-core/ari/agent/tool_manager.py` — `_INTERNAL_MCP_TOOLS`, `available_tools_openai(suppress=...)` | Existing precedent for tools an LLM must never call (`_set_current_node`). Meta-control tools (candidate submission, registry views) get the same suppression treatment for object-level agents. |
| `ari-core/ari/agent/loop.py` — `make_metric_spec` handler (~line 1178) reassigning `self.evaluator.metric_spec` | The one ungoverned meta-level channel in ARI today: a node agent self-determines evaluation criteria mid-run. §5.8 caps it under `ari_rqgm`. |
| `ari-core/ari/evaluator/llm_evaluator.py` — `_resolve_axis_weights` | MetricSpec weights currently outrank constructor/AxisDef/default weights. The cap in §5.8 inserts the epoch-frozen weight policy above MetricSpec under `ari_rqgm`. |
| `ari-core/ari/orchestrator/lineage_decision.py` — deterministic-rule-first + LLM-with-total-fallback + append-only JSONL | The behavioral template for the meta-evolution step: config-gated, budgeted, deterministic checks first, best-effort, audited. |
| `ari-core/ari/cli/bfts_loop.py` — epoch-boundary attachment point (head of outer loop; lineage hook block as hook template) | The meta-evolution step runs inside the Task 05 epoch-boundary sequence hooked here; it must inherit the fail-open, never-kill-the-run discipline of the existing hooks. |
| `ari-core/ari/paths.py` — `PathManager.META_FILES`, `_TRACE_FILES` | New checkpoint files (`meta_agent_outputs.jsonl`, sandbox result files, candidate prompt dumps) must be registered here or they contaminate node work dirs and `files_changed`. |
| `ari-core/ari/checkpoint.py` + `ari-core/ari/protocols/stores.py` | Snapshot-store precedent (`save_prompt_versions_json`) for any derived rollup of meta outputs; new store methods follow the subtask-044 playbook. |
| `ari-core/ari/orchestrator/node_report/builder.py` — `_INTERNAL_JSON_NAMES` | New internal JSON artifacts must be classified as non-publishable, like `prompt_versions.json`. |
| `ari-core/ari/cost_tracker.py` — litellm callback, `set_default_metadata` | Meta-agent LLM calls get `phase="rqgm_meta"`, `skill=<role>` metadata for free cost attribution; never record cost manually. |
| `ari-core/ari/config/__init__.py` — `ARIConfig`, `load_config` filtering, env-override appliers | `rqgm.meta_evolution.*` lives inside the typed `RQGMConfig` block introduced by Task 01; `load_config` silently drops unknown top-level keys, so no separate top-level block. |
| `ari-core/ari/core.py` — `build_runtime` | Composition root: the MetaEvolutionCoordinator (§5.4) is constructed here only when `ari.mode == "ari_rqgm"`, following the `hpc_enabled` conditional-wiring precedent. |
| `scripts/check_prompts.py` + the four prompt snapshot layers (`ari-core/tests/test_prompt_registry.py` etc.) | Meta-agent role prompts are committed `.md` templates from day one; runtime-*generated* candidate prompts use the Task 07 Gate-10 carve-out (per-epoch dump under the checkpoint + `rendered_prompt_hash` provenance). |
| `ari-core/config/workflow.yaml` | Pinned 13-skill list; if meta-agents ship as an `ari-skill-rqgm` server, it must be added here with a governance phase string so `phase: none` keeps it unspawnable by default. |

## 5. Proposed design

### 5.1 Tier model

Every ComponentRegistry entry (Task 02) carries a mandatory `tier`:

| Tier | Members (examples) | Evolves? | Authority ceiling |
|---|---|---|---|
| `fixed` | ConstitutionalKernel, SchemaValidator, HashChecker, AccessGuard, FixedVerifier, MetricRecomputer, ClaimEvidenceGate, audit log, hash registry | Never (invariants 16–17) | N/A — not represented by prompts; flags all `false` and immutable |
| `institutional` | ProposalGenerator, ProposalRouter, Reviewer, Adversary, Defender, Judge, UtilityPolicy | Yes (Tasks 06/07/09) | May produce records that *influence* scores/decisions via adjudication; still cannot touch registries directly (invariant 10) |
| `meta` | PromptMutator, CleanRoomPromptGenerator, ReplayCaseSelector, FailureSummaryCompressor, PolicyMutator, CandidateSelector, AnchorCaseSelector, PromptDistiller | v1: the first four only | Strictly narrower than institutional: outputs are inert candidates with **zero** in-epoch effect on scoring, frontier, or governance verdicts |

Tier ordering for the kernel is `fixed > institutional > meta` in *trust*, and
`fixed ⊃ institutional ⊃ meta` in *authority*: a meta entry can never hold a capability an
institutional entry of the same role family is denied, and no evolving entry can hold a
fixed-layer capability.

### 5.2 Meta-agent authority matrix

MAY (the full, closed list — anything not listed is denied):

1. Generate candidate PromptSpecs for allowed target roles (PromptMutator).
2. Generate clean-room candidate PromptSpecs from a `CleanRoomGenerationRequest` (Task 08).
3. Select replay-case *candidates* from the AdversarialReplayPool (ReplayCaseSelector) — the
   selection is a recommendation consumed by GovernanceOrchestrator, not a binding set.
4. Compress validated failure evidence into abstract `FailureSummary` records
   (FailureSummaryCompressor), subject to the Task 08 contamination rules.
5. Attach an `expected_improvement` free-text rationale to any candidate it produces.

MAY NOT (each row maps to a deterministic kernel check; see §5.6):

| # | Prohibition | Enforcing check |
|---|---|---|
| M1 | Activate its own (or any) candidates | `validate_capability` (`can_activate_candidates=false`) + Task 09 rule that only RegistryTransitionEngine applies transitions |
| M2 | Modify PromptRegistry / ComponentRegistry directly | `validate_capability` (`can_modify_registry=false`); registries are passed as read-only views (§5.5) |
| M3 | Change ConstitutionalKernel, fixed verifier, metric recomputer, claim-evidence gate | fixed-tier entries are not valid `allowed_targets`; kernel rejects any candidate whose `role` is a fixed-tier role |
| M4 | Write to or rewrite the ImmutableAuditLog | append-only integrity check (Task 04); meta outputs are appended *about* meta-agents by the coordinator, never *by* them |
| M5 | Change the hash registry / prompt-hash scheme | hash verification is fixed-tier; no capability flag grants it |
| M6 | Loosen clean-room constraints (e.g. rewrite `allowed_inputs`) | `CleanRoomGenerationRequest` is authored by RegistryTransitionEngine (Task 09); kernel rejects requests whose `allowed_inputs` differ from the constitutional template |
| M7 | Read retired prompt text or retired few-shots | `can_read_retired_prompt_text=false` + Task 08 access guard + filtered sandbox inputs (§5.5) |
| M8 | Alter the epoch-boundary transaction or trigger transitions mid-epoch | transitions accepted only from RegistryTransitionEngine inside the boundary transaction (invariants 10–11) |
| M9 | Expand its own or a successor's capability flags | authority-non-expansion check (§5.6) |
| M10 | File impeachment motions or author EvidenceBundles | role-separation check (Task 04/05); meta outputs are observations at most |

> **Given a permanent home, 2026-08-22.** The MAY list and the M1–M10 MAY-NOT
> matrix are no longer carried only here. Both are reproduced — each MAY-NOT row
> against the enforcement point that actually ships (`meta_rules.py`'s
> `META_HARD_DENIED_FLAGS` / `DEFAULT_FORBIDDEN_TARGETS`, and the named kernel
> codes `CK-ROL-901`, `CK-AUD-00*`, `CK-CLN-001`, `CK-ACC-002`, `CK-EPO-002`,
> `CK-REG-004`, `CK-REG-101`, `CK-ROL-001/002`) — in
> [`docs/concepts/rqgm_architecture.md`, "Meta-tier authority"](../../concepts/rqgm_architecture.md#meta-tier-authority),
> in all three languages
> ([ja](../../ja/concepts/rqgm_architecture.md#メタ層の権限) ·
> [zh](../../zh/concepts/rqgm_architecture.md#元层权限)); the tier model of §5.1
> was already carried by that page's "The three layers", and invariant 8 now
> points at the matrix instead of paraphrasing four of its rows. The permanent
> page also states the honest limit these rows do not carry on their own: the
> checks are application-level inside one process, not OS-level containment.
> Nothing above is amended.

### 5.3 Every meta output is a candidate

`MetaAgentOutputRecord` (§6.2) is the *only* artifact a meta-agent produces. Routing:

- PromptSpec candidates (mutation or clean-room) → the Task 07 `PromptCandidate` intake with
  `generation_mode: "mutation" | "clean_room"` and `produced_by: <meta component_id>`. They
  enter the standard lifecycle (candidate → static validation → constitutional validation →
  schema dry-run → replay → anchor → shadow → probationary_active → active) with **no
  shortcuts**; the meta origin is provenance, not privilege.
- Replay-case selections → a `replay_case_recommendation` list consumed by
  GovernanceOrchestrator's ReplayBoard (Task 05), which may ignore it; the constitutionally
  mandated minimum replay set (Task 09 retirement cases) is always unioned in, so a
  cherry-picking selector cannot suppress mandatory cases.
- Failure summaries → `FailureSummary` records validated by the Task 08 contamination-free
  check before any clean-room use.

Nothing in this flow mutates any registry, score, frontier entry, or governance verdict
within the epoch. A meta-agent whose outputs are all rejected has simply wasted its budget.

### 5.4 Where meta-evolution runs: MetaEvolutionCoordinator

A small, non-evolving coordinator (constructed in `build_runtime` under `ari_rqgm` only)
invoked once per epoch boundary, after `GovernanceOrchestrator.audit_epoch` and before
`RegistryTransitionEngine.resolve_transition` (SPEC core-algorithm steps 12→13):

```python
class MetaEvolutionCoordinator:
    """Non-evolving driver of the meta tier. Fixed-tier trust, but performs no
    judgment itself: it invokes meta-agents in sandboxes, records their outputs,
    and forwards candidates to the Task 07/08 intakes."""

    def run_epoch_boundary_step(
        self, *, epoch_state, governance_report,
        prompt_registry_view, component_registry_view,   # read-only views
        replay_pool_view, budget,
    ) -> MetaEvolutionResult:
        results = []
        for meta in self._active_meta_agents(component_registry_view):
            if not budget.allows(meta.role):
                continue
            inputs = self._assemble_filtered_inputs(meta, governance_report,
                                                    replay_pool_view)   # M7 filter
            output = self._invoke_sandboxed(meta, inputs)               # §5.5
            record = self._to_output_record(meta, output)               # schema §6.2
            self._kernel.validate_record_schema(record)
            self._kernel.validate_capability(meta, "emit_candidate", record)
            self._audit_log.append(record)                              # coordinator appends, not the agent
            results.append(record)
        return MetaEvolutionResult(records=results,
                                   candidates=self._route_candidates(results))
```

Discipline inherited from the lineage hook (`ari-core/ari/cli/bfts_loop.py`): config-gated,
budget-capped, wrapped in best-effort try/except (a meta-evolution failure degrades to "no
candidates this epoch", never kills the run), every outcome appended to the audit log.

### 5.5 Structural containment: read-only views and the sandbox harness

Defense in depth, three independent layers:

1. **No handle.** Meta-agents never receive registry objects, the audit log, stores, or the
   raw checkpoint dir. The coordinator passes (a) frozen read-only dataclass views
   (`PromptRegistryView`, `ComponentRegistryView`) that expose status/hash/role metadata of
   non-retired entries only — retired entries appear as `{prompt_id, role, status:"retired"}`
   stubs with **no text, no path**; and (b) pre-filtered input bundles (abstract failure
   summaries, role specs, output schemas) assembled per the Task 08 allowed-inputs table.
2. **Capability check.** Every action the coordinator performs *on behalf of* a meta-agent
   passes `ConstitutionalKernel.validate_capability(actor, action, resource)` against the
   entry's flags (§6.1). Actions are a closed vocabulary:
   `{emit_candidate, emit_replay_recommendation, emit_failure_summary}`.
3. **Sandboxed execution.** Agentic meta rollouts run through a wrapper over
   `ari-core/ari/agent/react_driver.py:run_react` with: `sandbox=` a scratch dir containing
   only the filtered input bundle; `allow_paths=` restricted to that dir (existing
   `_validate_paths_in_args` enforcement); a phase-filtered tool list from a
   **MetaSandboxMCPProxy** (same duck-type as `MCPClient`: `list_tools`, `call_tool`,
   `close_all`, `to_claude_mcp_config`, `_COW_TOOLS`) that exposes only read-only helper
   tools and the synthesized `final_tool` (`submit_meta_output`); and no memory-write tools
   (proxy returns `{"error": ...}` for anything outside its allowlist, preserving the exact
   `{"result"}|{"error"}` envelope). One-shot (non-agentic) meta calls use a direct
   `LLMClient.complete` with `phase="rqgm_meta"` metadata and no tools at all — preferred
   when the role does not need iteration.

The retired-prompt-text prohibition is therefore enforced even against a *malicious* meta
prompt: the text is not in the sandbox, the proxy has no tool that reads it, and the Task 08
access guard denies the path if a tool is tricked into trying.

### 5.6 Meta-agents as evolution targets: stricter lifecycle

Meta components evolve through the *same* Task 07 lifecycle and Task 09 transition table,
with four additional constraints:

1. **Authority non-expansion (invariant 18, deterministic).** A candidate for a meta role is
   admissible only if its registry entry's capability set is a subset of the incumbent's:
   for every boolean flag, `candidate[flag] → incumbent[flag]`; `allowed_targets(candidate) ⊆
   allowed_targets(incumbent)`; `forbidden_targets(candidate) ⊇ forbidden_targets(incumbent)`.
   Pure set arithmetic in the kernel — no judgment involved. (Narrowing is allowed; widening
   requires a human-authored constitution change, out of scope for evolution.)
2. **Who mutates the mutator.** PromptMutator candidates targeting the `prompt_mutator` role
   are *not* produced by the incumbent PromptMutator (self-modification) — they are produced
   only by the CleanRoomPromptGenerator from role spec + failure summaries, or authored by
   humans. Symmetrically, CleanRoomPromptGenerator successors are produced by the
   PromptMutator (from the *active*, non-retired incumbent) or humans. This cross-generation
   rule breaks the direct self-reference loop; the kernel rejects
   `produced_by.role == target_role` for meta targets.
3. **Tighter budgets and longer probation.** At most `max_meta_candidates_per_epoch: 1`
   in total across meta roles (config §6.4); meta candidates require both sandbox and shadow
   evaluation to pass and spend ≥2 epochs in `shadow` before `probationary_active`
   (institutional components may need only 1 per Task 07/09 policy).
4. **Downstream-fate fitness (deterministic).** A meta candidate/incumbent is scored by the
   recorded fate of artifacts it produced in prior epochs, aggregated from registry history
   and the audit log — no LLM in the loop:
   - PromptMutator / CleanRoomPromptGenerator: of candidates produced, the fraction passing
     static+constitutional validation; fraction passing replay/anchor; promotion rate;
     post-promotion sanction/retirement rate of its promotees (negative signal).
   - ReplayCaseSelector: replay sets recommended vs. the cases that later mattered
     (validated attacks / retirements that its selected cases did or did not cover).
   - FailureSummaryCompressor: fraction of its summaries passing the Task 08 contamination
     check; downstream clean-room candidate validation rate.

### 5.7 Sandbox and shadow evaluation of meta candidates

- **Sandbox evaluation (offline, epoch-boundary, cached):** replay N historical meta-tasks
  (frozen input bundles archived from earlier epochs: governance reports, failure summaries,
  clean-room requests) through the candidate. Deterministic pass criteria: outputs
  schema-valid; declared constitutional constraints preserved in generated PromptSpecs;
  no forbidden-input references (string/hash scan against the Task 08 contamination list);
  budget respected. Results recorded as `MetaCandidateEvaluation` (§6.3). Same cache-key
  discipline as Task 12 (`artifact_hash + prompt_hash + role + epoch_id + input_context_hash
  + output_schema_hash`).
- **Shadow evaluation (live, no effect):** for up to `max_shadow_epochs`, the candidate runs
  alongside the incumbent on the *same* inputs at the epoch boundary; its outputs are
  recorded with `shadow: true` and routed nowhere. Comparison of incumbent-vs-shadow outputs
  becomes a `ComparisonObservation` for the Task 09 promotion decision. Shadow calls count
  against `rqgm.shadow.max_shadow_calls_per_epoch` (Task 12).
- **MCPClient Protocol decision:** introduce a minimal duck-typed `MCPToolCaller` Protocol in
  `ari-core/ari/protocols/` (methods: `list_tools`, `call_tool`, `close_all`,
  `to_claude_mcp_config`; attribute `_COW_TOOLS`) so `MetaSandboxMCPProxy` and future
  governance proxies are type-checkable. This fulfills the deferral noted in
  `ari-core/ari/protocols/__init__.py` without changing any call site (structural typing;
  duck-type assertions per the contract-snapshot robustness convention). If Task 05 lands a
  governance proxy first, it owns the Protocol and this task reuses it.

### 5.8 Constitutional cap on `make_metric_spec` (prerequisite hardening)

Today (`ari-core/ari/agent/loop.py` ~line 1178) a node agent can call `make_metric_spec` and
overwrite `evaluator.metric_spec`; because `MetricSpec.axis_weights` outrank everything in
`LLMEvaluator._resolve_axis_weights`, a single node can rewrite the run's weight regime —
an ungoverned meta-level action. Under `ari_rqgm`:

- The epoch freeze (Task 02) pins `utility_policy` including axis weights. The
  `make_metric_spec` handler still updates `expected_metrics` / `expected_params` /
  `scoring_guide` / extractor (domain knowledge, harmless), but **axis_weights from a
  node-initiated MetricSpec are ignored** in favor of the epoch-frozen weights; the attempted
  override is appended to the audit log as an observation
  (`event: "metric_spec_weight_override_suppressed"`).
- Implementation sketch: an `enforce_epoch_weight_policy(metric_spec, epoch_state)` clamp
  applied at the single handler site in `loop.py` (or equivalently a weight-precedence
  change scoped to `ari_rqgm` in `_resolve_axis_weights`); the exact seam is chosen at
  implementation time for minimal diff.
- Under `simple_bfts`, behavior is byte-for-byte unchanged (weight precedence remains
  MetricSpec > ctor > AxisDef > defaults).

### 5.9 Prompt hygiene for meta roles

The four meta role prompts (mutator, clean-room generator, replay selector, compressor) are
committed `.md` templates under `ari-core/ari/prompts/` (or a governance skill's
`src/prompts/`), passing all four snapshot layers and `scripts/check_prompts.py` from day
one. Runtime-generated *candidate* prompts (the meta-agents' outputs) follow the Task 07
carve-out: dumped per-epoch under the checkpoint dir, registered in `META_FILES`, with
`rendered_prompt_hash` provenance via `record_prompt_use`.

## 6. Data structures / schema changes

### 6.1 ComponentRegistry entry: `tier` + capability flags (extends Task 02 schema)

```json
{
  "component_id": "prompt_mutator_v2",
  "role": "prompt_mutator",
  "tier": "meta",
  "status": "shadow",
  "prompt_hash": "a1b2c3d4e5f6",
  "epoch_id": "epoch_004",
  "allowed_targets": ["reviewer", "adversary"],
  "forbidden_targets": ["fixed_verifier", "audit_log", "prompt_registry",
                        "component_registry", "hash_registry",
                        "constitutional_kernel", "epoch_transition"],
  "can_modify_registry": false,
  "can_activate_candidates": false,
  "can_read_retired_prompt_text": false,
  "can_file_impeachment": false,
  "can_author_evidence_bundle": false,
  "can_emit_candidates": true,
  "can_emit_replay_recommendation": false,
  "can_emit_failure_summary": false,
  "max_outputs_per_epoch": 1
}
```

Rules: `tier ∈ {"fixed","institutional","meta"}` (closed vocabulary, JSON-schema enum);
for `tier: "meta"` the five `can_modify_registry` / `can_activate_candidates` /
`can_read_retired_prompt_text` / `can_file_impeachment` / `can_author_evidence_bundle` flags
MUST be `false` (schema-level `const: false` under a conditional — a meta entry with any of
them `true` is a schema violation, not merely a capability denial); `fixed`-tier entries have
all `can_*` flags `false` and are never valid transition subjects (Task 09). Flags default to
`false` — capability is opt-in, absence is denial.

### 6.2 `MetaAgentOutputRecord`

Carries the SPEC-mandated common envelope (`record_id, epoch_id, component_id, prompt_hash,
role, created_at, source_refs, status`) plus:

```json
{
  "record_id": "meta_out_000131",
  "epoch_id": "epoch_004",
  "component_id": "prompt_mutator_v2",
  "prompt_hash": "a1b2c3d4e5f6",
  "role": "prompt_mutator",
  "created_at": "2026-07-05T00:00:00Z",
  "source_refs": ["failure_summary_0007", "governance_report_epoch_004"],
  "status": "recorded",
  "output_kind": "prompt_candidate",
  "target_role": "reviewer",
  "candidate_ref": "reviewer_prompt_v5_candidate",
  "expected_improvement": "Reduce false-accept on unsupported novelty claims.",
  "shadow": false,
  "sandboxed": true,
  "input_bundle_hash": "sha256:...",
  "output_payload_hash": "sha256:..."
}
```

`output_kind ∈ {"prompt_candidate", "clean_room_candidate", "replay_case_recommendation",
"failure_summary"}` (closed). `created_at` is metadata only and never enters any hash (P2).
Storage: append-only `{ckpt}/rqgm_meta_outputs.jsonl` (registered in `META_FILES` /
`_TRACE_FILES` / node-report blocklists), modeled line-for-line on
`ari/prompts/_provenance.py` (lock, run-pin no-op, never raises); alternatively folded into
the shared `rqgm_audit.jsonl` if Task 02 consolidates — INDEX.md records whichever wins.

### 6.3 `MetaCandidateEvaluation`

```json
{
  "record_id": "meta_eval_00007",
  "epoch_id": "epoch_005",
  "candidate_component_id": "prompt_mutator_v3_candidate",
  "incumbent_component_id": "prompt_mutator_v2",
  "sandbox": {
    "cases_run": 6, "schema_valid_rate": 1.0,
    "constraint_preservation_rate": 1.0,
    "contamination_hits": 0, "budget_violations": 0, "passed": true
  },
  "shadow": {
    "epochs_observed": 2, "outputs_recorded": 2,
    "comparison_observation_refs": ["cmp_obs_0042", "cmp_obs_0051"]
  },
  "downstream_fate": {
    "candidates_produced": 3, "validation_pass_rate": 0.67,
    "promotion_rate": 0.33, "post_promotion_sanction_rate": 0.0
  },
  "authority_non_expansion_check": "pass"
}
```

Consumed by RegistryTransitionEngine (Task 09) as the `candidate_evaluations` input for meta
roles. All numeric fields are deterministic aggregations over registry history and audit-log
records.

### 6.4 Config sketch (inside the Task 01 `rqgm:` typed block; all inert under `simple_bfts`)

```yaml
rqgm:
  meta_evolution:
    enabled: true              # meaningful only when ari.mode == ari_rqgm
    evolving_roles: [prompt_mutator, clean_room_generator,
                     replay_case_selector, failure_summary_compressor]
    max_meta_candidates_per_epoch: 1
    sandbox:
      max_cases: 6
      use_cached_results: true
    shadow:
      min_epochs_before_probation: 2
    metric_spec_weight_cap: true   # §5.8; ignored under simple_bfts
```

## 7. API / class changes

All new symbols stay out of `ari.public.*` (no public-API contract-snapshot churn); no new
CLI commands or flags (zero CLI-surface change per the Task 01 stance).

- `ari/rqgm/meta_evolution.py` (new module; final location coordinated with Task 05's
  package layout): `MetaEvolutionCoordinator` (§5.4), `MetaEvolutionResult`,
  `MetaSandboxMCPProxy`, `PromptRegistryView` / `ComponentRegistryView` (frozen dataclasses),
  `assemble_filtered_inputs(...)`.
- `ConstitutionalKernel.validate_capability(actor, action, resource)` (Task 04 signature):
  this task specifies its flag vocabulary (§6.1), the closed action vocabulary (§5.5), and
  adds `validate_authority_non_expansion(candidate_entry, incumbent_entry) -> None | Violation`
  (pure set arithmetic, §5.6.1) and the cross-generation rule check (§5.6.2).
- `RegistryTransitionEngine` (Task 09): accepts `MetaCandidateEvaluation` for meta roles; no
  interface change — meta candidates ride the existing `candidate_evaluations` parameter.
- `ari/protocols/`: new `MCPToolCaller` Protocol (§5.7) — additive, structural, no call-site
  changes; documented as fulfilling the deferral note in `ari-core/ari/protocols/__init__.py`.
- `ari/agent/loop.py`: the `make_metric_spec` handler gains the `ari_rqgm`-gated weight clamp
  (§5.8); one function, mode-checked, no behavior change under `simple_bfts`.
- `ari/checkpoint.py`: optional `save_meta_outputs_rollup` store method + module shim if a
  derived snapshot is wanted (JSONL-is-truth, snapshot-derived, per repo precedent).
- `build_runtime` (`ari-core/ari/core.py`): conditional construction of the coordinator under
  `ari_rqgm`; returned via a wrapper object, never by extending the 6-tuple.

## 8. Migration / compatibility

- **`simple_bfts` (default): zero change.** No meta module is imported at run time, no meta
  file is created, `make_metric_spec` semantics are untouched, no prompt/template changes to
  the existing 11 keys. The existing `~2,700`-test ari-core suite (2674 collected on branch
  `RQGM` via `pytest ari-core/tests --collect-only -q`) must pass unmodified.
- **`ari_rqgm` with `meta_evolution.enabled: false`:** Tasks 02–10 machinery runs; the
  coordinator is constructed but `run_epoch_boundary_step` no-ops (records a single
  `meta_evolution_skipped` audit line). Meta-tier entries still exist in ComponentRegistry
  (frozen) so capability checks remain total.
- **Registry compatibility:** `tier` and the `can_*` flags are fields of the *new* Task 02
  ComponentRegistry — no legacy data to migrate. For robustness, readers treat a missing
  `tier` as `institutional` and missing flags as `false` (deny-by-default), so partially
  written registries from interrupted runs fail closed on capability and open on nothing.
- **Resume:** meta state is reconstructed from checkpoint-side files only
  (`rqgm_meta_outputs.jsonl` + the Task 02 epoch/registry files); nothing rides `tree.json`
  (contract-frozen) or in-memory BFTS state.
- **VirSci:** no interaction; meta-evolution never reads VirSci transcripts (they are not in
  any filtered input bundle) and works identically with `virsci.enabled: false`.
- **Mode switching:** meta-evolution runs only inside the epoch-boundary transaction; a
  mode switch at run start or epoch boundary (Task 01) trivially includes/excludes it, and
  mid-epoch switching remains forbidden.

## 9. Tests

Unit (ari-core/tests, following the tmp_path + `ARI_CHECKPOINT_DIR` isolation convention):

1. **Schema:** meta-tier entry with any hard-denied flag `true` fails JSON-schema validation;
   `tier` enum closed; flags default `false`; `MetaAgentOutputRecord` round-trips and its
   `output_kind` vocabulary is closed.
2. **Authority non-expansion:** subset/superset arithmetic — widening any flag, adding an
   `allowed_target`, or removing a `forbidden_target` in a candidate entry is rejected;
   narrowing passes; equal passes.
3. **Cross-generation rule:** a PromptMutator-produced candidate targeting `prompt_mutator`
   is rejected; clean-room-produced one is accepted.
4. **Capability enforcement:** `validate_capability` denies `emit_replay_recommendation` for
   an entry with that flag `false`; denies every action for `fixed` tier; unknown action
   string is a violation (closed vocabulary).
5. **No-handle containment:** registry views expose no text/path for retired entries; view
   dataclasses are frozen (mutation raises); `assemble_filtered_inputs` output for a
   clean-room task contains no retired-prompt bytes (hash-scan assertion, reusing the Task 08
   contamination checker).
6. **Outputs are candidates:** after `run_epoch_boundary_step`, PromptRegistry/
   ComponentRegistry snapshots are byte-identical; produced candidates sit in the Task 07
   intake with `status: candidate`; audit log gained exactly the expected records.
7. **Sandbox proxy:** `MetaSandboxMCPProxy` satisfies `MCPToolCaller` structurally
   (duck-type assertions, not isinstance); disallowed tool → `{"error": ...}` envelope;
   allowed read-only tool passes through; path outside `allow_paths` rejected via the
   `run_react` validation.
8. **Sandbox evaluation determinism:** same frozen input bundles + same candidate →
   byte-identical `MetaCandidateEvaluation.sandbox` block (P2); cache hit on second run.
9. **Shadow no-effect:** shadow outputs recorded with `shadow: true`; frontier, registries,
   utility records, and transition inputs unchanged by their presence.
10. **`make_metric_spec` cap:** under `ari_rqgm`, node-initiated axis_weights are suppressed,
    epoch weights win in `_resolve_axis_weights`, and the suppression observation is logged;
    under `simple_bfts`, existing precedence tests
    (`test_llm_evaluator_axes.py::test_metric_spec_weights_override_constructor_weights`)
    still pass unchanged.
11. **Budget:** `max_meta_candidates_per_epoch: 1` enforced; second candidate attempt in the
    same epoch is skipped with an audit line, not an error.

Integration / regression / smoke:

12. **simple_bfts regression:** full existing suite green with this task's code merged and
    mode unset (proves inertness).
13. **ari_rqgm smoke:** two-epoch stub run (fake LLM) in which epoch 1 produces one mutator
    candidate, epoch 2 shadow-evaluates it; assert lifecycle states, audit trail, and that
    activation did not occur (candidate still non-active after two epochs — probation floor).
14. **META_FILES hygiene:** new filenames asserted registered (mirroring
    `test_prompt_provenance.py::test_new_filenames_are_meta_files`); new files listed in
    `ari-core/tests/README.md` Contents (readme-sync gate).

## 10. Risks

- **Self-reference loopholes.** Even with the cross-generation rule, PromptMutator and
  CleanRoomPromptGenerator regenerate *each other* — a two-cycle. Mitigation: authority
  non-expansion is checked on every candidate regardless of producer, human review remains
  in the loop for meta promotions in early operation (Task 09 can require manual ack for
  `tier: meta` adoptions), and Task 13's failure injection includes "bad prompt mutator".
- **Fitness gaming.** A mutator maximizing promotion rate can emit conservative near-copies
  of incumbents. Mitigation: downstream-fate fitness includes post-promotion sanction rate
  (punishes useless promotees only weakly); accept this residual risk in v1 and revisit with
  a diversity/novelty term in Task 13's ablation (B8) rather than complicating v1.
- **Enforcement gap on the flat checkpoint filesystem.** Skills can read
  `ARI_CHECKPOINT_DIR` directly, so M7 ultimately depends on the Task 08 access-guard design
  plus the sandbox's filtered inputs. If Task 08's guard lands weaker than planned, the
  sandbox-copy approach (retired text simply absent from the sandbox) remains the effective
  barrier — documented as the load-bearing layer.
- **Complexity vs. value.** The meta tier is the most speculative RQGM layer; budgets are
  deliberately minimal (1 candidate/epoch) and `evolving_roles` is config-shrinkable to `[]`,
  making the whole layer effectively removable without code changes.
- **Cost.** Sandbox replays and shadow calls add LLM spend at epoch boundaries; bounded by
  §6.4 caps and counted under Task 12 budgets (`phase="rqgm_meta"` attribution makes
  overruns visible in `cost_trace.jsonl`).
- **Determinism (P2).** Meta-agent *generation* is inherently LLM-nondeterministic; the plan
  keeps every *judgment* about meta-agents (capability checks, non-expansion, sandbox pass
  criteria, fitness aggregation) deterministic, and all generated bytes are hash-logged. The
  scoping mirrors the Task 07 stance for institutional prompt evolution.
- **Retry re-execution.** MCP tools retry up to 3× with reconnect; meta tools must be
  idempotent (`record_id` derived from `input_bundle_hash`, duplicate appends deduplicated at
  read time) or run as one-shot in-process calls.

## 11. Completion criteria

This task is complete when all of the following are true (design-complete, concretizing the
SPEC's Task 11 criteria; implementation and tests are deletion criteria — §12):

1. **Meta-agent authority boundary defined.** The MAY / MAY-NOT matrix (§5.2) is fully
   specified, and every MAY-NOT row M1–M10 is mapped to a named deterministic enforcement
   point: a schema-level hard denial on meta-tier entries (§6.1),
   `ConstitutionalKernel.validate_capability` with the closed action vocabulary (§5.5), or a
   structural containment layer (read-only views, filtered inputs, sandbox harness — §5.5),
   with the failing-path tests enumerated in §9.
2. **No-direct-registry-modification defined.** `tier: meta` entries carry
   `can_modify_registry: false` / `can_activate_candidates: false` as schema constants
   (§6.1); the design guarantees registry state is unchanged by any meta-evolution step
   (byte-identity test specified in §9.6); the only path from a meta output to a registry
   change is Task 07/08 validation → Task 09 RegistryTransitionEngine → kernel-validated
   transition (§5.3).
3. **Meta-agent output treated as candidates, defined.** Every meta output is a
   `MetaAgentOutputRecord` (§6.2); PromptSpec outputs enter the Task 07 candidate intake with
   `status: candidate`; replay recommendations are non-binding and unioned with the mandatory
   set; no meta output has any in-epoch effect on scores, frontier, or verdicts (§5.3, with
   no-effect tests specified in §9.6 and §9.9).
4. **`tier` field and capability flags specified for ComponentRegistry.** The extension of
   Task 02's schema per §6.1 — closed tier vocabulary, deny-by-default flags, and the
   fixed/institutional/meta constraints — is written down and agreed with Task 02 as the
   owning plan.
5. **Sandbox and shadow evaluation designed.** The sandbox harness (filtered inputs +
   `run_react` sandbox + `MetaSandboxMCPProxy`) and the shadow no-effect path are specified
   (§5.5, §5.7), deterministic where required, budget-capped, and produce
   `MetaCandidateEvaluation` records (§6.3) consumed by Task 09.
6. **Authority non-expansion specified as a deterministic kernel check** (pure set
   arithmetic, §5.6.1), together with the cross-generation rule (§5.6.2) and their
   widen-rejected / narrow-accepted test cases (§9.2, §9.3).
7. **The `make_metric_spec` cap designed** (§5.8): `ari_rqgm`-gated via
   `metric_spec_weight_cap`, audited, with `simple_bfts` behavior explicitly stated as
   byte-for-byte unchanged.
8. **Checkpoint-file hygiene planned.** Every new checkpoint file is enumerated with its
   `META_FILES`/`_TRACE_FILES`/node-report-blocklist registration (§4, §6.2); no `~/.ari`
   writes; no new public-API/CLI/MCP contract-snapshot deltas beyond intentionally
   regenerated ones.

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

Task-specific criteria (all must also hold):

- The `tier` field (and capability flags) has been added to ComponentRegistry and is
  documented in the permanent schema reference.
- Meta-agents cannot modify PromptRegistry/ComponentRegistry — enforced by
  ConstitutionalKernel and proven by failing-path tests.
- Meta-agent outputs are treated as candidates end-to-end (intake → validation → transition),
  with no activation shortcut.
- Sandbox/shadow evaluation for meta candidates exists and its policy (budgets, probation
  floor, deterministic pass criteria) is recorded in the permanent developer guide /
  evaluation guide.
- The `make_metric_spec` cap (§5.8) is implemented behind `ari_rqgm`, audited, and
  `simple_bfts` behavior is regression-proven unchanged.
- All new checkpoint files are registered in `META_FILES`/`_TRACE_FILES`/node-report
  blocklists, with no `~/.ari` writes and no unintended contract-snapshot deltas.
- Tests for all of the above have been added and are green in CI (including at least one
  failing-path test per MAY-NOT row M1–M10).
- The authority matrix (§5.2) and the tier model (§5.1) have been migrated to the permanent
  architecture overview, so this plan is no longer the sole source of that specification.

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

- [ ] `tier` + capability flags are in the ComponentRegistry schema and the schema reference.
- [ ] Kernel denial tests exist for every MAY-NOT row (M1–M10).
- [ ] Authority non-expansion and cross-generation checks are implemented and tested.
- [ ] Sandbox + shadow evaluation paths run in the ari_rqgm smoke test.
- [ ] `make_metric_spec` cap is merged with a simple_bfts regression test proving unchanged
      default behavior.
- [ ] New checkpoint filenames are registered in `META_FILES`/`_TRACE_FILES` and covered by a
      hygiene test.
