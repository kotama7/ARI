# ari-skill-paper/src

MCP server package for the paper skill — AI Scientist v2-style iterative
LaTeX paper generation (generate → review → revise per section), plus a
rubric-driven peer-review engine. `__init__.py` is empty; the package is
imported as `src`.

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `claim_links.py` — deterministic claim-id post-processing (Story2Proposal Phase A2): reconciles `% CLAIM:Cx:NCx` anchors against science_data claims, classifies numeric mentions, late-binds figures → `paper_claim_links`.
- `review_engine.py` — rubric-driven review pipeline (score dimensions, reflection loop, few-shot).
- `rubric.py` — venue-agnostic YAML rubric loader/validator (sha256 for P2 determinism).
- `server.py` — MCP entry point: `write_paper_iterative` (now injects the claims registry + `% CLAIM` anchor instruction), `link_paper_claims`, `paper_refine` (anchor-preserving), `merge_reviews` (independent vs evidence-grounded split), `review_compiled_paper`, …

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
