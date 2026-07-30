# ari.schemas

JSON Schemas shipped with ari-core, loaded by basename via
`ari.schemas.load(name)`.

## Contents

- `README.md` — this file.
- `__init__.py` — `load(name)` loader.
- `clean_room_bundle.schema.json` — the closed `CleanRoomInputBundle` assembled for the `CleanRoomPromptGenerator`; `additionalProperties:false` plus `bundle_hash` keep the generator's entire input surface auditable.
- `clean_room_request.schema.json` — one `CleanRoomGenerationRequest` line of append-only `{ckpt}/rqgm_cleanroom.jsonl`, minted from a transition-engine retirement event with the five forbidden-input flags pinned const-false.
- `epoch_state.schema.json` — derived rollup of the open (or last closed) `EpochState`; `rqgm_transitions.jsonl` stays the source of truth and rebuilds it on fingerprint mismatch.
- `epoch_transition.schema.json` — the `EpochTransition` record produced by the `RegistryTransitionEngine` at each boundary: adoptions, sanctions, retirements, bans, and the T1-T21 `rule_id` behind every status change.
- `erasure_state.schema.json` — derived `{ckpt}/rqgm_erasure_state.json` rollup of erasure/rebuild events; readers derive staleness from `stale_record_ids` because stored JSONL is never rewritten.
- `frontier_rebuild_event.schema.json` — one `FrontierRebuildEvent` appended to `rqgm_audit.jsonl` after the `FrontierRepairEngine` recomputes the frontier — removed, reinstated, and recomputed node ids.
- `governance_report.schema.json` — the `GovernanceReport` returned by `GovernanceOrchestrator.audit_epoch` and appended to `{ckpt}/rqgm_audit.jsonl`: motions, defenses, adjudications, and closed-set recommendations.
- `node_report.schema.json` — per-node report schema.
- `proposal_record.schema.json` — one line of `{ckpt}/proposals/proposal_records.jsonl` carrying the bounded `ProposalSummaryView` plus the logical-only `stale` / `valid_for_frontier` flags.
- `proposal_summary_view.schema.json` — the eight character-budgeted summary fields that are the only proposal representation BFTS may consume; full transcripts stay archive-only.
- `publish.schema.json` — publish record / manifest schema.
- `rqgm_attack_records.schema.json` — the four adversarial-loop shapes (`RawAttackRecord`, `DefenderResponse`, `JudgmentRecord`, `ValidatedAttackRecord`) multiplexed into `{ckpt}/rqgm_adversarial_cases.jsonl`; only a judge verdict mints a validated record.
- `rqgm_defs.schema.json` — canonical shared `$defs` — the `rqgm_record_base` envelope, closed status/role/tier vocabularies, and id/hash formats — that every other RQGM schema `$ref`s or copies byte-equal; mirrors `ari/rqgm/events.py`.
- `rqgm_governance_cache.schema.json` — one entry of append-only `{ckpt}/rqgm_governance_cache.jsonl`, keyed by a `cache_key` over artifact/prompt/role/epoch/context/schema hashes and never by wall clock.
- `rqgm_meta.schema.json` — the meta-agent evolution shapes: tier + capability-flag registry entries, `MetaAgentOutputRecord` lines of `{ckpt}/rqgm_meta_outputs.jsonl`, and `MetaCandidateEvaluation`; mirrors `ari/rqgm/meta_rules.py`.
- `rqgm_prompt_evolution.schema.json` — the three shapes in append-only `{ckpt}/prompt_evolution.jsonl`: `PromptCandidate` from the `PromptMutator`, per-stage `PromptCandidateValidation`, and observation-only `ComparisonObservation`.
- `rqgm_prompt_spec.schema.json` — one immutable versioned `PromptSpec` (`prompt_id`, `prompt_hash`, `template_ref` over package/checkpoint/policy byte sources); changing template bytes mints a new spec instead of mutating one.
- `rqgm_registry.schema.json` — derived `rqgm_registry.json` rollup holding `ComponentRegistry` and `PromptRegistry` in one file so both stay transactionally consistent; prompt text is referenced, never inlined.
- `rqgm_replay_pool.schema.json` — derived `{ckpt}/rqgm/adversarial_replay_pool.json` snapshot splitting each case into the full `replay_view` and the clean-room-safe `abstract_view`; eviction is a status flip only.
- `rqgm_transition_event.schema.json` — the hash-chained line envelope of `rqgm_transitions.jsonl`; v2 commits SHA-256 over version, event id/type, transaction id, canonical payload, and `prev_event_hash`, v1 over the payload alone.
- `rqgm_utility_policy_candidate.schema.json` — one `UtilityPolicyCandidate` proposed by the policy mutator onto the shared prompt-evolution log, carrying the policy body by value with `policy_hash` as its future `utility_policy_hash`.
- `rqgm_utility_record.schema.json` — one governed-utility audit record (`base_score`, `penalty`, `final_score`) storing `input_refs` and `frozen_policy` by value; any nonzero penalty must cite a `ValidatedAttackRecord`.
- `selective_erasure_event.schema.json` — one kernel-authored `SelectiveErasureEvent` from the `FrontierRepairEngine` listing the dependency closure staled by a retired `prompt_hash`; flagging is logical, never deletion.
- `viz_checkpoint.schema.json` — one item of the `GET /api/checkpoints` list built by `checkpoint_api`, mirroring the frontend `Checkpoint` type; `best_scientific_score` is the only optional key.
- `viz_checkpoint_summary.schema.json` — response of `GET /api/checkpoint/<id>/summary`; only `id` and `path` are guaranteed, the paper/review/repro/ORS keys appear only when their backing files exist.
- `viz_settings.schema.json` — response of `GET /api/settings` (defaults merged with saved values) and the flat body accepted by `POST /api/settings`; `additionalProperties` encodes saved-key passthrough.
- `viz_state.schema.json` — response of `GET /state` built inline by `routes.py` and polled by the dashboard; only the run-status tail (`is_running`, `pid`, `status_label`, `llm_model`) is guaranteed.
- `viz_tree_node.schema.json` — one BFTS/pipeline tree node passed through verbatim inside `/state` and `nodes_tree`; only `id` is guaranteed because raw node dicts are never transformed.

## See also

- **Loader** → the `load()` docstring in `__init__.py` (authoritative).
- **File formats these schemas validate** → `docs/reference/file_formats.md`.
