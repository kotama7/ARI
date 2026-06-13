# ari-skill-memory/tests

Pytest suite for the memory skill — ancestor scoping, checkpoint isolation,
copy-on-write, backup/restore, and Letta backend behaviour.

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `fake_letta.py` — Letta test double.
- `test_access_log.py` — access auditing.
- `test_ancestor_scope.py` — ancestor branch-scoping guarantees.
- `test_archival_pagination.py` — `_SdkLettaAdapter.archival_list` cursor pagination (sweeps all pages, dedups, single-page fallback when no cursor support).
- `test_backup_restore.py` — backup/restore.
- `test_checkpoint_isolation.py` — checkpoint isolation guarantees.
- `test_consolidation.py` — `consolidate_from_node_report` / `write_consolidated` (node_report → typed memory specs, in-memory round-trip).
- `test_cow.py` — copy-on-write branch-scoping guarantees.
- `test_global_tools_removed.py` — removed global-tools guard.
- `test_letta_embedding_compat.py` — Letta backend embedding compatibility.
- `test_letta_http_regression.py` — Letta backend HTTP regression coverage.
- `test_letta_live_integration.py` — Letta backend live-integration coverage.
- `test_llm_config_removed.py` — removed LLM-config guard.
- `test_memory.py` — core memory behaviour.
- `test_react.py` — ReAct behaviour.
- `test_research_memory_phase1.py` — Letta-free verifiability core: `ResearchMemory` schema validation, sha256 provenance, and artifact audit against disk.
- `test_research_memory_typed.py` — typed `writer`/`retriever` over the backend: kind stamping, ancestor scope, require_artifacts, reproducibility-event fold.
- `test_search_fallback.py` — search fallback behaviour.
- `test_server_typed_tools.py` — MCP server wiring for typed research-memory tools (registered, callable, round-trip through the backend).
- `test_verified_context.py` — `build_verified_context` for paper generation: ranks rerun_passed > grounded, gates usable_for_claims on artifacts, keeps failures as limitations, respects ancestor scope.
