"""Versioned requirement profiles and fixed applicability policy."""

from __future__ import annotations

from functools import lru_cache

from ari.manuscript.contracts import (
    ManuscriptRequirementProfileV1,
    RequirementSpecV1,
)


PROFILE_ID = "generic_empirical_v1"
EVALUATOR_VERSION = "manuscript-evaluator-v1"


def _req(
    requirement_id: str,
    description: str,
    sections: tuple[str, ...],
    rule: str,
    *,
    authoring: bool,
    publication: bool,
    resolvers: tuple[str, ...],
    evidence: tuple[str, ...],
) -> RequirementSpecV1:
    return RequirementSpecV1(
        requirement_id=requirement_id,
        description=description,
        section_targets=sections,
        applicability_rule_id=rule,
        authoring_blocking=authoring,
        publication_blocking=publication,
        resolver_kinds=resolvers,
        evidence_kinds=evidence,
    )


@lru_cache(maxsize=1)
def generic_empirical_profile() -> ManuscriptRequirementProfileV1:
    specs = (
        _req("MC-RQ-001", "Research question and objective", ("introduction",), "always", authoring=True, publication=True, resolvers=("method_clarification", "human_decision"), evidence=("research-contract",)),
        _req("MC-RQ-002", "Hypothesis and falsification condition", ("introduction", "method"), "hypothesis_testing", authoring=True, publication=True, resolvers=("method_clarification", "human_decision"), evidence=("research-contract",)),
        _req("MC-ME-001", "Method or algorithm description", ("method",), "always", authoring=True, publication=True, resolvers=("artifact_recovery", "method_clarification"), evidence=("node", "source", "research-contract")),
        _req("MC-ME-002", "Configuration and execution environment", ("experimental-setup",), "empirical", authoring=True, publication=True, resolvers=("artifact_recovery",), evidence=("science-data", "ear-manifest", "configuration")),
        _req("MC-ME-003", "Protocol, workload, and stopping rule", ("experimental-setup",), "empirical", authoring=True, publication=True, resolvers=("artifact_recovery", "validation_experiment"), evidence=("research-contract", "ear-manifest", "source")),
        _req("MC-RS-001", "Primary metric, direction, unit, and run identities", ("results",), "result_claim", authoring=True, publication=True, resolvers=("projection_rebuild", "validation_experiment"), evidence=("science-data", "measurement")),
        _req("MC-RS-002", "Repetition and uncertainty", ("results", "limitations"), "stochastic_claim", authoring=True, publication=True, resolvers=("repetition_or_uncertainty",), evidence=("science-data", "measurement")),
        _req("MC-CP-001", "Baseline or comparator", ("experimental-setup", "results"), "comparative_claim", authoring=True, publication=True, resolvers=("baseline_comparison",), evidence=("measurement", "configuration")),
        _req("MC-CP-002", "Equivalent comparison protocol", ("experimental-setup", "results"), "comparator_exists", authoring=True, publication=True, resolvers=("validation_experiment",), evidence=("measurement", "configuration")),
        _req("MC-AB-001", "Ablation for component-causal contribution", ("results",), "multi_component_claim", authoring=True, publication=True, resolvers=("ablation",), evidence=("measurement", "configuration")),
        _req("MC-CL-001", "Claim-to-measurement coverage", ("results",), "result_claim", authoring=True, publication=True, resolvers=("projection_rebuild",), evidence=("science-data", "measurement")),
        _req("MC-CL-002", "Reproducible numeric assertions", ("results",), "numeric_result", authoring=True, publication=True, resolvers=("projection_rebuild", "validation_experiment"), evidence=("science-data", "measurement", "figure")),
        _req("MC-NG-001", "Failed, null, and inconclusive result accounting", ("results", "limitations"), "always", authoring=False, publication=True, resolvers=("projection_rebuild", "limitation_disclosure"), evidence=("node",)),
        _req("MC-SL-001", "Selection rationale and off-lineage accounting", ("method", "results"), "multiple_candidates", authoring=False, publication=True, resolvers=("projection_rebuild",), evidence=("node", "selection")),
        _req("MC-RW-001", "Recorded related-work snapshot", ("related-work",), "always", authoring=True, publication=True, resolvers=("literature_search",), evidence=("retrieval-records",)),
        _req("MC-RW-002", "Novelty distinction", ("introduction", "related-work"), "novelty_claim", authoring=True, publication=True, resolvers=("literature_search", "human_decision"), evidence=("retrieval-records", "research-contract")),
        _req("MC-LM-001", "Limitations disclosure", ("limitations",), "always", authoring=True, publication=True, resolvers=("limitation_disclosure",), evidence=("context",)),
        _req("MC-LM-002", "Threats to validity", ("limitations",), "empirical", authoring=False, publication=True, resolvers=("limitation_disclosure",), evidence=("context",)),
        _req("MC-RP-001", "EAR, source, and environment inventory", ("reproducibility",), "empirical", authoring=True, publication=True, resolvers=("artifact_recovery",), evidence=("ear-manifest", "source")),
        _req("MC-RP-002", "Reproduction commands and locks", ("reproducibility",), "reproducibility_claim", authoring=True, publication=True, resolvers=("artifact_recovery",), evidence=("ear-manifest", "code-bundle-lock")),
        _req("MC-AS-001", "Current publication certification", ("reproducibility", "limitations"), "assurance_enforce", authoring=False, publication=True, resolvers=("assurance_certification",), evidence=("harness-attestation",)),
        _req("MC-OM-001", "Complete omission accounting", ("all",), "manuscript_enabled", authoring=True, publication=True, resolvers=("projection_rebuild",), evidence=("omission-manifest",)),
    )
    return ManuscriptRequirementProfileV1.create(
        profile_id=PROFILE_ID,
        profile_version="1",
        paper_family="generic_empirical",
        policy_version="1",
        evaluator_compatibility=(EVALUATOR_VERSION,),
        requirements=specs,
    )


def resolve_profile(profile_id: str) -> ManuscriptRequirementProfileV1:
    if profile_id != PROFILE_ID:
        raise ValueError(f"unknown manuscript profile: {profile_id}")
    return generic_empirical_profile()


__all__ = [
    "EVALUATOR_VERSION",
    "PROFILE_ID",
    "generic_empirical_profile",
    "resolve_profile",
]
