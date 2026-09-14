"""Atomic Knowledge–Capability–Assurance run admission.

The fixed binders/resolver return values; this trusted facade alone persists
their schema-specific artifacts.  A directory rename publishes the complete
baseline set at once, so an interrupted admission can never leave a partial
set that a resume mistakes for authoritative state.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ari.protocols.integrity import (
    DigestBoundModel,
    SHA256_DIGEST_PATTERN,
    canonical_digest,
)
from ari.protocols.immutable_store import rendered_json


ADMISSION_RELATIVE_DIR = Path("rqgm") / "kca" / "admission-v1"
ADMISSION_FILENAME = "run_admission.json"


class KCAModeSnapshotV1(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    knowledge: Literal["off", "audit", "enforce"]
    capability_binding: Literal["legacy", "audit", "enforce"]
    assurance: Literal["off", "audit", "enforce"]


class KCARunAdmissionV1(DigestBoundModel):
    _digest_field = "admission_digest"

    schema_version: Literal["ari.rqgm-kca-run-admission/v1"] = (
        "ari.rqgm-kca-run-admission/v1"
    )
    run_id: str = Field(min_length=1)
    modes: KCAModeSnapshotV1
    constitution_sha256: str = Field(pattern=SHA256_DIGEST_PATTERN)
    fixed_component_ids: tuple[str, ...]
    research_contract_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)
    knowledge_catalog_snapshot_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    knowledge_skill_lock_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    capability_ontology_snapshot_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    provider_catalog_snapshot_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    provider_lock_digest: str | None = Field(default=None, pattern=SHA256_DIGEST_PATTERN)
    capability_binding_lock_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    verification_contract_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    harness_catalog_snapshot_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    baseline_harness_lock_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    active_harness_lock_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    verification_environment_digest: str | None = Field(
        default=None, pattern=SHA256_DIGEST_PATTERN
    )
    oracle_bundle_digest: str | None = Field(default=None, pattern=SHA256_DIGEST_PATTERN)
    artifact_digests: dict[str, str]
    admission_digest: str = Field(pattern=SHA256_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _enforced_layers_are_complete(self):
        if self.modes.knowledge == "enforce" and not (
            self.knowledge_catalog_snapshot_digest and self.knowledge_skill_lock_digest
        ):
            raise ValueError("knowledge.enforce requires catalog and epoch lock")
        if self.modes.capability_binding == "enforce" and not all((
            self.capability_ontology_snapshot_digest,
            self.provider_catalog_snapshot_digest,
            self.provider_lock_digest,
            self.capability_binding_lock_digest,
        )):
            raise ValueError("capability_binding.enforce requires ontology/provider/binding locks")
        if self.modes.assurance == "enforce" and not all((
            self.verification_contract_digest,
            self.harness_catalog_snapshot_digest,
            self.baseline_harness_lock_digest,
            self.active_harness_lock_digest,
            self.verification_environment_digest,
            self.oracle_bundle_digest,
        )):
            raise ValueError("assurance.enforce requires Verification/Harness baseline identities")
        if self.baseline_harness_lock_digest and (
            self.active_harness_lock_digest is None
        ):
            raise ValueError("an active Harness lock identity is required with a baseline")
        for name, digest in self.artifact_digests.items():
            if not name or not digest.startswith("sha256:") or len(digest) != 71:
                raise ValueError("artifact_digests must use safe names and full SHA-256")
        return self

    def scientific_identity(self) -> dict[str, str]:
        """Full-digest fields committed into an execution epoch."""

        return {
            key: value
            for key, value in {
                "research_contract_digest": self.research_contract_digest,
                "knowledge_catalog_snapshot_digest": self.knowledge_catalog_snapshot_digest,
                "knowledge_skill_lock_digest": self.knowledge_skill_lock_digest,
                "capability_ontology_snapshot_digest": self.capability_ontology_snapshot_digest,
                "provider_catalog_snapshot_digest": self.provider_catalog_snapshot_digest,
                "provider_lock_digest": self.provider_lock_digest,
                "capability_binding_lock_digest": self.capability_binding_lock_digest,
                "verification_contract_digest": self.verification_contract_digest,
                "harness_catalog_snapshot_digest": self.harness_catalog_snapshot_digest,
                "baseline_harness_lock_digest": self.baseline_harness_lock_digest,
                "active_harness_lock_digest": self.active_harness_lock_digest,
                "verification_environment_digest": self.verification_environment_digest,
                "oracle_bundle_digest": self.oracle_bundle_digest,
                "kca_run_admission_digest": self.admission_digest,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class KCAAdmissionArtifacts:
    admission: KCARunAdmissionV1
    documents: dict[str, BaseModel | dict[str, Any]]


_SAFE_DOCUMENT_NAMES = frozenset({
    "research_contract.json",
    "knowledge_catalog_snapshot.json",
    "knowledge_selection_proposal.json",
    "knowledge_admission_context.json",
    "knowledge_skill_lock.json",
    "knowledge_bodies.json",
    "capability_ontology_snapshot.json",
    "provider_catalog_snapshot.json",
    "provider_lock.json",
    "capability_binding_request.json",
    "capability_binding_lock.json",
    "capability_binding_report.json",
    "verification_contract.json",
    "harness_catalog_snapshot.json",
    "harness_suite.json",
    "baseline_harness_lock.json",
    "verification_environment.json",
})


def build_run_admission(
    *,
    run_id: str,
    modes: KCAModeSnapshotV1,
    research_contract,
    documents: dict[str, BaseModel | dict[str, Any]],
    identity_fields: dict[str, str | None],
    oracle_bundle_digest: str | None = None,
) -> KCAAdmissionArtifacts:
    """Validate cross-artifact identity and mint one admission record."""

    unknown = set(documents) - _SAFE_DOCUMENT_NAMES
    if unknown:
        raise ValueError(f"unsupported admission document names: {sorted(unknown)}")
    from ari.rqgm.kernel_rules import CONSTITUTION_SHA256
    from ari.rqgm.prompt_spec import KCA_FIXED_COMPONENT_TABLE

    research_digest = str(getattr(research_contract, "contract_digest", "") or "")
    if not research_digest:
        raise ValueError("run admission requires a digest-bound Research Contract")
    artifact_digests = {
        name: canonical_digest(value) for name, value in sorted(documents.items())
    }
    values = dict(identity_fields)
    admission = KCARunAdmissionV1.create(
        run_id=run_id,
        modes=modes,
        constitution_sha256=CONSTITUTION_SHA256,
        fixed_component_ids=tuple(row[0] for row in KCA_FIXED_COMPONENT_TABLE),
        research_contract_digest=research_digest,
        oracle_bundle_digest=oracle_bundle_digest,
        artifact_digests=artifact_digests,
        **values,
    )
    _validate_document_bindings(admission, documents)
    return KCAAdmissionArtifacts(admission=admission, documents=dict(documents))


def _document(name: str, documents: dict[str, Any]) -> dict:
    value = documents.get(name)
    if value is None:
        return {}
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value)


def _validate_document_bindings(
    admission: KCARunAdmissionV1, documents: dict[str, BaseModel | dict[str, Any]]
) -> None:
    """Reject mixed contracts/locks before any bytes are persisted."""

    expected = {
        "research_contract.json": ("contract_digest", admission.research_contract_digest),
        "knowledge_catalog_snapshot.json": (
            "snapshot_digest", admission.knowledge_catalog_snapshot_digest
        ),
        "knowledge_skill_lock.json": ("lock_digest", admission.knowledge_skill_lock_digest),
        "capability_ontology_snapshot.json": (
            "snapshot_digest", admission.capability_ontology_snapshot_digest
        ),
        "provider_catalog_snapshot.json": (
            "snapshot_digest", admission.provider_catalog_snapshot_digest
        ),
        "capability_binding_lock.json": (
            "lock_digest", admission.capability_binding_lock_digest
        ),
        "verification_contract.json": (
            "contract_digest", admission.verification_contract_digest
        ),
        "harness_catalog_snapshot.json": (
            "snapshot_digest", admission.harness_catalog_snapshot_digest
        ),
        "baseline_harness_lock.json": (
            "lock_digest", admission.baseline_harness_lock_digest
        ),
        "verification_environment.json": (
            "identity_digest", admission.verification_environment_digest
        ),
    }
    for name, (field, digest) in expected.items():
        value = _document(name, documents)
        if digest is None:
            if value:
                raise ValueError(f"{name} is present while its layer identity is disabled")
            continue
        if not value or str(value.get(field, "")) != digest:
            raise ValueError(f"{name} does not match run admission identity")
    provider = _document("provider_lock.json", documents)
    if admission.provider_lock_digest is not None:
        if not provider or canonical_digest(provider) != admission.provider_lock_digest:
            raise ValueError("Provider Lock document does not match admission identity")
    knowledge = _document("knowledge_skill_lock.json", documents)
    if knowledge and str(knowledge.get("research_contract_digest", "")) != (
        admission.research_contract_digest
    ):
        raise ValueError("Knowledge lock belongs to another Research Contract")
    bodies = _document("knowledge_bodies.json", documents)
    if bodies:
        from ari.protocols.integrity import bytes_digest

        for digest, body in bodies.items():
            if bytes_digest(str(body).encode("utf-8")) != str(digest):
                raise ValueError("persisted Knowledge body digest mismatch")
    binding = _document("capability_binding_lock.json", documents)
    if binding and admission.provider_lock_digest != str(binding.get("provider_lock_digest", "")):
        raise ValueError("Capability Binding belongs to another Provider Lock")
    verification = _document("verification_contract.json", documents)
    if verification and str(verification.get("research_contract_digest", "")) != (
        admission.research_contract_digest
    ):
        raise ValueError("Verification Contract belongs to another Research Contract")
    harness = _document("baseline_harness_lock.json", documents)
    if harness and str(harness.get("verification_contract_digest", "")) != (
        admission.verification_contract_digest
    ):
        raise ValueError("Harness Lock belongs to another Verification Contract")


def persist_run_admission(
    checkpoint_dir: str | Path, artifacts: KCAAdmissionArtifacts
) -> Path:
    """Publish all baseline artifacts by one atomic same-filesystem rename."""

    root = Path(checkpoint_dir)
    parent = root / ADMISSION_RELATIVE_DIR.parent
    final = root / ADMISSION_RELATIVE_DIR
    parent.mkdir(parents=True, exist_ok=True)
    documents = {
        ADMISSION_FILENAME: artifacts.admission,
        **artifacts.documents,
    }
    if final.exists():
        loaded = load_run_admission(root)
        if loaded != artifacts.admission:
            raise ValueError("persisted KCA run admission differs from requested admission")
        for name, value in documents.items():
            path = final / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != rendered_json(value):
                raise ValueError(f"persisted KCA admission artifact mismatch: {name}")
        return final
    temporary = Path(tempfile.mkdtemp(prefix=".admission-v1.", dir=parent))
    try:
        for name, value in sorted(documents.items()):
            path = temporary / name
            path.write_bytes(rendered_json(value))
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        directory_fd = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        try:
            os.rename(temporary, final)
        except FileExistsError:
            loaded = load_run_admission(root)
            if loaded != artifacts.admission:
                raise ValueError("concurrent KCA run admission mismatch")
        return final
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def load_run_admission(checkpoint_dir: str | Path) -> KCARunAdmissionV1:
    path = Path(checkpoint_dir) / ADMISSION_RELATIVE_DIR / ADMISSION_FILENAME
    if path.is_symlink():
        raise ValueError("KCA run admission symbolic link is refused")
    document = json.loads(path.read_text(encoding="utf-8"))
    return KCARunAdmissionV1.model_validate(document)


def load_admission_artifacts(checkpoint_dir: str | Path) -> KCAAdmissionArtifacts:
    root = Path(checkpoint_dir) / ADMISSION_RELATIVE_DIR
    admission = load_run_admission(checkpoint_dir)
    documents: dict[str, dict] = {}
    for name in admission.artifact_digests:
        if name not in _SAFE_DOCUMENT_NAMES:
            raise ValueError("persisted admission names an unsupported artifact")
        path = root / name
        if path.is_symlink():
            raise ValueError(f"admission artifact symlink refused: {name}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if canonical_digest(value) != admission.artifact_digests[name]:
            raise ValueError(f"admission artifact digest mismatch: {name}")
        documents[name] = value
    _validate_document_bindings(admission, documents)
    return KCAAdmissionArtifacts(admission=admission, documents=documents)


__all__ = [
    "ADMISSION_FILENAME",
    "ADMISSION_RELATIVE_DIR",
    "KCAAdmissionArtifacts",
    "KCAModeSnapshotV1",
    "KCARunAdmissionV1",
    "build_run_admission",
    "load_admission_artifacts",
    "load_run_admission",
    "persist_run_admission",
]
