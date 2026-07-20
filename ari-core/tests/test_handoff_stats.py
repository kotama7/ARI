"""Tests for the handoff-study analysis statistics core (Stage 4)."""
import math

from ari.evaluator.handoff_stats import (
    bootstrap_ci,
    geomean,
    holm_adjust,
    jonckheere_terpstra,
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


# ── Jonckheere–Terpstra ordered-alternative trend test (PRIMARY / 主検定) ──

def test_jt_perfect_increasing_is_significant():
    r = jonckheere_terpstra([[1, 2, 3], [4, 5, 6], [7, 8, 9]], n_perm=3000, seed=1)
    assert r["J"] == 27.0 and abs(r["J_mean"] - 13.5) < 1e-9  # maximal J
    assert r["p_perm"] < 0.01 and r["p_normal"] < 0.01


def test_jt_no_tie_variance_matches_classic_formula():
    r = jonckheere_terpstra([[1, 2, 3], [4, 5, 6], [7, 8, 9]], n_perm=1, seed=0)
    ns, N = [3, 3, 3], 9
    classic = (N * N * (2 * N + 3) - sum(n * n * (2 * n + 3) for n in ns)) / 72.0
    assert abs(r["J_var"] - classic) < 1e-9


def test_jt_is_rank_invariant_to_monotone_transform():
    raw = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    log = [[math.log(1 + x) for x in g] for g in raw]
    r1 = jonckheere_terpstra(raw, n_perm=3000, seed=7)
    r2 = jonckheere_terpstra(log, n_perm=3000, seed=7)
    assert r1["J"] == r2["J"] and r1["p_perm"] == r2["p_perm"]


def test_jt_decreasing_data_not_significant_for_increasing_Ha():
    r = jonckheere_terpstra([[7, 8, 9], [4, 5, 6], [1, 2, 3]], n_perm=3000, seed=2)
    assert r["J"] == 0.0 and r["p_perm"] > 0.9


def test_jt_handles_ties_including_zero_invalid_runs():
    # invalid runs score 0 -> many ties; must not crash and stays sane in [0,1].
    r = jonckheere_terpstra([[0, 0, 0, 2.0], [0, 0, 1.0, 3.0], [0, 1.5, 2.0, 4.0]],
                            n_perm=3000, seed=3)
    assert 0.0 <= r["p_perm"] <= 1.0 and r["J_var"] > 0.0


def test_jt_needs_two_nonempty_groups():
    r = jonckheere_terpstra([[1, 2, 3], [], []], n_perm=100, seed=0)
    assert math.isnan(r["p_value"]) and "reason" in r
