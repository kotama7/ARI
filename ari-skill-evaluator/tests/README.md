# ari-skill-evaluator/tests

Pytest suite for the evaluator skill's MCP server.

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_metric_spec_claims.py` — deterministic typed-contract mint, explicit
  proposal/admission, conservative legacy reading, mint-once persistence, and
  negative assertions that removed implicit LLM helpers stay absent.
- `test_prompt_extraction.py` — full-byte identities for the two versioned
  prompts and absence of the deleted extraction prompts.
- `test_s2p_tools.py` — typed hard-gate wrapper, independent semantic model
  policy, unavailable-state behavior, post-refine deltas, and hard-gate byte
  immutability.
- `test_server.py` — exercises the metric-spec parsing helpers (`_parse_success_metrics`, `_parse_metric_keyword`, `_parse_min_expected`, `_build_scoring_guide`).
