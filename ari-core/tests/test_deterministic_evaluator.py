"""Tests for the handoff-study deterministic evaluator (B2): scoring contract.

The SpMM kernel compile/run/timing harness (B2b) is compute-node validated and
out of scope here; these tests cover the pure scoring contract that drives BFTS
selection via metrics["_scientific_score"].
"""
import math

from ari.evaluator.deterministic_evaluator import (
    DeterministicEvaluator,
    gamma,
    geomean,
    scientific_score,
)


def test_geomean():
    assert abs(geomean([2.0, 8.0]) - 4.0) < 1e-9
    assert geomean([]) == 0.0
    assert geomean([0.0, -1.0]) == 0.0  # non-positive filtered out


def test_scientific_score_prereg_target():
    assert scientific_score(4.0, 4.0) == 1.0
    assert abs(scientific_score(2.0, 4.0) - 0.5) < 1e-9
    assert scientific_score(8.0, 4.0) == 1.0  # capped at 1.0
    assert scientific_score(0.0, 4.0) == 0.0
    assert scientific_score(None, 4.0) == 0.0


def test_gamma():
    assert gamma(10, 2 ** -53) > 0.0
    assert math.isinf(gamma(2, 1.0))  # k*u >= 1 -> vacuous bound


def test_score_all_valid_geomean_to_unit_score():
    ev = DeterministicEvaluator(target_speedup=4.0)
    out = ev._score({"compile_ok": True, "families": {
        "uniform": {"speedup": 2.0, "valid": True},
        "banded": {"speedup": 8.0, "valid": True},
    }})
    assert out["metrics"]["_scientific_score"] == 1.0
    assert abs(out["metrics"]["valid_geomean_speedup"] - 4.0) < 1e-9
    assert out["has_real_data"] and out["valid"]
    assert out["metrics"]["speedup_uniform"] == 2.0


def test_score_any_invalid_family_zeroes_node():
    ev = DeterministicEvaluator(target_speedup=4.0)
    out = ev._score({"compile_ok": True, "families": {
        "uniform": {"speedup": 9.0, "valid": True},
        "banded": {"speedup": 0.0, "valid": False},
    }})
    assert out["metrics"]["_scientific_score"] == 0.0  # no zero mixed into geomean
    assert not out["valid"] and not out["has_real_data"]


def test_score_compile_fail_is_invalid():
    assert DeterministicEvaluator()._score(
        {"compile_ok": False, "families": {}})["valid"] is False


def test_evaluate_sync_injected_and_graceful_on_error():
    ok = {"compile_ok": True, "families": {"u": {"speedup": 4.0, "valid": True}}}
    ev = DeterministicEvaluator(measure_fn=lambda wd: ok)
    assert ev.evaluate_sync("g", [], "s")["metrics"]["_scientific_score"] == 1.0

    def boom(_wd):
        raise RuntimeError("boom")

    bad = DeterministicEvaluator(measure_fn=boom).evaluate_sync("g", [], "s")
    assert bad["metrics"]["_scientific_score"] == 0.0 and not bad["valid"]


def test_default_measure_absent_is_graceful():
    out = DeterministicEvaluator().evaluate_sync("g", [], "s")
    assert out["metrics"]["_scientific_score"] == 0.0
    assert "harness" in out["reason"].lower()
