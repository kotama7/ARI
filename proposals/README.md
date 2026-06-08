# proposals/

Design proposals / RFCs for ARI. Each proposal records a converged design, its
grounding evidence, open risks, and the gate that must clear before
implementation. Proposals are **design artifacts, not implementation** — code
lands in separate PRs once a proposal's gate (e.g. a real-environment spike) is
met.

Naming: `YYYY-MM-<slug>.md`. Every proposal carries a **Status** line
(`Proposed` / `Accepted` / `Implemented` / `Rejected` / `Superseded`).

## Contents

- `README.md` — this file.
- `2026-06-broad-tool-registry-integration.md` — Proposed (both build blockers resolved in design; gated only on a real-env spike). Integrate broad external MCP tool/skill registries (official MCP Registry, mcp.science, Argonne MCP-for-Science) into ARI as one staged stdio broker skill (`ari-skill-tool-registry`), keeping reproducibility-first (P5); records the converged design, the two build blockers (`ARI_PHASE` does not exist; the reproduce sandbox cannot see the broker/cassettes) now resolved with zero ari-core change (§4a — drop the phase signal; vendor cassettes via the existing curate→clone chain), and the compute-node spike that remains the only gate.
