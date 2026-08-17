"""Driver for the ARI-native performance harnesses.

The measuring driver for the `performance-regression` slot that the property
vocabulary reserved and six knowledge-skill import profiles require. It does not
FILL that slot yet: no manifest names this driver revision, so nothing resolves
to it and nothing it measures is attested.

WHAT IT NORMALIZES INTO. A performance verdict is a COMPARISON against a pinned
denominator, not an absolute number, so `pass` means "did not regress past the
registered threshold" and the absolute quantities travel in ``measurements``
because a ratio alone cannot answer "is this fast for this machine".

WHY THE PARITY PROBE LOOKS THE WAY IT DOES. The obvious clean control — score
the frozen reference AS the candidate — FAILS, and that is not a bug. Measured
on an aarch64 compute node: the anchor is built with the reference's own flags
and the candidate is not, so the same source measures 0.44x of itself. The
honest clean control therefore builds the reference the reference's way, which
reads 1.0232 (spread 0.0515). The two negative controls are deliberately
distinct: a correct-but-slow kernel must fail on the RATIO (measured 0.0017x)
and a fast-but-wrong kernel must fail on the ORACLE (measured 2.79e11x the
residual bound). A probe that only had the slow control could not tell a
performance harness from a stopwatch.
"""

from __future__ import annotations

from pathlib import Path

from ari.assurance.models import (
    HarnessPropertyResultV1,
    NormalizedHarnessResultV1,
)
from ari.assurance.native_perf_common import (MAX_TRUSTED_SPREAD, load_case_set,
                                              measurement_placement)
from ari.assurance.native_perf import (
    DEFAULT_REGRESSION_THRESHOLD,
    NativePerfReportV1,
    reference_flags,
    reference_source,
    verify_native_perf,
)
from ari.assurance.problems import load_problem
from ari.protocols.integrity import bytes_digest, canonical_digest
from ari.research_contract import ResearchArtifactRefV1


PERF_DRIVER_REVISION = "ari.assurance.native-perf/v1"

# WHERE the probe certifies is the PROBLEM's choice (``parity_case_set``,
# falling back to its scored set). A constant here could only ever name one
# family's set, and the probe certifies whichever harness it is handed. It is
# still pinned like any other set, still checked against the family, and a set
# declaring ``resolves: false`` is refused: registration has to happen where the
# instrument resolves, and at a small shape a single ~20 ms stall against a
# ~0.2 ms kernel gave a 100x spread against 0.095% at the scored shape.

#: The most run-to-run spread a clean control may show and still certify. Same
#: figure ``normalize_result`` reports an ordinary run at, because an instrument
#: cannot be certified to a looser standard than it is read at.
_MAX_CLEAN_SPREAD = MAX_TRUSTED_SPREAD

#: How short a timed region may be before the spread above stops being a
#: statement about the candidate.
#:
#: NOT A GUESS, and not an independent bound. Measured on an exclusive x86 node,
#: varying only the thread budget so the same case was timed at durations from
#: 81 ms down to 3.3 ms: the spread went 0.0012, 0.0057, 0.066, 0.105, 0.214,
#: and then back to 0.019 when the duration returned to 8.8 ms. Multiplying back
#: out, the instrument's own jitter is 0.1-0.7 ms and grows only slowly; the
#: spread is dominated by the shrinking denominator.
#:
#: 0.005 s is where that sweep first breaches ``_MAX_CLEAN_SPREAD`` (4.8 ms gave
#: 0.105). So this refuses nothing the spread bound was not already refusing --
#: it names the CAUSE. "Did not resolve" read as noise from somewhere
#: unspecified; below this the answer is that the measurement was too short to
#: hold the instrument's own overhead, and a reader who knows that reaches for a
#: bigger case rather than a quieter node.
_MIN_RESOLVING_SECONDS = 0.005

#: The controls used to be gemm source embedded here, which was fine while gemm
#: was the only problem and wrong the moment the probe started probing the
#: manifest's OWN problem: they must keep that problem's contract to compile at
#: all. They are declared scaffolding now, and a problem that omits them cannot
#: be registered -- see ``parity_probe``.
_MISSING_CONTROLS = (
    "problem {revision!r} declares no {which} negative control, so this probe "
    "could only show that the harness runs, not that it can tell a wrong answer "
    "from a slow one"
)


def perf_driver_digest() -> str:
    """Content address for the INSTRUMENT: what measures, not what is measured.

    This used to cover the gemm kernels too, on the reasoning that the
    denominator is part of the instrument. It is not — it is part of the
    problem, and it moved there with the rest of the scaffolding. Keeping it
    here would have meant that adding a research theme changed the driver
    digest, which is a re-registration of every harness using this driver, for a
    file none of them read. The problem's own digest covers those bytes and a
    manifest pins it in ``oracle.sha256``; ``prepare`` checks both.

    What remains is the measuring half: the loop, the flag screen, the family
    oracles, the compile rules, and the counter tool, whose source stays under
    ``kernels/tools`` because a profile taken with a tool that changed under a
    pinned manifest is unattributable.
    """
    root = Path(__file__).resolve().parent
    package = root.parent
    files = [
        package / "native_perf.py",
        package / "native_perf_common.py",
        package / "native_perf_family.py",
        package / "native_perf_measure.py",
        # Every family: an oracle is what decides whether a fast answer counts,
        # so all of them are inside the instrument's content address even when a
        # given harness measures only one.
        package / "native_perf_gemm.py",
        package / "native_perf_spmm.py",
        package / "native_perf_stencil.py",
        # The profiler is part of the instrument too.
        package / "native_perf_profile.py",
        # THE ISOLATION ITSELF. ``sandbox.py`` implements the landlock
        # restriction ``run_timed`` applies to every timed child, fail-closed,
        # immediately before exec -- and it was in no driver's content address,
        # so the code that decides whether an untrusted candidate can write
        # outside its output file could change under a pinned manifest with
        # nothing noticing. The report carries what it decided
        # (``filesystem_isolation``, ``mechanism``, ``landlock_abi``), and a
        # record of an isolation nobody pinned is a record of a claim.
        package / "sandbox.py",
        # A problem is only as pinned as the code that resolves and digests it.
        package / "problems.py",
        root / "perf.py",
        root / "perf_worker.py",
        root / "perf_profile_worker.py",
    ]
    # No skip-if-absent: a missing instrument file must fail loudly here rather
    # than drop out of the digest, which would make deleting one of these a
    # change no pin could see.
    missing = [str(path.name) for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"instrument files missing from the digest: {missing}")
    kernels = package / "kernels"
    files.extend(sorted(kernels.rglob("*.c")))
    files.extend(sorted(kernels.rglob("*.h")))
    return canonical_digest(
        tuple((str(path.relative_to(package)), bytes_digest(path.read_bytes()))
              for path in files)
    )


class NativePerfDriver:
    """Normalize a locked performance worker result; never choose a Harness."""

    revision = PERF_DRIVER_REVISION

    #: The typed result this driver's worker emits. Registration resolves the
    #: JSON schema from it, so ``result_schema_conformance`` checks the type the
    #: harness ACTUALLY produces rather than whichever schema was to hand.
    report_schema_version = "ari.native-perf-report/v1"

    def identity(self) -> dict:
        return {"driver_revision": self.revision, "driver_digest": perf_driver_digest()}

    def prepare(self, manifest, request):
        if manifest.driver.revision != self.revision:
            raise ValueError("performance Harness uses another driver revision")
        if manifest.driver.sha256 != perf_driver_digest():
            raise ValueError("performance Harness driver bytes drifted")
        if manifest.kind != "benchmark":
            raise ValueError("the native performance driver requires a benchmark harness")
        declared = {atom.property_id for atom in request.property_atoms}
        if declared - {"performance-regression"}:
            raise ValueError(
                "the native performance driver only decides performance-regression")
        if manifest.network_policy != "deny" or manifest.credential_policy != "none":
            raise ValueError(
                "performance verifier must be credential-free and network-denied")
        if request.execution_request.network != "deny":
            raise ValueError("performance Harness request does not require isolation")
        # WHICH IMAGE, and this driver had no such check while both siblings did
        # -- ``native.py`` and ``problem_correctness.py`` each refuse a request
        # whose container identity is absent or is not the one the manifest
        # pins, and ``runner.py`` delegates rather than asking generically. So
        # the word "container" did not appear in this file at all.
        #
        # IT MATTERS MORE HERE THAN THERE. ``runner.py`` stamps the
        # attestation's ``container_digest`` from the MANIFEST, not from the
        # request it just ran, and its own cross-check only asks that the
        # RESULT's container matches the REQUEST's. So a request carrying
        # another image -- or, since the field is optional, none at all --
        # produces an attestation naming an image the measurement never entered,
        # and every consistency check between the two agrees, because the pair
        # they compare are each other. On a timed harness that is not a
        # provenance nicety: what compiler and what libm the candidate was built
        # and run against is most of what the number means, so an attestation
        # naming the wrong image is a speed claim about a machine nobody can
        # identify.
        container = request.execution_request.container
        if container is None or container.digest != manifest.container.resolved_digest:
            raise ValueError(
                "performance Harness request lacks the pinned container identity")
        # WHICH QUESTION is part of what was registered. A problem definition is
        # PINNED BUT NOT APPROVED -- anyone may add one, no signature -- so this
        # check is what the whole arrangement rests on: an unapproved problem may
        # be measured, but only the exact bytes this manifest was registered
        # against may be measured AS this manifest. Without it, a run could swap
        # the scaffolding, the goal text or the reference and still carry an
        # attestation naming this harness.
        problem = load_problem(manifest.oracle.revision)
        if problem.digest != manifest.oracle.sha256:
            raise ValueError(
                f"problem {manifest.oracle.revision!r} does not match the "
                f"manifest pin; the registered question has changed")
        # WHICH PROBLEMS is part of it too. Registration evidence is established
        # at a size and does not transfer: without this a run could measure
        # anything and still carry an attestation naming this manifest.
        case_set, digest = load_case_set(manifest.dataset.revision)
        if digest != manifest.dataset.sha256:
            raise ValueError(
                f"case set {manifest.dataset.revision!r} does not match the "
                f"manifest pin; the registered problem set has changed")
        if case_set.kind != problem.definition.family:
            raise ValueError(
                f"case set {manifest.dataset.revision!r} is for family "
                f"{case_set.kind!r}, but the pinned problem is "
                f"{problem.definition.family!r}")
        # WHERE, as well as what and how big. A timed verdict is a statement
        # about a machine: the same commit and the same clean worktree scored
        # 15/15 on an exclusive aarch64 node at 48 threads and 13/15 on an
        # exclusive x86 node at 64, where the clean control did not resolve.
        # Without this the first attestation covered the second run.
        pinned = dict(getattr(manifest, "registered_placement", None) or {})
        if not pinned:
            raise ValueError(
                "a performance harness must pin the placement its evidence was "
                "established on; a timed verdict does not transfer across "
                "machines any more than it transfers across sizes")
        here = measurement_placement()
        differs = {key: (pinned[key], here.get(key))
                   for key in sorted(pinned)
                   if here.get(key) != pinned[key]}
        if differs:
            raise ValueError(
                f"this host is not the placement {manifest.id} was registered "
                f"on: {differs}. The evidence was established there and does "
                f"not describe here")
        if not case_set.resolves:
            raise ValueError(
                f"case set {manifest.dataset.revision!r} declares resolves=false, "
                f"so it cannot support a regression verdict")
        return None

    def build_request(self, manifest, request):
        return request.execution_request

    @staticmethod
    def _full_log(request, result, role: str) -> bytes:
        artifact = next(item for item in result.artifacts if item.logical_role == role)
        return request.execution_request.workspace.read_bytes(
            artifact.relative_path, max_bytes=result.limits.max_output_bytes
        )

    def _degraded(self, request, evidence, reason: str):
        return NormalizedHarnessResultV1(
            verdict="infrastructure_error",
            property_results=tuple(
                HarnessPropertyResultV1(
                    property_id=atom.property_id, method=atom.method, tier=atom.tier,
                    tested_scope=atom.scope, verdict="infrastructure_error",
                    covered_atom_digests=(atom.atom_digest,),
                    evidence_artifact_refs=evidence,
                )
                for atom in request.property_atoms
            ),
            evidence_artifact_refs=evidence,
            infrastructure_status="failed",
            nondeterminism_observations=(reason,),
        )

    def normalize_result(self, manifest, request, result):
        evidence = tuple(
            ResearchArtifactRefV1(
                logical_name=item.relative_path, digest=item.digest,
                media_type=item.media_type, role=f"harness-{item.logical_role}",
                source_run_id=request.run_id,
            )
            for item in result.artifacts
        )
        if result.status in {"timed_out", "cancelled"}:
            return self._degraded(request, evidence, result.status)
        try:
            lines = self._full_log(request, result, "stdout").decode(
                "utf-8", errors="strict").splitlines()
            report = NativePerfReportV1.model_validate_json(
                next(line for line in reversed(lines) if line.strip()))
        except Exception:
            return self._degraded(request, evidence, "malformed-perf-worker-result")

        cases = report.case_results
        ratios = [case.speedup for case in cases]
        spreads = [case.relative_spread for case in cases
                   if case.relative_spread is not None]
        properties = tuple(
            HarnessPropertyResultV1(
                property_id=atom.property_id, method=atom.method, tier=atom.tier,
                tested_scope=atom.scope, verdict=report.verdict,
                measurements={
                    "case_count": len(cases),
                    "failed_case_count": sum(c.verdict == "fail" for c in cases),
                    # WHETHER THE ANSWER WAS RIGHT, AND WHETHER THE MEASUREMENT
                    # FINISHED -- separately, and separately from the verdict.
                    #
                    # `failed_case_count` cannot answer either. It counts
                    # `verdict == "fail"`, and that verdict covers two unlike
                    # things: a WRONG answer, which is not a measurement of
                    # anything, and a CORRECT answer slower than the frozen
                    # reference, which is a perfectly good measurement of a slow
                    # kernel. A reader deriving "is this node valid" from it
                    # would call every early candidate invalid -- the seed
                    # measures 0.008-0.02x of a competent denominator -- which
                    # is the collapse the direct path documents at
                    # evaluator/assurance_measure.py and avoids by taking
                    # validity from correctness instead.
                    #
                    # So the attestation now carries the two FACTS and leaves
                    # the policy to whoever reads it. Completeness is separate
                    # from correctness because counting only the repetitions
                    # that survived let a case that timed out after one of three
                    # rank as a finished measurement carrying that one
                    # repetition's speedup.
                    "correct_by_case": {
                        c.case_id: all(r.correct for r in c.repetitions)
                        for c in cases
                    },
                    "complete_by_case": {
                        c.case_id: len(c.repetitions) >= c.repetitions_requested
                        for c in cases
                    },
                    # The ratio the verdict was decided on, per case and worst.
                    "min_speedup": min(ratios, default=0.0),
                    "median_speedup_by_case": {c.case_id: c.speedup for c in cases},
                    # The absolute number, because a ratio cannot say whether the
                    # machine was used well.
                    "credited_seconds_by_case": {
                        c.case_id: min((r.credited_seconds for r in c.repetitions),
                                       default=0.0)
                        for c in cases
                    },
                    # What the toolchain bought, where a compiler boundary was
                    # actually crossed. Absent is not zero.
                    "toolchain_gain_by_case": {
                        c.case_id: c.toolchain_gain for c in cases
                        if c.toolchain_gain is not None
                    },
                },
                tolerance_evidence={
                    "regression_threshold": report.regression_threshold,
                    "denominator": report.denominator,
                    # Without the spread a median is a number with no claim
                    # attached; this study has mistaken variance for effect once.
                    "worst_relative_spread": max(spreads) if spreads else None,
                },
                oracle_comparison={
                    "report_digest": report.report_digest,
                    "default_toolchain": report.default_toolchain,
                    "candidate_toolchain": report.candidate_toolchain,
                    "crossed_compiler_boundary": report.crossed_compiler_boundary,
                    # A timing is a statement about a machine.
                    "placement": report.placement,
                },
                covered_atom_digests=(atom.atom_digest,),
                evidence_artifact_refs=evidence,
            )
            for atom in request.property_atoms
        )
        observations: tuple[str, ...] = ()
        if spreads and max(spreads) > 0.1:
            observations = (
                f"repetition spread {max(spreads):.3f} exceeds 0.1; the median is "
                f"not resolving the difference it is quoted to",
            )
        return NormalizedHarnessResultV1(
            verdict=report.verdict,
            property_results=properties,
            evidence_artifact_refs=evidence,
            infrastructure_status="ready",
            nondeterminism_observations=observations,
        )

    def parity_probe(self, manifest):
        """Clean control passes, both negative controls fail, for different reasons.

        Probes THE MANIFEST'S OWN problem, not a fixed one: a probe that always
        certified gemm would say nothing about a harness registered against
        anything else, while looking exactly as though it had.
        """
        problem = load_problem(manifest.oracle.revision)
        definition = problem.definition
        scaffolding = definition.scaffolding
        parity_set = definition.parity_case_set or definition.case_set

        def _refused(reason: str) -> dict:
            # Fail closed, and say why. Reporting passed=False beats skipping the
            # check: it is what keeps "a problem may be added without approval"
            # from also meaning "a problem may be registered without evidence".
            return {
                "schema_version": "ari.native-perf-parity-report/v1",
                "driver_digest": perf_driver_digest(),
                "case_set": parity_set,
                "problem": definition.revision,
                "problem_digest": problem.digest,
                "results": {},
                "passed": False,
                "reason": reason,
            }

        probe_set, _digest = load_case_set(parity_set)
        if probe_set.kind != definition.family:
            return _refused(
                f"parity case set {parity_set!r} is for family "
                f"{probe_set.kind!r}, not {definition.family!r}")
        if not probe_set.resolves:
            return _refused(
                f"parity case set {parity_set!r} declares resolves=false; an "
                f"instrument certified where its own spread swamps the "
                f"difference it reports has not been certified")
        for which, name in (("slow", scaffolding.negative_control_slow),
                            ("wrong", scaffolding.negative_control_wrong)):
            if not name:
                return _refused(_MISSING_CONTROLS.format(
                    revision=definition.revision, which=which))
        flags = " ".join(reference_flags(problem))
        # THE THRESHOLD IS NOT THE PROBE'S TO CHOOSE. It was three literal 0.95s
        # here against a 1.0 default in the worker and the measurement, and the
        # governed path passes no threshold at all -- so a registered run judged
        # its candidate at a ratio the evidence beside it had never been earned
        # at. Imported, so the controls certify the instrument at exactly the
        # figure a scored run is decided by.
        threshold = DEFAULT_REGRESSION_THRESHOLD
        clean = verify_native_perf(
            problem, reference_source(problem), tier="validate",
            dataset_revision=parity_set, candidate_flags=flags,
            regression_threshold=threshold)
        slow = verify_native_perf(
            problem, problem.path(scaffolding.negative_control_slow),
            tier="screen", dataset_revision=parity_set,
            candidate_flags=flags, regression_threshold=threshold)
        wrong = verify_native_perf(
            problem, problem.path(scaffolding.negative_control_wrong),
            tier="screen", dataset_revision=parity_set,
            candidate_flags=flags, regression_threshold=threshold)
        slow_detail = slow.case_results[0].detail if slow.case_results else ""
        wrong_detail = wrong.case_results[0].detail if wrong.case_results else ""
        clean_spread = (clean.case_results[0].relative_spread
                        if clean.case_results else None)
        # THE PROBE HAD THE SPREAD AND DID NOT USE IT. ``normalize_result``
        # already reports a spread above 0.1 as "the median is not resolving the
        # difference it is quoted to" -- and the probe, whose whole job is to
        # certify the instrument, ignored its own. Measured on a shared node:
        # the probe passed once in three runs, and the run that PASSED had a
        # clean-control spread of 1.16, eleven times the figure the same code
        # calls unresolved. Registration evidence produced there would have
        # certified noise.
        resolved = clean_spread is not None and clean_spread <= _MAX_CLEAN_SPREAD
        clean_seconds = (clean.case_results[0].median_seconds
                         if clean.case_results else None)
        too_short = (clean_seconds is not None
                     and clean_seconds < _MIN_RESOLVING_SECONDS)
        if not resolved and too_short:
            resolution_note = (
                f"the timed region was {clean_seconds * 1000:.1f} ms; at that "
                f"duration the instrument's own overhead is a large fraction of "
                f"what it measures, so this is a case too small for this machine "
                f"rather than a noisy machine")
        elif not resolved:
            resolution_note = (
                f"spread {clean_spread!r} exceeds {_MAX_CLEAN_SPREAD} at a timed "
                f"region of {clean_seconds!r} s")
        else:
            resolution_note = ""
        return {
            "schema_version": "ari.native-perf-parity-report/v1",
            "driver_digest": perf_driver_digest(),
            "case_set": parity_set,
            # Which question was probed. A probe report that named only the
            # driver could be read as evidence about a harness it never ran.
            "problem": definition.revision,
            "problem_digest": problem.digest,
            # The common view the gates read; the detail below stays.
            "controls": {
                "clean": {"verdict": clean.verdict,
                          "resolved": resolved,
                          "relative_spread": clean_spread,
                          # The duration the spread is a fraction OF, and, when
                          # it did not resolve, which of the two it was.
                          "median_seconds": clean_seconds,
                          "resolution_note": resolution_note,
                          "median_speedup": (clean.case_results[0].speedup
                                             if clean.case_results else 0.0)},
                "negatives": [
                    {"name": "slow-but-correct", "verdict": slow.verdict,
                     "detail": slow_detail},
                    {"name": "fast-but-wrong", "verdict": wrong.verdict,
                     "detail": wrong_detail},
                ],
            },
            "results": {
                "clean_control": {
                    "verdict": clean.verdict,
                    "median_speedup": clean.case_results[0].speedup if clean.case_results else 0.0,
                    "relative_spread": clean_spread,
                    "resolved": resolved,
                    "report_digest": clean.report_digest,
                },
                "negative_control_slow": {
                    "verdict": slow.verdict, "detail": slow_detail,
                    "report_digest": slow.report_digest,
                },
                "negative_control_wrong": {
                    "verdict": wrong.verdict, "detail": wrong_detail,
                    "report_digest": wrong.report_digest,
                },
            },
            # The two negatives must fail for DIFFERENT reasons, or the harness
            # is a stopwatch that cannot tell a wrong answer from a slow one --
            # AND the clean control must have resolved, or the three verdicts
            # are three coin flips that happened to land right.
            "passed": (
                clean.verdict == "pass"
                and slow.verdict == "fail"
                and wrong.verdict == "fail"
                and "threshold" in slow_detail
                and "residual bound" in wrong_detail
                and resolved
            ),
            "reason": (
                None if resolved else
                f"clean-control spread {clean_spread} exceeds "
                f"{_MAX_CLEAN_SPREAD}; the instrument did not resolve on this "
                f"node, so these verdicts certify nothing"),
        }


__all__ = ["PERF_DRIVER_REVISION", "NativePerfDriver", "perf_driver_digest"]
