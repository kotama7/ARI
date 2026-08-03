# docs/reference

Lookup material: the precise contracts for ARI's CLI, APIs, configuration,
file formats, and terminology.

## Contents

- `README.md` — this file.
- `api_paperbench.md` — PaperBench API reference: the PaperBench endpoints on the viz server.
- `analysis_contract.md` — typed deterministic summary, inference, run-comparison, and plot hand-off contracts.
- `cli_reference.md` — ARI CLI Reference: complete reference for command-line operations.
- `configuration.md` — Configuration Reference: `workflow.yaml`, the single source of truth for the pipeline.
- `compatibility_support.md` — retained read-only/limited compatibility paths, owners, and objective removal gates.
- `environment_variables.md` — Environment Variable Reference: the ~90 environment variables ARI honours.
- `execution_profile.md` — `execution_profile` reference: the object under `reproduce_contract`.
- `execution_contract.md` — closed workspace, bounded execution, complete-log artifact, and typed measurement contracts.
- `file_formats.md` — File Formats Reference: the self-describing ARI checkpoint directory.
- `glossary.md` — Glossary: short definitions of terms recurring across the docs.
- `internal_boundaries.md` — Internal boundaries: the LLM, OS/scheduler/container, and two-engine orchestration boundaries + their concurrency hazards.
- `mcp_tools.md` — MCP Tools Reference: the MCP servers ARI ships (one per skill package).
- `orchestrator.md` — authenticated durable ARI run control, lifecycle, quotas, and artifact access.
- `public_api.md` — `ari.public`: the only stable module surface for `ari-skill-*` packages.
- `qiskit_profiles.md` — immutable Qiskit/Aer/IBM Runtime scientific profiles, credentials, evidence, and operations.
- `registry.md` — ari-registry (v0.7.0+): the minimal HTTP registry for curated EAR bundles.
- `rest_api.md` — REST API Reference: the viz dashboard server endpoints.
- `rubric_schema.md` — Rubric schema reference: the canonical replication rubric schema.
- `skills.md` — MCP Skills Reference: canonical manifest contract plus the `ari-skill-*` servers and tools.
- `tool_registry.md` — Federated Scientific Tool Registry: immutable catalog, admission, overlap, and replay contracts.
