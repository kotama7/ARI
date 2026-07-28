# docs/concepts

How ARI works under the hood — the architecture, algorithms, and design ideas
behind the autonomous research system.

## Contents

- `README.md` — this file.
- `architecture.md` — ARI Architecture: end-to-end system from research goal to output.
- `bfts.md` — BFTS Algorithm: Best-First Tree Search with its two-pool design.
- `gui_architecture.md` — Dashboard Architecture: the strangler shell, the route registry, run-scoped server-state caching, realtime as invalidation, and the seam from HTTP down to checkpoint artifacts.
- `memory.md` — Memory Architecture: how each node reads from its ancestor chain.
- `PHILOSOPHY.md` — ARI Design Philosophy: the rationale behind ARI's approach to research automation.
- `publication-lifecycle.md` — Publication Lifecycle (v0.7.0): how the EAR flow evolved from whole-checkpoint drops.
- `research_and_governance_state.md` — Research and Governance State: run lifecycle, research phase, governance stage and node score state as four separate state machines, plus the stale / invalidated / removed / deleted distinction.
- `rqgm_architecture.md` — Constitutional ARI-RQGM Architecture: the opt-in `ari_rqgm` governance and co-evolution layer, its epoch loop, and its invariants.
- `rqgm_runtime_walkthrough.md` — RQGM Runtime Walkthrough: one `ari_rqgm` run traced from boot to epoch boundary, with the artifacts it writes.
- `verifiable_research_memory.md` — Verifiable Research Memory: the typed, artifact-grounded memory layer over Letta where `consolidate_node_memory` turns `node_report.json` into provenanced entries and `write_verified_context` grounds paper claims.
