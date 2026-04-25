"""Unit tests for ari.agent.react_driver.

These tests do not hit any live LLM or MCP server; the LLMClient and
MCPClient dependencies are stubbed so the ReAct loop logic itself can be
exercised deterministically.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ari.agent.react_driver import (
    _build_window,
    _make_final_tool_def,
    _validate_paths_in_args,
    run_react,
)
from ari.llm.client import LLMResponse


# ─── unit tests for helpers ──────────────────────────────────────────────


class TestValidatePaths:
    def test_clean_relative_paths_ok(self, tmp_path):
        assert _validate_paths_in_args(
            {"filename": "hello.c", "content": "int main(){}"}, tmp_path,
        ) is None

    def test_absolute_path_under_sandbox_ok(self, tmp_path):
        inside = str(tmp_path / "run.sh")
        assert _validate_paths_in_args({"path": inside}, tmp_path) is None

    def test_absolute_path_outside_sandbox_rejected(self, tmp_path):
        err = _validate_paths_in_args(
            {"path": "/etc/passwd"}, tmp_path,
        )
        assert err and "outside sandbox" in err

    def test_checkpoint_path_outside_sandbox_rejected(self, tmp_path):
        ckpt = tmp_path.parent / "checkpoint_root"
        ckpt.mkdir(exist_ok=True)
        (ckpt / "nodes_tree.json").write_text("{}")
        err = _validate_paths_in_args(
            {"command": f"cat {ckpt}/nodes_tree.json"}, tmp_path,
        )
        assert err and "outside sandbox" in err

    def test_allow_extra_paths(self, tmp_path):
        paper = tmp_path.parent / "paper.tex"
        paper.write_text("x")
        err = _validate_paths_in_args(
            {"paper_path": str(paper)}, tmp_path, allow_extra=[paper],
        )
        assert err is None

    def test_relative_dotslash_binary_ok(self, tmp_path):
        """`./bin` must not be misread as absolute `/bin` (regression)."""
        for cmd in ("./spmm_baseline", "bash -c './spmm_baseline'", "time ./spmm_baseline -n 100"):
            assert _validate_paths_in_args({"command": cmd}, tmp_path) is None, cmd

    def test_traversal_rejected(self, tmp_path):
        err = _validate_paths_in_args(
            {"path": "../secret"}, tmp_path,
        )
        assert err and "traversal" in err

    def test_no_sandbox_skips_check(self, tmp_path):
        assert _validate_paths_in_args(
            {"path": "/etc/passwd"}, None,
        ) is None


class TestBuildWindow:
    def test_short_conversations_preserved(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
        ]
        assert _build_window(msgs, max_msgs=50) == msgs

    def test_long_conversations_keep_head(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
        ] + [{"role": "assistant", "content": f"a{i}"} for i in range(60)]
        w = _build_window(msgs, max_msgs=20)
        assert len(w) == 20
        assert w[0]["role"] == "system"
        assert w[1]["role"] == "user"


class TestFinalToolDef:
    def test_required_value_field(self):
        d = _make_final_tool_def("report_metric")
        assert d["function"]["name"] == "report_metric"
        assert "value" in d["function"]["parameters"]["required"]


# ─── stubs for run_react integration ─────────────────────────────────────


class _FakeLLM:
    """Scripted LLM: consumes tool-call responses from a queue."""
    def __init__(self, scripted_calls: list[list[dict] | None]):
        self._calls = list(scripted_calls)
        self.invocations: list[list[dict]] = []

    def complete(self, messages, tools=None, require_tool=False, **kwargs):
        self.invocations.append(list(messages))
        if not self._calls:
            return LLMResponse(content="done", tool_calls=None)
        nxt = self._calls.pop(0)
        if nxt is None:
            return LLMResponse(content="done", tool_calls=None)
        return LLMResponse(content="", tool_calls=nxt)


class _FakeMCP:
    """Fake MCPClient exposing a fixed tool list and recording calls."""
    def __init__(self, tools: list[dict], results: dict[str, Any] | None = None):
        self._tools = list(tools)
        self._results = dict(results or {})
        self.calls: list[tuple[str, dict]] = []

    def list_tools(self, phase: str | None = None) -> list[dict]:
        return list(self._tools)

    def call_tool(self, tool_name: str, args: dict) -> dict:
        self.calls.append((tool_name, args))
        return self._results.get(tool_name, {"ok": True, "name": tool_name})


# ─── run_react integration ───────────────────────────────────────────────


def _tc(id_: str, name: str, args: dict) -> dict:
    return {
        "id": id_,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


class TestRunReact:
    def test_completes_when_final_tool_called(self, tmp_path):
        llm = _FakeLLM(scripted_calls=[
            [_tc("c1", "write_file", {"filename": "run.sh", "content": "echo 1"})],
            [_tc("c2", "report_metric", {"value": 42.0, "unit": "MFLOPS"})],
        ])
        mcp = _FakeMCP(
            tools=[{
                "name": "write_file", "description": "write",
                "inputSchema": {"type": "object", "properties": {}},
            }],
        )
        out = run_react(
            llm, mcp,
            system_prompt="sys", user_prompt="usr",
            agent_phase="reproduce", final_tool="report_metric",
            max_steps=10, sandbox=tmp_path, log_dir=tmp_path,
        )
        assert out["status"] == "completed"
        assert out["final_args"] == {"value": 42.0, "unit": "MFLOPS"}
        assert ("write_file", {"filename": "run.sh", "content": "echo 1"}) in mcp.calls
        # final_tool never dispatched to MCP
        assert all(name != "report_metric" for name, _ in mcp.calls)

    def test_sandbox_violation_blocks_dispatch(self, tmp_path):
        """A tool call referencing /etc/passwd must NOT reach the MCP server."""
        llm = _FakeLLM(scripted_calls=[
            [_tc("c1", "read_file", {"path": "/etc/passwd"})],
            [_tc("c2", "report_metric", {"value": 0.0})],
        ])
        mcp = _FakeMCP(
            tools=[{
                "name": "read_file", "description": "read",
                "inputSchema": {"type": "object", "properties": {}},
            }],
        )
        out = run_react(
            llm, mcp,
            system_prompt="sys", user_prompt="usr",
            agent_phase="reproduce", final_tool="report_metric",
            max_steps=5, sandbox=tmp_path, log_dir=tmp_path,
        )
        assert out["status"] == "completed"
        # The rejected tool call never reached the MCP server.
        assert all(name != "read_file" for name, _ in mcp.calls)
        # The violation is reported back to the agent as a tool message.
        tool_msgs = [m for m in out["messages"] if m.get("role") == "tool"]
        rejections = [m for m in tool_msgs if "sandbox violation" in m.get("content", "")]
        assert rejections, "sandbox violation must surface as a tool reply"

    def test_max_steps_when_final_never_called(self, tmp_path):
        # LLM keeps writing files but never calls final_tool.
        script = [
            [_tc(f"c{i}", "write_file", {"filename": f"f{i}.txt", "content": "x"})]
            for i in range(10)
        ]
        llm = _FakeLLM(scripted_calls=script)
        mcp = _FakeMCP(
            tools=[{
                "name": "write_file", "description": "w",
                "inputSchema": {"type": "object", "properties": {}},
            }],
        )
        out = run_react(
            llm, mcp,
            system_prompt="sys", user_prompt="usr",
            agent_phase="reproduce", final_tool="report_metric",
            max_steps=3, sandbox=tmp_path, log_dir=tmp_path,
        )
        assert out["status"] == "max_steps"
        assert out["final_args"] is None

    def test_log_file_persisted(self, tmp_path):
        llm = _FakeLLM(scripted_calls=[
            [_tc("c1", "report_metric", {"value": 1.0})],
        ])
        mcp = _FakeMCP(tools=[])
        run_react(
            llm, mcp,
            system_prompt="sys", user_prompt="usr",
            agent_phase="reproduce", final_tool="report_metric",
            max_steps=2, sandbox=tmp_path, log_dir=tmp_path,
        )
        log_file = tmp_path / "react_log.json"
        assert log_file.exists()
        data = json.loads(log_file.read_text())
        assert isinstance(data, list) and len(data) >= 2
