"""Tests for the multi-axis / weighted-harmonic-mean evaluator contract."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ari.evaluator.llm_evaluator import (
    AXIS_NAMES,
    LLMEvaluator,
    MetricSpec,
    _DEFAULT_AXIS_WEIGHTS,
    weighted_harmonic_mean,
)


def _fake_completion_response(payload_json: str):
    msg = MagicMock()
    msg.content = payload_json
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ── weighted_harmonic_mean ────────────────────────────────────────────────────


def test_harmonic_mean_uniform_axes_equals_value():
    axes = {k: 0.6 for k in AXIS_NAMES}
    assert weighted_harmonic_mean(axes, _DEFAULT_AXIS_WEIGHTS) == pytest.approx(0.6)


def test_harmonic_mean_zero_axis_drags_score_near_floor():
    """A single zero axis must crush the composite below the arithmetic mean."""
    axes = {k: 0.9 for k in AXIS_NAMES}
    axes["reproducibility"] = 0.0
    score = weighted_harmonic_mean(axes, _DEFAULT_AXIS_WEIGHTS)
    # Arithmetic mean would be 0.72; harmonic with ε=0.01 floor must be tiny.
    assert score < 0.1


def test_harmonic_mean_separates_balanced_from_lopsided():
    """Lopsided axes should score strictly lower than balanced ones at the same mean."""
    balanced = weighted_harmonic_mean({k: 0.7 for k in AXIS_NAMES}, _DEFAULT_AXIS_WEIGHTS)
    lopsided = weighted_harmonic_mean(
        {
            "measurement_validity": 0.95,
            "comparative_rigor": 0.95,
            "novelty": 0.95,
            "reproducibility": 0.3,
            "clarity_of_contribution": 0.35,
        },
        _DEFAULT_AXIS_WEIGHTS,
    )
    assert lopsided < balanced


def test_harmonic_mean_clamps_out_of_range_inputs():
    axes = {k: 1.5 for k in AXIS_NAMES}  # 1.5 clamped to 1.0
    assert weighted_harmonic_mean(axes, _DEFAULT_AXIS_WEIGHTS) == pytest.approx(1.0)


# ── evaluate() contract ──────────────────────────────────────────────────────


def test_evaluate_parses_axis_scores_and_computes_composite():
    ev = LLMEvaluator(model="dummy")

    async def _fake(**kwargs):
        return _fake_completion_response(
            '{"has_real_data": true, "metrics": {}, "reason": "ok", '
            '"axis_scores": {"measurement_validity": 0.9, "comparative_rigor": 0.8, '
            '"novelty": 0.6, "reproducibility": 0.4, "clarity_of_contribution": 0.7}, '
            '"axis_rationales": {"measurement_validity": "strong"}, '
            '"comparison_found": true}'
        )

    with patch("ari.evaluator.llm_evaluator.litellm.acompletion", side_effect=_fake):
        result = ev.evaluate_sync(goal="g", artifacts=[], summary="s", node_id="nx")

    # Composite = weighted harmonic mean over the five axes
    expected = weighted_harmonic_mean(
        {
            "measurement_validity": 0.9,
            "comparative_rigor": 0.8,
            "novelty": 0.6,
            "reproducibility": 0.4,
            "clarity_of_contribution": 0.7,
        },
        _DEFAULT_AXIS_WEIGHTS,
    )
    assert result["scientific_score"] == pytest.approx(expected)
    assert result["metrics"]["_scientific_score"] == pytest.approx(expected)
    assert result["metrics"]["_axis_scores"]["novelty"] == pytest.approx(0.6)
    assert result["axis_rationales"]["measurement_validity"] == "strong"


def test_evaluate_falls_back_to_legacy_scientific_score():
    """Older judges that return only the scalar score still produce a composite."""
    ev = LLMEvaluator(model="dummy")

    async def _fake(**kwargs):
        return _fake_completion_response(
            '{"has_real_data": true, "metrics": {}, "reason": "ok", '
            '"scientific_score": 0.5, "comparison_found": false}'
        )

    with patch("ari.evaluator.llm_evaluator.litellm.acompletion", side_effect=_fake):
        result = ev.evaluate_sync(goal="g", artifacts=[], summary="s", node_id="nx")

    assert result["scientific_score"] == pytest.approx(0.5)
    for k in AXIS_NAMES:
        assert result["metrics"]["_axis_scores"][k] == pytest.approx(0.5)


def test_evaluate_missing_axis_treated_as_zero_crushes_score():
    """A judge that omits an axis is penalised (implicit zero on missing axis)."""
    ev = LLMEvaluator(model="dummy")

    async def _fake(**kwargs):
        return _fake_completion_response(
            '{"has_real_data": true, "metrics": {}, "reason": "ok", '
            '"axis_scores": {"measurement_validity": 0.9, "comparative_rigor": 0.9, '
            '"novelty": 0.9, "clarity_of_contribution": 0.9}, '
            '"comparison_found": false}'
        )

    with patch("ari.evaluator.llm_evaluator.litellm.acompletion", side_effect=_fake):
        result = ev.evaluate_sync(goal="g", artifacts=[], summary="s", node_id="nx")

    # reproducibility is missing → treated as 0 → composite near floor
    assert result["metrics"]["_axis_scores"]["reproducibility"] == 0.0
    assert result["scientific_score"] < 0.1


# ── axis_weights resolution ──────────────────────────────────────────────────


def test_metric_spec_weights_override_constructor_weights():
    spec = MetricSpec(axis_weights={"measurement_validity": 1.0})
    ev = LLMEvaluator(
        model="dummy",
        metric_spec=spec,
        axis_weights={"novelty": 1.0},  # should be ignored
    )
    assert ev._resolve_axis_weights() == {"measurement_validity": 1.0}


def test_constructor_weights_used_when_spec_has_none():
    ev = LLMEvaluator(
        model="dummy",
        axis_weights={"novelty": 0.5, "measurement_validity": 0.5},
    )
    assert ev._resolve_axis_weights() == {"novelty": 0.5, "measurement_validity": 0.5}


def test_default_weights_when_nothing_specified():
    ev = LLMEvaluator(model="dummy")
    assert ev._resolve_axis_weights() == dict(_DEFAULT_AXIS_WEIGHTS)


def test_system_prompt_includes_axis_weight_line():
    ev = LLMEvaluator(model="dummy")
    sp = ev._build_system_prompt()
    assert "Axis weights" in sp
    for k in AXIS_NAMES:
        assert k in sp


def test_results_json_survives_an_llm_failure(tmp_path, monkeypatch):
    """results.json is the AUTHORITATIVE measured ground truth. An empty/garbage
    LLM reply (json.loads on "" → "Expecting value") must NOT orphan a node's
    real measurements as has_real_data=False — the e2e run's root node lost 27
    real measurements this way because the merge lived inside the try that the
    LLM parse failure short-circuited."""
    (tmp_path / "results.json").write_text(
        '{"measurements": {"gbps_untiled": 11.389, "speedup_best": 1.265, "correctness": 0}}'
    )
    monkeypatch.setenv("ARI_WORK_DIR", str(tmp_path))

    ev = LLMEvaluator(model="dummy")

    async def _empty(**kwargs):            # the judge returns nothing
        return _fake_completion_response("")

    with patch("ari.evaluator.llm_evaluator.litellm.acompletion", side_effect=_empty):
        result = ev.evaluate_sync(goal="g", artifacts=[{"type": "result"}],
                                  summary="s", node_id="root")

    assert result["has_real_data"] is True, "real measurements were discarded on LLM failure"
    assert result["metrics"]["gbps_untiled"] == pytest.approx(11.389)
    assert result["metrics"]["speedup_best"] == pytest.approx(1.265)


def test_no_results_json_still_reports_no_real_data_on_failure(tmp_path, monkeypatch):
    """Without results.json, an LLM failure correctly stays has_real_data=False —
    the recovery must not fabricate real data where there is none."""
    monkeypatch.setenv("ARI_WORK_DIR", str(tmp_path))  # no results.json here
    ev = LLMEvaluator(model="dummy")

    async def _empty(**kwargs):
        return _fake_completion_response("")

    with patch("ari.evaluator.llm_evaluator.litellm.acompletion", side_effect=_empty):
        result = ev.evaluate_sync(goal="g", artifacts=[], summary="s", node_id="root")

    assert result["has_real_data"] is False
    assert result["metrics"] == {}


def test_corrupt_results_json_is_flagged_not_silently_absent(tmp_path, monkeypatch, caplog):
    """M3: a results.json that EXISTS but does not decode is a LOST measurement,
    not an absent one. The reader must warn and drop a `results.json.unreadable`
    sidecar so a truncated write (the writer is non-atomic) is distinguishable
    from a node that legitimately emitted no results.json."""
    (tmp_path / "results.json").write_text('{"measurements": {"gbps": 1.5', encoding="utf-8")
    monkeypatch.setenv("ARI_WORK_DIR", str(tmp_path))

    with caplog.at_level("WARNING"):
        meas = LLMEvaluator._results_json_measurements()

    assert meas == {}  # unparseable → no measurements recovered
    assert (tmp_path / "results.json.unreadable").is_file()
    assert any("unreadable" in r.getMessage() for r in caplog.records)


def test_absent_results_json_leaves_no_unreadable_sidecar(tmp_path, monkeypatch):
    """M3 corollary: a genuinely absent results.json stays silent — no sidecar,
    no warning — so absence and corruption never look alike."""
    monkeypatch.setenv("ARI_WORK_DIR", str(tmp_path))
    assert LLMEvaluator._results_json_measurements() == {}
    assert not (tmp_path / "results.json.unreadable").exists()
