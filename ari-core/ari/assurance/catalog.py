"""Read-only Harness catalog snapshots and search."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import yaml

from ari.assurance.models import HarnessCatalogSnapshotV1, HarnessManifestV1
from ari.assurance.registration_models import (
    HarnessPromotionApprovalV1,
    HarnessRegistrationEvidenceV1,
    HarnessRegistrationReportV1,
)
from ari.assurance.contract import load_property_vocabulary
from ari.protocols.integrity import bytes_digest


def build_harness_catalog_snapshot(
    *,
    catalog_source_revision: str,
    property_vocabulary_digest: str,
    driver_protocol_version: str,
    manifests: tuple[HarnessManifestV1, ...],
    registration_report_digests: dict[str, str],
    registration_evidence_digests: dict[str, str] | None = None,
    promotion_approval_digests: dict[str, str] | None = None,
) -> HarnessCatalogSnapshotV1:
    return HarnessCatalogSnapshotV1.create(
        catalog_source_revision=catalog_source_revision,
        property_vocabulary_digest=property_vocabulary_digest,
        driver_protocol_version=driver_protocol_version,
        manifests=tuple(
            sorted(manifests, key=lambda item: (item.id, item.version, item.manifest_digest))
        ),
        registration_report_digests=dict(sorted(registration_report_digests.items())),
        registration_evidence_digests=dict(
            sorted((registration_evidence_digests or {}).items())
        ),
        promotion_approval_digests=dict(
            sorted((promotion_approval_digests or {}).items())
        ),
    )


def search_harnesses(
    snapshot: HarnessCatalogSnapshotV1, query: str = ""
) -> tuple[HarnessManifestV1, ...]:
    needle = query.strip().lower()
    return tuple(
        item
        for item in snapshot.manifests
        if not needle
        or needle in item.id.lower()
        or needle in item.description.lower()
        or any(needle in tag.lower() for tag in item.tags)
    )


def describe_harness(
    snapshot: HarnessCatalogSnapshotV1, harness_id: str
) -> HarnessManifestV1 | None:
    return next((item for item in snapshot.manifests if item.id == harness_id), None)


def _safe_manifest(root: Path, value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise ValueError("Harness catalog path must be safe and relative")
    path = root.joinpath(*pure.parts)
    if path.is_symlink():
        raise ValueError("Harness catalog symbolic links are refused")
    resolved = path.resolve(strict=True)
    if root.resolve() not in resolved.parents or not resolved.is_file():
        raise ValueError("Harness catalog path escapes its root")
    return resolved


def load_harness_catalog(path: str | Path) -> HarnessCatalogSnapshotV1:
    """Load digest-bound checked-in manifests; no runner or network is used."""

    source = Path(path)
    root = source.parent
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    _, vocabulary_digest = load_property_vocabulary(
        root / "property_vocabulary.yaml"
    )
    manifests: list[HarnessManifestV1] = []
    report_digests: dict[str, str] = {}
    evidence_digests: dict[str, str] = {}
    approval_digests: dict[str, str] = {}
    for entry in raw.get("entries", ()):
        manifest_path = _safe_manifest(root, str(entry["manifest"]))
        document = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        advertised = document.pop("manifest_digest", None)
        manifest = HarnessManifestV1.create(**document)
        if advertised is not None and advertised != manifest.manifest_digest:
            raise ValueError(f"Harness manifest digest mismatch: {manifest.id}")
        report_path = _safe_manifest(root, str(entry["registration_report"]))
        report_document = yaml.safe_load(report_path.read_text(encoding="utf-8")) or {}
        report = HarnessRegistrationReportV1.model_validate(report_document)
        report_digest = str(entry.get("registration_report_digest", ""))
        if (
            report.report_digest != report_digest
            or report.harness_id != manifest.id
            or report.manifest_digest != manifest.manifest_digest
        ):
            raise ValueError(f"Harness registration report differs: {manifest.id}")
        evidence_path = _safe_manifest(root, str(entry["registration_evidence"]))
        evidence_document = yaml.safe_load(
            evidence_path.read_text(encoding="utf-8")
        ) or {}
        evidence = HarnessRegistrationEvidenceV1.model_validate(evidence_document)
        evidence_digest = str(entry.get("registration_evidence_digest", ""))
        if (
            evidence.evidence_digest != evidence_digest
            or evidence.harness_id != manifest.id
            or evidence.harness_version != manifest.version
            or evidence.manifest_digest != manifest.manifest_digest
        ):
            raise ValueError(f"Harness registration evidence differs: {manifest.id}")
        for relative, expected_digest in evidence.evidence_artifact_digests.items():
            artifact_path = _safe_manifest(root, relative)
            if artifact_path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError(
                    f"Harness registration evidence is too large: {manifest.id}"
                )
            if bytes_digest(artifact_path.read_bytes()) != expected_digest:
                raise ValueError(
                    f"Harness registration evidence artifact differs: {manifest.id}"
                )
        if manifest.status == "verified":
            if report.decision != "eligible-for-verified":
                raise ValueError(
                    f"verified Harness lacks passing registration gates: {manifest.id}"
                )
            approval_path = _safe_manifest(root, str(entry["promotion_approval"]))
            approval_document = (
                yaml.safe_load(approval_path.read_text(encoding="utf-8")) or {}
            )
            approval = HarnessPromotionApprovalV1.model_validate(approval_document)
            advertised_approval = str(entry.get("promotion_approval_digest", ""))
            if (
                approval.approval_digest != advertised_approval
                or approval.harness_id != manifest.id
                or approval.harness_version != manifest.version
                or approval.harness_manifest_digest != manifest.manifest_digest
                or approval.registration_report_digest != report.report_digest
                or approval.evidence_bundle_digest != evidence.evidence_digest
            ):
                raise ValueError(f"Harness promotion approval differs: {manifest.id}")
            approval_digests[manifest.id] = approval.approval_digest
        manifests.append(manifest)
        report_digests[manifest.id] = report_digest
        evidence_digests[manifest.id] = evidence_digest
    return build_harness_catalog_snapshot(
        catalog_source_revision=str(raw.get("catalog_source_revision", "unknown")),
        property_vocabulary_digest=vocabulary_digest,
        driver_protocol_version=str(raw.get("driver_protocol_version", "unknown")),
        manifests=tuple(manifests),
        registration_report_digests=report_digests,
        registration_evidence_digests=evidence_digests,
        promotion_approval_digests=approval_digests,
    )


__all__ = [
    "build_harness_catalog_snapshot",
    "describe_harness",
    "load_harness_catalog",
    "search_harnesses",
]
