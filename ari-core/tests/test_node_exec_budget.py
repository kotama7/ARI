"""A node must not be able to spend its whole life inside run_bash.

Each call had its own timeout but nothing bounded the SUM, so one node could
consume the entire per-node watchdog on shell calls and then be killed with no
score, no self-report and no signal about why. That is the worst outcome
available: the node costs a slot and teaches nothing. The budget makes the node
run out of COMMANDS while it still has turns left to report what it found.
"""
import pytest

from ari.agent import tool_manager as tm


class _FakeMCP:
    _COW_TOOLS: set = set()

    def __init__(self, spend=0.0):
        self.calls = []
        self._spend = spend

    def call_tool(self, name, args, **kw):
        import time
        self.calls.append((name, dict(args)))
        if self._spend:
            time.sleep(self._spend)
        return {"status": "ok"}


def _call(name, **args):
    import json
    return {"id": "c1", "function": {"name": name, "arguments": json.dumps(args)}}


def test_budget_is_per_node_and_resets(monkeypatch):
    monkeypatch.setenv("ARI_NODE_EXEC_BUDGET_S", "100")
    tm.reset_exec_budget("nodeA")
    assert tm.exec_budget_remaining("nodeA") == 100
    tm._exec_spent["nodeA"] = 60.0
    assert tm.exec_budget_remaining("nodeA") == 40
    assert tm.exec_budget_remaining("nodeB") == 100, "budgets must not be shared"
    tm.reset_exec_budget("nodeA")
    assert tm.exec_budget_remaining("nodeA") == 100


def test_zero_disables_the_cap(monkeypatch):
    monkeypatch.setenv("ARI_NODE_EXEC_BUDGET_S", "0")
    assert tm.exec_budget_remaining("n") == float("inf")


def test_exhausted_budget_refuses_the_call_and_says_what_to_do(monkeypatch):
    monkeypatch.setenv("ARI_NODE_EXEC_BUDGET_S", "100")
    tm.reset_exec_budget("n1")
    tm._exec_spent["n1"] = 100.0
    mcp = _FakeMCP()
    out = tm.execute_tool_calls(mcp, [_call("run_bash", command="make")], node_id="n1")
    assert mcp.calls == [], "the command ran despite an exhausted budget"
    assert out[0]["result"]["status"] == "error"
    assert "return your result" in out[0]["result"]["error"], (
        "the refusal must tell the agent what to do instead, or it will retry")


def test_a_single_call_cannot_overshoot_what_is_left(monkeypatch):
    monkeypatch.setenv("ARI_NODE_EXEC_BUDGET_S", "100")
    tm.reset_exec_budget("n2")
    tm._exec_spent["n2"] = 90.0
    mcp = _FakeMCP()
    tm.execute_tool_calls(
        mcp, [_call("run_bash", command="sleep 600", timeout=600)], node_id="n2")
    assert mcp.calls[0][1]["timeout"] <= 10


def test_non_exec_tools_are_untouched(monkeypatch):
    monkeypatch.setenv("ARI_NODE_EXEC_BUDGET_S", "100")
    tm.reset_exec_budget("n3")
    tm._exec_spent["n3"] = 100.0
    mcp = _FakeMCP()
    out = tm.execute_tool_calls(mcp, [_call("read_file", filename="a.c")], node_id="n3")
    assert mcp.calls and out[0]["result"] == {"status": "ok"}, (
        "reading a file is not command execution and must not be refused")
