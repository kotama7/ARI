"""ARI-native SpMM oracle and hidden-case verifier."""

from __future__ import annotations

import random
from decimal import Decimal, localcontext
from typing import Any, Literal

from ari.assurance.native_hpc_common import (
    NativeCandidate,
    NativeCaseResultV1,
    NativeHPCVerificationReportV1,
    build_report,
    run_case,
)


def _validate_csr(case: dict[str, Any]) -> None:
    m, k = int(case["m"]), int(case["k"])
    row_ptr = [int(item) for item in case["row_ptr"]]
    col_idx = [int(item) for item in case["col_idx"]]
    values = list(case["values"])
    if m < 0 or k < 0 or len(row_ptr) != m + 1 or not row_ptr or row_ptr[0] != 0:
        raise ValueError("invalid CSR row pointer")
    if any(a > b for a, b in zip(row_ptr, row_ptr[1:])):
        raise ValueError("CSR row pointers are not monotonic")
    if row_ptr[-1] != len(values) or len(col_idx) != len(values):
        raise ValueError("CSR nnz arrays disagree")
    if any(column < 0 or column >= k for column in col_idx):
        raise ValueError("CSR column is out of range")


def spmm_reference(case: dict[str, Any]) -> list[float]:
    _validate_csr(case)
    m, k, n = (int(case[name]) for name in ("m", "k", "n"))
    row_ptr = [int(item) for item in case["row_ptr"]]
    col_idx = [int(item) for item in case["col_idx"]]
    values = [float(item) for item in case["values"]]
    b = [float(item) for item in case["b"]]
    c = [float(item) for item in case["c"]]
    ldb, ldc = int(case["ldb"]), int(case["ldc"])
    if ldb < n or ldc < n or len(b) < k * ldb or len(c) < m * ldc:
        raise ValueError("invalid SpMM dense layout")
    alpha, beta = float(case["alpha"]), float(case["beta"])
    out = list(c)
    with localcontext() as context:
        context.prec = 18 if case.get("dtype") == "float32" else 40
        for row in range(m):
            for rhs in range(n):
                total = Decimal(0)
                for pos in range(row_ptr[row], row_ptr[row + 1]):
                    total += Decimal(str(values[pos])) * Decimal(
                        str(b[col_idx[pos] * ldb + rhs])
                    )
                out[row * ldc + rhs] = float(
                    Decimal(str(alpha)) * total
                    + Decimal(str(beta)) * Decimal(str(c[row * ldc + rhs]))
                )
    return out


def _spmm_patterns() -> list[
    tuple[str, int, int, list[int], list[int], list[float]]
]:
    return [
        ("zero-nnz", 3, 5, [0, 0, 0, 0], [], []),
        (
            "empty-row",
            4,
            5,
            [0, 2, 2, 3, 4],
            [0, 3, 2, 4],
            [1.0, -2.0, 0.5, 3.0],
        ),
        (
            "duplicate-index",
            3,
            5,
            [0, 3, 5, 6],
            [1, 1, 4, 0, 0, 3],
            [1.0, 2.0, -1.0, 4.0, -0.5, 2.0],
        ),
        (
            "unsorted-index",
            3,
            7,
            [0, 3, 5, 8],
            [5, 0, 3, 6, 1, 4, 2, 0],
            [1.0, 2.0, 3.0, -1.0, 0.5, 2.0, -3.0, 4.0],
        ),
        (
            "irregular-row",
            5,
            11,
            [0, 1, 8, 8, 10, 15],
            [0, 1, 3, 5, 7, 8, 9, 10, 2, 4, 0, 2, 6, 7, 10],
            [0.25 * (i - 4) for i in range(15)],
        ),
    ]


def verify_spmm(
    candidate: NativeCandidate,
    *,
    tier: Literal["screen", "validate", "certify"] = "screen",
    seed: int = 8123,
    negative_control: bool = False,
) -> NativeHPCVerificationReportV1:
    rng = random.Random(seed)
    patterns = _spmm_patterns()
    if tier == "screen":
        patterns = patterns[:4]
    results: list[NativeCaseResultV1] = []
    index = 0
    for dtype in ("float32", "float64"):
        for category, m, k, row_ptr, col_idx, values in patterns:
            for n in ((1, 3) if tier == "screen" else (1, 3, 7)):
                ldb, ldc = n + (index % 2), n + ((index + 1) % 2)
                case = {
                    "schema_version": "ari.native-spmm-case/v1",
                    "m": m,
                    "k": k,
                    "n": n,
                    "row_ptr": row_ptr,
                    "col_idx": col_idx,
                    "values": values,
                    "b": [rng.uniform(-1.0, 1.0) for _ in range(k * ldb)],
                    "c": [rng.uniform(-1.0, 1.0) for _ in range(m * ldc)],
                    "ldb": ldb,
                    "ldc": ldc,
                    "alpha": (1.0, 0.5)[index % 2],
                    "beta": (0.0, -0.25)[index % 2],
                    "dtype": dtype,
                    "thread_count": (1, 2, 4)[index % 3],
                    "duplicate_policy": "sum",
                    "invalid_input_policy": "reject",
                }
                longest = max(
                    (b - a for a, b in zip(row_ptr, row_ptr[1:])),
                    default=0,
                )
                results.append(
                    run_case(
                        case_id=f"spmm-{index:04d}",
                        category=category,
                        case=case,
                        expected=spmm_reference(case),
                        candidate=candidate,
                        accumulation=longest,
                        repeated=3 if tier != "screen" else 2,
                    )
                )
                index += 1
    invalid = {
        "schema_version": "ari.native-spmm-case/v1",
        "m": 2,
        "k": 3,
        "n": 1,
        "row_ptr": [0, 2, 1],
        "col_idx": [0, 9],
        "values": [1.0, 2.0],
        "b": [1.0, 1.0, 1.0],
        "c": [0.0, 0.0],
        "ldb": 1,
        "ldc": 1,
        "alpha": 1.0,
        "beta": 0.0,
        "dtype": "float64",
        "thread_count": 1,
        "duplicate_policy": "sum",
        "invalid_input_policy": "reject",
    }
    try:
        value = candidate(dict(invalid))
        rejected = isinstance(value, dict) and value.get("status") == "invalid_input"
    except (ValueError, IndexError):
        rejected = True
    except Exception:
        rejected = False
    results.append(
        NativeCaseResultV1(
            case_id="spmm-invalid-csr",
            category="invalid-input-policy",
            verdict="pass" if rejected else "fail",
            detail="invalid CSR rejected" if rejected else "invalid CSR was accepted",
            max_abs_error=0,
            max_rel_error=0,
        )
    )
    return build_report(
        "spmm",
        tier,
        results,
        oracle="independent CSR traversal with duplicate-index summation",
        error_model="dtype unit-roundoff gamma_(max row nnz) bound",
        negative_control=negative_control,
    )


__all__ = ["spmm_reference", "verify_spmm"]
