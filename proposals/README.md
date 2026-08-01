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
- `2026-06-broad-tool-registry-integration.md` — Proposed (architecture consolidated; real-env spike cleared on fx700/A64FX). Defines a provider-neutral MCP federation control plane with a fixed five-tool surface, generated candidate/admission/lock lifecycle, collection-level adapters for ToolUniverse and future MCP aggregators, scientific admission and conflict/independence handling, EAR/cassette replay, OpenROAD and Qiskit domain profiles, and a staged A.0→C implementation plan. The existing `ARI_PHASE` and reproduction-sandbox hand-off blockers remain resolved with zero `ari-core` change.
