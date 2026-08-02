# ari.schemas

JSON Schemas shipped with ari-core, loaded by basename via
`ari.schemas.load(name)`.

## Contents

- `README.md` — this file.
- `async_tool_handle_v1.schema.json` — immutable submit/status/result/cancel handle contract.
- `call_context_v1.schema.json` — explicit run, node, ordered-lineage, and call provenance context.
- `execution_request_v1.schema.json` — exact command, workspace, input digest, environment, resource, network, and container request.
- `execution_result_v1.schema.json` — attempt identity, enforcement report, bounded previews, and complete-log artifacts.
- `__init__.py` — `load(name)` loader.
- `node_report.schema.json` — per-node report schema.
- `publish.schema.json` — publish record / manifest schema.
- `result_envelope_v1.schema.json` — typed MCP result plus value-free credential-scope provenance.
- `measurement_set_v1.schema.json` — typed parameter/measurement/unit/execution/artifact separation.
- `retrieval_record_v1.schema.json` — provider-neutral literature/web record identity and payload digest.
- `survey_snapshot_v1.schema.json` — digest-bound record/replay retrieval input and citation graph.
- `metric_contract_v1.schema.json` — immutable metric, unit, direction, comparison, and evidence vocabulary.
- `idea_candidate_v1.schema.json` — admitted falsifiable hypothesis candidate.
- `idea_set_v1.schema.json` — generation lock, admitted candidates, and explicit rejections.
- `research_contract_v1.schema.json` — selected mint-once scientific hand-off consumed by evaluators.
- `skill_manifest_v1.schema.json` — canonical Skill package, environment, and credential-scope contract.
- `skills_lock_v1.schema.json` — immutable provider/schema/phase/credential-authority snapshot.
- `workspace_ref_v1.schema.json` — canonical closed workspace root.
- `viz_checkpoint.schema.json` — TODO
- `viz_checkpoint_summary.schema.json` — TODO
- `viz_settings.schema.json` — TODO
- `viz_state.schema.json` — TODO
- `viz_tree_node.schema.json` — TODO

## See also

- **Loader** → the `load()` docstring in `__init__.py` (authoritative).
- **File formats these schemas validate** → `docs/reference/file_formats.md`.
