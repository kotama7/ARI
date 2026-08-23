"""Harness registration evidence contracts kept separate from run models."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ari.protocols.integrity import (
    DigestBoundModel,
    FULL_GIT_COMMIT_PATTERN,
    SHA256_DIGEST_PATTERN,
    Sha256Digest,
    StrictModel,
)


class HarnessRegistrationGateV1(StrictModel):
    gate_id: str
    passed: bool
    evidence_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    detail: str = ""


class HarnessRegistrationReportV1(DigestBoundModel):
    _digest_field = "report_digest"

    schema_version: Literal["ari.harness-registration-report/v1"] = (
        "ari.harness-registration-report/v1"
    )
    harness_id: str
    manifest_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    gates: tuple[HarnessRegistrationGateV1, ...]
    decision: Literal["candidate", "eligible-for-verified", "rejected"]
    report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _decision_matches(self):
        if self.decision == "eligible-for-verified" and (
            len(self.gates) != 15 or not all(item.passed for item in self.gates)
        ):
            raise ValueError("verified eligibility requires all fifteen gates")
        return self


class HarnessPromotionApprovalV1(DigestBoundModel):
    """Human/admin authorization for one exact verified Harness manifest."""

    _digest_field = "approval_digest"

    schema_version: Literal["ari.harness-promotion-approval/v1"] = (
        "ari.harness-promotion-approval/v1"
    )
    harness_id: str
    harness_version: str
    from_status: Literal["candidate"] = "candidate"
    to_status: Literal["verified"] = "verified"
    actor_kind: Literal["human-maintainer", "authenticated-admin-cli"]
    actor_id: str = Field(min_length=1, max_length=512)
    authorization_basis: str = Field(min_length=1, max_length=1024)
    approved_date: str = Field(min_length=10, max_length=64)
    harness_manifest_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    registration_report_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    evidence_bundle_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    approval_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class HarnessRegistrationEvidenceV1(DigestBoundModel):
    """Exact evidence bundle reviewed before one Harness promotion."""

    _digest_field = "evidence_digest"

    schema_version: Literal["ari.harness-registration-evidence/v1"] = (
        "ari.harness-registration-evidence/v1"
    )
    harness_id: str
    harness_version: str
    manifest_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    source_full_commit_sha: str = Field(pattern=FULL_GIT_COMMIT_PATTERN)
    environment_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    evidence_artifact_digests: dict[str, Sha256Digest] = Field(min_length=1)
    attestation_digests: tuple[Sha256Digest, ...] = Field(min_length=1)
    clean_control_verdict: Literal["pass", "fail", "not_available"]
    negative_control_verdict: Literal["pass", "fail", "not_available"]
    official_runner_parity: bool
    result_schema_conformant: bool
    network_isolation: Literal["proved", "not_proved"]
    target_write_isolation: Literal["proved", "not_proved"]
    oracle_visibility: Literal["denied", "not_proved"]
    run_count: int = Field(ge=1)
    evidence_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator("evidence_artifact_digests")
    @classmethod
    def _artifacts_are_canonical(cls, value: dict[str, str]) -> dict[str, str]:
        if list(value) != sorted(value) or any(
            not name or not re.fullmatch(SHA256_DIGEST_PATTERN, digest)
            for name, digest in value.items()
        ):
            raise ValueError("registration evidence artifacts must be sorted full SHA-256")
        return value

    @field_validator("attestation_digests")
    @classmethod
    def _attestations_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(value)) or len(value) != len(set(value)):
            raise ValueError("registration Attestations must be uniquely digest-sorted")
        return value


__all__ = [
    "HarnessPromotionApprovalV1",
    "HarnessRegistrationEvidenceV1",
    "HarnessRegistrationGateV1",
    "HarnessRegistrationReportV1",
]
