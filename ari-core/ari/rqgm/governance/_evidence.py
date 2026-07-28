"""EvidenceClerk + EvidenceAuditChecker + SourceRefValidator (Task 05 §5.3 step 3).

**Deterministic** bundle assembly: the EvidenceClerk builds EvidenceBundles
from record refs + content hashes, the SourceRefValidator resolves every ref
against the epoch's record map, and the EvidenceAuditChecker enforces
admissibility (plan 05 §5.4 / §6.3):

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
    "node_report": "fixed_verifier_result",
    "judgment_record": "judgment_record",
    "review_record": "review_record",
}

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
    (§5.4 rule 3, §6.3 example).
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
        if rtype in ("validated_attack", "utility_record", "raw_attack"):
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
            # equals the subject's role by definition — §6.2 invariant).
            excluded.append({"ref": ref, "reason": EXCLUDE_SAME_ROLE})
            continue
        kind = ADMISSIBLE_KIND_BY_TYPE.get(rtype)
        if kind is None:
            excluded.append({"ref": ref, "reason": EXCLUDE_INADMISSIBLE_TYPE})
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
