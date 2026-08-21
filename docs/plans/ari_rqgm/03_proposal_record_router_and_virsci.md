# Task 03: ProposalRecord, ProposalRouter, and VirSci

> **Status**: planned · **Depends on**: 00, 01, 02 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

Today, research proposals enter ARI through two ad-hoc channels: (i) a one-shot
`generate_ideas` MCP call at the root node whose result the agent loop persists verbatim as
`{ckpt}/idea.json`, and (ii) per-expansion child "directions" generated inline by
`BFTS.expand`. Neither channel produces a governed record: there is no stable proposal
identity, no `prompt_hash`/`epoch_id` provenance, no archive of the deliberation that produced
a proposal, and no separation between what is *stored* and what the search loop *sees*.

This task reorganizes proposal generation into three pieces required by ARI-RQGM:

1. **ProposalRecord** — an archival, provenance-complete record of every generated proposal
   ("store everything").
2. **ProposalSummaryView** — the bounded summary that is the *only* proposal representation
   BFTS may consume ("hand BFTS only the summary"; full VirSci transcripts are archive-only).
3. **ProposalRouter** — a budget-aware dispatcher over five generators (CheapGenerator,
   MutationGenerator, AttackDrivenGenerator, PriorArtDifferentiationGenerator, and the
   *optional* VirSciAdapter), active only in `ari_rqgm` mode.

It also defines the **staged `idea.json` compatibility plan**: `idea.json` remains a
conforming projection of the selected ProposalRecord so that every existing consumer keeps
working, and `simple_bfts` behavior is preserved byte-for-byte.

## 2. Scope

- ProposalRecord schema (JSON Schema + dataclass) with the mandatory common record fields
  (`record_id, epoch_id, component_id, prompt_hash, role, created_at, source_refs, status`)
  plus `stale` / `valid_for_frontier` fields whose semantics are owned by Task 10: logical-only,
  written once at their defaults and never rewritten in stored JSONL — staleness is materialized
  only in the erasure state and derived by readers as `record_id ∈ stale_record_ids`.
- ProposalSummaryView schema with the eight spec-mandated fields and hard size budgets.
- ProposalRouter design: generator registry, deterministic routing policy, trigger events,
  per-epoch call budgets, invocation surfaces (root ideation; expansion recording;
  epoch-boundary re-ideation as an explicitly gated new behavior).
- VirSciAdapter design: normalization of `generate_ideas` output (re-impl loop or real vendored
  engine) into ProposalRecord + archive refs; `virsci.enabled=false` guarantees.
- Checkpoint-scoped proposal store (`{ckpt}/proposals/`): append-only JSONL truth + per-record
  archive directory, registered in `PathManager.META_FILES` / `_TRACE_FILES` and node-report
  blocklists.
- `idea.json` compatibility layer: projection writer, single-writer discipline, staged consumer
  migration (Section 8).
- **Stage-0 prerequisite fix**: restore the lost `@mcp.tool()` registration on `survey` and
  `generate_ideas` in `ari-skill-idea/src/server.py` (regression documented in Task 00), with
  an MCP-level test so it cannot silently regress again.
- Config: `proposal_router.*` block (typed, per Task 01's `RQGMConfig` decision), including
  `generators.virsci.enabled`, `mode: event_triggered`, `max_calls_per_epoch`, `trigger_on`.
- An opt-in **record-only** mode so `simple_bfts` runs can dual-write ProposalRecords without
  any behavior change (needed for Task 13 ablation B1).

## 3. Non-goals

- No implementation in this task plan; design only.
- No change to `simple_bfts` default behavior. The router, the record store, and all new
  config are inert unless explicitly enabled.
- No removal of `idea.json`. It stays indefinitely as the compatibility projection (GUI and
  child-launch seeding depend on it); retiring it would be a separate, future decision.
- No editing of the vendored VirSci engine (`ari-skill-idea/vendor/virsci` submodule) — all
  integration remains wrapper-layer, as today.
- No adversary/defender/judge design (Task 06); this task only reserves the
  AttackDrivenGenerator seam that consumes Task 06's `ValidatedAttackRecord`s.
- No PromptSpec lifecycle (Task 07); generator prompts here are versioned `.md` templates
  under the existing `load_versioned` + `record_prompt_use` discipline; their evolution is
  Task 07's job.
- No frontier staling/erasure logic (Task 10); this task only carries the flags.
- No governance of `make_metric_spec` or evaluator axes (Tasks 04/11).

## 4. Existing ARI touchpoints

All paths repo-relative; verified to exist on branch `RQGM`.

| Touchpoint | Path / symbol | Relevance |
|---|---|---|
| VirSci adapter skill | `ari-skill-idea/src/server.py` (`survey`, `generate_ideas`, `_llm`, pinned-idea merge at the persistence tail) | Becomes the backend the VirSciAdapter calls via MCP. **Stage-0 bug**: only `_load_virsci_snapshot_papers` currently carries `@mcp.tool()`; `survey`/`generate_ideas` lost registration (commits `711dad0`/`0625d2d`/`3707fd6`). |
| Real VirSci engine wrapper | `ari-skill-idea/src/virsci_runtime.py` (`run_virsci_live`, `LivePlatform`), `ari-skill-idea/src/snapshot.py` (`build_snapshot`) | Source of full transcripts/retrieval snapshots that must become archive-only refs (`{ckpt}/virsci_logs/`, `{ckpt}/virsci_snapshot/`). Vendored engine at `ari-skill-idea/vendor/virsci` (git submodule; may be absent). |
| Skill metadata | `ari-skill-idea/mcp.json`, `ari-skill-idea/skill.yaml`, `ari-skill-idea/tests/test_server.py` | Declarative tool list (not read by MCPClient); tests call functions directly and therefore missed the registration regression — the new test must go through `mcp.list_tools()`. |
| `idea.json` writer #1 | `ari-core/ari/agent/loop.py` (generate_ideas persistence handler, ~lines 1011–1175) | The agent loop, not the skill, writes `idea.json`, seeds memory (`EVALUATION_CRITERIA:`, Letta `selected_idea`), and suppresses further `generate_ideas` calls. Unchanged in `simple_bfts`; superseded by the router in `ari_rqgm`. |
| `idea.json` writer #2 | `ari-core/ari/orchestrator/root_idea_selector.py` (`select_root_idea`, `apply_root_choice`, `append_root_selection_log`) | One-shot re-rank with `_root_choice` marker; the pattern (swap + provenance marker + shared JSONL log) the projection writer must follow. |
| `idea.json` writer #3 | `ari-core/ari/viz/api_orchestrator.py` (`_api_launch_sub_experiment`, `inherit_idea_index`, `_pinned` / `_inherited_from` seeding) | Child runs receive a pinned parent idea before start; the projection must preserve these markers and the pinned-ideas-in-front merge. |
| BFTS consumption channel | `ari-core/ari/cli/bfts_loop.py` (`_run_loop`: first-appearance block, `_idea_ctx_for_expand`), `ari-core/ari/cli/lineage.py` (`_build_idea_ctx_for_expand`) | The ~6000-char serialization of `ideas[0]` is today's *only* channel from idea to expand prompts — the exact seam where ProposalSummaryView plugs in, and the existing proof that BFTS already never sees transcripts. |
| Expansion proposal site | `ari-core/ari/orchestrator/bfts.py` (`BFTS.expand`, one-child cap, fallback child), `ari-core/ari/protocols/search.py` (`SearchStrategy`) | Expansion directions are de-facto cheap proposals; the router records them via a `SearchStrategy` decorator installed in `ari-core/ari/core.py:build_runtime`. |
| Lineage/idea-pool readers | `ari-core/ari/orchestrator/lineage_decision.py` (`build_lineage_state`), `ari-core/ari/lineage.py` (`get_idea_pool_for_ckpt`, `format_ancestor_pool_for_virsci`) | Runner-up catalog for pivots and the opt-in ancestor catalog — Stage-3 migration consumers; the directive-vs-catalog two-path contract must survive. |
| Paper pipeline reader | `ari-core/ari/pipeline/driver.py` (idea directive read, `plan_promote`), `ari-core/ari/pipeline/experiment_md.py` (`_extract_plan_sections`, `_promote_plan_to_experiment_md`) | Reads `ideas[0]` only; projection must keep `### N)` plan-section format parseable. |
| Evaluator axis coupling | `ari-core/ari/evaluator/llm_evaluator.py` (`_idea_json_signature`), `ari-core/ari/evaluator/dynamic_axes.py` (`build_axes_for_run`) | Axes derive from `ideas[0].experiment_plan` with content-hash refresh; projection rewrites must be content-visible and confined to today's rewrite windows so evaluator axes stay frozen between the existing refresh points (axis-freeze discipline; see §8 Stage 2). |
| MCP invocation path | `ari-core/ari/mcp/client.py` (`MCPClient.call_tool`, `_SLOW_TOOLS` incl. `generate_ideas`, retry×3), `ari-core/ari/agent/tool_manager.py` | VirSciAdapter calls the skill through the shared client; adapter calls must be idempotent under the 3-retry policy or carry an explicit budget arg. |
| State layer homes | `ari-core/ari/paths.py` (`PathManager.META_FILES`), `ari-core/ari/checkpoint.py`, `ari-core/ari/protocols/stores.py`, `ari-core/ari/schemas/node_report.schema.json` (sibling location for new schemas) | Where `proposals/` files get registered and where `proposal_record.schema.json` / `proposal_summary_view.schema.json` live. |
| Config plumbing | `ari-core/ari/config/__init__.py` (`ARIConfig`, `load_config` filters unknown top-level keys, `_merge_bfts_disabled_tools`, `export_resolved_config_to_skill_env`), `ari-core/config/workflow.yaml` (`bfts_pipeline.generate_idea`, pinned `skills:` list) | `proposal_router:` must ride Task 01's typed `RQGMConfig` or it is silently dropped from the typed cfg. |
| Prompt provenance | `ari-core/ari/prompts/registry.py` (`PromptRegistry`, `load_versioned` → `sha256[:12]`) | New generator prompts are committed `.md` templates with `hash12` provenance — the single prompt-hash scheme reused as ProposalRecord `prompt_hash`. |
| CLI env bridge | `ari-core/ari/cli/run.py` (`--virsci-*` → `ARI_IDEA_VIRSCI_*`), `ari-core/ari/agent/workflow.py` (`has_idea_gen`) | Existing VirSci width knobs (`K/TEAM_SIZE/MAX_TEAMS`) that epoch exploration width maps onto; degradation tier-3 behavior when the tool is absent. |

## 5. Proposed design

### 5.1 Principle

**Store everything; hand BFTS only the summary.** Every generated proposal becomes a
ProposalRecord in a checkpoint-scoped archive. BFTS (prompt builders, expand context, frontier
logic) receives only rendered ProposalSummaryViews within a fixed character budget. Full
VirSci transcripts, agent discussion logs, citation candidates, retrieval snapshots, raw
proposal lists, and generator configs live under archive refs and are never deserialized by
any prompt-side code.

### 5.2 ProposalRouter (ari_rqgm mode only)

```
ProposalRouter
  ├─ CheapGenerator                      # default; one-shot LLM proposal
  ├─ MutationGenerator                   # mutates one facet of an existing ProposalRecord
  ├─ AttackDrivenGenerator               # consumes ValidatedAttackRecords (Task 06)
  ├─ PriorArtDifferentiationGenerator    # differentiates vs survey/related refs
  └─ VirSciAdapter                       # optional high-cost deliberative generator
```

Routing is a **deterministic policy function** (P2, deterministic-rule-first precedent from
`deterministic_stagnation_pivot`): `route(event, budgets, available_generators) -> generator`.
The router itself is not an LLM in v1; what evolves later (Task 07) are the generator
*prompts*, not the routing rule. Trigger events map onto existing hooks:

| Event | Existing hook |
|---|---|
| `initial_exploration` | run start / first proposal need in `_run_loop` (replaces root `generate_ideas` in `ari_rqgm`) |
| `frontier_stagnation` | `detect_stagnation()` true in the per-node lineage hook |
| `major_pivot` | lineage decision `switch_to_idea` / `fanout` |
| `paper_candidate` | paper-pipeline pre-flight (`WorkflowDriver.run`) |

Two invocation surfaces:

1. **`generate_root_proposals(ctx) -> list[ProposalRecord]`** — called on the `_run_loop`
   main thread (marker-guarded, like root idea selection), replacing the agent-initiated root
   `generate_ideas` call in `ari_rqgm` mode. Writes records + `idea.json` projection, then the
   run proceeds exactly as today (root selection markers respected).
2. **`record_expansion_proposal(node, direction) -> ProposalRecord`** — v1 wraps
   `SearchStrategy.expand` with a recording decorator installed in `build_runtime`: each child
   direction produced by `BFTS.expand` is captured as a CheapGenerator ProposalRecord
   (observation, zero behavior change to expansion), and the `idea_context` string passed to
   expand is rendered from the active ProposalSummaryView. Moving direction *generation* into
   the router proper is deferred (recorded as an open question forwarded to Task 05/07).

Every generation failure degrades: router errors are caught, logged, and fall back to the
status-quo path (existing fallback child, existing `idea.json` if present). The loop never
dies on a router failure: this preserves the existing BFTS-loop failure-isolation discipline —
every optional hook in `_run_loop` is try/except + warn-and-degrade, and no proposal-side
error may crash the search loop.

### 5.3 Generators

- **CheapGenerator** — one prompt-templated LLM call (`ari-core/ari/prompts/rqgm/proposal_cheap.md`,
  new committed template) producing one proposal from node/goal context. In v1 it also serves
  as the label for recorded `BFTS.expand` directions. Deterministic fallback: reuse the
  existing DEBUG/IMPROVE fallback child semantics.
- **MutationGenerator** — input: one existing non-stale ProposalRecord (selected
  deterministically: highest-utility or current directive) + a mutation facet
  (`hypothesis | plan_step | success_metric | scope`); output: a new ProposalRecord with
  `source_refs.parent_proposal_id` set. Never mutates the parent record in place (mirrors the
  no-in-place-prompt-mutation invariant).
- **AttackDrivenGenerator** — input: ValidatedAttackRecords affecting the current lineage
  (from Task 06's AdversarialReplayPool); output: proposals that address validated
  weaknesses, with `source_refs.attack_case_ids`. Disabled (and absent from the routing
  table) until Task 06 lands; config default `enabled: false`.
- **PriorArtDifferentiationGenerator** — input: survey output / `related_refs.json` /
  frozen `virsci_snapshot/papers` when present; output: proposals with explicit
  differentiation claims and `source_refs.survey_refs`. Degrades to skipped when no prior-art
  source exists.
- **VirSciAdapter** — see 5.4.

All generators stamp `prompt_hash` (the existing `hash12`), `component_id`, `epoch_id` (from
Task 02's EpochState; `null` when recording in `simple_bfts` record-only mode), and record
prompt use via `record_prompt_use` (→ `prompt_trace.jsonl`).

### 5.4 VirSciAdapter and the archive/summary split

The adapter is **core-side, MCP-only**: it calls `generate_ideas` (and optionally `survey`)
on the idea skill through the shared `MCPClient` and normalizes the 9-key result into
ProposalRecords. It imports nothing from `ari-skill-idea` and has zero VirSci dependencies —
heavy deps (torch/faiss/agentscope) stay inside the skill, which keeps its existing three
degradation tiers. This is what makes "tests pass without VirSci installed" structural rather
than aspirational.

```
VirSci discussion → raw output/transcript/paper refs
  → VirSciAdapter (normalize, 1 record per idea)
    → ProposalRecord (archive_refs → virsci_logs/, virsci_snapshot/, raw_output.json)
      → ProposalSummaryView (bounded)
        → BFTS node expansion (idea_context rendering only)
```

Archive (stored, never prompt-side): full transcript, agent discussion log, citation
candidates, prompt_hashes, generator config (`K`, `TEAM_SIZE`, `MAX_TEAMS`, model, api_base),
retrieval snapshot ref, raw proposal list. Existing artifacts (`{ckpt}/virsci_logs/`,
`{ckpt}/virsci_snapshot/`) are *referenced*, not copied.

Passed to BFTS (summary only): title, short description, hypothesis, minimal experiment plan,
success metric, novelty risks, expected artifacts, dissent summary.

`virsci.enabled=false` guarantees (mechanism in parentheses):

- VirSciAdapter never initialized (conditional construction in `build_runtime`; no module-level
  import side effects).
- No VirSci runtime/vendored path required (adapter is MCP-only; submodule may be absent).
- No VirSci prompts registered in PromptRegistry (adapter registers its normalization prompt
  keys only when constructed; skill-local prompts never enter core's registry anyway).
- No VirSci transcripts generated, no retrieval snapshot required (the router never routes to
  the adapter; `build_snapshot` is only reached via the skill's real path).
- ProposalRouter generates proposals with the other generators only; BFTS/Governance/
  Registry/FrontierRepair run normally.
- Tests pass on environments without VirSci installed (CI runs without the submodule).

**Mode × VirSci matrix** (all four combinations valid; VirSci toggles independently of mode):

| | VirSci "on" | VirSci "off" |
|---|---|---|
| `simple_bfts` | Today's behavior: root `generate_ideas` (re-impl loop; real engine iff `ARI_IDEA_VIRSCI_REAL`). `proposal_router.*` is **inert**. | Today's existing levers: `bfts_pipeline.generate_idea.enabled: false` (tier-3 degradation) and/or `ARI_IDEA_VIRSCI_REAL` unset (tier-2). Unchanged. |
| `ari_rqgm` | `proposal_router.generators.virsci.enabled: true`, event-triggered, `max_calls_per_epoch` capped. | `enabled: false` (default): guarantees above; other four generators only. |

Deliberate decision: `proposal_router.generators.virsci.enabled` is **not** read in
`simple_bfts`. Making the shipped default (`false`) meaningful there would disable today's
default ideation — a forbidden behavior change. The `simple_bfts` VirSci levers remain the
existing ones. This asymmetry is documented in the config reference when migrated to
permanent docs.

Epoch-boundary **re-ideation is new behavior**: today `generate_ideas` runs exactly once at
root (the `frontier_expand` stage's declared `tool: generate_ideas` in
`ari-core/config/workflow.yaml` is fiction). Re-ideation therefore exists only in `ari_rqgm`,
only via router events, and each re-ideation appends records and re-emits the projection under
the same content-visible rewrite discipline as `apply_root_choice`.

### 5.5 Enforcement of "BFTS never sees full transcripts"

Three layers, all deterministic:

1. **Schema bound**: ProposalSummaryView fields carry hard character limits; the rendered
   `idea_context` replacement (`render_summary_ctx`) enforces the same ~6000-char total budget
   as `_build_idea_ctx_for_expand` today.
2. **Code path bound**: `bfts_prompt_builder` and the expand path receive only the rendered
   summary string; no archive path is ever opened by prompt-side modules (kept pure per P2).
3. **Kernel check (Task 04 hook)**: ConstitutionalKernel's schema validation rejects any
   ProposalSummaryView exceeding budgets, and an access check flags archive-path reads from
   prompt-building contexts. This task defines the check surface; Task 04 implements it.

## 6. Data structures / schema changes

New JSON Schemas beside `ari-core/ari/schemas/node_report.schema.json`:
`proposal_record.schema.json`, `proposal_summary_view.schema.json` (both `schema_version: 1`,
additive-only evolution policy).

### 6.1 ProposalRecord (draft)

```jsonc
{
  "record_id": "prop_000042",              // stable, monotonic per run
  "record_type": "proposal_record",
  "schema_version": 1,
  "epoch_id": "epoch_000",                 // null in simple_bfts record-only mode
  "component_id": "proposal_router_v1",
  "role": "generator",
  "generator": "cheap | mutation | attack_driven | prior_art | virsci | legacy_idea_json",
  "prompt_hash": "ab12cd34ef56",           // existing hash12 scheme; null for legacy imports
  "created_at": "2026-07-05T00:00:00Z",    // wall clock; NEVER part of any content hash (P2)
  "status": "candidate | selected | expanded | superseded",
  "stale": false,                          // logical-only; semantics owned by Task 10 (§6): the
                                           // stored value stays false and is NEVER rewritten in
                                           // JSONL — on retirement, staleness is materialized only
                                           // in the erasure state, and readers derive it as
                                           // record_id ∈ stale_record_ids
  "valid_for_frontier": true,              // logical-only companion; same Task 10 read-time
                                           // semantics (derived from the erasure state)
  "source_refs": {
    "node_id": null,                       // expansion-recorded proposals
    "parent_proposal_id": null,            // MutationGenerator
    "attack_case_ids": [],                 // AttackDrivenGenerator
    "survey_refs": []                      // PriorArtDifferentiationGenerator
  },
  "summary": { /* ProposalSummaryView, inline (single source of the summary) */ },
  "archive_refs": {                        // checkpoint-relative paths; refs, not copies
    "raw_output": "proposals/archive/prop_000042/raw_output.json",
    "transcript": "proposals/archive/prop_000042/transcript.jsonl",   // VirSci only
    "discussion_log": "virsci_logs/virsci_stdout.log",                // VirSci real path
    "retrieval_snapshot": "virsci_snapshot/",                          // VirSci real path
    "generator_config": "proposals/archive/prop_000042/generator_config.json",
    "prompt_hashes": { "generator": "ab12cd34ef56" }
  },
  "idea_projection": { "projected": true, "idea_index": 0 }            // link into idea.json
}
```

### 6.2 ProposalSummaryView (draft; the ONLY shape BFTS sees)

```jsonc
{
  "proposal_record_id": "prop_000042",
  "title": "…",                            // ≤ 200 chars
  "short_description": "…",                // ≤ 600 chars
  "hypothesis": "…",                       // ≤ 400 chars
  "experiment_plan": ["### 1) …", "…"],    // ≤ 6 steps × ≤ 400 chars; keeps the "### N)"
                                           // section format so _extract_plan_sections parses it
  "success_metric": { "name": "…", "higher_is_better": true, "rationale": "…" },
  "novelty_risks": ["…"],                  // ≤ 3 × ≤ 200 chars
  "expected_artifacts": ["…"],             // ≤ 5 × ≤ 120 chars
  "dissent_summary": "…",                  // ≤ 400 chars; VirSci minority view; "" for cheap gen
  "scores": { "novelty": 0.8, "feasibility": 0.7, "overall": 0.77 }   // idea.json 0–1 scale
}
```

Rendered total budget ≤ 6000 chars (parity with `_build_idea_ctx_for_expand`).

### 6.3 Checkpoint layout and store

```
{ckpt}/proposals/
  proposal_records.jsonl       # append-only truth (one record per line, lock-guarded,
                               # best-effort, never raises — record_prompt_use pattern)
  proposal_index.json          # derived rollup: record_id → status/generator/epoch
  archive/<record_id>/…        # raw outputs, transcripts, generator configs
```

All three names registered in `ari-core/ari/paths.py:PathManager.META_FILES` (+
`_TRACE_FILES` for the JSONL) and added to node-report blocklists so they never contaminate
node work dirs or `files_changed`. A `ProposalStore` Protocol is added beside
`ari-core/ari/protocols/stores.py:TraceStore` (subtask-044 playbook). `simple_bfts` default
runs create **no** `proposals/` directory at all.

### 6.4 idea.json projection mapping

| idea.json key | Source |
|---|---|
| `ideas[i].title / description` | `summary.title / short_description` |
| `ideas[i].experiment_plan` | `summary.hypothesis` + `summary.experiment_plan` joined, `### N)` format |
| `ideas[i].novelty / feasibility` | `summary.novelty_risks` prose / feasibility note |
| `ideas[i].{novelty_score,feasibility_score,overall_score}` | `summary.scores` (same 0–1 scale, same `overall = (2n+f+c)/4` convention) |
| `ideas[i]._proposal_record_id` | new underscore key (traceability; underscore-key precedent) |
| top-level `primary_metric / higher_is_better / metric_rationale` | selected record's `summary.success_metric` |
| `gap_analysis`, `papers_analyzed`, `n_agents`, `discussion_rounds`, `virsci_integration_status` | preserved from generator output (VirSci) or synthesized (`"router:<generator>"`) |
| `_pinned`, `_inherited_from`, `_root_choice` | preserved verbatim; pinned entries stay in front |

### 6.5 Config sketch (typed `RQGMConfig` per Task 01; silently-dropped raw keys are not acceptable)

```yaml
ari:
  mode: simple_bfts            # simple_bfts | ari_rqgm
rqgm:
  enabled: false
proposal_router:               # consumed ONLY when ari.mode == ari_rqgm,
  record_only: false           #   EXCEPT record_only, honored in simple_bfts (ablation B1)
  summary_budget_chars: 6000
  generators:
    cheap:      { enabled: true }
    mutation:   { enabled: true,  max_calls_per_epoch: 2 }
    attack_driven: { enabled: false }          # requires Task 06
    prior_art:  { enabled: true,  max_calls_per_epoch: 1 }
    virsci:
      enabled: false
      mode: event_triggered
      max_calls_per_epoch: 2
      trigger_on: [initial_exploration, frontier_stagnation, major_pivot, paper_candidate]
```

## 7. API / class changes

New package `ari-core/ari/orchestrator/proposals/` (kept out of `ari.public.*` to avoid
contract-snapshot churn; no new CLI surface in v1):

```python
# records.py
@dataclass ProposalRecord: ...          # mirrors §6.1; to_dict/from_dict; schema validation
@dataclass ProposalSummaryView: ...     # mirrors §6.2; render_summary_ctx(view) -> str (pure, P2)

# store.py
class ProposalStore:                    # + Protocol in ari/protocols/stores.py
    def append(self, record: ProposalRecord) -> None: ...        # lock, never raises
    def load_all(self) -> list[ProposalRecord]: ...
    def selected(self) -> ProposalRecord | None: ...
    def write_idea_projection(self) -> bool: ...                 # single idea.json writer (ari_rqgm)

# router.py
class ProposalRouter:
    def __init__(self, cfg, llm, mcp, store, epoch_state=None): ...
    def generate_root_proposals(self, ctx) -> list[ProposalRecord]: ...
    def record_expansion_proposal(self, node, direction) -> ProposalRecord: ...
    def on_event(self, event: str, ctx) -> list[ProposalRecord]: ...   # deterministic routing

# generators.py  (Generator Protocol + CheapGenerator, MutationGenerator,
#                 AttackDrivenGenerator, PriorArtDifferentiationGenerator)
# virsci_adapter.py  (VirSciAdapter — MCP-only; constructed only when virsci.enabled)
```

Changed (all additive / conditional):

- `ari-core/ari/core.py:build_runtime` — when `ari.mode == ari_rqgm`, construct
  `ProposalStore` + `ProposalRouter` and wrap the search strategy with the expand-recording
  decorator (wrap objects; do **not** extend the returned 6-tuple).
- `ari-core/ari/cli/bfts_loop.py:_run_loop` — in `ari_rqgm` mode, the first-appearance /
  root-ideation block delegates to `generate_root_proposals`; the `_idea_ctx_for_expand`
  string comes from `render_summary_ctx` with an `idea.json` fallback. `simple_bfts` code path
  untouched.
- `ari-skill-idea/src/server.py` — Stage 0: restore `@mcp.tool()` on `survey` and
  `generate_ideas`; demote `_load_virsci_snapshot_papers` to a plain helper (it was never
  meant to be agent-visible; `survey` calls it directly).
- New prompt templates `ari-core/ari/prompts/rqgm/proposal_cheap.md`,
  `proposal_mutation.md`, `proposal_prior_art.md` — committed `.md` from day one (the 4
  prompt-snapshot layers apply; `scripts/check_prompts.py` forbids inline strings).

## 8. Migration / compatibility

Preserve-existing-behavior stance: `simple_bfts` keeps current ARI behavior verbatim;
everything below is opt-in via config; VirSci fully removable; nothing enabled by default.

**Stage 0 — regression fix (prerequisite, behavior-*restoring*).** Restore MCP registration of
`survey`/`generate_ideas`. This returns runs to the documented tier-1/2 behavior (they are
currently idle-degrading to tier-3). Guard with an `mcp.list_tools()`-level test. No RQGM
machinery involved.

**Stage 1 — record-only dual-write (opt-in; ablation B1).** With
`proposal_router.record_only: true` in `simple_bfts`, the agent-loop persistence handler's
output is additionally imported into `proposal_records.jsonl` as `generator:
"legacy_idea_json"` records. Zero consumer changes, zero behavior changes; `idea.json` is
still written by the same single writer. Rollback: delete the flag.

**Stage 2 — router with projection (`ari_rqgm` only).** ProposalRouter becomes the proposal
producer and the **single writer** of `idea.json` (in `ari_rqgm`): root proposals, root-choice
application, and re-ideation all flow through `ProposalStore.write_idea_projection()`, which
preserves the 9-key contract, `ideas` sort order, pinned-in-front merge, and
`_pinned`/`_inherited_from`/`_root_choice` semantics. All consumers still read `idea.json`.
Concurrency: all projection writes happen on the `_run_loop` main thread (lineage-hook
precedent) under a store-level lock; rewrites stay content-visible so
`_idea_json_signature`-driven axis refresh keeps working, and are confined to today's rewrite
windows (pre-expand; epoch boundary) to respect the axis-freeze discipline: evaluator axes,
once derived from `ideas[0].experiment_plan`, must not change between those windows, so
mid-window projection rewrites are forbidden.

**Stage 3 — consumer migration to ProposalSummaryView (`ari_rqgm` only, one consumer at a
time, each with `idea.json` fallback).** Order, chosen by blast radius:

1. `ari-core/ari/cli/lineage.py:_build_idea_ctx_for_expand` → `render_summary_ctx` (the
   BFTS-facing channel; this is the "ProposalSummaryView passed to BFTS" deliverable).
2. `ari-core/ari/orchestrator/lineage_decision.py:build_lineage_state` alternatives pool →
   non-stale candidate ProposalRecords' summaries.
3. `ari-core/ari/pipeline/driver.py` `idea_context` + plan promotion → selected record's
   summary (plan-section format preserved).
4. `ari-core/ari/evaluator/dynamic_axes.py` axis derivation → summary plan (only after 1–3
   are stable; axis semantics must not drift mid-migration).

GUI (`ari/viz`) and child-launch seeding (`api_orchestrator.py`) are **not** migrated: they
keep reading/writing `idea.json`, which the projection maintains indefinitely. Cross-run
inheritance continues to ride `inherit_idea_index`; an inherited pinned idea is imported as a
`legacy_idea_json` ProposalRecord at child start in `ari_rqgm` mode.

**Stage 4 — steady state.** `idea.json` = maintained compatibility projection of the selected
ProposalRecord. Removal is out of scope for this project.

Compatibility invariants enforced at every stage: `ideas[0]` is the directive; pinned ideas
stay in front; one-shot markers respected, never cleared; degrade-never-block at every tier;
directive-vs-catalog two-path separation; `lineage_decisions.jsonl` stays the shared audit log
(router decisions log there with new `trigger: "proposal_router"` values rather than a new
file — the record store itself is separate because records are data, not decisions).

## 9. Tests

Unit:
- Schema round-trip + validation for ProposalRecord / ProposalSummaryView; rejection of
  over-budget summaries; `render_summary_ctx` purity (byte-identical output for identical
  input) and ≤ budget.
- Projection writer: golden test that a projected `idea.json` satisfies the 9-key contract,
  sort invariant, pinned-in-front merge, marker preservation, and that
  `_extract_plan_sections` parses projected plans.
- Router policy table: event → generator dispatch, per-epoch budget exhaustion, deterministic
  tie-breaking; disabled generators never selected.
- VirSciAdapter normalization from a canned 9-key `generate_ideas` payload (both
  `real_wrap` and `reimpl` statuses); archive_refs populated; no transcript content in
  `summary`.

Regression:
- **Stage 0**: `mcp.list_tools()` on the idea skill includes `survey` and `generate_ideas`
  and excludes `_load_virsci_snapshot_papers` (must go through FastMCP registration, not
  direct function calls, or it cannot catch decorator loss).
- `simple_bfts` default run: no `proposals/` dir created; `idea.json` flow byte-compatible
  with pre-change behavior; existing prompt-snapshot layers green (new `rqgm/*` templates
  blessed once).
- `META_FILES`/blocklist registration: `proposals/*` never appears in node `files_changed`.

Integration:
- `ari_rqgm` + `virsci.enabled=false`: run boots, CheapGenerator proposals flow, assertion
  that `VirSciAdapter` was never constructed and no `virsci_snapshot/` build was attempted.
- **No-VirSci environment**: full test suite passes with the `ari-skill-idea/vendor/virsci`
  submodule absent and heavy deps uninstalled (CI already runs this way).
- Archive/summary split: rendered expand context of an `ari_rqgm` run contains no string from
  the archived transcript fixture.
- Four-combination smoke matrix (`simple_bfts`/`ari_rqgm` × VirSci on/off) at
  config-validation + boot level (full VirSci-on runs are cost-gated to manual/nightly).
- Retry idempotency: VirSciAdapter's MCP call repeated 3× yields no duplicate ProposalRecords
  (dedup by content key, not wall clock).

## 10. Risks

- **Dual-write divergence**: projection and records drifting apart. Mitigation: projection is
  always derived from records by one function; a deterministic consistency check
  (records ↔ projection) runs at write time and in tests.
- **Summary lossiness**: bounded summaries may drop information the expand prompt used to get
  (today's channel is already ~6000 chars, so parity is achievable; budgets are config-tunable
  per epoch via Task 12).
- **Single-writer erosion**: more writers of `idea.json` in `ari_rqgm` (router, root choice,
  re-ideation). Mitigation: all writes funneled through `ProposalStore.write_idea_projection`
  on the main thread; `apply_root_choice` in `ari_rqgm` becomes a store operation.
- **Axis-refresh churn**: projection rewrites trigger evaluator axis recomputation
  (`_idea_json_signature`). Confining rewrites to the existing windows keeps the axis freeze
  intact (axes never change outside those windows); epoch
  re-weighting interactions are Task 10's explicit problem, not silently changed here.
- **Mid-run re-ideation is genuinely new**: it can shift the directive mid-run. Gated to
  `ari_rqgm`, event-triggered, budget-capped, logged; `simple_bfts` unaffected.
- **`ARI_DISABLED_TOOLS_FOR_CHILD` is a stub** (`ari-core/ari/cli/lineage.py`): "run inherited
  idea verbatim" in child runs needs real plumbing; forwarded as an open item to Task 05
  (governance of sub-run spawning).
  > **Landed 2026-08-22.** It had not in fact reached Task 05 — that plan contained no
  > mention of the variable or of sub-run governance — so the item was owned by nobody
  > while both plans read as though it were owned. It is now recorded in
  > [05](05_governance_orchestrator.md) §3 as an explicit open question owned there. The
  > *stub's current behaviour* needs no plan at all: it is permanently documented in
  > `docs/reference/environment_variables.md`, `docs/reference/file_formats.md` and
  > `docs/concepts/architecture.md` (all three languages) as **inert — reserved, no
  > reader**. What stays open is only the design question of whether sub-run spawning is
  > governed at all.
- **Timeout/retry hazards**: `generate_ideas` is a `_SLOW_TOOLS` member (1 h); adapter calls
  under the 3-retry policy must be idempotent (content-keyed dedup) or results get duplicated.
- **Snapshot/gate friction**: three new committed prompt templates touch all four
  prompt-snapshot layers; budget one blessing cycle.
- **Docs/CI hygiene**: new checkpoint filenames and config keys, once documented under
  `docs/reference/`, are SemVer-frozen — decide the documented subset deliberately (Task 00
  open question).

## 11. Completion criteria

This task is complete when all of the following hold:

1. **ProposalRecord design exists**: schema (§6.1) finalized with the mandatory common record
   fields (`record_id, epoch_id, component_id, prompt_hash, role, created_at, source_refs,
   status`) plus `stale`/`valid_for_frontier`, reviewed for consistency with Task 02's
   EpochState/PromptRegistry field conventions (`prompt_hash` = existing `hash12`; no second
   hash scheme).
2. **ProposalSummaryView design exists**: schema (§6.2) finalized with exactly the eight
   spec-mandated fields (title, short description, hypothesis, minimal experiment plan,
   success metric, novelty risks, expected artifacts, dissent summary) plus size budgets and
   the rendered-context budget matching today's `_build_idea_ctx_for_expand` channel.
3. **ProposalRouter design exists**: the five-generator registry, the deterministic routing
   policy, the four trigger events mapped to concrete existing hooks, per-epoch call budgets,
   and both invocation surfaces (root; expansion recording) are specified, including
   degradation behavior (router failure ⇒ status quo, run continues).
4. **VirSciAdapter design exists**: normalization mapping from the 9-key `generate_ideas`
   contract to ProposalRecord, archive_refs layout, MCP-only/no-core-VirSci-deps rule, and the
   Stage-0 tool-registration fix are specified with their tests.
5. **VirSci optionality is stated**: the full `virsci.enabled=false` guarantee list is
   reproduced with a concrete mechanism per guarantee, and the mode × VirSci four-combination
   matrix (including the deliberate `simple_bfts` inertness of `proposal_router.*`) is
   documented.
6. **Staged idea.json compatibility plan exists**: Stages 0–4 (§8) are defined, grounded in
   the verified writer/consumer list, with per-stage rollback and the compatibility invariants
   (`ideas[0]` directive, pinned-in-front, one-shot markers, single-writer discipline,
   degrade-never-block) explicitly carried through every stage.
7. **Archive-vs-summary split is specified**: "BFTS sees ProposalSummaryView only; full VirSci
   transcripts are archive-only" with its three deterministic enforcement layers (§5.5),
   including the Task 04 kernel-check surface.
8. Open questions raised here are resolved in this plan or explicitly forwarded (Task 05:
   sub-run governance / `ARI_DISABLED_TOOLS_FOR_CHILD`; Task 07: router-internal generation
   and prompt evolution; Task 10: stale-flag consumption; Task 12: summary budget tuning and
   VirSci call budgets).

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

- ProposalRecord schema implemented (schema file + dataclass + store).
- ProposalSummaryView is what is passed to BFTS (the `ari_rqgm` expand-context channel renders
  summaries only).
- idea.json compatibility preserved (projection conforms to the 9-key contract; all existing
  consumers work unchanged; `simple_bfts` behavior byte-compatible).
- VirSciAdapter implemented.
- ARI-RQGM works with `virsci.enabled=false`.
- Tests pass without VirSci installed (submodule absent, heavy deps absent).
- Full transcripts are archive-only (enforced by test, not convention).
- VirSci integration policy moved to permanent docs (VirSci integration guide + schema
  reference + execution mode guide).

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

- [ ] `survey`/`generate_ideas` MCP registration restored and guarded by an
      `mcp.list_tools()`-level regression test (Stage 0).
- [ ] ProposalRecord / ProposalSummaryView schemas implemented and validated in CI.
- [ ] `ari_rqgm` expand context rendered from ProposalSummaryView only; archive content
      proven absent from prompts by test.
- [ ] `idea.json` projection round-trip test green; `simple_bfts` default run creates no
      `proposals/` directory.
- [ ] Four-combination (mode × VirSci) smoke matrix green, including the no-VirSci
      environment job.
- [ ] `proposals/*` filenames registered in `META_FILES`/`_TRACE_FILES`/node-report
      blocklists.
- [ ] VirSci integration policy, ProposalRecord/SummaryView schemas, and the idea.json
      projection contract migrated to permanent docs (VirSci integration guide, schema
      reference, migration guide).
