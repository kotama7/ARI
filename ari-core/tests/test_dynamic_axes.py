"""Tests for Phase 3 dynamic-axis system.

Covers:
- rubric_to_axes derives axes from rubric.score_dimensions (dict + dataclass-like)
- plan_to_axes recognises VirSci experiment_plan keywords
- build_axes_for_run composes generic + rubric + plan, dedupes, preserves order
- Generic axes survive when rubric / plan are absent (graceful floor)
- LLMEvaluator with dynamic axes uses the new schema in prompt and parser
- LLMEvaluator without ``axes=`` keeps legacy 5-axis behaviour intact
- weighted_harmonic_mean honours a custom axis_names tuple
"""

from __future__ import annotations

import pytest

from ari.evaluator.dynamic_axes import (
    GENERIC_AXES,
    GENERIC_AXIS_NAMES,
    AxisDef,
    axes_to_prompt_section,
    axes_to_weights,
    build_axes_for_run,
    plan_to_axes,
    rubric_to_axes,
)
from ari.evaluator.llm_evaluator import (
    AXIS_NAMES,
    LLMEvaluator,
    weighted_harmonic_mean,
)


# ---------------------------------------------------------------------------
# rubric_to_axes
# ---------------------------------------------------------------------------


def test_rubric_to_axes_dict_input():
    rubric = {
        "id": "sc",
        "score_dimensions": [
            {"name": "scalability_evaluation", "description": "scaling study"},
            {"name": "novelty", "description": "originality"},  # collides with generic
            {"name": "overall", "description": "overall rating"},  # bookkeeping → skip
        ],
    }
    axes = rubric_to_axes(rubric)
    names = [a.name for a in axes]
    # scalability_evaluation kept, novelty dropped (clashes with generic floor),
    # overall dropped (bookkeeping).
    assert "scalability_evaluation" in names
    assert "novelty" not in names
    assert "overall" not in names
    # All rubric-derived axes carry source=rubric:<id>.
    assert all(a.source == "rubric:sc" for a in axes)


def test_rubric_to_axes_dataclass_like_input():
    class _Dim:
        def __init__(self, name, description):
            self.name = name
            self.description = description

    class _Rubric:
        id = "icpp"
        score_dimensions = [_Dim("mpi_scaling", "MPI scaling rigor")]

    axes = rubric_to_axes(_Rubric())
    assert len(axes) == 1
    assert axes[0].name == "mpi_scaling"
    assert axes[0].source == "rubric:icpp"


def test_rubric_to_axes_skips_bookkeeping_dims():
    rubric = {
        "id": "neurips",
        "score_dimensions": [
            {"name": "originality", "description": "..."},
            {"name": "overall", "description": "..."},
            {"name": "confidence", "description": "..."},
            {"name": "ethical_concerns", "description": "..."},
        ],
    }
    names = [a.name for a in rubric_to_axes(rubric)]
    assert names == ["originality"]


def test_rubric_to_axes_empty_or_none():
    assert rubric_to_axes(None) == []
    assert rubric_to_axes({}) == []
    assert rubric_to_axes({"score_dimensions": []}) == []


def test_rubric_to_axes_sanitises_names():
    rubric = {
        "id": "sc",
        "score_dimensions": [
            {"name": "Strong/Weak Scaling Rigor", "description": "..."},
            {"name": "AD/AE Artifact!", "description": "..."},
        ],
    }
    names = [a.name for a in rubric_to_axes(rubric)]
    # Sanitised: lowercase, non-alnum collapsed to underscore.
    assert "strong_weak_scaling_rigor" in names
    assert "ad_ae_artifact" in names


# ---------------------------------------------------------------------------
# plan_to_axes
# ---------------------------------------------------------------------------


_HPC_RUBRIC = {"id": "sc", "domain": "HPC / Systems"}
_ML_RUBRIC = {"id": "neurips", "domain": "ML / AI"}


def test_plan_to_axes_recognises_pmax_bmax():
    """HPC vocabulary only activates when rubric.domain matches."""
    plan = (
        "1) Baseline\n"
        "4) CTCE model construction\n"
        "- Microbenchmark to measure bandwidth ceilings (Pmax/Bmax).\n"
    )
    names = [a.name for a in plan_to_axes(plan, rubric=_HPC_RUBRIC)]
    assert "model_calibration_present" in names


def test_plan_to_axes_recognises_baselines_and_scaling():
    plan = (
        "6) Comparisons:\n"
        "- Baselines: MKL, BOUND-SpMM.\n"
        "- Strong scaling across cores.\n"
    )
    names = [a.name for a in plan_to_axes(plan, rubric=_HPC_RUBRIC)]
    # baseline_comparison_present is in the CORE vocabulary → always fires.
    assert "baseline_comparison_present" in names
    # scaling_study_present is HPC-specific → fires only with HPC rubric.
    assert "scaling_study_present" in names


def test_plan_to_axes_recognises_statistical_test():
    """Cross-domain core vocabulary applies regardless of rubric."""
    plan = "Run 5 seeds, report mean ± std and 95% confidence interval."
    names = [a.name for a in plan_to_axes(plan)]   # no rubric needed
    assert "statistical_test_present" in names


def test_plan_to_axes_dedupes_within_call():
    plan = (
        "Section 1: STREAM bandwidth measurement.\n"
        "Section 2: Pmax compute peak.\n"
        "Section 3: Bmax bandwidth ceiling.\n"
    )
    names = [a.name for a in plan_to_axes(plan, rubric=_HPC_RUBRIC)]
    # All three lines map to the same canonical axis; only one entry.
    assert names.count("model_calibration_present") == 1


def test_plan_to_axes_empty_plan():
    assert plan_to_axes("") == []
    assert plan_to_axes("just freeform text without keywords") == []


def test_plan_to_axes_hpc_keywords_skip_for_ml_rubric():
    """Pmax/Bmax mentions in an ML run must NOT activate HPC axes —
    domain gating prevents HPC bias leaking into ML evaluation."""
    plan = "We measure peak compute Pmax for the GPU."
    names_hpc = [a.name for a in plan_to_axes(plan, rubric=_HPC_RUBRIC)]
    names_ml = [a.name for a in plan_to_axes(plan, rubric=_ML_RUBRIC)]
    assert "model_calibration_present" in names_hpc
    assert "model_calibration_present" not in names_ml


def test_plan_to_axes_ml_vocabulary_activates_for_neurips():
    plan = (
        "We use 5-fold cross-validation and report ROC AUC. "
        "Hyperparameter tuning via grid search."
    )
    names = [a.name for a in plan_to_axes(plan, rubric=_ML_RUBRIC)]
    assert "cross_validation_present" in names
    assert "classification_metrics_present" in names
    assert "hyperparameter_search_present" in names


def test_plan_to_axes_theory_vocabulary_activates_for_stoc():
    rubric = {"id": "stoc", "domain": "Theory / Algorithms"}
    plan = (
        "Theorem 1: the algorithm runs in polynomial time. "
        "Lemma 2 establishes a tight upper bound."
    )
    names = [a.name for a in plan_to_axes(plan, rubric=rubric)]
    assert "formal_proof_present" in names
    assert "complexity_analysis_present" in names
    assert "bound_analysis_present" in names


def test_plan_to_axes_hci_vocabulary_activates_for_chi():
    rubric = {"id": "chi", "domain": "Human-Computer Interaction"}
    plan = (
        "We conducted a between-subjects user study (N=24, IRB approved) "
        "with Likert-scale questionnaires."
    )
    names = [a.name for a in plan_to_axes(plan, rubric=rubric)]
    assert "user_study_present" in names
    assert "ethics_compliance_present" in names
    assert "subjective_measurement_present" in names


def test_plan_to_axes_unknown_domain_falls_back_to_core():
    """A rubric with an unrecognised domain still gets the core
    vocabulary applied — the system stays generic."""
    rubric = {"id": "weird", "domain": "Astrology"}
    plan = "We baseline against prior approaches with t-tests."
    names = [a.name for a in plan_to_axes(plan, rubric=rubric)]
    assert "baseline_comparison_present" in names
    assert "statistical_test_present" in names


def test_plan_to_axes_rubric_custom_patterns_apply():
    """rubric.plan_keyword_axes is the per-venue extension point."""
    rubric = {
        "id": "custom",
        "domain": "ML / AI",
        "plan_keyword_axes": [
            {
                "pattern": r"\b(my custom marker)\b",
                "axis": "custom_marker_present",
                "description": "Whether the custom marker is present.",
            }
        ],
    }
    plan = "We document our My Custom Marker for traceability."
    names = [a.name for a in plan_to_axes(plan, rubric=rubric)]
    assert "custom_marker_present" in names


def test_plan_to_axes_malformed_custom_pattern_is_skipped():
    rubric = {
        "id": "broken",
        "domain": "ML / AI",
        "plan_keyword_axes": [
            {"pattern": "(?<-bad regex", "axis": "broken", "description": "x"},
            {"pattern": r"\bgood\b", "axis": "good_present", "description": "ok"},
        ],
    }
    plan = "good marker"
    names = [a.name for a in plan_to_axes(plan, rubric=rubric)]
    assert "good_present" in names
    assert "broken" not in names


# ---------------------------------------------------------------------------
# build_axes_for_run
# ---------------------------------------------------------------------------


def test_build_axes_includes_generic_floor_when_no_inputs():
    axes = build_axes_for_run()
    names = [a.name for a in axes]
    for k in GENERIC_AXIS_NAMES:
        assert k in names
    assert all(a.source == "generic" for a in axes)


def test_build_axes_composes_all_three_layers():
    rubric = {
        "id": "sc",
        "domain": "HPC / Systems",
        "score_dimensions": [
            {"name": "scalability_evaluation", "description": "scaling rigor"},
            {"name": "reproducibility", "description": "AD/AE"},  # clashes with generic
        ],
    }
    idea_data = {
        "ideas": [
            {
                "title": "ENVELOPE-SpMM",
                "experiment_plan": (
                    "1) baseline\n"
                    "4) CTCE model construction (measure Pmax/Bmax via STREAM)\n"
                    "6) Comparisons against MKL\n"
                ),
            }
        ]
    }
    axes = build_axes_for_run(rubric=rubric, idea_data=idea_data)
    names = [a.name for a in axes]

    # Generic floor present.
    for k in GENERIC_AXIS_NAMES:
        assert k in names

    # Rubric axis kept; rubric "reproducibility" dropped (clash with generic).
    assert "scalability_evaluation" in names
    # The dropped rubric axis should appear *only* in its generic form.
    assert names.count("reproducibility") == 1

    # Plan-derived axes added.
    assert "model_calibration_present" in names
    assert "baseline_comparison_present" in names

    # Provenance preserved.
    by_name = {a.name: a for a in axes}
    assert by_name["scalability_evaluation"].source.startswith("rubric:")
    assert by_name["model_calibration_present"].source == "plan"


def test_build_axes_idea_without_plan_falls_back_gracefully():
    idea_data = {"ideas": [{"title": "no plan field"}]}
    axes = build_axes_for_run(idea_data=idea_data)
    # Just generic floor.
    assert {a.name for a in axes} == set(GENERIC_AXIS_NAMES)


# ---------------------------------------------------------------------------
# axes_to_prompt_section / axes_to_weights
# ---------------------------------------------------------------------------


def test_prompt_section_lists_each_axis():
    axes = build_axes_for_run()
    block = axes_to_prompt_section(axes)
    for a in axes:
        assert a.name in block
        assert a.description[:30] in block


def test_axes_to_weights_extracts_per_axis_weight():
    axes = [AxisDef("a", "?", "generic", weight=0.3), AxisDef("b", "?", "plan", weight=0.05)]
    w = axes_to_weights(axes)
    assert w == {"a": 0.3, "b": 0.05}


# ---------------------------------------------------------------------------
# weighted_harmonic_mean axis_names parameter
# ---------------------------------------------------------------------------


def test_harmonic_mean_uses_dynamic_axis_names():
    axes = {"foo": 0.8, "bar": 0.2, "baz": 0.6}
    weights = {"foo": 0.4, "bar": 0.3, "baz": 0.3}
    composite = weighted_harmonic_mean(
        axes, weights, axis_names=("foo", "bar", "baz")
    )
    # Harmonic mean of biased axes — should be < arithmetic mean (0.55).
    assert 0.0 < composite < 0.55


def test_harmonic_mean_default_axis_names_is_legacy():
    axes = {k: 0.5 for k in AXIS_NAMES}
    weights = {k: 0.2 for k in AXIS_NAMES}
    out = weighted_harmonic_mean(axes, weights)
    assert out == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# LLMEvaluator: legacy path unchanged
# ---------------------------------------------------------------------------


def test_evaluator_without_axes_uses_legacy_5():
    ev = LLMEvaluator(model="dummy")
    # _axis_names defaults to AXIS_NAMES (5 generic axes).
    assert ev._axis_names == AXIS_NAMES
    sys_prompt = ev._build_system_prompt()
    # Legacy BASE_SYSTEM contains the canonical wording.
    assert "EXACTLY these five keys" in sys_prompt
    for k in AXIS_NAMES:
        assert k in sys_prompt


# ---------------------------------------------------------------------------
# LLMEvaluator: dynamic-axes path
# ---------------------------------------------------------------------------


def test_evaluator_with_dynamic_axes_lists_them_in_prompt():
    rubric = {"id": "sc", "domain": "HPC / Systems",
              "score_dimensions": [{"name": "scalability_evaluation", "description": "scaling"}]}
    idea_data = {"ideas": [{"experiment_plan": "Pmax/Bmax measurement.\nbaseline against MKL.\n"}]}
    axes = build_axes_for_run(rubric=rubric, idea_data=idea_data)
    ev = LLMEvaluator(model="dummy", axes=axes)
    sys_prompt = ev._build_system_prompt()
    # Legacy 5-axis preamble is replaced.
    assert "EXACTLY these five keys" not in sys_prompt
    # New axes enumerated.
    assert "scalability_evaluation" in sys_prompt
    assert "model_calibration_present" in sys_prompt
    assert "baseline_comparison_present" in sys_prompt
    # Provenance annotations present in weights line.
    assert "[generic]" in sys_prompt
    assert "[plan]" in sys_prompt
    assert "rubric:" in sys_prompt


def test_evaluator_dynamic_axes_have_self_axis_names_correct():
    axes = build_axes_for_run()  # generic only
    ev = LLMEvaluator(model="dummy", axes=axes)
    assert ev._axis_names == tuple(a.name for a in axes)
    # Generic floor must be a SUPERSET of the legacy 5-axis tuple. Phase 6
    # adds `claim_implementation_alignment` (low-weight, cross-domain) on
    # top of the original five, but those five must remain present so
    # legacy callers / score history calibration keep working.
    assert set(AXIS_NAMES).issubset(set(ev._axis_names))


# ---------------------------------------------------------------------------
# Phase 3 wiring (core.py path): checkpoint_dir + rubric
# ---------------------------------------------------------------------------


def test_evaluator_with_checkpoint_and_rubric_builds_dynamic_axes(tmp_path):
    rubric = {
        "id": "sc",
        "score_dimensions": [
            {"name": "scalability_evaluation", "description": "scaling rigor"},
        ],
    }
    ev = LLMEvaluator(model="dummy", checkpoint_dir=str(tmp_path), rubric=rubric)
    # Generic + rubric-derived (no plan yet, idea.json absent).
    names = set(ev._axis_names)
    assert "scalability_evaluation" in names
    for k in AXIS_NAMES:
        assert k in names
    # Plan-derived axes not yet present.
    assert "model_calibration_present" not in names


def test_evaluator_picks_up_idea_json_when_it_appears(tmp_path):
    """Root node typically writes idea.json after the evaluator was
    constructed. ``_refresh_axes_if_needed`` must pick that up on the
    next evaluate() call without restarting."""
    import json as _json
    rubric = {"id": "sc", "domain": "HPC / Systems",
              "score_dimensions": [{"name": "scalability_evaluation", "description": "..."}]}
    ev = LLMEvaluator(model="dummy", checkpoint_dir=str(tmp_path), rubric=rubric)
    # Initial axes: generic + rubric only.
    assert "model_calibration_present" not in ev._axis_names

    # Simulate generate_ideas writing idea.json mid-run. Sleep briefly to
    # ensure the new file's mtime differs from the original (refresh is
    # cached on mtime equality).
    import time as _time
    _time.sleep(0.01)
    (tmp_path / "idea.json").write_text(_json.dumps({
        "ideas": [{
            "title": "ENVELOPE",
            "experiment_plan": "1) baseline\n4) measure Pmax via STREAM\n6) compare against MKL",
        }]
    }))
    ev._refresh_axes_if_needed()
    # Plan-derived axes now present.
    assert "model_calibration_present" in ev._axis_names
    assert "baseline_comparison_present" in ev._axis_names
    # Rubric-derived still present.
    assert "scalability_evaluation" in ev._axis_names


def test_evaluator_refresh_caches_on_unchanged_mtime(tmp_path):
    """Calling _refresh_axes_if_needed twice without changing idea.json
    must not rebuild (mtime cache)."""
    import json as _json
    (tmp_path / "idea.json").write_text(_json.dumps({"ideas": [{"experiment_plan": "STREAM"}]}))
    ev = LLMEvaluator(model="dummy", checkpoint_dir=str(tmp_path))
    first = ev._dynamic_axes
    ev._refresh_axes_if_needed()
    second = ev._dynamic_axes
    # Same instance — list not reassigned because mtime unchanged.
    assert first is second


def test_evaluator_legacy_path_unchanged_when_no_rubric_no_axes_no_ckpt():
    """Bare LLMEvaluator() must keep the legacy 5-axis behaviour."""
    ev = LLMEvaluator(model="dummy")
    assert ev._dynamic_axes is None
    assert ev._axis_names == AXIS_NAMES


def test_evaluator_no_idea_json_yet_uses_rubric_only_floor(tmp_path):
    rubric = {"id": "sc", "score_dimensions": [{"name": "scalability_evaluation", "description": "..."}]}
    # Empty checkpoint dir, no idea.json.
    ev = LLMEvaluator(model="dummy", checkpoint_dir=str(tmp_path), rubric=rubric)
    names = set(ev._axis_names)
    # Generic floor + rubric, but NO plan-derived (because no idea.json).
    assert "scalability_evaluation" in names
    assert "model_calibration_present" not in names


# ---------------------------------------------------------------------------
# lineage decisions: weight balance — generic floor must dominate even when a
# rubric declares many score_dimensions.
# ---------------------------------------------------------------------------


def test_generic_floor_total_weight_exceeds_rubric_total():
    """Sum of generic axis weights must dominate the sum of rubric axes
    so switching rubric never tips the composite away from the generic
    'is this real research?' baseline."""
    rubric = {
        "id": "neurips",
        "domain": "ML / AI",
        "score_dimensions": [
            {"name": "originality", "description": "..."},
            {"name": "quality", "description": "..."},
            {"name": "clarity", "description": "..."},
            {"name": "significance", "description": "..."},
            {"name": "soundness", "description": "..."},
            {"name": "presentation", "description": "..."},
            {"name": "contribution", "description": "..."},
        ],
    }
    axes = build_axes_for_run(rubric=rubric)
    generic_w = sum(a.weight for a in axes if a.source == "generic")
    rubric_w = sum(a.weight for a in axes if a.source.startswith("rubric:"))
    # Generic floor (5 axes × 0.2 = 1.0) must exceed rubric (≤ 7 × 0.05 = 0.35).
    assert generic_w > rubric_w, (
        f"generic={generic_w} should dominate rubric={rubric_w}"
    )
    assert generic_w >= 1.0


# ---------------------------------------------------------------------------
# Phase 6 #3 / #5: cross-domain extensions
# ---------------------------------------------------------------------------


def test_policy_variants_cross_domain():
    """`policy_variants_compared` is a cross-domain axis — fires for
    HPC, ML, theory, HCI runs alike when the plan calls for variant
    head-to-head comparison."""
    hpc = "Compare temporal vs non-temporal store policy variants head-to-head."
    ml = "We run a configuration sweep over Adam, SGD, AdamW."
    theory = "Variant comparison: greedy vs DP for the matching subroutine."
    hci = "Head-to-head policy comparison of two UI variants."
    for plan, label in [(hpc, "hpc"), (ml, "ml"), (theory, "theory"), (hci, "hci")]:
        names = [a.name for a in plan_to_axes(plan)]
        assert "policy_variants_compared" in names, f"missed for {label}"


def test_policy_variants_distinct_from_ablation():
    plan_ablation_only = "We run an ablation removing component X."
    plan_variants_only = "We compare the temporal vs non-temporal variants head-to-head."
    a = [x.name for x in plan_to_axes(plan_ablation_only)]
    v = [x.name for x in plan_to_axes(plan_variants_only)]
    assert "ablation_present" in a
    assert "policy_variants_compared" not in a
    assert "policy_variants_compared" in v


def test_claim_implementation_alignment_in_generic_floor():
    """`claim_implementation_alignment` is in the generic floor so it
    applies to every run regardless of rubric/plan."""
    axes = build_axes_for_run()
    names = {a.name: a for a in axes}
    assert "claim_implementation_alignment" in names
    # Low weight (0.05) so it never dominates the 0.2 generic five.
    assert names["claim_implementation_alignment"].weight < 0.1
    assert names["claim_implementation_alignment"].source == "generic"


def test_claim_implementation_alignment_stays_below_generic_dominants():
    axes = build_axes_for_run()
    dominants = [a for a in axes
                 if a.source == "generic" and a.name != "claim_implementation_alignment"]
    cia = next(a for a in axes if a.name == "claim_implementation_alignment")
    assert cia.weight < min(d.weight for d in dominants)


def test_per_axis_weight_caps_prevent_rubric_dominance():
    """No single rubric-derived axis weight may exceed any single
    generic axis weight, so a rubric cannot tilt the composite via
    a few high-weight dimensions."""
    rubric = {"id": "sc", "score_dimensions": [
        {"name": "scalability_evaluation", "description": "..."},
        {"name": "reproducibility", "description": "..."},
    ]}
    axes = build_axes_for_run(rubric=rubric)
    max_generic = max(a.weight for a in axes if a.source == "generic")
    max_rubric = max(
        (a.weight for a in axes if a.source.startswith("rubric:")),
        default=0,
    )
    assert max_rubric <= max_generic
