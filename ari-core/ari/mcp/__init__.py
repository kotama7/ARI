"""ari.mcp — MCP client used by the agent loop to talk to skills.

Owns the stdio lifecycle of every ``ari-skill-*`` subprocess and routes
tool calls + tool-result messages between the LLM and the skill.

Public symbols:
- ``MCPClient`` — connect/serve/dispatch wrapper around the MCP protocol.

See also:
- ``ari-core/ari/agent/tool_manager.py`` (caller).
- ``ari-skill-*/`` (each skill is a separate MCP server).
"""
