"""ReliabilityMonitor + MetaReliabilityMonitor — step 2 of the Task 05 audit
(the aggregation that runs over step 1's epoch record slice, before the
motion pipeline reads its numbers).

**Deterministic** aggregation per ``(component_id, prompt_hash)`` over the
epoch's audit-log record slice: counts, validated-attack involvement,
agreement rates, calibration stats. No LLM, no randomness, no wall clock in
any computed value (P2); iteration/output order is sorted by component id.
Missing stats yield ``reliability_score: None`` flagged ``insufficient_data``
— never fabricated.

The MetaReliabilityMonitor is the SAME aggregation restricted to the
governance-actor roles (auditor / evidence_clerk / defender /
governance_judge): governance components are measured by the same yardstick
as the components they govern.
"""

from __future__ import annotations

from ari.rqgm.governance._records import GOVERNANCE_ACTOR_ROLES

#: Score parts are averaged; six-decimal rounding keeps reports byte-stable
#: across platforms (P2 double-invocation equality).
_ROUND = 6


def _mean(values: list) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), _ROUND)


def build_reliability_entries(records: list, component_registry=None) -> list:
    """One entry per observed/registered component, sorted by component id.

    *records* is the epoch's record-dict slice (step 1 output). Aggregates:

    * ``observation_count`` — records authored by the component this epoch;
    * ``validated_attack_involvement`` — ValidatedAttackRecords whose
      ``target_component_id`` is the component;
    * ``agreement_rate`` — mean of the ``agreement`` field over the
      component's own records that carry one (``None`` when absent);
    * ``calibration_error`` — mean ``|confidence - outcome_score|`` over the
      component's records carrying both fields (``None`` when absent);
    * ``reliability_score`` — mean of the available parts
      ``[1 - attack_ratio, agreement_rate, 1 - calibration_error]``;
      ``None`` + ``insufficient_data`` when the component authored nothing.
    """
    authored: dict[str, list] = {}
    attacks_by_target: dict[str, list] = {}
    obs_by_subject: dict[str, list] = {}
    roles: dict[str, str] = {}
    hashes: dict[str, str | None] = {}

    for rec in records:
        cid = str(rec.get("component_id", "") or "")
        rtype = str(rec.get("record_type", "") or "")
        if cid:
            authored.setdefault(cid, []).append(rec)
            roles.setdefault(cid, str(rec.get("role", "") or ""))
            hashes.setdefault(cid, rec.get("prompt_hash"))
        if rtype == "validated_attack":
            target = str(rec.get("target_component_id", "") or "")
            if target:
                attacks_by_target.setdefault(target, []).append(
                    str(rec.get("record_id", ""))
                )
        if rtype == "comparison_observation":
            subject = str(rec.get("subject_component_id", "") or "")
            if subject:
                obs_by_subject.setdefault(subject, []).append(
                    str(rec.get("record_id", ""))
                )

    cids = set(authored) | set(attacks_by_target) | set(obs_by_subject)
    active = getattr(component_registry, "active_set", None)
    if callable(active):
        try:
            cids |= set(active().values())
        except Exception:
            pass

    entries = []
    for cid in sorted(cids):
        own = authored.get(cid, [])
        count = len(own)
        attacks = attacks_by_target.get(cid, [])
        role = roles.get(cid, "")
        tier = ""
        prompt_hash = hashes.get(cid)
        getter = getattr(component_registry, "get", None)
        if callable(getter):
            try:
                entry = getter(cid)
            except Exception:
                entry = None
            if entry is not None:
                role = str(getattr(entry, "role", "") or role)
                tier = str(getattr(entry, "tier", "") or "")
        agreements = [
            float(r["agreement"]) for r in own
            if isinstance(r.get("agreement"), (int, float))
            and not isinstance(r.get("agreement"), bool)
        ] + [1.0 if r["agreement"] else 0.0
             for r in own if isinstance(r.get("agreement"), bool)]
        calibrations = [
            abs(float(r["confidence"]) - float(r["outcome_score"]))
            for r in own
            if isinstance(r.get("confidence"), (int, float))
            and isinstance(r.get("outcome_score"), (int, float))
        ]
        agreement_rate = _mean(agreements)
        calibration_error = _mean(calibrations)
        insufficient = count == 0
        if insufficient:
            score = None
        else:
            parts = [max(0.0, 1.0 - len(attacks) / count)]
            if agreement_rate is not None:
                parts.append(agreement_rate)
            if calibration_error is not None:
                parts.append(max(0.0, 1.0 - calibration_error))
            score = round(sum(parts) / len(parts), _ROUND)
        entries.append(
            {
                "component_id": cid,
                "role": role,
                "tier": tier,
                "prompt_hash": prompt_hash,
                "observation_count": count,
                "validated_attack_involvement": len(attacks),
                "agreement_rate": agreement_rate,
                "calibration_error": calibration_error,
                "reliability_score": score,
                "insufficient_data": insufficient,
                "evidence_refs": sorted(
                    set(attacks) | set(obs_by_subject.get(cid, []))
                ),
            }
        )
    return entries


def meta_reliability_entries(entries: list) -> list:
    """MetaReliabilityMonitor: the same aggregation over governance roles."""
    return [e for e in entries if e.get("role") in GOVERNANCE_ACTOR_ROLES]
