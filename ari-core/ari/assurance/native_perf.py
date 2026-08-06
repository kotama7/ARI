"""Public facade for the ARI-native performance harnesses.

Mirrors ``ari.assurance.native_hpc``: it owns the scored shapes and the frozen
denominator but neither selects a Harness nor mutates RQGM state. Production
execution stays in the isolated driver.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ari.assurance.native_perf_common import (
    NativePerfReportV1,
    PerfBuildError,
    PerfInfrastructureError,
    PerfKind,
    PerfTier,
)
from ari.assurance.native_perf_gemm import (
    DEFAULT_CASE_SET as GEMM_DEFAULT_CASE_SET,
    gemm_reference_source,
    reference_flags,
    verify_gemm_performance,
)


def verify_native_perf(
    kind: PerfKind,
    candidate_source: str | Path,
    *,
    tier: PerfTier = "screen",
    seed: int = 0,
    **kwargs,
) -> NativePerfReportV1:
    functions = {"gemm": verify_gemm_performance}
    if kind not in functions:
        raise PerfInfrastructureError(
            f"no registered performance harness for {kind!r}; "
            f"available: {sorted(functions)}")
    return functions[kind](Path(candidate_source), tier=tier, seed=seed, **kwargs)


def reference_source(kind: PerfKind) -> Path:
    sources = {"gemm": gemm_reference_source}
    if kind not in sources:
        raise PerfInfrastructureError(f"no frozen reference for {kind!r}")
    return sources[kind]()


__all__ = [
    "GEMM_DEFAULT_CASE_SET",
    "NativePerfReportV1",
    "PerfBuildError",
    "PerfInfrastructureError",
    "reference_flags",
    "reference_source",
    "verify_native_perf",
]
