"""Render a discovered ARI registry for Claude CLI's native MCP interface."""

from __future__ import annotations

import json
import sys
from typing import Any

from ari.call_context import ToolCallContextV1
from ari.config import SkillConfig
from ari.mcp.dispatch_support import phase_is_disabled, phase_matches


def build_claude_mcp_config(
    *,
    skills: list[SkillConfig],
    connections: dict[str, Any],
    visible_tools: list[dict],
    phase: str | None,
    context: ToolCallContextV1 | None = None,
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
        child_environment = connection.child_environment
        skill_tools = []
        for tool in visible_tools:
            if tool.get("skill_name") != skill.name:
                continue
            requirement = str(
                (tool.get("policy") or {}).get("context_requirement") or "none"
            )
            if requirement != "none" and (
                context is None or not context.satisfies(requirement)
            ):
                continue
            skill_tools.append(tool)
        if not skill_tools:
            continue
        context_requirements = {
            str(tool["name"]): str(
                (tool.get("policy") or {}).get("context_requirement") or "none"
            )
            for tool in skill_tools
            if str((tool.get("policy") or {}).get("context_requirement") or "none")
            != "none"
        }
        markers = {
            env_name: str(identity["scope_id"])
            for identity in child_environment.credential_scope_identities
            for env_name in identity["present_env"]
        }
        proxy_spec = {
            "command": params.command,
            "args": list(params.args),
            "env_names": sorted(
                set(child_environment.transport_values())
                | set(child_environment.credential_env_names)
            ),
            "credential_markers": markers,
            "context_requirements": context_requirements,
        }
        if context_requirements:
            assert context is not None
            proxy_spec["call_context"] = context.model_dump(mode="json")
        servers[skill.name] = {
            "command": sys.executable,
            "args": [
                "-m",
                "ari.mcp.secure_stdio_proxy",
                "--spec",
                json.dumps(
                    proxy_spec,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ],
            "env": child_environment.transport_values(),
        }
        if child_environment.credential_env_names:
            servers[skill.name]["_ariCredentialEnv"] = list(
                child_environment.credential_env_names
            )
        allowed.extend(
            f"mcp__{skill.name}__{tool['name']}"
            for tool in skill_tools
        )
    return {"mcpServers": servers}, allowed


__all__ = ["build_claude_mcp_config"]
