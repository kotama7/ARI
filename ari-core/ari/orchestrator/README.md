# ari.orchestrator

Best-first tree search (BFTS) that drives each ARI run: leaf selection,
LLM node scoring, lineage decisions, and root-idea selection.

## Contents

- `README.md` — this file.
- `__init__.py` — package exports + authoritative module-map docstring.
- `bfts.py` — `BFTS` loop and stage hooks (expand/select, pruning, frontier retire).
- `lineage_decision.py` — LLM lineage action + `lineage_decisions.jsonl` log.
- `node.py` — `Node` data model + `NodeStatus` / `NodeLabel` enums.
- `node_selection.py` — shared node-selection helpers + publication source-file selection.
- `Plan.md` — G3 node_summary_view / G9a deterministic selector の実装計画（handoff study）.
- `root_idea_selector.py` — run-start LLM root-idea pick + selection log.
- `web_provenance.py` — read/write `bfts_web_provenance.json`, the marker recording that web search was opted into during BFTS exploration (flags the trajectory non-reproducible, P5).
- `node_report/` — per-node `node_report.json` package.
  - `README.md` — node_report index.
  - `__init__.py` — re-exports the builder + legacy shim.
  - `builder.py` — v0.7+ `node_report.json` builder.
  - `legacy_reconstruct.py` — v0.5 → v0.7 reconstruct shim.

## See also

- `docs/concepts/bfts.md`, `docs/concepts/architecture.md` — algorithm & Plan/Venue contract.
- `git log -- ari-core/ari/orchestrator/` — split history.
