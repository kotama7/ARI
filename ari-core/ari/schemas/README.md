# ari.schemas

JSON Schemas shipped with ari-core, loaded by basename via
`ari.schemas.load(name)`.

## Contents

- `README.md` — this file.
- `__init__.py` — `load(name)` loader.
- `analysis_request_v1.schema.json` — TODO
- `analysis_result_v1.schema.json` — TODO
- `async_tool_handle_v1.schema.json` — immutable submit/status/result/cancel handle contract.
- `call_context_v1.schema.json` — explicit run, node, ordered-lineage, and call provenance context.
- `execution_request_v1.schema.json` — exact command, workspace, input digest, environment, resource, network, and container request.
- `execution_result_v1.schema.json` — attempt identity, enforcement report, bounded previews, and complete-log artifacts.
- `figure_batch_v1.schema.json` — declarative specs, render environment,
- `gate_report_v1.schema.json` — deterministic policy/evidence/formula-bound hard-gate report.
- `idea_candidate_v1.schema.json` — admitted falsifiable hypothesis candidate.
- `idea_set_v1.schema.json` — generation lock, admitted candidates, and explicit rejections.
- `measurement_set_v1.schema.json` — typed parameter/measurement/unit/execution/artifact separation.
- `memory_backup_v1.schema.json` — TODO
- `memory_record_v1.schema.json` — TODO
- `memory_retrieval_v1.schema.json` — TODO
- `metric_admission_decision_v1.schema.json` — explicit human admission/rejection record.
- `metric_contract_proposal_v1.schema.json` — provenance-bound, untrusted LLM metric proposal.
- `metric_contract_v1.schema.json` — immutable metric, unit, direction, comparison, and evidence vocabulary.
- `metric_gate_contract_v1.schema.json` — evaluator projection of one admitted metric contract.
- `node_report.schema.json` — per-node report schema.
- `paper_build_v1.schema.json` — TODO
- `paper_model_call_batch_v1.schema.json` — TODO
- `publish.schema.json` — publish record / manifest schema.
- `research_contract_v1.schema.json` — selected mint-once scientific hand-off consumed by evaluators.
- `result_envelope_v1.schema.json` — typed MCP result plus value-free credential-scope provenance.
- `retrieval_record_v1.schema.json` — provider-neutral literature/web record identity and payload digest.
- `run_comparison_request_v1.schema.json` — TODO
- `science_data_v1.schema.json` — separately digest-bound raw measurement,
- `semantic_review_v1.schema.json` — independent provenance-bound semantic advisory.
- `skill_manifest_v1.schema.json` — canonical Skill package, environment, and credential-scope contract.
- `skills_lock_v1.schema.json` — immutable provider/schema/phase/credential-authority snapshot.
- `statistical_test_request_v1.schema.json` — TODO
- `survey_snapshot_v1.schema.json` — digest-bound record/replay retrieval input and citation graph.
- `visual_review_batch_v1.schema.json` — criteria profiles, artifact identity,
- `viz_checkpoint.schema.json` — TODO
- `viz_checkpoint_summary.schema.json` — TODO
- `viz_settings.schema.json` — TODO
- `viz_state.schema.json` — TODO
- `viz_tree_node.schema.json` — TODO
- `workspace_ref_v1.schema.json` — canonical closed workspace root.

## See also

- **Loader** → the `load()` docstring in `__init__.py` (authoritative).
- **File formats these schemas validate** → `docs/reference/file_formats.md`.
