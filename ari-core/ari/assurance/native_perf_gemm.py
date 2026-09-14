"""The dense fp64 GEMM family: how to make an instance and how to judge one.

This file used to hold the measurement loop as well, keyed on the literal string
"gemm". The loop was generic — compiling, screening flags, ordering the timed
launches, the two denominators — and only four things in it were actually about
matrix multiplication. Those four are what remain here. Everything else moved to
``native_perf_measure``, so a second family costs a generator and an oracle
rather than a copy of the instrument.

WHAT IS STILL GEMM-SPECIFIC. The problem is a pair of random matrices; the
serialized form is the header the frozen driver reads; the answer is n*m
doubles; and correctness is a per-element backward-error bound rather than
equality, because a reassociating kernel is allowed to round differently. That
last one is the reason an oracle cannot be data: "close enough" for a GEMM is a
formula in p, not a tolerance a problem file could name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ari.assurance.native_perf_family import register_family

#: Backward-error constant for the residual bound, matching the correctness
#: verifier's model.
_C_EPS = 8.0
_FP64_U = 2.0**-53

#: The reference is built the way a competent user of this toolchain would build
#: it, so the denominator is not handicapped relative to the candidates it is the
#: bar for.
_REFERENCE_FLAGS_AARCH64 = ("-march=armv8.2-a+sve", "-ffast-math")
_REFERENCE_FLAGS_OTHER = ("-ffast-math",)


def reference_flags() -> tuple[str, ...]:
    import platform

    if platform.machine() == "aarch64":
        return _REFERENCE_FLAGS_AARCH64
    return _REFERENCE_FLAGS_OTHER


def gen_problem(shape: tuple[int, int, int], seed: int):
    n, p, m = shape
    rng = np.random.default_rng(seed)
    a = rng.standard_normal((n, p)).astype(np.float64)
    b = rng.standard_normal((p, m)).astype(np.float64)
    return a, b


def _write_problem(path: Path, a: np.ndarray, b: np.ndarray) -> None:
    n, p = a.shape
    _p, m = b.shape
    with path.open("wb") as handle:
        np.array([n, m, p], dtype=np.int32).tofile(handle)
        np.ascontiguousarray(a).tofile(handle)
        np.ascontiguousarray(b).tofile(handle)


def _residual_ok(c_candidate: np.ndarray, a: np.ndarray, b: np.ndarray,
                 ) -> tuple[bool, float]:
    """Per-element backward-error bound, the same model the correctness verifier
    uses. A NaN residual fails it, which is how the driver's poisoned output
    catches a kernel that does not write every element."""
    reference = a @ b
    if c_candidate.shape != reference.shape:
        return False, float("inf")
    p = a.shape[1]
    gamma = (p * _FP64_U) / max(1e-30, 1.0 - p * _FP64_U)
    bound = _C_EPS * gamma * (np.abs(a) @ np.abs(b))
    delta = np.abs(c_candidate - reference)
    with np.errstate(invalid="ignore", divide="ignore"):
        worst = float(np.nanmax(delta / np.maximum(bound, 1e-300)))
    ok = bool(np.all(np.isfinite(delta)) and np.all(delta <= bound))
    return ok, worst


class GemmFamily:
    """Dense row-major fp64 C = A*B."""

    name = "gemm"

    def reference_flags(self) -> tuple[str, ...]:
        return reference_flags()

    def generate(self, case: tuple[int, ...], seed: int) -> Any:
        n, p, m = (int(v) for v in case)
        return gen_problem((n, p, m), seed)

    def write(self, path: Path, instance: Any) -> None:
        a, b = instance
        _write_problem(path, a, b)

    def output_elements(self, case: tuple[int, ...]) -> int:
        n, _p, m = (int(v) for v in case)
        return n * m

    def check(self, output: Any, case: tuple[int, ...], instance: Any,
              ) -> tuple[bool, float]:
        n, _p, m = (int(v) for v in case)
        a, b = instance
        return _residual_ok(np.asarray(output).reshape(n, m), a, b)


GEMM_FAMILY = register_family(GemmFamily())


__all__ = ["GEMM_FAMILY", "GemmFamily", "gen_problem", "reference_flags"]
