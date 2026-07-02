"""Conformance guard for the extended Evaluator Protocol (subtask 009).

009 extends ``ari.protocols.Evaluator`` to cover the actual runtime contract
(async ``evaluate`` + sync ``evaluate_sync`` + the ``metric_spec`` attribute).
This pins that ``LLMEvaluator`` still satisfies it structurally (no subclassing),
that the Protocol stays ``runtime_checkable``, and — adversarially — that the
extension is *meaningful* (an evaluator missing the new members is rejected).
"""
from __future__ import annotations

import inspect

from ari.evaluator.llm_evaluator import LLMEvaluator
from ari.protocols import Evaluator


def test_evaluator_is_runtime_checkable():
    assert getattr(Evaluator, "_is_runtime_protocol", False) is True


def test_llmevaluator_instance_satisfies_evaluator():
    # Side-effect-free construction (no network until evaluate() is called).
    ev = LLMEvaluator(model="gpt-4o-mini")
    assert isinstance(ev, Evaluator)
    assert callable(ev.evaluate)
    assert callable(ev.evaluate_sync)
    assert hasattr(ev, "metric_spec")


def test_extension_is_meaningful_incomplete_evaluator_rejected():
    # An evaluator exposing only the async evaluate (no evaluate_sync, no
    # metric_spec) must NOT satisfy the extended Protocol — proves 009 tightened
    # the contract rather than leaving it vacuous.
    class OnlyAsync:
        async def evaluate(self, goal, artifacts, summary, node_id=None, node_label=None):
            return {}

    assert not isinstance(OnlyAsync(), Evaluator)


def test_agentloop_evaluator_seam_present():
    # The AgentLoop injection seam is annotated ``Evaluator | None`` (annotation
    # -only retype); the parameter must still exist and default to None.
    from ari.agent.loop import AgentLoop

    param = inspect.signature(AgentLoop.__init__).parameters["evaluator"]
    assert param.default is None
