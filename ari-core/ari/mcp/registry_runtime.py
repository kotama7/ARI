"""Live MCP discovery and immutable runtime registry assembly."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

from ari.config import SkillConfig
from ari.mcp.dispatch_support import (
    ToolNameCollisionError,
    phase_is_disabled,
    runtime_tool_ref,
)
from ari.skill_lock import SkillProviderAdmissionError


logger = logging.getLogger(__name__)


class ToolDiscoveryConnection(Protocol):
    def list_tools(self) -> list[dict]: ...


@dataclass(frozen=True)
class DiscoveredRegistry:
    tools: list[dict]
    owner_by_name: dict[str, str]
    owner_by_ref: dict[str, str]
    name_by_ref: dict[str, str]
    ref_by_name: dict[str, str]
    metadata_by_ref: dict[str, dict]


def discover_registry(
    skills: list[SkillConfig],
    *,
    init_connection: Callable[[SkillConfig], ToolDiscoveryConnection],
    close_all: Callable[[], None],
    strict_provider_loading: bool,
) -> DiscoveredRegistry:
    """Discover enabled providers and reject ambiguous runtime identities."""

    tools: list[dict] = []
    owner_by_name: dict[str, str] = {}
    owner_by_ref: dict[str, str] = {}
    name_by_ref: dict[str, str] = {}
    ref_by_name: dict[str, str] = {}
    collisions: dict[str, set[str]] = {}

    for skill in skills:
        if phase_is_disabled(getattr(skill, "phase", "all")):
            logger.info("Skipping disabled skill '%s' (phase=none)", skill.name)
            continue
        try:
            skill_tools = init_connection(skill).list_tools()
            for raw_tool in skill_tools:
                tool = dict(raw_tool)
                tool_ref = runtime_tool_ref(skill, tool)
                tool["tool_ref"] = tool_ref
                capability_ref = skill.tool_capabilities.get(tool["name"])
                if capability_ref:
                    tool["capability_ref"] = capability_ref
                policy = skill.tool_policies.get(tool["name"])
                if policy:
                    tool["policy"] = policy

                previous = owner_by_name.get(tool["name"])
                if previous is not None and previous != skill.name:
                    collisions.setdefault(tool["name"], {previous}).add(skill.name)
                else:
                    owner_by_name[tool["name"]] = skill.name
                    ref_by_name[tool["name"]] = tool_ref
                previous_ref = owner_by_ref.get(tool_ref)
                if previous_ref is not None and previous_ref != skill.name:
                    raise ToolNameCollisionError(
                        f"immutable tool_ref collision: {tool_ref}"
                    )
                owner_by_ref[tool_ref] = skill.name
                name_by_ref[tool_ref] = tool["name"]
                tools.append(tool)
            logger.info("Loaded %d tools from skill '%s'", len(skill_tools), skill.name)
        except ToolNameCollisionError:
            raise
        except Exception as exc:
            if strict_provider_loading:
                close_all()
                raise SkillProviderAdmissionError(
                    f"required MCP Skill '{skill.name}' failed live discovery: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            logger.warning("Failed to load skill '%s': %s", skill.name, exc)

    if collisions:
        rendered = "; ".join(
            f"{name}: {', '.join(sorted(owners))}"
            for name, owners in sorted(collisions.items())
        )
        close_all()
        raise ToolNameCollisionError(
            "Ambiguous MCP tool names are not admitted; configure one owner "
            f"or use a namespaced registry: {rendered}"
        )

    return DiscoveredRegistry(
        tools=tools,
        owner_by_name=owner_by_name,
        owner_by_ref=owner_by_ref,
        name_by_ref=name_by_ref,
        ref_by_name=ref_by_name,
        metadata_by_ref={tool["tool_ref"]: tool for tool in tools},
    )


__all__ = ["DiscoveredRegistry", "ToolDiscoveryConnection", "discover_registry"]
