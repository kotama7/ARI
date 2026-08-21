"""Correctness of a candidate against a PINNED PROBLEM's own contract.

WHY THIS EXISTS ALONGSIDE ``native_hpc``. Both answer "is this kernel right",
and both name the interface contract ``gemm-c-abi/v1`` -- but they are contracts
with different things, and the shared name is the trap. ``hpc/gemm-correctness``
resolves ``ari_gemm_f32``/``ari_gemm_f64`` out of a shared library over a
13-argument status-returning ABI, in two dtypes, across 33 cases. A candidate
submitted to ``gemm-dense-fp64`` exports ``gemm``, six arguments, no status,
fp64 only, because that is what ``gemm_kernel.h`` says. Handing one verifier the
other's target is not a near miss: measured, the ARI-native verifier reported
33/33 ``missing ari_gemm_f32 symbol`` with every error 0.0. A governed run
therefore read a candidate that was never loaded as a candidate that was checked
and found wanting -- the failure mode this whole subsystem keeps producing,
where a mismatch surfaces as a verdict about the candidate instead of an error.

WHAT IT REUSES, AND WHY THAT IS THE POINT. The build, the flag screen, the
object audit and the launch are ``native_perf_common``'s, and the oracle is the
FAMILY's -- the same residual bound the performance harness credits time behind.
So this is not a second opinion about correctness; it is the same opinion,
reported on its own instead of only as a precondition for a stopwatch.

WHAT IT DELIBERATELY DOES NOT HAVE.

* No anchor and no denominator. The gemm family's oracle is a backward-error
  bound against a NumPy-computed ``A @ B``, not a comparison with the frozen
  reference, so correctness needs no competent baseline to be checked against.
* No timing, anywhere in the report. A correctness verdict carrying a number of
  seconds would be read as a performance result taken without a denominator.
* No registered placement. ``NativePerfDriver.prepare`` refuses to run anywhere
  but the machine its evidence was established on, because a timed verdict does
  not transfer -- measured, the same commit scored 15/15 on one node and 13/15
  on another. A residual bound is not a statement about a machine, so this
  harness can be registered where a performance harness cannot.

WHAT IT INHERITS THAT IT DOES NOT WANT, stated because it changes what a verdict
MEANS. ``run_timed`` is the audited launch path -- the private timing file, the
credit floor, the forged-timing checks -- and those guards apply whether or not
anybody reads the clock. Nothing here reads it. So a candidate refused by a
timing guard is recorded as ``fail`` with "candidate run did not complete", not
as a numerical failure: measured, a kernel whose body is empty is refused for
crediting 5.5e-08s against 0.039s of wall clock, and never reaches the oracle
that would have caught its untouched NaN output. The verdict is the same and the
attribution is honest, but the oracle is not what produced it. Forking the
launcher to drop the guards would fork the audited path, which is worse than
saying this plainly.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import Field

from ari.assurance.native_perf_common import (
    TIER_REPETITIONS,
    PerfBuildError,
    PerfInfrastructureError,
    PerfTier,
    compile_binary,
    crosses_compiler_boundary,
    load_case_set,
    measurement_environment,
    measurement_placement,
    resolve_compiler,
    finite_ratio,
    sandbox_record,
    run_timed,
    runtime_libs_for,
    screen_flags,
    toolchain_identity,
)
from ari.assurance.native_perf_family import get_family
from ari.assurance.problems import LoadedProblemV1, load_problem
from ari.protocols.integrity import (DigestBoundModel, StrictModel,
                                     bytes_digest)


def resolve_problem(problem: str | LoadedProblemV1) -> LoadedProblemV1:
    """Same two lines as ``native_perf_measure``'s, deliberately not imported.

    Taking it from there would put the whole timed measurement loop inside this
    driver's content address, so a change to how the anchor is launched would
    re-register a harness that never launches an anchor.
    """
    return problem if isinstance(problem, LoadedProblemV1) else load_problem(problem)


#: The two properties this verifier decides, and the order a report lists them.
#: Named here rather than in the driver because what an instrument establishes
#: is a property of the instrument.
CORRECTNESS_PROPERTIES: tuple[str, ...] = (
    "numerical-equivalence",
    "interface-conformance",
)

#: The role every build and launch on this path uses. Named once so the prefixes
#: below cannot drift from the role the compile actually ran under.
_CANDIDATE_ROLE = "candidate"

#: PREFIXES of a build failure that mean the CONTRACT was broken rather than the
#: compiler being unhappy. ``audit_kernel_object`` raises ``PerfBuildError`` for
#: both, and the two are different findings: a candidate that does not compile
#: has not been shown to conform to anything, while a candidate that compiles and
#: exports a constructor has been shown NOT to.
_INTERFACE_FAULTS = (
    f"{_CANDIDATE_ROLE} kernel exports symbols other than",
    f"{_CANDIDATE_ROLE} kernel runs code outside the measured call",
)


class ProblemCorrectnessCaseResultV1(StrictModel):
    """One scored shape. Every measurement is OPTIONAL, and that is the point.

    THE DEFECT THIS SHAPE FIXES. These fields were plain scalars initialised to
    0.0 / 0 / True before the launch loop, and emitted verbatim when no launch
    completed -- so a candidate that never ran published
    ``worst_residual_ratio: 0.0``, which reads as "exactly zero error", and
    ``output_elements_written: 0``, which reads as "the kernel wrote nothing"
    even when the truth was that nothing was ever read. An attestation carried
    those numbers as measurements. ``None`` means "not observed", which is a
    thing the reader can act on; a default dressed as a measurement is not.
    """

    case_id: str
    verdict: Literal["pass", "fail", "inconclusive"]
    detail: str
    #: Worst ratio to the family's residual bound over this case's repetitions.
    #: 1.0 is exactly at the bound; the verdict is the family's, not a
    #: comparison written here.
    #:
    #: ``None`` when no FINITE ratio was observed -- either nothing ran, or the
    #: oracle returned a non-finite ratio. Both happen: the family oracle returns
    #: ``inf`` for a candidate whose output contains an infinity and ``nan`` for
    #: one that leaves the driver's poisoned buffer untouched. Those are not
    #: representable in JSON, and this field used to be a bare ``float``, so
    #: ``create`` raised "Out of range float values are not JSON compliant"
    #: INSIDE the verifier -- turning a wrong candidate into a crashed worker,
    #: which the driver reports as an infrastructure outage rather than as the
    #: failure it is. ``detail`` says which condition was seen.
    worst_residual_ratio: float | None = Field(default=None, ge=0)
    output_elements_expected: int = Field(ge=0)
    #: ``None`` when no output was read at all (the launch failed).
    output_elements_written: int | None = Field(default=None, ge=0)
    repetitions_requested: int = Field(ge=0)
    repetitions_completed: int = Field(ge=0)
    #: Byte-identical output across two launches of the SAME input. Recorded,
    #: never a failure: an OpenMP reduction may legitimately reassociate, and a
    #: harness that failed a candidate for it would be enforcing a property this
    #: problem never asked for. See ``deterministic`` on the report. ``None``
    #: when the repeat launch never happened.
    repeat_identical: bool | None = None


class NativeProblemCorrectnessReportV1(DigestBoundModel):
    _digest_field = "report_digest"

    schema_version: Literal["ari.native-problem-correctness-report/v1"] = (
        "ari.native-problem-correctness-report/v1"
    )
    #: WHICH QUESTION. A correctness verdict against an unnamed problem is not
    #: attributable, and the manifest pins these three.
    problem_id: str
    problem_revision: str
    problem_digest: str
    family: str
    entry_point: str
    #: WHICH CANDIDATE. Every other field here is about the problem, the case
    #: set, the toolchain or the machine, so without this the report describes
    #: the question and never the answer: measured, the frozen reference, the
    #: correct-but-slow control and the naive seed produced three BYTE-IDENTICAL
    #: reports, and therefore one ``report_digest``. A manifest pins
    #: ``negative_control_report_digest`` and an attestation cites
    #: ``report_digest`` to say what was verified; neither could distinguish the
    #: candidate it covered from any other candidate with the same verdict.
    candidate_digest: str
    tier: Literal["screen", "validate", "certify"]
    verdict: Literal["pass", "fail", "inconclusive"]
    case_results: tuple[ProblemCorrectnessCaseResultV1, ...]
    #: Per property, because the driver must not re-derive from a summary what
    #: the verifier already knows. A build failure or an export violation fails
    #: BOTH -- nothing ran, so equivalence is not established either, and
    #: "inconclusive" would let an uncompilable candidate sit outside both the
    #: pass set and the fail set. A candidate that runs and misses the bound
    #: fails equivalence alone; one that writes the wrong element count fails
    #: conformance too.
    property_verdicts: dict[str, str]
    #: Every case's output was byte-identical across a repeat launch. An
    #: observation, not a property: nothing here declares reproducibility, so
    #: nothing may be attested for it.
    deterministic: bool
    oracle: str
    error_model: str
    build_error: str | None
    interface_error: str | None
    accepted_flags: tuple[str, ...]
    rejected_flags: tuple[str, ...]
    candidate_toolchain: dict[str, str | None]
    crossed_compiler_boundary: bool
    dataset_revision: str
    dataset_sha256: str
    environment: dict[str, Any]
    #: Recorded, NOT gated -- unlike the performance driver, which refuses to run
    #: off its registered placement. Kept because "where did this run" is
    #: provenance for any verdict; absent from ``registered_placement`` because a
    #: residual bound does not transfer any less across machines than it holds on
    #: one.
    placement: dict[str, Any]
    #: What the launch actually got, recorded from the launch that happened
    #: rather than from a probe taken separately. An untrusted candidate runs
    #: here; "was it isolated" is not answerable after the fact, and the launch
    #: already decides it.
    sandbox: dict[str, Any]
    #: A label. The controls this harness registers against are the problem's own
    #: wrong kernel, so nothing needs to be synthetically corrupted, and this
    #: never alters a verdict.
    negative_control: bool
    #: Covers every field above, so nothing here may vary between two runs that
    #: reached the same verdict. THIS IS A CONSTRAINT, not a description, and
    #: what enforces it is the registration's stability gate: for a verifier
    #: declared deterministic, ``probe_repeatedly`` requires the clean control to
    #: be BYTE-IDENTICAL across runs, and this digest is what it compares.
    #: Recording the ambient run-queue length here made the harness
    #: unregisterable -- measured, the gate reported "no repeated-run evidence"
    #: because a live load reading is a measurement of the machine, not of the
    #: answer. A manifest also pins ``negative_control_report_digest``, but
    #: nothing recomputes that field and compares it, so it is recorded rather
    #: than enforced and it is not a second guard. The performance report carries
    #: the load reading, where the verdict IS a time and the load is the
    #: confound; a residual bound has no duration for it to contaminate.
    report_digest: str


def _classify_build_failure(message: str) -> tuple[str | None, str | None]:
    """``(build_error, interface_error)`` for one ``PerfBuildError``.

    Anchored to the START of the message, not searched anywhere in it. A compile
    failure's message embeds the last 400 characters of the COMPILER'S STDERR,
    which is text the candidate controls: a candidate containing
    ``#error candidate kernel exports symbols other than 'gemm'`` failed to
    compile and was recorded as a proven interface violation, which is a finding
    about the artifact that nothing established.
    """
    for fragment in _INTERFACE_FAULTS:
        if message.startswith(fragment):
            return None, message
    return message, None


def verify_problem_correctness(
    problem: str | LoadedProblemV1,
    candidate_source: str | Path,
    *,
    tier: PerfTier = "screen",
    seed: int = 0,
    dataset_revision: str | None = None,
    candidate_compiler: str | None = None,
    candidate_flags: str | None = None,
    run_timeout: float = 300.0,
    negative_control: bool = False,
) -> NativeProblemCorrectnessReportV1:
    """Check ``candidate_source`` against the pinned problem's own oracle.

    ``dataset_revision`` defaults to the problem's declared case set and must
    belong to the problem's family, or the shapes would be handed to an oracle
    they mean nothing to. Unlike the performance path there is no ``resolves``
    requirement: a case set too small to separate two timings still separates a
    right answer from a wrong one, which is why registration for this harness
    does not need an exclusive node.
    """
    loaded = resolve_problem(problem)
    definition = loaded.definition
    family = get_family(definition.family)
    source_path = Path(candidate_source)
    candidate_digest = bytes_digest(source_path.read_bytes())

    case_set, dataset_digest = load_case_set(dataset_revision or definition.case_set)
    if case_set.kind != definition.family:
        raise PerfInfrastructureError(
            f"case set {case_set.revision!r} is for family {case_set.kind!r}, "
            f"but problem {definition.revision!r} is {definition.family!r}")
    cases = tuple(tuple(case) for case in case_set.cases)
    reps = TIER_REPETITIONS[tier]

    include_dir = loaded.directory
    driver = loaded.path(definition.scaffolding.driver)
    entry_point = definition.entry_point

    status, resolved = resolve_compiler(candidate_compiler)
    boundary = crosses_compiler_boundary(status, resolved)
    accepted, rejected = screen_flags(candidate_flags)
    candidate_identity = {**toolchain_identity(resolved),
                          "requested": candidate_compiler, "status": status}
    candidate_libs = runtime_libs_for(resolved) if boundary else None

    def _report(*, verdict, results, property_verdicts, deterministic=True,
                build_error=None, interface_error=None):
        """One shape for every way this function can end.

        A candidate that did not build carries the same provenance as a
        completed check, for the same reason the performance path does: a build
        failure would otherwise be the one outcome a reader could not attribute.
        """
        return NativeProblemCorrectnessReportV1.create(
            problem_id=definition.id, problem_revision=definition.revision,
            problem_digest=loaded.digest, family=definition.family,
            entry_point=entry_point, candidate_digest=candidate_digest,
            tier=tier, verdict=verdict,
            case_results=results, property_verdicts=property_verdicts,
            deterministic=deterministic,
            oracle=f"{definition.family}-family-residual-bound",
            error_model="per-element backward-error bound (family oracle)",
            build_error=build_error, interface_error=interface_error,
            accepted_flags=accepted, rejected_flags=rejected,
            candidate_toolchain=candidate_identity,
            crossed_compiler_boundary=boundary,
            dataset_revision=case_set.revision, dataset_sha256=dataset_digest,
            environment=measurement_environment(),
            placement=measurement_placement(),
            sandbox=dict(sandbox_seen),
            negative_control=negative_control)

    sandbox_seen: dict = {}
    results: list[ProblemCorrectnessCaseResultV1] = []
    # WHICH CASES FAILED THE CONTRACT, recorded where the check happens rather
    # than inferred afterwards from ``written != expected``. Inferring it read a
    # candidate that CRASHED -- no output file, so nothing written -- as a
    # candidate that wrote the wrong number of elements, which is a statement
    # about its interface that nothing had established.
    size_failures: set[str] = set()
    with tempfile.TemporaryDirectory() as raw_td:
        build = Path(raw_td)
        try:
            candidate_exe = compile_binary(
                include_dir=include_dir, driver=driver, entry_point=entry_point,
                role=_CANDIDATE_ROLE, source=source_path, out_dir=build,
                compiler=resolved, extra_flags=accepted)
        except PerfBuildError as exc:
            build_error, interface_error = _classify_build_failure(str(exc))
            # A candidate that did not compile has not been shown to conform;
            # one the audit refused HAS been shown not to. Either way nothing was
            # run, so equivalence is unestablished and the verdict is fail --
            # "inconclusive" would let an uncompilable candidate sit outside both
            # the pass set and the fail set.
            return _report(
                verdict="fail", results=(),
                property_verdicts={"numerical-equivalence": "fail",
                                   "interface-conformance": "fail"},
                build_error=build_error, interface_error=interface_error)

        instance_path = build / "problem.bin"
        # Two output paths so a repeat launch can be compared against the first
        # without the second overwriting what it is being compared to.
        first_out = build / "out0.bin"
        repeat_out = build / "out1.bin"
        # The frozen driver writes its credited time whether or not anybody reads
        # it. Nothing here does; see the module docstring.
        timing = build / "timing.bin"

        deterministic = True
        for case in cases:
            case_id = "x".join(str(v) for v in case)
            expected = family.output_elements(case)
            verdict = "pass"
            detail = "within the residual bound"
            # None, not 0.0 -- see ProblemCorrectnessCaseResultV1. Only FINITE
            # ratios accumulate here: ``max`` silently returns the accumulator
            # when handed a NaN, so a candidate that left the driver's poisoned
            # buffer untouched -- the oracle's NaN answer -- published
            # ``worst_residual_ratio: 0.0``, i.e. "exactly zero error", as the
            # measurement behind its own fail verdict.
            worst_seen: float | None = None
            completed = 0
            written: int | None = None
            repeat_identical: bool | None = None
            for index in range(reps):
                input_seed = seed * 100003 + index
                instance = family.generate(case, input_seed)
                family.write(instance_path, instance)
                watched: dict = {}
                try:
                    run_timed(candidate_exe, instance_path, first_out, timing,
                              timeout=run_timeout, role=_CANDIDATE_ROLE,
                              observed=watched,
                              ld_library_path=candidate_libs)
                    if index == 0:
                        # THE SAME INPUT, TWICE. Recorded as an observation only;
                        # see ``repeat_identical``.
                        run_timed(candidate_exe, instance_path, repeat_out, timing,
                                  timeout=run_timeout, role=_CANDIDATE_ROLE,
                                  ld_library_path=candidate_libs)
                        repeat_identical = (first_out.read_bytes()
                                            == repeat_out.read_bytes())
                except PerfBuildError as exc:
                    # THE LAUNCH DID NOT COMPLETE. Every candidate-side fault
                    # ``run_timed`` raises arrives here -- a non-zero exit, a
                    # timeout, and the timing guards it applies whether or not
                    # anyone reads the clock. The verdict is fail, because a
                    # candidate that cannot produce an answer has not been shown
                    # correct; but it is said as "did not complete" and carries
                    # NO residual measurement, because the oracle never ran.
                    verdict = "fail"
                    detail = f"candidate run did not complete: {exc}"
                    break
                finally:
                    sandbox_seen.update(sandbox_record(watched.get("sandbox") or {}))
                output = np.fromfile(first_out, dtype=np.float64)
                written = int(output.size)
                if written != expected:
                    # A short write is an interface failure, not a numerical one:
                    # the contract says how many elements the kernel owns. The
                    # frozen driver allocates n*m, poisons every element to NaN
                    # and writes exactly n*m, so a COMPLETED run cannot reach
                    # here -- this catches a truncated file from a process that
                    # died mid-write, and a future driver that does not.
                    verdict = "fail"
                    detail = (f"candidate wrote {written} values where {expected} "
                              f"were expected")
                    size_failures.add(case_id)
                    break
                correct, worst = family.check(output, case, instance)
                ratio = finite_ratio(worst)
                if ratio is not None:
                    worst_seen = ratio if worst_seen is None else max(worst_seen, ratio)
                completed += 1
                if not correct:
                    verdict = "fail"
                    detail = (
                        f"candidate output failed the residual bound ({ratio:.3g}x)"
                        if ratio is not None else
                        # inf for an output containing an infinity, NaN for one
                        # left at the driver's poison. Both are the oracle
                        # answering, and neither is a number this report can
                        # carry: as a bare float it raised "Out of range float
                        # values are not JSON compliant" inside the verifier,
                        # turning a wrong candidate into a crashed worker that
                        # the driver reports as an infrastructure outage.
                        "candidate output failed the residual bound "
                        "(non-finite residual: the output contains an infinity "
                        "or leaves the driver's poisoned NaN in place)")
                    break
            if verdict == "pass" and completed == 0:
                verdict, detail = "inconclusive", "no repetition completed"
            if repeat_identical is False:
                deterministic = False
            results.append(ProblemCorrectnessCaseResultV1(
                case_id=case_id, verdict=verdict, detail=detail,
                worst_residual_ratio=worst_seen,
                output_elements_expected=expected, output_elements_written=written,
                repetitions_requested=reps, repetitions_completed=completed,
                repeat_identical=repeat_identical))

    overall = "pass"
    if any(item.verdict == "fail" for item in results):
        overall = "fail"
    elif any(item.verdict == "inconclusive" for item in results) or not results:
        overall = "inconclusive"
    # THE SIZE FAILURES ARE THE CONFORMANCE ONES. Everything past the build is
    # either "wrote the wrong number of elements" -- the contract -- or "missed
    # the bound" -- the numbers. Splitting here rather than in the driver keeps
    # the classification with the code that knows which check produced it.
    # A candidate that faulted is neither: it is a failure this verifier reports
    # without claiming to have located, so it fails equivalence and leaves
    # conformance where the build left it.
    size_failed = bool(size_failures)
    properties = {
        "numerical-equivalence": overall,
        "interface-conformance": "fail" if size_failed else (
            "inconclusive" if overall == "inconclusive" else "pass"),
    }
    return _report(verdict=overall, results=tuple(results),
                   property_verdicts=properties, deterministic=deterministic)


__all__ = [
    "CORRECTNESS_PROPERTIES",
    "NativeProblemCorrectnessReportV1",
    "ProblemCorrectnessCaseResultV1",
    "verify_problem_correctness",
]
