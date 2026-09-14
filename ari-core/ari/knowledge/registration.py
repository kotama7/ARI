"""Knowledge registration gate aggregation; no catalog write authority."""

from __future__ import annotations

from ari.knowledge.models import (
    KnowledgeRegistrationGateV1,
    KnowledgeSkillRefV1,
    KnowledgeSkillRegistrationReportV1,
)


KNOWLEDGE_REGISTRATION_GATES = (
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


def registration_report(
    *,
    skill_ref: KnowledgeSkillRefV1,
    gates: tuple[KnowledgeRegistrationGateV1, ...],
    non_authoritative_hints: tuple[str, ...] = (),
    attachments: tuple[str, ...] = (),
) -> KnowledgeSkillRegistrationReportV1:
    if tuple(item.gate_id for item in gates) != KNOWLEDGE_REGISTRATION_GATES:
        raise ValueError("Knowledge registration gates are incomplete or out of order")
    if all(item.passed for item in gates):
        decision = "eligible-for-verified"
    elif any(item.gate_id in {"no_executable_entrypoint", "no_script_autolaunch", "reference_isolation"} and not item.passed for item in gates):
        decision = "quarantined"
    else:
        decision = "candidate"
    return KnowledgeSkillRegistrationReportV1.create(
        skill_ref=skill_ref,
        gates=gates,
        non_authoritative_hints=tuple(sorted(set(non_authoritative_hints))),
        attachments=tuple(sorted(set(attachments))),
        decision=decision,
    )


__all__ = ["KNOWLEDGE_REGISTRATION_GATES", "registration_report"]
