"""Tests for the domain-general producer obligation (ari.agent.metric_contract).

Generality is the property under test: the obligation text must state the SAME
requirements (verify correctness, measure the ceiling, emit provenance, declare
the contract) for any domain, WITHOUT baking in roofline/HPC vocabulary. The
agent supplies the domain-specific fulfilment.
"""
from __future__ import annotations

from ari.agent.metric_contract import build_contract_obligation


def test_no_contract_no_obligation():
    assert build_contract_obligation(None) == ""
    assert build_contract_obligation({}) == ""
    assert build_contract_obligation("nope") == ""


def test_obligation_states_all_four_requirements():
    obl = build_contract_obligation(
        {"key": "primary_norm_metric", "concept": "normalized", "invariants": ["value <= 1"]}
    )
    assert obl
    # the four obligations are present
    for token in ("CORRECTNESS", "MEASURED CEILING", "PROVENANCE", "required_measured"):
        assert token in obl, token
    # the metric key and its invariant are surfaced
    assert "primary_norm_metric" in obl
    assert "value <= 1" in obl


def test_obligation_is_domain_neutral():
    # The FRAMEWORK text must not bake in HPC/roofline vocabulary — those would
    # leak domain knowledge into a system that also runs ML / theory experiments.
    obl = build_contract_obligation(
        {"key": "norm_efficiency", "concept": "normalized", "invariants": ["value <= 1"]}
    ).lower()
    for banned in ("roofline", "gflop", "flop/s", "bandwidth", "cache", "dram", "stream", "arithmetic intensity"):
        assert banned not in obl, banned


def test_obligation_works_for_ml_concept():
    # Same machinery, an ML-flavoured metric: still domain-neutral, still states
    # the obligations — the agent would fulfil with an ML baseline, not a STREAM.
    obl = build_contract_obligation(
        {"key": "val_accuracy_fraction", "concept": "probability", "invariants": ["0 <= value", "value <= 1"]}
    )
    assert "CORRECTNESS" in obl and "val_accuracy_fraction" in obl
    assert "roofline" not in obl.lower() and "gflop" not in obl.lower()
