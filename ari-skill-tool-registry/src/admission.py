"""Admission and overlap policy for federated tools."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from models import (
    AdmissionDecisionV1,
    AdmissionEvidenceV1,
    AdmissionLevel,
    CanonicalToolDescriptorV1,
    OverlapDecisionV1,
    credential_field_paths,
    sha256_digest,
)


class AdmissionPolicyV1(BaseModel):
    """Versioned, deterministic requirements for runtime admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str = "ari.default-federation-admission"
    version: str = "1.0.0"
    required_level: AdmissionLevel = "callable"
    allowed_permissions: list[str] = Field(
        default_factory=lambda: [
            "network",
            "process",
            "scheduler",
            "workspace-read",
            "workspace-write",
        ]
    )
    require_protocol_conformance: bool = True
    require_provider_pin: bool = True
    require_verified_launcher: bool = True
    require_dependency_pin_for_replay: bool = True
    require_replay_fixture: bool = True
    require_scientific_validation: bool = True
    require_limitations: bool = True
    require_semantics: bool = True
    require_units: bool = True
    require_method_identity: bool = True

    @property
    def digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))


class AdmissionEngine:
    def __init__(self, policy: AdmissionPolicyV1 | None = None) -> None:
        self.policy = policy or AdmissionPolicyV1()

    def evaluate(
        self,
        descriptor: CanonicalToolDescriptorV1,
        evidence: AdmissionEvidenceV1,
    ) -> AdmissionDecisionV1:
        """Return the highest level supported by evidence without guessing."""

        reasons: list[str] = []
        callable_ok = True
        if (
            self.policy.require_protocol_conformance
            and not evidence.protocol_conformance
        ):
            callable_ok = False
            reasons.append("protocol conformance evidence is missing")
        if self.policy.require_provider_pin and not evidence.provider_pinned:
            callable_ok = False
            reasons.append("provider identity is not pinned")
        if self.policy.require_verified_launcher and not evidence.launcher_verified:
            callable_ok = False
            reasons.append("launcher has not been verified")
        disallowed = sorted(
            set(descriptor.permissions) - set(self.policy.allowed_permissions)
        )
        if disallowed:
            callable_ok = False
            reasons.append(f"permissions are not admitted: {disallowed}")
        credential_fields = credential_field_paths(
            descriptor.input_schema.get("properties", {}),
            "input_schema.properties",
        )
        if credential_fields:
            callable_ok = False
            reasons.append(
                "direct credential fields require a value-free credential-scope "
                f"adapter: {credential_fields}"
            )

        level: AdmissionLevel = "discovered"
        if callable_ok:
            level = "callable"

        reproducible_ok = callable_ok
        if (
            self.policy.require_dependency_pin_for_replay
            and not evidence.dependencies_pinned
        ):
            reproducible_ok = False
            reasons.append("dependency closure is not pinned")
        if (
            self.policy.require_replay_fixture
            and evidence.replay_fixture_digest is None
        ):
            reproducible_ok = False
            reasons.append("offline replay fixture is missing")
        if reproducible_ok:
            level = "reproducible"

        scientific_ok = reproducible_ok
        scientific_requirements = (
            (
                self.policy.require_scientific_validation
                and evidence.scientific_validation_digest is None,
                "scientific validation evidence is missing",
            ),
            (
                self.policy.require_limitations and not evidence.limitations_documented,
                "limitations are not documented",
            ),
            (
                self.policy.require_semantics and not evidence.semantics_documented,
                "measurement semantics are not documented",
            ),
            (
                self.policy.require_units and not evidence.units_documented,
                "units are not documented",
            ),
            (
                self.policy.require_method_identity
                and not evidence.method_identity_documented,
                "method/backend identity is not documented",
            ),
        )
        for missing, reason in scientific_requirements:
            if missing:
                scientific_ok = False
                reasons.append(reason)
        if scientific_ok:
            level = "scientifically_admitted"

        return AdmissionDecisionV1(
            tool_ref=descriptor.tool_ref,
            level=level,
            required_level=self.policy.required_level,
            policy_digest=self.policy.digest,
            evidence_digest=sha256_digest(evidence.model_dump(mode="json")),
            reasons=reasons,
        )

    def evaluate_all(
        self,
        descriptors: Iterable[CanonicalToolDescriptorV1],
        evidence_by_ref: dict[str, AdmissionEvidenceV1],
    ) -> list[AdmissionDecisionV1]:
        return [
            self.evaluate(
                descriptor,
                evidence_by_ref.get(descriptor.tool_ref, AdmissionEvidenceV1()),
            )
            for descriptor in sorted(descriptors, key=lambda item: item.tool_ref)
        ]


def resolve_overlaps(
    descriptors: Iterable[CanonicalToolDescriptorV1],
) -> tuple[list[CanonicalToolDescriptorV1], list[OverlapDecisionV1]]:
    """Collapse execution-identical aliases and explain semantic overlap."""

    by_ref: dict[str, list[CanonicalToolDescriptorV1]] = defaultdict(list)
    for descriptor in descriptors:
        by_ref[descriptor.tool_ref].append(descriptor)

    collapsed: list[CanonicalToolDescriptorV1] = []
    overlaps: list[OverlapDecisionV1] = []
    for tool_ref, aliases in sorted(by_ref.items()):
        first = aliases[0]
        if len(aliases) == 1:
            collapsed.append(first)
            continue
        source_ids = sorted(
            {source_id for alias in aliases for source_id in alias.source_ids}
        )
        chains: list = []
        seen_chains: set[str] = set()
        for alias in aliases:
            for chain in alias.origin_chains:
                signature = sha256_digest(
                    [hop.model_dump(mode="json") for hop in chain]
                )
                if signature not in seen_chains:
                    seen_chains.add(signature)
                    chains.append(chain)
        merged = first.model_copy(
            update={"source_ids": source_ids, "origin_chains": chains}
        )
        collapsed.append(merged)
        overlaps.append(
            OverlapDecisionV1(
                capability_ref=first.capability_ref,
                tool_refs=[tool_ref],
                relationship="exact-duplicate",
                explanation=(
                    f"collapsed {len(aliases)} aliases of the same provider, "
                    "adapter, schema, defaults, and leaf implementation"
                ),
            )
        )

    by_capability: dict[str, list[CanonicalToolDescriptorV1]] = defaultdict(list)
    for descriptor in collapsed:
        by_capability[descriptor.capability_ref].append(descriptor)
    for capability, members in sorted(by_capability.items()):
        if len(members) < 2:
            continue
        refs = sorted(member.tool_ref for member in members)
        independence_groups = {member.independence_group for member in members}
        equivalence_keys = {member.equivalence_key for member in members}
        semantic_digests = {
            sha256_digest({"semantics": member.semantics, "units": member.units})
            for member in members
        }
        if len(independence_groups) < len(members):
            relationship = "same-backend"
            explanation = (
                "multiple wrappers share an independence group and must not be "
                "counted as independent evidence"
            )
        elif (
            None not in equivalence_keys
            and len(equivalence_keys) == 1
            and len(semantic_digests) == 1
        ):
            relationship = "independent-method"
            explanation = (
                "equivalent semantics are implemented by distinct independence groups"
            )
        else:
            relationship = "semantic-near-match"
            explanation = "shared capability is insufficient for equivalence; tools remain separate"
        overlaps.append(
            OverlapDecisionV1(
                capability_ref=capability,
                tool_refs=refs,
                relationship=relationship,
                explanation=explanation,
            )
        )

    return sorted(collapsed, key=lambda item: item.tool_ref), sorted(
        overlaps,
        key=lambda item: (
            item.capability_ref,
            item.relationship,
            item.tool_refs,
        ),
    )


__all__ = ["AdmissionEngine", "AdmissionPolicyV1", "resolve_overlaps"]
