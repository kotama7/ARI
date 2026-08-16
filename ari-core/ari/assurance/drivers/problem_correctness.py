"""Driver for correctness against a PINNED PROBLEM's own contract.

The gap this fills. Every registered correctness harness verifies the ARI-native
ABI out of a shared library. Every pinned problem submits C source against its
own header. Nothing verified the second, so a governed run over a problem had
exactly one correctness harness available to it and that harness could not load
its target -- reported not as "no harness fits" but as 33 failing cases.

Its digest is its own, and that is the whole reason it can exist. Putting a
problem-shaped correctness verifier inside ``native_driver_digest`` would have
re-registered the three ARI-native harnesses for a file none of them read; the
performance driver's docstring worked this out first and this follows it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ari.assurance.models import (
    HarnessPropertyResultV1,
    NormalizedHarnessResultV1,
)
from ari.assurance.native_perf_common import load_case_set
from ari.assurance.native_problem_correctness import (
    CORRECTNESS_PROPERTIES,
    NativeProblemCorrectnessReportV1,
    verify_problem_correctness,
)
from ari.assurance.problems import load_problem
from ari.protocols.integrity import bytes_digest, canonical_digest
from ari.research_contract import ResearchArtifactRefV1


PROBLEM_CORRECTNESS_DRIVER_REVISION = "ari.assurance.problem-correctness/v1"

#: Appended to the problem's OWN seed candidate to make the interface control.
#: A literal control kernel here would be problem-specific source living in the
#: instrument -- the mistake the performance driver's controls were moved out of
#: the driver to fix. Appending a file-scope global is a mechanical transform of
#: whatever C the problem declares, so it stays family-agnostic.
_EXTRA_SYMBOL = "\nint ari_problem_correctness_probe_symbol = 0;\n"

_MISSING_CONTROLS = (
    "problem {revision!r} declares no {which}, so this probe could only show "
    "that the harness runs, not that it can tell a wrong answer from a slow one"
)


def problem_correctness_driver_digest() -> str:
    """Content address for THIS instrument.

    Covers the shared build/audit/launch machinery and every family oracle,
    because an oracle is what decides whether an answer counts even when a given
    harness verifies only one family. It does NOT cover
    ``native_perf_measure.py``: the timed loop, the anchor, the two denominators
    and the overhead check are not read on this path, and including them would
    mean a change to how a stopwatch is run re-registers a harness that runs no
    stopwatch. It does not cover ``kernels/`` either, for the same reason -- that
    is the profiler's tooling.
    """
    root = Path(__file__).resolve().parent
    package = root.parent
    files = (
        package / "native_problem_correctness.py",
        # The build, the flag screen, the object audit and the launch.
        package / "native_perf_common.py",
        package / "native_perf_family.py",
        package / "native_perf_gemm.py",
        package / "native_perf_spmm.py",
        package / "native_perf_stencil.py",
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
        root / "problem_correctness.py",
        root / "problem_correctness_worker.py",
    )
    # No skip-if-absent: a missing instrument file must fail loudly rather than
    # drop out of the digest, which would make deleting one invisible to a pin.
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"instrument files missing from the digest: {missing}")
    return canonical_digest(
        tuple((path.name, bytes_digest(path.read_bytes())) for path in files)
    )


class ProblemCorrectnessDriver:
    """Normalize a locked problem-correctness result; never choose a Harness."""

    revision = PROBLEM_CORRECTNESS_DRIVER_REVISION

    report_schema_version = "ari.native-problem-correctness-report/v1"

    def identity(self) -> dict:
        return {"driver_revision": self.revision,
                "driver_digest": problem_correctness_driver_digest()}

    def prepare(self, manifest, request):
        if manifest.driver.revision != self.revision:
            raise ValueError("problem-correctness Harness uses another driver revision")
        if manifest.driver.sha256 != problem_correctness_driver_digest():
            raise ValueError("problem-correctness Harness driver bytes drifted")
        if manifest.kind != "artifact_verifier" or not manifest.accepts_external_target:
            raise ValueError(
                "the problem-correctness driver requires an external artifact verifier")
        declared = {atom.property_id for atom in request.property_atoms}
        unknown = sorted(declared - set(CORRECTNESS_PROPERTIES))
        if unknown:
            raise ValueError(
                f"the problem-correctness driver does not decide {unknown}")
        if manifest.network_policy != "deny" or manifest.credential_policy != "none":
            raise ValueError(
                "problem-correctness verifier must be credential-free and network-denied")
        if request.execution_request.network != "deny":
            raise ValueError("problem-correctness request does not require isolation")
        container = request.execution_request.container
        if container is None or container.digest != manifest.container.resolved_digest:
            raise ValueError(
                "problem-correctness request lacks the pinned container identity")
        # WHICH QUESTION was registered. A problem definition is PINNED BUT NOT
        # APPROVED -- anyone may add one -- so this is what the arrangement rests
        # on: an unapproved problem may be verified, but only the exact bytes
        # this manifest was registered against may be verified AS this manifest.
        problem = load_problem(manifest.oracle.revision)
        if problem.digest != manifest.oracle.sha256:
            raise ValueError(
                f"problem {manifest.oracle.revision!r} does not match the manifest "
                f"pin; the registered question has changed")
        case_set, digest = load_case_set(manifest.dataset.revision)
        if digest != manifest.dataset.sha256:
            raise ValueError(
                f"case set {manifest.dataset.revision!r} does not match the manifest "
                f"pin; the registered problem set has changed")
        if case_set.kind != problem.definition.family:
            raise ValueError(
                f"case set {manifest.dataset.revision!r} is for family "
                f"{case_set.kind!r}, but the pinned problem is "
                f"{problem.definition.family!r}")
        # NO PLACEMENT CHECK, and no ``resolves`` requirement. Both are load-
        # bearing for the performance driver and neither is a correctness
        # question: a residual bound holds or does not hold independently of how
        # many memory domains the allocation had, and a case set too small to
        # separate two timings still separates a right answer from a wrong one.
        # Stated rather than merely omitted, because the next reader will
        # compare this method with ``NativePerfDriver.prepare`` and the
        # difference has to look deliberate.
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
            report = NativeProblemCorrectnessReportV1.model_validate_json(
                next(line for line in reversed(lines) if line.strip()))
        except Exception:
            return self._degraded(
                request, evidence, "malformed-problem-correctness-result")

        # THE REPORT MUST BE ABOUT THE PINNED QUESTION. ``prepare`` checks the
        # problem and case set ON DISK against the manifest, before anything
        # runs; nothing checked what came BACK. The worker is launched with the
        # manifest's own pins, so a mismatch here is not a candidate failing --
        # it means the result being normalized describes a different question
        # from the one this manifest was registered against, and normalizing it
        # would file that answer under this Harness's attestation.
        mismatched = {
            key: (mine, theirs)
            for key, mine, theirs in (
                ("problem", manifest.oracle.revision, report.problem_revision),
                ("problem_digest", manifest.oracle.sha256, report.problem_digest),
                ("dataset", manifest.dataset.revision, report.dataset_revision),
                ("dataset_digest", manifest.dataset.sha256, report.dataset_sha256),
            )
            if mine != theirs
        }
        if mismatched:
            return self._degraded(
                request, evidence,
                f"result describes another question than the one pinned: "
                f"{sorted(mismatched)}")

        cases = report.case_results
        failed = sum(case.verdict == "fail" for case in cases)
        # ABSENT IS NOT ZERO, AND ZERO IS THE PERFECT ANSWER. A case reports no
        # ``worst_residual_ratio`` when no FINITE ratio was observed: either
        # nothing ran (the launch did not complete, or the output was short) or
        # the oracle answered ``inf``/``NaN`` for a candidate whose output holds
        # an infinity or the driver's untouched poison. Neither of those is a
        # small residual; one is unmeasured and the other is worse than any
        # number this report can carry.
        #
        # ``max(..., default=0.0)`` got both wrong. On the EMPTY sequence -- which
        # is every build failure, where ``verify_problem_correctness`` returns
        # ``results=()`` -- it published 0.0, i.e. "exactly zero error", as the
        # measurement behind a candidate that never compiled. And with a ``None``
        # INSIDE the sequence it raised TypeError, so the one shape the
        # nullability was introduced for was the one shape that crashed here.
        #
        # The aggregate claims to be the WORST over the case set, so it exists
        # only when every case reported one. A maximum over just the cases that
        # produced a number is a bound the evidence does not support, and it is
        # published beside ``residual_ratio_limit: 1.0``, where a reader would
        # take it for "inside the bound". ``None`` says the worst is not known;
        # ``worst_residual_ratio_by_case`` below says which cases withheld it.
        observed = [case.worst_residual_ratio for case in cases
                    if case.worst_residual_ratio is not None]
        worst = max(observed) if cases and len(observed) == len(cases) else None
        properties = tuple(
            HarnessPropertyResultV1(
                property_id=atom.property_id, method=atom.method, tier=atom.tier,
                tested_scope=atom.scope,
                # PER PROPERTY, from the verifier. A build failure fails both; a
                # candidate that writes the wrong element count fails
                # conformance; a candidate that misses the bound fails
                # equivalence and conforms. Reporting one overall verdict against
                # every atom is how a run learns "the interface was wrong" from a
                # harness that only ever checked the numbers.
                verdict=report.property_verdicts.get(atom.property_id, report.verdict),
                measurements={
                    "case_count": len(cases),
                    "failed_case_count": failed,
                    "worst_residual_ratio": worst,
                    "worst_residual_ratio_by_case": {
                        case.case_id: case.worst_residual_ratio for case in cases
                    },
                    "output_elements_by_case": {
                        case.case_id: {
                            "expected": case.output_elements_expected,
                            "written": case.output_elements_written,
                        }
                        for case in cases
                    },
                },
                tolerance_evidence={
                    "error_model": report.error_model,
                    # 1.0 is the bound. Stated so a reader does not have to know
                    # that the ratio is already normalized to it.
                    "residual_ratio_limit": 1.0,
                },
                oracle_comparison={
                    "oracle": report.oracle,
                    "report_digest": report.report_digest,
                    "problem": report.problem_revision,
                    "problem_digest": report.problem_digest,
                    "dataset_revision": report.dataset_revision,
                    "candidate_toolchain": report.candidate_toolchain,
                    "build_error": report.build_error,
                    "interface_error": report.interface_error,
                },
                covered_atom_digests=(atom.atom_digest,),
                evidence_artifact_refs=evidence,
            )
            for atom in request.property_atoms
        )
        # THE AGGREGATE IS OVER WHAT WAS ASKED. ``report.verdict`` unions both
        # properties, and ``prepare`` accepts a request declaring either one on
        # its own: a request asking only about interface conformance would have
        # been handed a harness-level ``fail`` because the numbers missed the
        # bound, which is a verdict about a question it did not ask.
        declared = [item.verdict for item in properties]
        overall = report.verdict
        if declared:
            overall = ("fail" if "fail" in declared
                       else "inconclusive" if "inconclusive" in declared
                       else "infrastructure_error" if "infrastructure_error" in declared
                       else "pass")
        return NormalizedHarnessResultV1(
            verdict=overall,
            property_results=properties,
            evidence_artifact_refs=evidence,
            infrastructure_status="ready",
            nondeterminism_observations=(
                () if report.deterministic
                else ("candidate output varied byte-for-byte across a repeat launch "
                      "of the same input; recorded, not failed",)
            ),
        )

    def parity_probe(self, manifest):
        """Clean control passes; a WRONG kernel fails; a merely SLOW one does not.

        The third control is the one that makes this a correctness harness rather
        than a stopwatch with a different label. The performance probe requires
        its two negatives to fail for different reasons; the mirror of that here
        is that the slow control must PASS -- an instrument that refused a
        correct-but-slow kernel would be scoring speed while reporting
        correctness, and every verdict it ever emitted would be unreadable.

        The fourth certifies the OTHER declared property. Numerical equivalence
        and interface conformance are two claims, and a probe that exercised only
        the numbers would register a conformance claim on no evidence.
        """
        problem = load_problem(manifest.oracle.revision)
        definition = problem.definition
        scaffolding = definition.scaffolding
        # WHERE the probe certifies is the PROBLEM's choice, as it is for the
        # performance driver: a probe pinned to the manifest's scored set would
        # compile and run the slow control at every scored shape to establish a
        # property that does not depend on shape. What the registered set is
        # still governs real runs -- ``prepare`` checks it.
        probe_set = definition.parity_case_set or definition.case_set

        def _refused(reason: str) -> dict:
            return {
                "schema_version": "ari.problem-correctness-parity-report/v1",
                "driver_digest": problem_correctness_driver_digest(),
                "case_set": probe_set,
                "problem": definition.revision,
                "problem_digest": problem.digest,
                "results": {},
                "passed": False,
                "reason": reason,
            }

        case_set, _digest = load_case_set(probe_set)
        if case_set.kind != definition.family:
            return _refused(
                f"case set {probe_set!r} is for family {case_set.kind!r}, "
                f"not {definition.family!r}")
        for which, name in (("wrong negative control", scaffolding.negative_control_wrong),
                            ("slow negative control", scaffolding.negative_control_slow),
                            ("seed candidate", scaffolding.seed_candidate)):
            if not name:
                return _refused(_MISSING_CONTROLS.format(
                    revision=definition.revision, which=which))

        def _run(source, **kwargs):
            return verify_problem_correctness(
                problem, source, tier="screen", dataset_revision=probe_set, **kwargs)

        clean = _run(problem.path(scaffolding.reference))
        wrong = _run(problem.path(scaffolding.negative_control_wrong),
                     negative_control=True)
        slow = _run(problem.path(scaffolding.negative_control_slow))
        with tempfile.TemporaryDirectory() as raw_td:
            extra = Path(raw_td) / "interface_control.c"
            extra.write_text(
                problem.path(scaffolding.seed_candidate).read_text(encoding="utf-8")
                + _EXTRA_SYMBOL, encoding="utf-8")
            exports = _run(extra, negative_control=True)

        def _failing_detail(report) -> str:
            """The detail of the case that FAILED, not of case one.

            ``case_results[0]`` is the first case, which is the failing one only
            when the probe set has a single shape. The gate below asserts the
            wrong control was caught by the ORACLE by looking for "residual
            bound" in this string, so reading a passing case's detail would
            check for that phrase in the text "within the residual bound" --
            the sentence that means the candidate was ACCEPTED.
            """
            for case in report.case_results:
                if case.verdict == "fail":
                    return case.detail
            return report.case_results[0].detail if report.case_results else ""

        wrong_detail = _failing_detail(wrong)
        results = {
            "clean_control": {"verdict": clean.verdict,
                              "report_digest": clean.report_digest},
            "negative_control_wrong": {"verdict": wrong.verdict,
                                       "detail": wrong_detail,
                                       "report_digest": wrong.report_digest},
            "specificity_control_slow": {"verdict": slow.verdict,
                                         "report_digest": slow.report_digest},
            "negative_control_extra_symbol": {
                "verdict": exports.verdict,
                "detail": exports.interface_error or "",
                "report_digest": exports.report_digest},
        }
        # The common view the registration gates read; the detail above stays.
        controls = {
            "clean": {
                "verdict": clean.verdict,
                # A correctness verdict is deterministic: there is no run-to-run
                # spread for it to resolve.
                "resolved": True,
                "relative_spread": 0.0,
                # WHAT REPEATING THE PROBE ACTUALLY COMPARES.
                # ``registration_run.probe_repeatedly`` takes the deterministic
                # path for this driver -- no ``median_speedup`` to spread -- and
                # digests THIS DICT on each run, requiring every run to produce
                # the identical answer. With only constants and a coarse verdict
                # in it, that digest was the same for an instrument that had
                # silently started accepting anything, so the stability gate
                # certified a comparison of one fixed string against itself. The
                # report digest moves with the problem, the case set, the
                # toolchain, the candidate and every per-case measurement, so
                # repeating the probe now compares the thing the probe measured.
                "report_digest": clean.report_digest,
                "note": ("the problem's frozen reference passed its own family "
                         "oracle, and a correct-but-slow kernel passed with it"),
            },
            "negatives": [
                {"name": "fast-but-wrong", "verdict": wrong.verdict,
                 "detail": wrong_detail},
                {"name": "exports-extra-symbol", "verdict": exports.verdict,
                 "detail": exports.interface_error or ""},
            ],
        }
        return {
            "schema_version": "ari.problem-correctness-parity-report/v1",
            "driver_digest": problem_correctness_driver_digest(),
            "case_set": probe_set,
            "problem": definition.revision,
            "problem_digest": problem.digest,
            "controls": controls,
            "results": results,
            "passed": (
                clean.verdict == "pass"
                and wrong.verdict == "fail"
                # "FAILED the residual bound", not "residual bound" -- the
                # passing detail is "within the residual bound", so the looser
                # test is satisfied by the sentence that means the candidate was
                # ACCEPTED.
                and "failed the residual bound" in wrong_detail
                # The specificity direction. Without it the three verdicts above
                # are equally consistent with an instrument that fails anything
                # slower than the reference.
                and slow.verdict == "pass"
                and exports.verdict == "fail"
                and bool(exports.interface_error)
            ),
            "reason": None,
        }


__all__ = [
    "PROBLEM_CORRECTNESS_DRIVER_REVISION",
    "ProblemCorrectnessDriver",
    "problem_correctness_driver_digest",
]
