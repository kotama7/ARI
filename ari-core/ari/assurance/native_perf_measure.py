"""The measurement, once, for every problem.

The property is ``performance-regression`` by ``benchmark-comparison``, so the
verdict is a comparison against a pinned denominator, not an absolute number.
The absolute numbers travel in ``measurements`` because a ratio alone cannot
answer "is 33 GFLOPS too low", but they are not what decides the verdict.

WHY THIS IS NOT PER-PROBLEM. Every anti-gaming property this loop has — the
header-less staging, the driver built with default flags, the object-level
symbol audit, all timed launches before the oracle, the anchor/matched pair,
the per-role output files — was paid for by a defect, and each one would have to
be re-established in a copy. A second family that copied this file would be a
second instrument with the same name, and its numbers would not be comparable to
this one's while looking exactly as though they were.

WHAT COMES FROM WHERE, and this is the whole design:

  * the PROBLEM (pinned, unapproved) supplies scaffolding, entry point, case set,
    goal text — the question;
  * the FAMILY (registered code) supplies the generator and the oracle — the
    mathematics;
  * this module supplies flags, the timed window, the thread regime, the
    denominators and the placement record — the instrument.

Nothing in the first two can move anything in the third.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Literal

import numpy as np

from ari.assurance.native_perf_common import (
    MAX_OVERHEAD_RATIO,
    finite_ratio,
    sandbox_record,
    TIER_REPETITIONS,
    NativePerfReportV1,
    PerfBuildError,
    PerfCaseResultV1,
    PerfInfrastructureError,
    PerfInfrastructureError as _PerfInfra,
    PerfRepetitionV1,
    compile_binary,
    crosses_compiler_boundary,
    default_compiler,
    isa_flags_for,
    load_case_set,
    measurement_environment,
    measurement_placement,
    median,
    relative_spread,
    resolve_compiler,
    run_timed,
    runtime_libs_for,
    screen_flags,
    toolchain_identity,
)
from ari.assurance.native_perf_family import get_family
from ari.assurance.problems import LoadedProblemV1, load_problem


def resolve_problem(problem: str | LoadedProblemV1) -> LoadedProblemV1:
    return problem if isinstance(problem, LoadedProblemV1) else load_problem(problem)


def verify_performance(
    problem: str | LoadedProblemV1,
    candidate_source: Path,
    *,
    tier: Literal["screen", "validate", "certify"] = "screen",
    seed: int = 0,
    dataset_revision: str | None = None,
    candidate_compiler: str | None = None,
    candidate_flags: str | None = None,
    regression_threshold: float = 1.0,
    run_timeout: float = 300.0,
    negative_control: bool = False,
) -> NativePerfReportV1:
    """Measure ``candidate_source`` against the problem's frozen reference.

    ``regression_threshold`` is the ratio the candidate must reach to pass. The
    default of 1.0 states the property literally: not slower than the frozen
    reference. A harness manifest supplies the value it registered.

    ``dataset_revision`` defaults to the problem's own declared case set. It is
    overridable only so the parity probe can certify at its own pinned set;
    whichever set is used must belong to the problem's family, or the shapes
    would be handed to an oracle they mean nothing to.
    """
    loaded = resolve_problem(problem)
    definition = loaded.definition
    family = get_family(definition.family)

    case_set, dataset_digest = load_case_set(dataset_revision or definition.case_set)
    if case_set.kind != definition.family:
        raise PerfInfrastructureError(
            f"case set {case_set.revision!r} is for family {case_set.kind!r}, "
            f"but problem {definition.revision!r} is {definition.family!r}")
    # Passed to the family verbatim. The loop used to coerce every element to
    # int, which silently made a case descriptor a list of sizes -- true for
    # GEMM and false for anything with a categorical in it.
    cases = tuple(tuple(case) for case in case_set.cases)
    reps = TIER_REPETITIONS[tier]

    include_dir = loaded.directory
    driver = loaded.path(definition.scaffolding.driver)
    reference_source = loaded.path(definition.scaffolding.reference)
    if not reference_source.is_file():
        raise PerfInfrastructureError(f"frozen reference missing: {reference_source}")
    entry_point = definition.entry_point
    ref_flags = family.reference_flags()

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

    sandbox_seen: dict = {}

    def _report(*, verdict, results, build_error=None):
        """One shape for every way this function can end.

        The early return for a candidate that did not build has to carry the
        same provenance -- toolchains, flags, environment, placement, which
        problem, which sizes -- as a completed measurement, or a build failure
        would be the one outcome a reader could not attribute.
        """
        return NativePerfReportV1.create(
            problem_id=definition.id, problem_revision=definition.revision,
            problem_digest=loaded.digest, family=definition.family,
            tier=tier, verdict=verdict, case_results=results,
            build_error=build_error,
            regression_threshold=regression_threshold,
            default_toolchain=default_identity,
            candidate_toolchain=candidate_identity,
            crossed_compiler_boundary=boundary,
            base_flags=base, reference_flags=ref_flags,
            accepted_flags=accepted, rejected_flags=rejected,
            environment=measurement_environment(),
            dataset_revision=case_set.revision, dataset_sha256=dataset_digest,
            placement=measurement_placement(), sandbox=dict(sandbox_seen),
            negative_control=negative_control)

    results: list[PerfCaseResultV1] = []
    with tempfile.TemporaryDirectory() as raw_td:
        build = Path(raw_td)
        # The anchor is ALWAYS the default toolchain. It is the published
        # denominator and must stay exactly the object it has always been.
        anchor_exe = compile_binary(
            include_dir=include_dir, driver=driver, entry_point=entry_point,
            role="reference", source=reference_source, out_dir=build,
            compiler=default_cc, reference_flags=ref_flags)
        try:
            candidate_exe = compile_binary(
                include_dir=include_dir, driver=driver, entry_point=entry_point,
                role="candidate", source=candidate_source, out_dir=build,
                compiler=resolved, extra_flags=accepted)
        except PerfBuildError as exc:
            # ONE ANSWER FOR BOTH ENTRY POINTS. This compile is outside the
            # repetition loop, so the error used to escape and the two callers
            # classified it differently -- the evaluator as a candidate failure,
            # the worker as a non-zero exit the driver reads as an
            # infrastructure error. A candidate that does not build is a result.
            return _report(build_error=str(exc), verdict="fail", results=())
        matched_exe = None
        if boundary:
            matched_exe = compile_binary(
                include_dir=include_dir, driver=driver, entry_point=entry_point,
                role="reference_matched", source=reference_source, out_dir=build,
                compiler=resolved, extra_flags=accepted)

        instance_path = build / "problem.bin"
        # ONE OUTPUT FILE PER ROLE, AND THE NAME DOES NOT SAY WHICH. Sharing one
        # meant the anchor overwrote the candidate's answer, so the correctness
        # check had to run between the two timed launches -- see below. Naming
        # them after the role then handed the driver its own role in argv[2],
        # and the driver is PROBLEM-owned C: one line comparing that path could
        # scale the candidate's credited time and nothing here would see it.
        # The problem still supplies the driver; it no longer learns which side
        # of the comparison it is running.
        outputs = {role: build / f"out{ordinal}.bin"
                   for ordinal, role in enumerate(
                       ("candidate", "reference", "reference_matched"))}
        timing = build / "timing.bin"

        for case in cases:
            case_id = "x".join(str(v) for v in case)
            expected = family.output_elements(case)
            repetitions: list[PerfRepetitionV1] = []
            ratios: list[float] = []
            verdict = "pass"
            detail = "not slower than the frozen reference"
            for index in range(reps):
                input_seed = seed * 100003 + index
                instance = family.generate(case, input_seed)
                family.write(instance_path, instance)
                # ALL TIMED LAUNCHES FIRST, THEN THE ORACLE. The oracle is a
                # multi-threaded numpy call running in THIS process; sitting it
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
                    watched: dict[str, dict[str, float]] = {}
                    for role, exe in order:
                        watched[role] = {}
                        seconds[role] = run_timed(
                            exe, instance_path, outputs[role], timing,
                            timeout=run_timeout, role=role,
                            observed=watched[role],
                            ld_library_path=(candidate_libs
                                             if role != "reference" else None))
                    if matched_exe is not None:
                        try:
                            seconds["reference_matched"] = run_timed(
                                matched_exe, instance_path,
                                outputs["reference_matched"], timing,
                                timeout=run_timeout, role="reference_matched",
                                ld_library_path=candidate_libs)
                        except _PerfInfra:
                            # A matched-run failure must not discard an anchor
                            # measurement that already succeeded.
                            pass
                    t_cand = seconds["candidate"]
                    t_ref = seconds["reference"]
                    # THE OVERHEAD CHECK, which is what a self-timing forger
                    # cannot satisfy. Both processes ran the same frozen driver
                    # on the same problem, so their work outside the timed call
                    # is the same work. A kernel that writes a fraction of its
                    # own elapsed time keeps its wall and shrinks its credit, so
                    # the whole difference appears as excess overhead here.
                    # Measured: such a kernel scored 89.3x and passed under the
                    # wall bound alone.
                    # Recorded from the launch that happened, not from a probe
                    # taken separately: those are the two things that used to be
                    # able to disagree.
                    # FILTERED, because the launch's record carries
                    # ``writable_root`` -- the per-run temporary directory,
                    # i.e. a HOST FILESYSTEM PATH -- and this report is
                    # published and digested evidence. It also changes every
                    # run, so it makes the report digest non-reproducible.
                    sandbox_seen.update(sandbox_record(
                        watched["candidate"].get("sandbox") or {}))
                    over_cand = watched["candidate"].get("overhead", 0.0)
                    over_ref = watched["reference"].get("overhead", 0.0)
                    if over_ref > 0 and over_cand > over_ref * MAX_OVERHEAD_RATIO:
                        verdict = "fail"
                        detail = (
                            f"the candidate process spent {over_cand:.4g}s outside "
                            f"its credited {t_cand:.4g}s against the reference's "
                            f"{over_ref:.4g}s on the same driver and problem; the "
                            f"credited time does not account for what ran")
                        break
                    c_out = np.fromfile(outputs["candidate"], dtype=np.float64)
                    r_out = np.fromfile(outputs["reference"], dtype=np.float64)
                except PerfBuildError as exc:
                    verdict, detail = "fail", str(exc)
                    break
                # THE DENOMINATOR IS CHECKED TOO. This module's docstring has
                # always said the frozen reference is checked at the scored size
                # -- "a reference that were wrong and fast would deflate every
                # candidate" -- and it was not: the reference's output file was
                # written and never read. A wrong-and-fast denominator makes
                # every candidate look bad, and nothing downstream could tell
                # that from candidates that were bad. It is the instrument, so
                # its failure is an infrastructure error, not a verdict.
                if r_out.size != expected:
                    raise PerfInfrastructureError(
                        f"the frozen reference wrote {r_out.size} values where "
                        f"{expected} were expected; the denominator is not "
                        f"solving this problem")
                ref_ok, ref_worst = family.check(r_out, case, instance)
                if not ref_ok:
                    raise PerfInfrastructureError(
                        f"the frozen reference failed its own oracle "
                        f"({ref_worst:.3g}x the bound); every ratio measured "
                        f"against it would be meaningless")
                if c_out.size != expected:
                    verdict, detail = "fail", "candidate wrote the wrong output size"
                    break
                correct, worst = family.check(c_out, case, instance)
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
                        speedup=t_ref / t_cand, correct=False,
                        max_rel_error=finite_ratio(worst)))
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
                    toolchain_gain=gain, correct=True,
                    max_rel_error=finite_ratio(worst)))
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
                repetitions_requested=reps,
                speedup_matched=median(matched_values) if matched_values else None,
                toolchain_gain=median(gains) if gains else None,
                relative_spread=relative_spread(ratios),
                repetitions=tuple(repetitions)))

    overall = "pass"
    if any(item.verdict == "fail" for item in results):
        overall = "fail"
    elif any(item.verdict == "inconclusive" for item in results) or not results:
        overall = "inconclusive"
    if not case_set.resolves and overall in ("pass", "fail"):
        # A cheap set can show that a candidate built and was right. It cannot
        # support "did not regress" OR "did regress": at this size the
        # measurement's own spread swamps the difference either verdict claims
        # to have found.
        #
        # This used to downgrade only ``pass``, so the set's declared inability
        # to resolve protected exactly the direction that flatters -- a ratio of
        # 0.79x on a set whose own YAML says it cannot support a verdict was
        # emitted verbatim as a regression.
        overall = "inconclusive"
    return _report(verdict=overall, results=tuple(results))


__all__ = ["resolve_problem", "verify_performance"]
