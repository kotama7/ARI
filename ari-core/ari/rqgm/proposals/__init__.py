"""ProposalRecord / ProposalRouter / VirSciAdapter (RQGM Task 03).

Home of the governed proposal layer (``docs/reference/rqgm_schemas.md``,
"Proposal schemas (Task 03)"):
"store everything; hand BFTS only the summary". Every generated proposal
becomes an archival :class:`~ari.rqgm.proposals.records.ProposalRecord` in
``{ckpt}/proposals/``; BFTS only ever sees the bounded
:class:`~ari.rqgm.proposals.records.ProposalSummaryView` rendered by
:func:`~ari.rqgm.proposals.records.render_summary_ctx`.

Import rule: same as :mod:`ari.rqgm` — the default ``simple_bfts`` path never
imports this package (the sole exception is the explicitly opt-in
``proposal_router.record_only`` Stage-1 dual-write). Keep this ``__init__``
free of submodule imports so importing ``ari.rqgm.proposals`` stays
side-effect-free.

Modules
-------
- ``records`` — ProposalRecord + ProposalSummaryView schemas, size budgets,
  the pure ``render_summary_ctx`` renderer, and the idea.json field mapping.
- ``store`` — checkpoint-scoped ``proposals/`` store (append-only JSONL truth
  + archive dir + ``idea.json`` projection writer + legacy import).
- ``generators`` — Generator protocol + Cheap/Mutation/AttackDriven/PriorArt
  generators (prompt-templated, injectable LLM; deterministic fallbacks).
- ``router`` — budget-aware deterministic ProposalRouter (``ari_rqgm`` only).
- ``virsci_adapter`` — MCP-only VirSciAdapter; never imports anything from
  ``ari-skill-idea`` and is constructed only when
  ``proposal_router.generators.virsci.enabled`` is true.
"""
