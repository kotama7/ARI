"""Tests for the handoff-study analysis statistics core (Stage 4)."""
import math

from ari.evaluator.handoff_stats import (
    bootstrap_ci,
    bootstrap_difference_ci,
    geomean,
    holm_adjust,
    jonckheere_terpstra,
    paired_bootstrap_difference_ci,
    paired_permutation_test,
    summarize_arm,
    two_sample_permutation_test,
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


def test_two_sided_permutation_and_difference_ci():
    a = [5.0, 6.0, 7.0, 8.0]
    b = [1.0, 2.0, 3.0, 4.0]
    out = two_sample_permutation_test(a, b, n_perm=5000, seed=2)
    assert out["alternative"] == "two-sided"
    assert out["mean_diff"] == 4.0
    assert out["p_value"] < 0.05
    point, lo, hi = bootstrap_difference_ci(a, b, n_boot=1000, seed=2)
    assert point == 4.0 and lo <= point <= hi


def test_paired_sign_flip_and_seed_block_bootstrap():
    control = [1.0, 4.0, 2.0, 8.0, 3.0, 7.0, 5.0, 6.0]
    treatment = [x + 2.0 for x in control]
    out = paired_permutation_test(
        treatment, control, n_perm=10000, seed=2)
    assert out["alternative"] == "two-sided"
    assert out["method"] == "paired sign-flip permutation"
    assert out["mean_diff"] == 2.0
    assert out["n_pairs"] == 8
    assert out["p_value"] < 0.02
    point, lo, hi = paired_bootstrap_difference_ci(
        treatment, control, n_boot=1000, seed=2)
    assert point == 2.0 and lo == 2.0 and hi == 2.0


def test_paired_statistics_reject_unmatched_groups():
    out = paired_permutation_test([1.0, 2.0], [1.0], n_perm=10)
    assert math.isnan(out["p_value"])
    point, lo, hi = paired_bootstrap_difference_ci([1.0, 2.0], [1.0])
    assert all(math.isnan(v) for v in (point, lo, hi))


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


# Legacy exploratory Jonckheere–Terpstra helper.

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


def test_sign_flip_ci_agrees_with_the_test_it_inverts():
    """The interval must exclude zero exactly when the sign-flip test rejects.

    That agreement is the entire reason the interval exists: the paper reports a
    percentile bootstrap interval next to a sign-flip p-value, and the two can
    disagree at the boundary, which reads as an inconsistent result. Inverting
    the same test removes the disagreement by construction, so a case where the
    two disagree here means the inversion is wrong.
    """
    import numpy as np

    from ari.evaluator.handoff_stats import paired_permutation_test, sign_flip_ci

    rng = np.random.default_rng(3)
    for shift in (0.0, 0.6, 1.5, 3.0):
        a = rng.normal(shift, 1.0, 30)
        b = rng.normal(0.0, 1.0, 30)
        p = paired_permutation_test(a, b, n_perm=20000)["p_value"]
        point, lo, hi = sign_flip_ci(a, b, n_perm=50_000)
        excludes_zero = not (lo <= 0.0 <= hi)
        assert excludes_zero == (p <= 0.05), (
            f"shift={shift}: p={p} but interval [{lo}, {hi}]")
        assert lo <= point <= hi
        assert abs(point - float(np.mean(a - b))) < 1e-12


def test_sign_flip_ci_degenerate_inputs_match_the_bootstrap_helper():
    """Empty and ragged inputs return NaNs, as paired_bootstrap_difference_ci does."""
    import math

    from ari.evaluator.handoff_stats import sign_flip_ci

    for a, b in (([], []), ([1.0, 2.0], [1.0])):
        assert all(math.isnan(x) for x in sign_flip_ci(a, b))
