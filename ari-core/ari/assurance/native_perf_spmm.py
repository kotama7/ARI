"""The CSR SpMM family: how to make an instance and how to judge one.

Ported from the prototype's harness, keeping the two decisions that were paid
for there and would be easy to lose:

THE TOLERANCE IS PER ROW. Accept iff every output element is within
``C * gamma(nnz_i) * (|A| @ |X|)``, where ``nnz_i`` is the number of nonzeros in
that element's row -- the length of the summation that produced it. A single
global tolerance either rejects legitimate reassociation on the dense rows of a
power-law matrix or accepts wrong output on the short ones, and this problem is
scored on both kinds at once.

THE FAMILY SET IS PART OF THE PROBLEM, NOT OF THIS FILE. Which matrix families a
run is scored over lives in the pinned case set, because it is a choice about
what is being asked. What lives here is only how to build a named family, since
that is code.

WHAT IS DELIBERATELY NOT PORTED: the prototype's on-disk caches for the
reference product and the ``|A| @ |X|`` bound. They were worth roughly 80% of a
repetition's cost, so this is slower -- but the cached value IS the correctness
ground truth, and the prototype needed a content-verification pass on every hit
to keep a stale or foreign-scipy cache from silently scoring a different
problem. Porting the cache without that check would trade a real guarantee for
speed; porting both belongs in its own change, measured.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ari.assurance.native_perf_common import PerfInfrastructureError
from ari.assurance.native_perf_family import register_family

#: Backward-error constant, the same model the correctness verifier uses.
_C_EPS = 8.0
_FP64_U = 2.0**-53

#: Every family the case sets may name. Adding one is an ARI change because it
#: is a generator; choosing WHICH of them a run is scored over is not.
KNOWN_MATRIX_FAMILIES: tuple[str, ...] = (
    "uniform", "banded", "power_law", "block", "diagonal_dominant", "skewed",
)

_REFERENCE_FLAGS_AARCH64 = ("-march=armv8.2-a+sve", "-ffast-math")
_REFERENCE_FLAGS_OTHER = ("-ffast-math",)


def reference_flags() -> tuple[str, ...]:
    import platform

    if platform.machine() == "aarch64":
        return _REFERENCE_FLAGS_AARCH64
    return _REFERENCE_FLAGS_OTHER


def gamma(k: int, u: float = _FP64_U) -> float:
    ku = float(k) * float(u)
    return ku / (1.0 - ku) if ku < 1.0 else float("inf")


def _parse_case(case: tuple[Any, ...]) -> tuple[str, int, int, float]:
    """``(matrix_family, n, k)`` or ``(matrix_family, n, k, density_permille)``.

    Density travels as an integer per-mille rather than a float so a case set
    stays exactly comparable byte for byte; 20 is the prototype's 0.02.
    """
    if len(case) not in (3, 4):
        raise PerfInfrastructureError(
            f"spmm case {case!r} must be (matrix_family, n, k[, density_permille])")
    matrix_family = str(case[0])
    if matrix_family not in KNOWN_MATRIX_FAMILIES:
        raise PerfInfrastructureError(
            f"unknown spmm matrix family {matrix_family!r}; "
            f"known: {list(KNOWN_MATRIX_FAMILIES)}")
    n, k = int(case[1]), int(case[2])
    permille = int(case[3]) if len(case) == 4 else 20
    return matrix_family, n, k, permille / 1000.0


def gen_matrix(matrix_family: str, n: int, *, density: float, seed: int):
    """Deterministic CSR matrix for a named family."""
    import scipy.sparse as sp

    rng = np.random.default_rng(seed)
    fam = matrix_family.lower()
    if fam == "uniform":
        a = sp.random(n, n, density=density, format="csr",
                      random_state=rng, data_rvs=rng.standard_normal)
    elif fam == "banded":
        bw = max(1, int(n * density))
        diags = [rng.standard_normal(n - abs(o)) for o in range(-bw, bw + 1)]
        a = sp.diags(diags, list(range(-bw, bw + 1)), shape=(n, n)).tocsr()
    elif fam == "diagonal_dominant":
        a = sp.random(n, n, density=density, format="csr",
                      random_state=rng, data_rvs=rng.standard_normal).tolil()
        for i in range(n):
            a[i, i] = float(abs(a[i]).sum()) + 1.0
        a = a.tocsr()
    elif fam == "block":
        b = max(1, n // 16)
        blk = sp.random(b, b, density=min(1.0, density * 16), format="csr",
                        random_state=rng, data_rvs=rng.standard_normal)
        a = sp.block_diag([blk] * (n // b), format="csr")
        a = a[:n, :n].tocsr()
    elif fam in ("power_law", "skewed"):
        # Row nnz follows a heavy-tailed distribution: a few very dense rows.
        rows, cols, vals = [], [], []
        for i in range(n):
            deg = int(min(n, 1 + rng.pareto(1.5) * n * density))
            chosen = rng.choice(n, size=min(deg, n), replace=False)
            rows.extend([i] * len(chosen))
            cols.extend(chosen.tolist())
            vals.extend(rng.standard_normal(len(chosen)).tolist())
        a = sp.csr_matrix((vals, (rows, cols)), shape=(n, n))
    else:                                   # unreachable: _parse_case screens it
        raise PerfInfrastructureError(f"unknown matrix family: {matrix_family}")
    a.eliminate_zeros()
    return a.tocsr()


class SpmmFamily:
    """CSR A times a dense row-major panel X, fp64."""

    name = "spmm"

    def reference_flags(self) -> tuple[str, ...]:
        return reference_flags()

    def generate(self, case: tuple[Any, ...], seed: int) -> Any:
        matrix_family, n, k, density = _parse_case(case)
        a = gen_matrix(matrix_family, n, density=density, seed=seed)
        rng = np.random.default_rng(seed + 1)
        x = rng.standard_normal((a.shape[1], k)).astype(np.float64)
        return a, x

    def write(self, path: Path, instance: Any) -> None:
        a, x = instance
        with path.open("wb") as handle:
            np.array([a.shape[0], a.shape[1], x.shape[1], a.nnz],
                     dtype=np.int32).tofile(handle)
            a.indptr.astype(np.int32).tofile(handle)
            a.indices.astype(np.int32).tofile(handle)
            a.data.astype(np.float64).tofile(handle)
            np.ascontiguousarray(x).tofile(handle)

    def output_elements(self, case: tuple[Any, ...]) -> int:
        _matrix_family, n, k, _density = _parse_case(case)
        return n * k

    def check(self, output: Any, case: tuple[Any, ...], instance: Any,
              ) -> tuple[bool, float]:
        import scipy.sparse as sp

        _matrix_family, n, k, _density = _parse_case(case)
        a, x = instance
        candidate = np.asarray(output, dtype=np.float64)
        if candidate.size != n * k:
            return False, float("inf")
        candidate = candidate.reshape(n, k)
        reference = np.asarray(sp.csr_matrix(a).astype(np.float64) @ x)
        nnz_per_row = np.diff(a.indptr)
        g = np.array([gamma(int(count)) for count in nnz_per_row],
                     dtype=np.float64)
        abs_a = sp.csr_matrix((np.abs(a.data), a.indices, a.indptr), shape=a.shape)
        bound = _C_EPS * g[:, None] * (abs_a @ np.abs(x))
        delta = np.abs(candidate - reference)
        with np.errstate(invalid="ignore", divide="ignore"):
            worst = float(np.nanmax(delta / np.maximum(bound, 1e-300)))
        ok = bool(np.all(np.isfinite(delta)) and np.all(delta <= bound))
        return ok, worst


SPMM_FAMILY = register_family(SpmmFamily())


__all__ = ["KNOWN_MATRIX_FAMILIES", "SPMM_FAMILY", "SpmmFamily", "gamma",
           "gen_matrix", "reference_flags"]
