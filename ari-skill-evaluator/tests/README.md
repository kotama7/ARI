# ari-skill-evaluator/tests

Pytest suite for the evaluator skill's MCP server.

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_metric_spec_claims.py` — `make_metric_spec` claims resolution: structured/LLM `falsifiable_claims` extraction (`_normalize_claims`, `_resolve_falsifiable_claims`), `metric_contract.json` persist + mint-once freeze, idea-owned contract flags, and the platform-capability note feeding the hard gate.
- `test_prompt_extraction.py` — TODO
- `test_s2p_tools.py` — Story2Proposal evaluator helpers + the non-blocking semantic-review no-op path (`_agg_score`, `_load_jsonish`, `evidence_grounded_semantic_review`).
- `test_server.py` — exercises the metric-spec parsing helpers (`_parse_success_metrics`, `_parse_metric_keyword`, `_parse_min_expected`, `_build_scoring_guide`).
