# ari-skill-evaluator Requirements

## Overview

MCP server for evaluation tooling. Historically a data extractor
(`make_metric_spec`). With the Story2Proposal integration it also hosts the two
paper-phase evaluation tools (the heavy logic for the gate lives in ari-core;
this skill is the MCP surface).

## Tools

### make_metric_spec(experiment_text) -> dict
Deterministic (LLM fallback) MetricSpec extraction. Unchanged.

### claim_evidence_hard_gate(...) -> dict  (Story2Proposal Phase B)
Thin wrapper over `ari.pipeline.claim_gate.run_hard_gate` (ari-core is on the
skill's PYTHONPATH). Deterministic claim/evidence verification:
- claim existence (nodes executed, artifacts present),
- numeric `formula`-level recompute from `results.json` vs the paper-reported
  number within tolerance,
- numeric coverage per section policy (uncovered result numbers),
- figure existence.
Writes `evaluation/claim_evidence_hard_gate_{phase}.json`. **Blocking contract:**
when `should_block` (final + strict + blocking errors) it returns an *error-only*
payload so the pipeline stage fails and `finalize_paper` is skipped; otherwise it
returns the full report. Degrades gracefully (non-blocking skip) if ari-core is
unimportable — it never breaks the finalize chain in `warn`/`off` mode.

Verification boundary: transcription/derivation consistency only (paper ↔
recorded results), NOT the truthfulness of the recorded results (that is ORS).

### evidence_grounded_semantic_review(...) -> dict  (Story2Proposal Phase D)
**Non-blocking** LLM review of *meaning only* (numbers/figures already verified by
the hard gate): over-claiming, over-generalization, interpretation validity,
unregistered strong (non-numeric) claims. Emits `suggested_revisions` for
`paper_refine` and per-axis `scores`. On rerun (`phase=post_refine`) computes
`score_delta` and `resolved_overclaim_count` vs the initial review.
`human_verified_overclaim_precision` is left `null` (human spot-check, master
§10.3). Writes `evaluation/evidence_grounded_semantic_review[_post_refine].json`.
On any LLM/parse failure it returns a non-blocking no-op. Does **not** modify
`review_compiled_paper` (independence contract) or the dynamic-axes evaluator.

## Model selection

`ARI_MODEL_EVAL` > `ARI_MODEL` > `ARI_LLM_MODEL` > `gpt-4o-mini`.

## Status

Phase D + gate wrapper code + unit tests complete (`tests/test_s2p_tools.py`;
gate logic itself tested in ari-core). Real compute-node validation pending; see
`PLAN_s2p_semantic_review.md`.
