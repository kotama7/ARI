"""Tool dispatch pins filesystem tools to the node's work_dir (handoff study).

Regression guard for the BFTS bug where a tool call that OMITS ``work_dir`` falls
back to the shared ``/tmp/ari_work`` default (the MCP coding server snapshots
ARI_WORK_DIR at fork time, so per-node updates never reach it). The result was
that the agent's edits landed in a shared scratch dir the evaluator never reads,
so nodes were silently scored on their inherited (parent) code.
"""
import json

from ari.agent.tool_manager import execute_tool_calls, _WORKDIR_TOOLS


class _FakeMCP:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, args, context=None, **_kw):
        # Mirrors MCPClient.call_tool: per-node authority now travels in
        # ``context`` (the earlier ``cow_node_id`` routing is gone).
        self.calls.append((name, dict(args), context))
        return {"result": "{}"}


def _tc(name, args):
    return {"id": "tc1", "function": {"name": name, "arguments": json.dumps(args)}}


def test_workdir_injected_for_fs_tool_when_omitted():
    mcp = _FakeMCP()
    execute_tool_calls(mcp, [_tc("write_code", {"filename": "c.c", "code": "x"})],
                       node_id="n1", work_dir="/exp/run/n1")
    name, args, _cow = mcp.calls[0]
    assert name == "write_code" and args["work_dir"] == "/exp/run/n1"


def test_all_fs_tools_get_pinned():
    for tool in _WORKDIR_TOOLS:
        mcp = _FakeMCP()
        execute_tool_calls(mcp, [_tc(tool, {})], work_dir="/exp/run/n1")
        assert mcp.calls[0][1]["work_dir"] == "/exp/run/n1", tool


def test_explicit_workdir_is_overridden_to_node_root():
    # Container model: each node's real work_dir is authoritative and is what the
    # agent sees mounted at /workspace. An agent-supplied work_dir (e.g. the
    # virtual "/workspace", or any stray path) must be REPLACED by this node's
    # real dir — the coding server cannot map "/workspace" back to THIS node
    # (its ARI_WORK_DIR is fork-time), so the loop pins the real path here.
    mcp = _FakeMCP()
    execute_tool_calls(mcp, [_tc("run_bash", {"command": "ls", "work_dir": "/workspace"})],
                       work_dir="/exp/run/n1")
    assert mcp.calls[0][1]["work_dir"] == "/exp/run/n1"


def test_non_fs_tool_not_injected_and_context_is_forwarded():
    # Pinning is scoped to the filesystem tools: a memory tool has no work_dir
    # argument, and inventing one would be a wrong call, not a safer one.
    # The per-node authority it does need rides in ``context``.
    mcp = _FakeMCP()
    sentinel = object()
    execute_tool_calls(mcp, [_tc("add_memory", {"text": "t"})], sentinel,
                       node_id="n1", work_dir="/exp/run/n1")
    name, args, context = mcp.calls[0]
    assert "work_dir" not in args
    assert context is sentinel


def test_no_workdir_means_no_injection():
    # When no node work_dir is threaded (non-BFTS contexts), behaviour is unchanged.
    mcp = _FakeMCP()
    execute_tool_calls(mcp, [_tc("write_code", {"filename": "c.c", "code": "x"})])
    assert "work_dir" not in mcp.calls[0][1]
