---
sources:
  - path: ari-core/ari/public/paper.py
    role: schema
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-skill-paper/src/finalize.py
    role: implementation
  - path: ari-skill-paper/src/claim_links.py
    role: implementation
  - path: ari-core/ari/schemas/paper_build_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/paper_model_call_batch_v1.schema.json
    role: schema
last_verified: 2026-08-07
---

# Paper build contract

`PaperBuildV1` is the immutable record for an ARI-authored scientific paper.
The JSON Schema is published at
`ari-core/ari/schemas/paper_build_v1.schema.json`; Skill-facing Python imports
are available from `ari.public.paper`.

## Build lifecycle

1. `write_paper_iterative` validates native evidence under one
   `WorkspaceRefV1`, stores every authoring call, and writes
   `.ari-paper/paper_build.draft.json`.
2. Text, visual, semantic, and hard-gate review run independently.
3. `paper_refine` applies only unique replacements that keep every exact
   `% CLAIM:` declaration — the marker plus its `metric=`, `formula=` and
   operand tokens — and leave every renderer-owned figure environment
   byte-identical, and stores a digest-bound `PaperModelCallBatchV1`.
4. Code availability is injected deterministically.
5. Claim links, semantic review, hard gate, and compilation run again over the
   exact post-injection TeX.
6. `finalize_paper_build` recomputes and verifies the evidence graph, then writes
   `paper_build.json` with status `finalized`, `blocked`, or `compile-error`.

Only `finalized` is a successful scientific paper build. A blocked record is
persisted before the MCP tool reports failure, so the reason remains auditable.

## Required evidence

The authoring input set contains unique roles for:

- `science-data` — native, digest-bound `ScienceDataV1`;
- `figure-batch` — fixed-renderer `FigureBatchV1`;
- `retrieval-records` — `ari.retrieval-result/v1` whose snapshot and cassette
  reproduce through `snapshot_ref`;
- `ear-manifest` — an EAR generation result with `evidence_index_digest`;
- `template` and `rubric` — exact bytes selected for this build.

Finalization rereads every input and compares its size and SHA-256 to the draft
record. Changing an input after authoring is therefore a hard error.

`ARI_MANUSCRIPT_RUNTIME_MODE=enforce` additionally requires the roles
`manuscript-profile`, `manuscript-context`, `manuscript-readiness`,
`section-briefs`, and `manuscript-authoring-binding`, each supplied through its
own `ARI_MANUSCRIPT_*_PATH`. Authoring rejects a bundle whose profile, context,
readiness, brief-bundle and binding digests do not form one lineage, or whose
readiness is not `ready`/`ready_with_disclosures`; finalization rechecks that
lineage against the draft's `build_id` and `run_id` and blocks the build unless
the readiness publication verdict is `ready`. The mode defaults to `off`, and
the default pipeline supplies none of these inputs.

## Revision and model provenance

Every revision binds its direct parent and records:

- exact TeX and BibTeX artifacts;
- reason and associated model-call ID;
- claim anchors, citation keys, canonical figure IDs, and math digest.

Every stochastic call stores separate `prompt` and `raw-model-response`
artifacts plus provider, model, optional immutable revision, sampling values,
token counts, and reported cost. Multi-pass refinement uses
`PaperModelCallBatchV1`; each network call remains a distinct item.

The finalizer refuses to finalize if the last transformation drops an admitted
anchor, citation, figure, or changes mathematical content. A published reader
for the earlier single refinement-call record remains read-only; new producers
always emit the batch schema.

## Claim coverage

The shared lexical parser is `ari.public.latex_claims`. Paper-specific binding
is `ari-skill-paper/src/claim_links.py` and emits
`ari.paper-claim-links/v1` with:

- final-TeX digest;
- resolved/unresolved anchors;
- classified numeric mentions and uncovered result mentions;
- writer-declared formula operands;
- canonical figure references;
- digest of the complete document.

Numeric mentions on lines inside a figure environment bound to the FigureBatch
are classified `figure_evidence` and carry no anchor obligation: that caption
text is already owned and digested by `FigureBatchV1`. They stay in
`numeric_mentions` for auditing.

Finalization does not trust this intermediary: it recomputes the whole document
from the locked ScienceData, FigureBatch, and final TeX. A finalized build has
zero unresolved anchors and zero uncovered numeric result mentions. Explicit
numeric exclusions require a content-addressed exclusion policy; the default
pipeline does not create exclusions.

## Independent review set

`PaperReviewSetV1` keeps four artifacts separate:

- independent text review;
- independent VLM figure review;
- evidence-grounded semantic review;
- deterministic hard-gate report.

The text review must bind an authoring revision and retain its raw model
response. Every VLM target must match an exact FigureBatch manifest/artifact and
its bytes. The semantic review evidence digest must match the exact final TeX,
ScienceData projection, claim-link document, and hard-gate digest. No aggregate
score can replace these records.

## Compile policy

The compiler accepts only the fixed command names `pdflatex` and `bibtex`, a
safe root-level main file, canonical `refs.bib`, and graphics declared by
`FigureBatchV1`. It always adds `-no-shell-escape` and rejects TeX process/file
I/O, `input`/`include`, `filecontents`, absolute/traversal paths, and undeclared
graphics before execution.

Compilation uses the common `ExecutionRequestV1` process-group and resource
limits. Each pass retains complete stdout/stderr artifacts and execution
identity. Timeout, cancellation, tool absence, nonzero exit, missing PDF, and
PDF digest mismatch cannot become a completed compile.

## Rubric migration

Paper authoring and review require an explicit `rubric_id`. They do not read
`ARI_RUBRIC`, guess `neurips`, or silently fall back after a missing rubric.
`ARI_RUBRIC_DIR` remains a location override.

For an old launch document, run
`src.rubric_migration.migrate_legacy_rubric_selection`. It resolves the old
explicit field, `ARI_RUBRIC`, or historical default once, validates the rubric,
and returns a configuration with `paper_rubric` plus a version/digest migration
ledger. This helper is not called by runtime authoring.

## Removed runtime paths and rollback

Version 0.3.0 removed per-section `generate_section`, `review_section`, and
`revise_section`, generic node-tree metric discovery, the model figure inserter,
duplicate LaTeX parsing, caller-selected compiler paths, and raw subprocess
compilation. Use whole-document authoring/review, native contracts, the fixed
renderer, shared parser, and common execution contract respectively.

The rollback boundary is the last v0.2.0 paper Skill commit. Published
`PaperBuildV1`, legacy rubric migration, and pre-batch call readers are retained
as data readers; removed unsafe producer paths are not restored by replay.

## Verification

```bash
PYTHONPATH=ari-core pytest -q ari-skill-paper/tests
ruff check ari-skill-paper/src ari-skill-paper/tests
python scripts/sync_skill_metadata.py
python scripts/snapshot_contracts.py --surface public --check
python scripts/snapshot_contracts.py --surface mcp --check
```
