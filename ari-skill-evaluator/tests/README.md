# ari-skill-evaluator/tests

Pytest suite for the evaluator skill's MCP server.

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_metric_spec_claims.py` — TODO
- `test_s2p_tools.py` — Story2Proposal evaluator helpers + the non-blocking semantic-review no-op path (`_agg_score`, `_load_jsonish`, `evidence_grounded_semantic_review`).
- `test_server.py` — exercises extractor generation and `evaluate` against artefacts.
