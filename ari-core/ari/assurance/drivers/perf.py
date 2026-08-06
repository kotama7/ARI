"""Driver for the ARI-native performance harnesses.

Fills the `performance-regression` slot that the property vocabulary reserved and
three knowledge-skill import profiles already require, so that requirement stops
resolving to ``no_candidate``.

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

import tempfile
from pathlib import Path

from ari.assurance.models import (
    HarnessPropertyResultV1,
    NormalizedHarnessResultV1,
)
from ari.assurance.native_perf_common import load_case_set
from ari.assurance.native_perf import (
    NativePerfReportV1,
    reference_flags,
    reference_source,
    verify_native_perf,
)
from ari.protocols.integrity import bytes_digest, canonical_digest
from ari.research_contract import ResearchArtifactRefV1


PERF_DRIVER_REVISION = "ari.assurance.native-perf/v1"

#: The case set the parity probe measures at — named and pinned like any other,
#: so the probe cannot certify the harness at a size no scored run uses. Separate
#: from the scored set so a probe can be cheap without silently changing what a
#: scored run measures. Registration has to happen on the node class that
#: measures: at a small shape a single ~20 ms stall against a ~0.2 ms kernel gave
#: a 100x spread here, against 0.095% at the scored shape.
_PARITY_CASE_SET = "native-perf-gemm-cases/v1@parity"

_SLOW_BUT_CORRECT = """#include "gemm_kernel.h"
void gemm(int n, int m, int p, const double *A, const double *B, double *C) {
  for (int i = 0; i < n; i++)
    for (int j = 0; j < m; j++) {
      double s = 0.0;
      for (int l = 0; l < p; l++) s += A[i * p + l] * B[l * m + j];
      C[i * m + j] = s;
    }
}
"""

_FAST_BUT_WRONG = """#include "gemm_kernel.h"
void gemm(int n, int m, int p, const double *A, const double *B, double *C) {
  (void)A; (void)B; (void)p;
  for (int i = 0; i < n * m; i++) C[i] = 0.0;
}
"""


def perf_driver_digest() -> str:
    """Content address for the driver AND the frozen scaffolding it measures with.

    The C files are included deliberately: the denominator is part of the
    instrument, so a driver digest that covered only python would let the
    reference change under a pinned manifest.
    """
    root = Path(__file__).resolve().parent
    package = root.parent
    files = [
        package / "native_perf.py",
        package / "native_perf_common.py",
        package / "native_perf_gemm.py",
        # The profiler is part of the instrument too: a profile taken with a
        # counter tool that changed under a pinned manifest is unattributable.
        package / "native_perf_profile.py",
        root / "perf.py",
        root / "perf_worker.py",
        root / "perf_profile_worker.py",
    ]
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
        # WHICH PROBLEMS is part of what was registered. Resolving the manifest's
        # own dataset revision here is what makes "verified" mean "verified at
        # this size": without it a run could measure anything and still carry an
        # attestation naming this manifest.
        case_set, digest = load_case_set(manifest.dataset.revision)
        if digest != manifest.dataset.sha256:
            raise ValueError(
                f"case set {manifest.dataset.revision!r} does not match the "
                f"manifest pin; the registered problem set has changed")
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
        """Clean control passes, both negative controls fail, for different reasons."""
        flags = " ".join(reference_flags())
        clean = verify_native_perf(
            "gemm", reference_source("gemm"), tier="validate",
            dataset_revision=_PARITY_CASE_SET, candidate_flags=flags,
            regression_threshold=0.95)
        with tempfile.TemporaryDirectory() as raw:
            slow_path = Path(raw, "slow.c")
            slow_path.write_text(_SLOW_BUT_CORRECT)
            slow = verify_native_perf(
                "gemm", slow_path, tier="screen",
                dataset_revision=_PARITY_CASE_SET,
                candidate_flags=flags, regression_threshold=0.95)
            wrong_path = Path(raw, "wrong.c")
            wrong_path.write_text(_FAST_BUT_WRONG)
            wrong = verify_native_perf(
                "gemm", wrong_path, tier="screen",
                dataset_revision=_PARITY_CASE_SET,
                candidate_flags=flags, regression_threshold=0.95)
        slow_detail = slow.case_results[0].detail if slow.case_results else ""
        wrong_detail = wrong.case_results[0].detail if wrong.case_results else ""
        return {
            "schema_version": "ari.native-perf-parity-report/v1",
            "driver_digest": perf_driver_digest(),
            "case_set": _PARITY_CASE_SET,
            "results": {
                "clean_control": {
                    "verdict": clean.verdict,
                    "median_speedup": clean.case_results[0].speedup if clean.case_results else 0.0,
                    "relative_spread": (clean.case_results[0].relative_spread
                                        if clean.case_results else None),
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
            # is a stopwatch that cannot tell a wrong answer from a slow one.
            "passed": (
                clean.verdict == "pass"
                and slow.verdict == "fail"
                and wrong.verdict == "fail"
                and "threshold" in slow_detail
                and "residual bound" in wrong_detail
            ),
        }


__all__ = ["PERF_DRIVER_REVISION", "NativePerfDriver", "perf_driver_digest"]
