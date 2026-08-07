"""ARI-native Stencil oracle and hidden-case verifier."""

from __future__ import annotations

import random
from typing import Any, Literal

from ari.assurance.native_hpc_family import register_native_family
from ari.assurance.native_hpc_common import (
    NativeCandidate,
    NativeCaseResultV1,
    NativeHPCVerificationReportV1,
    build_report,
    run_case,
)


def _stencil_index(x: int, y: int, z: int, nx: int, ny: int) -> int:
    return (z * ny + y) * nx + x


def stencil_reference(case: dict[str, Any]) -> list[float]:
    nx, ny, nz = (int(case[name]) for name in ("nx", "ny", "nz"))
    iterations = int(case["iterations"])
    boundary = str(case["boundary"])
    if (
        min(nx, ny, nz) <= 0
        or iterations < 0
        or boundary not in {"fixed", "periodic"}
    ):
        raise ValueError("invalid Stencil case")
    current = [float(item) for item in case["input"]]
    if len(current) != nx * ny * nz:
        raise ValueError("Stencil input size mismatch")
    neighbours = (
        (-1, 0, 0),
        (1, 0, 0),
        (0, -1, 0),
        (0, 1, 0),
        (0, 0, -1),
        (0, 0, 1),
    )
    for _ in range(iterations):
        following = list(current)
        for z in range(nz):
            for y in range(ny):
                for x in range(nx):
                    edge = (
                        x in {0, nx - 1}
                        or y in {0, ny - 1}
                        or z in {0, nz - 1}
                    )
                    if boundary == "fixed" and edge:
                        continue
                    adjacent = []
                    for dx, dy, dz in neighbours:
                        xx, yy, zz = x + dx, y + dy, z + dz
                        if boundary == "periodic":
                            xx, yy, zz = xx % nx, yy % ny, zz % nz
                        elif not (
                            0 <= xx < nx and 0 <= yy < ny and 0 <= zz < nz
                        ):
                            continue
                        adjacent.append(
                            current[_stencil_index(xx, yy, zz, nx, ny)]
                        )
                    index = _stencil_index(x, y, z, nx, ny)
                    following[index] = (current[index] + sum(adjacent)) / (
                        1 + len(adjacent)
                    )
        current = following
    return current


def verify_stencil(
    candidate: NativeCandidate,
    *,
    tier: Literal["screen", "validate", "certify"] = "screen",
    seed: int = 9917,
    negative_control: bool = False,
) -> NativeHPCVerificationReportV1:
    rng = random.Random(seed)
    shapes = [(1, 1, 1), (2, 3, 5), (3, 5, 7)]
    iterations = (0, 1, 2) if tier == "screen" else (0, 1, 2, 5)
    if tier == "certify":
        shapes += [(5, 7, 11)]
        iterations += (9,)
    results: list[NativeCaseResultV1] = []
    index = 0
    for dtype in ("float32", "float64"):
        for nx, ny, nz in shapes:
            for boundary in ("fixed", "periodic"):
                for count in iterations:
                    values = [
                        rng.uniform(-2.0, 2.0) for _ in range(nx * ny * nz)
                    ]
                    if boundary == "periodic" and index % 7 == 0:
                        values = [1.25] * len(values)
                    case = {
                        "schema_version": "ari.native-stencil-case/v1",
                        "nx": nx,
                        "ny": ny,
                        "nz": nz,
                        "iterations": count,
                        "boundary": boundary,
                        "halo": 1,
                        "input": values,
                        "dtype": dtype,
                        "thread_count": (1, 2, 4)[index % 3],
                        "update_mode": ("out-of-place", "in-place")[index % 2],
                    }
                    category = (
                        "constant-field-metamorphic"
                        if len(set(values)) == 1
                        else "boundary-halo-trajectory"
                    )
                    results.append(
                        run_case(
                            case_id=f"stencil-{index:04d}",
                            category=category,
                            case=case,
                            expected=stencil_reference(case),
                            candidate=candidate,
                            accumulation=max(1, count * 7),
                            repeated=3 if tier != "screen" else 2,
                        )
                    )
                    index += 1
    return build_report(
        "stencil",
        tier,
        results,
        oracle=(
            "independent Jacobi reference trajectory with explicit "
            "halo/boundary semantics"
        ),
        error_model="dtype unit-roundoff gamma_(iterations*stencil-width) bound",
        negative_control=negative_control,
    )


class StencilFamily:
    """The stencil correctness family: hidden cases, an independent oracle, and
    the ABI its candidates are called through."""

    name = "stencil"

    def verify(self, candidate, **kwargs):
        return verify_stencil(candidate, **kwargs)

    def reference(self, case):
        return stencil_reference(case)

    def call_shared_library(self, path, case):
        from ari.assurance.drivers.shared_library import run_stencil

        return run_stencil(path, case)


STENCIL_FAMILY = register_native_family(StencilFamily())


__all__ = ["STENCIL_FAMILY", "StencilFamily", "stencil_reference", "verify_stencil"]
