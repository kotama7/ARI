"""Hardware counters for the region a candidate is SCORED on. Never a score.

WHY IT IS SEPARATE FROM THE VERDICT. A profile says WHY a kernel is slow;
``performance-regression`` says WHETHER it regressed. Wiring the first into the
second would be a second scoring channel with none of the first one's
anti-gaming surface — the counter tool runs outside the sandboxed compile, its
numbers are not reproducible to a threshold, and a candidate that could move
them would be judged on an unguarded number. So a profile carries
``scored: false``, and nothing here writes a field the evaluator reads.

WHY THE REGION AND NOT THE PROCESS. The timed window is one kernel call; around
it in the same process sit the problem read, the serial NaN poison of the output
and the write-out. Counting the whole process was measured at 7.16x the region's
cycles on an aarch64 compute node, and it drags the L2D ratio toward "memory
bound" for every candidate, because the poison pass is pure write-allocate
traffic. The profiled driver therefore MARKS the region and the counter tool
gates on those marks: measured, adding 7.2x more untimed work around the region
moved the gated count by 0.07% and the ungated count by 7.16x.

WHAT THE UNITS ARE, MEASURED. On the aarch64 compute nodes the L1 data line is
256 B — established by counting lines under a stride sweep, where refills per
access saturate at the line size and the ratio between adjacent strides must
equal max(S,L)/max(2S,L). L2D_CACHE_REFILL does NOT tick per L1 line: it reads
~2.0 per line while both 128 B halves are demanded and ~1.0 when one is, so it
ticks per 128 B granule. Applying the L1 line to it reports roughly twice the
traffic. Neither unit is hardcoded here: the tool takes what the OS reports and
suppresses a ratio it cannot ground.

WHAT IT IS BLIND TO. The scored arrays are first-touched OUTSIDE the timed
window, serially, by the frozen driver. Page-fault, TLB and NUMA-placement work
is therefore mostly not in the counted region; only scratch a candidate
allocates itself faults inside. A profile cannot be read as evidence about
placement.

COLD AND ONCE, like the score. No warmup and no in-process repetition: a warm
profile would describe a regime the score never measures. ``reps`` repeats the
PROCESS, with the scored input-seed formula, so profile point r lines up with
scored repetition r.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from ari.assurance.native_perf_common import (
    NativePerfReportV1,  # noqa: F401  (re-exported shape reference)
    PerfBuildError,
    PerfFamily,
    PerfInfrastructureError,
    compile_binary,
    crosses_compiler_boundary,
    default_compiler,
    isa_flags_for,
    kernels_root,
    load_case_set,
    measurement_environment,
    measurement_placement,
    resolve_compiler,
    runtime_libs_for,
    screen_flags,
    toolchain_identity,
)
from ari.assurance.native_perf_family import get_family
from ari.assurance.problems import LoadedProblemV1
from ari.protocols.integrity import DigestBoundModel, StrictModel


class ProfilePointV1(StrictModel):
    """One gated, counted process."""

    case_id: str
    input_seed: int
    credited_seconds: float | None = None
    counters: dict[str, Any] | None = None
    #: The profiled run used to be the one run whose output nobody looked at. A
    #: candidate that behaves differently under the gate — deliberately, or by
    #: accident through some env-keyed path — would then produce a profile of a
    #: program that was never scored, and nothing would say so.
    output_correct: bool | None = None
    output_rel_error: float | None = None
    error: str | None = None


class NativePerfProfileV1(DigestBoundModel):
    """A profile of the scored region. Diagnostic; never a verdict."""

    _digest_field = "profile_digest"

    schema_version: Literal["ari.native-perf-profile/v1"] = "ari.native-perf-profile/v1"
    #: The same pinned identity the verdict carries, so a profile and a score can
    #: be shown to be about one question rather than assumed to be.
    problem_id: str
    problem_revision: str
    problem_digest: str
    family: PerfFamily
    scored: Literal[False] = False
    points: tuple[ProfilePointV1, ...]
    dataset_revision: str
    dataset_sha256: str
    reps: int = Field(ge=1)
    #: Per case, never pooled: two shapes have genuinely different IPC, and
    #: pooling them reports that difference as measurement noise.
    ratio_spread: dict[str, dict[str, Any]]
    default_toolchain: dict[str, Any]
    candidate_toolchain: dict[str, Any]
    #: The counter tool lives inside the driver digest, but a profile is read on
    #: its own, so it carries its own provenance too.
    counter_tool: dict[str, Any]
    environment: dict[str, Any]
    placement: dict[str, Any]
    profile_digest: str = Field(default="")


def counter_tool_source() -> Path:
    return kernels_root() / "tools" / "region_counters.c"


def build_counter_tool(build_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Build the counter tool, and record what actually ran.

    An operator-supplied prebuilt binary is honoured, but then the SOURCE digest
    does not describe what ran — recording it alone made the one field a reader
    would use to identify the tool a false statement.
    """
    import hashlib
    import os

    source = counter_tool_source()
    if not source.is_file():
        raise PerfInfrastructureError(f"counter tool source not found: {source}")
    source_digest = f"sha256:{hashlib.sha256(source.read_bytes()).hexdigest()}"
    given = os.environ.get("ARI_REGION_COUNTERS")
    if given and Path(given).is_file():
        return Path(given), {
            "source_sha256": source_digest,
            "binary_sha256": f"sha256:{hashlib.sha256(Path(given).read_bytes()).hexdigest()}",
            "built_from_source": False,
            "note": "ARI_REGION_COUNTERS supplied a prebuilt binary; the source "
                    "digest describes the tree, not necessarily what ran",
        }
    exe = build_dir / "region_counters"
    cc = os.environ.get("ARI_PROBE_CC") or default_compiler()
    completed = subprocess.run([cc, "-O2", str(source), "-o", str(exe)],
                               capture_output=True, text=True, timeout=180)
    if completed.returncode != 0:
        raise PerfInfrastructureError(
            f"could not build the counter tool: {completed.stderr.strip()[-300:]}")
    return exe, {
        "source_sha256": source_digest,
        "binary_sha256": f"sha256:{hashlib.sha256(exe.read_bytes()).hexdigest()}",
        "built_from_source": True,
    }


def _spread(points: list[ProfilePointV1], key: str) -> dict[str, dict[str, Any]]:
    by_case: dict[str, list[float]] = {}
    for point in points:
        value = ((point.counters or {}).get("ratios") or {}).get(key)
        if isinstance(value, (int, float)):
            by_case.setdefault(point.case_id, []).append(float(value))
    out: dict[str, dict[str, Any]] = {}
    for case, values in by_case.items():
        if len(values) < 2:
            continue
        centre = statistics.median(values)
        out[case] = {
            "n": len(values), "median": centre,
            "relative_spread": ((max(values) - min(values)) / centre
                                if centre else None),
        }
    return out


def profile_problem(
    problem: str | LoadedProblemV1,
    candidate_source: Path,
    *,
    dataset_revision: str | None = None,
    seed: int = 0,
    reps: int = 3,
    candidate_compiler: str | None = None,
    candidate_flags: str | None = None,
    line_bytes: int | None = None,
    l2_granule_bytes: int | None = None,
    run_timeout: float = 300.0,
) -> NativePerfProfileV1:
    """Counters for the candidate's scored region, over a pinned case set.

    ``reps`` defaults to 3, not 1: one point has no spread, and a ratio quoted
    without one is how this study previously mistook run-to-run variance for an
    effect. The size comes from the same pinned case sets the verdict uses, so a
    profile and a score can be read next to each other.

    A problem that declares no ``profiled_driver`` cannot be profiled, and says
    so rather than being profiled with the scored driver -- which has no counter
    gate, so every number would describe the whole process instead of the region.
    """
    import numpy as np

    from ari.assurance.native_perf_common import run_timed
    from ari.assurance.native_perf_measure import resolve_problem

    loaded = resolve_problem(problem)
    definition = loaded.definition
    family = get_family(definition.family)
    profiled_driver = definition.scaffolding.profiled_driver
    if not profiled_driver:
        raise PerfInfrastructureError(
            f"problem {definition.revision!r} declares no profiled driver, so "
            f"its scored region is not marked and cannot be counted")

    case_set, dataset_digest = load_case_set(dataset_revision or definition.case_set)
    if case_set.kind != definition.family:
        raise PerfInfrastructureError(
            f"case set {case_set.revision!r} is for family {case_set.kind!r}, "
            f"but problem {definition.revision!r} is {definition.family!r}")

    status, resolved = resolve_compiler(candidate_compiler)
    accepted, _rejected = screen_flags(candidate_flags)
    boundary = crosses_compiler_boundary(status, resolved)
    candidate_libs = runtime_libs_for(resolved) if boundary else None

    points: list[ProfilePointV1] = []
    with tempfile.TemporaryDirectory() as raw:
        build = Path(raw)
        counters, tool_record = build_counter_tool(build)
        launcher = [str(counters), "--gate", "--json"]
        if line_bytes:
            launcher += ["--line-bytes", str(int(line_bytes))]
        if l2_granule_bytes:
            launcher += ["--l2-granule-bytes", str(int(l2_granule_bytes))]
        launcher.append("--")
        exe = compile_binary(
            include_dir=loaded.directory,
            driver=loaded.path(profiled_driver),
            entry_point=definition.entry_point,
            role="candidate", source=candidate_source, out_dir=build,
            compiler=resolved, extra_flags=accepted, tag="candidate_profiled")

        instance_path = build / "problem.bin"
        output = build / "profiled.bin"
        timing = build / "timing.bin"
        for raw_case in case_set.cases:
            case = tuple(raw_case)
            case_id = "x".join(str(v) for v in case)
            expected = family.output_elements(case)
            for index in range(int(reps)):
                input_seed = seed * 100003 + index
                instance = family.generate(case, input_seed)
                family.write(instance_path, instance)
                captured: dict[str, str] = {}
                credited = None
                error = None
                parsed = None
                correct = None
                worst = None
                try:
                    credited = run_timed(
                        exe, instance_path, output, timing, timeout=run_timeout,
                        # NOT "candidate". The launcher here is the counter tool,
                        # and ``_fault`` types a candidate-role failure as a
                        # PerfBuildError -- documented as "a candidate fault, not
                        # a substrate fault". The counter tool opens PERF_TYPE_RAW
                        # with ARMv8 PMUv3 encodings, so on any other machine it
                        # fails and the candidate was blamed for the host. A
                        # profile is never scored; it must not be able to blame
                        # the candidate for anything.
                        role="profiled", ld_library_path=candidate_libs,
                        launcher=tuple(launcher), capture=captured)
                except (PerfBuildError, PerfInfrastructureError) as exc:
                    error = f"{type(exc).__name__}: {exc}"
                raw_out = (captured.get("stdout") or "").strip()
                if raw_out:
                    try:
                        parsed = json.loads(raw_out.splitlines()[-1])
                    except ValueError:
                        error = error or f"counter output was not JSON: {raw_out[:160]}"
                elif error is None:
                    error = "the counter tool produced no output"
                if credited is not None:
                    got = np.fromfile(output, dtype=np.float64)
                    if got.size == expected:
                        correct, worst = family.check(got, case, instance)
                    else:
                        correct, worst = False, float("inf")
                points.append(ProfilePointV1(
                    case_id=case_id, input_seed=input_seed,
                    credited_seconds=credited, counters=parsed,
                    output_correct=correct, output_rel_error=worst, error=error))

    return NativePerfProfileV1.create(
        problem_id=definition.id, problem_revision=definition.revision,
        problem_digest=loaded.digest, family=definition.family,
        points=tuple(points),
        dataset_revision=case_set.revision, dataset_sha256=dataset_digest,
        reps=int(reps),
        ratio_spread={key: _spread(points, key) for key in
                      ("ipc", "l1d_refill_per_access",
                       "l2d_refill_per_l1d_refill", "l1_fill_bytes_per_cycle",
                       "l2_refill_bytes_per_cycle")},
        default_toolchain=toolchain_identity(default_compiler()),
        candidate_toolchain={**toolchain_identity(resolved),
                             "requested": candidate_compiler, "status": status},
        counter_tool=tool_record,
        environment=measurement_environment(),
        placement=measurement_placement())


__all__ = [
    "NativePerfProfileV1",
    "ProfilePointV1",
    "build_counter_tool",
    "counter_tool_source",
    "profile_problem",
]
