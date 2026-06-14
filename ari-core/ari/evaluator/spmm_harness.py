"""SpMM measurement harness for the handoff study (B2b) — measurement CORE.

This is the engine ``DeterministicEvaluator.measure_fn`` calls. It owns the
fixed reference oracle (fp64 ``Y = A @ X``), the per-output-element correctness
bound (PREREG eps model), the seeded matrix families, and the per-family
geomean-speedup aggregation — i.e. everything that makes a "valid speedup"
well-defined and un-gameable (the evaluator generates A and X; the agent only
supplies a kernel).

LOGIN-TESTABLE (pure numpy/scipy, validated here): ``gen_matrix``,
``reference_spmm``, ``gamma``, ``is_correct``, and ``measure_node`` with an
injected ``run_kernel``.

COMPUTE-NODE ONLY (NOT validated on a login node — repo rule "validate
environment-dependent logic on a real compute node"): ``_default_run_kernel``
(compile + OpenMP run + timing of the agent's C kernel) and the ``.c`` kernel
fixtures. Those land + are validated separately. Until then ``measure_node``
with the default runner will raise, and DeterministicEvaluator degrades to a
graceful invalid result.

See ari-core/ari/evaluator/Plan.md and ari-core/PREREG_handoff_study.md.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
import scipy.sparse as sp

# PREREG: the fixed family set the geomean is taken over.
FAMILIES: tuple[str, ...] = (
    "uniform", "banded", "power_law", "block", "diagonal_dominant", "skewed",
)
_FP64_U = 2.0 ** -53  # double-precision unit roundoff


def gamma(k: int, u: float = _FP64_U) -> float:
    """Backward-stable summation error factor k*u/(1-k*u); inf when k*u>=1."""
    ku = float(k) * float(u)
    return ku / (1.0 - ku) if ku < 1.0 else float("inf")


def gen_matrix(family: str, n: int = 512, *, density: float = 0.02,
               seed: int = 0) -> sp.csr_matrix:
    """Deterministic CSR matrix for a named family (seeded; reproducible)."""
    rng = np.random.default_rng(seed)
    fam = family.lower()
    if fam == "uniform":
        A = sp.random(n, n, density=density, format="csr",
                      random_state=rng, data_rvs=rng.standard_normal)
    elif fam == "banded":
        bw = max(1, int(n * density))
        diags = [rng.standard_normal(n - abs(o)) for o in range(-bw, bw + 1)]
        A = sp.diags(diags, list(range(-bw, bw + 1)), shape=(n, n)).tocsr()
    elif fam == "diagonal_dominant":
        A = sp.random(n, n, density=density, format="csr",
                      random_state=rng, data_rvs=rng.standard_normal).tolil()
        for i in range(n):
            A[i, i] = float(abs(A[i]).sum()) + 1.0
        A = A.tocsr()
    elif fam == "block":
        b = max(1, n // 16)
        blk = sp.random(b, b, density=min(1.0, density * 16), format="csr",
                        random_state=rng, data_rvs=rng.standard_normal)
        A = sp.block_diag([blk] * (n // b), format="csr")
        A = A[:n, :n].tocsr()
    elif fam in ("power_law", "skewed"):
        # row nnz follows a heavy-tailed distribution (a few very dense rows).
        rows, cols, vals = [], [], []
        for i in range(n):
            deg = int(min(n, 1 + rng.pareto(1.5) * n * density))
            cs = rng.choice(n, size=min(deg, n), replace=False)
            rows.extend([i] * len(cs)); cols.extend(cs.tolist())
            vals.extend(rng.standard_normal(len(cs)).tolist())
        A = sp.csr_matrix((vals, (rows, cols)), shape=(n, n))
    else:
        raise ValueError(f"unknown matrix family: {family}")
    A.eliminate_zeros()
    return A.tocsr()


def reference_spmm(A: sp.csr_matrix, X: np.ndarray) -> np.ndarray:
    """Reference Y = A @ X in fp64 (the correctness ground truth)."""
    return np.asarray(sp.csr_matrix(A).astype(np.float64) @ np.asarray(X, dtype=np.float64))


def is_correct(Y_cand: np.ndarray, Y_ref: np.ndarray, A: sp.csr_matrix,
               X: np.ndarray, *, C: float = 8.0, u: float = _FP64_U) -> tuple[bool, float]:
    """Per-element correctness against the PREREG bound; returns (ok, max_rel_resid).

    Accept iff for every output element ``|Y_cand-Y_ref| <= C * gamma_{nnz_i} *
    (|A| @ |X|)`` where ``nnz_i`` is the nnz of A's row i (the length of that
    output element's summation). Scales the tolerance per-row with row length,
    so legitimate FP-reorderings on dense (power-law) rows are not falsely
    rejected and wrong kernels on short rows are not falsely accepted.
    """
    A = sp.csr_matrix(A)
    Yc = np.asarray(Y_cand, dtype=np.float64)
    Yr = np.asarray(Y_ref, dtype=np.float64)
    if Yc.shape != Yr.shape:
        return False, float("inf")
    nnz_per_row = np.diff(A.indptr)
    g = np.array([gamma(int(k), u) for k in nnz_per_row], dtype=np.float64)
    absA = sp.csr_matrix((np.abs(A.data), A.indices, A.indptr), shape=A.shape)
    bound = C * g[:, None] * (absA @ np.abs(np.asarray(X, dtype=np.float64)))
    resid = np.abs(Yc - Yr)
    ok = bool(np.all(resid <= bound))
    denom = np.abs(Yr)
    max_rel = float(np.max(resid / np.where(denom > 0, denom, np.inf))) if Yr.size else 0.0
    return ok, max_rel


def _default_run_kernel(*_a: Any, **_k: Any):  # pragma: no cover - compute node only
    raise RuntimeError(
        "SpMM kernel harness compile/run/timing is compute-node only and not "
        "yet installed (B2b). Inject run_kernel for tests, or run on a compute node."
    )


def measure_node(
    work_dir: str,
    *,
    run_kernel: Callable | None = None,
    families: tuple[str, ...] = FAMILIES,
    n: int = 512,
    k: int = 32,
    seed: int = 0,
    warmup: int = 3,
    reps: int = 10,
) -> dict:
    """Measure a node's candidate SpMM kernel against the fixed family set.

    ``run_kernel(kind, work_dir, A, X, warmup, reps) -> (median_seconds, Y)``
    compiles+runs the baseline ('baseline') or the agent's candidate
    ('candidate') and returns its timing + output. The evaluator owns A and X
    (the agent cannot supply them — anti-gaming). Returns the dict
    DeterministicEvaluator._score consumes.
    """
    run = run_kernel or _default_run_kernel
    out_families: dict[str, dict] = {}
    compile_ok = True
    reason = "ok"
    for fam in families:
        A = gen_matrix(fam, n, seed=seed)
        X = np.random.default_rng(seed + 1).standard_normal((A.shape[1], k))
        Y_ref = reference_spmm(A, X)
        try:
            t_base, _ = run("baseline", work_dir, A, X, warmup, reps)
            t_cand, Y_cand = run("candidate", work_dir, A, X, warmup, reps)
        except Exception as e:
            compile_ok = False
            reason = f"kernel run failed on {fam}: {e}"
            out_families[fam] = {"speedup": 0.0, "valid": False}
            continue
        ok, max_rel = is_correct(Y_cand, Y_ref, A, X)
        speedup = (t_base / t_cand) if (t_cand and t_cand > 0) else 0.0
        out_families[fam] = {
            "speedup": float(speedup), "valid": bool(ok),
            "max_relative_error": max_rel,
        }
    return {"compile_ok": compile_ok, "families": out_families, "reason": reason}
