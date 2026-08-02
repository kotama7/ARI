# ari-skill-paper

Evidence-grounded whole-document paper generation for ARI. The supported path
consumes native `ScienceDataV1`, `FigureBatchV1`, a recorded retrieval snapshot,
and an EAR manifest through one closed checkpoint workspace. It writes LaTeX and
BibTeX, performs bounded review/refinement, recompiles with the common execution
contract, and locks the result as `PaperBuildV1`.

## Scientific boundary

- Numeric result prose is linked to `% CLAIM:Cx:NCx` anchors and independently
  checked by the evaluator hard gate.
- Figure values, units, paths, captions, and labels come from the immutable
  `FigureBatchV1`; the writer cannot replace them with model-generated values.
- Literature is accepted only from a verified `SurveySnapshotV1` reference.
- Every authoring/refinement call stores the exact prompt, raw response,
  model/revision/provider, sampling, token counts, and reported cost.
- Text, visual, semantic, and hard-gate reviews remain independent fields.
- Finalization recomputes claim links from the exact final TeX and verifies all
  input/review/artifact digests before declaring the build finalized.

The complete contract and migration policy are documented in
[`docs/reference/paper_build_contract.md`](../docs/reference/paper_build_contract.md).

## Primary inputs

`write_paper_iterative` requires:

- `workspace_root`
- `science_data_path` (`ScienceDataV1`)
- `figures_manifest_path` (`FigureBatchV1`)
- `references_path` (`ari.retrieval-result/v1` with `snapshot_ref`)
- `ear_manifest_path` (must contain `evidence_index_digest`)
- `rubric_id` (explicit; no environment/default fallback)
- `venue`

`verified_context_path` is optional. Paths must remain inside `workspace_root`.
The output includes `full_paper.tex`, `refs.bib`, immutable authoring artifacts,
and `.ari-paper/paper_build.draft.json`.

## MCP tools

| Tool | Purpose |
|---|---|
| `list_venues` | List bundled venue templates |
| `get_template` | Read one venue template |
| `compile_paper` | Compile through fixed `pdflatex`/`bibtex` argv and bounded execution |
| `check_format` | Check PDF format constraints |
| `write_paper_iterative` | Native-evidence whole-document authoring and reflection |
| `review_compiled_paper` | Explicit-rubric independent text review with raw-response artifact |
| `link_paper_claims` | Deterministically bind anchors/numeric mentions to evidence |
| `paper_refine` | Anchor-preserving bounded find/replace refinement |
| `list_rubrics` | List versioned rubric contracts |
| `inject_code_availability` | Deterministically bind the published EAR/code digest |
| `merge_reviews` | Preserve and route independent/evidence-grounded reviews |
| `finalize_paper_build` | Fail-closed final artifact/review/gate lock |

The old per-section `generate_section`, `review_section`, and `revise_section`
runtime tools were removed in v0.3.0. Migrate to `write_paper_iterative` and
`review_compiled_paper`.

## Rubrics

`rubric_id` is mandatory for authoring and review. `ARI_RUBRIC_DIR` may point to
an alternate rubric directory, but runtime selection never reads `ARI_RUBRIC`
and never guesses `neurips`. Existing launch documents can be converted with
`src.rubric_migration.migrate_legacy_rubric_selection`, which emits a migration
ledger containing the selected rubric version and digest.

## Compilation

The compiler accepts only root-level `.tex`, canonical `refs.bib`, and graphics
declared by `FigureBatchV1`. Shell escape, TeX file I/O, undeclared includes, and
caller-selected binaries are rejected. Complete stdout/stderr logs and execution
identities are retained for every pass; timeouts use the common process-group
cleanup contract.

## Tests

```bash
PYTHONPATH=../ari-core pytest -q tests
ruff check src tests
```
