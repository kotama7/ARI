"""Tool-management helpers for AgentLoop (Phase 3D).

Three pure functions extracted from :class:`ari.agent.loop.AgentLoop`.
The class keeps thin delegating methods so subclasses + monkeypatches
don't need to change.

- :func:`available_tools_openai` — convert MCP tool list to the OpenAI
  function-calling shape, filtering ``_set_current_node`` and any
  user-supplied suppress set.
- :func:`execute_tool_calls`     — dispatch a batch of tool calls,
  routing CoW-guarded memory tools through ``cow_node_id``.
- :func:`active_tools`           — phase-aware filter over the
  available tool list (post-survey vs post-job-submit vs final
  output, etc.).
"""

from __future__ import annotations

import json as _json
from typing import Any

from ari.agent.message_utils import _tool_was_called
from ari.agent.workflow import WorkflowHints


# MCP tools that the parent (ari-core) drives itself and must never be
# exposed to the LLM — otherwise the model could set an arbitrary node
# id and bypass the memory skill's CoW check.
_INTERNAL_MCP_TOOLS = frozenset({"_set_current_node"})


def available_tools_openai(
    mcp: Any,
    suppress: set | None = None,
    phase: str | None = None,
) -> list[dict]:
    """Return the MCP tool list in OpenAI function-calling format.

    ``suppress`` excludes tools by name (e.g. already-called once-only
    tools); ``phase`` filters to tools whose declared phase matches.
    """
    suppress = (suppress or set()) | _INTERNAL_MCP_TOOLS
    return [
        {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema") or t.get("parameters") or {"type": "object", "properties": {}},
            },
        }
        for t in mcp.list_tools(phase=phase)
        if t.get("name", "") not in suppress
    ]


def execute_tool_calls(
    mcp: Any,
    tool_calls: list[dict],
    node_id: str | None = None,
) -> list[dict]:
    """Execute a batch of tool calls and return results.

    When *node_id* is provided and the call targets a CoW-guarded
    memory tool, ``cow_node_id`` is forwarded to ``mcp.call_tool`` so
    the ``(_set_current_node, write)`` pair is locked atomically —
    prevents the env-var race when ``max_parallel_nodes > 1``.
    """
    results = []
    for tc in tool_calls:
        func = tc.get("function", {})
        name = func.get("name", "")
        try:
            args = _json.loads(func.get("arguments", "{}"))
        except _json.JSONDecodeError:
            args = {}
        if node_id and name in mcp._COW_TOOLS:
            result = mcp.call_tool(name, args, cow_node_id=node_id)
        else:
            result = mcp.call_tool(name, args)
        results.append({"tool_call_id": tc.get("id", ""), "name": name, "result": result})
    return results


def active_tools(
    hints: WorkflowHints,
    all_tools: list[dict],
    messages: list[dict],
    job_ids: list[str],
    exec_called: bool,
    force_all: bool,
) -> list[dict] | None:
    """Filter available tools based on current progress.

    Returning ``None`` makes all tools available (e.g. during
    forced-finish phase).
    """
    if force_all or not all_tools:
        return None

    h = hints
    # If no sequence is specified, all tools are available
    if not h.tool_sequence:
        return None

    def by_name(*names: str) -> list[dict]:
        return [t for t in all_tools if t["function"]["name"] in names]

    # async job read complete
    if h.job_reader_tool and exec_called and job_ids:
        return None  # everything done → JSON output phase

    # async job submitted
    if h.job_submitter_tool and job_ids:
        # If job is COMPLETED, re-enable slurm_submit (for submitting the next experiment)
        _last_job_done = False
        for _msg in reversed(messages):
            if _msg.get("role") == "tool":
                try:
                    _r = _json.loads(_msg.get("content", "{}"))
                    if isinstance(_r, dict) and _r.get("status") in ("COMPLETED", "FAILED"):
                        _last_job_done = True
                except Exception:
                    pass
                break
        if _last_job_done:
            # COMPLETED: provide slurm_submit + run_bash + job_status
            # (even if stdout is null, can submit next experiment or read output file)
            extra = [h.job_submitter_tool] if h.job_submitter_tool else []
            rb = ["run_bash"] if any(t["function"]["name"] == "run_bash" for t in all_tools) else []
            candidates = extra + rb
            if h.job_poller_tool:
                candidates = candidates + [h.job_poller_tool]
            if h.job_reader_tool and h.job_reader_tool not in candidates:
                candidates = candidates + [h.job_reader_tool]
            return by_name(*candidates) or None
        candidates = []
        if h.job_poller_tool:
            candidates.append(h.job_poller_tool)
        if h.job_reader_tool:
            candidates.append(h.job_reader_tool)
        return by_name(*candidates) or None

    # All tools available — LLM decides what to call
    return None
