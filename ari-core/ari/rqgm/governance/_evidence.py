"""EvidenceClerk + EvidenceAuditChecker + SourceRefValidator — the evidence
step of the epoch audit (RQGM Task 05), run between threshold flagging and
motion drafting.

**Deterministic** bundle assembly: the EvidenceClerk builds EvidenceBundles
from record refs + content hashes, the SourceRefValidator resolves every ref
against the epoch's record map, and the EvidenceAuditChecker enforces
admissibility — the full exclusion ladder is docs/reference/rqgm_schemas.md,
"The motion-pipeline records":

* same-role-authored items are excluded with reason ``same_role_source``
  (observations-not-accusations, invariants 4-7);
* raw adversary attacks are excluded with ``unadjudicated_raw_attack`` until
  a Judge produced a ValidatedAttackRecord (global invariants 8-9);
* an unverifiable ref is excluded with ``unresolvable_ref`` and flips
  ``all_refs_resolved`` to ``False`` — the bundle never silently pads and
  never raises.

``content_hash`` is ``hash12(canonical_json(record))`` — the single RQGM
hash scheme (no second implementation).
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from ari.rqgm.events import payload_hash
from ari.rqgm.governance._records import (
    EVIDENCE_CLERK_ROLE,
    EvidenceBundle,
    build_evidence_bundle,
)

#: ``record_type -> bundle item kind`` — the closed admissible-kind map.
ADMISSIBLE_KIND_BY_TYPE: dict[str, str] = {
    "validated_attack": "validated_attack",
    "utility_record": "utility_record",
    "node_report": "execution_provenance",
    "harness_attestation": "fixed_verifier_result",
    "knowledge_skill_use": "instruction_provenance",
    "capability_binding": "execution_authority",
    "judgment_record": "judgment_record",
    "review_record": "review_record",
}


def _artifact_integrity_reason(
    record: dict, artifact_root: str | Path | None
) -> str | None:
    """Validate checkpoint-relative, digest-bound provenance attachments.

    ``source_refs`` remains a record-to-record graph.  K/C/A file evidence is
    carried by ``artifact_refs`` and may never escape the checkpoint root or
    resolve through a symlink.  Direct unit callers may omit *artifact_root*;
    the production orchestrator always supplies it.
    """

    from ari.protocols.integrity import canonical_digest, is_full_sha256

    refs = record.get("artifact_refs") or ()
    if not refs:
        return "missing_artifact_reference" if artifact_root is not None else None
    root = Path(artifact_root).resolve() if artifact_root is not None else None
    for raw in refs:
        if not isinstance(raw, dict):
            return "invalid_artifact_reference"
        relative = str(raw.get("path", "") or "")
        digest = str(raw.get("content_digest", "") or "")
        posix = PurePosixPath(relative)
        if (
            not relative
            or "\\" in relative
            or posix.is_absolute()
            or ".." in posix.parts
            or not is_full_sha256(digest)
        ):
            return "invalid_artifact_reference"
        if root is None:
            continue
        candidate = root.joinpath(*posix.parts)
        cursor = root
        for part in posix.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return "unsafe_artifact_reference"
        try:
            if not candidate.is_file() or not candidate.resolve().is_relative_to(root):
                return "unresolvable_artifact_reference"
            document = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return "unresolvable_artifact_reference"
        if canonical_digest(document) != digest:
            return "artifact_digest_mismatch"
    return None


def _type_specific_integrity_reason(
    record: dict, *, artifact_root: str | Path | None = None
) -> str | None:
    """Evidence Clerk admission checks for K/C/A typed provenance."""

    record_type = str(record.get("record_type", ""))
    if record_type in {
        "harness_attestation",
        "knowledge_skill_use",
        "capability_binding",
    }:
        artifact_reason = _artifact_integrity_reason(record, artifact_root)
        if artifact_reason is not None:
            return artifact_reason
    if record_type == "harness_attestation":
        return _harness_integrity_reason(record)
    if record_type == "knowledge_skill_use":
        return _knowledge_integrity_reason(record)
    if record_type == "capability_binding":
        return _binding_integrity_reason(record)
    return None


def _harness_integrity_reason(record: dict) -> str | None:
    from ari.protocols.integrity import is_full_sha256

    if record.get("component_id") != "fixed_verifier_v1":
        return "invalid_fixed_verifier_author"
    if record.get("prompt_hash") is not None:
        return "prompted_fixed_verifier"
    required = (
        "attestation_digest",
        "target_digest",
        "verification_contract_digest",
        "baseline_harness_lock_digest",
        "active_harness_lock_digest",
        "harness_manifest_digest",
        "driver_digest",
        "oracle_digest",
        "dataset_digest",
        "container_digest",
    )
    if any(not is_full_sha256(str(record.get(name, ""))) for name in required):
        return "invalid_attestation_digest"
    if record.get("target_digest") != record.get("current_node_target_digest"):
        return "stale_target_attestation"
    try:
        from ari.assurance.models import HarnessAttestationV1

        attestation = HarnessAttestationV1.model_validate(
            record.get("attestation") or {}
        )
    except Exception:
        return "malformed_harness_attestation"
    if (
        attestation.attestation_digest != record.get("attestation_digest")
        or attestation.node_id != str(record.get("node_id", ""))
        or attestation.target_digest != record.get("target_digest")
    ):
        return "attestation_envelope_mismatch"
    return None


def _knowledge_integrity_reason(record: dict) -> str | None:
    from ari.protocols.integrity import is_full_sha256

    required = (
        "knowledge_use_record_digest",
        "node_use_digest",
        "instruction_identity_digest",
        "knowledge_skill_lock_digest",
    )
    if any(not is_full_sha256(str(record.get(name, ""))) for name in required):
        return "invalid_knowledge_provenance"
    if record.get("node_use_digest") != record.get("prompt_node_use_digest"):
        return "knowledge_prompt_mismatch"
    if record.get("instruction_identity_digest") != record.get(
        "node_instruction_identity_digest"
    ):
        return "knowledge_instruction_identity_mismatch"
    try:
        from ari.knowledge.models import (
            KnowledgeSkillUseRecordV1,
            NodeKnowledgeSkillUseV1,
        )

        use_record = KnowledgeSkillUseRecordV1.model_validate(
            record.get("knowledge_use_record") or {}
        )
        node_use = NodeKnowledgeSkillUseV1.model_validate(record.get("node_use") or {})
    except Exception:
        return "malformed_knowledge_provenance"
    if (
        use_record.record_digest != record.get("knowledge_use_record_digest")
        or use_record.node_use_digest != node_use.use_digest
        or node_use.use_digest != record.get("node_use_digest")
        or node_use.epoch_lock_digest != record.get("knowledge_skill_lock_digest")
        or use_record.instruction_identity.instruction_digest
        != record.get("instruction_identity_digest")
    ):
        return "knowledge_provenance_envelope_mismatch"
    if any(
        str(status) in {"deprecated", "revoked"}
        for status in (record.get("knowledge_skill_status_at_use") or {}).values()
    ):
        return "inactive_knowledge_skill_use"
    return None


def _binding_integrity_reason(record: dict) -> str | None:
    from ari.protocols.integrity import canonical_digest, is_full_sha256

    required = (
        "capability_binding_lock_digest",
        "provider_lock_digest",
        "invocation_set_digest",
    )
    if any(not is_full_sha256(str(record.get(name, ""))) for name in required):
        return "invalid_capability_authority"
    invoked = tuple(sorted({
        str(item) for item in record.get("invoked_tool_refs") or ()
    }))
    if canonical_digest(invoked) != record.get("invocation_set_digest"):
        return "invocation_set_digest_mismatch"
    if record.get("unbound_tool_refs"):
        return "unbound_invocation"
    decisions = record.get("invocation_decisions") or ()
    if not isinstance(decisions, (list, tuple)):
        return "malformed_invocation_decisions"
    if any(
        not isinstance(item, dict)
        or str(item.get("tool_ref", "")) not in set(invoked)
        or str(item.get("reason_code", "")) != "bound"
        or not is_full_sha256(str(item.get("binding_digest", "")))
        for item in decisions
    ):
        return "invalid_binding_decision"
    return None

EXCLUDE_SAME_ROLE = "same_role_source"
EXCLUDE_RAW_ATTACK = "unadjudicated_raw_attack"
EXCLUDE_UNRESOLVABLE = "unresolvable_ref"
EXCLUDE_INADMISSIBLE_TYPE = "inadmissible_record_type"


def candidate_refs_for_target(records_by_id: dict, target_cid: str) -> list:
    """Deterministic candidate ref set for one prosecution target.

    Primary artifacts: validated attacks and utility records naming the
    target. Same-role ComparisonObservations about the target enter only as
    *leads*: their own ``source_refs`` (primary artifacts) are pulled in for
    independent verification while the observation ref itself is also listed
    — so its exclusion is recorded transparently in ``excluded_items``
    (reason ``same_role_source``) instead of being silently dropped here.
    """
    refs: set[str] = set()
    for rid, rec in records_by_id.items():
        rtype = str(rec.get("record_type", "") or "")
        target = str(
            rec.get("target_component_id", "")
            or rec.get("subject_component_id", "")
            or ""
        )
        if target != target_cid:
            continue
        if rtype in (
            "validated_attack",
            "utility_record",
            "raw_attack",
            "harness_attestation",
            "knowledge_skill_use",
            "capability_binding",
        ):
            refs.add(rid)
        elif rtype == "comparison_observation":
            refs.add(rid)  # recorded as excluded (lead, never evidence)
            for lead in rec.get("source_refs") or ():
                if isinstance(lead, str) and lead:
                    refs.add(lead)
    return sorted(refs)


def assemble_evidence_bundle(
    *,
    record_id: str,
    epoch_id: str,
    clerk_component_id: str,
    target_component_id: str,
    target_role: str,
    candidate_refs: list,
    records_by_id: dict,
    artifact_root: str | Path | None = None,
) -> EvidenceBundle:
    """Build one verified EvidenceBundle for *target_component_id*."""
    items: list = []
    excluded: list = []
    all_resolved = True
    for ref in sorted(set(str(r) for r in candidate_refs)):
        rec = records_by_id.get(ref)
        if rec is None:
            excluded.append({"ref": ref, "reason": EXCLUDE_UNRESOLVABLE})
            all_resolved = False
            continue
        rtype = str(rec.get("record_type", "") or "")
        author_role = str(rec.get("role", "") or "")
        if rtype == "raw_attack":
            excluded.append({"ref": ref, "reason": EXCLUDE_RAW_ATTACK})
            continue
        if author_role and author_role == target_role:
            # Covers same-role ComparisonObservations too (their author role
            # equals the subject's role by definition).
            excluded.append({"ref": ref, "reason": EXCLUDE_SAME_ROLE})
            continue
        kind = ADMISSIBLE_KIND_BY_TYPE.get(rtype)
        if kind is None:
            excluded.append({"ref": ref, "reason": EXCLUDE_INADMISSIBLE_TYPE})
            continue
        integrity_reason = _type_specific_integrity_reason(
            rec, artifact_root=artifact_root
        )
        if integrity_reason is not None:
            excluded.append({"ref": ref, "reason": integrity_reason})
            continue
        items.append(
            {"kind": kind, "ref": ref, "content_hash": payload_hash(rec)}
        )
    return build_evidence_bundle(
        author_role=EVIDENCE_CLERK_ROLE,
        record_id=record_id,
        epoch_id=epoch_id,
        clerk_component_id=clerk_component_id,
        target_component_id=target_component_id,
        target_role=target_role,
        items=tuple(items),
        excluded_items=tuple(excluded),
        all_refs_resolved=all_resolved,
    )
