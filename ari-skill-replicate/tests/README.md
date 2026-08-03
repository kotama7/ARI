# ari-skill-replicate/tests

Pytest suite for the replicate skill (auto-rubric generation + auditing).

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_auditor.py` — `auditor` coverage.
- `test_categories.py` — `categories` coverage.
- `test_generator.py` — `generator` coverage.
- `test_manifest.py` — `manifest` coverage.
- `test_prompt_snapshots.py` — TODO
- `test_rubric_template.py` — `rubric_template` coverage.
- `test_schema.py` — rubric validation against `schemas/replication_rubric.schema.json`.
- `test_server_env.py` — server env wiring.
- `fixtures/` — test fixtures (not enumerated)
- `snapshots/` — TODO
  - `prompts/` — TODO
    - hierarchical skeleton/subtree prompt coverage
    - `rubric_audit.md` — TODO
    - `skeleton.md` — TODO
    - `subtree.md` — TODO
