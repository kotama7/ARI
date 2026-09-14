# ari-skill-replicate/tests

Pytest suite for the replicate skill (auto-rubric generation + auditing).

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_auditor.py` — `auditor` coverage.
- `test_categories.py` — `categories` coverage.
- `test_generator.py` — `generator` coverage.
- `test_manifest.py` — `manifest` coverage.
- `test_migration.py` — legacy rubric conversion, audit output, idempotence, and unsupported-input rejection.
- `test_prompt_snapshots.py` — raw byte snapshots of every `src/prompts/*.md`, the only drift guard for templates loaded via ad-hoc `Path.read_text()`; re-bless with `ARI_UPDATE_PROMPT_SNAPSHOTS=1`.
- `test_rubric_template.py` — `rubric_template` coverage.
- `test_schema.py` — rubric validation against `schemas/replication_rubric.schema.json`.
- `test_server_env.py` — server env wiring.
- `test_v2_provenance.py` — v2 rubric provenance, calibration fixtures, digest binding, and tamper rejection.
- `fixtures/` — test fixtures (not enumerated)
- `snapshots/` — golden files for `test_prompt_snapshots.py` (only `prompts/`).
  - `prompts/` — byte goldens, one per `src/prompts/*.md` template.
    - `rubric_audit.md` — golden copy of `src/prompts/rubric_audit.md` (per-leaf quality flags).
    - `skeleton.md` — golden copy of `src/prompts/skeleton.md` (Pass 1: rubric root + direct children).
    - `subtree.md` — golden copy of `src/prompts/subtree.md` (Pass 2: populate a subtree with leaves).
