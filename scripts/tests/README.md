# scripts/tests

Unit and smoke tests for the top-level `scripts/` quality checkers.

## Contents

- `README.md` — this file.
- `test_analyze_references.py` — unit + smoke + determinism tests for `analyze_references.py` (string-key/MCP fixtures + publish-backend/prompt non-orphan repo smoke).
- `test_check_dashboard_ux.py` — TODO
- `test_check_dead_code.py` — unit + smoke + determinism tests for `check_dead_code.py` (precedence, hard-downgrade, ruff-gated `SAFE_DELETE` + `--check` ratchet, repo firewall smoke).
- `test_check_directory_policy.py` — TODO
- `test_check_docs_source_sync.py` — TODO
- `test_check_import_boundaries.py` — unit + smoke tests for `check_import_boundaries.py` (B1/B2 fixtures + repo-level seed-edge smoke).
- `test_check_prompts.py` — unit + smoke tests for `check_prompts.py` (synthetic new/allowlisted, user-message negative filter, `agent/loop.py` negative control, census-reproduction + unique-id repo smoke, Gate 10 delegation).
- `test_check_viz_api_schema.py` — unit + smoke tests for `check_viz_api_schema.py` (normalization + all-four-regime client extraction + server if/elif extraction fixtures + repo reconciliation smoke).
- `test_generate_quality_report.py` — TODO
