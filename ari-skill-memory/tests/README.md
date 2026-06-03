# ari-skill-memory/tests

Pytest suite for the memory skill — ancestor scoping, checkpoint isolation,
copy-on-write, backup/restore, and Letta backend behaviour.

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `fake_letta.py` — Letta test double.
- `test_access_log.py` — access auditing.
- `test_ancestor_scope.py` — ancestor branch-scoping guarantees.
- `test_backup_restore.py` — backup/restore.
- `test_checkpoint_isolation.py` — checkpoint isolation guarantees.
- `test_cow.py` — copy-on-write branch-scoping guarantees.
- `test_global_tools_removed.py` — removed global-tools guard.
- `test_letta_embedding_compat.py` — Letta backend embedding compatibility.
- `test_letta_http_regression.py` — Letta backend HTTP regression coverage.
- `test_letta_live_integration.py` — Letta backend live-integration coverage.
- `test_llm_config_removed.py` — removed LLM-config guard.
- `test_memory.py` — core memory behaviour.
- `test_react.py` — ReAct behaviour.
- `test_research_memory_phase1.py` — TODO
- `test_research_memory_typed.py` — TODO
- `test_search_fallback.py` — search fallback behaviour.
- `test_verified_context.py` — TODO
