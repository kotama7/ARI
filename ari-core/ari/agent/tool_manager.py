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
import time as _time
from typing import Any

from ari.agent.message_utils import _tool_was_called
from ari.agent.workflow import WorkflowHints


# MCP tools that the parent (ari-core) drives itself and must never be
# exposed to the LLM — otherwise the model could set an arbitrary node
# id and bypass the memory skill's CoW check.
_INTERNAL_MCP_TOOLS = frozenset({"_set_current_node"})

# Coding-skill filesystem tools that take a ``work_dir`` argument and, when the
# model omits it, fall back to a SHARED default (``ARI_WORK_DIR`` snapshotted at
# MCP fork time, else ``/tmp/ari_work``). In a multi-node BFTS run that default
# is NOT the node's per-node work_dir, so an omitted ``work_dir`` silently routes
# the agent's edits to a shared scratch dir that the evaluator never reads — the
# node is then scored on its inherited (parent) code. We pin these calls to the
# current node's work_dir whenever the model leaves it unset.
_WORKDIR_TOOLS = frozenset({"write_code", "run_code", "run_bash", "emit_results", "read_file"})


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
    node_id: str | None = None,
    work_dir: str | None = None,
) -> list[dict]:
    """Execute a batch of tool calls and return results.

    When *node_id* is provided and the call targets a CoW-guarded
    memory tool, ``cow_node_id`` is forwarded to ``mcp.call_tool`` so
    the ``(_set_current_node, write)`` pair is locked atomically —
    prevents the env-var race when ``max_parallel_nodes > 1``.

    When *work_dir* is provided, filesystem tools (:data:`_WORKDIR_TOOLS`)
    that the model called WITHOUT a ``work_dir`` argument are pinned to it,
    so per-node edits land in the node's evaluated dir instead of the shared
    ``/tmp/ari_work`` fallback (which the evaluator never reads).
    """
    results = []
    for tc in tool_calls:
        func = tc.get("function", {})
        name = func.get("name", "")
        try:
            args = _json.loads(func.get("arguments", "{}"))
        except _json.JSONDecodeError:
            args = {}
        if work_dir and name in _WORKDIR_TOOLS:
            # The node's real work_dir is authoritative and is mounted at the
            # virtual container root (``/workspace``) that the agent sees. Always
            # pin it — whether the model omitted work_dir (would route to the
            # shared fork-time fallback the evaluator never reads) OR passed the
            # virtual "/workspace" (the coding server cannot map that back to THIS
            # node, since its ARI_WORK_DIR is snapshotted at MCP fork time). Any
            # sub-path the model wanted goes in the filename/path/command args,
            # which the coding server devirtualizes against this same work_dir.
            args["work_dir"] = work_dir
        if name in _EXEC_TOOLS:
            _left = exec_budget_remaining(node_id)
            if _left <= 0:
                results.append({
                    "tool_call_id": tc.get("id", ""), "name": name,
                    "result": {
                        "status": "error",
                        "error": (
                            f"this node has used its whole command-execution "
                            f"budget of {exec_budget_seconds():.0f}s. Stop running "
                            f"commands and return your result with what you have."
                        ),
                    },
                })
                continue
            # Never let one call outlast what is left, so the cap cannot be
            # overshot by a single long command.
            if _left != float("inf"):
                try:
                    _req = float(args.get("timeout") or 0)
                except (TypeError, ValueError):
                    _req = 0.0
                if _req <= 0 or _req > _left:
                    args["timeout"] = int(max(1, _left))
        _t0 = _time.monotonic()
        if node_id and name in mcp._COW_TOOLS:
            result = mcp.call_tool(name, args, cow_node_id=node_id)
        else:
            result = mcp.call_tool(name, args)
        if name in _EXEC_TOOLS and node_id:
            _exec_spent[str(node_id)] = (
                _exec_spent.get(str(node_id), 0.0) + (_time.monotonic() - _t0))
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
