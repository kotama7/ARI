"""Step-guidance + metrics-validation helpers for AgentLoop (Phase 3D).

Both functions used to live as methods on :class:`ari.agent.loop.AgentLoop`;
they only read state via the injected :class:`WorkflowHints`, so they
move out as pure functions and the methods become 1-line delegators.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

from ari.agent.workflow import WorkflowHints
from ari.orchestrator.node import Node


logger = logging.getLogger(__name__)


def guidance(
    hints: WorkflowHints,
    last_tool: str,
    job_ids: list[str],
    tool_outputs: list[str],
    messages: list[dict] | None = None,
) -> str | None:
    """Return additional instructions to the LLM after a tool dispatch.

    See :class:`ari.agent.loop.AgentLoop._guidance` for the original
    behaviour; this function is the canonical implementation now.
    """
    h = hints

    # Generic: detect tool error in the most recent tool message
    for _msg in reversed(messages or []):
        if _msg.get("role") == "tool":
            _tc = _msg.get("content", "")
            try:
                _parsed = _json.loads(_tc) if isinstance(_tc, str) and _tc.startswith("{") else {}
                if isinstance(_parsed, dict) and "error" in _parsed:
                    return (
                        f"The previous tool call ({last_tool}) returned an error:\n"
                        f"  {_parsed['error']}\n"
                        "Read the error carefully. Diagnose the root cause and try a different approach. "
                        "Do NOT retry the exact same call."
                    )
            except Exception:
                pass
            break

    # after survey completes
    if last_tool == "survey" and not job_ids:
        if h.post_survey_hint:
            return f"Good. Now proceed:\n{h.post_survey_hint}"
        return "Good. Now execute the experiment using available tools."

    # after async job submitted
    if h.job_submitter_tool and last_tool == h.job_submitter_tool and job_ids:
        jid = job_ids[-1]
        poller = h.job_poller_tool or "job_status"
        return (
            f"Job {jid} submitted. "
            f"The system will automatically poll {poller}() every 30 seconds until the job completes. "
            f"Do NOT call {poller}() manually — it wastes steps. "
            f"Instead, call {poller}(job_id='{jid}') ONCE and the framework will handle polling."
        )

    # after job status checked
    if h.job_poller_tool and last_tool == h.job_poller_tool and job_ids:
        jid = job_ids[-1]
        reader = h.job_reader_tool or "run_bash"
        if h.output_file_pattern:
            path = h.output_file_pattern.format(job_id=jid)
            return f"Good. Now read results:\n{reader}(command='cat {path}')"
        return (
            f"Good. Job completed. Use {reader}() to read the job output. "
            f"Check the output path specified in your job script. "
            f"Do NOT call {h.job_poller_tool}() again — the job is already done."
        )

    # after execution result read
    if h.job_reader_tool and last_tool in (h.job_reader_tool, "run_bash", "run_code"):
        summary = "\n".join(tool_outputs[-5:])
        return (
            f"Execution output:\n{summary}\n\n"
            "Now return the final JSON with REAL measured values.\n"
            'Format: {"status":"success","artifacts":[...],"summary":"..."}\n'
            "Use ONLY values from actual tool outputs."
        )

    return None


def validate_metrics(
    hints: WorkflowHints,
    result_str: str,
    job_ids: list[str],
    node: Node,
) -> bool:
    """Validate metrics, mark *node* failed if problematic.

    Returns ``True`` when the metric set is suspicious (hallucinated or
    below threshold) so the agent loop can short-circuit; ``False``
    otherwise.  See :class:`ari.agent.loop.AgentLoop._validate_metrics`
    for the original method.
    """
    h = hints
    if h.metric_extractor is None and h.min_expected_metric == 0:
        return False

    vals: list[float] = []
    if h.metric_extractor:
        try:
            vals = h.metric_extractor(result_str)
        except Exception:
            pass

    if not vals:
        return False

    # values appeared without going through a job → hallucination
    if h.job_submitter_tool and not job_ids:
        logger.warning("Node %s: metrics without async job → hallucination", node.id)
        return True  # treat as fabricated value

    # threshold check
    if h.min_expected_metric > 0 and len(vals) > 1 and max(vals) < h.min_expected_metric:
        logger.warning("Node %s: metric too low %s < %s → failed",
                       node.id, vals, h.min_expected_metric)
        node.mark_failed(
            error_log=f"Metric too low: max={max(vals)} < expected={h.min_expected_metric}"
        )
        return True  # marked node as failed

    return False
