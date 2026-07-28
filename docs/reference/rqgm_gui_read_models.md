---
sources:
  - path: ari-core/ari/viz/v1/rqgm.py
    role: implementation
  - path: ari-core/ari/viz/v1/dto.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/tests/test_gui_v1_rqgm.py
    role: test
last_verified: 2026-07-27
---

# RQGM GUI Read Models

The twelve `GET /api/v1/runs/{run_id}/rqgm/*` endpoints are an **offline
projector** over a checkpoint's committed RQGM artifacts. This page
documents what each payload means, which artifact it came from, and the
truth rules the API enforces so a UI cannot render a governance claim the
evidence does not support.

For the *record shapes* those artifacts contain (schemas, id formats, hash
discipline) see [RQGM Schema Reference](rqgm_schemas.md). For transport
concerns (error envelope, cursors, auth) see
[REST API → `/api/v1`](rest_api.md#apiv1-canonical). For the governance
mechanism itself see [RQGM architecture](../concepts/rqgm_architecture.md).

## Ground rules

The reader (`ari-core/ari/viz/v1/rqgm.py`) is bound by four constraints that
shape every payload on this page:

1. **`ari.rqgm` is never imported.** The read model parses the committed
   checkpoint artifacts directly and re-executes no kernel or score-policy
   decision. The only RQGM arithmetic reproduced is the frozen hash contract
   `event_hash = hash12(canonical_json(payload))`, duplicated deliberately
   because a viz → governance import edge is prohibited; parity with the
   production helpers is pinned by `ari-core/tests/test_gui_v1_rqgm.py`.
2. **Committed records only.** A JSONL trailing partial line (a torn append)
   is silently ignored, and transition events after an
   `epoch_transaction_prepare` with no matching commit are never adopted
   into current state — the mirror of `ari.rqgm.store.committed_events`.
3. **Degraded, never broken.** A broken hash chain or a stale rollup flips an
   integrity flag and appends `degraded_reasons`; a corrupt artifact yields
   HTTP 200 with honest flags, not a 500. A missing source is `None`, never
   displayed as clean or zero.
4. **Read-only.** Nothing writes a file, touches `viz.state` or mutates
   `os.environ`, and there is **no mutation endpoint** — the GUI cannot
   perform governance actions, only observe them.

## Capability gating

`GET .../rqgm/capabilities` is the only RQGM endpoint that answers for a
non-RQGM run. Capability detection is artifact presence, nothing else:

| Signal | Derived from |
|---|---|
| `enabled` | `{ckpt}/rqgm_state.json` exists **and** records `rqgm_enabled` (defaulting to `mode == "ari_rqgm"`). Absent file ⇒ `enabled: false` with reason `"simple_bfts run"`. |
| `mode` / `mode_source` | The persisted `mode` and its provenance in `rqgm_state.json`. |
| `paper_mode` | `{ckpt}/paper_archive_state.json` exists. Execution mode and paper mode are **independent axes**: all four combinations are valid. |
| `reasons` | Why the capability is off / unreadable — never an empty success claim. |

The other eleven endpoints answer the typed `404 not_found` envelope for a
run without `rqgm_state.json` (message: "not an RQGM run … simple_bfts
run"), which is distinct from the `404` for an unknown run id.

## Artifact → endpoint map

The critical distinction is **truth log vs snapshot**: an append-only,
hash-chained log is the source of truth, and a rollup/snapshot file is read
*only to verify* it — never to become current state.

| Endpoint | Truth sources (state comes from here) | Snapshots (verification / provenance only) |
|---|---|---|
| `…/capabilities` | — | `rqgm_state.json`, `paper_archive_state.json` (presence + persisted mode) |
| `…/overview` | `rqgm_transitions.jsonl` (committed replay), `rqgm_audit.jsonl` (chain) | `rqgm_registry.json` (rollup check), `epoch_state.json` (cross-check), `meta.json` (`constitution_hash`) |
| `…/registry` | `rqgm_transitions.jsonl` replay | `rqgm_registry.json` (`as_of_event_hash` comparison only) |
| `…/transitions` | `rqgm_transitions.jsonl` | — |
| `…/audit` | `rqgm_audit.jsonl` | — |
| `…/policies` | `rqgm_transitions.jsonl` replay (`utility_policy`-role prompts) | the registered policy body file referenced by the prompt's `source.path` (hash-verified before it is served) |
| `…/score-rewrites` | `rqgm_transitions.jsonl` (T20 supersessions) joined with `rqgm_audit.jsonl` (`SelectiveErasureEvent` / `FrontierRebuildEvent`) | — |
| `…/nodes/{node_id}/lineage` | `rqgm_adversarial_cases.jsonl`, `rqgm_audit.jsonl`, and the node's `metrics` sentinels via the tree view | — |
| `…/epochs`, `…/epochs/{epoch_id}` | `rqgm_transitions.jsonl` (`epoch_open` payloads + closing boundary entries), `rqgm_audit.jsonl` (`epoch_transition` records for `fallbacks`) | `epoch_state.json` is **not** used as state |
| `…/evolution` | `prompt_evolution.jsonl`, `rqgm_meta_outputs.jsonl`, plus registry replay for the adoption join | — |
| `…/paper-archive` | `paper_draft_archive.jsonl`, `paper_anchor_corpus.jsonl`, `rqgm/paper_self_preference_stat.json`, `full_paper.tex` (presence) | `paper_archive_state.json` (persisted mode + frozen paper policy) |

Two consequences worth internalising:

- `rqgm_registry.json` is a **rollup**, not the registry. `…/registry`
  rebuilds components and prompts by replaying committed transitions and
  reports the rollup only through `verified` /
  `rollup_as_of_event_hash` / `replay_tail_event_hash`.
- `epoch_state.json` never sets `current_epoch`. `…/overview` derives the
  current epoch from the last committed `epoch_open` and, if the snapshot
  disagrees, appends a degraded reason ("snapshot ahead of the truth log").

## Integrity flags and degraded semantics

`…/overview` carries three **tri-state** flags; `…/transitions` and
`…/audit` repeat the relevant one as `chain_ok`:

| Flag | `true` | `false` | `null` |
|---|---|---|---|
| `transitions_chain_ok` | Every line of `rqgm_transitions.jsonl` verifies: `event_hash` covers its payload and `prev_event_hash` chains (the first line from `""`). | A hash mismatch or a chain break was found; scanning continued so the data is still served, flagged. | The file is missing. |
| `registry_verified` | `rqgm_registry.json`'s `as_of_event_hash` equals the committed transitions tail. | The rollup is stale or ahead of the log. | The rollup is missing/unreadable, or there is no transitions tail to compare with. |
| `audit_chain_ok` | `rqgm_audit.jsonl` verifies as an independent chain. | Break found. | The file is missing. |

`null` is a first-class answer: **a missing source is never rendered as
clean.** Alongside the flags, `degraded_reasons` is a bounded list of
human-readable strings (at most three per source) naming the offending event
id and byte offset, e.g.
`"rqgm_transitions.jsonl: hash chain broken at evt_000117 (byte 40213)"`.
Other reasons the reader emits without failing the request: an unparseable
terminated JSONL line (skipped), a status value outside the closed registry
vocabulary (entry excluded from listings and counts), a policy body whose
bytes no longer hash to its registered `prompt_hash` (`body: null` —
refused, never served silently), and `meta.json` carrying no
`constitution_hash`.

## Two vocabularies, two state machines

Registry lifecycle status and node score state are **different state
machines and must never be mixed in one field or one legend**. The DTOs
enforce this structurally: the two literal types are distinct, so no payload
can carry a node score state where a registry status belongs.

**Registry component / prompt lifecycle — 10 values** (verbatim
`ari.rqgm.events.STATUS_VALUES`, a frozen contract):

| Status | Meaning in the read model |
|---|---|
| `candidate` | Registered, not yet validated. |
| `validated` | Passed validation, not yet live. |
| `shadow` | Runs alongside the active component for comparison. |
| `probationary_active` | Live under probation. Counts as **active**. |
| `active` | Live. Counts as **active**. |
| `warning` | Sanction posture. |
| `probation` | Sanction posture. |
| `quarantine` | Sanction posture (also the target of `emergency_quarantine`). |
| `retired` | Withdrawn from service. |
| `banned` | Permanently barred. |

`active` and `probationary_active` form the frozen active set used by
`active_components` / `active_prompt_hashes` (role → id/hash, latest
registration wins in deterministic replay order).

**Node score state — 5 values** (`NodeScoreStateV1`):

| State | Source of the claim |
|---|---|
| `computed` | A `UtilityRecord` for the node, or node metrics without a staleness sentinel. |
| `recomputed` | A `UtilityRecord` with `recomputed_in_epoch`, or the node appearing in an erasure event's `recompute_node_ids`. |
| `stale` | Node metrics carry `_stale` without the invalidation reason. |
| `invalidated` | `_stale_reason == "utility_invalidated"`, or the node listed in a `SelectiveErasureEvent`'s `invalidated_node_ids`. |
| `removed` | Reserved for logical removal from the frontier. The current reader does **not** assert it: a `FrontierRebuildEvent` naming the node is reported as a fact in `values` (`frontier_removed` / `frontier_reinstated` / `recomputed_utility`) with `state: null`, because a frontier event is not a score-state claim. |

`stale` / `invalidated` / `removed` are **logical** states: none of them
means the node was physically deleted, and "Deleted" is not a valid label
for any of them. Physical deletion is a further, separate state that these
payloads do not describe.

## The two score-rewrite channels

A node's score can move for two structurally different reasons. The API
keeps them in **separate lists that no consumer can accidentally merge into
one series** (`…/nodes/{node_id}/lineage` returns `penalty_channel` and
`policy_channel` side by side).

### Channel 1 — adversarial penalty (epoch-internal, node-scoped)

| Aspect | Detail |
|---|---|
| Evidence | `UtilityRecord` (`utl_*`) rows in `rqgm_adversarial_cases.jsonl`, plus the node's `_pre_penalty_score` / `_validated_attack_penalty` metric sentinels. |
| Values surfaced | `base_score`, `penalty`, `final_score`, `supersedes`, `recomputed_in_epoch` — passed through verbatim, never recomputed. |
| Attribution | `validated_attack_ids` from the record's `input_refs`. |
| Scope | Inside one epoch, for one node. |

Raw versus validated is enforced by type, not by convention: a raw
adversarial claim (`atk_*`) can only be represented as `RqgmRawAttackV1`,
which **has no score, penalty or confidence field at all** — its
`severity_claimed` is the attacker's claim. Only an adjudicated
`validated_attack` (`vat_*`) may drive a penalty, and only via a
`UtilityRecord` that references its id. A run with zero attacks is therefore
reported as a capability state, never as evidence of health.

### Channel 2 — epoch utility-policy rewrite (boundary, run-wide)

| Aspect | Detail |
|---|---|
| Trigger | A committed T20 transition that retires one `utility_policy`-role prompt and adopts another — i.e. `utility_policy_hash` changes at the epoch boundary. |
| Consequences | `SelectiveErasureEvent` (`erase_*`) and `FrontierRebuildEvent` (`rebuild_*`) records in the audit log. |
| Node sets | `invalidated_node_ids`, `recompute_node_ids`, `frontier_removed_node_ids`, `frontier_reinstated_node_ids` — **copied from the real event fields, never recomputed** by the reader. |
| Node-side evidence | The `_utility_policy_hash`, `_scientific_score`, `_stale`, `_stale_reason`, `_valid_for_frontier`, `_erasure_event_id` metric sentinels. |

`…/score-rewrites` is the run-level view of this channel: each entry joins
the supersession transition (`from_policy_hash` → `to_policy_hash`) with its
erasure/rebuild consequences and lists every `source_event_ids` it used.
Honesty rules baked into the join:

- an erasure or rebuild that could **not** be joined to an adoption
  transition still appears as its own entry — a rewrite without its
  transition is shown as such, never hidden;
- when a boundary retires or adopts more than one `utility_policy` prompt,
  `from_policy_hash` / `to_policy_hash` stay `null` with a degraded reason
  rather than guessing which one is "the" policy;
- the page cursor is an integer index into the deterministic joined list
  (transition order, then unjoined audit events in file order) — not a byte
  offset, because the list is a join across two logs.

## Presentation truth rules the API enforces

These rules are implemented in the reader and the DTOs, so a client that
simply renders the payload cannot violate them.

| Rule | How it is enforced |
|---|---|
| A score is never shown without its policy identity. | Every `RqgmScoreObservationV1` carries `policy_hash`; every epoch row carries its own `utility_policy_hash`, so scores under different hashes are never one continuous series. |
| Raw attacks never carry a score. | `RqgmRawAttackV1` has no numeric field — the type makes it impossible. |
| Governance status ≠ research status. | The RQGM payloads describe governance only; run/research status lives on `…/summary`. |
| An open epoch is not zero activity. | `transition_counts` is `None` for the still-open latest epoch, and `fallbacks` is `None` when no `epoch_transition` audit record carries the array. |
| Adoption is a join, never a self-claim. | In `…/evolution`, `adopted` is derived only by matching a candidate's proposed hash against a same-role prompt that reached the active set in committed replay, with `adopted_via` citing the transition. Meta-agent outputs are inert provenance: their `adopted` is `None`. |
| Validation evidence ≠ adoption. | `validation_record_count` / `validation_passed_count` count `prompt_candidate_validation` records and are reported separately from `adopted`. |
| A policy body is served only if its bytes still hash correctly. | `…/policies` returns `body: null` plus a degraded reason when the stored file no longer matches the registered `prompt_hash` (the storage face of the write-once rule). |
| The paper winner is a reviewed selection. | `…/paper-archive` reports the `is_best_belief` draft under `winner`, which is neither the governance winner nor the research result; `materialized` is `full_paper.tex` presence. |
| Absence is reported as absence. | Presence flags (`evolution_present`, `meta_outputs_present`, `state_present`, `archive_present`, `stat_present`, `corpus_present`) accompany every optional source, and counts stay `None` — never `0` — when their artifact is missing. Anchor `enabled` is `None` when no paper policy was frozen. |
| Payloads stay bounded. | Overview embeds no lists; audit entries summarize arrays as `<key>_count` and truncate long strings, with the raw payload available only on `?expand=1`; transition entries carry counts, with raw events only on `?expand=1`. |

## Paging

`…/transitions` and `…/audit` use byte-offset cursors into their JSONL
source with a no-gap/no-duplicate guarantee and committed-only reads;
`…/score-rewrites` uses an index cursor. `source_revision` on the two log
pages is the parsed byte length of the source (excluding a torn tail). The
shared cursor contract is documented once in
[REST API → Cursor conventions](rest_api.md#cursor-conventions).

## See also

- [RQGM Schema Reference](rqgm_schemas.md) — record shapes, id formats, hash
  discipline, and the checkpoint file inventory.
- [File Formats Reference](file_formats.md) — the checkpoint files these
  read models parse.
- [REST API Reference](rest_api.md) — the transport contract.
- [Execution Modes](../guides/execution_modes.md) — when a run is an RQGM
  run at all.
