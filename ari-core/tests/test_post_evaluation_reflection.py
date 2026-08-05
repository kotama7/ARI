"""The handoff's next_steps/concerns must be written AFTER the node is scored.

WHY THIS MATTERS TO THE STUDY. The S-E contrast is meant to isolate what an
LLM's INTERPRETATION adds on top of the same objective evidence. If the
self-report is written before the evaluator runs, S is "evidence + a self-account
made without the verdict", which is a different and muddier question — and not
even cleanly blind, since the agent's own self-test already estimates its score.
Running the review after scoring makes both arms carry identical evidence and
lets S differ only by the interpretation.

The fallback matters just as much: an auxiliary LLM call that fails must never
cost a node its handoff, so the pre-scoring self-report stays in place and the
report says which stage produced it. An analysis that pooled the two would be
comparing two different treatments under one name.
"""
import json

import pytest


class _Resp:
    def __init__(self, content):
        self.content = content


class _LLM:
    """Records what it was asked and returns a canned review."""

    def __init__(self, content, fail=False):
        self.content, self.fail, self.calls = content, fail, []

    def complete(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self.fail:
            raise RuntimeError("auxiliary call failed")
        return _Resp(self.content)


def _make_node():
    from ari.orchestrator.node import Node
    n = Node(id="n1", parent_id=None, depth=0)
    n.metrics = {"valid_geomean_speedup": 1.23}
    n.auxiliary_llm_calls = []
    return n


def test_reflection_sees_the_verdict_and_is_told_not_to_restate_it():
    from ari.agent.loop import AgentLoop

    llm = _LLM(json.dumps({"next_steps": ["block the k loop"],
                           "concerns": ["alignment assumed"]}))
    loop = AgentLoop.__new__(AgentLoop)
    loop.llm = llm
    loop.max_react_steps = 20
    node = _make_node()
    steps, concerns = AgentLoop._post_evaluation_reflection(
        loop, node, [{"role": "assistant", "content": "built and ran"}],
        {"goal": "optimise gemm"},
        {"reason": "valid", "scientific_score": 1.23})

    assert steps == ["block the k loop"]
    assert concerns == ["alignment assumed"]
    sent = json.dumps(llm.calls[0]["messages"])
    assert "1.23" in sent, "the verdict must reach the reviewer"
    assert "restate" in sent.lower() or "repeating" in sent.lower(), (
        "the prompt must forbid parroting the numbers, or S becomes E in prose")
    assert llm.calls[0]["kwargs"].get("phase") == "post_evaluation_reflection"
    assert node.auxiliary_llm_calls, "the call must be auditable"


def test_a_failed_reflection_returns_empty_so_the_caller_keeps_the_earlier_report():
    from ari.agent.loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    loop.llm = _LLM("", fail=True)
    loop.max_react_steps = 20
    node = _make_node()
    steps, concerns = AgentLoop._post_evaluation_reflection(
        loop, node, [], {"goal": "g"}, {"reason": "valid"})
    assert (steps, concerns) == ([], [])
    assert node.auxiliary_llm_calls[-1].get("error"), "the failure must be recorded"


def test_unparseable_output_does_not_raise():
    from ari.agent.loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    loop.llm = _LLM("I think you should try blocking.")
    loop.max_react_steps = 20
    assert AgentLoop._post_evaluation_reflection(
        loop, _make_node(), [], {"goal": "g"}, {"reason": "valid"}) == ([], [])


def test_node_report_records_which_stage_wrote_the_hints():
    """Pooling pre- and post-scoring reports would compare two treatments as one."""
    from ari.orchestrator.node import Node

    n = Node(id="n2", parent_id=None, depth=0)
    assert n.self_report_stage == "pre_evaluation"
    n.self_report_stage = "post_evaluation"
    assert n.self_report_stage == "post_evaluation"
