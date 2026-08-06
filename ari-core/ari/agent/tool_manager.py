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


# Coding-skill filesystem tools that take a ``work_dir`` argument and, when the
# model omits it, fall back to a SHARED default (``ARI_WORK_DIR`` snapshotted at
# MCP fork time, else ``/tmp/ari_work``). In a multi-node BFTS run that default
# is NOT the node's per-node work_dir, so an omitted ``work_dir`` silently routes
# the agent's edits to a shared scratch dir that the evaluator never reads — the
# node is then scored on its inherited (parent) code. We pin these calls to the
# current node's work_dir whenever the model leaves it unset.
#
# ari-skill-coding/src/server.py documents this pinning as the invariant it
# relies on, so the two must not drift apart.
_WORKDIR_TOOLS = frozenset({"write_code", "run_code", "run_bash", "emit_results",
                            "read_file", "edit_code"})


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


# ── Per-node compute budget for SCHEDULER work ─────────────────────────────
# exec_budget above charges run_bash/run_code, which is time on ONE machine.
# It never saw a scheduler job, so a node could spend half an hour of local
# shell and be refused, while submitting a thousand-node job for two hours
# cost it nothing. That is the wrong way round: the second consumes orders of
# magnitude more of the resource the site is actually rationing.
#
# The unit is NODE-SECONDS (nodes x walltime), the unit a scheduler allocates
# in. Charged at SUBMISSION against the RESERVATION rather than on completion
# against the actual elapsed time, for two reasons: a budget that only learns
# the cost afterwards cannot refuse anything, and a scheduler holds the whole
# reservation regardless of when the job's own work finishes.
_SCHEDULER_SUBMIT_TOOLS = frozenset({
    "slurm_submit", "job_submit", "container_submit",
})
_compute_spent: dict[str, float] = {}


def compute_budget_node_seconds() -> float:
    """Per-node scheduler budget in node-seconds, 0 to disable (the default).

    Off unless a site sets it: a bound on how much of a cluster one search
    node may reserve is a policy, and inventing a default would silently cap
    existing runs.
    """
    import os as _os

    try:
        return float(_os.environ.get("ARI_NODE_COMPUTE_BUDGET_NS", "0") or 0)
    except ValueError:
        return 0.0


def reset_compute_budget(node_id: str | None) -> None:
    if node_id:
        _compute_spent.pop(str(node_id), None)


def compute_budget_remaining(node_id: str | None) -> float:
    """Node-seconds this node may still reserve (inf when off)."""
    budget = compute_budget_node_seconds()
    if budget <= 0 or not node_id:
        return float("inf")
    return max(0.0, budget - _compute_spent.get(str(node_id), 0.0))


def parse_walltime_seconds(value: object) -> float:
    """SLURM walltime -> seconds. Unparseable input reads as 0, not as free.

    Accepts the forms sbatch does: ``mm``, ``mm:ss``, ``hh:mm:ss``,
    ``d-hh``, ``d-hh:mm``, ``d-hh:mm:ss``.
    """
    text = str(value or "").strip()
    if not text:
        return 0.0
    days = 0
    if "-" in text:
        head, _, text = text.partition("-")
        if not head.isdigit():
            return 0.0
        days = int(head)
    parts = text.split(":") if text else ["0"]
    if not all(p.isdigit() for p in parts) or len(parts) > 3:
        return 0.0
    if len(parts) == 1:
        # Bare number is MINUTES for sbatch, unless a day part preceded it,
        # where it is hours.
        unit = 3600 if days else 60
        return days * 86400 + int(parts[0]) * unit
    if len(parts) == 2:
        hours, minutes = (parts if days else ("0", parts[0]))
        seconds = "0" if days else parts[1]
        return days * 86400 + int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    return (days * 86400 + int(parts[0]) * 3600
            + int(parts[1]) * 60 + int(parts[2]))


def _record_reservation(tool: str, node_id: str | None, node_seconds: float) -> None:
    """Put the reservation in the run's cost trace.

    Enforcement alone leaves no record: a run would be refused work without
    anything saying what it had already reserved, and a run under no budget
    would show nothing at all. Recorded even when the budget is off, because
    "how much cluster did this search use" is a question worth answering
    whether or not anyone capped it.

    ``resource_measurement_basis`` says declared-reservation, not measured:
    this is what the job asked the scheduler to hold, which is what the site
    charges, and it is deliberately not passed off as elapsed time.

    Never raises. A cost trace that cannot be written must not stop the run.
    """
    if node_seconds <= 0:
        return
    try:
        from ari import cost_tracker as _ct

        tracker = getattr(_ct, "_tracker", None)
        if tracker is None:
            return
        tracker.record(
            model="", prompt_tokens=0, completion_tokens=0,
            node_id=str(node_id or ""), phase="bfts", skill="hpc-skill",
            component="scheduler", op=tool, cost_usd=0.0,
            wall_time_ms=node_seconds * 1000.0,
            cpu_core_seconds=None,
            resource_measurement_basis="declared-reservation",
            execution_status="reserved",
        )
    except Exception:
        return


def reserved_node_seconds(args: dict) -> float:
    """What a submission would reserve, from the tool's own arguments.

    Reads both shapes: the flat bridge arguments and the typed request's
    nested ``resources``. An argument set neither shape recognises reserves
    nothing, which is the honest reading — this cannot invent a cost it has
    no basis for, and the unpriced case is visible in the record instead.
    """
    payload = args if isinstance(args, dict) else {}
    request = payload.get("request")
    if isinstance(request, dict):
        payload = request.get("resources") or {}
    if not isinstance(payload, dict):
        return 0.0
    try:
        nodes = int(payload.get("nodes") or 1)
    except (TypeError, ValueError):
        nodes = 1
    return max(0, nodes) * parse_walltime_seconds(payload.get("walltime"))



def execute_tool_calls(
    mcp: Any,
    tool_calls: list[dict],
    context: ToolCallContextV1 | None = None,
    *,
    node_id: str | None = None,
    work_dir: str | None = None,
) -> list[dict]:
    """Execute a batch of tool calls and return results.

    ``context`` is forwarded unchanged. The MCP control plane uses manifest
    policy to require and sign it only for tools that need run/node authority.

    When *work_dir* is given, filesystem tools (:data:`_WORKDIR_TOOLS`) are
    pinned to it — see that constant for why this cannot be left to the model
    or to the environment. ``context`` does not carry a work_dir, so this is a
    separate concern from the call-authority it does carry.

    When *node_id* is given, run_bash/run_code additionally draw down that
    node's wall-clock budget (:func:`exec_budget_remaining`).
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
            # Always pin, whether the model omitted work_dir (it would route to
            # the shared fork-time fallback the evaluator never reads) OR passed
            # the virtual "/workspace" (the coding server cannot map that back to
            # THIS node, its ARI_WORK_DIR being snapshotted at MCP fork time).
            # Any sub-path the model wanted rides in the filename/path/command
            # args, which the server devirtualizes against this same work_dir.
            args["work_dir"] = work_dir
        if name in _SCHEDULER_SUBMIT_TOOLS:
            _left_ns = compute_budget_remaining(node_id)
            _want_ns = reserved_node_seconds(args)
            if _want_ns > _left_ns:
                # Refused BEFORE submission: once the job is queued the
                # reservation is held whatever we do here, and cancelling it
                # afterwards would still have taken the slot.
                results.append({
                    "tool_call_id": tc.get("id", ""), "name": name,
                    "result": {
                        "status": "error",
                        "error": (
                            f"this submission reserves {_want_ns / 3600:.1f} "
                            f"node-hours but only {_left_ns / 3600:.1f} remain "
                            f"of this node's compute budget "
                            f"({compute_budget_node_seconds() / 3600:.1f} "
                            f"node-hours). Ask for fewer nodes or a shorter "
                            f"walltime, or finish with what you have."
                        ),
                    },
                })
                continue
            if _want_ns and node_id and _left_ns != float("inf"):
                _compute_spent[str(node_id)] = (
                    _compute_spent.get(str(node_id), 0.0) + _want_ns)
            _record_reservation(name, node_id, _want_ns)
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
        result = mcp.call_tool(name, args, context=context)
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
