# ari.schemas

JSON Schemas shipped with ari-core, loaded by basename via
`ari.schemas.load(name)`.

## Contents

- `README.md` — this file.
- `__init__.py` — `load(name)` loader.
- `analysis_request_v1.schema.json` — deterministic summary, inference, comparison, or plot-analysis request.
- `analysis_result_v1.schema.json` — provenance-bound analysis result with typed tables, tests, and artifacts.
- `async_tool_handle_v1.schema.json` — immutable submit/status/result/cancel handle contract.
- `call_context_v1.schema.json` — explicit run, node, ordered-lineage, and call-provenance context.
- `clean_room_bundle.schema.json` — the closed `CleanRoomInputBundle` assembled for the `CleanRoomPromptGenerator`; `additionalProperties:false` plus `bundle_hash` keep the generator's entire input surface auditable.
- `clean_room_request.schema.json` — one `CleanRoomGenerationRequest` line of append-only `{ckpt}/rqgm_cleanroom.jsonl`, minted from a transition-engine retirement event with the five forbidden-input flags pinned const-false.
- `epoch_state.schema.json` — derived rollup of the open (or last closed) `EpochState`; `rqgm_transitions.jsonl` stays the source of truth and rebuilds it on fingerprint mismatch.
- `epoch_transition.schema.json` — the `EpochTransition` record produced by the `RegistryTransitionEngine` at each boundary: adoptions, sanctions, retirements, bans, and the T1-T21 `rule_id` behind every status change.
- `erasure_state.schema.json` — derived `{ckpt}/rqgm_erasure_state.json` rollup of erasure/rebuild events; readers derive staleness from `stale_record_ids` because stored JSONL is never rewritten.
- `execution_request_v1.schema.json` — exact command, workspace, inputs, environment, resources, network, and container request.
- `execution_result_v1.schema.json` — attempt identity, enforcement report, bounded previews, and complete-log artifacts.
- `figure_batch_v1.schema.json` — declarative figure specs, render environment, outputs, and review hand-off.
- `frontier_rebuild_event.schema.json` — one `FrontierRebuildEvent` appended to `rqgm_audit.jsonl` after the `FrontierRepairEngine` recomputes the frontier — removed, reinstated, and recomputed node ids.
- `gate_report_v1.schema.json` — deterministic policy/evidence/formula-bound hard-gate report.
- `governance_report.schema.json` — the `GovernanceReport` returned by `GovernanceOrchestrator.audit_epoch` and appended to `{ckpt}/rqgm_audit.jsonl`: motions, defenses, adjudications, and closed-set recommendations.
- `idea_candidate_v1.schema.json` — admitted falsifiable hypothesis candidate.
- `idea_set_v1.schema.json` — generation lock, admitted candidates, and explicit rejections.
- `measurement_set_v1.schema.json` — typed parameter, measurement, unit, execution, and artifact separation.
- `memory_backup_v1.schema.json` — content-addressed memory backup with backend and retention provenance.
- `memory_record_v1.schema.json` — immutable scoped memory record with lifecycle and evidence metadata.
- `memory_retrieval_v1.schema.json` — authorized memory query, ranked hits, and retrieval provenance.
- `metric_admission_decision_v1.schema.json` — explicit human admission or rejection of a proposed metric.
- `metric_contract_proposal_v1.schema.json` — provenance-bound untrusted LLM metric proposal.
- `metric_contract_v1.schema.json` — immutable metric, unit, direction, comparison, and evidence vocabulary.
- `metric_gate_contract_v1.schema.json` — evaluator projection of one admitted metric contract.
- `node_report.schema.json` — per-node report schema.
- `paper_build_v1.schema.json` — immutable paper inputs, revisions, compile outcome, and publication readiness.
- `paper_model_call_batch_v1.schema.json` — ordered model-call provenance and usage records for one paper operation.
- `proposal_record.schema.json` — one line of `{ckpt}/proposals/proposal_records.jsonl` carrying the bounded `ProposalSummaryView` plus the logical-only `stale` / `valid_for_frontier` flags.
- `proposal_summary_view.schema.json` — the eight character-budgeted summary fields that are the only proposal representation BFTS may consume; full transcripts stay archive-only.
- `publish.schema.json` — publish record / manifest schema.
- `research_contract_v1.schema.json` — selected mint-once scientific hand-off consumed by downstream stages.
- `result_envelope_v1.schema.json` — typed MCP result plus artifact, error, and credential-scope provenance.
- `retrieval_record_v1.schema.json` — provider-neutral literature or web record identity and payload digest.
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
- `run_comparison_request_v1.schema.json` — explicit run/cohort comparison, pairing, metric, and statistical-test request.
- `science_data_v1.schema.json` — separately digest-bound raw measurement, derived result, and interpretation aggregate.
- `selective_erasure_event.schema.json` — one kernel-authored `SelectiveErasureEvent` from the `FrontierRepairEngine` listing the dependency closure staled by a retired `prompt_hash`; flagging is logical, never deletion.
- `semantic_review_v1.schema.json` — independent provenance-bound semantic advisory.
- `skill_manifest_v1.schema.json` — canonical Skill package, environment, credentials, and tool-policy contract.
- `skills_lock_v1.schema.json` — immutable provider, schema, phase, and credential-authority snapshot.
- `statistical_test_request_v1.schema.json` — explicit samples, pairing, hypotheses, method, correction, and threshold request.
- `survey_snapshot_v1.schema.json` — digest-bound record/replay retrieval input and citation graph.
- `visual_review_batch_v1.schema.json` — criteria profiles, artifact identities, findings, and reviewer provenance.
- `viz_checkpoint.schema.json` — one item of the `GET /api/checkpoints` list built by `checkpoint_api`, mirroring the frontend `Checkpoint` type; `best_scientific_score` is the only optional key.
- `viz_checkpoint_summary.schema.json` — response of `GET /api/checkpoint/<id>/summary`; only `id` and `path` are guaranteed, the paper/review/repro/ORS keys appear only when their backing files exist.
- `viz_settings.schema.json` — response of `GET /api/settings` (defaults merged with saved values) and the flat body accepted by `POST /api/settings`; `additionalProperties` encodes saved-key passthrough.
- `viz_state.schema.json` — response of `GET /state` built inline by `routes.py` and polled by the dashboard; only the run-status tail (`is_running`, `pid`, `status_label`, `llm_model`) is guaranteed.
- `viz_tree_node.schema.json` — one BFTS/pipeline tree node passed through verbatim inside `/state` and `nodes_tree`; only `id` is guaranteed because raw node dicts are never transformed.
- `workspace_ref_v1.schema.json` — canonical closed workspace root and path-containment contract.

## See also

- **Loader** → the `load()` docstring in `__init__.py` (authoritative).
- **File formats these schemas validate** → `docs/reference/file_formats.md`.
