# ari-skill-paper/src/prompts

Externalized system-prompt templates for the paper-generation and peer-review tools, loaded byte-identically by `_load_prompt` in `server.py`.

Most templates are loaded RAW because they embed literal LaTeX/JSON braces; `academic_reviewer` is the one `str.format` template (single `{venue_upper}` placeholder). `_load_prompt_versioned` also exposes a `sha256[:12]` of each on-disk body for prompt provenance (P2 determinism — a package-relative file read, no LLM, no network).

## Contents

- `README.md` — this file.
- `academic_reviewer.md` — `review_section` tool system prompt: single-section LaTeX peer review returning JSON (`overall` / `strengths` / `weaknesses` / `suggestions` / `accept_recommendation`) with a reproducibility criterion; the one `str.format` template (`{venue_upper}`).
- `figure_inserter.md` — `write_paper_iterative` figure-injection pass: terse system prompt instructing a LaTeX expert to insert figures inline.
- `fill_in_writer.md` — `write_paper_iterative` fill-in pass: the rules block appended to the writer system prompt that replaces each `FILL_*_START … FILL_*_END` placeholder with real LaTeX; carries the research-contract `% CLAIM` forward-declaration protocol.
- `global_coherence.md` — `paper_refine` tool system prompt: the S2P global-coherence refiner that returns TARGETED find/replace JSON edits over the whole manuscript (never a full rewrite), preserving every `% CLAIM` anchor.
- `paper_writer.md` — `write_paper_iterative` compile + reflection loop: system prompt to fix LaTeX/quality issues flagged by reflection without hallucinating results, hardware, or citations, returning the entire corrected document.
