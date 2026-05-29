"""Verify LLMEvaluator honours each evaluator.axis_mode."""

from __future__ import annotations

from ari.evaluator.dynamic_axes import AxisDef
from ari.evaluator.llm_evaluator import AXIS_NAMES, LLMEvaluator


def test_legacy_mode_pins_canonical_axes():
    """No axes/rubric/checkpoint → legacy 5-axis path."""
    ev = LLMEvaluator(model="test")
    assert ev._axis_names == AXIS_NAMES
    assert ev._dynamic_axes is None


def test_custom_mode_uses_supplied_axes():
    """Explicit ``axes=`` should win and replace AXIS_NAMES."""
    axes = [
        AxisDef(name="speedup", description="kernel speedup", source="custom", weight=0.4),
        AxisDef(name="accuracy", description="numerical accuracy", source="custom", weight=0.4),
        AxisDef(name="cost", description="$/run", source="custom", weight=0.2),
    ]
    ev = LLMEvaluator(model="test", axes=axes)
    assert ev._axis_names == ("speedup", "accuracy", "cost")
    assert ev._dynamic_axes is not None
    # The weight returned by _resolve_axis_weights() must come from the
    # AxisDef.weight when no MetricSpec / ctor override is supplied.
    resolved = ev._resolve_axis_weights()
    assert resolved == {"speedup": 0.4, "accuracy": 0.4, "cost": 0.2}


def test_dynamic_mode_builds_axes_from_rubric(tmp_path):
    """rubric/checkpoint_dir present → dynamic axes that include generic floor."""
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    rubric = {
        "id": "test-rubric",
        "version": "1",
        "score_dimensions": [
            {"id": "rigor", "name": "rigor", "weight": 0.1,
             "description": "scientific rigor"},
        ],
    }
    ev = LLMEvaluator(model="test", checkpoint_dir=str(ckpt), rubric=rubric)
    assert ev._dynamic_axes is not None
    # The generic floor must still appear at the head of the dynamic set.
    head = ev._axis_names[: len(AXIS_NAMES)]
    assert head == AXIS_NAMES
