"""Render a discovered ARI registry for Claude CLI's native MCP interface."""

from __future__ import annotations

from typing import Any

from ari.config import SkillConfig
from ari.mcp.dispatch_support import phase_is_disabled, phase_matches


def build_claude_mcp_config(
    *,
    skills: list[SkillConfig],
    connections: dict[str, Any],
    visible_tools: list[dict],
    phase: str | None,
) -> tuple[dict, list[str]]:
    """Return Claude's ``mcpServers`` document and fully-qualified allowlist."""

    servers: dict[str, dict] = {}
    allowed: list[str] = []
    for skill in skills:
        if phase_is_disabled(skill.phase):
            continue
        if phase is not None and not phase_matches(skill.phase, phase):
            continue
        connection = connections.get(skill.name)
        if connection is None:
            continue
        params = connection._server_params()
        servers[skill.name] = {
            "command": params.command,
            "args": list(params.args),
            "env": dict(params.env or {}),
        }
        allowed.extend(
            f"mcp__{skill.name}__{tool['name']}"
            for tool in visible_tools
            if tool.get("skill_name") == skill.name
        )
    return {"mcpServers": servers}, allowed


__all__ = ["build_claude_mcp_config"]
