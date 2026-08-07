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
from ari.assurance.native_hpc_family import (
    get_native_family,
    registered_native_families,
)


def verify_native_hpc(
    kind: NativeKind,
    candidate: NativeCandidate,
    *,
    tier: Literal["screen", "validate", "certify"] = "screen",
    seed: int | None = None,
    negative_control: bool = False,
) -> NativeHPCVerificationReportV1:
    """Verify a candidate against the named family's hidden cases and oracle.

    Dispatched through the registry rather than a table written here: the set
    of families was previously spelled out in five places, so adding one meant
    finding all five and a half-added family failed at whichever it missed.
    """
    kwargs: dict[str, Any] = {
        "tier": tier,
        "negative_control": negative_control,
    }
    if seed is not None:
        kwargs["seed"] = seed
    return get_native_family(kind).verify(candidate, **kwargs)


def native_reference(kind: NativeKind):
    """The family's independent implementation, which is also the clean control."""
    return get_native_family(kind).reference


__all__ = [
    "NativeCaseResultV1",
    "native_reference",
    "registered_native_families",
    "NativeHPCVerificationReportV1",
    "verify_native_hpc",
]
