"""Strict normalization shared by pinned external Harness adapters."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ari.assurance.models import HarnessPropertyResultV1, NormalizedHarnessResultV1
from ari.protocols.integrity import (
    DigestBoundModel,
    FULL_GIT_COMMIT_PATTERN,
    SHA256_DIGEST_PATTERN,
    StrictModel,
    ZERO_SHA256,
    bytes_digest,
    canonical_digest,
)
from ari.research_contract import ResearchArtifactRefV1


EXTERNAL_RESULT_SCHEMA = "ari.external-harness-result/v1"
_VERDICT_RANK = {
    "pass": 0,
    "inconclusive": 1,
    "infrastructure_error": 2,
    "fail": 3,
    "tampered": 4,
}


class ExternalParityCheckV1(StrictModel):
    check_id: str
    status: Literal["passed", "failed", "not_available"]
    evidence_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    detail: str = ""


class ExternalHarnessParityReportV1(DigestBoundModel):
    """Digest-bound evidence from an official runner and ARI adapter.

    API imports and scorer-unit checks may be retained as non-authoritative
    checks, but they cannot satisfy ``official_runner_parity``.
    """

    _digest_field = "report_digest"

    schema_version: Literal["ari.external-harness-parity/v1"] = (
        "ari.external-harness-parity/v1"
    )
    harness_id: str
    manifest_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    source_revision: str = Field(pattern=FULL_GIT_COMMIT_PATTERN)
    dataset_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    container_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    driver_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    official_runner_invocation_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    official_result_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    normalized_result_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    reference_verdict: Literal["pass", "fail", "not_available"]
    negative_control_verdict: Literal["pass", "fail", "not_available"]
    result_schema_parity: bool
    official_runner_parity: bool
    status: Literal["passed", "failed", "not_available"]
    unavailable_reasons: tuple[str, ...] = ()
    non_authoritative_checks: tuple[ExternalParityCheckV1, ...] = ()
    report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _coherent(self):
        checks = [item.check_id for item in self.non_authoritative_checks]
        if checks != sorted(checks) or len(checks) != len(set(checks)):
            raise ValueError("external parity checks must be uniquely sorted")
        if self.status == "passed":
            pinned_digests = (
                self.manifest_digest,
                self.dataset_digest,
                self.container_digest,
                self.driver_digest,
                self.official_runner_invocation_digest,
                self.official_result_digest,
                self.normalized_result_digest,
            )
            required = (
                self.official_runner_parity,
                self.result_schema_parity,
                self.reference_verdict == "pass",
                self.negative_control_verdict == "fail",
                self.official_runner_invocation_digest is not None,
                self.official_result_digest is not None,
                self.normalized_result_digest is not None,
                ZERO_SHA256 not in pinned_digests,
                not self.unavailable_reasons,
            )
            if not all(required):
                raise ValueError(
                    "passed parity requires official execution, controls, and exact results"
                )
        if self.status == "not_available":
            if self.official_runner_parity or not self.unavailable_reasons:
                raise ValueError(
                    "not_available parity requires an explicit external prerequisite"
                )
        return self


class ExternalAtomResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    atom_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    verdict: Literal[
        "pass", "fail", "inconclusive", "infrastructure_error", "tampered"
    ]
    measurements: dict[str, Any] = Field(default_factory=dict)
    tolerance_evidence: dict[str, Any] = Field(default_factory=dict)
    oracle_comparison: dict[str, Any] = Field(default_factory=dict)


class ExternalHarnessResultV1(BaseModel):
    """Envelope a reviewed upstream wrapper must print as its final line."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.external-harness-result/v1"] = EXTERNAL_RESULT_SCHEMA
    harness_id: str
    harness_manifest_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    target_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    upstream_source_revision: str
    dataset_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    oracle_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    driver_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    container_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    verdict: Literal[
        "pass", "fail", "inconclusive", "infrastructure_error", "tampered"
    ]
    atom_results: tuple[ExternalAtomResultV1, ...]
    infrastructure_status: Literal["ready", "failed", "degraded"]
    nondeterminism_observations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _coherent(self):
        valid = set(_VERDICT_RANK)
        if self.verdict not in valid or any(item.verdict not in valid for item in self.atom_results):
            raise ValueError("external verdict is outside the closed vocabulary")
        atoms = [item.atom_digest for item in self.atom_results]
        if atoms != sorted(atoms) or len(atoms) != len(set(atoms)):
            raise ValueError("external atom results must be uniquely digest-sorted")
        if self.infrastructure_status not in {"ready", "failed", "degraded"}:
            raise ValueError("external infrastructure status is invalid")
        if self.verdict == "pass" and {item.verdict for item in self.atom_results} != {"pass"}:
            raise ValueError("external pass requires every atom to pass")
        if self.verdict == "fail" and not any(item.verdict == "fail" for item in self.atom_results):
            raise ValueError("external fail requires a failed atom")
        if self.verdict == "infrastructure_error" and self.infrastructure_status == "ready":
            raise ValueError("infrastructure_error cannot report ready infrastructure")
        return self


def external_driver_digest(*paths: Path, identity: str) -> str:
    return canonical_digest({
        "identity": identity,
        "files": [
            (path.name, bytes_digest(path.read_bytes())) for path in sorted(paths)
        ],
    })


class LockedExternalDriver:
    """Base for adapters that invoke, but never reimplement, official runners."""

    revision = ""
    allowed_harness_ids: frozenset[str] = frozenset()

    def __init__(
        self,
        *,
        parity_reports: Mapping[
            str, ExternalHarnessParityReportV1 | dict
        ]
        | None = None,
    ) -> None:
        self._parity_reports = dict(parity_reports or {})

    def driver_digest(self) -> str:
        module = __import__(type(self).__module__, fromlist=["__file__"])
        return external_driver_digest(
            Path(__file__).resolve(), Path(module.__file__).resolve(), identity=self.revision
        )

    def identity(self) -> dict[str, str]:
        return {"driver_revision": self.revision, "driver_digest": self.driver_digest()}

    def prepare(self, manifest, request):
        if manifest.id not in self.allowed_harness_ids:
            raise ValueError("external driver is not registered for this Harness id")
        if manifest.driver.revision != self.revision:
            raise ValueError("external Harness uses another driver revision")
        if manifest.driver.sha256 != self.driver_digest():
            raise ValueError("external Harness driver bytes drifted")
        if request.harness.driver_digest != manifest.driver.sha256:
            raise ValueError("request driver pin differs from Harness Manifest")
        if request.expected_result_schema != manifest.expected_result_schema:
            raise ValueError("external expected-result schema drifted")
        if request.execution_request.shell_command is not None:
            raise ValueError("external Harness requires argv, never shell text")
        # ExecutionRequestV1 deliberately has no implicit allowlist semantics.
        # An allowlisted external Harness therefore remains inadmissible until
        # a reviewed executor can prove the exact allowlist.  Never translate
        # ``allowlisted`` to the legacy ``inherit`` value.
        if manifest.network_policy != "deny" or request.execution_request.network != "deny":
            raise ValueError("external Harness v1 requires a proved network-deny substrate")
        container = request.execution_request.container
        if container is None or container.digest != manifest.container.resolved_digest:
            raise ValueError("external Harness lacks its pinned container")
        self.validate_locked_argv(manifest, tuple(request.execution_request.argv or ()))

    def validate_locked_argv(self, manifest, argv: tuple[str, ...]) -> None:
        raise NotImplementedError

    def build_request(self, manifest, request):
        return request.execution_request

    @staticmethod
    def _evidence(request, result) -> tuple[ResearchArtifactRefV1, ...]:
        return tuple(
            ResearchArtifactRefV1(
                logical_name=item.relative_path,
                digest=item.digest,
                media_type=item.media_type,
                role=f"harness-{item.logical_role}",
                source_run_id=request.run_id,
            )
            for item in result.artifacts
        )

    @staticmethod
    def _stdout(request, result) -> str:
        stdout = next(
            (item for item in result.artifacts if item.logical_role == "stdout"), None
        )
        if stdout is None:
            raise ValueError("external Harness produced no stdout artifact")
        return request.execution_request.workspace.read_bytes(
            stdout.relative_path, max_bytes=result.limits.max_output_bytes
        ).decode("utf-8", errors="strict")

    def _infrastructure_result(self, request, result, reason: str):
        evidence = self._evidence(request, result)
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
            nondeterminism_observations=(reason,),
        )

    def normalize_result(self, manifest, request, result):
        if result.status in {"timed_out", "cancelled"}:
            return self._infrastructure_result(request, result, result.status)
        try:
            lines = [line for line in self._stdout(request, result).splitlines() if line.strip()]
            upstream = ExternalHarnessResultV1.model_validate_json(lines[-1])
            exact = {
                "harness_id": (upstream.harness_id, manifest.id),
                "harness_manifest_digest": (
                    upstream.harness_manifest_digest, manifest.manifest_digest
                ),
                "target_digest": (upstream.target_digest, request.target_digest),
                "upstream_source_revision": (
                    upstream.upstream_source_revision, manifest.source_full_commit_sha
                ),
                "dataset_digest": (upstream.dataset_digest, manifest.dataset.sha256),
                "oracle_digest": (upstream.oracle_digest, manifest.oracle.sha256),
                "driver_digest": (upstream.driver_digest, manifest.driver.sha256),
                "container_digest": (
                    upstream.container_digest, manifest.container.resolved_digest
                ),
            }
            mismatches = [name for name, pair in exact.items() if pair[0] != pair[1]]
            if mismatches:
                raise ValueError("external result pin mismatch: " + ", ".join(mismatches))
            expected_atoms = {item.atom_digest: item for item in request.property_atoms}
            actual_atoms = {item.atom_digest: item for item in upstream.atom_results}
            if set(actual_atoms) != set(expected_atoms):
                raise ValueError("external result does not cover exactly the locked atoms")
        except Exception as exc:
            return self._infrastructure_result(
                request, result, f"malformed-or-drifted-upstream-result:{type(exc).__name__}"
            )
        evidence = self._evidence(request, result)
        properties = tuple(
            HarnessPropertyResultV1(
                property_id=expected_atoms[digest].property_id,
                method=expected_atoms[digest].method,
                tier=expected_atoms[digest].tier,
                tested_scope=expected_atoms[digest].scope,
                verdict=actual_atoms[digest].verdict,
                measurements=actual_atoms[digest].measurements,
                tolerance_evidence=actual_atoms[digest].tolerance_evidence,
                oracle_comparison=actual_atoms[digest].oracle_comparison,
                covered_atom_digests=(digest,),
                evidence_artifact_refs=evidence,
            )
            for digest in sorted(expected_atoms)
        )
        aggregate = max(
            (item.verdict for item in properties), key=lambda item: _VERDICT_RANK[item]
        )
        if aggregate != upstream.verdict:
            return self._infrastructure_result(request, result, "upstream-aggregate-mismatch")
        return NormalizedHarnessResultV1(
            verdict=upstream.verdict,
            property_results=properties,
            evidence_artifact_refs=evidence,
            infrastructure_status=upstream.infrastructure_status,
            nondeterminism_observations=upstream.nondeterminism_observations,
        )

    def parity_probe(self, manifest):
        report = self._parity_reports.get(manifest.id)
        if report is None:
            return {
                "schema_version": "ari.external-harness-parity/v1",
                "harness_id": manifest.id,
                "status": "not_available",
                "passed": False,
                "reason": "digest-bound official-runner parity report was not supplied",
            }
        try:
            typed = (
                report
                if isinstance(report, ExternalHarnessParityReportV1)
                else ExternalHarnessParityReportV1.model_validate(report)
            )
        except (ValidationError, ValueError) as exc:
            return {
                "schema_version": "ari.external-harness-parity/v1",
                "harness_id": manifest.id,
                "status": "failed",
                "passed": False,
                "reason": f"malformed parity report: {type(exc).__name__}",
            }
        required = {
            "harness_id": manifest.id,
            "manifest_digest": manifest.manifest_digest,
            "source_revision": manifest.source_full_commit_sha,
            "dataset_digest": manifest.dataset.sha256,
            "container_digest": manifest.container.resolved_digest,
            "driver_digest": manifest.driver.sha256,
        }
        document = typed.model_dump(mode="json")
        mismatches = [
            key for key, value in required.items() if document.get(key) != value
        ]
        passed = not mismatches and typed.status == "passed"
        return {
            "schema_version": "ari.external-harness-parity/v1",
            "harness_id": manifest.id,
            "status": typed.status if not mismatches else "failed",
            "passed": passed,
            "mismatches": mismatches,
            "unavailable_reasons": list(typed.unavailable_reasons),
            "non_authoritative_checks": [
                item.model_dump(mode="json")
                for item in typed.non_authoritative_checks
            ],
            "report_digest": typed.report_digest,
        }


__all__ = [
    "EXTERNAL_RESULT_SCHEMA",
    "ExternalHarnessParityReportV1",
    "ExternalParityCheckV1",
    "ExternalHarnessResultV1",
    "LockedExternalDriver",
    "external_driver_digest",
]
