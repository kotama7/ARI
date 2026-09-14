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


# --- the two judges answer in different currencies -------------------------------
#
# ARI runs either an LLM judge (a bounded composite plus per-axis rationales) or
# the harness evaluator (a native speedup plus per-case validity). The reviewer
# is asked to interpret whichever arrived; a reviewer that only understood one
# would silently produce a weaker handoff under the other, and the arms would
# still be reported as comparable.

def _loop_with(llm):
    from ari.agent.loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    loop.llm = llm
    loop.max_react_steps = 20
    return loop


def _review(loop, node, eval_result):
    from ari.agent.loop import AgentLoop

    return AgentLoop._post_evaluation_reflection(
        loop, node, [{"role": "assistant", "content": "built and ran"}],
        {"goal": "optimise the kernel"}, eval_result)


def test_the_llm_judges_axes_reach_the_reviewer():
    llm = _LLM(json.dumps({"next_steps": ["tighten the error bound"],
                           "concerns": ["only one seed"]}))
    loop = _loop_with(llm)
    node = _make_node()
    node.metrics = {"_scientific_score": 0.72}
    steps, concerns = _review(loop, node, {
        "reason": "novel but under-validated",
        "scientific_score": 0.72,
        "axis_scores": {"rigor": 0.6, "novelty": 0.9},
        "evaluation_status": "valid",
    })
    assert steps and concerns
    sent = json.dumps(llm.calls[0]["messages"])
    assert "axis_scores" in sent and "rigor" in sent


def test_the_harnesss_per_case_validity_reaches_the_reviewer_without_its_numbers():
    """Validity, not measurements: the child already receives evaluation_cases,
    and the prompt's whole point is that the review must not restate them."""
    llm = _LLM(json.dumps({"next_steps": ["fix the 2000x500x500 case"],
                           "concerns": ["one shape still wrong"]}))
    loop = _loop_with(llm)
    node = _make_node()
    steps, concerns = _review(loop, node, {
        "reason": "measurement_invalid",
        "scientific_score": 0.0,
        "evaluation_status": "measurement_invalid",
        "evaluation_cases": {
            "1000x1000x1000": {"valid": True, "measurements": {"speedup": 1.4}},
            "2000x500x500": {"valid": False, "measurements": {"speedup": 0.0}},
        },
    })
    assert steps and concerns
    sent = json.dumps(llm.calls[0]["messages"])
    assert "case_validity" in sent
    assert "2000x500x500" in sent
    # The per-case speedups are NOT forwarded into the review prompt.
    assert "1.4" not in sent


def test_an_outage_is_not_reviewed_at_all():
    """An infrastructure error carries no metrics and no score by construction --
    an outage is not a claim about the candidate. Asking a model to interpret it
    would invent content in the one channel this study measures, and it would
    land in the handoff looking like a finding."""
    llm = _LLM(json.dumps({"next_steps": ["invented"], "concerns": ["invented"]}))
    loop = _loop_with(llm)
    node = _make_node()
    node.metrics = {}
    steps, concerns = _review(loop, node, {
        "reason": "deterministic eval infrastructure error: no harness",
        "evaluation_status": "infrastructure_error",
    })
    assert (steps, concerns) == ([], [])
    assert llm.calls == [], "the model was asked to interpret an outage"


def test_a_verdict_with_nothing_measurable_is_not_reviewed():
    """Prose alone is not evidence; reviewing it invents what it interprets."""
    llm = _LLM(json.dumps({"next_steps": ["invented"], "concerns": []}))
    loop = _loop_with(llm)
    node = _make_node()
    node.metrics = {}
    steps, concerns = _review(loop, node, {"reason": "looks fine to me"})
    assert (steps, concerns) == ([], [])
    assert llm.calls == []


def test_every_auxiliary_call_is_audited_with_its_prompt():
    """A study comparing what a child was handed has to be able to show what
    produced it."""
    llm = _LLM(json.dumps({"next_steps": ["a"], "concerns": ["b"]}))
    loop = _loop_with(llm)
    node = _make_node()
    _review(loop, node, {"reason": "valid", "scientific_score": 1.23,
                         "evaluation_status": "valid"})
    assert len(node.auxiliary_llm_calls) == 1
    call = node.auxiliary_llm_calls[0]
    assert call["phase"] == "post_evaluation_reflection"
    assert call["messages"] and call["response"]["content"]


def test_the_node_fields_the_merge_dropped_are_declared():
    """They were deleted while every reader and every test stayed, so writes
    landed on an undeclared attribute and reads got a default. Nothing raised;
    the self-report was simply empty for every run.

    ``auxiliary_llm_calls`` is the exception that made it visible: appending to
    an attribute nobody declared is an AttributeError, not a default.
    """
    from ari.orchestrator.node import Node

    node = Node(id="n", parent_id=None, depth=0)
    assert node.agent_summary == ""
    assert node.agent_next_steps == [] and node.agent_concerns == []
    assert node.self_report_stage == "pre_evaluation"
    assert node.auxiliary_llm_calls == []
    assert node.ended_by == ""
    node.auxiliary_llm_calls.append({"phase": "x"})
    assert len(node.auxiliary_llm_calls) == 1
