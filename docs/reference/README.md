# docs/reference

Lookup material: the precise contracts for ARI's CLI, APIs, configuration,
file formats, and terminology.

## Contents

- `README.md` — this file.
- `analysis_contract.md` — deterministic summaries, inference, run comparisons, statistics, and plot hand-offs.
- `api_paperbench.md` — PaperBench API reference: the PaperBench endpoints on the viz server.
- `cli_reference.md` — ARI CLI Reference: complete reference for command-line operations.
- `compatibility_support.md` — retained compatibility paths, owners, support windows, and objective deletion gates.
- `configuration.md` — Configuration Reference: `workflow.yaml`, the single source of truth for the pipeline.
- `environment_variables.md` — Environment Variable Reference: the ~90 environment variables ARI honours.
- `evaluation_contract.md` — metric admission, deterministic hard gates, calibration, and semantic-review boundaries.
- `execution_contract.md` — closed workspaces, bounded execution, complete logs, and typed measurement provenance.
- `execution_profile.md` — `execution_profile` reference: the object under `reproduce_contract`.
- `figure_visual_contract.md` — declarative figures, deterministic rendering, artifact identity, and visual review.
- `file_formats.md` — File Formats Reference: the self-describing ARI checkpoint directory.
- `glossary.md` — Glossary: short definitions of terms recurring across the docs.
- `internal_boundaries.md` — Internal boundaries: the LLM, OS/scheduler/container, and two-engine orchestration boundaries + their concurrency hazards.
- `knowledge_capability_assurance.md` — contracts and operational boundaries for knowledge skills, capability binding, and scientific assurance.
- `manuscript_complete_contracts.md` — Manuscript Complete V1 digests, states, repair transactions, authoring binding, and publication lock.
- `manuscript_complete_profile.md` — `generic_empirical_v1` requirements, applicability, evidence lanes, and subject selection.
- `mcp_tools.md` — MCP Tools Reference: the MCP servers ARI ships (one per skill package).
- `memory_contract.md` — scoped immutable records, retrieval authorization, lifecycle events, backups, and deletion gates.
- `orchestrator.md` — authenticated durable run control, lifecycle, quotas, reconciliation, and artifact access.
- `paper_build_contract.md` — immutable authoring inputs, revisions, model calls, compilation, review, and finalization.
- `public_api.md` — `ari.public`: the only stable module surface for `ari-skill-*` packages.
- `qiskit_profiles.md` — immutable Qiskit, Aer, and IBM Runtime profiles, credentials, evidence, and operations.
- `registry.md` — ari-registry (v0.7.0+): the minimal HTTP registry for curated EAR bundles.
- `reproduction_contract.md` — versioned plans, attempts, sandboxed runs, artifacts, rubrics, and grade reports.
- `research_contracts.md` — falsifiable ideas, admitted metrics, retrieval snapshots, evidence, and stage hand-offs.
- `rest_api.md` — REST API Reference: the canonical `/api/v1` surface plus the frozen legacy facade.
- `retrieval_contract.md` — provider-neutral records, record/replay snapshots, citation graphs, and network policy.
- `rqgm_gui_read_models.md` — RQGM GUI read models: the `/api/v1/runs/{run_id}/rqgm/*` payloads, their source artifacts, and the truth rules they enforce.
- `rqgm_schemas.md` — RQGM Schema Reference: the JSON Schemas for every record the `ari_rqgm` mode persists.
- `rubric_schema.md` — Rubric schema reference: the canonical replication rubric schema.
- `science_data_contract.md` — raw measurements, derived results, interpretations, units, lineage, and migration.
- `skills.md` — MCP Skills Reference: the `ari-skill-*` MCP servers and their tools.
- `tool_registry.md` — federated scientific catalog, provider admission, overlap resolution, locks, and replay.
