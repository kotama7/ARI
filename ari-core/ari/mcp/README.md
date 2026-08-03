# ari.mcp

MCP client used by the agent loop to talk to skills: owns the stdio
lifecycle of each `ari-skill-*` subprocess and routes tool calls + results.

## Contents

- `README.md` — this file.
- `__init__.py` — public `MCPClient` + contract.
- `child_environment.py` — exact child allowlist, credential scopes, and redaction.
- `claude_bridge.py` — value-free Claude CLI MCP config and allowed-tool rendering.
- `client.py` — registry, typed dispatch, retry, and connection pooling.
- `connection.py` — one provider's stdio lifecycle and event-loop thread.
- `dispatch_support.py` — pure identity, phase, timeout, and tracing policy.
- `invoke_runtime.py` — retries, cancellation, and typed transport normalization.
- `lock_runtime.py` — per-client exact/subset `SKILLS.lock` reconciliation state.
- `registry_runtime.py` — live discovery, enrichment, and collision admission.
- `secure_stdio_proxy.py` — exact-env/redacting boundary for direct MCP clients.

## See also

- **Public symbol (`MCPClient`) & contract** → the `__init__.py` module docstring (authoritative).
- **Tool catalogue** → `docs/reference/mcp_tools.md`.
- **Caller** → `ari-core/ari/agent/tool_manager.py`; **servers** → `ari-skill-*/`.
