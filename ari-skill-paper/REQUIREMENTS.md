# ari-skill-paper requirements

## Runtime contract

The paper Skill runs only in the post-BFTS paper phase. New authoring runs must
use native `ScienceDataV1`, `FigureBatchV1`, recorded retrieval, and EAR inputs
inside an explicit `WorkspaceRefV1`. Generic tree/metric discovery and inline
legacy JSON coercion are not authoring paths.

`PaperBuildV1` is the authoritative output. It binds:

- input, template, rubric, and EAR artifact digests;
- ordered revision lineage and preserved claim/citation/figure/math identities;
- each stochastic call's prompt/raw response/model/sampling/usage;
- bounded compile commands, execution identities, environment, and full logs;
- independent text, visual, semantic, and hard-gate review artifacts;
- final claim coverage and TeX/BibTeX/PDF digests.

Finalization is fail closed. A disabled/failed gate, uncovered result number,
unresolved anchor, review/evidence mismatch, changed input, VLM failure, compile
failure, or final artifact mismatch produces a persisted blocked build and never
a finalized status.

## Claim protocol

Result statements use `% CLAIM:Cx:NCx` or a writer declaration with an admitted
formula and exact operands. `link_paper_claims` emits
`ari.paper-claim-links/v1`, including a final-TeX digest and a digest of the
complete link document. The finalizer recomputes this document rather than
trusting it.

The canonical lexical parser lives in `ari.public.latex_claims`; paper-specific
ScienceData/figure binding remains in `src.claim_links`.

## Review protocol

The text reviewer receives paper text only. VLM reviews receive the exact
FigureBatch artifacts. Semantic review and the deterministic hard gate are
separate evidence-grounded results. `merge_reviews` never mutates those inputs
or collapses them into one score.

## Supported migration

- Legacy rubric environment/default selection: offline
  `migrate_legacy_rubric_selection` only.
- Published pre-batch refinement call: read-only finalizer reader.
- Legacy per-section tools: removed; use whole-document authoring/review.
- Legacy claim/generic metric producer: not accepted by new authoring runs.

See `docs/reference/paper_build_contract.md` for schemas, operations, and the
deletion/rollback record.
