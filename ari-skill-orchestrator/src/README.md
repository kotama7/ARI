# Orchestrator source layout

- `server.py` — fixed FastMCP tool surface and stdio/Streamable HTTP adapters.
- `ari_skill_orchestrator/contracts.py` — immutable public v1 contracts.
- `ari_skill_orchestrator/registry*.py` — SQLite idempotency, lineage, schema, and state authority.
- `ari_skill_orchestrator/runtime.py` — validated deployment policy and hardened file/process helpers.
- `ari_skill_orchestrator/execution.py` — wrapper launch, receipt validation, and attach-race handling.
- `ari_skill_orchestrator/service.py` — compact transport-neutral lifecycle facade.
- `ari_skill_orchestrator/migration.py` — explicit fail-closed pre-v2 checkpoint repair.
- `ari_skill_orchestrator/views.py` — bounded progress and sanitized lock projections.
- `ari_skill_orchestrator/runner.py` — process-group owner and atomic restart receipt.
- `ari_skill_orchestrator/artifacts.py` — closed artifact admission and digest verification.
- `ari_skill_orchestrator/auth.py` — local principal and MCP bearer-token adapter.

No transport owns business logic. See
[the permanent reference](../../docs/reference/orchestrator.md).
