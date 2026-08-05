"""Immutable body storage and append-only Knowledge catalog lifecycle."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from ari.knowledge.external_models import (
    KnowledgeImportMaterialV1,
    KnowledgeSkillImportProfileV1,
)
from ari.knowledge.models import (
    KnowledgeCatalogStatus,
    KnowledgeSkillCatalogSnapshotV1,
    KnowledgeSkillEntryV1,
    KnowledgeSkillRefV1,
    KnowledgeRegistrationGateV1,
    KnowledgeSkillManifestV1,
    KnowledgeSkillRegistrationReportV1,
    KnowledgeSkillStatusTransitionV1,
)
from ari.knowledge.importer import validate_body_sections
from ari.protocols.integrity import bytes_digest, canonical_digest


_ALLOWED_TRANSITIONS = {
    "candidate": frozenset({"verified", "deprecated", "revoked"}),
    "verified": frozenset({"deprecated", "revoked"}),
    "deprecated": frozenset({"revoked"}),
    "revoked": frozenset(),
}


@dataclass
class KnowledgeSkillBodyStore:
    """Content-addressed body store with no overwrite or execution API."""

    _bodies: dict[str, bytes] = field(default_factory=dict)

    def put(self, body: str | bytes) -> str:
        payload = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        digest = bytes_digest(payload)
        previous = self._bodies.setdefault(digest, payload)
        if previous != payload:
            raise ValueError("content-address collision")
        return digest

    def get_text(self, digest: str) -> str:
        return self._bodies[digest].decode("utf-8")


@dataclass
class GovernedKnowledgeSkillRegistry:
    entries: dict[tuple[str, str, str], KnowledgeSkillEntryV1] = field(
        default_factory=dict
    )
    transitions: list[KnowledgeSkillStatusTransitionV1] = field(default_factory=list)

    def register(self, entry: KnowledgeSkillEntryV1) -> None:
        key = (
            entry.manifest.id,
            entry.manifest.version,
            entry.manifest.source.body_sha256,
        )
        previous = self.entries.get(key)
        if previous is not None and previous != entry:
            raise ValueError("Knowledge catalog entries are immutable")
        self.entries[key] = entry

    def transition(
        self,
        *,
        skill_ref: KnowledgeSkillRefV1,
        to_status: KnowledgeCatalogStatus,
        actor_id: str,
        evidence_digest: str,
    ) -> KnowledgeSkillStatusTransitionV1:
        key = (skill_ref.id, skill_ref.version, skill_ref.body_sha256)
        entry = self.entries.get(key)
        if (
            entry is None
            or entry.manifest.source.manifest_sha256 != skill_ref.manifest_sha256
        ):
            raise ValueError("unknown exact Knowledge Skill")
        current = self.status_at(skill_ref)
        if to_status not in _ALLOWED_TRANSITIONS[current]:
            raise ValueError(
                f"illegal Knowledge status transition {current}->{to_status}"
            )
        parent = next(
            (
                item.transition_digest
                for item in reversed(self.transitions)
                if item.skill_ref == skill_ref
            ),
            None,
        )
        transition = KnowledgeSkillStatusTransitionV1.create(
            skill_ref=skill_ref,
            from_status=current,
            to_status=to_status,
            actor_id=actor_id,
            evidence_digest=evidence_digest,
            parent_transition_digest=parent,
        )
        self.transitions.append(transition)
        return transition

    def status_at(self, skill_ref: KnowledgeSkillRefV1) -> KnowledgeCatalogStatus:
        status = self.entries[
            (skill_ref.id, skill_ref.version, skill_ref.body_sha256)
        ].status
        for item in self.transitions:
            if item.skill_ref == skill_ref:
                status = item.to_status
        return status


def build_catalog_snapshot(
    *,
    catalog_source_revision: str,
    importer_version: str,
    entries: tuple[KnowledgeSkillEntryV1, ...],
) -> KnowledgeSkillCatalogSnapshotV1:
    return KnowledgeSkillCatalogSnapshotV1.create(
        catalog_source_revision=catalog_source_revision,
        importer_version=importer_version,
        entries=tuple(
            sorted(
                entries,
                key=lambda item: (
                    item.manifest.id,
                    item.manifest.version,
                    item.manifest.source.body_sha256,
                ),
            )
        ),
    )


def build_registry_snapshot(
    *,
    registry: GovernedKnowledgeSkillRegistry,
    catalog_source_revision: str,
    importer_version: str,
) -> KnowledgeSkillCatalogSnapshotV1:
    """Freeze the registry's append-only lifecycle view without rewriting bodies.

    A status transition creates a new digest-bound catalog entry in the new
    snapshot.  The previous entry and every transition remain available for
    replay; no manifest/body bytes are changed in place.
    """

    entries = []
    for entry in registry.entries.values():
        status = registry.status_at(entry.manifest.exact_ref())
        entries.append(
            KnowledgeSkillEntryV1.create(
                manifest=entry.manifest,
                body_store_key=entry.body_store_key,
                registration_report_digest=entry.registration_report_digest,
                importer_version=entry.importer_version,
                status=status,
            )
        )
    return build_catalog_snapshot(
        catalog_source_revision=catalog_source_revision,
        importer_version=importer_version,
        entries=tuple(entries),
    )


@dataclass(frozen=True)
class LoadedKnowledgeCatalog:
    snapshot: KnowledgeSkillCatalogSnapshotV1
    body_store: KnowledgeSkillBodyStore
    registration_reports: dict[str, KnowledgeSkillRegistrationReportV1]


def _catalog_relative(root: Path, value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise ValueError("Knowledge catalog path must be safe and relative")
    path = root.joinpath(*pure.parts)
    if path.is_symlink():
        raise ValueError("Knowledge catalog symbolic links are refused")
    resolved = path.resolve(strict=True)
    if root.resolve() not in resolved.parents or not resolved.is_file():
        raise ValueError("Knowledge catalog path escapes its root")
    return resolved


def load_knowledge_catalog(path: str | Path) -> LoadedKnowledgeCatalog:
    """Load checked-in catalog bytes without runtime network or branch lookup."""

    catalog_path = Path(path)
    root = catalog_path.parent
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    body_store = KnowledgeSkillBodyStore()
    entries: list[KnowledgeSkillEntryV1] = []
    reports: dict[str, KnowledgeSkillRegistrationReportV1] = {}
    for item in raw.get("entries", []):
        has_import_material = "import_material" in item
        has_legacy_pair = "manifest" in item or "body" in item
        if has_import_material == has_legacy_pair:
            raise ValueError(
                "Knowledge catalog entry requires exactly one of import_material "
                "or the manifest/body pair"
            )
        external_material: KnowledgeImportMaterialV1 | None = None
        if has_import_material:
            if set(item) != {"import_material", "import_profile"}:
                raise ValueError(
                    "external Knowledge catalog entry requires exactly "
                    "import_material and import_profile"
                )
            material_path = _catalog_relative(root, str(item["import_material"]))
            profile_path = _catalog_relative(root, str(item["import_profile"]))
            try:
                material_document = json.loads(
                    material_path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Knowledge import material is invalid JSON: {material_path.name}"
                ) from exc
            external_material = KnowledgeImportMaterialV1.model_validate(
                material_document
            )
            if external_material.source_provenance is None:
                raise ValueError(
                    "checked-in import material requires external source provenance"
                )
            profile_document = (
                yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
            )
            profile = KnowledgeSkillImportProfileV1.model_validate(profile_document)
            provenance = external_material.source_provenance
            if canonical_digest(profile) != provenance.import_profile_digest:
                raise ValueError("Knowledge import profile digest mismatch")
            if (
                profile.id != external_material.manifest.id
                or profile.version != external_material.manifest.version
                or profile.body_normalization != provenance.body_normalization
            ):
                raise ValueError(
                    "Knowledge import profile differs from imported manifest"
                )
            manifest = external_material.manifest
            document = manifest.model_dump(mode="json")
            body = external_material.body
            source_label = material_path.name
            entry_importer_version = external_material.source_provenance.adapter_version
            non_authoritative_hints = external_material.non_authoritative_tool_hints
            attachment_paths = tuple(
                attachment.path for attachment in external_material.attachments
            )
        else:
            if set(item) != {"manifest", "body"}:
                raise ValueError(
                    "built-in Knowledge catalog entry requires exactly manifest and body"
                )
            if "manifest" not in item or "body" not in item:
                raise ValueError(
                    "Knowledge catalog legacy entry requires both manifest and body"
                )
            manifest_path = _catalog_relative(root, str(item["manifest"]))
            body_path = _catalog_relative(root, str(item["body"]))
            document = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            manifest = KnowledgeSkillManifestV1.model_validate(document)
            body = body_path.read_text(encoding="utf-8")
            source_label = manifest_path.name
            entry_importer_version = str(raw.get("importer_version", "unknown"))
            non_authoritative_hints = ()
            attachment_paths = ()
        manifest_payload = dict(document)
        source = dict(manifest_payload["source"])
        source.pop("manifest_sha256", None)
        manifest_payload["source"] = source
        if canonical_digest(manifest_payload) != manifest.source.manifest_sha256:
            raise ValueError(f"Knowledge manifest digest mismatch: {source_label}")
        validate_body_sections(body)
        body_digest = body_store.put(body)
        if body_digest != manifest.source.body_sha256:
            raise ValueError(f"Knowledge body digest mismatch: {source_label}")
        # Repository commit pins in a working tree cannot attest the newly
        # added body until that commit actually contains it.  Candidates also
        # cannot claim empirical clean-task/portability evidence before
        # registration CI.  Promotion therefore remains an explicit later
        # admin transition, never an optimistic loader side effect.
        gate_names = (
            "manifest_schema",
            "full_sha256_integrity",
            "source_commit_pin",
            "license_completeness",
            "no_executable_entrypoint",
            "no_script_autolaunch",
            "capability_ontology",
            "forbidden_authority",
            "authority_ceiling",
            "property_vocabulary",
            "reference_isolation",
            "prompt_composition_schema",
            "body_sections_and_size",
            "hostile_instruction_boundary",
            "clean_task",
            "provider_portability",
        )
        pending_gates = {"clean_task", "provider_portability"}
        if external_material is None:
            pending_gates.add("source_commit_pin")
        gates = tuple(
            KnowledgeRegistrationGateV1(
                gate_id=name,
                passed=name not in pending_gates,
                evidence_digest=canonical_digest(
                    {"manifest": manifest.source.manifest_sha256, "gate": name}
                ),
                detail=(
                    "pending committed-source or empirical registration evidence"
                    if name in pending_gates
                    else "checked-in static validation"
                ),
            )
            for name in gate_names
        )
        report = KnowledgeSkillRegistrationReportV1.create(
            skill_ref=manifest.exact_ref(),
            gates=gates,
            non_authoritative_hints=non_authoritative_hints,
            attachments=attachment_paths,
            decision="candidate",
        )
        reports[report.report_digest] = report
        entries.append(
            KnowledgeSkillEntryV1.create(
                manifest=manifest,
                body_store_key=body_digest,
                registration_report_digest=report.report_digest,
                importer_version=entry_importer_version,
                status=manifest.status,
            )
        )
    snapshot = build_catalog_snapshot(
        catalog_source_revision=str(raw.get("catalog_source_revision", "unknown")),
        importer_version=str(raw.get("importer_version", "unknown")),
        entries=tuple(entries),
    )
    return LoadedKnowledgeCatalog(snapshot, body_store, reports)


__all__ = [
    "GovernedKnowledgeSkillRegistry",
    "KnowledgeSkillBodyStore",
    "LoadedKnowledgeCatalog",
    "build_catalog_snapshot",
    "load_knowledge_catalog",
]
