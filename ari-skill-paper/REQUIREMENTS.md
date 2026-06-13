# ari-skill-paper Requirements

## Overview

MCP Server for LaTeX paper writing assistance.
Manages academic templates, section generation, and format review.

## Design

- Called only in the post-BFTS pipeline (not inside the BFTS search loop)
- `generate_section` searches `nodes_tree.json` for relevant evidence (keyword-based)
- Default venue: arXiv (no page limit). Conference venues enforce their constraints.
- `<think>` tags from LLM output are stripped automatically.

## Tech Stack

- Python 3.11+
- FastMCP
- litellm (LLM calls for generation and review)

## Tool Specifications

### generate_section(section: str, goal: str, artifacts: str, venue: str = "arxiv", nodes_json_path: str = "") -> dict
Generates a LaTeX section. Enriches context with up to 8 matching nodes from the tree.

### review_section(section_tex: str, venue: str = "arxiv") -> dict
Reviews the generated section for clarity, correctness, and venue compliance.

## Story2Proposal integration (Research Contract)

### write_paper_iterative — claims registry + anchors + forward declaration (Phase A2 / (c))
When `science_data.json` carries `claims[]`, the writer prompt is enriched with a
"RESEARCH CONTRACT — CANDIDATE CLAIMS" block and instructed (system rule 10) to
emit a LaTeX comment anchor `% CLAIM:Cx:NCx` immediately before any sentence
stating a numeric result that corresponds to a candidate claim. Non-result
numbers (years, figure/table indices, settings) are not anchored.

**Forward declaration (Story2Proposal (c)).** For result numbers that are NOT a
pre-generated candidate claim, the writer is also given a "FORWARD-DECLARATION —
CONFIG HANDLES" block (`cfgN` + each config's metric_keys, from
`science_data._config_nodes`) and instructed to DECLARE the derivation inline:
`% CLAIM:Cw:NCw metric=<key> formula=<formula> <operands>` where operands are
`value=cfgN` (identity), `baseline=cfgN proposed=cfgM` (same-metric comparison),
or `baseline=cfgN:metricA proposed=cfgN:metricB` (cross-metric ratio, e.g.
measured/ceiling attainment via `ratio_percent`). The hard gate re-derives every
declared number from the executed data (forward, no reverse search), so a wrong
declaration is caught as `numeric_mismatch` — the writer cannot launder a number.

### link_paper_claims(tex_path, science_data_json, figures_manifest_json) -> dict (Phase A2)
Deterministic post-processor (no LLM). Produces `paper_claim_links` (anchor-keyed:
`claim_id/numeric_id/section/span_hash/line_range/figures/resolved`),
`numeric_mentions` (classified: result_claim / experimental_setting /
citation_year / figure_table_ref / ambiguous), `writer_assertions` (the writer's
inline forward declarations parsed into verifiable assertions: `id/claim_id/
metric/formula/operands(node_id,metric_path)/line`, with `unresolved_config_refs`
when a `cfgN` is unknown), `figure_refs` (late-bound figure ids),
`unresolved_anchors`, `uncovered_numeric_candidates`. An anchor is `resolved` if it
references a pre-generated assertion OR carries a valid inline declaration. The
**anchor** is the stable key; `span_hash` detects sentence change; `line_range` is
auxiliary (a `% CLAIM` comment line binds to the following prose line, not itself).
**`science_data.json` is never mutated** (figure binding recorded here). Run after
write_paper (draft) and after paper_refine (final). Degrades to a valid empty
result on failure (never error-only) to protect the finalize chain. Pure logic in
`src/claim_links.py`.

### paper_refine(tex_path, merged_review_path, semantic_review_path) -> dict (Phase E)
S2P refiner role (eq. 5 `(M',C)=A_ref({D_i},C)`): **global coherence** over the
whole manuscript (cross-section consistency, redundancy compression, terminology
harmonization, visual reconciliation) + the merged `suggested_revisions`. It is a
**bounded** task, NOT a full rewrite — so the model sees the whole paper (global
context) but returns **targeted diff edits** (`[{"find": <verbatim unique span>,
"replace": <revised span>}]`), not a regenerated document. Edits are applied
**deterministically and safely**: only a `find` that occurs **exactly once** is
applied (ambiguous/absent → skipped, never guessed), and only if every `% CLAIM`
anchor inside the span survives in `replace` (anchor-dropping edits skipped). On
zero safe edits or anchor loss it reverts to the draft (`refined=False`). No-op
when there are no revisions. Overwrites `full_paper.tex` (draft saved as
`full_paper.draft.tex`). **Why diff, not full rewrite:** regenerating the entire
LaTeX in one call (the previous design, `max_tokens=16384`, "complete revised
document") is slow via the CLI shim and, with the retry layers, timed out and
skipped finalize; bounding output to the changed spans fixes this while keeping
the refiner's global role (the per-section localized edits are the writer's job in
S2P). PDF recompilation is a documented follow-up (the `.tex` is the living
artifact the hard gate and finalize consume).

### merge_reviews — independent vs evidence-grounded split (Phase E)
Splits into `independent_reviews` (review_paper + vlm_review_figures, unchanged —
reviewer independence preserved) and `evidence_grounded_reviews`
(claim_evidence_hard_gate + evidence_grounded_semantic_review), and emits a
unified `suggested_revisions` list for `paper_refine`. Structural only (no LLM).

### review_compiled_paper — UNCHANGED
The independent text reviewer is not modified; it still evaluates paper text only.

## Status

Story2Proposal Phase A2 + E code + unit tests complete
(`tests/test_claim_links.py`). Real compute-node validation pending; see
`PLAN_s2p_claim_annotation.md` and `../ari-core/PLAN_s2p_merge_refine.md`.
