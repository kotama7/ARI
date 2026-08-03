# scripts/tests

Unit and smoke tests for the top-level `scripts/` quality checkers.

## Contents

- `README.md` — this file.
- `test_analyze_references.py` — unit + smoke + determinism tests for `analyze_references.py` (string-key/MCP fixtures + publish-backend/prompt non-orphan repo smoke).
- `test_check_bundle_budget.py` — unit + smoke tests for `check_bundle_budget.py` (Vite hash-stem extraction, entry/route/shared classification, tmp fake-dist over/within-budget + route-override + total-aggregate cases, gzip determinism, real-dist plan-09 budget smoke — skipped with a clear message when the frontend build is absent).
- `test_check_dashboard_ux.py` — unit + smoke tests for `check_dashboard_ux.py` (unquoted-key i18n extraction + duplicate detection, parity union-diff, `json_dump` scoped to `components/`, line-independent finding ids, route↔nav hidden-route allowlist, allowlist `known` marking, and repo smoke: zero net-new with the seeded allowlist, still exit 0 with an empty one).
- `test_check_dead_code.py` — unit + smoke + determinism tests for `check_dead_code.py` (precedence, hard-downgrade, ruff-gated `SAFE_DELETE` + `--check` ratchet, repo firewall smoke).
- `test_check_directory_policy.py` — unit + smoke tests for `check_directory_policy.py` (trio missing/kind/marker findings, `sonfigs/` + config-family collision while a benign `config2` sibling stays silent, Rule B new-storage-dir warning, Rule C tracked `node_modules`/`*.pyc` over the git universe, allowlist `known` marking, real-tree clean + `--strict` smoke).
- `test_check_doc_links.py` — intra-documentation Markdown/HTML link resolution, anchors, exclusions, and repo smoke tests.
- `test_check_docs_source_sync.py` — unit + smoke + determinism tests for `check_docs_source_sync.py` over a temp git repo (stale vs fresh `last_verified`, allowlist suppression, docs missing `sources`/`last_verified` skipped, translations ignored, fail-open when git history is absent, byte-identical reruns, shipped-allowlist validity).
- `test_check_import_boundaries.py` — unit + smoke tests for `check_import_boundaries.py` (B1/B2 fixtures + repo-level seed-edge smoke).
- `test_check_prompts.py` — unit + smoke tests for `check_prompts.py` (synthetic new/allowlisted, user-message negative filter, `agent/loop.py` negative control, census-reproduction + unique-id repo smoke, Gate 10 delegation).
- `test_check_skill_manifests.py` — manifest/package/runtime/workflow/schema conformance fixtures and repository smoke tests.
- `test_check_translation_freshness.py` — translation source timestamps, front matter, missing locales, and drift detection.
- `test_check_viz_api_schema.py` — unit + smoke tests for `check_viz_api_schema.py` (normalization + all-four-regime client extraction + server if/elif extraction fixtures + repo reconciliation smoke).
- `test_generate_quality_report.py` — unit + smoke tests for `generate_quality_report.py` (zero-checker graceful report, `--target` ingestion of valid/missing/malformed/unknown-version envelopes, JSON round-trip re-ingestible as `--baseline`, net-new delta with `--fail-on-regression`/`--warning-only` exits, `--run-checkers` ok/unavailable/crash, live per-area LOC + longest-prefix attribution, and the dead-code section's seven buckets + delta).
- `test_readme_sync.py` — deterministic Contents regeneration, description preservation, deletion, ignore, and drift checks.
