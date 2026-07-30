# ari-skill-paper/tests

Pytest suite for the paper skill.

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_claim_links.py` — Story2Proposal Phase A2 claim-id post-processing (`% CLAIM` anchors, numeric classification, section parse, figure late-bind).
- `test_code_availability.py` — code-availability handling in the paper output.
- `test_prompt_extraction.py` — the five extracted paper system prompts (`paper_writer`, `fill_in_writer`, `academic_reviewer`, `figure_inserter`, `global_coherence`) load byte-identical to their pre-extraction inline literals, with pinned `load_versioned` sha256[:12].
- `test_rubric.py` — rubric loader/validator.
- `test_server.py` — `write_paper_iterative` behaviour.
- `test_verified_context_wiring.py` — write_paper injects the verified-context grounded block into the system prompt (graceful when absent).
- `test_writer_prompt_override.py` — the `writer_prompt_override` seam: `""` reproduces the loaded `paper_writer` / `global_coherence` prompts byte-for-byte, a non-empty override drives the governed bytes, and the skill imports no `ari.rqgm`.
