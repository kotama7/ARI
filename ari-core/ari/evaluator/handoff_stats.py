"""Run-level statistics for the handoff-study analysis (Stage 4 core).

Pure, unit-tested statistics the ``workspace/analyze_handoff_ablation.py`` CLI
composes. The unit of analysis is the RUN (one BFTS tree -> one scalar primary
outcome); these functions therefore resample/compare whole runs and NEVER
lineage-correlated nodes (PREREG §7).

Two complementary confirmatory tests, matching the paper's design:
  * PRIMARY (directional trend): the Jonckheere–Terpstra ordered-alternative
    test (``jonckheere_terpstra``) — does the outcome increase monotonically
    along a PRE-SPECIFIED handoff-richness order? It is RANK-based, hence
    invariant to any monotone transform, so the "log domain" distinction is
    moot for it (a speedup ratio and its log give the same JT). Every run
    enters, including invalid runs scored 0 (validity differences are part of
    the trend, not silently dropped).
  * EQUIVALENCE (parity): ``tost_equivalence`` for the nested "does the full log
    add value ON TOP of the summary?" contrast. Speedups are ratios, so the
    caller passes LOG-domain per-run values (margin in log units, SESOI ~log(1.2) — log(1.05) was vacuous at feasible n); bounded
    [0,1] scores are passed in the linear domain with an absolute margin.

See ari-core/ari/evaluator/Plan.md and the pre-registration.
"""

from __future__ import annotations

import math
from typing import Callable, Sequence

import numpy as np
from scipy import stats


def geomean(values: Sequence[float]) -> float:
    """Geometric mean of strictly-positive values; 0.0 if none are positive."""
    v = [float(x) for x in values if x is not None and float(x) > 0.0]
    if not v:
        return 0.0
    return math.exp(sum(math.log(x) for x in v) / len(v))


def bootstrap_ci(
    values: Sequence[float],
    *,
    statistic: Callable[[np.ndarray], float] | None = None,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Percentile bootstrap CI of ``statistic`` over independent RUN-level values.

    Resamples whole runs with replacement (the unit of analysis) — never
    lineage-correlated nodes, which would understate variance. Returns
    ``(point, lo, hi)``.
    """
    stat = statistic or (lambda a: float(np.mean(a)))
    arr = np.asarray([float(x) for x in values], dtype=float)
    if arr.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    point = float(stat(arr))
    rng = np.random.default_rng(seed)
    boots = np.array([
        stat(rng.choice(arr, size=arr.size, replace=True)) for _ in range(n_boot)
    ])
    lo, hi = np.percentile(boots, [100 * alpha / 2.0, 100 * (1.0 - alpha / 2.0)])
    return (point, float(lo), float(hi))


def _mw_count(xi: np.ndarray, xj: np.ndarray) -> float:
    """Mann–Whitney P-count: #{(a in xi, b in xj): b > a} + 0.5·#{b == a}.

    Summed over ordered group pairs (i<j) this is the Jonckheere J statistic."""
    if xi.size == 0 or xj.size == 0:
        return 0.0
    d = xj[:, None] - xi[None, :]
    return float(np.count_nonzero(d > 0) + 0.5 * np.count_nonzero(d == 0))


def _jt_statistic(groups: list[np.ndarray]) -> float:
    k = len(groups)
    J = 0.0
    for i in range(k):
        for j in range(i + 1, k):
            J += _mw_count(groups[i], groups[j])
    return J


def jonckheere_terpstra(
    groups: Sequence[Sequence[float]],
    *,
    alternative: str = "increasing",
    n_perm: int = 20000,
    seed: int = 0,
) -> dict:
    """Jonckheere–Terpstra test for an ORDERED alternative across ``groups``.

    ``groups`` are given in the PRE-SPECIFIED increasing order (e.g. the handoff
    nested chain code_only ⊂ code+summary ⊂ code+summary+full_log). H0: all
    groups share one distribution. Ha(increasing): later groups stochastically
    dominate earlier ones (the study's directional hypothesis: richer handoff →
    better outcome). RANK-based ⇒ invariant to monotone transforms, so log vs
    linear domain is irrelevant.

    Returns the statistic J, its null mean/variance (TIE-corrected — the many
    invalid runs scored 0 are ties), a normal-approximation z + one-sided p, and
    an EXACT permutation p (Monte-Carlo, seeded) which is the honest p at the
    small per-arm n of this study. ``p_value`` is the permutation p.
    """
    gs = [np.asarray([float(x) for x in g], dtype=float) for g in groups]
    ns = [int(g.size) for g in gs]
    N = int(sum(ns))
    nonempty = [n for n in ns if n > 0]
    if len(nonempty) < 2 or N < 3:
        return {"J": float("nan"), "p_value": float("nan"), "p_perm": float("nan"),
                "p_normal": float("nan"), "z": float("nan"), "n_per_group": ns,
                "alternative": alternative, "reason": "need >=2 non-empty groups, N>=3"}

    J = _jt_statistic(gs)
    J_mean = (N * N - sum(n * n for n in ns)) / 4.0

    pooled = np.concatenate(gs)
    _, tie_counts = np.unique(pooled, return_counts=True)
    t = tie_counts.astype(float)
    nsf = np.asarray(ns, dtype=float)

    def _s1(x):  # Σ x(x-1)(2x+5)
        return float(np.sum(x * (x - 1.0) * (2.0 * x + 5.0)))

    def _s2(x):  # Σ x(x-1)(x-2)
        return float(np.sum(x * (x - 1.0) * (x - 2.0)))

    def _s3(x):  # Σ x(x-1)
        return float(np.sum(x * (x - 1.0)))

    var = (N * (N - 1.0) * (2.0 * N + 5.0) - _s1(nsf) - _s1(t)) / 72.0
    if N > 2:
        var += (_s2(nsf) * _s2(t)) / (36.0 * N * (N - 1.0) * (N - 2.0))
    var += (_s3(nsf) * _s3(t)) / (8.0 * N * (N - 1.0))
    var = max(var, 0.0)
    sd = math.sqrt(var)

    # Normal approximation with continuity correction (one-sided by default).
    if sd > 0.0:
        if alternative == "increasing":
            z = (J - J_mean - 0.5) / sd
            p_normal = float(stats.norm.sf(z))
        elif alternative == "decreasing":
            z = (J - J_mean + 0.5) / sd
            p_normal = float(stats.norm.cdf(z))
        else:  # two-sided
            z = (J - J_mean - math.copysign(0.5, J - J_mean)) / sd
            p_normal = float(2.0 * stats.norm.sf(abs(z)))
    else:
        z, p_normal = 0.0, 1.0

    # Exact-ish permutation p (honest at small n): permute group labels.
    rng = np.random.default_rng(seed)
    idx = np.concatenate([[i] * ns[i] for i in range(len(ns))])
    ge = 1  # +1 (observed) in numerator and denominator
    le = 1
    for _ in range(int(n_perm)):
        perm = rng.permutation(pooled)
        pg = [perm[idx == i] for i in range(len(ns))]
        Jp = _jt_statistic(pg)
        if Jp >= J:
            ge += 1
        if Jp <= J:
            le += 1
    denom = int(n_perm) + 1
    if alternative == "increasing":
        p_perm = ge / denom
    elif alternative == "decreasing":
        p_perm = le / denom
    else:
        p_perm = min(1.0, 2.0 * min(ge, le) / denom)

    return {"J": float(J), "J_mean": float(J_mean), "J_var": float(var),
            "z": float(z), "p_normal": float(p_normal), "p_perm": float(p_perm),
            "p_value": float(p_perm), "n_per_group": ns, "n_perm": int(n_perm),
            "alternative": alternative}


def tost_equivalence(a: Sequence[float], b: Sequence[float], *,
                     margin: float, alpha: float = 0.05) -> dict:
    """Two one-sided Welch tests (TOST) for equivalence of mean(a)-mean(b).

    Pass LOG-domain per-run values for ratio metrics (e.g. log speedup); ``margin``
    is then the half-width of the equivalence band in log units (PREREG: log(1.05)).
    Equivalent iff both one-sided tests reject at ``alpha`` (i.e. the difference is
    confidently inside [-margin, +margin]). Returns a dict with the verdict + stats.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 2 or b.size < 2:
        return {"equivalent": False, "reason": "n<2", "mean_diff": float("nan")}
    ma, mb = float(a.mean()), float(b.mean())
    va, vb = float(a.var(ddof=1)), float(b.var(ddof=1))
    na, nb = a.size, b.size
    se = math.sqrt(va / na + vb / nb)
    diff = ma - mb
    if se == 0.0:
        eq = abs(diff) < margin
        return {"equivalent": bool(eq), "mean_diff": diff, "se": 0.0,
                "p_lower": 0.0 if eq else 1.0, "p_upper": 0.0 if eq else 1.0,
                "alpha": alpha, "margin": margin}
    df = (va / na + vb / nb) ** 2 / (
        (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    )
    # Ha_lower: diff > -margin ; Ha_upper: diff < +margin
    p_lower = float(stats.t.sf((diff + margin) / se, df))
    p_upper = float(stats.t.cdf((diff - margin) / se, df))
    equivalent = (p_lower < alpha) and (p_upper < alpha)
    return {"equivalent": bool(equivalent), "mean_diff": diff, "se": se,
            "df": float(df), "p_lower": p_lower, "p_upper": p_upper,
            "alpha": alpha, "margin": margin}


def holm_adjust(pvalues: Sequence[float]) -> list[float]:
    """Holm-Bonferroni step-down adjusted p-values, aligned to input order.

    For the multiplicity across the mode/field/task contrasts (PREREG): only the
    pre-registered primary contrast is confirmatory; the rest are corrected here.
    """
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    adj = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * float(pvalues[idx]))
        adj[idx] = min(1.0, running)
    return adj


def summarize_arm(run_speedups: Sequence[float], *, seed: int = 0,
                  n_boot: int = 2000, alpha: float = 0.05) -> dict:
    """Per-arm summary: geomean best-valid speedup + bootstrap CI over runs."""
    point, lo, hi = bootstrap_ci(run_speedups, statistic=geomean,
                                 n_boot=n_boot, alpha=alpha, seed=seed)
    return {"n_runs": int(len(run_speedups)), "geomean": point,
            "ci_lo": lo, "ci_hi": hi}
