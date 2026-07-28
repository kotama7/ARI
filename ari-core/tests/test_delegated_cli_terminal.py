"""Delegated-CLI terminal-protocol handling in ``AgentLoop.run``.

With the cli-shim MCP-direct backend, ONE ``claude -p`` subprocess runs the
whole tool loop itself and the outer ReAct loop only ever sees final text —
never ``tool_calls``. Live runs showed the delegated claude doing real work
(skills wrote results into the node work_dir) but signing off in PROSE, so the
loop burned all steps and marked the node failed. The fix (ari/agent/loop.py):

1. a bounded corrective nudge asking for the terminal JSON;
2. acceptance from the skill-side ``results*.json`` artifacts the delegated
   run verifiably wrote (``result_source="delegated_cli_artifacts"``);
3. strictly inert for non-delegated backends (``last_request_delegated`` must
   be the literal ``True``, set only by ``LLMClient`` when it attached
   ``mcp_config``).

All tests are deterministic: no real LLM, CLI, or network.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ari.agent.loop import (
    AgentLoop,
    _DELEGATED_RESULT_SOURCE,
    _DELEGATED_TERMINAL_NUDGE,
    collect_delegated_completion_evidence,
    snapshot_results_files,
)
from ari.llm.client import LLMResponse
from ari.orchestrator.node import Node, NodeStatus


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeDelegatedLLM:
    """Mimics ``LLMClient`` in cli-shim MCP-direct mode.

    Scripted final-text replies, never tool_calls. ``delegated=False`` mimics
    a normal backend that happens to reply with the same prose (the flag and
    the shim probes then read as non-delegated). ``delegated="truthy"``
    assigns a truthy-but-not-True sentinel inside ``complete()`` — the
    MagicMock shape — so the loop's strict ``is True`` read of
    ``last_request_delegated`` is actually exercised.
    """

    def __init__(self, replies: list[str], delegated: bool | str = True) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.seen_messages: list[list[dict]] = []
        self._delegated = delegated
        # LLMClient contract: mcp_client set + _is_cli_shim_target() is True
        # is the precondition for delegation; last_request_delegated is set
        # per-call when mcp_config was actually attached.
        self.mcp_client = object() if delegated else None
        self.last_request_delegated = False
        self.config = SimpleNamespace(model="openai/claude-cli")

    def _is_cli_shim_target(self) -> bool:
        return self._delegated

    def complete(self, messages, tools=None, require_tool=True, **kw) -> LLMResponse:
        self.seen_messages.append([dict(m) for m in messages])
        idx = min(self.calls, len(self.replies) - 1)
        self.calls += 1
        # "truthy" mode: the flag the loop reads right after this call is
        # truthy yet not the literal True (what a MagicMock would yield).
        self.last_request_delegated = (
            object() if self._delegated == "truthy" else self._delegated
        )
        return LLMResponse(content=self.replies[idx], tool_calls=None)


class _FakeMCP:
    _COW_TOOLS: frozenset = frozenset()

    def __init__(self, tool_names=("run_bash",)) -> None:
        self._tools = [
            {"name": n, "description": n,
             "inputSchema": {"type": "object", "properties": {}}}
            for n in tool_names
        ]
        self.calls: list[tuple] = []

    def list_tools(self, phase=None):
        return self._tools

    def call_tool(self, name, args, cow_node_id=None):
        self.calls.append((name, args))
        return {"result": "{}"}


class _FakeMemory:
    def add(self, *a, **k):
        pass

    def search(self, *a, **k):
        return []


_PROSE = "Confirmed: results.json is written and the sweep is complete."
_TERMINAL = json.dumps({
    "status": "success",
    "artifacts": [{"type": "result", "stdout": "bw_gbps: 42.0"}],
    "summary": "sweep done",
})


def _make_loop(llm, max_react_steps: int = 6) -> AgentLoop:
    return AgentLoop(
        llm=llm, memory=_FakeMemory(), mcp=_FakeMCP(),
        evaluator=None, max_react_steps=max_react_steps,
    )


def _run(loop: AgentLoop, tmp_path) -> Node:
    node = Node(id="node_d", parent_id=None, depth=0)
    experiment = {"goal": "measure bandwidth", "work_dir": str(tmp_path)}
    return loop.run(node, experiment)


@pytest.fixture(autouse=True)
def _no_checkpoint_env(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    monkeypatch.delenv("ARI_WORK_DIR", raising=False)


# ---------------------------------------------------------------------------
# (i) prose then terminal JSON after the nudge → success, exactly one extra call
# ---------------------------------------------------------------------------

def test_delegated_prose_then_terminal_json_succeeds_after_one_nudge(tmp_path):
    llm = _FakeDelegatedLLM([_PROSE, _TERMINAL])
    node = _run(_make_loop(llm), tmp_path)

    assert node.status == NodeStatus.SUCCESS
    assert llm.calls == 2  # exactly one corrective extra call
    # The terminal result came from the MODEL, not artifact synthesis.
    assert all(a.get("result_source") != _DELEGATED_RESULT_SOURCE
               for a in node.artifacts)
    assert node.artifacts == [{"type": "result", "stdout": "bw_gbps: 42.0"}]
    # The second call saw the corrective nudge.
    nudged = [m for m in llm.seen_messages[1]
              if m.get("role") == "user"
              and m.get("content") == _DELEGATED_TERMINAL_NUDGE]
    assert len(nudged) == 1


# ---------------------------------------------------------------------------
# (ii) prose forever + skill-side evidence → artifact acceptance with provenance
# ---------------------------------------------------------------------------

def test_delegated_prose_with_results_json_accepted_with_provenance(tmp_path):
    (tmp_path / "results.json").write_text(json.dumps({
        "params": {"block": 64},
        "measurements": {"bw_gbps": 42.0, "max_abs_err": 1e-12},
    }))
    llm = _FakeDelegatedLLM([_PROSE])  # never emits the terminal JSON
    node = _run(_make_loop(llm, max_react_steps=8), tmp_path)

    assert node.status == NodeStatus.SUCCESS
    # nudge cap (2) + the accepting call = 3 LLM calls, budget NOT burned
    assert llm.calls == 3
    assert node.artifacts[0]["result_source"] == _DELEGATED_RESULT_SOURCE
    assert "bw_gbps" in node.artifacts[0]["stdout"]
    # provenance also lands in the node trace log
    assert any(_DELEGATED_RESULT_SOURCE in t for t in node.trace_log)
    # the delegated CLI's own prose sign-off is kept as the summary
    assert node.eval_summary == _PROSE


# ---------------------------------------------------------------------------
# (iii) prose forever + NO evidence → still fails on budget (no false success)
# ---------------------------------------------------------------------------

def test_delegated_prose_without_evidence_still_fails_on_budget(tmp_path):
    llm = _FakeDelegatedLLM([_PROSE])
    node = _run(_make_loop(llm, max_react_steps=6), tmp_path)

    assert node.status == NodeStatus.FAILED
    assert node.error_log == "Max ReAct steps exceeded"
    assert llm.calls == 6  # every step consumed, as before the fix


def test_delegated_inherited_results_do_not_count_as_evidence(tmp_path):
    # A custom-named lineage file inherited from the parent work_dir must NOT
    # be accepted: it predates the node (captured by the run-start baseline).
    (tmp_path / "results_seed42.json").write_text(json.dumps({
        "measurements": {"bw_gbps": 40.0},
    }))
    llm = _FakeDelegatedLLM([_PROSE])
    node = _run(_make_loop(llm, max_react_steps=6), tmp_path)

    assert node.status == NodeStatus.FAILED


# ---------------------------------------------------------------------------
# (iv) non-delegated backend with identical prose → behavior identical to today
# ---------------------------------------------------------------------------

def test_non_delegated_prose_gets_no_nudge_and_no_acceptance(tmp_path):
    # Even with completion-shaped artifacts on disk, a normal backend that
    # replies in prose must fail exactly as before the fix.
    (tmp_path / "results.json").write_text(json.dumps({
        "measurements": {"bw_gbps": 42.0},
    }))
    llm = _FakeDelegatedLLM([_PROSE], delegated=False)
    node = _run(_make_loop(llm, max_react_steps=4), tmp_path)

    assert node.status == NodeStatus.FAILED
    assert node.error_log == "Max ReAct steps exceeded"
    assert all(a.get("result_source") != _DELEGATED_RESULT_SOURCE
               for a in node.artifacts)
    # The delegated corrective nudge never entered the conversation.
    for msgs in llm.seen_messages:
        assert all(m.get("content") != _DELEGATED_TERMINAL_NUDGE for m in msgs)
    # Step-0 prose still gets the legacy force prompt.
    assert any("STOP. Do not write plans." in str(m.get("content", ""))
               for m in llm.seen_messages[1])


def test_truthy_but_not_true_flag_stays_inert(tmp_path):
    # MagicMock-style fakes auto-create truthy attributes; only the literal
    # True (set by LLMClient when mcp_config was attached) may activate the
    # delegated branches. The sentinel is assigned INSIDE complete(), so the
    # loop reads it fresh on every step — weakening the `is True` read of
    # last_request_delegated to bool(...) makes this test fail.
    llm = _FakeDelegatedLLM([_PROSE], delegated="truthy")
    node = _run(_make_loop(llm, max_react_steps=4), tmp_path)

    # The loop really saw a truthy-but-not-True flag.
    assert llm.last_request_delegated and llm.last_request_delegated is not True
    assert node.status == NodeStatus.FAILED
    for msgs in llm.seen_messages:
        assert all(m.get("content") != _DELEGATED_TERMINAL_NUDGE for m in msgs)


# ---------------------------------------------------------------------------
# evidence-collection helpers (pure functions)
# ---------------------------------------------------------------------------

class TestCompletionEvidence:
    def test_results_json_always_eligible(self, tmp_path):
        (tmp_path / "results.json").write_text(
            json.dumps({"measurements": {"a": 1}}))
        ev = collect_delegated_completion_evidence(str(tmp_path), baseline={})
        assert ev is not None
        assert ev["files"] == ["results.json"]
        assert ev["measurement_names"] == ["a"]

    def test_empty_measurements_is_not_evidence(self, tmp_path):
        (tmp_path / "results.json").write_text(
            json.dumps({"measurements": {}}))
        assert collect_delegated_completion_evidence(
            str(tmp_path), baseline={}) is None

    def test_custom_name_needs_baseline_delta(self, tmp_path):
        p = tmp_path / "results_seed42.json"
        p.write_text(json.dumps({"measurements": {"a": 1}}))
        baseline = snapshot_results_files(str(tmp_path))
        # unchanged vs baseline → inherited → not evidence
        assert collect_delegated_completion_evidence(
            str(tmp_path), baseline) is None
        # rewritten after the baseline (size delta) → this node's own output
        p.write_text(json.dumps({"measurements": {"a": 1, "b": 2.5}}))
        ev = collect_delegated_completion_evidence(str(tmp_path), baseline)
        assert ev is not None and ev["files"] == ["results_seed42.json"]

    def test_custom_name_without_baseline_is_ignored(self, tmp_path):
        (tmp_path / "results_x.json").write_text(
            json.dumps({"measurements": {"a": 1}}))
        assert collect_delegated_completion_evidence(
            str(tmp_path), baseline=None) is None

    def test_missing_dir_and_garbage_are_none(self, tmp_path):
        assert collect_delegated_completion_evidence(
            str(tmp_path / "nope"), baseline={}) is None
        (tmp_path / "results.json").write_text("not json")
        assert collect_delegated_completion_evidence(
            str(tmp_path), baseline={}) is None
