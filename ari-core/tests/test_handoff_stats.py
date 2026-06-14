"""Tests for the handoff-study analysis statistics core (Stage 4)."""
import math

from ari.evaluator.handoff_stats import (
    bootstrap_ci,
    geomean,
    holm_adjust,
    summarize_arm,
    tost_equivalence,
)


def test_geomean():
    assert abs(geomean([2.0, 8.0]) - 4.0) < 1e-9
    assert geomean([]) == 0.0
    assert geomean([0.0, -1.0]) == 0.0


def test_bootstrap_ci_no_variance():
    point, lo, hi = bootstrap_ci([4.0] * 8, statistic=geomean)
    assert abs(point - 4.0) < 1e-9 and abs(lo - 4.0) < 1e-9 and abs(hi - 4.0) < 1e-9


def test_bootstrap_ci_brackets_point():
    point, lo, hi = bootstrap_ci([1.5, 2.0, 2.5, 3.0, 2.2, 1.8], statistic=geomean, seed=1)
    assert lo <= point <= hi
    assert math.isfinite(lo) and math.isfinite(hi)


def test_tost_equivalent_when_close_within_margin():
    a = [0.40, 0.41, 0.39, 0.40, 0.405, 0.395]
    b = [0.40, 0.40, 0.41, 0.39, 0.400, 0.405]
    out = tost_equivalence(a, b, margin=math.log(1.05))
    assert out["equivalent"] is True
    assert abs(out["mean_diff"]) < math.log(1.05)


def test_tost_not_equivalent_when_far_apart():
    a = [0.40, 0.41, 0.39, 0.40]
    b = [0.90, 0.91, 0.89, 0.92]  # ~0.5 log apart >> margin
    out = tost_equivalence(a, b, margin=math.log(1.05))
    assert out["equivalent"] is False


def test_tost_needs_two_per_arm():
    assert tost_equivalence([0.4], [0.4], margin=0.05)["equivalent"] is False


def test_holm_adjust_known():
    adj = holm_adjust([0.01, 0.02, 0.5])
    assert abs(adj[0] - 0.03) < 1e-9
    assert abs(adj[1] - 0.04) < 1e-9
    assert abs(adj[2] - 0.5) < 1e-9
    # monotone non-decreasing in p-order, capped at 1.0
    assert all(0.0 <= x <= 1.0 for x in holm_adjust([0.6, 0.7, 0.8]))


def test_summarize_arm():
    s = summarize_arm([2.0, 2.0, 2.0, 2.0])
    assert s["n_runs"] == 4 and abs(s["geomean"] - 2.0) < 1e-9
    assert s["ci_lo"] <= s["geomean"] <= s["ci_hi"]
