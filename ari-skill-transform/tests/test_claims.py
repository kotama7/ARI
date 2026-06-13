"""Tests for the Research Contract claim layer (Story2Proposal Phase A).

Covers deterministic claim/numeric-assertion generation, operand resolution,
formula correctness, and direction handling. Pure unit tests over synthetic
node dicts — no LLM, no disk, no ari-core dependency.
"""
from __future__ import annotations

from src.claims import (
    FORMULAS,
    build_science_claims,
    recompute,
    _resolve_metric,
    _autodetect_primary_metric,
)


# ── formula registry ────────────────────────────────────────────────────────

def test_formula_semantics():
    assert recompute("identity", {"value": 42.0}) == 42.0
    assert recompute("relative_speedup", {"baseline": 10.0, "proposed": 5.0}) == 2.0
    assert recompute("relative_gain", {"baseline": 5.0, "proposed": 10.0}) == 2.0
    assert recompute("relative_reduction_percent", {"baseline": 10.0, "proposed": 8.0}) == 20.0
    assert recompute("relative_increase_percent", {"baseline": 8.0, "proposed": 10.0}) == 25.0
    assert recompute("absolute_difference", {"baseline": 8.0, "proposed": 10.0}) == 2.0


def test_recompute_guards():
    assert recompute("relative_speedup", {"baseline": 10.0, "proposed": 0.0}) is None
    assert recompute("relative_reduction_percent", {"baseline": 0.0, "proposed": 1.0}) is None
    assert recompute("unknown_formula", {"value": 1.0}) is None
    assert recompute("identity", {}) is None  # missing operand


# ── metric resolution ───────────────────────────────────────────────────────

def test_resolve_metric_prefers_results_measurements():
    node = {"id": "n1", "metrics": {"GFlops": 99.0}}
    results = {"measurements": {"GFlops": 26.8}, "params": {"M": 120000}}
    val, path = _resolve_metric(node, results, "GFlops")
    assert val == 26.8
    assert path == "measurements.GFlops"


def test_resolve_metric_falls_back_to_node_metrics():
    node = {"id": "n1", "metrics": {"GFlops": 99.0}}
    val, path = _resolve_metric(node, {}, "GFlops")
    assert val == 99.0
    assert path == "metrics.GFlops"


def test_resolve_metric_scores_path():
    node = {"id": "n1", "metrics": {}}
    results = {"scores": {"accuracy": 0.91}}
    val, path = _resolve_metric(node, results, "accuracy")
    assert val == 0.91
    assert path == "scores.accuracy"


def test_resolve_metric_missing():
    val, path = _resolve_metric({"id": "n1", "metrics": {}}, {}, "nope")
    assert val is None and path == ""


def test_autodetect_skips_input_params_and_reserved():
    good = [
        {"id": "n1", "metrics": {"GFlops": 10.0, "_scientific_score": 0.5}},
        {"id": "n2", "metrics": {"GFlops": 20.0}},
    ]
    typed = {"n1": {"params": {"M": 1}, "measurements": {"GFlops": 10.0}}}
    pm = _autodetect_primary_metric(good, typed)
    assert pm == "GFlops"


# ── claim generation: higher-is-better ──────────────────────────────────────

def test_higher_is_better_absolute_and_comparison():
    good = [
        {"id": "n_base", "label": "draft", "metrics": {"GFlops": 100.0}},
        {"id": "n_prop", "label": "improve", "metrics": {"GFlops": 150.0}},
    ]
    out = build_science_claims(good, {}, primary_metric="GFlops", higher_is_better=True)
    claims = out["claims"]
    assert len(claims) == 2  # absolute + comparison

    absolute = claims[0]
    assert absolute["id"] == "C1"
    assert absolute["status"] == "draft"
    assert absolute["supported_by"]["nodes"] == ["n_prop"]  # best
    assert absolute["supported_by"]["figures"] == []  # late-bind
    na = absolute["numeric_assertions"][0]
    assert na["formula"] == "identity"
    assert na["value"] == 150.0
    assert na["operands"]["value"]["node_id"] == "n_prop"
    assert na["operands"]["value"]["metric_path"] == "metrics.GFlops"
    assert "environment" in na["operands"]["value"]  # provenance tag

    comp = claims[1]
    cna = comp["numeric_assertions"][0]
    assert cna["formula"] == "relative_increase_percent"
    assert cna["value"] == 50.0  # (150-100)/100*100
    assert cna["operands"]["baseline"]["node_id"] == "n_base"
    assert cna["operands"]["proposed"]["node_id"] == "n_prop"
    assert set(comp["supported_by"]["nodes"]) == {"n_prop", "n_base"}


# ── claim generation: lower-is-better ───────────────────────────────────────

def test_lower_is_better_uses_reduction():
    good = [
        {"id": "n_base", "metrics": {"runtime": 10.0}},
        {"id": "n_prop", "metrics": {"runtime": 8.0}},
    ]
    out = build_science_claims(good, {}, primary_metric="runtime", higher_is_better=False)
    claims = out["claims"]
    # absolute claim references the best (min runtime) node
    assert claims[0]["supported_by"]["nodes"] == ["n_prop"]
    assert claims[0]["numeric_assertions"][0]["value"] == 8.0
    comp = claims[1]["numeric_assertions"][0]
    assert comp["formula"] == "relative_reduction_percent"
    assert comp["value"] == 20.0  # (10-8)/10*100
    assert comp["operands"]["baseline"]["node_id"] == "n_base"   # worst = max runtime
    assert comp["operands"]["proposed"]["node_id"] == "n_prop"   # best = min runtime


def test_single_node_only_absolute_claim():
    good = [{"id": "n1", "metrics": {"GFlops": 173.25}}]
    out = build_science_claims(good, {}, primary_metric="GFlops", higher_is_better=True)
    assert len(out["claims"]) == 1
    assert out["claims"][0]["numeric_assertions"][0]["formula"] == "identity"


def test_flattened_numeric_assertions_have_claim_id():
    good = [
        {"id": "a", "metrics": {"x": 1.0}},
        {"id": "b", "metrics": {"x": 2.0}},
    ]
    out = build_science_claims(good, {}, primary_metric="x", higher_is_better=True)
    flat = out["numeric_assertions"]
    assert len(flat) == 2
    assert all("claim_id" in na for na in flat)
    assert {na["claim_id"] for na in flat} == {"C1", "C2"}
    # ids are unique across claims
    assert {na["id"] for na in flat} == {"NC1", "NC2"}


def test_no_resolvable_metric_returns_empty():
    good = [{"id": "n1", "metrics": {"nonnumeric": "x"}}]
    out = build_science_claims(good, {}, primary_metric="missing", higher_is_better=True)
    assert out == {"claims": [], "numeric_assertions": []}


def test_results_json_operands_are_deterministic():
    """Same inputs -> identical operands (acceptance: deterministic operand refs)."""
    good = [
        {"id": "n1", "metrics": {"GFlops": 10.0}},
        {"id": "n2", "metrics": {"GFlops": 20.0}},
    ]
    typed = {
        "n1": {"measurements": {"GFlops": 10.0}},
        "n2": {"measurements": {"GFlops": 20.0}},
    }
    a = build_science_claims(good, typed, "GFlops", True)
    b = build_science_claims(good, typed, "GFlops", True)
    assert a == b
    assert a["claims"][0]["numeric_assertions"][0]["operands"]["value"]["metric_path"] == "measurements.GFlops"


def test_prose_primary_metric_falls_back_to_autodetect():
    """A prose primary_metric (idea-skill emits sentences, not keys) must fall
    back to the most-covered measurement key instead of yielding 0 claims."""
    good = [
        {"id": "a", "metrics": {"GFlops/s": 100.0}},
        {"id": "b", "metrics": {"GFlops/s": 150.0}},
    ]
    prose = ("Effective GFLOP/s averaged across RHS widths K in {8,16,32,64}, "
             "geometric mean speedup over a tuned baseline CSR-SpMM, with roofline ratio")
    out = build_science_claims(good, {}, primary_metric=prose, higher_is_better=True)
    assert len(out["claims"]) >= 1
    assert out["claims"][0]["numeric_assertions"][0]["metric"] == "GFlops/s"


def test_operands_tagged_with_environment():
    good = [{"id": "a", "metrics": {"x": 1.0}}, {"id": "b", "metrics": {"x": 2.0}}]
    env = {"a": {"executor": "local", "cpu_model": "Intel", "arch": "x86_64"},
           "b": {"executor": "slurm", "cpu_model": "cpuX", "arch": "aarch64"}}
    out = build_science_claims(good, {}, "x", True, node_env=env, comparison_scope="any")
    c1 = out["claims"][0]["numeric_assertions"][0]
    assert c1["operands"]["value"]["environment"]["cpu_model"] == "cpuX"  # best=b


def test_any_scope_generates_cross_env_comparison_tagged():
    """Cross-architecture study (scope=any): the cross-host comparison IS built,
    and flagged cross_environment=True (transparency, not prohibition)."""
    good = [{"id": "a", "metrics": {"x": 6.0}}, {"id": "b", "metrics": {"x": 81.0}}]
    env = {"a": {"executor": "local", "cpu_model": "Intel", "arch": "x86_64"},
           "b": {"executor": "slurm", "cpu_model": "cpuX", "arch": "aarch64"}}
    out = build_science_claims(good, {}, "x", True, node_env=env, comparison_scope="any")
    assert len(out["claims"]) == 2  # C1 + cross-env C2
    c2 = out["claims"][1]["numeric_assertions"][0]
    assert c2["cross_environment"] is True
    assert "across different execution environments" in out["claims"][1]["text"]


def test_same_environment_scope_skips_cross_env_comparison():
    """Single-architecture study (scope=same_environment): a cross-host pair must
    NOT become a comparison claim — only the absolute claim remains."""
    good = [{"id": "a", "metrics": {"x": 6.0}}, {"id": "b", "metrics": {"x": 81.0}}]
    env = {"a": {"executor": "local", "cpu_model": "Intel", "arch": "x86_64"},
           "b": {"executor": "slurm", "cpu_model": "cpuX", "arch": "aarch64"}}
    out = build_science_claims(good, {}, "x", True, node_env=env, comparison_scope="same_environment")
    assert len(out["claims"]) == 1  # only C1 absolute; no spurious cross-host C2
    assert out["claims"][0]["numeric_assertions"][0]["formula"] == "identity"


def test_same_environment_scope_keeps_same_env_comparison():
    """scope=same_environment still produces a comparison when a same-env peer exists."""
    good = [{"id": "a", "metrics": {"x": 60.0}},
            {"id": "b", "metrics": {"x": 81.0}},
            {"id": "c", "metrics": {"x": 6.0}}]
    env = {"a": {"executor": "slurm", "cpu_model": "cpuX", "arch": "aarch64"},
           "b": {"executor": "slurm", "cpu_model": "cpuX", "arch": "aarch64"},
           "c": {"executor": "local", "cpu_model": "Intel", "arch": "x86_64"}}
    out = build_science_claims(good, {}, "x", True, node_env=env, comparison_scope="same_environment")
    assert len(out["claims"]) == 2  # absolute + same-env (cpuX b vs a) comparison
    c2 = out["claims"][1]["numeric_assertions"][0]
    assert c2["cross_environment"] is False
    # baseline must be the same-env cpuX node 'a', NOT the lower Intel node 'c'
    assert c2["operands"]["baseline"]["node_id"] == "a"


def test_all_formulas_registered():
    expected = {
        "identity", "relative_speedup", "relative_gain",
        "relative_improvement_percent", "relative_increase_percent",
        "relative_reduction_percent", "absolute_difference", "ratio_percent",
    }
    assert set(FORMULAS) == expected


def test_ratio_percent_formula():
    assert round(recompute("ratio_percent", {"baseline": 114.0, "proposed": 81.55}), 1) == 71.5
    assert recompute("ratio_percent", {"baseline": 0.0, "proposed": 1.0}) is None
