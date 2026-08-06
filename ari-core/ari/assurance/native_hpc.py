"""Public facade for deterministic ARI-native HPC artifact verifiers.

The implementation owns hidden cases and independent oracles but neither
selects a Harness nor mutates RQGM state. Production execution remains in the
isolated native Harness driver.
"""

from __future__ import annotations

from typing import Any, Literal

from ari.assurance.native_hpc_common import (
    NativeCandidate,
    NativeCaseResultV1,
    NativeHPCVerificationReportV1,
    NativeKind,
)
from ari.assurance.native_hpc_gemm import gemm_reference, verify_gemm
from ari.assurance.native_hpc_spmm import spmm_reference, verify_spmm
from ari.assurance.native_hpc_stencil import stencil_reference, verify_stencil


def verify_native_hpc(
    kind: NativeKind,
    candidate: NativeCandidate,
    *,
    tier: Literal["screen", "validate", "certify"] = "screen",
    seed: int | None = None,
    negative_control: bool = False,
) -> NativeHPCVerificationReportV1:
    functions = {
        "gemm": verify_gemm,
        "spmm": verify_spmm,
        "stencil": verify_stencil,
    }
    kwargs: dict[str, Any] = {
        "tier": tier,
        "negative_control": negative_control,
    }
    if seed is not None:
        kwargs["seed"] = seed
    return functions[kind](candidate, **kwargs)


__all__ = [
    "NativeCaseResultV1",
    "NativeHPCVerificationReportV1",
    "gemm_reference",
    "spmm_reference",
    "stencil_reference",
    "verify_gemm",
    "verify_native_hpc",
    "verify_spmm",
    "verify_stencil",
]
