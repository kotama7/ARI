"""Pure CK-KNW integrity and authority checks for Knowledge Skill use."""

from __future__ import annotations

import re

from ari.protocols.integrity import bytes_digest, canonical_digest
from ari.rqgm.kernel_kca_common import (
    SIDE_EFFECT_RANK,
    actor_role,
    as_dict,
    full_digest_matches,
    violation,
)
from ari.rqgm.kernel_types import make_report


CHECK = "validate_knowledge_integrity"


def _append_lock_findings(
    violations: list,
    *,
    severity: dict[str, str],
    use: dict,
    lock: dict,
    subject: str,
    composition_digest: str | None,
    expected_lock_digest: str | None,
    previous_node_use,
) -> None:
    def add(code, rule, detail) -> None:
        violations.append(
            violation(severity, code, CHECK, subject, rule, detail)
        )
    if not full_digest_matches(lock, "lock_digest"):
        add(
            "CK-KNW-011",
            "EpochKnowledgeSkillLockV1.lock_digest",
            "Knowledge lock canonical digest is invalid",
        )
    if expected_lock_digest and str(lock.get("lock_digest", "")) != str(
        expected_lock_digest
    ):
        add(
            "CK-KNW-011",
            "epoch_frozen_knowledge_lock",
            "Knowledge use refers to a stale epoch lock",
        )
    if str(use.get("epoch_lock_digest", "")) != str(lock.get("lock_digest", "")):
        add(
            "CK-KNW-006",
            "NodeKnowledgeSkillUseV1.epoch_lock_digest",
            "node Knowledge use differs from the frozen epoch lock",
        )
    if not full_digest_matches(use, "use_digest"):
        add(
            "CK-KNW-005",
            "NodeKnowledgeSkillUseV1.use_digest",
            "Knowledge use canonical digest is invalid",
        )
    if composition_digest is not None and str(
        use.get("knowledge_composition_digest", "")
    ) != str(composition_digest):
        add(
            "CK-KNW-005",
            "instruction_composition",
            "node use and actual prompt composition digests differ",
        )
    if previous_node_use is not None and as_dict(previous_node_use) != use:
        add(
            "CK-KNW-006",
            "mid_node_immutability",
            "Knowledge use changed after node execution began",
        )


def _catalog_entries(catalog: dict) -> dict[tuple[str, ...], dict]:
    entries = {}
    for raw in catalog.get("entries") or ():
        entry = as_dict(raw)
        manifest = as_dict(entry.get("manifest") or {})
        source = as_dict(manifest.get("source") or {})
        key = (
            str(manifest.get("id", "")),
            str(manifest.get("version", "")),
            str(source.get("body_sha256", "")),
            str(source.get("manifest_sha256", "")),
        )
        entries[key] = entry
    return entries


def _previous_entries(snapshot) -> dict[tuple[str, str], dict]:
    previous = as_dict(snapshot)
    entries = {}
    for raw in previous.get("entries") or ():
        entry = as_dict(raw)
        manifest = as_dict(entry.get("manifest") or {})
        entries[(str(manifest.get("id", "")), str(manifest.get("version", "")))] = entry
    return entries


def _append_catalog_mutation_findings(
    violations: list,
    *,
    severity: dict[str, str],
    entries: dict,
    previous_catalog_snapshot,
) -> None:
    if previous_catalog_snapshot is None:
        return
    previous = _previous_entries(previous_catalog_snapshot)
    for entry in entries.values():
        manifest = as_dict(entry.get("manifest") or {})
        key = (str(manifest.get("id", "")), str(manifest.get("version", "")))
        old = previous.get(key)
        if old is None:
            continue
        source = as_dict(manifest.get("source") or {})
        old_source = as_dict(as_dict(old.get("manifest") or {}).get("source") or {})
        identity = (str(source.get("body_sha256", "")), str(source.get("manifest_sha256", "")))
        old_identity = (
            str(old_source.get("body_sha256", "")),
            str(old_source.get("manifest_sha256", "")),
        )
        if identity != old_identity:
            violations.append(
                violation(
                    severity,
                    "CK-KNW-004",
                    CHECK,
                    key[0],
                    "append_only_knowledge_identity",
                    "an existing Knowledge Skill id/version was mutated in place",
                )
            )


def _skill_key(ref: dict) -> tuple[str, str, str, str]:
    return (
        str(ref.get("id", "")),
        str(ref.get("version", "")),
        str(ref.get("body_sha256", "")),
        str(ref.get("manifest_sha256", "")),
    )


def _own_requirements(lock_requirements: list[dict], source: dict) -> list[dict]:
    source_ref = "knowledge:" + str(source.get("body_sha256", ""))
    return [
        item
        for item in lock_requirements
        if source_ref in {
            str(value) for value in item.get("source_requirement_refs") or ()
        }
    ]


def _append_skill_integrity_findings(
    violations: list,
    *,
    severity: dict[str, str],
    key: tuple[str, str, str, str],
    entry: dict,
    body_by_sha256,
) -> tuple[dict, dict]:
    manifest = as_dict(entry.get("manifest") or {})
    source = as_dict(manifest.get("source") or {})
    payload = dict(manifest)
    source_payload = dict(source)
    recorded_manifest = str(source_payload.pop("manifest_sha256", ""))
    payload["source"] = source_payload
    if canonical_digest(payload) != recorded_manifest:
        violations.append(
            violation(
                severity,
                "CK-KNW-003",
                CHECK,
                key[0],
                "KnowledgeSkillManifestV1.source.manifest_sha256",
                "Knowledge manifest digest mismatch",
            )
        )
    if body_by_sha256 is not None:
        body = body_by_sha256.get(key[2])
        if body is None or bytes_digest(str(body).encode("utf-8")) != key[2]:
            violations.append(
                violation(
                    severity,
                    "CK-KNW-002",
                    CHECK,
                    key[0],
                    "KnowledgeSkillManifestV1.source.body_sha256",
                    "Knowledge body is missing or digest-mismatched",
                )
            )
    if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", str(source.get("commit", ""))) is None:
        violations.append(
            violation(
                severity,
                "CK-KNW-010",
                CHECK,
                key[0],
                "pinned_external_source",
                "Knowledge source is not full-commit pinned",
            )
        )
    return manifest, source


def _append_skill_authority_findings(
    violations: list,
    *,
    severity: dict[str, str],
    skill_id: str,
    manifest: dict,
    requirements: list[dict],
) -> None:
    required = {str(item.get("capability_ref", "")) for item in requirements}
    forbidden = {str(value) for value in manifest.get("forbidden_capabilities") or ()}
    if required & forbidden:
        violations.append(
            violation(
                severity,
                "CK-KNW-008",
                CHECK,
                skill_id,
                "forbidden_capabilities",
                "Knowledge lock contains a forbidden capability",
            )
        )
    allowed = as_dict(manifest.get("authority_ceiling") or {}).get(
        "side_effects", ()
    )
    maximum = max((SIDE_EFFECT_RANK.get(str(item), -1) for item in allowed), default=-1)
    exceeded = any(
        SIDE_EFFECT_RANK.get(str(item.get("side_effect_ceiling", "")), 99)
        > maximum
        for item in requirements
    )
    if exceeded:
        violations.append(
            violation(
                severity,
                "CK-KNW-007",
                CHECK,
                skill_id,
                "knowledge_authority_ceiling",
                "a locked capability requirement exceeds the Skill authority ceiling",
            )
        )


def _append_skill_findings(
    violations: list,
    *,
    severity: dict[str, str],
    raw_ref,
    entries: dict,
    lock_requirements: list[dict],
    body_by_sha256,
) -> None:
    key = _skill_key(as_dict(raw_ref))
    entry = entries.get(key)
    status = str(entry.get("status", "")) if entry is not None else ""
    if entry is None or status != "verified":
        violations.append(
            violation(
                severity,
                "CK-KNW-001",
                CHECK,
                key[0],
                "verified_catalog_entry",
                "authoritative Knowledge use is not an exact verified entry",
            )
        )
        if status == "revoked":
            violations.append(
                violation(
                    severity,
                    "CK-KNW-012",
                    CHECK,
                    key[0],
                    "new_epoch_revocation_gate",
                    "a revoked Knowledge Skill was activated in this epoch",
                )
            )
        return
    manifest, source = _append_skill_integrity_findings(
        violations,
        severity=severity,
        key=key,
        entry=entry,
        body_by_sha256=body_by_sha256,
    )
    _append_skill_authority_findings(
        violations,
        severity=severity,
        skill_id=key[0],
        manifest=manifest,
        requirements=_own_requirements(lock_requirements, source),
    )


def _append_boundary_findings(
    violations: list,
    *,
    severity: dict[str, str],
    subject: str,
    actor,
    attempted_catalog_write: bool,
    attachment_launch: bool,
    effective_directives,
) -> None:
    if attempted_catalog_write:
        role = actor_role(actor)
        violations.append(
            violation(
                severity,
                "CK-KNW-009",
                CHECK,
                role or subject,
                "catalog_admin_boundary",
                "non-admin actor attempted a Knowledge catalog write",
            )
        )
    if attachment_launch:
        violations.append(
            violation(
                severity,
                "CK-KNW-015",
                CHECK,
                subject,
                "knowledge_non_executable",
                "Knowledge attachment was used as a direct launch path",
            )
        )
    directives = {str(item) for item in effective_directives or ()}
    if directives & {"registry_write", "authority_escalation", "secret_access"}:
        violations.append(
            violation(
                severity,
                "CK-KNW-013",
                CHECK,
                subject,
                "instruction_only_boundary",
                "Knowledge text changed executable authority",
            )
        )
    if directives & {"harness_bypass", "tolerance_change", "oracle_change"}:
        violations.append(
            violation(
                severity,
                "CK-KNW-014",
                CHECK,
                subject,
                "verification_authority_boundary",
                "Knowledge text changed fixed verification behavior",
            )
        )


def validate_knowledge_integrity(
    *,
    severity: dict[str, str],
    node_use,
    epoch_lock,
    catalog_snapshot,
    body_by_sha256=None,
    composition_digest: str | None = None,
    expected_epoch_lock_digest: str | None = None,
    previous_catalog_snapshot=None,
    previous_node_use=None,
    actor=None,
    attempted_catalog_write: bool = False,
    attachment_launch: bool = False,
    effective_directives=(),
):
    use = as_dict(node_use)
    lock = as_dict(epoch_lock)
    catalog = as_dict(catalog_snapshot)
    subject = str(use.get("node_id", "") or "<unknown-node>")
    violations: list = []
    _append_lock_findings(
        violations,
        severity=severity,
        use=use,
        lock=lock,
        subject=subject,
        composition_digest=composition_digest,
        expected_lock_digest=expected_epoch_lock_digest,
        previous_node_use=previous_node_use,
    )
    entries = _catalog_entries(catalog)
    _append_catalog_mutation_findings(
        violations,
        severity=severity,
        entries=entries,
        previous_catalog_snapshot=previous_catalog_snapshot,
    )
    lock_requirements = [
        as_dict(item) for item in lock.get("capability_requirements") or ()
    ]
    for raw_ref in use.get("ordered_skills") or ():
        _append_skill_findings(
            violations,
            severity=severity,
            raw_ref=raw_ref,
            entries=entries,
            lock_requirements=lock_requirements,
            body_by_sha256=body_by_sha256,
        )
    _append_boundary_findings(
        violations,
        severity=severity,
        subject=subject,
        actor=actor,
        attempted_catalog_write=attempted_catalog_write,
        attachment_launch=attachment_launch,
        effective_directives=effective_directives,
    )
    return make_report("knowledge_integrity", violations)


__all__ = ["validate_knowledge_integrity"]
