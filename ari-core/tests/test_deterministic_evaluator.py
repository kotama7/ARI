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


def test_scientific_score_returns_native_speedup():
    assert scientific_score(4.0, 4.0) == 4.0
    assert scientific_score(2.0, 4.0) == 2.0
    assert scientific_score(8.0, 4.0) == 8.0  # not capped at target
    assert scientific_score(0.0, 4.0) == 0.0
    assert scientific_score(None, 4.0) == 0.0


def test_scientific_score_ignores_target_for_bfts_ranking():
    # BFTS compares nodes within a task; arbitrary target ceilings must not
    # collapse high-performing candidates into the same score.
    assert scientific_score(16.0) == 16.0
    assert scientific_score(8.0) == 8.0
    assert scientific_score(4.0) == 4.0


def test_scientific_score_scale_argument_is_compatibility_only():
    assert scientific_score(1.0, 256, "log") == 1.0
    assert scientific_score(256.0, 256, "log") == 256.0
    assert scientific_score(500.0, 256, "log") == 500.0


def test_gamma():
    assert gamma(10, 2 ** -53) > 0.0
    assert math.isinf(gamma(2, 1.0))  # k*u >= 1 -> vacuous bound


def test_score_all_valid_geomean_to_native_ranking_score():
    ev = DeterministicEvaluator(target_speedup=4.0)
    out = ev._score({"compile_ok": True, "families": {
        "uniform": {"speedup": 2.0, "valid": True},
        "banded": {"speedup": 8.0, "valid": True},
    }})
    assert out["metrics"]["_scientific_score"] == 4.0
    assert abs(out["metrics"]["valid_geomean_speedup"] - 4.0) < 1e-9
    assert out["has_real_data"] and out["valid"]
    assert out["metrics"]["speedup_uniform"] == 2.0


def test_score_any_invalid_family_zeroes_node():
    ev = DeterministicEvaluator(target_speedup=4.0)
    out = ev._score({"compile_ok": True, "families": {
        "uniform": {"speedup": 9.0, "valid": True},
        "banded": {
            "speedup": 0.0,
            "valid": False,
            "max_relative_error": 0.25,
            "n_clamped": 0,
        },
    }})
    assert out["metrics"]["_scientific_score"] == 0.0  # no zero mixed into geomean
    assert not out["valid"] and not out["has_real_data"]
    assert out["evaluation_cases"]["banded"] == {
        "valid": False,
        "measurements": {
            "speedup": 0.0,
            "max_relative_error": 0.25,
            "n_clamped": 0,
        },
    }
    assert out["reason"].startswith("measurement invalid:")
    assert "banded" in out["reason"]
    assert out["reason"] != "ok"


def test_score_persists_harness_defined_case_measurements():
    out = DeterministicEvaluator(target_speedup=4.0)._score({
        "compile_ok": True,
        "reason": "ok",
        "families": {
            "square": {
                "speedup": 3.0,
                "valid": True,
                "max_abs_error": 1.25e-14,
                "n_clamped": 2,
            },
        },
    })
    assert out["valid"] is True
    assert out["reason"] == "ok"
    assert out["evaluation_cases"]["square"] == {
        "valid": True,
        "measurements": {
            "speedup": 3.0,
            "max_abs_error": 1.25e-14,
            "n_clamped": 2,
        },
    }


def test_valid_but_unmeasurable_family_zeroes_node():
    """A valid family with non-finite/non-positive speedup must not vanish from
    the geomean and let the node score on only the surviving families."""
    ev = DeterministicEvaluator(target_speedup=4.0)
    for bad_speedup in (0.0, -1.0, float("nan"), float("inf")):
        out = ev._score({"compile_ok": True, "families": {
            "uniform": {"speedup": 8.0, "valid": True},
            "banded": {"speedup": bad_speedup, "valid": True},
        }})
        assert out["metrics"]["_scientific_score"] == 0.0
        assert out["metrics"]["valid_geomean_speedup"] == 0.0
        assert out["valid"] is False and out["has_real_data"] is False


def test_score_axis_is_clamped_and_compile_fail_scores_zero():
    ev = DeterministicEvaluator()

    high = ev._score({"compile_ok": True, "score": 2.5})
    assert high["metrics"]["_scientific_score"] == 1.0
    assert high["valid"] is True

    neg = ev._score({"compile_ok": True, "score": -0.5})
    assert neg["metrics"]["_scientific_score"] == 0.0

    nan = ev._score({"compile_ok": True, "score": float("nan")})
    assert nan["metrics"]["_scientific_score"] == 0.0

    failed = ev._score({"compile_ok": False, "score": 0.9})
    assert failed["metrics"]["_scientific_score"] == 0.0
    assert failed["valid"] is False and failed["has_real_data"] is False


def test_invalid_candidate_still_carries_computed_metrics():
    """An INVALID candidate is still SCORED: ``has_real_data`` is False, but
    ``metrics`` carries the computed ``valid_geomean_speedup: 0.0`` (plus the
    per-family speedups).

    The max-steps fallback in ari.agent.loop relies on exactly this: it records
    these metrics before ``mark_failed`` so an exhausted node whose candidate ran
    but was invalid reads as "produced an invalid candidate" (0.0) rather than
    "produced nothing" (null) — symmetric with the finish path, which records the
    evaluator's metrics regardless of validity. If ``metrics`` were dropped for
    invalid candidates, that fallback would have nothing to record.
    """
    out = DeterministicEvaluator(target_speedup=4.0)._score({
        "compile_ok": True,
        "families": {"uniform": {"speedup": 9.0, "valid": True},
                     "banded": {"speedup": 0.0, "valid": False}},
    })
    assert out["has_real_data"] is False            # invalid -> not "real data"
    assert out["metrics"]["valid_geomean_speedup"] == 0.0   # ...but SCORED as 0.0
    assert out["metrics"]["speedup_uniform"] == 9.0         # per-family kept
    assert out["metrics"], "metrics must never be empty for a candidate that ran"


def test_compile_fail_still_carries_computed_metrics():
    """Same contract when the candidate did not even compile."""
    out = DeterministicEvaluator()._score({"compile_ok": False, "families": {}})
    assert out["valid"] is False and out["has_real_data"] is False
    assert out["metrics"]["valid_geomean_speedup"] == 0.0


def test_score_compile_fail_is_invalid():
    assert DeterministicEvaluator()._score(
        {"compile_ok": False, "families": {}})["valid"] is False


def test_evaluate_sync_injected_and_graceful_on_error():
    ok = {"compile_ok": True, "families": {"u": {"speedup": 4.0, "valid": True}}}
    ev = DeterministicEvaluator(measure_fn=lambda wd: ok, target_speedup=4.0)
    assert ev.evaluate_sync("g", [], "s")["metrics"]["_scientific_score"] == 4.0

    def boom(_wd):
        raise RuntimeError("boom")

    bad = DeterministicEvaluator(measure_fn=boom).evaluate_sync("g", [], "s")
    assert bad["metrics"]["_scientific_score"] == 0.0 and not bad["valid"]
    assert bad["evaluation_status"] == "infrastructure_error"


def test_raw_repetitions_and_effective_flags_are_audit_only():
    out = DeterministicEvaluator(target_speedup=1.0)._score({
        "compile_ok": True,
        "evaluation_status": "valid",
        "candidate_cflags": ["-O3", "-mcpu=a64fx"],
        "rejected_cflags": ["-lblas"],
        "families": {
            "case": {
                "speedup": 2.0,
                "valid": True,
                "n_requested_repetitions": 1,
                "n_accepted_repetitions": 1,
                "repetitions": [{
                    "index": 0,
                    "status": "accepted",
                    "valid": True,
                    "measurements": {
                        "candidate_internal_seconds": 1.0,
                        "baseline_internal_seconds": 2.0,
                    },
                }],
            },
        },
    })
    assert "repetitions" not in out["evaluation_cases"]["case"]["measurements"]
    audit = out["measurement_audit"]
    assert audit["effective_candidate_compile_flags"] == ["-O3", "-mcpu=a64fx"]
    assert audit["rejected_candidate_compile_flags"] == ["-lblas"]
    assert audit["cases"]["case"][0]["status"] == "accepted"


def test_nonfinite_measurement_is_strict_json_and_typed_invalid():
    out = DeterministicEvaluator(task="gemm")._score({
        "compile_ok": True,
        "evaluation_status": "valid",
        "families": {
            "case": {
                "speedup": float("nan"),
                "valid": True,
                "repetitions": [{
                    "index": 0,
                    "status": "unverifiable_timing",
                    "valid": False,
                    "measurements": {"candidate_internal_seconds": float("nan")},
                }],
            },
        },
    })
    assert out["valid"] is False
    assert out["evaluation_status"] == "measurement_invalid"
    assert (
        out["measurement_audit"]["cases"]["case"][0]["measurements"]
        ["candidate_internal_seconds"] is None
    )


def test_default_measure_without_candidate_is_graceful(monkeypatch):
    # No candidate kernel in work_dir -> measure_node fails the candidate step
    # and the evaluator returns a graceful invalid (score 0), never raising.
    monkeypatch.setenv("ARI_WORK_DIR", "/nonexistent_handoff_dir")
    out = DeterministicEvaluator().evaluate_sync("g", [], "s")
    assert out["metrics"]["_scientific_score"] == 0.0
    assert out["valid"] is False
