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
- `prompts/` — Externalized system-prompt templates for the paper-generation and peer-review tools, loaded byte-identically by `_load_prompt` in `server.py`.
  - `README.md` — prompts index.
  - `academic_reviewer.md` — `review_section` tool system prompt: single-section LaTeX peer review returning JSON (`overall` / `strengths` / `weaknesses` / `suggestions` / `accept_recommendation`) with a reproducibility criterion; the one `str.format` template (`{venue_upper}`).
  - `figure_inserter.md` — `write_paper_iterative` figure-injection pass: terse system prompt instructing a LaTeX expert to insert figures inline.
  - `fill_in_writer.md` — `write_paper_iterative` fill-in pass: the rules block appended to the writer system prompt that replaces each `FILL_*_START … FILL_*_END` placeholder with real LaTeX; carries the research-contract `% CLAIM` forward-declaration protocol.
  - `global_coherence.md` — `paper_refine` tool system prompt: the S2P global-coherence refiner that returns TARGETED find/replace JSON edits over the whole manuscript (never a full rewrite), preserving every `% CLAIM` anchor.
  - `paper_writer.md` — `write_paper_iterative` compile + reflection loop: system prompt to fix LaTeX/quality issues flagged by reflection without hallucinating results, hardware, or citations, returning the entire corrected document.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
