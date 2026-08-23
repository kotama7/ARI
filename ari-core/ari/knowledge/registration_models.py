"""Digest-bound empirical evidence for Knowledge Skill registration gates."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ari.knowledge.models import KnowledgeSkillRefV1
from ari.protocols.integrity import (
    DigestBoundModel,
    FULL_GIT_COMMIT_PATTERN,
    SHA256_DIGEST_PATTERN,
    StrictModel,
)


class KnowledgeCleanTaskEvidenceV1(StrictModel):
    status: Literal["pass", "fail", "unsatisfied"]
    methods: tuple[str, ...] = Field(min_length=1)
    artifact_digests: dict[str, str] = Field(min_length=1)
    detail: str = Field(min_length=1, max_length=8192)

    @field_validator("methods")
    @classmethod
    def _methods_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))) or any(not item for item in value):
            raise ValueError("clean-task methods must be unique and sorted")
        return value

    @field_validator("artifact_digests")
    @classmethod
    def _artifacts_are_canonical(cls, value: dict[str, str]) -> dict[str, str]:
        if list(value) != sorted(value) or any(
            not name or re.fullmatch(SHA256_DIGEST_PATTERN, digest) is None
            for name, digest in value.items()
        ):
            raise ValueError("clean-task artifacts must be sorted full SHA-256")
        return value


class KnowledgeProviderPortabilityEvidenceV1(StrictModel):
    """How the Skill was shown not to depend on one Capability Provider.

    ``two-providers`` is the original ecosystem test: the required capability
    set binds and completes on two verified Providers.  It measures the
    Provider population as much as the Skill, so a correct Skill is blocked
    until someone registers a second implementation for unrelated reasons.

    ``synthetic-substitution`` is the artifact-level test: the incumbent is
    withdrawn and the identical contracts are re-offered under a reserved
    stand-in identity.  It proves the requirement set names a capability
    rather than a Provider.  It is strictly weaker -- no second implementation
    ran -- and must not be described as cross-Provider portability.
    """

    status: Literal["pass", "fail", "not_applicable_no_second_provider"]
    method: Literal["two-providers", "synthetic-substitution"] = "two-providers"
    provider_catalog_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    compatible_provider_ids: tuple[str, ...]
    binding_lock_digests: tuple[str, ...] = Field(default_factory=tuple)
    abstraction_report_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    detail: str = Field(min_length=1, max_length=8192)

    @field_validator("compatible_provider_ids", "binding_lock_digests")
    @classmethod
    def _values_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))) or any(not item for item in value):
            raise ValueError("portability identities must be unique and sorted")
        return value

    @model_validator(mode="after")
    def _status_matches_method(self):
        substitution = self.method == "synthetic-substitution"
        if not substitution and self.abstraction_report_digest is not None:
            raise ValueError(
                "an abstraction report belongs to synthetic-substitution only"
            )
        if self.status == "pass":
            if substitution:
                # Baseline and substituted locks: the stand-in must have been
                # bound, not merely offered.
                if self.abstraction_report_digest is None:
                    raise ValueError(
                        "synthetic-substitution pass requires an abstraction report"
                    )
                if len(self.binding_lock_digests) < 2:
                    raise ValueError(
                        "synthetic-substitution pass requires the baseline and "
                        "substituted Binding Locks"
                    )
            elif (
                len(self.compatible_provider_ids) < 2
                or len(self.binding_lock_digests) < 2
            ):
                raise ValueError(
                    "portability pass requires two Providers and two Binding Locks"
                )
        if self.status == "not_applicable_no_second_provider":
            if substitution:
                raise ValueError(
                    "synthetic-substitution is always runnable and is never "
                    "not-applicable"
                )
            if len(self.compatible_provider_ids) > 1:
                raise ValueError("not-applicable portability cannot name two Providers")
        return self


class KnowledgeSkillPromotionApprovalV1(DigestBoundModel):
    """Human/admin authorization for one exact verified Knowledge Skill.

    Passing all sixteen gates makes a Skill *eligible*; it does not promote
    it.  Promotion is this separate authenticated act, bound to the exact
    body, manifest, registration report, and evidence that were reviewed, so
    a later edit to any of them invalidates the approval instead of silently
    inheriting it.
    """

    _digest_field = "approval_digest"

    schema_version: Literal["ari.knowledge-skill-promotion-approval/v1"] = (
        "ari.knowledge-skill-promotion-approval/v1"
    )
    skill_ref: KnowledgeSkillRefV1
    from_status: Literal["candidate"] = "candidate"
    to_status: Literal["verified"] = "verified"
    actor_kind: Literal["human-maintainer", "authenticated-admin-cli"]
    actor_id: str = Field(min_length=1, max_length=512)
    authorization_basis: str = Field(min_length=1, max_length=1024)
    approved_date: str = Field(min_length=10, max_length=64)
    registration_evidence_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    # Optional, and checked when present.  The registration report is derived
    # at load time from the promoted manifest, so requiring its digest here
    # would make an approval unauthorable: the promoter would need a value
    # that only a successful load produces, and the load needs the approval.
    # ``skill_ref`` already pins the exact manifest and body bytes.
    registration_report_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    approval_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


class KnowledgeSkillRegistrationEvidenceV1(DigestBoundModel):
    """Reviewed clean-task and cross-Provider evidence for one exact Skill."""

    _digest_field = "evidence_digest"

    schema_version: Literal["ari.knowledge-skill-registration-evidence/v1"] = (
        "ari.knowledge-skill-registration-evidence/v1"
    )
    skill_ref: KnowledgeSkillRefV1
    source_full_commit_sha: str = Field(pattern=FULL_GIT_COMMIT_PATTERN)
    environment_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    clean_task: KnowledgeCleanTaskEvidenceV1
    provider_portability: KnowledgeProviderPortabilityEvidenceV1
    evidence_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)


__all__ = [
    "KnowledgeCleanTaskEvidenceV1",
    "KnowledgeProviderPortabilityEvidenceV1",
    "KnowledgeSkillPromotionApprovalV1",
    "KnowledgeSkillRegistrationEvidenceV1",
]
