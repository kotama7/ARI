"""Tool-management helpers for AgentLoop (Phase 3D).

Three pure functions extracted from :class:`ari.agent.loop.AgentLoop`.
The class keeps thin delegating methods so subclasses + monkeypatches
don't need to change.

- :func:`available_tools_openai` — convert MCP tool list to the OpenAI
  function-calling shape, filtering any user-supplied suppress set.
- :func:`execute_tool_calls`     — dispatch a batch of tool calls,
  attaching the explicit run/node context to every dispatch.
- :func:`active_tools`           — phase-aware filter over the
  available tool list (post-survey vs post-job-submit vs final
  output, etc.).
"""

from __future__ import annotations

import json as _json
import time as _time
from typing import Any

from ari.call_context import ToolCallContextV1
from ari.agent.message_utils import _tool_was_called
from ari.agent.workflow import WorkflowHints


def available_tools_openai(
    mcp: Any,
    suppress: set | None = None,
    phase: str | None = None,
    context: ToolCallContextV1 | None = None,
) -> list[dict]:
    """Return the MCP tool list in OpenAI function-calling format.

    ``suppress`` excludes tools by name (e.g. already-called once-only
    tools); ``phase`` filters to tools whose declared phase matches.
    """
    suppress = suppress or set()
    try:
        listed_tools = mcp.list_tools(phase=phase, context=context)
    except TypeError as context_error:
        # Compatibility for pre-context clients and lightweight test doubles.
        # Only retry a callable that explicitly rejects the new keyword; do
        # not hide TypeError raised by the implementation itself.
        message = str(context_error)
        if "context" not in message or "unexpected keyword" not in message:
            raise
        listed_tools = mcp.list_tools(phase=phase)
    return [
        {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema") or t.get("parameters") or {"type": "object", "properties": {}},
            },
        }
        for t in listed_tools
        if t.get("name", "") not in suppress
    ]


# ── Per-node wall-clock budget for command execution ────────────────────────
# A single run_bash is capped by its own timeout, but nothing capped the SUM.
# One node could therefore spend the whole per-node timeout on shell calls and
# be killed by the outer watchdog with no report at all, which is the worst
# outcome: no score, no self-report, and no signal about why. Tracked per node
# so a long build is fine while a loop of them is not. 0 disables the cap.
_EXEC_TOOLS = frozenset({"run_bash", "run_code"})
_exec_spent: dict[str, float] = {}


def exec_budget_seconds() -> float:
    """Per-node wall-clock budget for run_bash/run_code, 0 to disable."""
    import os as _os

    try:
        return float(_os.environ.get("ARI_NODE_EXEC_BUDGET_S", "1800") or 0)
    except ValueError:
        return 1800.0


def reset_exec_budget(node_id: str | None) -> None:
    """Start a fresh budget for a node."""
    if node_id:
        _exec_spent.pop(str(node_id), None)


def exec_budget_remaining(node_id: str | None) -> float:
    """Seconds of command execution this node may still use (inf when off)."""
    budget = exec_budget_seconds()
    if budget <= 0 or not node_id:
        return float("inf")
    return max(0.0, budget - _exec_spent.get(str(node_id), 0.0))



def execute_tool_calls(
    mcp: Any,
    tool_calls: list[dict],
    context: ToolCallContextV1 | None = None,
) -> list[dict]:
    """Execute a batch of tool calls and return results.

    ``context`` is forwarded unchanged. The MCP control plane uses manifest
    policy to require and sign it only for tools that need run/node authority.
    """
    results = []
    for tc in tool_calls:
        func = tc.get("function", {})
        name = func.get("name", "")
        try:
            args = _json.loads(func.get("arguments", "{}"))
        except _json.JSONDecodeError:
            args = {}
        result = mcp.call_tool(name, args, context=context)
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
