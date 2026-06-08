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
- `2026-06-broad-tool-registry-integration.md` — Proposed (both build blockers resolved in design; real-env spike cleared on fx700/A64FX). Integrate broad external MCP tool/skill registries (official MCP Registry, mcp.science, Argonne MCP-for-Science) into ARI as one staged stdio broker skill (`ari-skill-tool-registry`), keeping reproducibility-first (P5); records the converged design, the two build blockers (`ARI_PHASE` does not exist; the reproduce sandbox cannot see the broker/cassettes) resolved with zero ari-core change (§4a), and the §7.2 compute-node spike (launch/stdio/offline proven online and offline) that surfaced 3 Stage A.0 provisions: arch-correct uv, uv-managed aarch64 python, and a broker stdout sanitizer.
