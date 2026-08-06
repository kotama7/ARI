"""Fixed applicability and readiness evaluation for manuscript contexts."""

from __future__ import annotations

from ari.manuscript.contracts import (
    ManuscriptContextV1,
    ManuscriptReadinessReportV1,
    ManuscriptRequirementProfileV1,
    OmissionManifestV1,
    RequirementResultV1,
    RequirementSpecV1,
)
from ari.manuscript.profiles import EVALUATOR_VERSION


def _applicable(spec: RequirementSpecV1, context: ManuscriptContextV1) -> tuple[bool, tuple[str, ...]]:
    rule = spec.applicability_rule_id
    if rule == "always":
        return True, ("rule:always",)
    value = bool(context.claim_characteristics.get(rule, False))
    return value, (f"claim_characteristics.{rule}={str(value).lower()}",)


def _result(
    spec: RequirementSpecV1,
    *,
    applicable: bool,
    trace: tuple[str, ...],
    satisfied: bool,
    evidence: tuple[str, ...] = (),
    reason_satisfied: str = "evidence_present",
    reason_missing: str = "required_evidence_missing",
    unavailable: bool = False,
    explanation: str = "",
) -> RequirementResultV1:
    if not applicable:
        status = "not_applicable"
        reason = "applicability_rule_false"
        resolver = None
    elif satisfied:
        status = "satisfied"
        reason = reason_satisfied
        resolver = None
    elif unavailable:
        status = "unavailable"
        reason = reason_missing
        resolver = spec.resolver_kinds[0] if spec.resolver_kinds else None
    else:
        status = "missing"
        reason = reason_missing
        resolver = spec.resolver_kinds[0] if spec.resolver_kinds else None
    return RequirementResultV1(
        requirement_id=spec.requirement_id,
        applicable=applicable,
        applicability_trace=trace,
        status=status,
        evidence_refs=tuple(dict.fromkeys(evidence)),
        reason_code=reason,
        explanation=explanation,
        authoring_blocking=spec.authoring_blocking,
        publication_blocking=spec.publication_blocking,
        resolver_kind=resolver,
        evaluator_version=EVALUATOR_VERSION,
    )


def _evaluate_one(
    spec: RequirementSpecV1,
    context: ManuscriptContextV1,
    omissions: OmissionManifestV1,
) -> RequirementResultV1:
    applicable, trace = _applicable(spec, context)
    if not applicable:
        return _result(spec, applicable=False, trace=trace, satisfied=False)

    evidence = context.evidence_records
    metrics = [item for item in evidence if item.metric_values and item.lane != "excluded"]
    rid = spec.requirement_id
    if rid == "MC-RQ-001":
        value = str(context.research_question.get("question") or "").strip()
        return _result(spec, applicable=True, trace=trace, satisfied=bool(value), evidence=("research-question",) if value else ())
    if rid == "MC-RQ-002":
        hypothesis = str(context.research_question.get("hypothesis") or "").strip()
        falsification = context.research_question.get("falsification_conditions") or []
        return _result(spec, applicable=True, trace=trace, satisfied=bool(hypothesis and falsification), evidence=("research-question",) if hypothesis or falsification else (), reason_missing="hypothesis_or_falsification_missing")
    if rid == "MC-ME-001":
        refs = tuple(str(item.get("method_id")) for item in context.methods if item.get("method_id"))
        return _result(spec, applicable=True, trace=trace, satisfied=bool(context.methods), evidence=refs, reason_missing="method_description_missing")
    if rid == "MC-ME-002":
        count = int(context.reproducibility.get("configuration_count") or 0)
        env = context.reproducibility.get("environment") or {}
        return _result(spec, applicable=True, trace=trace, satisfied=bool(count and env), evidence=("reproducibility",) if count or env else (), reason_missing="configuration_or_environment_missing")
    if rid == "MC-ME-003":
        has_plan = bool(context.methods)
        return _result(spec, applicable=True, trace=trace, satisfied=has_plan, evidence=("research-plan",) if has_plan else (), reason_missing="execution_protocol_missing")
    if rid == "MC-RS-001":
        refs = tuple(item.evidence_id for item in metrics)
        return _result(spec, applicable=True, trace=trace, satisfied=bool(metrics), evidence=refs, reason_missing="primary_result_missing")
    if rid == "MC-RS-002":
        ok = bool(context.reproducibility.get("uncertainty_evidence"))
        return _result(spec, applicable=True, trace=trace, satisfied=ok, evidence=("reproducibility:uncertainty",) if ok else (), reason_missing="uncertainty_evidence_missing")
    if rid in {"MC-CP-001", "MC-CP-002"}:
        ok = len(metrics) >= 2
        return _result(spec, applicable=True, trace=trace, satisfied=ok, evidence=tuple(item.evidence_id for item in metrics[:2]), reason_missing="comparator_evidence_missing")
    if rid == "MC-AB-001":
        refs = tuple(
            f"node:{item.get('node_id')}"
            for item in context.exploration_history
            if item.get("label") == "ablation"
        )
        return _result(spec, applicable=True, trace=trace, satisfied=bool(refs), evidence=refs, reason_missing="ablation_evidence_missing")
    if rid == "MC-CL-001":
        refs = tuple(item.evidence_id for item in metrics)
        return _result(spec, applicable=True, trace=trace, satisfied=bool(refs), evidence=refs, reason_missing="claim_evidence_projection_missing")
    if rid == "MC-CL-002":
        refs = tuple(item.evidence_id for item in metrics if item.artifact_item_ids)
        return _result(spec, applicable=True, trace=trace, satisfied=bool(refs), evidence=refs, reason_missing="numeric_evidence_artifact_missing")
    if rid == "MC-NG-001":
        expected = set(context.subjects.get("negative_node_ids") or [])
        actual = {str(item.get("node_id")) for item in context.negative_results}
        ok = expected == actual
        return _result(spec, applicable=True, trace=trace, satisfied=ok, evidence=tuple(f"node:{item}" for item in sorted(actual)), reason_missing="negative_result_accounting_incomplete")
    if rid == "MC-SL-001":
        expected = int(context.subjects.get("node_count") or 0)
        ok = len(context.exploration_history) == expected and bool(context.subjects.get("selection_reason"))
        return _result(spec, applicable=True, trace=trace, satisfied=ok, evidence=("subject-selection",) if ok else (), reason_missing="selection_rationale_incomplete")
    if rid == "MC-RW-001":
        refs = tuple(str(item.get("reference_id")) for item in context.related_work if item.get("reference_id"))
        return _result(spec, applicable=True, trace=trace, satisfied=bool(refs), evidence=refs, reason_missing="recorded_related_work_missing")
    if rid == "MC-RW-002":
        ok = bool(context.related_work and context.research_question.get("question"))
        return _result(spec, applicable=True, trace=trace, satisfied=ok, evidence=("related-work", "research-question") if ok else (), reason_missing="novelty_comparison_missing")
    if rid == "MC-LM-001":
        return _result(spec, applicable=True, trace=trace, satisfied=bool(context.limitations), evidence=("limitations",) if context.limitations else (), reason_missing="limitations_missing")
    if rid == "MC-LM-002":
        return _result(spec, applicable=True, trace=trace, satisfied=bool(context.threats_to_validity), evidence=("threats-to-validity",) if context.threats_to_validity else (), reason_missing="validity_threats_missing")
    if rid == "MC-RP-001":
        ok = bool(context.reproducibility.get("ear_manifest") and context.reproducibility.get("ear_digest"))
        return _result(spec, applicable=True, trace=trace, satisfied=ok, evidence=("ear-manifest",) if ok else (), reason_missing="ear_inventory_missing")
    if rid == "MC-RP-002":
        ok = bool(context.reproducibility.get("commands") or context.reproducibility.get("code_bundle_lock"))
        return _result(spec, applicable=True, trace=trace, satisfied=ok, evidence=("reproduction-lock",) if ok else (), reason_missing="reproduction_commands_or_lock_missing")
    if rid == "MC-AS-001":
        candidate = context.assurance.get("publication_candidate")
        certified = set(context.assurance.get("certified_node_ids") or [])
        ok = bool(candidate and candidate in certified)
        unavailable = not bool(context.assurance.get("attestation_item_ids"))
        return _result(spec, applicable=True, trace=trace, satisfied=ok, evidence=tuple(context.assurance.get("attestation_item_ids") or ()), reason_missing="publication_certification_unavailable" if unavailable else "publication_certification_missing", unavailable=unavailable)
    if rid == "MC-OM-001":
        return _result(spec, applicable=True, trace=trace, satisfied=True, evidence=(omissions.manifest_digest,), reason_satisfied="inventory_conserved")
    return _result(spec, applicable=True, trace=trace, satisfied=False, reason_missing="unimplemented_requirement_evaluator")


def evaluate_readiness(
    profile: ManuscriptRequirementProfileV1,
    context: ManuscriptContextV1,
    omissions: OmissionManifestV1,
) -> ManuscriptReadinessReportV1:
    if context.profile_digest != profile.profile_digest:
        raise ValueError("manuscript context belongs to another requirement profile")
    if context.omission_manifest_digest != omissions.manifest_digest:
        raise ValueError("manuscript context belongs to another omission manifest")
    results = tuple(_evaluate_one(spec, context, omissions) for spec in profile.requirements)
    counts = {
        status: sum(item.status == status for item in results)
        for status in ("satisfied", "not_applicable", "unavailable", "missing")
    }
    author_missing = any(item.authoring_blocking and item.status == "missing" for item in results)
    author_unavailable = any(item.authoring_blocking and item.status == "unavailable" for item in results)
    authoring_verdict = (
        "blocked"
        if author_unavailable
        else "repair_required"
        if author_missing
        else "ready_with_disclosures"
        if counts["unavailable"]
        else "ready"
    )
    publication_verdict = (
        "blocked"
        if any(
            item.publication_blocking and item.status in {"missing", "unavailable"}
            for item in results
        )
        else "ready"
    )
    return ManuscriptReadinessReportV1.create(
        run_id=context.run_id,
        profile_digest=profile.profile_digest,
        context_digest=context.context_digest,
        evaluator_version=EVALUATOR_VERSION,
        requirement_results=results,
        authoring_verdict=authoring_verdict,
        publication_verdict=publication_verdict,
        counts=counts,
    )


__all__ = ["evaluate_readiness"]
