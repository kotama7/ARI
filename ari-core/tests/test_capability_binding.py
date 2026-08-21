from __future__ import annotations

import json

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


def test_binding_lock_determinism():
    """Task 20 criterion 17: one requirement, snapshot and environment mint one
    Binding Lock, byte for byte.

    Stated as invariance under the one input a caller can vary without changing
    the question -- the order the candidate provisions arrive in.  The request
    digest is asserted equal first, so the Lock comparison below is about the
    binder and not about two different requests.
    """

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


# ------------------------------------------------------- compatibility rules


def test_the_shipped_ontology_names_only_reviewed_compatibility_rules():
    """The field was free-form and read by nothing; every name was inert."""

    from ari.capability_binding.ontology import (
        compatibility_rule_enforcement,
        load_capability_ontology,
    )
    from ari.config.finder import package_config_root

    ontology = load_capability_ontology(
        package_config_root() / "capabilities" / "ontology.yaml"
    )
    for item in ontology.snapshot.contracts:
        # Legitimately empty for three contracts: their only named rule was
        # json-schema-structural-conformance, retired because it named a
        # relation to a capability-side structure no contract states.
        for rule in item.compatibility_rules:
            assert compatibility_rule_enforcement(rule) in {
                "core",
                "provider",
                "unenforced",
            }


def test_an_invented_compatibility_rule_is_refused():
    from ari.capability_binding.ontology import (
        CapabilityOntologyError,
        compatibility_rule_enforcement,
    )

    with pytest.raises(CapabilityOntologyError, match="unknown compatibility rule"):
        compatibility_rule_enforcement("looks-plausible-v1")


def test_measurement_envelope_requires_the_conditions_it_promises(tmp_path):
    """A measurement rule on a contract that names no conditions is empty."""

    import yaml

    from ari.capability_binding.ontology import (
        CapabilityOntologyError,
        load_capability_ontology,
    )

    document = {
        "schema_version": 1,
        "source_revision": "test/1",
        "property_vocabulary_version": "v1",
        "contracts": [
            {
                "capability_ref": "ari.execution.measure/v1",
                "contract_version": "v1",
                "title": "Measure",
                "description": "Measure something",
                "side_effect_class": "read-only",
                "determinism_class": "conditional",
                "compatibility_rules": [
                    "measurement-envelope-v1",
                ],
            }
        ],
    }
    path = tmp_path / "ontology.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(CapabilityOntologyError, match="no nondeterminism_fields"):
        load_capability_ontology(path)

    document["contracts"][0]["nondeterminism_fields"] = ["hardware", "sampling"]
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    ontology = load_capability_ontology(path)
    assert ontology.snapshot.contracts[0].nondeterminism_fields == (
        "hardware",
        "sampling",
    )


def test_bound_tool_refs_includes_the_lifecycle_surface():
    """The governance path and the authorization view must agree.

    The view admits a binding's lifecycle tools; this projection is what the
    run's audit, the adversarial engine, and the capability kernel compare
    invocations against. Projecting tool_ref alone meant every legal poll of an
    asynchronous subject was scored as an invocation of an unbound tool.
    """

    from ari.capability_binding.resolver import bound_tool_refs

    contract = _contract()
    provision = _provision(
        contract,
        lifecycle_tool_refs=("prov::get_result@1", "prov::get_status@1"),
    )
    lock, _ = bind_capabilities(_request(_requirement(contract), (provision,)))
    assert bound_tool_refs(lock) == {
        "provider-a::compile",
        "prov::get_result@1",
        "prov::get_status@1",
    }


def test_a_synchronous_binding_contributes_only_its_own_ref():
    from ari.capability_binding.resolver import bound_tool_refs

    contract = _contract()
    lock, _ = bind_capabilities(
        _request(_requirement(contract), (_provision(contract),))
    )
    assert bound_tool_refs(lock) == {"provider-a::compile"}


# ── plan 20 §8.2 criteria 16 and 20 ──────────────────────────────────────────
#
# Both criteria name a behaviour that must be impossible, and the kernel rule
# that would report criterion 20 (CK-CAP-013, `used_name_inference`) has no
# producer anywhere in this repository. Reading the authority path explains
# why: nothing can produce it, because every step that turns a requested name
# into authority is an exact-equality lookup. These tests pin that -- they go
# red the moment a substring, prefix or case-folding fallback is introduced,
# which is the only way the rule could ever acquire a producer.


def _identity_variants(identity: str, known: set[str]) -> tuple[str, ...]:
    """Names a substring-inferring resolver would accept for *identity*.

    Proper substrings, proper superstrings and a case fold: the shapes
    tool-name inference matches and exact binding must refuse. Anything that
    is itself a registered identity in *known* is dropped -- a bare tool name
    is a substring of its own immutable ref, and resolving it is exact
    matching, not inference.
    """

    head = identity.split("@", 1)[0]
    candidates = (
        identity[:-1],
        identity[1:],
        head,
        head.rsplit("/", 1)[-1],
        head.rsplit("::", 1)[-1],
        identity + "_extra",
        "shadow-" + identity,
        identity.upper(),
    )
    variants = tuple(
        dict.fromkeys(item for item in candidates if item and item not in known)
    )
    # A for-loop guard over an empty corpus passes vacuously; refuse that.
    assert variants, identity
    return variants


class _NameInferenceConnection:
    """One provider exposing one tool with a substring-rich name."""

    def __init__(self, skill):
        self.skill = skill
        self.calls: list[tuple[str, dict]] = []

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "compile_source",
                "description": "fixture",
                "inputSchema": {"type": "object"},
                "skill_name": self.skill.name,
            }
        ]

    def call_tool(self, name: str, args: dict, timeout: int) -> dict:
        self.calls.append((name, dict(args)))
        return {"result": "ok"}

    def close(self) -> None:
        pass


def _name_inference_skill():
    from ari.config import SkillConfig

    return SkillConfig(
        name="fixture-skill",
        package="ari-skill-fixture",
        version="1.0.0",
        path="/nonexistent/fixture",
        tool_policies={
            "compile_source": {"phases": ["bfts"], "side_effects": "read-only"}
        },
    )


def test_enforce_no_substring_policy(monkeypatch):
    """Criterion 20: authority never uses tool-name substring inference.

    Not "the producer emits False" -- there is no producer, and this test says
    why. Authority is reached through three resolution steps, and all three are
    exact-equality lookups on an identity:

    * `resolve_registration` matches a request against `tool_ref_registry` /
      `tool_registry` by dict membership, so its whole outcome vocabulary is
      {immutable-tool-ref, unique-bare-alias, unresolved} -- exact, exact,
      refuse. There is no fuzzy branch for a fourth value to come from.
    * `BoundToolAuthorizationView.decide` looks the resolved ref up in the
      Binding Lock's `_by_tool` table, again by dict membership.
    * the composite gate compares the leaf named in the call's arguments
      against `subject_tool_ref` by dict membership too -- the place a
      federated broker would be tempted to match leaves by name.

    Each is driven here with proper substrings, proper superstrings and a case
    fold of a real identity. Introduce inference at any of the three and the
    corresponding block goes red.
    """

    from ari.mcp.client import MCPClient

    # ── 1. registration resolution, through the production dispatch path ──
    skill = _name_inference_skill()
    connection = _NameInferenceConnection(skill)
    probe = MCPClient([skill])
    monkeypatch.setattr(probe, "_init_connection", lambda _skill: connection)
    descriptor = probe.list_tools()[0]
    tool_ref, tool_name = descriptor["tool_ref"], descriptor["name"]

    contract = _contract()
    requirement = _requirement(contract)
    lock, _ = bind_capabilities(
        _request(_requirement(contract), (_provision(contract, tool=tool_ref),))
    )
    view = BoundToolAuthorizationView(lock, mode="enforce")

    client = MCPClient([skill], tool_authorization_view=view)
    monkeypatch.setattr(client, "_init_connection", lambda _skill: connection)
    context = ToolCallContextV1.for_node(
        run_id="run-1", node_id="node-1", phase="bfts"
    )

    # The two exact identities resolve, and say by which exact identity.
    admitted = client.call_tool_envelope(tool_ref, {"q": 1}, context=context)
    assert admitted.status == "ok"
    assert admitted.provenance.selection_reason == "immutable-tool-ref"
    aliased = client.call_tool_envelope(tool_name, {"q": 1}, context=context)
    assert aliased.status == "ok"
    assert aliased.provenance.selection_reason == "unique-bare-alias"
    dispatched = len(connection.calls)

    identities = {tool_ref, tool_name}
    for requested in (
        *_identity_variants(tool_ref, identities),
        *_identity_variants(tool_name, identities),
    ):
        envelope = client.call_tool_envelope(requested, {"q": 1}, context=context)
        assert envelope.status == "error", requested
        assert envelope.error is not None and envelope.error.kind == "admission"
        # The reason is the point: resolution refused rather than inferring.
        assert envelope.provenance.selection_reason == "unresolved", requested
    # Nothing that was not an exact identity ever reached the provider.
    assert len(connection.calls) == dispatched
    assert {name for name, _ in connection.calls} == {tool_name}

    # Only the exact identities were recorded as authorised invocations, and
    # both were authorised by the binding rather than by any name match.
    records = view.invocation_records("node-1")
    assert {ref for ref, _reason, _digest in records} == {tool_ref}
    assert {reason for _ref, reason, _digest in records} == {"bound"}

    # ── 2. the Binding Lock authority table itself ────────────────────────
    direct = _provision(contract, tool="provider-a::compile_source")
    direct_lock, _ = bind_capabilities(_request(requirement, (direct,)))
    direct_view = BoundToolAuthorizationView(direct_lock, mode="enforce")
    node_context = ToolCallContextV1.for_node(
        run_id="run-1", node_id="node-1", phase="bfts"
    )
    assert direct_view.decide(
        direct.tool_ref, phase="bfts", context=node_context
    ).allowed
    for requested in _identity_variants(direct.tool_ref, {direct.tool_ref}):
        decision = direct_view.decide(
            requested, phase="bfts", context=node_context
        )
        assert not decision.allowed, requested
        assert decision.reason_code == "unbound_tool", requested

    # ── 3. the composite subject gate a federated broker goes through ─────
    composite = _provision(
        contract,
        tool="broker::call_tool",
        subject_tool_ref="leaf::compile_source",
        dispatch_tool_ref="broker::call_tool",
        subject_argument="name",
        nested_source_lock_digests=(SHA,),
    )
    composite_lock, _ = bind_capabilities(_request(requirement, (composite,)))
    composite_view = BoundToolAuthorizationView(composite_lock, mode="enforce")
    assert composite_view.decide(
        composite.tool_ref,
        phase="bfts",
        context=node_context,
        arguments={"name": composite.subject_tool_ref},
    ).allowed
    for requested in _identity_variants(
        composite.subject_tool_ref, {composite.subject_tool_ref}
    ):
        decision = composite_view.decide(
            composite.tool_ref,
            phase="bfts",
            context=node_context,
            arguments={"name": requested},
        )
        assert not decision.allowed, requested
        assert decision.reason_code == "composite_subject_unbound", requested


def test_generator_binding_lock_denied(tmp_path):
    """Criterion 16: a Generator cannot rewrite the Binding Lock.

    There is no `generator_rewrote_the_lock` signal, and there does not need to
    be one: the Lock is a mint-once digest-bound document whose authorship is
    fixed by its own schema, and every route by which a Generator could reach
    it refuses. This test walks all five, because a guard that covered only the
    in-memory model would miss the one that matters -- a Generator that mints a
    fresh, internally consistent Lock, which no digest check can detect and
    only the epoch pin does.
    """

    from pydantic import ValidationError

    from ari.capability_binding.lock import (
        CapabilityBindingLockError,
        load_binding_lock,
        write_or_verify_binding_lock,
    )
    from ari.capability_binding.models import CapabilityBindingLockV1
    from ari.rqgm.kernel import ConstitutionalKernel
    from ari.rqgm.runtime import RQGMRuntime

    contract = _contract()
    lock, _ = bind_capabilities(
        _request(_requirement(contract), (_provision(contract),))
    )

    # 1. The admitted Lock object is frozen: it cannot be edited in place.
    with pytest.raises(ValidationError, match="frozen"):
        lock.mode = "audit"

    # 2. Its digest covers every other field, so a rewritten payload carrying
    #    the admitted digest is refused at construction.
    forged = lock.model_dump(mode="json")
    forged["mode"] = "audit"
    with pytest.raises(ValidationError, match="lock_digest does not match"):
        CapabilityBindingLockV1.model_validate(forged)

    # 3. Authorship is fixed by the schema, so a Generator cannot even claim
    #    to have produced a Lock: the producer is a literal and the prompt
    #    hash -- the mark of a prompted producer -- must be absent.
    for field, value in (
        ("producer_component_id", "generator_v1"),
        ("prompt_hash", SHA),
    ):
        claimed = lock.model_dump(mode="json")
        claimed[field] = value
        with pytest.raises(ValidationError):
            CapabilityBindingLockV1.model_validate(claimed)

    # 4. On disk the Lock is write-once. Rewriting the identical bytes is
    #    allowed (a resumed run re-derives the same Lock); replacing them with
    #    a different Lock is refused, and so is loading hand-edited bytes.
    path = tmp_path / "capability_binding_lock.json"
    write_or_verify_binding_lock(path, lock)
    assert write_or_verify_binding_lock(path, lock).lock_digest == lock.lock_digest
    rebound, _ = bind_capabilities(
        _request(_requirement(contract), (_provision(contract),), mode="audit")
    )
    assert rebound.lock_digest != lock.lock_digest
    with pytest.raises(CapabilityBindingLockError, match="immutable binding lock"):
        write_or_verify_binding_lock(path, rebound)
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["mode"] = "audit"
    path.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(CapabilityBindingLockError, match="invalid binding lock"):
        load_binding_lock(path)

    # 5. The kernel reports both shapes of rewrite, and stays silent on the
    #    admitted Lock. Tampering breaks the digest (CK-CAP-008); a Generator
    #    that re-mints a consistent Lock keeps the digest valid and is caught
    #    only by the epoch pin (CK-CAP-014), while naming itself as the
    #    selecting actor raises CK-CAP-004 through the production signal.
    kernel = ConstitutionalKernel()
    admitted = lock.model_dump(mode="json")

    def _codes(**kwargs):
        report = kernel.validate_capability_binding_integrity(**kwargs)
        return [item.code for item in report.violations]

    assert _codes(binding_lock=admitted, expected_lock_digest=lock.lock_digest) == []
    assert "CK-CAP-008" in _codes(binding_lock=forged)
    reminted = rebound.model_dump(mode="json")
    assert _codes(binding_lock=reminted) == []  # digest-valid, undetectable alone
    assert "CK-CAP-014" in _codes(
        binding_lock=reminted, expected_lock_digest=lock.lock_digest
    )
    assert "CK-CAP-004" in _codes(binding_lock=admitted, actor_selected=True)

    # The CK-CAP-004 signal is derived from the Lock, not set by a caller:
    # the admitted Lock names the fixed binder, a forged one names its author.
    fixed = RQGMRuntime._FIXED_CAPABILITY_BINDER
    assert RQGMRuntime._lock_selector_component_id(admitted, fixed) == fixed
    assert RQGMRuntime._lock_selector_component_id(
        {**admitted, "producer_component_id": "generator_v1"}, fixed
    ) != fixed
    assert RQGMRuntime._lock_selector_component_id(
        {**admitted, "prompt_hash": SHA}, fixed
    ) != fixed
