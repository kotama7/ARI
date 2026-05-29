"""Tests for the configurable composite formulas in LLMEvaluator."""

from __future__ import annotations

import math

import pytest

from ari.evaluator.llm_evaluator import (
    AXIS_NAMES,
    LLMEvaluator,
    _COMPOSITES,
    weighted_arithmetic_mean,
    weighted_geometric_mean,
    weighted_harmonic_mean,
    weighted_min,
)


def _equal_weights() -> dict[str, float]:
    return {name: 0.2 for name in AXIS_NAMES}


def _axes_uneven() -> dict[str, float]:
    # One weak axis (0.1) plus four strong (0.9) — picks up the spread
    # between the composites best.
    return {
        "measurement_validity": 0.1,
        "comparative_rigor": 0.9,
        "novelty": 0.9,
        "reproducibility": 0.9,
        "clarity_of_contribution": 0.9,
    }


def test_registry_keys_match_config_literal():
    """The registry must expose exactly the names EvaluatorConfig allows."""
    assert set(_COMPOSITES) == {
        "harmonic_mean",
        "arithmetic_mean",
        "weighted_min",
        "geometric_mean",
    }


def test_composite_ordering_with_weak_axis():
    """For an uneven axis set the four composites obey a known ordering."""
    axes = _axes_uneven()
    w = _equal_weights()
    h = weighted_harmonic_mean(axes, w)
    g = weighted_geometric_mean(axes, w)
    a = weighted_arithmetic_mean(axes, w)
    m = weighted_min(axes, w)

    # Bottleneck must be the weakest axis.
    assert m == pytest.approx(0.1)
    # Geometric vs. arithmetic vs. harmonic spread (HM ≤ GM ≤ AM is a
    # textbook inequality for positive values).
    assert h <= g <= a
    # Harmonic must be strictly above the floor and strictly below
    # arithmetic given a real weak axis.
    assert h < a
    # Arithmetic on this set is the simple mean (0.1+4*0.9)/5 = 0.74.
    assert a == pytest.approx(0.74)


def test_composite_collapses_when_all_axes_equal():
    """All formulas agree when every axis is the same value."""
    axes = {name: 0.5 for name in AXIS_NAMES}
    w = _equal_weights()
    for fn in (
        weighted_harmonic_mean,
        weighted_geometric_mean,
        weighted_arithmetic_mean,
        weighted_min,
    ):
        assert fn(axes, w) == pytest.approx(0.5, abs=1e-6)


def test_zero_axis_floored_by_epsilon():
    """harmonic / geometric mean must not blow up when an axis is 0."""
    axes = {name: 1.0 for name in AXIS_NAMES}
    axes["novelty"] = 0.0
    w = _equal_weights()
    h = weighted_harmonic_mean(axes, w)
    g = weighted_geometric_mean(axes, w)
    # Both formulas should remain finite and below 1.
    assert math.isfinite(h) and h < 1.0
    assert math.isfinite(g) and g < 1.0


def test_llm_evaluator_dispatches_to_selected_composite():
    """LLMEvaluator stores the composite name and the correct callable."""
    for name, fn in _COMPOSITES.items():
        ev = LLMEvaluator(model="test", composite=name)
        assert ev._composite_name == name
        assert ev._compose_fn is fn


def test_llm_evaluator_rejects_unknown_composite():
    with pytest.raises(ValueError):
        LLMEvaluator(model="test", composite="not_a_formula")
