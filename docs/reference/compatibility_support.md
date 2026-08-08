---
sources:
  - path: ari-core/ari/execution.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-memory/README.md
    role: doc
  - path: ari-skill-paper-re/src/rubric_contract.py
    role: implementation
  - path: ari-skill-paper-re/paperbench_patches.json
    role: config
  - path: ari-skill-orchestrator/src/ari_skill_orchestrator/registry.py
    role: implementation
last_verified: 2026-08-08
---

# Compatibility support policy

ARI does not keep compatibility paths merely because they once existed. A
retained path must be read-only or narrowly scoped, fail closed, have an owner,
and have an objective removal gate. New producers never emit retired formats.

## Retained support matrix

| Surface | Boundary and rationale | Owner | Re-evaluation / removal gate |
|---|---|---|---|
| Historical measurement documents | `parse_measurement_document` reads old flat v1/unversioned files without inventing units or execution provenance. `emit_results` writes only the canonical `measurement_set`. | ARI core maintainers | v1.1: published-checkpoint usage is zero and migration fixtures have been archived. |
| Historical research, retrieval, result, figure, review, paper-build, and EAR artifacts | Readers are isolated to replay, verification, or explicit migration. They are not runtime producer fallbacks. | Owning skill maintainers | Remove per format only after the supported publication/replay window closes and golden replay remains available. |
| Letta pip deployment | Containerless local installations still need the statically tested pip launcher. It is not an automatic data-backend fallback. | ARI maintainers | v1.1: review usage and an issue before removal; Docker/Apptainer/Cloud support must remain green. |
| `slurm_submit` script bridge | The core experiment agent still authors an allocated compute-node body. Generated scheduler policy precedes that body; `#SBATCH` text cannot override it. New programmatic integrations use `job_submit`/`container_submit`. | ARI core + HPC maintainers | v1.1: remove when the agent emits `JobRequestV1` directly and core/tool callers are zero. |
| Rubric V1 reader and offline migration | Paper-re verifies the source digest and fails closed; replicate can migrate losslessly to V2. No V1 runtime generator exists. | Replicate + paper-re maintainers | v1.1: workflow callers and supported V1 artifact usage are zero. |
| PaperBench runtime adaptations | Only adaptations listed in `paperbench_patches.json` at the exact source pin are applied and conformance-tested. | Paper-re maintainers | Re-evaluate on every PaperBench pin update; remove an adaptation when its declared `deletion_gate` condition holds and the target-version suite is green. |
| Orchestrator registry repair | Explicit repair may import only apparently terminal legacy runs into the durable registry. It is never automatic discovery or live-state inference. | Orchestrator maintainers | v1.1: remove only after supported checkpoints have been imported and repair fixtures are archived. |
| Archived registry locks and provider cassettes | Required to reproduce a published dispatch. Readers verify digests and never admit the archived provider into a new run implicitly. | Tool-registry and provider-profile maintainers | Retain for the publication/replay support window; then remove by format with a migration/replay fixture. |

## Change rules

- Adding a compatibility writer or silent fallback requires a new reviewed
  architecture decision; it cannot be justified by this policy.
- A removal records the last pre-removal commit, updates the changelog, checks
  repository callers, and runs the owning contract/replay suite.
- Security-sensitive fallbacks may be removed earlier when an explicit error
  and migration procedure are supplied.
