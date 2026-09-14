"""A search node's scheduler reservations are budgeted, in node-seconds.

`exec_budget` charges run_bash/run_code — time on ONE machine. It never saw a
scheduler job, so a node could be refused after half an hour of local shell
while a thousand-node two-hour submission cost it nothing. That is backwards:
the second consumes orders of magnitude more of what a site rations.
"""
import json

import pytest

from ari.agent import tool_manager as tm


class _FakeMCP:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, args, context=None, **_kw):
        self.calls.append((name, dict(args)))
        return {"job_id": "1", "status": "submitted"}


def _tc(name, args):
    return {"id": "t", "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.mark.parametrize(
    "spec,seconds",
    [
        ("30", 1800),          # bare number is MINUTES for sbatch
        ("10:00", 600),        # mm:ss
        ("01:30:00", 5400),    # hh:mm:ss
        ("2-00", 172800),      # d-hh
        ("1-12:00", 129600),   # d-hh:mm
    ],
)
def test_walltime_forms(spec, seconds):
    assert tm.parse_walltime_seconds(spec) == seconds


@pytest.mark.parametrize("spec", ["", "bad", "1:2:3:4", "-5", None])
def test_unparseable_walltime_reserves_nothing(spec):
    """Unreadable input must read as zero, never as unlimited.

    Charging nothing leaves the submission visible as unpriced; treating it as
    free-because-unknown would let any malformed walltime bypass the budget.
    """
    assert tm.parse_walltime_seconds(spec) == 0.0


def test_reservation_is_read_from_both_argument_shapes():
    flat = tm.reserved_node_seconds({"nodes": 4, "walltime": "02:00:00"})
    typed = tm.reserved_node_seconds(
        {"request": {"resources": {"nodes": 2, "walltime": "01:00:00"}}})
    assert flat == 4 * 2 * 3600
    assert typed == 2 * 3600
    # A shape neither form recognises reserves nothing rather than a guess.
    assert tm.reserved_node_seconds({"foo": 1}) == 0.0


def test_the_budget_is_off_by_default(monkeypatch):
    # A cap on how much cluster one search node may reserve is site policy;
    # a default would silently change every existing run.
    monkeypatch.delenv("ARI_NODE_COMPUTE_BUDGET_NS", raising=False)
    tm.reset_compute_budget("n")
    mcp = _FakeMCP()
    tm.execute_tool_calls(
        mcp, [_tc("slurm_submit", {"nodes": 9999, "walltime": "2-00"})],
        node_id="n")
    assert mcp.calls, "an unset budget must not refuse anything"


def test_reservations_accumulate_and_then_refuse(monkeypatch):
    monkeypatch.setenv("ARI_NODE_COMPUTE_BUDGET_NS", str(10 * 3600))
    tm.reset_compute_budget("n1")
    mcp = _FakeMCP()

    tm.execute_tool_calls(
        mcp, [_tc("slurm_submit", {"nodes": 2, "walltime": "02:00:00"})],
        node_id="n1")
    tm.execute_tool_calls(
        mcp, [_tc("slurm_submit", {"nodes": 3, "walltime": "02:00:00"})],
        node_id="n1")
    assert len(mcp.calls) == 2
    assert tm.compute_budget_remaining("n1") == 0

    out = tm.execute_tool_calls(
        mcp, [_tc("slurm_submit", {"nodes": 1, "walltime": "01:00:00"})],
        node_id="n1")
    # Refused BEFORE the scheduler sees it: once queued the reservation is
    # held whatever happens next, so a later cancel would not give it back.
    assert len(mcp.calls) == 2, "the refused call must not reach MCP"
    assert "node-hours" in out[0]["result"]["error"]


def test_the_typed_and_container_paths_are_budgeted_too(monkeypatch):
    # Otherwise the bridge is policed and the typed path is a way around it.
    monkeypatch.setenv("ARI_NODE_COMPUTE_BUDGET_NS", "3600")
    for tool in ("job_submit", "container_submit"):
        tm.reset_compute_budget("n")
        mcp = _FakeMCP()
        tm.execute_tool_calls(
            mcp,
            [_tc(tool, {"request": {"resources": {
                "nodes": 4, "walltime": "01:00:00"}}})],
            node_id="n")
        assert not mcp.calls, tool


def test_budgets_are_per_node(monkeypatch):
    # One node exhausting the cluster budget must not refuse its siblings.
    monkeypatch.setenv("ARI_NODE_COMPUTE_BUDGET_NS", str(3600))
    for node in ("a", "b"):
        tm.reset_compute_budget(node)
    mcp = _FakeMCP()
    tm.execute_tool_calls(
        mcp, [_tc("slurm_submit", {"nodes": 1, "walltime": "01:00:00"})],
        node_id="a")
    assert tm.compute_budget_remaining("a") == 0
    assert tm.compute_budget_remaining("b") == 3600


def test_running_commands_is_not_charged_to_the_compute_budget(monkeypatch):
    # The two budgets measure different resources and must not cross-charge.
    monkeypatch.setenv("ARI_NODE_COMPUTE_BUDGET_NS", str(3600))
    tm.reset_compute_budget("n")
    mcp = _FakeMCP()
    tm.execute_tool_calls(
        mcp, [_tc("run_bash", {"command": "true"})], node_id="n")
    assert tm.compute_budget_remaining("n") == 3600
