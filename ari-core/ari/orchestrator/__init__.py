"""ari.orchestrator — BFTS exploration and lineage decisions.

The orchestrator owns the breadth-first tree search that drives each
ARI run.  It picks which leaf to expand next, runs the LLM judge that
scores each completed node, and (since v0.7) consults a lineage
decision LLM when composite scores stagnate.

Modules:
- ``node`` / ``node_selection`` — node data model + leaf selector.
- ``bfts`` — main BFTS loop and stage hooks (expansion tracking, depth /
  sterile / total pruning, frontier retire policy).
- ``lineage_decision`` — LLM judge for ``continue`` / ``switch_to_idea``
  / ``fanout`` / ``terminate`` (v0.7.0).
- ``root_idea_selector`` — picks the seed idea from ``idea.json``.
- ``web_provenance`` — read/write the ``bfts_web_provenance.json`` marker that
  records web search being opted into during exploration (P5 trajectory caveat).
- ``node_report/`` — per-node report builder and v0.5 legacy
  reconstruct path (split in Phase 3E).

See also:
- ``docs/architecture.md`` (BFTS Algorithm, Plan / Venue contract).
- ``git log -- ari-core/ari/orchestrator/`` for the Phase 3E split history.
"""
