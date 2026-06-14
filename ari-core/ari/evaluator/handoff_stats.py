"""Run-level statistics for the handoff-study analysis (Stage 4 core).

Pure, unit-tested statistics the ``scripts/analyze_handoff_ablation.py`` CLI
composes. The unit of analysis is the RUN (one BFTS tree -> one scalar primary
outcome); these functions therefore resample/compare whole runs and NEVER
lineage-correlated nodes (PREREG §7). Speedups are ratios, so equivalence /
CIs are taken in the LOG domain by the caller.

See ari-core/ari/evaluator/Plan.md, ari-core/PREREG_handoff_study.md (§7,
primary contrast = code_plus_summary vs code_plus_full_log, TOST margin=log(1.05)).
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
