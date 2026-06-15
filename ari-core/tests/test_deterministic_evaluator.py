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


def test_scientific_score_default_target_is_parallel_ceiling():
    # Default TARGET = 16 (the OpenMP thread budget) so the score spans the
    # achievable range instead of saturating at a low 4x bar.
    assert scientific_score(16.0) == 1.0
    assert abs(scientific_score(8.0) - 0.5) < 1e-9       # mid-range, not capped
    assert abs(scientific_score(4.0) - 0.25) < 1e-9      # was 1.0 under old 4x


def test_scientific_score_log_scale_spreads_multiplicative_rungs():
    # GEMM (log scale, TARGET=256): multiplicative rungs map to even spacing;
    # no gain over the naive baseline (g<=1) scores 0; cap at 1.0.
    import math
    assert scientific_score(1.0, 256, "log") == 0.0
    assert scientific_score(256.0, 256, "log") == 1.0
    assert scientific_score(500.0, 256, "log") == 1.0   # capped
    assert abs(scientific_score(16.0, 256, "log") - 0.5) < 1e-9   # sqrt(256)=16
    # intermediate rung 21x is clearly between 0 and 1 (not crushed like linear)
    s = scientific_score(21.0, 256, "log")
    assert 0.4 < s < 0.7


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
    ev = DeterministicEvaluator(measure_fn=lambda wd: ok, target_speedup=4.0)
    assert ev.evaluate_sync("g", [], "s")["metrics"]["_scientific_score"] == 1.0

    def boom(_wd):
        raise RuntimeError("boom")

    bad = DeterministicEvaluator(measure_fn=boom).evaluate_sync("g", [], "s")
    assert bad["metrics"]["_scientific_score"] == 0.0 and not bad["valid"]


def test_default_measure_without_candidate_is_graceful(monkeypatch):
    # No candidate kernel in work_dir -> measure_node fails the candidate step
    # and the evaluator returns a graceful invalid (score 0), never raising.
    monkeypatch.setenv("ARI_WORK_DIR", "/nonexistent_handoff_dir")
    out = DeterministicEvaluator().evaluate_sync("g", [], "s")
    assert out["metrics"]["_scientific_score"] == 0.0
    assert out["valid"] is False
