# scripts/tests

Unit and smoke tests for the top-level `scripts/` quality checkers.

## Contents

- `README.md` — this file.
- `test_analyze_references.py` — unit + smoke + determinism tests for `analyze_references.py` (string-key/MCP fixtures + publish-backend/prompt non-orphan repo smoke).
- `test_check_import_boundaries.py` — unit + smoke tests for `check_import_boundaries.py` (B1/B2 fixtures + repo-level seed-edge smoke).
