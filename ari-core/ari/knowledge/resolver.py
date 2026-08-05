"""Pure fixed Knowledge Binder; Router proposals have no direct effect."""

from __future__ import annotations

from collections import defaultdict

from ari.capability_binding.models import CapabilityRequirementV1
from ari.knowledge.models import (
    EpochKnowledgeSkillLockV1,
    KnowledgeAdmissionContextV1,
    KnowledgeAdmissionFindingV1,
    KnowledgeSkillCatalogSnapshotV1,
    KnowledgeSkillEntryV1,
    KnowledgeSkillRefV1,
    KnowledgeSkillSelectionProposalV1,
)
from ari.protocols.integrity import canonical_digest
from ari.capability_binding.models import CapabilityOntologySnapshotV1
from ari.protocols.scientific_requirements import EvaluationObligationV1


class KnowledgeAdmissionError(ValueError):
    pass


_SIDE_RANK = {
    "read-only": 0,
    "workspace-write": 1,
    "scheduler-submit": 2,
    "external-write": 3,
    "physical-actuation": 4,
}


def _exact_key(ref: KnowledgeSkillRefV1) -> tuple[str, str, str, str]:
    return (ref.id, ref.version, ref.body_sha256, ref.manifest_sha256)


def _finding(ref: KnowledgeSkillRefV1, code: str, detail: str) -> KnowledgeAdmissionFindingV1:
    return KnowledgeAdmissionFindingV1(skill_ref=ref, code=code, detail=detail)


def _select_entries(
    proposal: KnowledgeSkillSelectionProposalV1,
    catalog: KnowledgeSkillCatalogSnapshotV1,
    context: KnowledgeAdmissionContextV1,
) -> tuple[
    dict[tuple[str, str, str, str], KnowledgeSkillEntryV1],
    list[KnowledgeAdmissionFindingV1],
    list[KnowledgeAdmissionFindingV1],
]:
    entries = {
        _exact_key(entry.manifest.exact_ref()): entry for entry in catalog.entries
    }
    selected: dict[tuple[str, str, str, str], KnowledgeSkillEntryV1] = {}
    rejected: list[KnowledgeAdmissionFindingV1] = []
    unsatisfied: list[KnowledgeAdmissionFindingV1] = []
    visiting: set[tuple[str, str, str, str]] = set()

    def add(ref: KnowledgeSkillRefV1) -> None:
        key = _exact_key(ref)
        if key in selected:
            return
        if key in visiting:
            unsatisfied.append(_finding(ref, "dependency_cycle", "dependency cycle"))
            return
        entry = entries.get(key)
        if entry is None:
            unsatisfied.append(_finding(ref, "missing_exact_entry", "exact entry absent"))
            return
        manifest = entry.manifest
        applicability = _applicability_finding(entry, context)
        if applicability is not None:
            rejected.append(applicability)
            return
        visiting.add(key)
        for dependency in manifest.dependencies:
            add(dependency)
        visiting.remove(key)
        selected[key] = entry

    for ref in sorted(proposal.proposed, key=_exact_key):
        add(ref)
    return selected, rejected, unsatisfied


def _applicability_finding(
    entry: KnowledgeSkillEntryV1,
    context: KnowledgeAdmissionContextV1,
) -> KnowledgeAdmissionFindingV1 | None:
    manifest = entry.manifest
    ref = manifest.exact_ref()
    if entry.status != "verified":
        return _finding(
            ref, f"status_{entry.status}", "only verified content is admissible"
        )
    if context.role not in manifest.applies_to.roles:
        return _finding(ref, "role_not_applicable", context.role)
    if context.phase not in manifest.applies_to.phases:
        return _finding(ref, "phase_not_applicable", context.phase)
    if manifest.applies_to.task_tags and not (
        set(manifest.applies_to.task_tags) & set(context.task_tags)
    ):
        return _finding(ref, "task_tag_not_applicable", "no matching task tag")
    if not set(manifest.authority_ceiling.side_effects).issubset(
        set(context.permitted_side_effects)
    ):
        return _finding(ref, "authority_ceiling_exceeded", "run authority is lower")
    return None


def _composition_findings(
    selected: dict[tuple[str, str, str, str], KnowledgeSkillEntryV1],
) -> list[KnowledgeAdmissionFindingV1]:
    findings: list[KnowledgeAdmissionFindingV1] = []
    selected_ids = {entry.manifest.id for entry in selected.values()}
    for entry in tuple(selected.values()):
        for conflict in sorted(selected_ids & set(entry.manifest.conflicts)):
            findings.append(
                _finding(entry.manifest.exact_ref(), "composition_conflict", conflict)
            )
    exclusive_slots: dict[str, list[KnowledgeSkillEntryV1]] = defaultdict(list)
    for entry in selected.values():
        if entry.manifest.composition.exclusive:
            exclusive_slots[entry.manifest.composition.slot].append(entry)
    for slot, items in exclusive_slots.items():
        if len(items) > 1:
            findings.extend(
                _finding(entry.manifest.exact_ref(), "exclusive_slot_conflict", slot)
                for entry in items
            )
    return findings


def _requirements_and_obligations(
    admitted_entries: list[KnowledgeSkillEntryV1],
    ontology: CapabilityOntologySnapshotV1,
    context: KnowledgeAdmissionContextV1,
    rejected: list[KnowledgeAdmissionFindingV1],
    unsatisfied: list[KnowledgeAdmissionFindingV1],
) -> tuple[list[CapabilityRequirementV1], list[EvaluationObligationV1]]:
    contracts = {item.capability_ref: item for item in ontology.contracts}
    requirements: list[CapabilityRequirementV1] = []
    obligations: list[EvaluationObligationV1] = []
    for entry in admitted_entries:
        manifest = entry.manifest
        ceiling = max(
            manifest.authority_ceiling.side_effects,
            key=lambda item: _SIDE_RANK[item],
        )
        declarations = (
            *((item, True) for item in manifest.requires.capabilities),
            *((item, False) for item in manifest.optional_capabilities),
        )
        for declared, is_required in declarations:
            contract = contracts.get(declared.ref)
            if contract is None:
                unsatisfied.append(
                    _finding(manifest.exact_ref(), "unknown_capability", declared.ref)
                )
            elif _SIDE_RANK[contract.side_effect_class] > _SIDE_RANK[ceiling]:
                rejected.append(
                    _finding(
                        manifest.exact_ref(), "capability_above_authority", declared.ref
                    )
                )
            else:
                requirements.append(
                    _capability_requirement(manifest, declared, contract, is_required, ceiling)
                )
        for obligation in manifest.evaluation_obligations:
            if obligation.property_id not in context.property_vocabulary:
                unsatisfied.append(
                    _finding(
                        manifest.exact_ref(),
                        "unknown_assurance_property",
                        obligation.property_id,
                    )
                )
            else:
                obligations.append(
                    obligation.model_copy(
                        update={"source_skill_digest": manifest.source.body_sha256}
                    )
                )
    return requirements, obligations


def _capability_requirement(manifest, declared, contract, is_required, ceiling):
    return CapabilityRequirementV1.create(
        capability_ref=declared.ref,
        capability_contract_digest=contract.contract_digest,
        required=is_required,
        semantic_constraints=declared.semantic_constraints,
        roles=manifest.applies_to.roles,
        phases=manifest.applies_to.phases,
        context_requirement=contract.context_requirement,
        side_effect_ceiling=ceiling,
        explicit_provider_pin=declared.explicit_provider_pin,
        forbidden_capability_refs=manifest.forbidden_capabilities,
        source_requirement_refs=(f"knowledge:{manifest.source.body_sha256}",),
    )


def _merge_requirements(
    requirements: list[CapabilityRequirementV1],
) -> dict[tuple[str, str, str], CapabilityRequirementV1]:
    merged: dict[tuple[str, str, str], CapabilityRequirementV1] = {}
    for item in requirements:
        key = (
            item.capability_ref,
            item.capability_contract_digest,
            canonical_digest(item.semantic_constraints),
        )
        previous = merged.get(key)
        if previous is None:
            merged[key] = item
            continue
        ceiling = min(
            (previous.side_effect_ceiling, item.side_effect_ceiling),
            key=lambda effect: _SIDE_RANK[effect],
        )
        merged[key] = CapabilityRequirementV1.create(
            **previous.model_dump(
                mode="python",
                exclude={
                    "requirement_digest",
                    "required",
                    "side_effect_ceiling",
                    "source_requirement_refs",
                },
            ),
            required=previous.required or item.required,
            side_effect_ceiling=ceiling,
            source_requirement_refs=tuple(
                sorted(
                    set(previous.source_requirement_refs)
                    | set(item.source_requirement_refs)
                )
            ),
        )
    return merged


def admit_knowledge_skills(
    *,
    proposal: KnowledgeSkillSelectionProposalV1,
    catalog: KnowledgeSkillCatalogSnapshotV1,
    ontology: CapabilityOntologySnapshotV1,
    context: KnowledgeAdmissionContextV1,
    mode: str,
) -> EpochKnowledgeSkillLockV1:
    """Resolve exact verified content without LLM, network, clock, or Provider use."""

    if mode not in {"audit", "enforce"}:
        raise KnowledgeAdmissionError("Knowledge Binder requires audit or enforce mode")
    selected, rejected, unsatisfied = _select_entries(proposal, catalog, context)
    unsatisfied.extend(_composition_findings(selected))
    admitted_entries = sorted(
        selected.values(),
        key=lambda item: (
            item.manifest.composition.slot_rank,
            -item.manifest.composition.priority,
            item.manifest.id,
            item.manifest.version,
            item.manifest.source.body_sha256,
        ),
    )
    requirements, obligations = _requirements_and_obligations(
        admitted_entries, ontology, context, rejected, unsatisfied
    )
    merged = _merge_requirements(requirements)

    rejected.sort(key=lambda item: (_exact_key(item.skill_ref), item.code))
    unsatisfied.sort(key=lambda item: (_exact_key(item.skill_ref), item.code))
    if mode == "enforce" and (rejected or unsatisfied):
        codes = ", ".join(sorted({item.code for item in rejected + unsatisfied}))
        raise KnowledgeAdmissionError(f"Knowledge admission unsatisfied: {codes}")
    return EpochKnowledgeSkillLockV1.create(
        run_id=proposal.run_id,
        epoch_id=proposal.epoch_id,
        research_contract_digest=proposal.research_contract_digest,
        catalog_snapshot_digest=catalog.snapshot_digest,
        proposal_digest=proposal.proposal_digest,
        ontology_snapshot_digest=ontology.snapshot_digest,
        context_digest=context.context_digest,
        admitted=tuple(entry.manifest.exact_ref() for entry in admitted_entries),
        capability_requirements=tuple(
            sorted(merged.values(), key=lambda item: (item.capability_ref, item.requirement_digest))
        ),
        evaluation_obligations=tuple(
            sorted(
                obligations,
                key=lambda item: (
                    item.property_id,
                    item.required_tier,
                    item.required_methods,
                    item.source_skill_digest or "",
                ),
            )
        ),
        rejected=tuple(rejected),
        unsatisfied=tuple(unsatisfied),
        mode=mode,
    )


__all__ = ["KnowledgeAdmissionError", "admit_knowledge_skills"]
