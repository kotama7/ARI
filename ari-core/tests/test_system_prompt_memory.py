"""Tests: SYSTEM_PROMPT memory rules are gated on memory-skill availability.

When memory-skill is disabled via workflow (phase: none) the MCP client
never registers add_memory, so the LLM must not be told to save memories.
The global memory tools (``add_global_memory`` /
``search_global_memory`` / ``list_global_memory``) were removed in
v0.6.0, so the prompt must no longer reference them.
"""
from __future__ import annotations

from ari.agent.loop import SYSTEM_PROMPT, _MEMORY_RULES_PER_NODE


def _render(tool_names: list[str], node_id: str = "root") -> str:
    memory_rules = ""
    if "add_memory" in tool_names:
        memory_rules += _MEMORY_RULES_PER_NODE.format(node_id=node_id)
    return SYSTEM_PROMPT.format(
        tool_desc=", ".join(tool_names) or "none",
        memory_rules=memory_rules,
        extra="",
    )


def test_prompt_omits_memory_rules_when_disabled():
    out = _render(["run_bash", "survey"])
    assert "add_memory" not in out
    assert "search_memory" not in out


def test_prompt_includes_per_node_rules_when_add_memory_available():
    out = _render(["run_bash", "add_memory", "search_memory"], node_id="node_abc")
    assert "add_memory(node_id=\"node_abc\"" in out
    assert "search_memory" in out


def test_prompt_never_mentions_global_tools_in_rules():
    """§3 — global memory is gone; the *rules* block must not reference it.

    The tool names may still appear in ``tool_desc`` (a literal list of
    callable tools) if legacy tools are registered upstream, but the
    memory-rules block assembled from _MEMORY_RULES_PER_NODE must not
    mention global memory or invite the LLM to use it.
    """
    node_id = "nX"
    rules = _MEMORY_RULES_PER_NODE.format(node_id=node_id)
    assert "add_global_memory" not in rules
    assert "search_global_memory" not in rules
    assert "cross-experiment" not in rules
