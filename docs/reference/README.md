# docs/reference

Lookup material: the precise contracts for ARI's CLI, APIs, configuration,
file formats, and terminology.

## Contents

- `README.md` — this file.
- `analysis_contract.md` — typed deterministic summary, inference, run-comparison, and plot hand-off contracts.
- `api_paperbench.md` — PaperBench API reference: the PaperBench endpoints on the viz server.
- `cli_reference.md` — ARI CLI Reference: complete reference for command-line operations.
- `compatibility_support.md` — retained read-only/limited compatibility paths, owners, and objective removal gates.
- `configuration.md` — Configuration Reference: `workflow.yaml`, the single source of truth for the pipeline.
- `environment_variables.md` — Environment Variable Reference: the ~90 environment variables ARI honours.
- `evaluation_contract.md` — TODO
- `execution_contract.md` — closed workspace, bounded execution, complete-log artifact, and typed measurement contracts.
- `execution_profile.md` — `execution_profile` reference: the object under `reproduce_contract`.
- `figure_visual_contract.md` — TODO
- `file_formats.md` — File Formats Reference: the self-describing ARI checkpoint directory.
- `glossary.md` — Glossary: short definitions of terms recurring across the docs.
- `internal_boundaries.md` — Internal boundaries: the LLM, OS/scheduler/container, and two-engine orchestration boundaries + their concurrency hazards.
- `mcp_tools.md` — MCP Tools Reference: the MCP servers ARI ships (one per skill package).
- `memory_contract.md` — TODO
- `orchestrator.md` — authenticated durable ARI run control, lifecycle, quotas, and artifact access.
- `paper_build_contract.md` — TODO
- `public_api.md` — `ari.public`: the only stable module surface for `ari-skill-*` packages.
- `qiskit_profiles.md` — immutable Qiskit/Aer/IBM Runtime scientific profiles, credentials, evidence, and operations.
- `registry.md` — ari-registry (v0.7.0+): the minimal HTTP registry for curated EAR bundles.
- `reproduction_contract.md` — TODO
- `research_contracts.md` — TODO
- `rest_api.md` — REST API Reference: the viz dashboard server endpoints.
- `retrieval_contract.md` — TODO
- `rubric_schema.md` — Rubric schema reference: the canonical replication rubric schema.
- `science_data_contract.md` — TODO
- `skills.md` — MCP Skills Reference: canonical manifest contract plus the `ari-skill-*` servers and tools.
- `tool_registry.md` — Federated Scientific Tool Registry: immutable catalog, admission, overlap, and replay contracts.
