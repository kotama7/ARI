# Task 12: Cost Control and Context Budget

> **Status**: planned · **Depends on**: 00, 01, 02, 03, 04, 05, 06 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

ARI-RQGM adds many new LLM-consuming actors (reviewer, adversary, defender, judge,
replay board, shadow evaluation, prompt mutator, clean-room generator, optional VirSci)
on top of the existing BFTS loop. Without explicit containment, governance cost grows
superlinearly with node count (every node × every actor × every epoch) and context grows
unboundedly (full transcripts, evidence bundles, and attack histories leaking into every
prompt). This task designs the two containment mechanisms:

1. **Cost control** — governance levels, event-driven escalation, per-epoch call budgets
   (replay / shadow / adversary / VirSci / prompt evolution), and a result cache keyed by
   a deterministic `cache_key`, all grounded in ARI's existing passive `cost_tracker`.
2. **Context budget** — role-specific context views so each actor sees only the minimal
   projection it needs; in particular, **BFTS receives ProposalSummaryView only, never
   full transcripts**.

The governing principle from the spec: *no always-on full governance; event-driven /
budget-aware*. All nodes get the fixed verifier + cheap validation; only some nodes get
adversary/defender/judge; replay / prompt evolution / governance audit run only at epoch
boundaries.

## 2. Scope

- Define the **governance level ladder** (L0–L3) and which actors run at each level.
- Define **deterministic escalation triggers** (frontier top-K, suspicious nodes, paper
  candidates, retirement candidates, adoption candidates, sudden score jumps, strong
  novelty claims, low reviewer confidence).
- Define the **budget config schema** under `rqgm:` (governance / shadow / replay /
  prompt_evolution) and the VirSci call budget under `proposal_router.generators.virsci`.
- Define the **BudgetLedger**: per-epoch counters and spend attribution built on
  `cost_tracker` (additive `epoch` metadata), plus where budget checks are enforced.
- Define the **`cache_key`** and the governance result cache (replay
  `use_cached_results: true` depends on it).
- Define **role-specific context views** (BFTS / Reviewer / Adversary / Judge /
  Governance / Paper writer) as deterministic projections, and the enforcement mechanism
  for the ProposalSummaryView-only constraint on BFTS.
- Define the **cost regression / budget check test** required by the spec.

## 3. Non-goals

- No implementation in this task (design only; implementation follows after the plan set
  is approved).
- Does not design the governance actors themselves (Task 05, Task 06) — only how often
  they may run and what they may see.
- Does not design ProposalRecord / ProposalSummaryView field-by-field (Task 03 owns the
  schemas); this task only fixes *which view reaches which role* and the size caps.
- Does not change `cost_tracker` from passive accounting into a hard killer of in-flight
  LLM calls. Enforcement is decision-point gating (skip/degrade the next governance
  action), never mid-call interruption.
- Does not add budget enforcement to `simple_bfts` mode. The only existing budget levers
  (`max_react_steps`, `timeout_per_node`, `max_total_nodes`, `rate_limit_per_run`)
  remain the sole limits there.
- Does not redesign the ≤4 worker clamp or MCP timeout tiers; it only documents how RQGM
  tools map onto the existing tiers.
- No CLI surface changes (config-only; avoids contract-snapshot churn per Task 01).

## 4. Existing ARI touchpoints

All paths repo-relative.

**Cost accounting (the foundation to extend, not replace)**
- `ari-core/ari/cost_tracker.py` — `CallRecord` (additive default-None fields already
  precedented: `component`, `op`, `backend`, `embedding_tokens`, `latency_ms`),
  `CostTracker.record` (appends `{ckpt}/cost_trace.jsonl`, rewrites
  `cost_summary.json` with totals/by_phase/by_model), `init` / `init_from_env` /
  `bootstrap_skill` (skill subprocesses), `set_default_metadata(**kwargs)`
  (process-wide metadata merged into every litellm call), `_litellm_success_handler`
  (global interception — skills included). **Passive: no budget enforcement exists.**
- `ari-core/ari/configs/model_prices.yaml` — externalized price table used for
  `estimated_cost_usd`.
- `ari-core/ari/llm/client.py` — `LLMClient.complete(..., node_id=, phase=, skill=)`
  forwards attribution metadata; governance actors must tag their calls the same way.

**Existing budget-like levers**
- `ari-core/ari/config/__init__.py` — `BFTSConfig.max_react_steps`, `timeout_per_node`,
  `max_parallel_nodes` (hard-clamped ≤4 in code), `max_total_nodes`, `max_depth`,
  `max_expansions_per_node`; `load_config` filters unknown top-level YAML keys, so the
  `rqgm:` block must ride the typed `RQGMConfig` field added by Task 01.
- `ari-core/ari/orchestrator/lineage_decision.py` — `LineageState.budget_remaining`
  (node-count budget, not dollars): the existing precedent for budget state threaded
  through lineage decisions.
- `ari-core/ari/cli/bfts_loop.py` — `_run_loop`: the outer-loop head is the epoch
  boundary (Task 01/05); the per-node lineage hook block — which enforces the
  `rate_limit_per_run` cap on lineage decisions (parsed from config in
  `ari-core/ari/cli/lineage.py`) — is the template for config-gated, rate-limited,
  best-effort governance hooks and the existing precedent for "governance actions are
  rate-limited per run". Budget checks for per-epoch governance live here (main
  thread, between batches).
- `ari-core/ari/mcp/client.py` — hardcoded timeout tiers `_SLOW_TOOLS` (1 h) /
  `_VERY_SLOW_TOOLS` (13 h) / default 300 s; `generate_ideas` is already a slow tool.
  Also `to_claude_mcp_config` (cli-shim exposure — currently leaks `_set_current_node`;
  governance tools must be excluded there too).
- `ari-skill-idea/src/server.py` — `generate_ideas` (the VirSci adapter seam, Task 03);
  exploration width already env-plumbed via `ARI_IDEA_VIRSCI_K` / `_TEAM_SIZE` /
  `_N_AUTHORS` / `_N_PAPERS` / `_MAX_TEAMS`. Today it runs exactly once per run at the
  root — the `max_calls_per_epoch` budget generalizes this.

**Context budget precedents (caps that already exist)**
- `ari-core/ari/agent/loop.py` — `build_working_context_messages` with per-field caps
  (`_CORE_FIELD_CAP=400`, `_IDEA_FIELD_CAP=1500`, `_ANCESTOR_SUMMARY_CAP=600`,
  `_SUPPLEMENT_CAP=400`), `_build_safe_window` (windowing with `_PINNED_USER_MARKERS`),
  tool-result truncation at 4000 chars. The established pattern: deterministic,
  read-only, capped context injection.
- `ari-core/ari/cli/lineage.py` — `_build_idea_ctx_for_expand` (~6000-char idea
  serialization): the *only* channel by which idea content reaches BFTS expansion today.
  This is precisely the "summary view only" behavior the ProposalSummaryView constraint
  formalizes.
- `ari-core/ari/evaluator/llm_evaluator.py` — judge evidence is already truncated
  (`str(artifacts)[:2000]`, `summary[:500]`, 120 s `evaluate_sync` timeout).
- `ari-core/ari/orchestrator/bfts_prompt_builder.py` — deterministic (P2) prompt-context
  serialization for BFTS; the summary-view renderer for BFTS follows its style.
- `ari-core/ari/agent/tool_manager.py` — `execute_tool_calls` is the single choke point
  for LLM-initiated tool calls (per-epoch tool budgets could hook here later; not v1).

**Hashing / caching / persistence primitives**
- `ari-core/ari/prompts/_provenance.py` — `hash12(text) = sha256[:12]`, the single
  prompt-hash scheme (`cache_key` reuses it; no second scheme). No wall-clock, git SHA,
  host, or absolute path ever enters a hash (P2).
- `ari-core/ari/paths.py` — `PathManager.META_FILES` and `_TRACE_FILES`: every new
  checkpoint-root file (budget ledger, governance cache) must be registered or it
  contaminates node work dirs and `node_report.files_changed`.
- `ari-core/ari/checkpoint.py` — the store-method + module-shim pattern for new snapshot
  files (`save_prompt_versions_json` precedent).
- `ari-core/ari/protocols/evaluator.py` — the `Evaluator` seam; governance-level
  dispatch wraps here or in `_run_loop`, never inside `LLMEvaluator`.
- `ari-core/config/workflow.yaml` — user-facing config; the `rqgm:` block lands here
  (checkpoint-first read discipline per Task 01).

## 5. Proposed design

### 5.1 Governance level ladder

Levels are per-node, assigned deterministically, and monotone (a higher level is a
superset of a lower one). Raw adversary attacks never touch BFTS scores at any level
(invariant 8); only Judge-validated attacks feed utility penalties (invariant 9).

| Level | Name | Runs | Cost profile |
|---|---|---|---|
| **L0** | fixed | Fixed verifier + cheap deterministic validation only: sterile gate, `validate_metrics`, `_FAKE_PATTERNS`, results.json merge, schema/hash checks (ConstitutionalKernel, Task 04). | Zero extra LLM calls. This is today's behavior and the floor for **every** node in both modes. |
| **L1** | reviewed | L0 + Reviewer review of the node's ProposalRecord/result. | 1 LLM call/node. `rqgm.governance.default_level: 1`. |
| **L2** | contested | L1 + Adversary attack + Defender response. | +2–3 calls/node. Trigger-driven only. |
| **L3** | adjudicated | L2 + Judge adjudication + EvidenceClerk bundle assembly. | +2 calls/node. Top-K / disputed / retirement-relevant only. |

Epoch-boundary work (replay evaluation, shadow evaluation, prompt evolution, clean-room
generation, `audit_epoch`) is **not** a node level — it is budgeted separately (§5.3)
and runs only in the epoch-boundary transaction (invariant 2; impeachment only at epoch
boundary per `impeachment_only_at_epoch_boundary: true`).

### 5.2 Escalation triggers (deterministic)

Level assignment is a pure function
`assign_level(node, frontier, epoch_state, cfg) -> Level` evaluated on the main thread
in `_run_loop` step (e) after evaluation, before governance actors run. Triggers (all
computable from existing `node.metrics` / frontier state, no LLM):

- **Frontier top-K** → L3 for the top `full_governance_only_on_top_k` (default 3) nodes
  by `_scientific_score` at the time of the epoch-boundary audit; ties broken by node id
  (lexicographic) for determinism.
- **Sudden score jump** → L2: `_scientific_score` exceeds parent's by
  `rqgm.adversarial.jump_threshold` (default 0.25). The key and its schema home are
  owned by Task 06 §7; this plan defines no separate `rqgm.governance.*` alias for it
  and only tunes the default value.
- **Low reviewer confidence** → L2→L3 escalation: ReviewRecord `confidence` below
  `low_confidence_threshold` (default 0.4) marks the node *disputed*.
- **Judge on disputed only** (`judge_on_disputed_only: true`): L3's Judge runs only when
  the Adversary attacked and the Defender contested (or reviewer confidence was low) —
  uncontested attacks lapse as observations.
- **Paper candidates** → L3: any node whose record enters the paper pipeline's
  top-ranked set (`verified_context` ranking).
- **Prompt retirement / adoption candidates** → their supporting evidence nodes get L3
  replay treatment at the epoch boundary (within the replay budget, §5.3).
- **Strong novelty claims** → L2: ProposalRecord `novelty_risks` non-empty or novelty
  axis ≥ `novelty_claim_threshold` (default 0.8).
- **Sterile / pruned nodes** → never escalate above L0 (no governance spend on nodes the
  fixed layer already killed).

All trigger evaluations and the resulting level are logged to the RQGM audit log
(Task 02) as `{node_id, epoch_id, level, triggers: [...]}` — deterministic and replayable.

### 5.3 Budget config

Typed as part of `RQGMConfig` (Task 01); defaults live in the Pydantic model so an
absent `rqgm:` block is inert. Spec-mandated shape, extended with explicit cost caps:

```yaml
rqgm:
  governance:
    default_level: 1                      # L0..L3; 0 disables all LLM governance
    full_governance_only_on_top_k: 3
    judge_on_disputed_only: true
    impeachment_only_at_epoch_boundary: true
    max_defender_calls_per_epoch: 12
    max_judge_calls_per_epoch: 8
    low_confidence_threshold: 0.4
    novelty_claim_threshold: 0.8
  # NOTE: the adversary call budget and the score-jump trigger are deliberately NOT
  # duplicated here. They live in the `rqgm.adversarial` block owned by Task 06 §7:
  #   rqgm.adversarial.max_adversary_calls_per_epoch: 24   (RawAttackRecord generation cap)
  #   rqgm.adversarial.jump_threshold: 0.25                (score-jump escalation trigger)
  # This plan owns the final tuning of those numeric defaults (per Task 06 §7), but the
  # keys have exactly one schema home — no `rqgm.governance.*` aliases exist.
  shadow:
    enabled: true
    sample_rate: 0.2                      # deterministic sampling, §5.6
    max_shadow_calls_per_epoch: 10
  replay:
    max_cases_per_epoch: 8
    max_cases_for_retirement: 12          # higher cap when a retirement is on the table
    use_cached_results: true              # consult the governance cache (§5.5) first
  prompt_evolution:
    max_candidates_per_role_per_epoch: 1
    max_total_candidates_per_epoch: 4
    max_clean_room_generations_per_epoch: 1
  budgets:
    max_governance_cost_usd_per_epoch: 0  # 0 = unlimited (attribution only)
    max_governance_tokens_per_epoch: 0    # 0 = unlimited
    on_exhausted: degrade                 # degrade | skip  (never crash; §5.4)

proposal_router:
  generators:
    virsci:
      enabled: false                      # default off (VirSci optionality, Task 03)
      mode: event_triggered
      max_calls_per_epoch: 2
      trigger_on: [initial_exploration, frontier_stagnation, major_pivot, paper_candidate]
```

Counters (`adversary_calls`, `defender_calls`, `judge_calls`, `shadow_calls`,
`replay_cases`, `virsci_calls`, `prompt_candidates` per role, `clean_room_generations`)
are persisted in `EpochState` (Task 02) so they survive `ari resume` — in-memory-only
counters would reset on resume and silently double budgets.

### 5.4 BudgetLedger and enforcement points

`cost_tracker` stays passive. A new read-side **`GovernanceBudgetManager`** owns
enforcement:

1. **Attribution (additive, both modes safe)**: add a default-None `epoch` field to
   `CallRecord` (the precedented additive-field pattern) and call
   `cost_tracker.set_default_metadata(epoch=epoch_id)` at each epoch start, so every
   litellm call — including MCP skill subprocesses via `bootstrap_skill` — is
   attributable to an epoch. Governance actors tag `phase="governance"` and
   `skill=<role>` (e.g. `skill="adversary"`), mirroring how `AgentLoop` tags
   `phase="react", skill="agent_loop"`. `cost_summary.json` then rolls up governance
   spend per phase for free.
2. **Counting**: `GovernanceBudgetManager.check(action) -> Verdict(allow | degrade | skip)`
   consults EpochState counters plus (when `budgets.max_governance_cost_usd_per_epoch > 0`)
   the CostTracker in-memory records filtered by `epoch` + `phase="governance"`.
3. **Enforcement points** (decision-point gating, never mid-call):
   - **Per-node governance** — in `_run_loop` step (e), before invoking
     reviewer/adversary/defender/judge for a node: exceeded per-role epoch cap (the
     adversary cap is `rqgm.adversarial.max_adversary_calls_per_epoch` from Task 06;
     defender/judge caps are `rqgm.governance.*`) ⇒ the
     node's effective level is capped below the actor's level (`on_exhausted: degrade`)
     or the single action is skipped (`skip`). Both outcomes are audit-logged.
   - **Epoch boundary** — inside `audit_epoch` (Task 05): replay case selection is
     truncated to `max_cases_per_epoch` (or `max_cases_for_retirement` when a
     RetirementEvent is under consideration); shadow evaluation stops at
     `max_shadow_calls_per_epoch`; prompt-evolution candidate generation stops at the
     per-role/total caps; clean-room generation at its cap.
   - **ProposalRouter** — before dispatching to `VirSciAdapter`: `virsci_calls`
     counter ≥ `max_calls_per_epoch` ⇒ route to a cheaper generator. VirSci is also
     called only on `trigger_on` events; a budget-denied VirSci call is logged and the
     router silently falls back (degrade-never-block, matching the idea skill's
     existing tiers).
4. **Failure posture**: budget exhaustion **degrades** governance; it never fails a
   node, never blocks the BFTS loop, and never raises (repo-wide "hooks never kill the
   run" discipline). The one deliberate asymmetry: L0 fixed checks are **not**
   budgetable — the constitutional floor always runs.

Node-agent budgets (`max_react_steps`, `timeout_per_node`) are untouched; RQGM budgets
apply only to governance-side calls.

### 5.5 cache_key and the governance result cache

Replay evaluation (`use_cached_results: true`) and repeated governance evaluations of
the same artifact must not re-pay LLM cost. Spec-fixed composition:

```
cache_key = H(
    artifact_hash        # sha256 of the evaluated artifact bytes (node_report file-hash scheme)
  + prompt_hash          # hash12 (sha256[:12]) of the actor's PromptSpec template — existing scheme
  + role                 # "reviewer" | "adversary" | "defender" | "judge" | ...
  + epoch_id             # e.g. "epoch_004" — epoch-local fixed-evaluator guarantee
  + input_context_hash   # sha256 of the canonical JSON of the exact context view given to the actor
  + output_schema_hash   # sha256 of the canonical JSON of the actor's output_schema (PromptSpec.spec.output_schema)
)
```

- `H` = `sha256(...)[:16]` over the `"\x1f"`-joined components (record-separator join
  prevents ambiguity; 16 hex chars matches the EAR artifact-id precedent).
- **Canonical JSON** = `json.dumps(obj, sort_keys=True, ensure_ascii=False,
  separators=(",", ":"))` — no wall-clock, no host, no absolute paths (P2).
- `epoch_id` inclusion is deliberate: a cached judgment is valid only within the epoch
  whose active prompt set produced it. Replay across epochs *with the same prompt_hash
  and inputs* still hits, because a candidate prompt replayed against historical cases
  carries the candidate's own `prompt_hash` — cross-epoch replay of the *same*
  (prompt, case) pair is the one sanctioned exception: the replay path may look up with
  the **case's original epoch_id** recorded in the AdversarialReplayCase, which is what
  makes `use_cached_results` effective. This rule is part of the schema (§6.2).
- **Store**: `{ckpt}/rqgm_governance_cache.jsonl` — append-only JSONL (lock, run-pin
  no-op, never raises; modeled on `record_prompt_use`), loaded into an in-memory
  `{cache_key: record}` index at run/resume start. Registered in
  `PathManager.META_FILES` + `_TRACE_FILES` + node-report blocklists. Absence of the
  file = empty cache, never an error.
- Cache entries are never invalidated in place; a retired prompt's entries simply stop
  being addressable (its `prompt_hash` never recurs in a lookup) — consistent with
  selective erasure's no-physical-deletion rule (invariant 13).

### 5.6 Deterministic shadow sampling

`shadow.sample_rate: 0.2` must not introduce wall-clock randomness (P2). Sampling is
hash-based: shadow-evaluate node `n` iff
`int(sha256(f"{run_id}:{epoch_id}:{n.id}:shadow").hexdigest(), 16) % 10_000 <
sample_rate * 10_000`, then truncate to `max_shadow_calls_per_epoch` in node-id order.
Same trick as the escalation tie-break: reproducible given the checkpoint, no RNG state
to persist.

### 5.7 Role-specific context views

Each governance actor receives a **view** — a deterministic, capped projection built by
pure functions in a new `ari-core/ari/rqgm/context_views.py` (final module path decided
at implementation; follows `bfts_prompt_builder.py` style: LLM-free, byte-deterministic,
unit-testable). Spec-fixed visibility matrix:

| Role | Sees | Explicitly never sees |
|---|---|---|
| **BFTS** (select/expand) | `ProposalSummaryView` only: title, short description, hypothesis, minimal experiment plan, success metric, novelty risks, expected artifacts, dissent summary | Full transcripts, agent discussion logs, raw proposal lists, attack/defense texts, evidence bundles |
| **Reviewer** | Proposal + evidence plan (`ProposalRecord` core + `node_report` refs) | Other reviewers' outputs (same-role isolation), raw attacks |
| **Adversary** | Claims + novelty risks + metric details (`ProposalSummaryView` + metrics + claim registry refs) | Defender strategy, registry state |
| **Judge** | Raw attack + defense + evidence bundle | Frontier scores (cannot be biased by utility), registry write access (invariant: Judge never modifies registry) |
| **Governance** (audit_epoch) | Prompt hashes + evidence bundles + replay results | Retired prompt text (Task 08 rule) |
| **Paper writer** | Verified context + `science_data` + claim registry | Raw transcripts, governance internals |

Enforcement of the **ProposalSummaryView-only constraint** for BFTS is layered:

1. **Construction-time**: the only code path feeding proposal content into
   `bfts.expand(...)` is the summary renderer replacing/wrapping
   `_build_idea_ctx_for_expand` (Task 03); it accepts a `ProposalSummaryView` dataclass,
   not a `ProposalRecord`, so full-record leakage is a type error. Rendered size cap:
   6000 chars (status quo).
2. **Check-time**: ConstitutionalKernel (Task 04) gets a deterministic
   `validate_context_scope(role, view)` check — the BFTS view's key set must be a
   subset of the ProposalSummaryView field whitelist; violations are logged (and, per
   Task 04's fail-posture decision, may block the expand in `ari_rqgm` mode).
3. **Test-time**: a regression test asserts that no archive-only field name
   (`transcript`, `discussion_log`, `raw_proposals`, ...) ever appears in the rendered
   expand context for a fixture ProposalRecord containing all of them.

Per-node agent context injection (epoch charter etc., Task 05) continues to ride
`build_working_context_messages` with a pinned marker and its own cap — this task fixes
the cap value (≤ 1200 chars for the charter block, in line with `_IDEA_FIELD_CAP`).

## 6. Data structures / schema changes

### 6.1 `RQGMConfig` budget section (Pydantic sketch)

```python
class GovernanceBudgetConfig(BaseModel):
    default_level: int = 1                       # 0..3
    full_governance_only_on_top_k: int = 3
    judge_on_disputed_only: bool = True
    impeachment_only_at_epoch_boundary: bool = True
    max_defender_calls_per_epoch: int = 12
    max_judge_calls_per_epoch: int = 8
    low_confidence_threshold: float = 0.4
    novelty_claim_threshold: float = 0.8
    # max_adversary_calls_per_epoch and the score-jump threshold are NOT fields here:
    # they are rqgm.adversarial.max_adversary_calls_per_epoch (24) and
    # rqgm.adversarial.jump_threshold (0.25) in Task 06's config model (§5.3 note).

class ShadowConfig(BaseModel):
    enabled: bool = True
    sample_rate: float = 0.2
    max_shadow_calls_per_epoch: int = 10

class ReplayConfig(BaseModel):
    max_cases_per_epoch: int = 8
    max_cases_for_retirement: int = 12
    use_cached_results: bool = True

class PromptEvolutionBudgetConfig(BaseModel):
    max_candidates_per_role_per_epoch: int = 1
    max_total_candidates_per_epoch: int = 4
    max_clean_room_generations_per_epoch: int = 1

class SpendBudgetConfig(BaseModel):
    max_governance_cost_usd_per_epoch: float = 0.0   # 0 = unlimited
    max_governance_tokens_per_epoch: int = 0         # 0 = unlimited
    on_exhausted: Literal["degrade", "skip"] = "degrade"
```

These nest under `RQGMConfig` (Task 01). The VirSci budget
(`enabled/mode/max_calls_per_epoch/trigger_on`) lives in the `proposal_router` config
block owned by Task 03; this plan fixes only the semantics of `max_calls_per_epoch`.
Likewise, the adversary attack budget and score-jump trigger live in the
`rqgm.adversarial` block owned by Task 06 §7
(`max_adversary_calls_per_epoch: 24`, `jump_threshold: 0.25`); this plan owns the
final tuning of those numeric defaults and `GovernanceBudgetManager` reads them from
`cfg.adversarial`, but no duplicate `rqgm.governance.*` fields exist for them.

### 6.2 Governance cache record (`rqgm_governance_cache.jsonl`, one per line)

```jsonc
{
  "cache_key": "a3f19c02b7d4e881",
  "role": "judge",
  "epoch_id": "epoch_004",              // epoch whose active set produced the result
  "prompt_hash": "9f2c01ab34de",        // hash12
  "artifact_hash": "sha256:...",
  "input_context_hash": "sha256:...",
  "output_schema_hash": "sha256:...",
  "result_ref": "judgment_00042",        // record_id of the stored output (audit log / record store)
  "created_at": "2026-07-05T00:00:00Z"  // provenance only — NEVER part of cache_key (P2)
}
```

Replay lookup rule (from §5.5): when replaying case `c` against prompt `p`, the lookup
key is computed with `epoch_id = c.origin_epoch_id` and `prompt_hash = p.hash`, so a
candidate re-run against old cases caches correctly across epochs.

### 6.3 EpochState budget counters (extends Task 02 schema, additive)

```jsonc
"budget_counters": {
  "adversary_calls": 0, "defender_calls": 0, "judge_calls": 0,
  "shadow_calls": 0, "replay_cases": 0, "virsci_calls": 0,
  "prompt_candidates": {"reviewer": 0, "adversary": 0},
  "clean_room_generations": 0,
  "governance_cost_usd": 0.0, "governance_tokens": 0
},
"governance_levels": [ {"node_id": "node_017", "level": 3, "triggers": ["top_k"]} ]
```

### 6.4 `CallRecord` (additive, `ari-core/ari/cost_tracker.py`)

- New default-None field `epoch: str | None = None`. Old `cost_trace.jsonl` files parse
  unchanged ("absence = no data recorded, never an error").

### 6.5 Context view field whitelists

Frozen constants (e.g. `PROPOSAL_SUMMARY_FIELDS: frozenset[str]`) beside the view
builders; the ConstitutionalKernel check and the leak-regression test both import the
same constant so they cannot drift. Field lists themselves are defined in Task 03
(ProposalSummaryView) and Task 05 (evidence bundle); this plan owns the whitelist
mechanism and the BFTS whitelist content (§5.7 table, row 1).

## 7. API / class changes

All new symbols stay out of `ari.public.*` (no public-API snapshot churn).

```python
class GovernanceBudgetManager:
    """Read-side budget enforcement. Never raises; never blocks the run loop."""
    def __init__(self, cfg: RQGMConfig, epoch_state: EpochState, cost_tracker): ...
    def check(self, action: BudgetedAction) -> BudgetVerdict:  # allow | degrade | skip
    def consume(self, action: BudgetedAction, *, cost_usd: float = 0.0, tokens: int = 0) -> None
    def assign_level(self, node, frontier, epoch_state) -> int   # pure; §5.2 triggers
    def shadow_sample(self, node_id: str) -> bool                # pure; §5.6 hash rule

class GovernanceCache:
    def make_key(self, *, artifact_hash, prompt_hash, role, epoch_id,
                 input_context_hash, output_schema_hash) -> str   # pure; §5.5
    def get(self, key: str) -> dict | None
    def put(self, key: str, record: dict) -> None                 # append-only JSONL

# context_views module — pure functions
def build_bfts_summary_context(view: ProposalSummaryView, *, cap: int = 6000) -> str
def build_reviewer_context(record: ProposalRecord, evidence_refs: list) -> dict
def build_adversary_context(view, metrics, claims) -> dict
def build_judge_context(attack, defense, bundle) -> dict
def build_governance_context(prompt_hashes, bundles, replay_results) -> dict
```

Changed (additive only):
- `ari-core/ari/cost_tracker.py`: `CallRecord.epoch` field; callers pass
  `set_default_metadata(epoch=...)` at epoch start (no signature changes).
- `ConstitutionalKernel` (Task 04) gains `validate_context_scope(role, view)` — listed
  here because this plan defines its whitelist input.
- `GovernanceOrchestrator.audit_epoch` (Task 05) accepts the `GovernanceBudgetManager`
  and must consult it before every internal LLM step.
- `ProposalRouter` (Task 03) consults `check(VIRSCI_CALL)` before `VirSciAdapter`.
- New checkpoint files registered in `ari-core/ari/paths.py` (`META_FILES`,
  `_TRACE_FILES`) and node-report blocklists.

## 8. Migration / compatibility

- **`simple_bfts` (default)**: no `GovernanceBudgetManager` is constructed
  (`build_runtime` conditional wiring, Task 01). `cost_tracker` behavior is unchanged
  except the inert additive `epoch=None` field. No new files are written. Existing
  budget levers (`max_react_steps`, `timeout_per_node`, `max_total_nodes`,
  `rate_limit_per_run`) behave exactly as today. Byte-level `cost_trace.jsonl`
  compatibility: the new field is emitted only when non-None.
- **`rqgm.enabled: false` / absent `rqgm:` block**: identical to `simple_bfts`
  (defaults are inert; `load_config` key filtering handled by Task 01's typed field).
- **`ari_rqgm` + `virsci.enabled: false`**: `virsci_calls` counter and budget exist but
  the adapter is never initialized (Task 03 guarantee); the router never consults the
  VirSci budget. All other budgets operate normally.
- **Resume**: budget counters are restored from `EpochState` (checkpoint-scoped,
  Task 02); the cache index is rebuilt from `rqgm_governance_cache.jsonl`. No state in
  memory only.
- **Degradation ordering**: budget exhaustion reduces governance level, never node
  execution; the fixed L0 layer is exempt from budgets, so no config value can disable
  the constitutional floor.
- **VirSci fully removable**: with VirSci off, tests must pass on environments without
  VirSci installed (spec guarantee, verified in Task 03's test matrix; the budget layer
  adds no VirSci import).

## 9. Tests

Unit (deterministic, no LLM):
1. `cache_key` golden test: fixed inputs → fixed key; component order and separator
   pinned; timestamp provably excluded (two records differing only in `created_at`
   collide).
2. Canonical-JSON hashing: dict key order does not change `input_context_hash`.
3. `assign_level` table test: each §5.2 trigger fires exactly as specified; ties in
   top-K broken by node id; sterile nodes never exceed L0.
4. `shadow_sample` determinism: same `(run_id, epoch_id, node_id)` → same verdict
   across processes; empirical rate on 10 000 synthetic ids within ±2% of
   `sample_rate`; truncation at `max_shadow_calls_per_epoch` respected.
5. Budget counter exhaustion: `check` returns `degrade`/`skip` per `on_exhausted`;
   `consume` past the cap never raises; counters round-trip through EpochState
   save/load (resume-safety).
6. `CallRecord.epoch` additive-field test: old `cost_trace.jsonl` lines parse; summary
   rollup unchanged when `epoch` absent.
7. **ProposalSummaryView-only leak test**: fixture ProposalRecord with `transcript`,
   `discussion_log`, `raw_proposals` populated → rendered BFTS expand context contains
   none of them; whitelist constant and Kernel check share one source.
8. Cache lookup rule: replay of case `c` under candidate prompt `p` builds the key
   from `c.origin_epoch_id` + `p.hash` and hits a pre-seeded entry.

Integration / regression:
9. **Cost regression / budget check** (spec-required): an `ari_rqgm` smoke run with a
   stub LLM backend and tiny caps (e.g. `max_judge_calls_per_epoch: 1`) asserts
   (a) the per-role call counts recorded in `cost_trace.jsonl` (filtered by
   `phase="governance"` + `epoch`) never exceed configured caps, (b) the run completes
   (degrade-never-block), (c) `virsci_calls` ≤ `max_calls_per_epoch` when VirSci is
   stub-enabled, and 0 when disabled.
10. `simple_bfts` no-op regression: with the default config, no
    `rqgm_governance_cache.jsonl` is created, no `epoch` values appear in
    `cost_trace.jsonl`, and existing cost-tracker tests pass unchanged.
11. META_FILES hygiene: new filenames are excluded from node work-dir copies and from
    `node_report.files_changed` (fixture node run).

## 10. Risks

- **Budget-driven bias**: capping adversary calls per epoch means late-epoch nodes get
  less scrutiny than early ones. Mitigation: top-K assignment happens at the epoch
  boundary over the *whole* epoch's nodes, so the highest-utility nodes are audited
  regardless of arrival order; per-node L2 triggers spend a reserved sub-budget.
- **Cache staleness across registry transitions**: a cache hit could serve a judgment
  produced under a since-quarantined prompt. Mitigated by `prompt_hash` in the key
  (retired hashes never recur in lookups) — but this depends on Task 09/10 never
  reusing a hash for a "fixed" prompt (guaranteed: prompts are never mutated in place,
  invariant 3).
- **Counter/ledger divergence**: EpochState counters and cost_tracker records are two
  bookkeeping systems; crashes between `consume` and persistence can undercount.
  Acceptable: budgets are caps, and undercounting by one call per crash is within
  tolerance; the cost regression test bounds drift.
- **Process-wide `set_default_metadata(epoch=...)`** affects skill subprocesses forked
  *after* the call; long-lived skills spawned in a previous epoch keep the old default.
  Mitigation: epoch attribution for skills is best-effort in v1 (documented); exact
  attribution would need per-call metadata plumbed through MCP, deferred.
- **Determinism vs. sample_rate expectations**: hash-based sampling is deterministic
  per node id, so re-runs sample the same nodes — a feature for P2 but a surprise for
  users expecting fresh randomness; document it.
- **Context-view under-provisioning**: an over-tight Adversary view could make attacks
  vacuous, wasting the attack budget. Ablation B4/B5 (Task 13) measures validated-attack
  precision to detect this.
- **`load_config` key filtering** silently drops a mistyped `rqgm:` block today; until
  Task 01's typed field lands, budget config would be ignored without error. Sequencing:
  this task's implementation must land after Task 01's config plumbing.

## 11. Completion criteria

This task is complete when all of the following hold (each maps to a spec criterion,
made concrete):

1. **Cost control config defined**: the full `rqgm.governance` / `rqgm.shadow` /
   `rqgm.replay` / `rqgm.prompt_evolution` / `rqgm.budgets` schema (§5.3, §6.1) is
   specified with types, defaults, and enforcement point for every knob — with the
   adversary-side knobs (`max_adversary_calls_per_epoch`, `jump_threshold`) referenced
   from Task 06's `rqgm.adversarial` block rather than duplicated — and reviewed
   for consistency with Task 01's `RQGMConfig` and Task 05's `audit_epoch` internals.
2. **VirSci max calls defined**: `proposal_router.generators.virsci.max_calls_per_epoch`
   semantics are fixed (counter home in EpochState, enforcement point in
   ProposalRouter, degrade-to-cheaper-generator fallback, zero-cost guarantee when
   `enabled: false`), cross-referenced with Task 03.
3. **No-full-transcript-to-BFTS stated**: the role/view visibility matrix (§5.7) is
   fixed, BFTS's row is `ProposalSummaryView` only, and the three-layer enforcement
   (typed renderer input, Kernel `validate_context_scope`, leak-regression test) is
   specified.
4. **Cache key defined**: the exact `cache_key` composition, canonicalization, join
   rule, hash truncation, epoch-id semantics for replay lookups, and the append-only
   store format (§5.5, §6.2) are specified and P2-clean (no wall-clock inputs).
5. Governance level ladder (L0–L3) and all deterministic escalation triggers are
   defined with default thresholds and audit-log format.
6. The budget-exhaustion posture (`degrade`/`skip`, never crash, L0 exempt) is stated
   and consistent with the repo's fail-open hook discipline.
7. The test list (§9), including the spec-required cost regression / budget check
   test, is agreed as the implementation acceptance suite.

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

- Governance level config exists (typed `rqgm.governance` block implemented, with the
  level ladder consumed by the run loop / GovernanceOrchestrator).
- Replay/shadow caps exist (`rqgm.replay.max_cases_per_epoch`,
  `max_cases_for_retirement`, `rqgm.shadow.max_shadow_calls_per_epoch` implemented and
  enforced at the epoch boundary).
- VirSci call budget config exists (`proposal_router.generators.virsci.max_calls_per_epoch`
  implemented and enforced in ProposalRouter; zero-cost when VirSci disabled).
- Cache key implemented (the §5.5 composition, with the golden-key unit test).
- ProposalSummaryView-only constraint implemented (typed renderer + Kernel check +
  leak-regression test all landed).
- Cost regression test or budget check exists (the §9 item 9 smoke test, running in CI).
- Budget semantics (level ladder, cache_key definition, view matrix) migrated to
  permanent docs (developer guide / schema reference / execution mode guide).

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
- [ ] The governance-level ladder and escalation-trigger table are documented in the permanent execution mode / developer guide.
- [ ] The `cache_key` definition and cache-record schema are documented in the permanent schema reference.
- [ ] The role→context-view visibility matrix (including the BFTS ProposalSummaryView-only rule) is documented in permanent docs.
- [ ] `docs/reference/` entries exist for any new checkpoint files (`rqgm_governance_cache.jsonl`) and config keys that were committed.
