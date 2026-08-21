"""Shared result, determinism, and numerical-error machinery for native HPC."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Literal

from pydantic import Field

from ari.protocols.integrity import DigestBoundModel, StrictModel


#: WHICH FAMILY, by name. This was a ``Literal`` of the three ARI ships, which
#: made the set of verifiable kernels a property of this file and a fourth thing
#: to edit when one changed. A family registers itself now
#: (``ari.assurance.native_hpc_family``) and every dispatch site asks the
#: registry; the name still appears in a report because a verdict has to say
#: what it verified.
#:
#: This does NOT make families free the way pinned problems are: adding one is
#: still an ARI change, because an oracle a caller could supply is an oracle a
#: caller could weaken.
NativeKind = str
NativeCandidate = Callable[[dict[str, Any]], Any]


class NativeCaseResultV1(StrictModel):
    case_id: str
    category: str
    verdict: Literal["pass", "fail", "inconclusive"]
    detail: str
    max_abs_error: float = Field(ge=0)
    max_rel_error: float = Field(ge=0)


class NativeHPCVerificationReportV1(DigestBoundModel):
    _digest_field = "report_digest"

    schema_version: Literal["ari.native-hpc-verification-report/v1"] = (
        "ari.native-hpc-verification-report/v1"
    )
    kind: NativeKind
    tier: Literal["screen", "validate", "certify"]
    verdict: Literal["pass", "fail", "inconclusive"]
    case_results: tuple[NativeCaseResultV1, ...]
    categories_covered: tuple[str, ...]
    deterministic: bool
    oracle: str
    error_model: str
    negative_control: bool
    #: WHAT THE CANDIDATE'S LAUNCHES RAN UNDER, observed by the worker that
    #: spawns them, because a family verifies a Callable and never launches.
    #: The two halves answer different kinds of question: the filesystem entry
    #: is a PRECONDITION -- the isolated host fails closed, so a candidate never
    #: runs unrestricted and only True can reach the record -- while the network
    #: entry is a genuine observation of the namespace the child inherited.
    #:
    #: Absent before this, and its absence had a consequence: this family's
    #: registration evidence declared ``network_isolation`` from the REQUEST,
    #: like the other two once did, and had nothing anywhere to derive it from.
    #: Free-form for the same reason the perf report's is: what a host can
    #: observe is not this schema's to enumerate.
    sandbox: dict[str, Any] = Field(default_factory=dict)
    report_digest: str


def _candidate_output(value: Any) -> list[float]:
    if isinstance(value, dict):
        if value.get("status") == "invalid_input":
            raise ValueError("candidate rejected input")
        value = value.get("output")
    if not isinstance(value, (list, tuple)):
        raise TypeError("candidate output must be an array or {output: array}")
    return [float(item) for item in value]


def _same_special(expected: float, actual: float) -> bool:
    if math.isnan(expected):
        return math.isnan(actual)
    if math.isinf(expected):
        return math.isinf(actual) and math.copysign(
            1.0, expected
        ) == math.copysign(1.0, actual)
    return math.isfinite(actual)


def _repeat_equal(first: list[float], other: list[float]) -> bool:
    if len(first) != len(other):
        return False
    for left, right in zip(first, other):
        if math.isnan(left) and math.isnan(right):
            continue
        if left != right:
            return False
    return True


def _compare(
    expected: list[float],
    actual: list[float],
    *,
    dtype: str,
    accumulation: int,
) -> tuple[bool, float, float, str]:
    if len(expected) != len(actual):
        return False, math.inf, math.inf, "output length mismatch"
    unit_roundoff = 2.0**-24 if dtype == "float32" else 2.0**-53
    # gamma_n grows with accumulation length; there is no global fixed rtol.
    n = max(1, int(accumulation))
    gamma = (n * unit_roundoff) / max(1e-30, 1.0 - n * unit_roundoff)
    relative_limit = max(8.0 * gamma, 8.0 * unit_roundoff)
    absolute_floor = 64.0 * unit_roundoff
    max_abs = 0.0
    max_rel = 0.0
    for index, (want, got) in enumerate(zip(expected, actual)):
        if not _same_special(want, got):
            return (
                False,
                math.inf,
                math.inf,
                f"special-value policy mismatch at {index}",
            )
        if not math.isfinite(want):
            continue
        delta = abs(want - got)
        rel = delta / max(abs(want), absolute_floor)
        max_abs = max(max_abs, delta)
        max_rel = max(max_rel, rel)
        if delta > absolute_floor + relative_limit * abs(want):
            return (
                False,
                max_abs,
                max_rel,
                f"error bound exceeded at {index}: abs={delta:.6g}, rel={rel:.6g}",
            )
    return True, max_abs, max_rel, "within accumulation-aware error bound"


def run_case(
    *,
    case_id: str,
    category: str,
    case: dict[str, Any],
    expected: list[float],
    candidate: NativeCandidate,
    accumulation: int,
    repeated: int = 2,
) -> NativeCaseResultV1:
    outputs: list[list[float]] = []
    try:
        for _ in range(repeated):
            outputs.append(_candidate_output(candidate(dict(case))))
    except Exception as exc:
        return NativeCaseResultV1(
            case_id=case_id,
            category=category,
            verdict="fail",
            detail=f"candidate error: {type(exc).__name__}: {exc}",
            max_abs_error=0,
            max_rel_error=0,
        )
    if any(not _repeat_equal(outputs[0], output) for output in outputs[1:]):
        return NativeCaseResultV1(
            case_id=case_id,
            category=category,
            verdict="fail",
            detail="repeated execution was not deterministic",
            max_abs_error=0,
            max_rel_error=0,
        )
    passed, max_abs, max_rel, detail = _compare(
        expected,
        outputs[0],
        dtype=str(case.get("dtype", "float64")),
        accumulation=accumulation,
    )
    return NativeCaseResultV1(
        case_id=case_id,
        category=category,
        verdict="pass" if passed else "fail",
        detail=detail,
        max_abs_error=max_abs if math.isfinite(max_abs) else 1.0e308,
        max_rel_error=max_rel if math.isfinite(max_rel) else 1.0e308,
    )


def build_report(
    kind: NativeKind,
    tier: str,
    results: list[NativeCaseResultV1],
    *,
    oracle: str,
    error_model: str,
    negative_control: bool,
) -> NativeHPCVerificationReportV1:
    passed = bool(results) and all(item.verdict == "pass" for item in results)
    return NativeHPCVerificationReportV1.create(
        kind=kind,
        tier=tier,
        verdict="pass" if passed else "fail",
        case_results=tuple(results),
        categories_covered=tuple(sorted({item.category for item in results})),
        deterministic=not any(
            "not deterministic" in item.detail for item in results
        ),
        oracle=oracle,
        error_model=error_model,
        negative_control=negative_control,
    )


__all__ = [
    "NativeCandidate",
    "NativeCaseResultV1",
    "NativeHPCVerificationReportV1",
    "NativeKind",
    "build_report",
    "run_case",
]
