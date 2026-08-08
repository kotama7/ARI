# Task 10: FrontierRepair and Selective Erasure

> **Status**: planned · **Depends on**: 00, 02, 04, 09 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

> **Implemented amendment (2026-07-28):** T16 now forms a forced emergency
> boundary with a fresh epoch fingerprint. References below to T16 as a
> mid-epoch exception describe the earlier plan and are superseded by the
> permanent architecture documentation.

## 1. Purpose

When the RegistryTransitionEngine (Task 09) retires a prompt, every record that was produced
by — or transitively depends on — that prompt is contaminated evidence: it must no longer
influence which BFTS node is selected, expanded, or retired. This task designs the
**FrontierRepairEngine** and the **selective erasure** mechanism that:

1. traces all records dependent on a retired `prompt_hash`,
2. marks them `stale=true` / `valid_for_frontier=false` **without deleting anything physically**,
3. rebuilds the BFTS frontier so that stale records contribute zero influence to frontier
   scoring, node selection, and retire rules, and
4. gives the ConstitutionalKernel (Task 04) a deterministic check that no stale or
   retired-prompt-derived record is ever consulted by frontier scoring again
   (global invariants 12 and 13).

This is the ARI redesign of the RQGM paper's slot-scoped utility erasure: erasure is a
*correctness* requirement (never mix utility evidence produced under a displaced evaluator into
the next epoch's search), not a cleanup feature. Erasure is logical, never physical: ARI's
stores are append-only JSONL, CoW memory, and contract-frozen JSON snapshots, so the only
admissible mechanism is flagging plus read-time exclusion.

## 2. Scope

- Definition of **logical staleness**: the `stale` / `valid_for_frontier` semantics on RQGM
  records (ProposalRecord, ReviewRecord, RawAttackRecord, DefenderResponse, JudgmentRecord,
  ValidatedAttackRecord, UtilityRecord) and on BFTS `Node`s (via `Node.metrics` sentinel keys).
- **Dependency tracing**: the deterministic algorithm that computes the stale closure from a
  set of retired `prompt_hash` values, using the record fields mandated by Task 02
  (`record_id`, `prompt_hash`, `role`, `epoch_id`, `source_refs`) and ARI's node lineage
  (`Node.ancestor_ids`, `parent_id`).
- **Per-role erasure policy**: what staleness of a generator / reviewer / adversary / defender /
  judge record means for the node that carries it (invalidate vs recompute utility).
- **Frontier rebuild**: a pure, deterministic `rebuild_frontier` function grounded in how the
  frontier actually exists today (an in-memory `list` inside `_run_loop`, reconstructible from
  `tree.json`), including the parent-reinstatement rule when a Rule-A-winning child is erased.
- **Schemas**: `SelectiveErasureEvent`, `FrontierRebuildEvent`, and the derived
  `rqgm_erasure_state.json` snapshot.
- **Kernel integration**: the `validate_selective_erasure` / `validate_frontier` checks and the
  epoch-boundary failure posture (conservative re-repair, then drain-only degradation).
- **Mode gating**: the engine exists only under `ari.mode: ari_rqgm` with `rqgm.enabled: true`;
  `simple_bfts` behavior is byte-identical to today.

## 3. Non-goals

- **Deciding retirement.** Which prompts/components retire is Task 09 (RegistryTransitionEngine)
  fed by Task 05 (GovernanceOrchestrator). This task consumes an already-validated
  `EpochTransition` with a non-empty `retirements` list.
- **Physical deletion or compaction of any store.** No JSONL rewriting, no tombstone GC, no
  Letta memory deletion, no pruning of `tree.json` nodes. Stale nodes remain in the tree as
  parents, history, and audit material.
- **Clean-room regeneration** of successors for retired prompts (Task 08).
- **Memory-layer erasure.** Letta memory is CoW/append-only; this task only *publishes* the
  stale node-id set in `rqgm_erasure_state.json`. Whether `search_memory` /
  `get_verified_context` consumers filter on it is a follow-up decision for Task 02/12; it is
  currently recorded only **here**, as an open question of this plan, and per §12/§13 it must
  be moved into the Task 02/12 plans (or permanent docs) before this file is deleted — not
  silently dropped.
  > **SETTLED (2026-07-30, permanent docs).** The `get_verified_context` half is decided and
  > recorded in `docs/concepts/rqgm_architecture.md` (invariant 6): `select_best_node` — the
  > function that picks the paper candidate, the archive seed, and the `verified_context.json`
  > lineage — excludes `_valid_for_frontier: False` nodes unconditionally, and returns no
  > winner when every candidate is erased (hard-exclude; the `should_prune` precedent). The
  > `search_memory` half is settled CALLER-SIDE (same date): the paper lineage drops
  > known-erased ancestors before `get_verified_context` (`build_verified_context` — erasure
  > never propagates to descendants, so a valid winner can carry an erased ancestor), and the
  > per-node working-context injection drops erased ancestor ids before `get_node_memory` /
  > `search_memory` (via the `rqgm_erasure_state.json` rollup read through the
  > rqgm-import-free checkpoint shim; absence == nothing stale). The skill half is settled
  > too (same date): `ari-skill-memory` reads this rollup itself — the cross-package file
  > contract this section published it for — and the decision between hard-exclude and
  > annotate is **annotate for PULL, hard-exclude for PUSH**. Rationale: erasure withdraws
  > the STANDING of a judgment (the generator that proposed the direction, or the policy that
  > scored it, was retired), not the facts an experiment measured, so a caller that
  > deliberately names an erased node gets its entries LABELLED (`erased` /
  > `erasure_event_id` / `erasure_note`) rather than silently emptied — an invalidated
  > measurement is still the honest record of what was tried, and a paper's limitations
  > section may legitimately need it. Every path that PUSHES memory into a decision keeps
  > hard-excluding: grounded paper claims (`get_verified_context`, filtered on both sides),
  > the "established conclusions" working-context injection, and best-node selection.
  > The skill imports no `ari` module and makes no LLM call; absence, malformed content, or a
  > newer `schema_version` all degrade to "nothing is stale". A cross-package contract test
  > pins the `invalid_frontier_node_ids` field name on both sides, so a rename cannot
  > silently turn the skill's awareness into dead code.
- **Epoch definition and freeze mechanics** (Task 02) and the epoch-boundary hook plumbing in
  `_run_loop` (Tasks 05/09). This task specifies only the repair step invoked from that hook.
- **Cross-run erasure.** v1 scope is one checkpoint. Propagation to child runs spawned via
  `fanout`/`switch_to_idea` is deferred (additive `meta.json` fields are the known channel; see
  Risks).

## 4. Existing ARI touchpoints

All paths are repo-relative (verified to exist on branch `RQGM`).

| Touchpoint | Why it matters here |
|---|---|
| `ari-core/ari/cli/bfts_loop.py` — `_run_loop` | The frontier is a plain in-memory `frontier: list` local to this function. Retire Rule A (child beats parent), Rule B (`max_expansions_per_node` via `bfts.expansion_count`), and the sterile gate all mutate it in step (e) on the main thread. The epoch-boundary hook (Tasks 05/09) at the outer `while` head is where `repair()` runs; `frontier[:] = ...` in-place replacement is the rebuild channel. `_save_tree_incremental(force=True)` is the persistence flush to reuse after repair. |
| `ari-core/ari/orchestrator/bfts.py` — `BFTS.should_prune`, `BFTS._fallback_score`, `BFTS._select_fallback`, `BFTS.expansion_count` | `should_prune` already reads the `metrics["_sterile"]` sentinel — the precedented, least-invasive veto channel. Frontier scoring (`_fallback_score` strategies) and selection fallbacks must never see stale nodes; the metrics-sentinel convention reaches all of them without modifying ranking logic. `_expansion_count` is in-memory only (empty after resume) — rebuild must not depend on it. |
| `ari-core/ari/orchestrator/node.py` — `Node`, `Node.to_dict`, `ancestor_ids`, `metrics` | `metrics` is a free dict serialized into `tree.json`, so `_stale`-family sentinel keys persist across resume additively (contract-safe). `ancestor_ids`/`parent_id`/`children` are the node-lineage edges used by node-level tracing and by the Rule-A reinstatement re-check. |
| `ari-core/ari/checkpoint.py` — `save_tree_incremental`, `load_nodes_tree`, `JsonCheckpointStore` | `tree.json` is the durable form of the frontier's inputs; resume reconstructs `Node`s from it. The byte-fixed triple contract (names, key order, `indent=2, ensure_ascii=False`) is additive-only. A `save_erasure_state_json` shim follows the `save_prompt_versions_json` pattern. |
| `ari-core/ari/cli/run.py` — `resume` | Resume rebuilds only a subset of node state and empties BFTS in-memory counters; the erasure state snapshot plus metrics sentinels must be sufficient for `rebuild_frontier` to reproduce the post-repair frontier deterministically on resume. |
| `ari-core/ari/paths.py` — `PathManager.META_FILES`, `_TRACE_FILES` | New checkpoint-root files (`rqgm_erasure_state.json`; erasure/rebuild events in the Task 02 audit JSONL) must be registered here (plus node_report blocklists) or they contaminate node work dirs and `files_changed`. |
| `ari-core/ari/protocols/stores.py` | Home of the `ErasureStateStore` Protocol (next to `CheckpointStore`/`TraceStore`), matching the Protocol + module-shim pattern. |
| `ari-core/ari/prompts/_provenance.py` — `hash12`, `record_prompt_use`; `ari-core/ari/prompts/registry.py` — `PromptRegistry`, `PromptEntry` | `hash12 = sha256(text)[:12]` is the **single** prompt-hash scheme; retired-prompt matching keys on exactly this value. `prompt_trace.jsonl` already records which prompt hash produced which LLM output (with `node_id`), a secondary evidence source for tracing generator-derived nodes. |
| `ari-core/ari/orchestrator/lineage_decision.py` — `append_decision_log`; `ari-core/ari/cli/lineage.py` | The append-only, self-contained-record, never-raise JSONL discipline that `SelectiveErasureEvent`/`FrontierRebuildEvent` logging must copy. |
| `ari-core/ari/orchestrator/node_report/builder.py` — `_FILES_CHANGED_BLOCKLIST_NAMES` | Blocklist registration for the new checkpoint-root file. |
| `ari-core/ari/evaluator/llm_evaluator.py` — `_scientific_score`, `_axis_scores` | Utility recomputation after reviewer/judge erasure must reproduce composites under the *original* epoch's frozen weights (recorded in the UtilityRecord per Task 02), never re-score under new policy. |
| `ari-core/ari/trace_store.py` — `JsonlTraceStore` | Dormant per-node `trace.jsonl` seam; per-node staling annotations may adopt it, but v1 keeps staleness centralized in the erasure state + metrics sentinels. |
| `ari-core/ari/config/__init__.py` — `ARIConfig`, `BFTSConfig` | `frontier_repair` config lives inside the typed `RQGMConfig` block introduced by Task 01 (raw `rqgm:` YAML is filtered out of the typed cfg today). |
| `ari-core/ari/viz/api_orchestrator.py` — launch gates, `meta.json` writer | The channel for (deferred) cross-run erasure propagation via additive `meta.json` fields. |

## 5. Proposed design

### 5.1 Principles

- **P-A. Erasure is logical.** No byte of any existing store is rewritten or removed. Staleness
  is (i) appended events in the RQGM audit log, (ii) a derived snapshot
  (`rqgm_erasure_state.json`), and (iii) additive `Node.metrics` sentinels persisted through
  `tree.json`. "JSONL is truth, snapshot is derived rollup" (the `prompt_trace` →
  `prompt_versions` precedent).
- **P-B. Slot-scoped, not lineage-scoped.** Retiring a reviewer prompt stales that reviewer's
  records and their downstream utility consequences — it does not stale unrelated work on the
  same node, and it does not automatically stale a node's descendants (their proposals came
  from their own expand calls; one-child-per-expand invariant).
- **P-C. Deterministic and pure where it counts.** Dependency tracing and `rebuild_frontier`
  are pure functions of (records, nodes, erasure state, config) — no LLM, no wall clock in any
  decision or hash (P2). LLMs play no role anywhere in this task.
- **P-D. Never mix utility evidence across epochs.** Recomputed utilities use the original
  epoch's frozen scoring rule; if that cannot be honored, the node becomes frontier-invalid
  rather than re-scored under a different policy (RQGM paper: erase, don't re-scale).
- **P-E. simple_bfts untouched.** In `simple_bfts` mode the engine is never constructed, no
  sentinel key is ever written, and the (inert) `should_prune` extension can never fire.

### 5.2 Trigger and placement

`FrontierRepairEngine.repair()` runs exactly once per applied `EpochTransition` with
`retirements != []`, inside the epoch-boundary block in `_run_loop` (main thread, between
batches — no in-flight nodes), strictly after `ConstitutionalKernel.validate_transition` and
`RegistryTransitionEngine.apply` (Task 09) and strictly before the next epoch's active-set
freeze (Task 02). Ordering within the boundary transaction:

```
apply(transition)                          # Task 09
→ repair(transition, frontier, all_nodes)  # this task
→ kernel.validate_selective_erasure(...)   # Task 04 check, run here
→ kernel.validate_frontier(frontier)
→ freeze_active_components(next_epoch)     # Task 02
```

Emergency quarantine (Task 09's sole mid-epoch exception) does **not** trigger erasure
mid-epoch; a quarantined component's records are staled only if/when the quarantine becomes a
retirement at the next boundary. Invariant 12 requires staleness *before next-epoch scoring*,
which the boundary placement satisfies.

### 5.3 Dependency tracing

Inputs: `retired_prompt_hashes: set[str]` (hash12 values) and `retired_component_ids`
extracted from `transition.retirements`; the RQGM record store (Task 02/03/06 records, all
carrying `record_id`, `prompt_hash`, `role`, `epoch_id`, `source_refs`, and a node anchor
field — `source_node_id` or equivalent); the node list from `tree.json`/`all_nodes`.

Algorithm (pure; two indexes built once per repair):

```python
def trace_dependents(retired_hashes, records) -> DependencyClosure:
    by_hash  = index(records, key=lambda r: r.prompt_hash)         # producer index
    by_ref   = reverse_index(records, key=lambda r: r.source_refs) # consumer index

    direct = {r.record_id for h in sorted(retired_hashes)
                          for r in by_hash.get(h, [])}             # produced BY retired prompt
    frontier_set, closure = deque(sorted(direct)), set(direct)
    while frontier_set:                                            # BFS over reverse refs
        rid = frontier_set.popleft()
        for dep in by_ref.get(rid, []):                            # records CITING a stale record
            if dep.record_id not in closure and depends_materially(dep, rid):
                closure.add(dep.record_id); frontier_set.append(dep.record_id)
    return DependencyClosure(direct=direct, transitive=closure - direct)
```

- **Materiality rule** (`depends_materially`): a consumer is staled only when the stale input is
  *load-bearing* for its conclusion, decided by record type, not content. `source_refs` is the
  flat list of record-id strings defined by Task 02's `rqgm_record_base` (no per-entry
  metadata), so materiality is a pure function of the *(consumer record type, referenced record
  type)* pair, looked up in a fixed table owned by this task: a `JudgmentRecord` citing a stale
  `RawAttackRecord` or `DefenderResponse` → stale; a `UtilityRecord` citing a stale
  `ReviewRecord`/`ValidatedAttackRecord` → stale (its penalty/bonus derived from it); type
  pairs the table designates as background *context* (e.g. a `ProposalRecord` citing an
  ancestor's `ProposalRecord` only as inspiration — consistent with P-B slot-scoping) → not
  staled. Default for any pair not in the table: load-bearing (conservative). The tracer
  resolves each referenced `record_id` to its record type via the record store.
- **Determinism**: sets are iterated in sorted order; the closure is a pure function of the
  record graph. Cycles are tolerated (visited-set BFS). Records already stale from a previous
  erasure are skipped idempotently.
- **Secondary evidence**: `prompt_trace.jsonl` (`prompt_name`, `template_hash`, `node_id`)
  cross-checks the producer index — a kernel-level consistency assertion (every trace line with
  a retired hash after that prompt's activation window must map to a record in `direct`), not a
  second source of truth.

### 5.4 Per-role erasure policy (record → node consequences)

For every node touched by the closure, the engine decides between **invalidate** and
**recompute**:

| Retired role | Stale records | Node consequence |
|---|---|---|
| generator / router / prompt-side of expand | `ProposalRecord` (and its `ProposalSummaryView` projection) | **Invalidate**: the node's very direction came from the retired prompt → `_valid_for_frontier=False`. Node stays in the tree; descendants are *not* auto-staled (P-B) but lose Rule-A protection from this node (see 5.5). |
| reviewer | `ReviewRecord` → dependent `UtilityRecord` | **Recompute**: rebuild utility from surviving inputs (fixed-verifier results, `results.json` merge, non-stale reviews/attack penalties) under the original epoch's frozen weights. If no valid utility survives (the review was the sole scored evidence), invalidate. |
| adversary / defender | `RawAttackRecord` / `DefenderResponse` → dependent `ValidatedAttackRecord` → `UtilityRecord` | **Recompute**: reverse the attack-derived penalty by recomputation (never by arithmetic un-scaling of the stored score — recompute from surviving inputs). |
| judge | `JudgmentRecord` / `ValidatedAttackRecord` | **Recompute**; attacks lose "validated" status (a raw attack without adjudication cannot touch score — invariant 8/9), so their penalties drop out. |
| utility policy | `UtilityRecord`s scored under the retired policy | **Invalidate** for frontier purposes (P-D: no re-scoring under a different policy). |

Recomputation is performed by the **MetricRecomputer** (Layer 0, non-evolving; Task 04) and
produces a *new* UtilityRecord (`supersedes: <old record_id>`, new `record_id`, current
`epoch_id` in a `recomputed_in_epoch` field, original epoch's weights recorded) — the old one
stays on disk, stale. Sentinel effects on the node: `metrics["_scientific_score"]` /
`_axis_scores` are overwritten in memory and re-persisted via the normal incremental save
(metrics values are run state, not an append-only store; `tree.json` is a rewrite-snapshot by
contract, so this is not physical erasure of a record).

### 5.5 Frontier rebuild

Today's frontier is *procedural* state: a list mutated by Rules A/B and the sterile gate. To
repair it correctly (including reinstating a parent whose Rule-A-winning child was erased), the
engine recomputes it declaratively:

```python
def rebuild_frontier(all_nodes, erasure_state, cfg) -> list[Node]:
    def eligible(n):
        return (n.status in (SUCCESS, FAILED)
                and n.metrics.get("_valid_for_frontier", True)
                and not n.metrics.get("_stale", False)
                and n.metrics.get("_sterile") is not True
                and n.depth < cfg.bfts.max_depth
                and len(n.children) < cfg.bfts.max_expansions_per_node)  # Rule B (see note)

    def dominated(n):  # Rule A re-check against VALID children only
        return any(c.metrics.get("_scientific_score", 0.0) > n.metrics.get("_scientific_score", 0.0)
                   for c in valid_children(n))

    return sorted((n for n in all_nodes if eligible(n) and not dominated(n)),
                  key=lambda n: n.id)  # deterministic order
```

Notes and decisions:

- **Rule B without in-memory counters**: `BFTS._expansion_count` is lost on resume; the
  one-child-per-expand invariant makes `len(node.children)` an exact, persistent proxy for the
  expansion count. Documented as the durable Rule-B source for rebuilds (running-loop Rule B in
  step (e) is unchanged).
- **Reinstatement rule**: `dominated()` considers only valid (non-stale, frontier-valid)
  children — a parent retired by Rule A because a now-erased child beat it re-enters the
  frontier automatically. This is the concrete meaning of "exclude their influence".
- **In-place replacement**: `frontier[:] = rebuilt` on the main thread at the boundary;
  `pending` is left untouched *except* that pending children whose proposal record went stale
  (generator retirement) are removed from `pending` and marked
  `ABANDONED` + `_stale=True` before they ever run (cheaper and cleaner than executing a
  direction authored by a retired generator). ABANDONED is an existing `NodeStatus`.
- **BFTS internal state**: `_recent_label_history` and `_expansion_count` are advisory
  (diversity bonus, Rule B duplicate) and are left as-is; the rebuild does not depend on them.
- After rebuild: `_save_tree_incremental(force=True)`, then append the `FrontierRebuildEvent`.

### 5.6 Kernel checks and failure posture

`ConstitutionalKernel.validate_selective_erasure(frontier, records, prompt_registry)` (Task 04)
asserts, deterministically:

```python
retired = prompt_registry.retired_hashes()
for node in frontier:
    assert node.metrics.get("_stale", False) is False
    assert node.metrics.get("_valid_for_frontier", True) is True
for record in records.frontier_scoring_inputs(frontier):
    assert record.stale is False and record.valid_for_frontier is True
    assert record.prompt_hash not in retired
# closure completeness: every record produced by a retired hash is in the stale set
assert records.by_hash(retired).issubset(erasure_state.stale_record_ids)
```

Failure posture (a deliberate, documented deviation from the fail-open hook discipline,
justified because invariant 12 is a correctness property, and scoped to the boundary where no
node is in flight):

1. Validation fails → **conservative re-repair**: every flagged node is dropped from the
   frontier outright (no recompute), event logged with `status: "conservative"`.
2. Still failing → **degrade to drain-only**: set the same internal flag the
   `frontier_expand`-disabled path uses (`_expand_enabled = False`), so the run finishes
   pending work but performs no further expansion; log
   `FrontierRebuildEvent(status="halted_expansion")`. The run never crashes (I-2 preserved in
   spirit: degrade, don't die — but degrade *closed* with respect to contaminated influence).

### 5.7 Mode gating and VirSci

- Constructed in `build_runtime` only when `cfg.ari.mode == "ari_rqgm"` and
  `cfg.rqgm.enabled` (Task 01 wiring). Under `simple_bfts`: no engine, no sentinel writes, no
  new files; the `should_prune`/eligibility reading of `_stale`-family keys is dead code
  because the keys never exist (same pattern as `_sterile` for runs without the sterile
  condition).
- VirSci needs no special path: VirSci-originated `ProposalRecord`s carry `prompt_hash`es
  registered like any other (Task 03), so retirement of a VirSci-side prompt stales them
  through the identical closure. With `virsci.enabled=false` nothing here changes; no VirSci
  import, prompt, or snapshot is required by this engine (invariant 19).

## 6. Data structures / schema changes

All records carry the Task 02 common envelope (`record_id`, `epoch_id`, `component_id`,
`prompt_hash`, `role`, `created_at`, `source_refs`, `status`). Erasure/rebuild events are
kernel-authored (no LLM prompt), so their `prompt_hash` is `null` and `component_id` is
`"frontier_repair_engine"`.

**SelectiveErasureEvent** (appended to the Task 02 RQGM audit JSONL):

```json
{
  "record_id": "erase_00007",
  "record_type": "SelectiveErasureEvent",
  "epoch_id": "epoch_004",
  "component_id": "frontier_repair_engine",
  "prompt_hash": null,
  "role": "kernel",
  "created_at": "2026-07-05T00:00:00Z",
  "source_refs": ["retire_00042", "transition_004_to_005"],
  "status": "applied",
  "retired_prompt_hashes": ["a1b2c3d4e5f6"],
  "retired_component_ids": ["reviewer_v3"],
  "direct_stale_record_ids": ["review_00311", "review_00317"],
  "transitive_stale_record_ids": ["utility_00311", "vattack_00090"],
  "invalidated_node_ids": [],
  "recompute_node_ids": ["node_017", "node_023"],
  "abandoned_pending_node_ids": [],
  "trace_stats": {"records_scanned": 412, "closure_size": 4, "max_ref_depth": 2}
}
```

**FrontierRebuildEvent** (same log):

```json
{
  "record_id": "rebuild_00007",
  "record_type": "FrontierRebuildEvent",
  "epoch_id": "epoch_005",
  "component_id": "frontier_repair_engine",
  "prompt_hash": null,
  "role": "kernel",
  "created_at": "2026-07-05T00:00:01Z",
  "source_refs": ["erase_00007"],
  "status": "applied",
  "frontier_before": ["node_012", "node_017"],
  "frontier_after": ["node_009", "node_012"],
  "removed_node_ids": ["node_017"],
  "reinstated_node_ids": ["node_009"],
  "recomputed_utility_node_ids": ["node_023"],
  "kernel_validation": "passed"
}
```

`status` values for both: `applied | conservative | halted_expansion`.

**`rqgm_erasure_state.json`** (checkpoint root; derived rollup, rebuildable by folding all
erasure/rebuild events; rewrite-snapshot with `indent=2, ensure_ascii=False`):

```json
{
  "schema_version": 1,
  "retired_prompt_hashes": {"a1b2c3d4e5f6": {"retirement_event_id": "retire_00042",
                                              "retired_in_epoch": "epoch_004"}},
  "stale_record_ids": {"review_00311": "erase_00007"},
  "invalid_frontier_node_ids": {"node_031": "erase_00007"},
  "last_erasure_event_id": "erase_00007",
  "last_rebuild_event_id": "rebuild_00007"
}
```

**Node metrics sentinels** (additive keys inside the free `metrics` dict; persisted through
`tree.json` automatically; never written in `simple_bfts`):

- `_stale: true` — some scoring-relevant record of this node is stale;
- `_valid_for_frontier: false` — node excluded from frontier eligibility (absence ⇒ valid);
- `_stale_reason: "generator_retired" | "utility_invalidated" | ...`;
- `_erasure_event_id: "erase_00007"`.

**Record-side fields** (Task 02 schema additions this task requires): `stale: bool`
(default `false` — *logical* field: materialized only in the erasure state, never rewritten
into stored JSONL lines; readers derive it as `record_id ∈ stale_record_ids`),
`valid_for_frontier: bool` with the same read-time semantics, `supersedes: record_id | null`
on UtilityRecord, and `recomputed_in_epoch: epoch_id | null` on UtilityRecord. No change to
`source_refs` is requested: it remains the flat list of record-id strings defined by Task 02's
`rqgm_record_base` `$defs`; the materiality rule (§5.3) needs only record types, which the
tracer derives by resolving each referenced `record_id` in the record store.

**Config** (inside Task 01's typed `RQGMConfig`; all defaults inert):

```yaml
rqgm:
  frontier_repair:
    enabled: true            # meaningful only when ari.mode == ari_rqgm
    max_trace_depth: 8       # BFS cap; exceeding it => conservative invalidate
    recompute_utilities: true  # false => invalidate instead of recompute
    abandon_stale_pending: true
```

**JSON schemas**: `selective_erasure_event.schema.json`, `frontier_rebuild_event.schema.json`,
`erasure_state.schema.json` beside `ari-core/ari/schemas/node_report.schema.json`, loadable via
`ari.schemas.load`. File registration: `rqgm_erasure_state.json` → `PathManager.META_FILES` +
node_report blocklists; the audit JSONL is registered by Task 02.

## 7. API / class changes

New module (proposed home `ari-core/ari/rqgm/frontier_repair.py`; kept **out of `ari.public.*`**
to avoid contract-snapshot churn):

```python
@dataclass(frozen=True)
class DependencyClosure:
    direct: frozenset[str]        # record_ids produced by retired hashes
    transitive: frozenset[str]    # record_ids stale via source_refs BFS
    invalidated_node_ids: frozenset[str]
    recompute_node_ids: frozenset[str]

@dataclass(frozen=True)
class RepairResult:
    erasure_event: SelectiveErasureEvent | None   # None when retirements == []
    rebuild_event: FrontierRebuildEvent
    status: Literal["applied", "conservative", "halted_expansion", "noop"]

class FrontierRepairEngine:
    def __init__(self, *, cfg: RQGMConfig, kernel: ConstitutionalKernel,
                 records: RecordStore, erasure_state: ErasureStateStore,
                 audit_log: RQGMAuditLog, recomputer: MetricRecomputer): ...

    def repair(self, *, transition: EpochTransition, frontier: list[Node],
               pending: list[Node], all_nodes: list[Node],
               checkpoint_dir: Path) -> RepairResult:
        """Trace → stale → recompute/invalidate → rebuild → validate. Main thread only."""

# pure helpers (unit-test surface, no I/O):
def trace_dependents(retired_hashes: set[str], records: Sequence[Record],
                     *, max_depth: int) -> DependencyClosure: ...
def rebuild_frontier(all_nodes: Sequence[Node], erasure_state: ErasureStateView,
                     cfg: BFTSConfig) -> list[Node]: ...
```

Supporting changes:

- `ari-core/ari/protocols/stores.py`: add `ErasureStateStore` Protocol
  (`load() -> ErasureStateView`, `save(state) -> None`, `apply_event(event) -> None`) next to
  `CheckpointStore`/`TraceStore`; concrete impl in `ari-core/ari/rqgm/erasure_state.py`
  following the `ari/checkpoint.py` module-shim style, with the JSON write funneled through a
  new `ari/checkpoint.py:save_erasure_state_json` shim.
- `ari-core/ari/orchestrator/bfts.py:BFTS.should_prune`: one additive clause —
  `metrics.get("_valid_for_frontier", True) is False` ⇒ prune (mirrors the `_sterile` read;
  inert in `simple_bfts` because the key never exists).
- `ari-core/ari/cli/bfts_loop.py`: inside the Task 05/09 epoch-boundary block, call
  `engine.repair(...)` and apply `frontier[:]`/`pending` edits + forced incremental save. No
  new CLI surface (keeps contract snapshots green).
- `ConstitutionalKernel` (Task 04): `validate_selective_erasure(...)` implemented against the
  data structures above; this plan supplies the assertion set (§5.6), Task 04 owns the class.

## 8. Migration / compatibility

- **`simple_bfts` is byte-identical to today.** The engine and its stores are constructed only
  under `ari_rqgm`; no sentinel keys, no new files, no behavior change in `should_prune`
  (missing-key defaults reproduce current outcomes exactly). Regression-tested (§9).
- **No store format breaks.** `tree.json`/`nodes_tree.json`/`results.json` gain nothing except
  values inside the already-free `metrics` dict (additive; GUI and paper pipeline readers
  ignore unknown metric keys, as with `_sterile`). Records JSONL is append-only; staleness is
  never written back into existing lines.
- **Resume-safe.** Sentinels persist in `tree.json`; `rqgm_erasure_state.json` persists the
  hash/record sets; `rebuild_frontier` is a pure function of persisted data, so the
  post-repair frontier is reproduced identically after `resume` (which already reconstructs the
  frontier from `tree.json`). Rule B uses `len(children)`, not the in-memory counter.
- **Old checkpoints.** Runs created before this feature simply lack the state file and
  sentinels; every read path treats absence as "nothing stale, all valid" — the `load_prompt_trace`
  "absence = no data, never an error" discipline.
- **Rollback.** Disabling `ari_rqgm` on a checkpoint that already contains erasure state is
  allowed only at run start (invariant 20); in `simple_bfts` the sentinels are then still
  honored by the additive `should_prune` clause? **No** — decision: the clause is gated on
  `rqgm.enabled` at construction time being irrelevant (keys read unconditionally), so a
  previously-erased node stays excluded even after a mode switch back. This is deliberate:
  contamination does not become clean by switching modes. Documented in the migration guide.
- **VirSci**: no dependency in either direction; all four mode×VirSci combinations behave as
  specified in Task 01.

## 9. Tests

Unit (pure, no I/O):

1. `trace_dependents`: direct hits by retired hash; transitive closure through
   `source_refs`; context-designated type pairs (§5.3 materiality table) not staled; cycle
   tolerance; idempotence on already-stale
   inputs; `max_trace_depth` overflow ⇒ conservative invalidate; deterministic output ordering.
2. `rebuild_frontier`: excludes `_stale`/`_valid_for_frontier=False`/`_sterile` nodes;
   Rule-A **reinstatement** of a parent whose winning child is erased; Rule B via
   `len(children)`; deterministic (same inputs ⇒ identical list, twice); depth cutoff honored.
3. Per-role policy table: generator retirement ⇒ node invalidated + pending child abandoned;
   reviewer retirement ⇒ utility recomputed under original-epoch weights (fixture asserts the
   recomputed UtilityRecord carries `supersedes` and original weights); judge retirement ⇒
   attack penalty drops out; utility-policy retirement ⇒ invalidate (no re-scaling).

Integration:

4. Epoch-boundary smoke (`ari_rqgm`, VirSci off): synthetic transition with one retirement ⇒
   erasure + rebuild events appended, `rqgm_erasure_state.json` written, frontier list mutated,
   `_save_tree_incremental` flushed, kernel validation passes.
5. **No-physical-deletion test**: byte-compare every pre-existing store file
   (records JSONL, audit JSONL, prompt_trace, memory files) before/after `repair()` — only
   appends and the two designated rewrite-snapshots (`tree.json` family, erasure state) may
   change.
6. Kernel detection test: hand-craft a frontier containing a stale node / a record with a
   retired `prompt_hash` ⇒ `validate_selective_erasure` fails; conservative re-repair clears
   it; forced double-failure ⇒ `halted_expansion` degradation (run completes, no crash).
7. Resume test: run → retire → repair → kill → `resume` ⇒ rebuilt frontier identical to
   pre-kill post-repair frontier; erased nodes stay excluded.

Regression (`simple_bfts`):

8. Full existing BFTS loop test suite green with the branch merged; assert no `_stale`-family
   key ever appears in `tree.json` and `rqgm_erasure_state.json` is never created; `META_FILES`
   registration test (new file never appears in node work dirs / `files_changed`).

## 10. Risks

- **Over-erasure cascade**: an aggressive materiality rule could stale most of the frontier and
  stall the search. Mitigations: slot-scoping (P-B), the record-type-pair materiality table
  with its context exemption, reinstatement rule, and Task 13's `frontier_contamination_rate` /
  `recovery_after_selective_erasure` metrics watching exactly this. `max_trace_depth` bounds
  pathological graphs.
- **Recompute correctness drift**: recomputed utilities must match what the original epoch
  would have produced minus stale inputs; requires UtilityRecords to store their input refs and
  frozen weights faithfully (Task 02 dependency). Fixture-based golden tests in §9.3 are the
  guard.
- **Rule-B proxy divergence**: `len(children)` == expansion count holds only while
  one-child-per-expand (I-1) holds; a future multi-child expand would silently change Rule B in
  rebuilds. Add an assertion comment at both sites and a test coupling them.
- **Fail-closed posture is unprecedented in the run loop** (all existing hooks fail open). The
  degradation ladder (§5.6) is designed to never crash, but "halt expansion" is user-visible;
  it must be prominently logged and surfaced in the GUI state. Documented as a deliberate
  deviation.
- **Score-comparability interaction** (bfts_core I-11): recomputation under original-epoch
  weights keeps within-epoch comparability, but cross-epoch `_scientific_score` comparisons in
  stagnation detection remain epoch-relative — owned by Task 02's freeze design and Task 14's
  rewrite design (02 froze the policy per epoch, 14 rewrites it at boundaries); this task must
  not silently re-weight. Cross-epoch comparisons remain epoch-relative **by design**: a rewrite
  invalidates the old regime instead of translating it, and the `utility_policy` member of
  `INVALIDATE_ROLES` (`frontier_repair.py:99-101`) is the enforcement — dead until Task 14 makes
  `utility_policy` a governed registry role, and reachable from then on. Task 14 §5.8 delta 2
  adds two things to this engine: the `_utility_policy_hash` node sentinel (stamped at the
  `wrap_node_executor` seam, never written under `simple_bfts`, following the `:75-80`
  convention), and one repair rule — a retirement whose `role` is `utility_policy` also
  invalidates every node whose `metrics[_utility_policy_hash]` is in `retired_hashes`, with
  `_stale_reason = UTILITY_INVALIDATED_REASON` (the constant already at `:86`).
- **Cross-run leakage**: a child run spawned (fanout) from a node later invalidated in the
  parent keeps running with inherited context. Out of scope for v1 (§3); the mitigation channel
  (additive `meta.json` flags + launch-gate check in `ari-core/ari/viz/api_orchestrator.py`) is
  recorded here so the limitation is explicit, with a decision owed to Task 02/05 before GA.
- **Performance**: closure tracing is O(records + refs) per repair with two dict indexes;
  repairs are epoch-boundary-rare. Not expected to matter below ~10^5 records; `trace_stats`
  in the event give observability if it does.

## 11. Completion criteria

This task is complete when all of the following hold (concretizing the spec's Task 10
criteria):

1. **Erasure-is-not-physical-deletion is defined**: §5.1 P-A and §6 specify that staleness
   lives only in appended events, the derived `rqgm_erasure_state.json`, and additive
   `Node.metrics` sentinels; no existing store line/file is ever rewritten or removed, and the
   byte-compare test (§9.5) is specified to enforce it (invariant 13).
2. **Tracing dependent records from retired `prompt_hash` is defined**: §5.3 gives a
   deterministic, pure, cycle-safe closure algorithm keyed on the existing `hash12` scheme,
   with a record-type-pair materiality rule, a depth bound, and the `prompt_trace.jsonl`
   cross-check — covering ProposalRecord/ReviewRecord/JudgmentRecord/UtilityRecord and the
   adversarial record chain.
3. **A frontier rebuild policy exists**: §5.5 defines the pure `rebuild_frontier` function
   grounded in the actual frontier representation (in-memory list in `_run_loop`, durable form
   `tree.json`), including eligibility rules, the Rule-A reinstatement rule, the durable Rule-B
   proxy, pending-node abandonment, resume determinism, and the in-place replacement +
   forced-checkpoint procedure.
4. Per-role invalidate-vs-recompute policy (§5.4), kernel assertions and the epoch-boundary
   failure posture (§5.6), schemas for `SelectiveErasureEvent` / `FrontierRebuildEvent` /
   erasure state (§6), the engine API (§7), and the mode/VirSci gating (§5.7) are all written
   down and consistent with global invariants 8, 9, 12, 13, 19, 20.
5. Downstream owners can consume this plan: Task 04 (kernel checks), Task 02 (record-envelope
   field additions), Task 09 (boundary ordering), Task 13 (erasure metrics) reference the
   sections above without needing additional design work from this task.

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

Task-specific criteria (from the spec's Task 10 section):

- The `SelectiveErasureEvent` schema is implemented (and `FrontierRebuildEvent` with it).
- The FrontierRepairEngine excludes stale records from the frontier in `ari_rqgm` mode.
- Retired-prompt-dependent records are demonstrably unused in frontier scoring (regression
  test §9.4–9.6 merged and green).
- The ConstitutionalKernel detects stale-record usage in the frontier (test §9.6 merged).
- Tests for tracing, rebuild, no-physical-deletion, resume, and `simple_bfts` regression are
  added and green.
- The erasure/rebuild design decisions (logical-only erasure, per-role policy, reinstatement
  rule, failure posture) have been moved to the permanent architecture/schema reference docs.

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

- [ ] `SelectiveErasureEvent` / `FrontierRebuildEvent` / `rqgm_erasure_state.json` schemas are
      implemented and documented in the schema reference.
- [ ] `rqgm_erasure_state.json` is registered in `PathManager.META_FILES` and node_report
      blocklists (verified by test).
- [ ] The no-physical-deletion byte-compare test is in CI.
- [ ] Kernel stale-usage detection and the boundary failure posture are documented in the
      permanent developer guide.
- [ ] The deferred items (memory read-time filtering, cross-run erasure propagation) have been
      recorded in their owning task plans (02/05/12) or in permanent docs.
