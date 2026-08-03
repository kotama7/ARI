# ari-skill-paper/tests

Pytest suite for the paper skill.

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_claim_links.py` — Story2Proposal Phase A2 claim-id post-processing (`% CLAIM` anchors, numeric classification, section parse, figure late-bind).
- `test_code_availability.py` — code-availability handling in the paper output.
- `test_compiler.py` — TODO
- `test_finalize.py` — TODO
- `test_prompt_extraction.py` — TODO
- `test_retrieval_snapshot_wiring.py` — TODO
- `test_rubric.py` — rubric loader/validator.
- `test_rubric_migration.py` — TODO
- `test_server.py` — `write_paper_iterative` behaviour.
- `test_verified_context_wiring.py` — write_paper injects the verified-context grounded block into the system prompt (graceful when absent).
