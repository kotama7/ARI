"""Tests: SYSTEM_PROMPT memory rules are gated on memory-skill availability.

When memory-skill is disabled via workflow (phase: none) the MCP client
never registers add_memory / add_global_memory, so the LLM must not be
told to save memories.
"""
from __future__ import annotations

from ari.agent.loop import (
    SYSTEM_PROMPT,
    _MEMORY_RULES_PER_NODE,
    _MEMORY_RULES_GLOBAL,
)


def _render(tool_names: list[str], node_id: str = "root") -> str:
    memory_rules = ""
    if "add_memory" in tool_names:
        memory_rules += _MEMORY_RULES_PER_NODE.format(node_id=node_id)
    if "add_global_memory" in tool_names:
        memory_rules += _MEMORY_RULES_GLOBAL
    return SYSTEM_PROMPT.format(
        tool_desc=", ".join(tool_names) or "none",
        memory_rules=memory_rules,
        extra="",
    )


def test_prompt_omits_memory_rules_when_disabled():
    out = _render(["run_bash", "survey"])
    assert "add_memory" not in out
    assert "add_global_memory" not in out
    assert "search_memory" not in out


def test_prompt_includes_per_node_rules_when_add_memory_available():
    out = _render(["run_bash", "add_memory", "search_memory"], node_id="node_abc")
    assert "add_memory(node_id=\"node_abc\"" in out
    assert "search_memory" in out
    assert "add_global_memory" not in out


def test_prompt_includes_global_rules_when_global_available():
    out = _render(
        ["run_bash", "add_memory", "add_global_memory", "search_global_memory"],
        node_id="n1",
    )
    assert "add_memory(node_id=\"n1\"" in out
    assert "add_global_memory" in out
    assert "search_global_memory" in out
    assert "cross-experiment" in out


def test_prompt_global_only_without_per_node():
    """Edge case: only global tool registered — per-node rules must not appear."""
    out = _render(["add_global_memory", "search_global_memory"])
    assert "add_global_memory" in out
    # per-node marker (node_id=) only appears in per-node template
    assert "node_id=" not in out
