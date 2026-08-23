"""ARI-native GEMM oracle and hidden-case verifier."""

from __future__ import annotations

import math
import random
from decimal import Decimal, localcontext
from typing import Any, Literal

from ari.assurance.native_hpc_family import register_native_family
from ari.assurance.native_hpc_common import (
    NativeCandidate,
    NativeCaseResultV1,
    NativeHPCVerificationReportV1,
    build_report,
    run_case,
)


def _matrix_value(storage: list[float], row: int, column: int, ld: int) -> float:
    return float(storage[row * ld + column])


def gemm_reference(case: dict[str, Any]) -> list[float]:
    m, n, k = (int(case[name]) for name in ("m", "n", "k"))
    ta, tb = bool(case["transpose_a"]), bool(case["transpose_b"])
    lda, ldb, ldc = (int(case[name]) for name in ("lda", "ldb", "ldc"))
    a, b, c = list(case["a"]), list(case["b"]), list(case["c"])
    alpha, beta = float(case["alpha"]), float(case["beta"])
    if (
        min(m, n, k) < 0
        or lda < (m if ta else k)
        or ldb < (k if tb else n)
        or ldc < n
    ):
        raise ValueError("invalid GEMM shape or leading dimension")
    out = list(map(float, c))
    with localcontext() as context:
        context.prec = 18 if case.get("dtype") == "float32" else 40
        da, db = Decimal(str(alpha)), Decimal(str(beta))
        for i in range(m):
            for j in range(n):
                terms: list[Decimal] = []
                special: float | None = None
                for p in range(k):
                    av = _matrix_value(a, p if ta else i, i if ta else p, lda)
                    bv = _matrix_value(b, j if tb else p, p if tb else j, ldb)
                    product = av * bv
                    if not math.isfinite(product):
                        special = product
                        break
                    terms.append(Decimal(str(av)) * Decimal(str(bv)))
                c0 = _matrix_value(c, i, j, ldc)
                if special is not None or not math.isfinite(c0):
                    product_sum = special if special is not None else 0.0
                    out[i * ldc + j] = alpha * product_sum + beta * c0
                else:
                    out[i * ldc + j] = float(
                        da * sum(terms, Decimal(0)) + db * Decimal(str(c0))
                    )
    return out


def _gemm_case(
    rng: random.Random,
    *,
    m: int,
    n: int,
    k: int,
    ta: bool,
    tb: bool,
    dtype: str,
    alpha: float,
    beta: float,
    threads: int,
    padding: int,
    alignment_offset: int,
) -> dict[str, Any]:
    lda = max(1, (m if ta else k) + padding)
    ldb = max(1, (k if tb else n) + padding)
    ldc = max(1, n + padding)
    a_rows = k if ta else m
    b_rows = n if tb else k

    def values(count: int) -> list[float]:
        return [rng.uniform(-1.25, 1.25) for _ in range(count)]

    return {
        "schema_version": "ari.native-gemm-case/v1",
        "m": m,
        "n": n,
        "k": k,
        "transpose_a": ta,
        "transpose_b": tb,
        "lda": lda,
        "ldb": ldb,
        "ldc": ldc,
        "alpha": alpha,
        "beta": beta,
        "dtype": dtype,
        "thread_count": threads,
        "alignment_offset": alignment_offset,
        "nan_inf_policy": "ieee-propagate",
        "a": values(a_rows * lda),
        "b": values(b_rows * ldb),
        "c": values(m * ldc),
    }


def verify_gemm(
    candidate: NativeCandidate,
    *,
    tier: Literal["screen", "validate", "certify"] = "screen",
    seed: int = 7301,
    negative_control: bool = False,
) -> NativeHPCVerificationReportV1:
    rng = random.Random(seed)
    shapes = [(0, 3, 5), (1, 1, 1), (2, 3, 5), (3, 5, 7)]
    if tier in {"validate", "certify"}:
        shapes += [(5, 7, 11), (7, 3, 17), (9, 11, 13)]
    if tier == "certify":
        shapes += [(17, 19, 23), (31, 7, 29)]
    results: list[NativeCaseResultV1] = []
    index = 0
    for dtype in ("float32", "float64"):
        for m, n, k in shapes:
            transpose_pairs = (
                (False, False),
                (True, False),
                (False, True),
                (True, True),
            )
            for ta, tb in transpose_pairs:
                alpha, beta = (
                    (1.0, 0.0),
                    (0.5, -0.25),
                    (0.0, 1.0),
                )[index % 3]
                case = _gemm_case(
                    rng,
                    m=m,
                    n=n,
                    k=k,
                    ta=ta,
                    tb=tb,
                    dtype=dtype,
                    alpha=alpha,
                    beta=beta,
                    threads=(1, 2, 4)[index % 3],
                    padding=index % 3,
                    alignment_offset=(0, 1, 3)[index % 3],
                )
                category = (
                    "zero-small-prime-odd"
                    if min(m, n, k) <= 1
                    else "shape-transpose-leading-dimension"
                )
                results.append(
                    run_case(
                        case_id=f"gemm-{index:04d}",
                        category=category,
                        case=case,
                        expected=gemm_reference(case),
                        candidate=candidate,
                        accumulation=k,
                        repeated=3 if tier != "screen" else 2,
                    )
                )
                index += 1
    special = _gemm_case(
        rng,
        m=2,
        n=2,
        k=2,
        ta=False,
        tb=False,
        dtype="float64",
        alpha=1.0,
        beta=0.0,
        threads=2,
        padding=1,
        alignment_offset=1,
    )
    special["a"][0] = math.nan
    special["b"][special["ldb"] + 1] = math.inf
    results.append(
        run_case(
            case_id="gemm-special-values",
            category="nan-inf-policy",
            case=special,
            expected=gemm_reference(special),
            candidate=candidate,
            accumulation=2,
        )
    )
    return build_report(
        "gemm",
        tier,
        results,
        oracle="decimal accumulation over an independently indexed row-major GEMM",
        error_model="dtype unit-roundoff gamma_k bound plus absolute underflow floor",
        negative_control=negative_control,
    )


class GemmFamily:
    """The gemm correctness family: hidden cases, an independent oracle, and
    the ABI its candidates are called through."""

    name = "gemm"

    def verify(self, candidate, **kwargs):
        return verify_gemm(candidate, **kwargs)

    def reference(self, case):
        return gemm_reference(case)

    def call_shared_library(self, path, case):
        from ari.assurance.drivers.shared_library import run_gemm

        return run_gemm(path, case)


GEMM_FAMILY = register_native_family(GemmFamily())


__all__ = ["GEMM_FAMILY", "GemmFamily", "gemm_reference", "verify_gemm"]
