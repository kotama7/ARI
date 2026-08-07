"""Driver for the ARI-native GEMM, SpMM, and Stencil verifier workers."""

from __future__ import annotations

from pathlib import Path

from ari.assurance.models import (
    HarnessPropertyResultV1,
    NormalizedHarnessResultV1,
)
from ari.assurance.native_hpc import (
    NativeHPCVerificationReportV1,
    native_reference,
    registered_native_families,
    verify_native_hpc,
)
from ari.protocols.integrity import bytes_digest, canonical_digest
from ari.research_contract import ResearchArtifactRefV1


NATIVE_DRIVER_REVISION = "ari.assurance.native-hpc/v1"


def native_driver_digest() -> str:
    root = Path(__file__).resolve().parent
    files = (
        root.parent / "native_hpc.py",
        root.parent / "native_hpc_common.py",
        # The registry decides WHICH ORACLE judges a run, so it is as much the
        # instrument as any verifier it dispatches to.
        root.parent / "native_hpc_family.py",
        root.parent / "native_hpc_gemm.py",
        root.parent / "native_hpc_spmm.py",
        root.parent / "native_hpc_stencil.py",
        root / "native.py",
        root / "native_worker.py",
        root / "native_candidate_host.py",
        root / "shared_library.py",
    )
    # No skip-if-absent: a missing verifier file must fail loudly here rather
    # than drop out of the digest, which would make deleting one a change no
    # pin could see.
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"verifier files missing from the digest: {missing}")
    return canonical_digest(
        tuple((path.name, bytes_digest(path.read_bytes())) for path in files)
    )


class NativeHPCDriver:
    """Normalize a locked native worker result; never choose a Harness."""

    revision = NATIVE_DRIVER_REVISION

    def identity(self) -> dict:
        return {
            "driver_revision": self.revision,
            "driver_digest": native_driver_digest(),
        }

    def prepare(self, manifest, request):
        if manifest.driver.revision != self.revision:
            raise ValueError("native Harness uses another driver revision")
        if manifest.driver.sha256 != native_driver_digest():
            raise ValueError("native Harness driver bytes drifted")
        if manifest.kind != "artifact_verifier" or not manifest.accepts_external_target:
            raise ValueError("native HPC driver requires an external artifact verifier")
        if manifest.network_policy != "deny" or manifest.credential_policy != "none":
            raise ValueError("native HPC verifier must be credential-free and network-denied")
        if request.execution_request.network != "deny":
            raise ValueError("native Harness request does not require network isolation")
        container = request.execution_request.container
        if container is None or container.digest != manifest.container.resolved_digest:
            raise ValueError("native Harness request lacks the pinned container identity")
        return None

    def build_request(self, manifest, request):
        return request.execution_request

    @staticmethod
    def _full_log(request, result, role: str) -> bytes:
        artifact = next(item for item in result.artifacts if item.logical_role == role)
        return request.execution_request.workspace.read_bytes(
            artifact.relative_path, max_bytes=result.limits.max_output_bytes
        )

    def normalize_result(self, manifest, request, result):
        evidence = tuple(
            ResearchArtifactRefV1(
                logical_name=item.relative_path,
                digest=item.digest,
                media_type=item.media_type,
                role=f"harness-{item.logical_role}",
                source_run_id=request.run_id,
            )
            for item in result.artifacts
        )
        if result.status in {"timed_out", "cancelled"}:
            verdict = "infrastructure_error"
            return NormalizedHarnessResultV1(
                verdict=verdict,
                property_results=tuple(
                    HarnessPropertyResultV1(
                        property_id=atom.property_id,
                        method=atom.method,
                        tier=atom.tier,
                        tested_scope=atom.scope,
                        verdict=verdict,
                        measurements={},
                        tolerance_evidence={},
                        oracle_comparison={},
                        covered_atom_digests=(atom.atom_digest,),
                        evidence_artifact_refs=evidence,
                    )
                    for atom in request.property_atoms
                ),
                evidence_artifact_refs=evidence,
                infrastructure_status="failed",
                nondeterminism_observations=(result.status,),
            )
        try:
            lines = self._full_log(request, result, "stdout").decode(
                "utf-8", errors="strict"
            ).splitlines()
            report = NativeHPCVerificationReportV1.model_validate_json(
                next(line for line in reversed(lines) if line.strip())
            )
        except Exception:
            return NormalizedHarnessResultV1(
                verdict="infrastructure_error",
                property_results=tuple(
                    HarnessPropertyResultV1(
                        property_id=atom.property_id,
                        method=atom.method,
                        tier=atom.tier,
                        tested_scope=atom.scope,
                        verdict="infrastructure_error",
                        covered_atom_digests=(atom.atom_digest,),
                        evidence_artifact_refs=evidence,
                    )
                    for atom in request.property_atoms
                ),
                evidence_artifact_refs=evidence,
                infrastructure_status="failed",
                nondeterminism_observations=("malformed-native-worker-result",),
            )
        verdict = report.verdict
        failed = sum(item.verdict == "fail" for item in report.case_results)
        max_abs = max((item.max_abs_error for item in report.case_results), default=0.0)
        max_rel = max((item.max_rel_error for item in report.case_results), default=0.0)
        properties = tuple(
            HarnessPropertyResultV1(
                property_id=atom.property_id,
                method=atom.method,
                tier=atom.tier,
                tested_scope=atom.scope,
                verdict=verdict,
                measurements={
                    "case_count": len(report.case_results),
                    "failed_case_count": failed,
                    "max_abs_error": max_abs,
                    "max_rel_error": max_rel,
                },
                tolerance_evidence={"error_model": report.error_model},
                oracle_comparison={
                    "oracle": report.oracle,
                    "report_digest": report.report_digest,
                },
                covered_atom_digests=(atom.atom_digest,),
                evidence_artifact_refs=evidence,
            )
            for atom in request.property_atoms
        )
        return NormalizedHarnessResultV1(
            verdict=verdict,
            property_results=properties,
            evidence_artifact_refs=evidence,
            infrastructure_status="ready",
            nondeterminism_observations=(
                () if report.deterministic else ("candidate output varied across repeats",)
            ),
        )

    def parity_probe(self, manifest):
        """Every REGISTERED family, not a list written here.

        The list was the fifth place the family set appeared, and it was the one
        that decided what the probe certified: a family added everywhere else
        would have been dispatchable, scored and attested while this probe never
        touched it -- and the report would still have said ``passed``.
        """
        results = {}
        for kind in registered_native_families():
            reference = native_reference(kind)
            clean = verify_native_hpc(kind, reference, tier="screen")

            def corrupted(case, _reference=reference):
                output = _reference(case)
                if output:
                    output[0] = output[0] + 1.0
                return output

            negative = verify_native_hpc(
                kind, corrupted, tier="screen", negative_control=True
            )
            results[kind] = {
                "reference_verdict": clean.verdict,
                "reference_report_digest": clean.report_digest,
                "negative_control_verdict": negative.verdict,
                "negative_control_report_digest": negative.report_digest,
            }
        return {
            "schema_version": "ari.native-hpc-parity-report/v1",
            "driver_digest": native_driver_digest(),
            "results": results,
            "passed": all(
                item["reference_verdict"] == "pass"
                and item["negative_control_verdict"] == "fail"
                for item in results.values()
            ),
        }


__all__ = ["NATIVE_DRIVER_REVISION", "NativeHPCDriver", "native_driver_digest"]
