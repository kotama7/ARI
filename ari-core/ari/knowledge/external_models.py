"""Typed admin contracts for pinned external Knowledge imports."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ari.knowledge.models import (
    KnowledgeAuthorityCeilingV1,
    KnowledgeCapabilityRequirementV1,
    KnowledgeCapabilitySetV1,
    KnowledgeCompositionV1,
    KnowledgeSkillApplicabilityV1,
    KnowledgeSkillLicenseV1,
    KnowledgeSkillManifestV1,
    KnowledgeSkillRefV1,
)
from ari.protocols.integrity import (
    DigestBoundModel,
    FULL_GIT_COMMIT_PATTERN,
    SHA256_DIGEST_PATTERN,
    StrictModel,
    bytes_digest,
)
from ari.protocols.scientific_requirements import EvaluationObligationV1


_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,255}$"
_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"
_COLLECTION_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"


def _safe_relative(value: str) -> str:
    from pathlib import PurePosixPath

    text = value.strip()
    path = PurePosixPath(text)
    if (
        not text
        or "\\" in text
        or path.is_absolute()
        or ".." in path.parts
        or any(ord(character) < 32 for character in text)
    ):
        raise ValueError("path must be safe and POSIX-relative")
    return path.as_posix()


class KnowledgeSkillImportProfileV1(StrictModel):
    """Human-reviewed semantics applied to untrusted external content.

    The upstream package cannot grant capabilities or authority by placing
    fields in its own frontmatter.  Those fields exist only in this separate
    admin input, whose digest is retained in import provenance.
    """

    schema_version: Literal[1] = 1
    id: str = Field(pattern=_ID_PATTERN)
    version: str = Field(pattern=_VERSION_PATTERN)
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=4096)
    license: KnowledgeSkillLicenseV1
    applies_to: KnowledgeSkillApplicabilityV1
    requires: KnowledgeCapabilitySetV1 = Field(default_factory=KnowledgeCapabilitySetV1)
    optional_capabilities: tuple[KnowledgeCapabilityRequirementV1, ...] = Field(
        default_factory=tuple
    )
    evaluation_obligations: tuple[EvaluationObligationV1, ...] = Field(
        default_factory=tuple
    )
    authority_ceiling: KnowledgeAuthorityCeilingV1
    forbidden_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    dependencies: tuple[KnowledgeSkillRefV1, ...] = Field(default_factory=tuple)
    conflicts: tuple[str, ...] = Field(default_factory=tuple)
    composition: KnowledgeCompositionV1
    body_normalization: Literal["strict", "ari-wrapper-v1"] = "strict"
    curation_notes: tuple[str, ...] = Field(default_factory=tuple, max_length=64)

    @field_validator("curation_notes")
    @classmethod
    def _curation_notes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value or len(value) > 4096 for value in normalized) or len(
            normalized
        ) != len(set(normalized)):
            raise ValueError("curation notes must be non-empty, bounded, and unique")
        return normalized

    @model_validator(mode="after")
    def _curation_requires_wrapper(self):
        if self.body_normalization == "strict" and self.curation_notes:
            raise ValueError("curation notes require ari-wrapper-v1 normalization")
        return self


class KnowledgeExternalSourceProvenanceV1(DigestBoundModel):
    _digest_field = "provenance_digest"

    schema_version: Literal["ari.knowledge-external-source-provenance/v1"] = (
        "ari.knowledge-external-source-provenance/v1"
    )
    source_kind: Literal[
        "git",
        "open-agent-skills",
        "tooluniverse-knowledge",
        "scientific-skill-repository",
    ]
    layout: Literal["plain", "open-agent-skills"]
    adapter_version: Literal["ari.knowledge.external-importer/v1"] = (
        "ari.knowledge.external-importer/v1"
    )
    repository: str = Field(min_length=1, max_length=4096)
    commit: str = Field(pattern=FULL_GIT_COMMIT_PATTERN)
    subpath: str = Field(min_length=1, max_length=1024)
    snapshot_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    source_skill_md_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    import_profile_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    upstream_metadata_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    upstream_name: str | None = Field(default=None, min_length=1, max_length=64)
    body_normalization: Literal["strict", "ari-wrapper-v1"] = "strict"
    collection_identity_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    provenance_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator("subpath")
    @classmethod
    def _subpath(cls, value: str) -> str:
        return _safe_relative(value)


class KnowledgeImportAttachmentV1(StrictModel):
    path: str
    sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    executable_in_source: bool
    authority: Literal["none"] = "none"

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return _safe_relative(value)


class KnowledgeImportMaterialV1(DigestBoundModel):
    """Self-contained, candidate-only output of the external importer.

    The canonical body is included so a checked-in catalog can load without
    fetching the external repository again.  The original source bytes remain
    independently bound by ``source_provenance.source_skill_md_sha256``.
    """

    _digest_field = "material_digest"

    schema_version: Literal["ari.knowledge-import-material/v1"] = (
        "ari.knowledge-import-material/v1"
    )
    decision: Literal["candidate"] = "candidate"
    authoritative: Literal[False] = False
    manifest: KnowledgeSkillManifestV1
    body: str = Field(min_length=1, max_length=1024 * 1024)
    body_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    reference_digests: dict[str, str] = Field(default_factory=dict)
    attachments: tuple[KnowledgeImportAttachmentV1, ...] = Field(default_factory=tuple)
    non_authoritative_tool_hints: tuple[str, ...] = Field(default_factory=tuple)
    source_provenance: KnowledgeExternalSourceProvenanceV1 | None = None
    material_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator("reference_digests")
    @classmethod
    def _reference_digests(cls, values: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for path, digest in sorted(values.items()):
            safe = _safe_relative(path)
            if not safe.startswith("references/"):
                raise ValueError("imported references must stay under references/")
            if re.fullmatch(SHA256_DIGEST_PATTERN, str(digest)) is None:
                raise ValueError("imported reference requires a full SHA-256")
            normalized[safe] = str(digest)
        if len(normalized) != len(values):
            raise ValueError("imported reference paths must be unique")
        return normalized

    @field_validator("attachments")
    @classmethod
    def _attachments(
        cls, values: tuple[KnowledgeImportAttachmentV1, ...]
    ) -> tuple[KnowledgeImportAttachmentV1, ...]:
        paths = tuple(item.path for item in values)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("import attachments must be unique and path-sorted")
        return values

    @field_validator("non_authoritative_tool_hints")
    @classmethod
    def _tool_hints(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("non-authoritative tool hints must be unique and sorted")
        return values

    @model_validator(mode="after")
    def _material_is_internally_consistent(self):
        if bytes_digest(self.body.encode("utf-8")) != self.body_sha256:
            raise ValueError("import material body digest mismatch")
        if self.manifest.source.body_sha256 != self.body_sha256:
            raise ValueError("import material manifest refers to a different body")
        expected_references = {
            item.path: item.sha256 for item in self.manifest.references
        }
        if self.reference_digests != expected_references:
            raise ValueError("import material reference digests differ from manifest")
        reference_paths = set(self.reference_digests)
        if reference_paths & {item.path for item in self.attachments}:
            raise ValueError("an imported path cannot be both reference and attachment")
        if self.source_provenance is not None:
            source = self.manifest.source
            provenance = self.source_provenance
            if (
                source.repository != provenance.repository
                or source.commit != provenance.commit
                or source.path != provenance.subpath
            ):
                raise ValueError("import provenance differs from manifest source")
        return self


class KnowledgeCollectionImportEntryV1(StrictModel):
    subpath: str
    layout: Literal["plain", "open-agent-skills"] = "open-agent-skills"
    profile: KnowledgeSkillImportProfileV1

    @field_validator("subpath")
    @classmethod
    def _subpath(cls, value: str) -> str:
        return _safe_relative(value)


class ToolUniverseKnowledgeCollectionProfileV1(StrictModel):
    """ARI-side import policy for a pinned ToolUniverse Knowledge collection.

    This deliberately has no MCP Provider identity, launcher, credential, or
    tool fields.  Loading it can only produce candidate Knowledge artifacts.
    """

    schema_version: Literal[1] = 1
    kind: Literal["tooluniverse-knowledge"] = "tooluniverse-knowledge"
    collection_id: str = Field(pattern=_COLLECTION_ID_PATTERN)
    version: str = Field(pattern=_VERSION_PATTERN)
    entries: tuple[KnowledgeCollectionImportEntryV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _entries_are_unique(self):
        paths = [item.subpath for item in self.entries]
        ids = [item.profile.id for item in self.entries]
        if len(paths) != len(set(paths)):
            raise ValueError("collection entry subpaths must be unique")
        if len(ids) != len(set(ids)):
            raise ValueError("collection Knowledge Skill ids must be unique")
        return self


class KnowledgeCollectionImportProvenanceV1(DigestBoundModel):
    _digest_field = "collection_identity_digest"

    schema_version: Literal["ari.knowledge-collection-import-provenance/v1"] = (
        "ari.knowledge-collection-import-provenance/v1"
    )
    collection_uri: str = Field(
        pattern=r"^ari://knowledge-source/tooluniverse/[a-z0-9._-]+@[0-9A-Za-z.+-]+$"
    )
    repository: str = Field(min_length=1, max_length=4096)
    commit: str = Field(pattern=FULL_GIT_COMMIT_PATTERN)
    root_subpath: str = Field(min_length=1, max_length=1024)
    import_profile_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    skill_snapshot_digests: tuple[str, ...] = Field(min_length=1)
    collection_identity_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @field_validator("root_subpath")
    @classmethod
    def _root_subpath(cls, value: str) -> str:
        return _safe_relative(value)

    @field_validator("skill_snapshot_digests")
    @classmethod
    def _skill_digests(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(values))
        if normalized != values or len(values) != len(set(values)):
            raise ValueError("skill snapshot digests must be unique and sorted")
        return values


__all__ = [
    "KnowledgeCollectionImportEntryV1",
    "KnowledgeCollectionImportProvenanceV1",
    "KnowledgeExternalSourceProvenanceV1",
    "KnowledgeImportAttachmentV1",
    "KnowledgeImportMaterialV1",
    "KnowledgeSkillImportProfileV1",
    "ToolUniverseKnowledgeCollectionProfileV1",
]
