"""Smoke tests for the agent layer (Phase 0 of REFACTORING.md).

Goal: provide minimal regression coverage for ``ari.agent.{loop,react_driver,workflow}``
before any structural splits.  These tests intentionally use mocked LLM/MCP
clients so they remain deterministic and fast.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from ari.agent.loop import (
    AgentLoop,
    SYSTEM_PROMPT,
    _extract_job_ids,
    _tool_was_called,
)
from ari.agent.react_driver import run_react
from ari.agent.workflow import (
    WorkflowHints,
    enrich_hints_from_mcp,
    from_experiment_text,
)
from ari.llm.client import LLMResponse
from ari.orchestrator.node import Node, NodeLabel, NodeStatus


# ─── stubs ──────────────────────────────────────────────────────────────


class _FakeLLM:
    """Scripted LLM driven by a queue of tool-call lists.

    Each ``complete()`` invocation pops the next entry; ``None`` means
    "respond with plain text and no tool calls" (i.e. terminate the loop).
    """

    def __init__(self, scripted: list[list[dict] | None]):
        self._scripted = list(scripted)
        self.invocations: list[list[dict]] = []

    def complete(self, messages, tools=None, require_tool=False, **kwargs):
        self.invocations.append(list(messages))
        if not self._scripted:
            return LLMResponse(content="done", tool_calls=None)
        nxt = self._scripted.pop(0)
        if nxt is None:
            return LLMResponse(content="done", tool_calls=None)
        return LLMResponse(content="", tool_calls=nxt)


class _FakeMCP:
    """Fake MCP client recording tool dispatch and returning canned results."""

    _COW_TOOLS: frozenset = frozenset({"add_memory", "clear_node_memory"})

    def __init__(self, tools: list[dict], results: dict[str, Any] | None = None):
        self._tools = list(tools)
        self._results = dict(results or {})
        self.calls: list[tuple[str, dict]] = []

    def list_tools(self, phase: str | None = None) -> list[dict]:
        return list(self._tools)

    def call_tool(self, tool_name: str, args: dict, **kwargs) -> dict:
        self.calls.append((tool_name, args))
        return self._results.get(tool_name, {"ok": True, "name": tool_name})


def _tc(id_: str, name: str, args: dict) -> dict:
    return {
        "id": id_,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


# ─── Test 1: AgentLoop helpers (single-node roundtrip surface) ──────────


class TestAgentLoopSingleNodeRoundtrip:
    """Exercise the helper surface that ``AgentLoop.run()`` relies on.

    These are the functions PR-3D will move into ``message_utils.py`` /
    ``tool_manager.py`` / ``guidance.py`` — locking their behaviour now
    creates a regression net for the split.
    """

    def test_extract_job_ids_from_sbatch_stdout(self):
        msgs = [
            {"role": "tool", "content": "Submitted batch job 12345"},
            {"role": "tool", "content": "Submitted batch job 67890\nfollow up"},
        ]
        assert _extract_job_ids(msgs, job_id_key="job_id") == ["12345", "67890"]

    def test_extract_job_ids_from_json(self):
        msgs = [
            {"role": "tool", "content": json.dumps({"job_id": "777"})},
            # Nested ``result`` field as produced by some MCP wrappers.
            {"role": "tool", "content": json.dumps({"result": json.dumps({"job_id": "888"})})},
        ]
        assert _extract_job_ids(msgs, job_id_key="job_id") == ["777", "888"]

    def test_tool_was_called_detects_assistant_invocations(self):
        msgs = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "survey"}}]},
            {"role": "tool", "content": "ok"},
        ]
        assert _tool_was_called(msgs, "survey") is True
        assert _tool_was_called(msgs, "slurm_submit") is False

    def test_active_tools_returns_none_when_no_sequence(self):
        loop = AgentLoop.__new__(AgentLoop)  # bypass __init__ side effects
        loop.hints = WorkflowHints()
        loop.mcp = _FakeMCP(tools=[])
        all_tools = [
            {"type": "function", "function": {"name": "survey"}},
            {"type": "function", "function": {"name": "run_bash"}},
        ]
        assert loop._active_tools(all_tools, [], [], False, False) is None

    def test_guidance_after_survey_uses_post_survey_hint(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.hints = WorkflowHints(post_survey_hint="step 1\nstep 2")
        out = loop._guidance(
            last_tool="survey", job_ids=[], tool_outputs=[], messages=[],
        )
        assert out is not None and "step 1" in out


# ─── Test 2: react_driver tool dispatch ─────────────────────────────────


class TestReactDriverToolInvocation:
    def test_run_react_dispatches_then_completes_on_final_tool(self, tmp_path):
        llm = _FakeLLM(scripted=[
            [_tc("c1", "write_file", {"filename": "run.sh", "content": "echo 1"})],
            [_tc("c2", "report_metric", {"value": 3.14})],
        ])
        mcp = _FakeMCP(
            tools=[{
                "name": "write_file",
                "description": "write",
                "inputSchema": {"type": "object", "properties": {}},
            }],
        )
        out = run_react(
            llm, mcp,
            system_prompt="sys",
            user_prompt="usr",
            agent_phase="reproduce",
            final_tool="report_metric",
            max_steps=10,
            sandbox=tmp_path,
            log_dir=tmp_path,
        )
        assert out["status"] == "completed"
        assert out["final_args"] == {"value": 3.14}
        # write_file was dispatched once; the final tool itself never reaches MCP.
        assert ("write_file", {"filename": "run.sh", "content": "echo 1"}) in mcp.calls
        assert all(name != "report_metric" for name, _ in mcp.calls)


# ─── Test 3: WorkflowHints phase transitions ────────────────────────────


class TestWorkflowPhaseTransitions:
    def test_from_experiment_text_detects_slurm_keywords(self):
        text = (
            "# Goal\n"
            "Reproduce X using slurm_submit.\n"
            "Partition: gpu\n"
            "Max CPUs: 16\n"
        )
        hints = from_experiment_text(text, hpc_enabled=True)
        # When the markdown mentions slurm, job submitter/poller wires up.
        assert hints.job_submitter_tool == "slurm_submit"
        assert hints.job_poller_tool == "job_status"
        assert hints.slurm_partition == "gpu"
        assert hints.slurm_max_cpus == 16

    def test_from_experiment_text_disabled_hpc_clears_slurm(self):
        text = "# Goal\nuse slurm_submit\nPartition: gpu\n"
        hints = from_experiment_text(text, hpc_enabled=False)
        assert hints.job_submitter_tool is None
        assert hints.slurm_partition == ""
        # Laptop tool sequence excludes slurm/job_status entries.
        assert "slurm_submit" not in hints.tool_sequence
        assert "job_status" not in hints.tool_sequence

    def test_enrich_hints_from_mcp_orders_tool_sequence(self):
        hints = WorkflowHints()
        mcp_tools = [
            {"name": "slurm_submit", "description": "submit a slurm job"},
            {"name": "job_status", "description": "poll a slurm job"},
            {"name": "run_bash", "description": "run a shell command"},
            {"name": "make_metric_spec", "description": "decide metrics"},
            {"name": "survey", "description": "literature survey"},
        ]
        enrich_hints_from_mcp(hints, mcp_tools, hpc_enabled=True)
        # tool_sequence respects the preferred ordering for the documented core.
        assert hints.tool_sequence[:5] == [
            "make_metric_spec", "survey", "run_bash", "slurm_submit", "job_status",
        ]
        # post_survey_hint becomes a non-empty workflow recipe.
        assert hints.post_survey_hint and "experiment" in hints.post_survey_hint.lower()

    def test_enrich_hints_disabled_hpc_strips_slurm_tools(self):
        hints = WorkflowHints(
            job_submitter_tool="slurm_submit",
            job_poller_tool="job_status",
            slurm_partition="gpu",
            slurm_max_cpus=16,
        )
        mcp_tools = [
            {"name": "slurm_submit", "description": "submit a slurm job"},
            {"name": "run_bash", "description": "run a shell command"},
        ]
        enrich_hints_from_mcp(hints, mcp_tools, hpc_enabled=False)
        assert hints.job_submitter_tool is None
        assert hints.slurm_partition == ""
        assert "slurm_submit" not in hints.tool_sequence

    def test_workflow_hints_default_is_inert(self):
        h = WorkflowHints()
        assert h.tool_sequence == []
        assert h.job_submitter_tool is None
        assert h.expected_metrics == []


# ─── Sanity: the SYSTEM_PROMPT is still present (PC3 will externalise) ──


def test_system_prompt_template_variables_intact():
    """Lock the template variables that PC3 must preserve byte-for-byte."""
    assert "{tool_desc}" in SYSTEM_PROMPT
    assert "{memory_rules}" in SYSTEM_PROMPT
    assert "{extra}" in SYSTEM_PROMPT
