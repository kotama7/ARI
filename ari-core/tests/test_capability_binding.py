from __future__ import annotations

import pytest

from ari.call_context import ToolCallContextV1
from ari.capability_binding.models import (
    CapabilityBindingRequestV1,
    CapabilityContractV1,
    CapabilityProvisionV1,
    CapabilityRequirementV1,
)
from ari.capability_binding.resolver import CapabilityBindingError, bind_capabilities
from ari.capability_binding.substitution import (
    SYNTHETIC_SUBSTITUTE_PROVIDER_ID,
    ProviderExecutionObservationV1,
    probe_capability_abstraction,
    probe_provider_substitution,
    synthetic_substitute_provision,
)
from ari.capability_binding.validation import BoundToolAuthorizationView
from ari.protocols.integrity import canonical_digest
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1


SHA = "sha256:" + ("3" * 64)


def _contract():
    return CapabilityContractV1.create(
        capability_ref="ari.execution.compile/v1",
        contract_version="v1",
        title="Compile",
        description="Compile source",
        side_effect_class="workspace-write",
        determinism_class="conditional",
        context_requirement="node",
        compatibility_rules=("schema",),
    )


def _requirement(contract, **updates):
    values = dict(
        capability_ref=contract.capability_ref,
        capability_contract_digest=contract.contract_digest,
        roles=("generator",),
        phases=("bfts",),
        context_requirement="node",
        side_effect_ceiling="workspace-write",
        source_requirement_refs=("knowledge:fixture",),
    )
    values.update(updates)
    return CapabilityRequirementV1.create(**values)


def _provision(contract, *, provider="provider-a", tool="provider-a::compile", **updates):
    values = dict(
        provider_id=provider,
        provider_identity_digest=canonical_digest({"provider": provider}),
        provider_status="verified",
        tool_ref=tool,
        declared_capability_ref="legacy.compile",
        capability_ref=contract.capability_ref,
        capability_contract_digest=contract.contract_digest,
        provider_lock_digest=SHA,
        manifest_digest=SHA,
        input_schema_digest=canonical_digest({"type": "object"}),
        output_schema_digest=canonical_digest({"type": "object"}),
        policy_digest=SHA,
        schema_compatibility_evidence_digest=SHA,
        side_effect_class="workspace-write",
        determinism_class="conditional",
        context_requirement="node",
        roles=("generator",),
        phases=("bfts",),
        reproducibility_grade="exact",
        declared_resource_cost=(1, 1, 1),
        registration_report_digest=SHA,
    )
    values.update(updates)
    return CapabilityProvisionV1.create(**values)


def _request(requirement, provisions, **updates):
    values = dict(
        run_id="run-1",
        epoch_id="epoch_000",
        research_contract_digest=SHA,
        knowledge_skill_lock_digest=SHA,
        ontology_snapshot_digest=SHA,
        provider_catalog_snapshot_digest=SHA,
        provider_lock_digest=SHA,
        requirements=(requirement,),
        provisions=tuple(provisions),
        available_tool_refs=tuple(item.tool_ref for item in provisions),
        role="generator",
        phase="bfts",
        call_context="node",
        authorized_capability_refs=(requirement.capability_ref,),
        environment=EnvironmentSnapshotV1.create(resource_types=("process",)),
        mode="enforce",
    )
    values.update(updates)
    return CapabilityBindingRequestV1.create(**values)


def test_binding_lock_is_byte_identical_for_permuted_input_order():
    contract = _contract()
    requirement = _requirement(contract)
    a = _provision(contract, provider="provider-a", tool="provider-a::compile")
    b = _provision(contract, provider="provider-b", tool="provider-b::compile")
    request_a = _request(requirement, (b, a))
    request_b = _request(requirement, (a, b))
    lock_a, _ = bind_capabilities(request_a)
    lock_b, _ = bind_capabilities(request_b)
    assert request_a.request_digest == request_b.request_digest
    assert lock_a.model_dump_json() == lock_b.model_dump_json()
    assert lock_a.bindings[0].tool_ref == "provider-a::compile"


def test_binding_filters_side_effect_and_credentials():
    contract = _contract()
    requirement = _requirement(contract, side_effect_ceiling="read-only")
    candidate = _provision(
        contract,
        credential_scope_ids=("admin",),
        side_effect_class="workspace-write",
    )
    with pytest.raises(CapabilityBindingError, match="unsatisfied"):
        bind_capabilities(_request(requirement, (candidate,)))


def test_binding_rejects_provision_from_another_provider_lock():
    contract = _contract()
    requirement = _requirement(contract)
    candidate = _provision(
        contract,
        provider_lock_digest=canonical_digest({"provider-lock": "other"}),
    )
    with pytest.raises(CapabilityBindingError, match="unsatisfied"):
        bind_capabilities(_request(requirement, (candidate,)))


def test_explicit_provider_pin_is_a_hard_constraint():
    contract = _contract()
    requirement = _requirement(contract, explicit_provider_pin="provider-b")
    a = _provision(contract, provider="provider-a", tool="provider-a::compile")
    b = _provision(contract, provider="provider-b", tool="provider-b::compile")
    lock, _ = bind_capabilities(_request(requirement, (a, b)))
    assert lock.bindings[0].provider_id == "provider-b"


def test_unknown_capability_has_no_substring_fallback():
    contract = _contract()
    requirement = _requirement(contract)
    similar = _provision(
        contract,
        tool="provider-a::compile_similar",
        capability_ref="ari.execution.run/v1",
    )
    with pytest.raises(CapabilityBindingError, match="unsatisfied"):
        bind_capabilities(_request(requirement, (similar,)))


def test_bound_authorization_view_enforces_phase_context_and_unbound():
    contract = _contract()
    requirement = _requirement(contract)
    candidate = _provision(contract)
    lock, _ = bind_capabilities(_request(requirement, (candidate,)))
    view = BoundToolAuthorizationView(lock, mode="enforce")
    context = ToolCallContextV1.for_node(
        run_id="run-1", node_id="node-1", phase="bfts"
    )
    assert view.decide(candidate.tool_ref, phase="bfts", context=context).allowed
    assert not view.decide(candidate.tool_ref, phase="paper", context=context).allowed
    assert not view.decide("provider-a::other", phase="bfts", context=context).allowed
    audit = BoundToolAuthorizationView(lock, mode="audit")
    decision = audit.decide("provider-a::other", phase="bfts", context=context)
    assert decision.allowed and decision.audit_only


def test_provider_substitution_reuses_production_binder_and_execution_evidence():
    contract = _contract()
    requirement = _requirement(contract)
    primary = _provision(
        contract,
        provider="provider-a",
        tool="a-provider::compile",
    )
    replacement = _provision(
        contract,
        provider="provider-b",
        tool="b-provider::compile",
    )
    observations = tuple(
        ProviderExecutionObservationV1(
            provider_id=item.provider_id,
            tool_ref=item.tool_ref,
            capability_ref=contract.capability_ref,
            invocation_digest=canonical_digest(
                {"provider": item.provider_id, "input": "fixture"}
            ),
            result_digest=canonical_digest(
                {"provider": item.provider_id, "result": "success"}
            ),
            result_schema="ari.compile-result/v1",
            status="success",
            source_record_count=0,
            source_identity_digest=item.provider_identity_digest,
        )
        for item in (primary, replacement)
    )

    report = probe_provider_substitution(
        _request(requirement, (primary, replacement)),
        capability_ref=contract.capability_ref,
        primary_provider_id="provider-a",
        execution_observations=observations,
    )

    assert report.binding_status == "passed"
    assert report.binding_deterministic is True
    assert report.primary_tool_ref == "a-provider::compile"
    assert report.replacement_provider_id == "provider-b"
    assert report.replacement_tool_ref == "b-provider::compile"
    assert report.execution_status == "passed"
    assert report.report_digest.startswith("sha256:")


def test_provider_substitution_reports_candidate_primary_as_unsatisfied():
    contract = _contract()
    requirement = _requirement(contract)
    candidate = _provision(
        contract,
        provider="provider-a",
        tool="a-provider::compile",
        provider_status="candidate",
    )
    replacement = _provision(
        contract,
        provider="provider-b",
        tool="b-provider::compile",
    )

    report = probe_provider_substitution(
        _request(requirement, (candidate, replacement)),
        capability_ref=contract.capability_ref,
        primary_provider_id="provider-a",
        execution_observations=tuple(
            ProviderExecutionObservationV1(
                provider_id=item.provider_id,
                tool_ref=item.tool_ref,
                capability_ref=contract.capability_ref,
                invocation_digest=canonical_digest({"provider": item.provider_id}),
                result_digest=canonical_digest({"result": item.provider_id}),
                result_schema="ari.compile-result/v1",
                status="success",
                source_record_count=0,
                source_identity_digest=item.provider_identity_digest,
            )
            for item in (candidate, replacement)
        ),
    )

    assert report.binding_status == "unsatisfied"
    assert report.binding_reason_codes == ("provider_not_verified",)
    assert report.replacement_provider_id == "provider-b"
    assert report.execution_status == "passed"


def test_abstraction_probe_passes_when_the_requirement_names_a_capability():
    contract = _contract()
    requirement = _requirement(contract)
    incumbent = _provision(contract)
    request = _request(requirement, [incumbent], mode="audit")

    report = probe_capability_abstraction(request, incumbent_provider_id="provider-a")

    assert report.status == "passed"
    assert report.deterministic is True
    assert report.covered_capability_refs == (contract.capability_ref,)
    assert report.provider_bound_capability_refs == ()
    assert report.disabled_incumbent_tool_refs == (incumbent.tool_ref,)
    assert report.synthetic_provider_id == SYNTHETIC_SUBSTITUTE_PROVIDER_ID
    assert report.baseline_lock_digest != report.substituted_lock_digest


def test_abstraction_probe_fails_when_the_requirement_pins_a_provider():
    """A pinned Provider is exactly the dependency this gate must catch."""

    contract = _contract()
    requirement = _requirement(contract, explicit_provider_pin="provider-a")
    incumbent = _provision(contract)
    request = _request(requirement, [incumbent], mode="audit")

    report = probe_capability_abstraction(request, incumbent_provider_id="provider-a")

    assert report.status == "failed"
    assert report.provider_bound_capability_refs == (contract.capability_ref,)
    assert report.covered_capability_refs == ()


def test_abstraction_probe_is_vacuous_when_the_incumbent_won_nothing():
    contract = _contract()
    requirement = _requirement(contract)
    other = _provision(contract, provider="provider-b", tool="provider-b::compile")
    request = _request(requirement, [other], mode="audit")

    report = probe_capability_abstraction(request, incumbent_provider_id="provider-a")

    assert report.status == "vacuous"
    assert report.covered_capability_refs == ()
    assert report.disabled_incumbent_tool_refs == ()


def test_synthetic_substitute_changes_only_the_provider_identity():
    contract = _contract()
    incumbent = _provision(contract)
    stand_in = synthetic_substitute_provision(incumbent)

    assert stand_in.provider_id == SYNTHETIC_SUBSTITUTE_PROVIDER_ID
    assert stand_in.tool_ref != incumbent.tool_ref
    assert stand_in.provider_identity_digest != incumbent.provider_identity_digest
    for field in (
        "capability_ref",
        "capability_contract_digest",
        "side_effect_class",
        "determinism_class",
        "context_requirement",
        "environment_requirements",
        "resource_type",
        "permissions",
        "roles",
        "phases",
        "credential_scope_ids",
    ):
        assert getattr(stand_in, field) == getattr(incumbent, field)
