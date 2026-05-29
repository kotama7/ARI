# ari.mcp

MCP client used by the agent loop to talk to skills: owns the stdio
lifecycle of each `ari-skill-*` subprocess and routes tool calls + results.

## Contents

- `README.md` — this file.
- `__init__.py` — public `MCPClient` + contract.
- `client.py` — stdio connection pooling, retry, per-thread asyncio loop.

## See also

- **Public symbol (`MCPClient`) & contract** → the `__init__.py` module docstring (authoritative).
- **Tool catalogue** → `docs/reference/mcp_tools.md`.
- **Caller** → `ari-core/ari/agent/tool_manager.py`; **servers** → `ari-skill-*/`.
