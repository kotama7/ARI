"""GEMM performance verification: does the candidate regress against the frozen
reference, and is it still right?

The property is ``performance-regression`` by ``benchmark-comparison``, so the
verdict is a comparison against a pinned denominator, not an absolute number.
The absolute numbers travel in ``measurements`` because a ratio alone cannot
answer "is 33 GFLOPS too low", but they are not what decides the verdict.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path
from typing import Any, Callable, Literal

import numpy as np

from ari.assurance.native_perf_common import (
    TIER_REPETITIONS,
    PerfInfrastructureError as _PerfInfra,
    NativePerfReportV1,
    PerfBuildError,
    PerfCaseResultV1,
    PerfInfrastructureError,
    PerfRepetitionV1,
    compile_binary,
    crosses_compiler_boundary,
    default_compiler,
    kernels_root,
    load_case_set,
    measurement_placement,
    median,
    relative_spread,
    isa_flags_for,
    measurement_environment,
    resolve_compiler,
    runtime_libs_for,
    screen_flags,
    toolchain_identity,
)

#: WHICH PROBLEMS is data, not code. The shapes live in a pinned case set the
#: manifest names and digests; see load_case_set. A theme that needs other sizes
#: registers a harness against another set rather than passing shapes through a
#: request, because the registration evidence is established at a size and does
#: not transfer.
DEFAULT_CASE_SET = "native-perf-gemm-cases/v1@scored-2026q3"

#: The only global symbol a candidate kernel object may define. Declared
#: beside the kernel, not in a table in core: which symbol a kernel exports
#: is knowledge that belongs with the kernel.
ENTRY_POINT = "gemm"

#: The reference is built the way a competent user of this toolchain would build
#: it, so the denominator is not handicapped relative to the candidates it is the
#: bar for.
_REFERENCE_FLAGS_AARCH64 = ("-march=armv8.2-a+sve", "-ffast-math")
_REFERENCE_FLAGS_OTHER = ("-ffast-math",)

#: Backward-error constant for the residual bound, matching the correctness
#: verifier's model.
_C_EPS = 8.0
_FP64_U = 2.0**-53


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


def verify_gemm_performance(
    candidate_source: Path,
    *,
    tier: Literal["screen", "validate", "certify"] = "screen",
    seed: int = 0,
    dataset_revision: str = DEFAULT_CASE_SET,
    candidate_compiler: str | None = None,
    candidate_flags: str | None = None,
    regression_threshold: float = 1.0,
    run_timeout: float = 300.0,
    negative_control: bool = False,
) -> NativePerfReportV1:
    """Measure ``candidate_source`` against the frozen reference.

    ``regression_threshold`` is the ratio the candidate must reach to pass. The
    default of 1.0 states the property literally: not slower than the frozen
    reference. A harness manifest supplies the value it registered.
    """
    from ari.assurance.native_perf_common import run_timed

    case_set, dataset_digest = load_case_set(dataset_revision)
    if case_set.kind != "gemm":
        raise PerfInfrastructureError(
            f"case set {dataset_revision!r} is for {case_set.kind!r}, not gemm")
    cases = tuple(tuple(int(v) for v in case) for case in case_set.cases)
    reps = TIER_REPETITIONS[tier]
    kdir = kernels_root() / "gemm"
    reference_source = kdir / "reference_gemm.c"
    if not reference_source.is_file():
        raise PerfInfrastructureError(f"frozen reference missing: {reference_source}")

    status, resolved = resolve_compiler(candidate_compiler)
    boundary = crosses_compiler_boundary(status, resolved)
    accepted, rejected = screen_flags(candidate_flags)
    default_cc = default_compiler()
    default_identity = toolchain_identity(default_cc)
    candidate_identity = {**toolchain_identity(resolved),
                          "requested": candidate_compiler, "status": status}
    # The candidate's process may need its selected compiler's runtime on the
    # loader path; the anchor's must not be given anything extra, because the
    # denominator has to stay exactly the object it has always been.
    candidate_libs = runtime_libs_for(resolved) if boundary else None
    base = ("-O3", "-fopenmp", *isa_flags_for(resolved))

    results: list[PerfCaseResultV1] = []
    with tempfile.TemporaryDirectory() as raw_td:
        build = Path(raw_td)
        # The anchor is ALWAYS the default toolchain. It is the published
        # denominator and must stay exactly the object it has always been.
        anchor_exe = compile_binary(
            kind="gemm", role="reference", source=reference_source, out_dir=build,
            compiler=default_cc, reference_flags=reference_flags(),
            entry_point=ENTRY_POINT)
        candidate_exe = compile_binary(
            kind="gemm", role="candidate", source=candidate_source, out_dir=build,
            compiler=resolved, extra_flags=accepted,
            entry_point=ENTRY_POINT)
        matched_exe = None
        if boundary:
            matched_exe = compile_binary(
                kind="gemm", role="reference_matched", source=reference_source,
                out_dir=build, compiler=resolved, extra_flags=accepted,
                entry_point=ENTRY_POINT)

        problem = build / "problem.bin"
        # ONE OUTPUT FILE PER ROLE. Sharing one meant the anchor overwrote the
        # candidate's answer, so the correctness check had to run between the two
        # timed launches -- see below.
        outputs = {role: build / f"{role}.bin"
                   for role in ("candidate", "reference", "reference_matched")}
        timing = build / "timing.bin"

        for shape in cases:
            n, p, m = shape
            case_id = "x".join(str(v) for v in shape)
            repetitions: list[PerfRepetitionV1] = []
            ratios: list[float] = []
            verdict = "pass"
            detail = "not slower than the frozen reference"
            for index in range(reps):
                input_seed = seed * 100003 + index
                a, b = gen_problem(shape, input_seed)
                _write_problem(problem, a, b)
                # ALL TIMED LAUNCHES FIRST, THEN THE ORACLE. The oracle is a
                # multi-threaded numpy GEMM running in THIS process; sitting it
                # between the candidate and the matched reference put a
                # full-size BLAS call on the same cores in between, and only on
                # one side of the comparison -- so it moved toolchain_gain.
                # Nothing but the timed processes runs inside this block.
                try:
                    if (index + seed) % 2 == 0:
                        order = (("candidate", candidate_exe), ("reference", anchor_exe))
                    else:
                        order = (("reference", anchor_exe), ("candidate", candidate_exe))
                    seconds: dict[str, float] = {}
                    for role, exe in order:
                        seconds[role] = run_timed(
                            exe, problem, outputs[role], timing,
                            timeout=run_timeout, role=role,
                            ld_library_path=(candidate_libs
                                             if role != "reference" else None))
                    if matched_exe is not None:
                        try:
                            seconds["reference_matched"] = run_timed(
                                matched_exe, problem, outputs["reference_matched"],
                                timing, timeout=run_timeout,
                                role="reference_matched",
                                ld_library_path=candidate_libs)
                        except _PerfInfra:
                            # A matched-run failure must not discard an anchor
                            # measurement that already succeeded.
                            pass
                    t_cand = seconds["candidate"]
                    t_ref = seconds["reference"]
                    c_out = np.fromfile(outputs["candidate"], dtype=np.float64)
                except PerfBuildError as exc:
                    verdict, detail = "fail", str(exc)
                    break
                if c_out.size != n * m:
                    verdict, detail = "fail", "candidate wrote the wrong output size"
                    break
                correct, worst = _residual_ok(c_out.reshape(n, m), a, b)
                if negative_control:
                    # A negative control must be REFUSED. Corrupting the timing
                    # would be indistinguishable from a fast kernel, so the
                    # control corrupts the ANSWER, which the oracle catches.
                    correct = False
                if not correct:
                    verdict = "fail"
                    detail = f"candidate output failed the residual bound ({worst:.3g}x)"
                    repetitions.append(PerfRepetitionV1(
                        index=index, input_seed=input_seed,
                        credited_seconds=t_cand, reference_seconds=t_ref,
                        speedup=t_ref / t_cand, correct=False, max_rel_error=worst))
                    break
                matched_seconds = seconds.get("reference_matched")
                speedup_matched = None
                gain = None
                if matched_seconds is not None:
                    speedup_matched = matched_seconds / t_cand
                    gain = (t_ref / t_cand) / speedup_matched
                ratio = t_ref / t_cand
                ratios.append(ratio)
                repetitions.append(PerfRepetitionV1(
                    index=index, input_seed=input_seed,
                    credited_seconds=t_cand, reference_seconds=t_ref, speedup=ratio,
                    matched_seconds=matched_seconds, speedup_matched=speedup_matched,
                    toolchain_gain=gain, correct=True, max_rel_error=worst))
            if verdict == "pass":
                if not ratios:
                    verdict, detail = "inconclusive", "no repetition completed"
                    centre = 0.0
                else:
                    centre = median(ratios)
                    if centre < regression_threshold:
                        verdict = "fail"
                        detail = (f"{centre:.4g}x of the frozen reference, below the "
                                  f"{regression_threshold:g}x threshold")
            else:
                centre = median(ratios) if ratios else 0.0
            matched_values = [r.speedup_matched for r in repetitions
                              if r.speedup_matched is not None]
            gains = [r.toolchain_gain for r in repetitions if r.toolchain_gain is not None]
            results.append(PerfCaseResultV1(
                case_id=case_id, verdict=verdict, detail=detail, speedup=centre,
                speedup_matched=median(matched_values) if matched_values else None,
                toolchain_gain=median(gains) if gains else None,
                relative_spread=relative_spread(ratios),
                repetitions=tuple(repetitions)))

    overall = "pass"
    if any(item.verdict == "fail" for item in results):
        overall = "fail"
    elif any(item.verdict == "inconclusive" for item in results) or not results:
        overall = "inconclusive"
    if not case_set.resolves and overall == "pass":
        # A cheap set can show that a candidate built and was right. It cannot
        # support "did not regress": at this size the measurement's own spread
        # swamps the difference the verdict claims to have found.
        overall = "inconclusive"
    return NativePerfReportV1.create(
        kind="gemm", tier=tier, verdict=overall, case_results=tuple(results),
        regression_threshold=regression_threshold,
        default_toolchain=default_identity, candidate_toolchain=candidate_identity,
        crossed_compiler_boundary=boundary,
        base_flags=base, reference_flags=reference_flags(),
        accepted_flags=accepted, rejected_flags=rejected,
        environment=measurement_environment(),
        dataset_revision=case_set.revision, dataset_sha256=dataset_digest,
        placement=measurement_placement(), negative_control=negative_control)


def gemm_reference_source() -> Path:
    """The frozen reference, which is also the natural clean control: scoring it
    as the candidate must give a ratio of about 1."""
    return kernels_root() / "gemm" / "reference_gemm.c"


__all__ = ["DEFAULT_CASE_SET", "ENTRY_POINT", "gemm_reference_source", "gen_problem", "reference_flags",
           "verify_gemm_performance"]
