"""The 3-D 7-point Jacobi family: how to make an instance and how to judge one.

Ported from the prototype's harness, keeping the two decisions that were paid
for there:

THE BOUND SCALES WITH nt. The update is a convex combination -- seven positive
weights summing to one -- so values stay inside the input's range and a single
sweep's rounding is bounded by ``gamma(7) * max|u0|``; nt sweeps accumulate
roughly linearly. A bound that ignored nt would reject legitimate reassociation
at high sweep counts, which is exactly where the interesting kernels live.

THE REFERENCE PING-PONGS INSTEAD OF COPYING. The naive expression of the same
arithmetic allocated a fresh temporary for each of the five neighbour additions
and copied the whole field every sweep, which on a 256-cube at 30 sweeps moved
roughly 24 GB through the allocator and took 16.1 s -- per repetition, for every
node, recomputing an identical answer. Two preallocated buffers ping-pong and
only the interior is ever written, since the Dirichlet boundary is already
correct in both buffers after the initial copy. The additions are issued in the
order the naive expression evaluated them, so the result is bit-identical rather
than merely close.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ari.assurance.native_perf_common import PerfInfrastructureError
from ari.assurance.native_perf_family import register_family

_C_EPS = 8.0
_FP64_U = 2.0**-53

#: The seven weights, which sum to 1. Part of the contract in the pinned header;
#: repeated here because the oracle has to compute the same thing.
_C0 = 0.5
_CW = 1.0 / 12.0

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


def _parse_case(case: tuple[Any, ...]) -> tuple[int, int, int, int]:
    if len(case) != 4:
        raise PerfInfrastructureError(
            f"stencil case {case!r} must be (nx, ny, nz, nt)")
    nx, ny, nz, nt = (int(v) for v in case)
    if min(nx, ny, nz) < 3:
        raise PerfInfrastructureError(
            f"stencil case {case!r} has no interior to sweep")
    if nt < 1:
        # nt=0 makes "hand back the input" a CORRECT answer, which would make
        # the fast-but-wrong control pass and the probe meaningless.
        raise PerfInfrastructureError(
            f"stencil case {case!r} applies no sweep, so a copy would be right")
    return nx, ny, nz, nt


def reference_jacobi(u0, nx: int, ny: int, nz: int, nt: int):
    """nt naive Jacobi sweeps, fixed (Dirichlet) boundary planes, fp64."""
    src = np.asarray(u0, dtype=np.float64).reshape(nx, ny, nz).copy()
    if int(nt) <= 0:
        return src
    dst = src.copy()                      # boundaries fixed = u0 in both buffers
    interior = (slice(1, -1), slice(1, -1), slice(1, -1))
    s = np.empty_like(src[interior])
    c0u = np.empty_like(s)
    for _ in range(int(nt)):
        np.add(src[2:, 1:-1, 1:-1], src[:-2, 1:-1, 1:-1], out=s)
        np.add(s, src[1:-1, 2:, 1:-1], out=s)
        np.add(s, src[1:-1, :-2, 1:-1], out=s)
        np.add(s, src[1:-1, 1:-1, 2:], out=s)
        np.add(s, src[1:-1, 1:-1, :-2], out=s)
        np.multiply(s, _CW, out=s)
        np.multiply(src[interior], _C0, out=c0u)
        np.add(c0u, s, out=dst[interior])
        src, dst = dst, src
    return src


class StencilFamily:
    """3-D 7-point Jacobi over an fp64 field with fixed boundary planes."""

    name = "stencil"

    def reference_flags(self) -> tuple[str, ...]:
        return reference_flags()

    def generate(self, case: tuple[Any, ...], seed: int) -> Any:
        nx, ny, nz, nt = _parse_case(case)
        rng = np.random.default_rng(seed)
        u0 = rng.standard_normal((nx, ny, nz)).astype(np.float64)
        return u0, nt

    def write(self, path: Path, instance: Any) -> None:
        u0, nt = instance
        nx, ny, nz = u0.shape
        with path.open("wb") as handle:
            np.array([nx, ny, nz, nt], dtype=np.int32).tofile(handle)
            np.ascontiguousarray(u0).tofile(handle)

    def output_elements(self, case: tuple[Any, ...]) -> int:
        nx, ny, nz, _nt = _parse_case(case)
        return nx * ny * nz

    def check(self, output: Any, case: tuple[Any, ...], instance: Any,
              ) -> tuple[bool, float]:
        nx, ny, nz, nt = _parse_case(case)
        u0, _nt = instance
        candidate = np.asarray(output, dtype=np.float64).ravel()
        if candidate.size != nx * ny * nz:
            return False, float("inf")
        reference = reference_jacobi(u0, nx, ny, nz, nt).ravel()
        amax = float(np.max(np.abs(np.asarray(u0, dtype=np.float64)))) or 1.0
        bound = _C_EPS * gamma(7) * float(max(int(nt), 1)) * amax
        delta = np.abs(candidate - reference)
        with np.errstate(invalid="ignore", divide="ignore"):
            worst = float(np.nanmax(delta / max(bound, 1e-300)))
        ok = bool(np.all(np.isfinite(delta)) and np.all(delta <= bound))
        return ok, worst


STENCIL_FAMILY = register_family(StencilFamily())


__all__ = ["STENCIL_FAMILY", "StencilFamily", "gamma", "reference_flags",
           "reference_jacobi"]
