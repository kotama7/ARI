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
    status: Literal["pass", "fail", "not_applicable_no_second_provider"]
    provider_catalog_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    compatible_provider_ids: tuple[str, ...]
    binding_lock_digests: tuple[str, ...] = Field(default_factory=tuple)
    detail: str = Field(min_length=1, max_length=8192)

    @field_validator("compatible_provider_ids", "binding_lock_digests")
    @classmethod
    def _values_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))) or any(not item for item in value):
            raise ValueError("portability identities must be unique and sorted")
        return value

    @model_validator(mode="after")
    def _status_matches_provider_count(self):
        if self.status == "pass" and (
            len(self.compatible_provider_ids) < 2 or len(self.binding_lock_digests) < 2
        ):
            raise ValueError(
                "portability pass requires two Providers and two Binding Locks"
            )
        if (
            self.status == "not_applicable_no_second_provider"
            and len(self.compatible_provider_ids) > 1
        ):
            raise ValueError("not-applicable portability cannot name two Providers")
        return self


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
    "KnowledgeSkillRegistrationEvidenceV1",
]
