"""The broker-to-binder bridge: composite provisions and what they refuse."""

from __future__ import annotations

import json

import pytest

from ari.capability_binding.models import (
    CapabilityBindingRequestV1,
    CapabilityContractV1,
    CapabilityRequirementV1,
)
from ari.capability_binding.resolver import bind_capabilities
from ari.protocols.integrity import canonical_digest
from ari.protocols.scientific_requirements import EnvironmentSnapshotV1
from ari.providers.brokered import (
    BrokerDispatchV1,
    BrokeredCatalogError,
    brokered_catalog_digest,
    build_brokered_provisions,
    load_brokered_catalog,
)


SHA = "sha256:" + ("3" * 64)
POLICY = "sha256:" + ("4" * 64)
LEAF = "tool:openroad::place_route@1"


def _contract(**updates):
    values = dict(
        capability_ref="ari.eda.place-route/v1",
        contract_version="v1",
        title="Place and route",
        description="Place and route a netlist",
        side_effect_class="workspace-write",
        determinism_class="conditional",
        context_requirement="none",
        required_permissions=("workspace-write",),
        compatibility_rules=("schema",),
    )
    values.update(updates)
    return CapabilityContractV1.create(**values)


def _ontology(*contracts):
    from ari.capability_binding.models import CapabilityOntologySnapshotV1

    return CapabilityOntologySnapshotV1.create(
        source_revision="test/1",
        property_vocabulary_version="v1",
        contracts=tuple(sorted(contracts, key=lambda item: item.capability_ref)),
    )


def _descriptor(**updates):
    values = dict(
        schema_version="ari.tool-descriptor/v1",
        tool_ref=LEAF,
        source_ids=["src-openroad"],
        provider_id="openroad",
        provider_version="2.0",
        provider_digest="sha256:" + ("a" * 64),
        adapter_id="openroad-adapter",
        adapter_version="1.0",
        adapter_digest="sha256:" + ("b" * 64),
        name="place_route",
        provider_tool_name="place_route",
        # The broker's own namespace -- never read as an ARI mapping.
        capability_ref="openroad.place-route",
        leaf_identity="openroad/2.0/place_route",
        origin_chains=[[{"kind": "source", "id": "src-openroad"}]],
        independence_group="openroad",
        side_effects="workspace-write",
        permissions=["workspace-write", "workspace-read"],
        determinism="conditional",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    values.update(updates)
    return values


def _lock(tools, *, sources=None, admissions=None, quarantined=None):
    tools = list(tools)
    if sources is None:
        sources = [
            {
                "source_id": "src-openroad",
                "kind": "openroad",
                "source_digest": "sha256:" + ("c" * 64),
                "provider_id": "openroad",
                "provider_version": "2.0",
                "provider_digest": "sha256:" + ("a" * 64),
                "adapter_id": "openroad-adapter",
                "adapter_version": "1.0",
                "adapter_digest": "sha256:" + ("b" * 64),
            }
        ]
    if admissions is None:
        admissions = [
            {
                "schema_version": "ari.admission-decision/v1",
                "tool_ref": item["tool_ref"],
                "level": "reproducible",
                "required_level": "callable",
                "policy_digest": POLICY,
                "evidence_digest": "sha256:" + ("d" * 64),
                "reasons": [],
            }
            for item in tools
        ]
    document = {
        "schema_version": "ari.catalog-lock/v1",
        "policy_digest": POLICY,
        "sources": sources,
        "tools": tools,
        "admissions": admissions,
        "quarantined": list(quarantined or ()),
        "overlaps": [],
    }
    document["catalog_digest"] = brokered_catalog_digest(document)
    return document


def _write(tmp_path, document, name="CATALOG.lock"):
    path = tmp_path / name
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    return path


def _dispatch(**updates):
    values = dict(
        provider_id="ari.provider.tool-registry",
        provider_identity_digest=canonical_digest({"provider": "tool-registry"}),
        provider_status="verified",
        tool_ref="tool-registry-skill::invoke@1",
        provider_lock_digest=SHA,
        manifest_digest=SHA,
        registration_report_digest=SHA,
        policy={
            "side_effects": "workspace-write",
            "permissions": ["workspace-write", "workspace-read", "network"],
            "phases": ["bfts"],
            "context_requirement": "none",
        },
        credential_scope_ids=(),
    )
    values.update(updates)
    return BrokerDispatchV1(**values)


def _build(document, *, contract=None, refs=None, dispatch=None):
    contract = contract or _contract()
    return build_brokered_provisions(
        document,
        dispatch=dispatch or _dispatch(),
        ontology=_ontology(contract),
        reviewed_capability_refs_by_leaf=(
            refs if refs is not None else {LEAF: (contract.capability_ref,)}
        ),
    )


# ---------------------------------------------------------------- lock reading


def test_lock_digest_is_recomputed_not_trusted(tmp_path):
    document = _lock([_descriptor()])
    path = _write(tmp_path, document)
    assert load_brokered_catalog(path)["catalog_digest"] == document["catalog_digest"]

    # A leaf swapped after the broker sealed the lock keeps the old digest.
    tampered = dict(document)
    tampered["tools"] = [_descriptor(leaf_identity="openroad/9.9/place_route")]
    _write(tmp_path, tampered, name="tampered.lock")
    with pytest.raises(BrokeredCatalogError, match="digest does not match"):
        load_brokered_catalog(tmp_path / "tampered.lock")


def test_lock_requires_one_admission_per_tool(tmp_path):
    document = _lock([_descriptor()], admissions=[])
    document["catalog_digest"] = brokered_catalog_digest(document)
    _write(tmp_path, document)
    with pytest.raises(BrokeredCatalogError, match="one admission per tool"):
        load_brokered_catalog(tmp_path / "CATALOG.lock")


def test_lock_refuses_admission_decided_under_another_policy(tmp_path):
    document = _lock([_descriptor()])
    document["admissions"][0]["policy_digest"] = "sha256:" + ("9" * 64)
    document["catalog_digest"] = brokered_catalog_digest(document)
    _write(tmp_path, document)
    with pytest.raises(BrokeredCatalogError, match="different policy"):
        load_brokered_catalog(tmp_path / "CATALOG.lock")


def test_empty_shipped_broker_lock_authenticates():
    """The checked-in lock is empty, but it must still verify as itself."""

    from ari.config.finder import package_config_root

    path = package_config_root().parents[1] / "ari-skill-tool-registry" / "CATALOG.lock"
    if not path.is_file():  # pragma: no cover - broker package not checked out
        pytest.skip("broker package is absent from this checkout")
    document = load_brokered_catalog(path)
    assert document["tools"] == []


# ------------------------------------------------------------------- composite


def test_composite_carries_dispatch_and_subject_identity():
    contract = _contract()
    (provision,) = _build(_lock([_descriptor()]), contract=contract)
    assert provision.tool_ref == "tool-registry-skill::invoke@1"
    assert provision.dispatch_tool_ref == "tool-registry-skill::invoke@1"
    assert provision.subject_tool_ref == LEAF
    assert provision.nested_source_lock_digests == ("sha256:" + "c" * 64,)
    # The reviewed table decides the ARI capability; the broker's own
    # capability_ref is recorded only so drift is visible.
    assert provision.capability_ref == "ari.eda.place-route/v1"
    assert provision.declared_capability_ref == "openroad.place-route"


def test_composite_identity_separates_two_leaves_of_one_broker():
    other = _descriptor(
        tool_ref="tool:openroad::route_only@1",
        name="route_only",
        leaf_identity="openroad/2.0/route_only",
    )
    contract = _contract()
    provisions = _build(
        _lock([_descriptor(), other]),
        contract=contract,
        refs={
            LEAF: (contract.capability_ref,),
            "tool:openroad::route_only@1": (contract.capability_ref,),
        },
    )
    assert len(provisions) == 2
    assert len({item.provider_identity_digest for item in provisions}) == 2
    assert len({item.tool_ref for item in provisions}) == 1


def test_reproducibility_is_capped_by_admission_level():
    document = _lock([_descriptor(determinism="deterministic")])
    (provision,) = _build(document)
    # determinism alone would say "exact"; the leaf only reached "reproducible".
    assert provision.reproducibility_grade == "bounded"

    document = _lock([_descriptor(determinism="deterministic")])
    document["admissions"][0]["level"] = "scientifically_admitted"
    document["catalog_digest"] = brokered_catalog_digest(document)
    (promoted,) = _build(document)
    assert promoted.reproducibility_grade == "exact"


def test_seeded_leaf_is_conditional_not_deterministic():
    (provision,) = _build(_lock([_descriptor(determinism="seeded")]))
    assert provision.determinism_class == "conditional"


# -------------------------------------------------------------------- refusals


def test_leaf_below_its_required_admission_level_is_refused():
    document = _lock([_descriptor()])
    document["admissions"][0]["level"] = "discovered"
    document["admissions"][0]["required_level"] = "reproducible"
    document["catalog_digest"] = brokered_catalog_digest(document)
    with pytest.raises(BrokeredCatalogError, match="below its required level"):
        _build(document)


def test_side_effect_is_the_envelope_of_both_hops():
    """A read-only leaf behind a workspace-write broker is not read-only."""

    contract = _contract(
        capability_ref="ari.eda.inspect/v1",
        side_effect_class="read-only",
        required_permissions=("workspace-read",),
    )
    document = _lock(
        [_descriptor(side_effects="read-only", permissions=["workspace-read"])]
    )
    with pytest.raises(BrokeredCatalogError, match="side-effect classification"):
        _build(document, contract=contract)

    # The same leaf does supply a workspace-write capability, because that is
    # what the route as a whole costs.
    envelope = _contract(
        capability_ref="ari.eda.inspect/v1", required_permissions=("workspace-read",)
    )
    (provision,) = _build(document, contract=envelope)
    assert provision.side_effect_class == "workspace-write"


def test_both_hops_must_grant_the_contract_permissions():
    """The leaf submits jobs; the broker the runtime actually gates does not."""

    contract = _contract(
        side_effect_class="scheduler-submit",
        required_permissions=("scheduler-submit",),
    )
    document = _lock(
        [
            _descriptor(
                side_effects="stateful",
                permissions=["scheduler", "workspace-write"],
            )
        ]
    )
    with pytest.raises(BrokeredCatalogError, match="does not grant"):
        _build(document, contract=contract)

    # Grant it on the dispatch tool too and the same leaf supplies it.
    (provision,) = _build(
        document,
        contract=contract,
        dispatch=_dispatch(
            policy={
                "side_effects": "stateful",
                "permissions": ["scheduler", "workspace-write"],
                "phases": ["bfts"],
                "context_requirement": "none",
            }
        ),
    )
    assert provision.side_effect_class == "scheduler-submit"
    assert "scheduler-submit" in provision.permissions


def test_unknown_capability_in_the_reviewed_table_is_refused():
    with pytest.raises(BrokeredCatalogError, match="unknown capability"):
        _build(_lock([_descriptor()]), refs={LEAF: ("ari.eda.nonexistent/v1",)})


def test_reviewed_leaf_absent_from_the_catalog_is_refused():
    """Stale review must fail loudly, not silently unsupply a capability."""

    contract = _contract()
    with pytest.raises(BrokeredCatalogError, match="absent from the catalog"):
        _build(
            _lock([_descriptor()]),
            contract=contract,
            refs={"tool:openroad::gone@1": (contract.capability_ref,)},
        )


def test_quarantined_leaf_is_refused():
    document = _lock(
        [_descriptor()],
        quarantined=[
            {
                "source_id": "src-openroad",
                "candidate_name": "place_route",
                "reason_code": "provider-drift",
                "detail": "provider digest changed",
                "candidate_digest": "sha256:" + ("e" * 64),
            }
        ],
    )
    with pytest.raises(BrokeredCatalogError, match="quarantined"):
        _build(document)


def test_candidate_broker_yields_candidate_provisions():
    """A broker ARI has not verified cannot launder a leaf into verified."""

    (provision,) = _build(
        _lock([_descriptor()]), dispatch=_dispatch(provider_status="candidate")
    )
    assert provision.provider_status == "candidate"


# ---------------------------------------------------------------- through bind


def _requirement(contract, **updates):
    values = dict(
        capability_ref=contract.capability_ref,
        capability_contract_digest=contract.contract_digest,
        phases=("bfts",),
        side_effect_ceiling="workspace-write",
        source_requirement_refs=("knowledge:fixture",),
    )
    values.update(updates)
    return CapabilityRequirementV1.create(**values)


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
        available_tool_refs=tuple({item.tool_ref for item in provisions}),
        role="generator",
        phase="bfts",
        call_context="node",
        authorized_capability_refs=(requirement.capability_ref,),
        environment=EnvironmentSnapshotV1.create(resource_types=("process",)),
        mode="enforce",
    )
    values.update(updates)
    return CapabilityBindingRequestV1.create(**values)


def test_composite_binds_and_the_lock_records_the_route():
    contract = _contract()
    (provision,) = _build(_lock([_descriptor()]), contract=contract)
    lock, _ = bind_capabilities(_request(_requirement(contract), (provision,)))
    (binding,) = lock.bindings
    assert binding.tool_ref == "tool-registry-skill::invoke@1"
    assert binding.dispatch_tool_ref == "tool-registry-skill::invoke@1"
    assert binding.subject_tool_ref == LEAF


def test_two_composites_tie_break_on_the_leaf_not_the_digest():
    contract = _contract()
    other = _descriptor(
        tool_ref="tool:openroad::aaa_route@1",
        name="aaa_route",
        leaf_identity="openroad/2.0/aaa_route",
    )
    provisions = _build(
        _lock([_descriptor(), other]),
        contract=contract,
        refs={
            LEAF: (contract.capability_ref,),
            "tool:openroad::aaa_route@1": (contract.capability_ref,),
        },
    )
    requirement = _requirement(contract)
    forward, _ = bind_capabilities(_request(requirement, provisions))
    reverse, _ = bind_capabilities(_request(requirement, tuple(reversed(provisions))))
    assert forward.bindings[0].subject_tool_ref == "tool:openroad::aaa_route@1"
    assert forward.model_dump_json() == reverse.model_dump_json()


# ----------------------------------------------------- through the real loader


def _broker_package():
    from ari.config.finder import package_config_root

    return package_config_root().parents[1] / "ari-skill-tool-registry"


def _provider_lock(manifest, *, run_id="run-1"):
    """A run lock exposing the broker's real ``invoke`` tool."""

    from ari.skill_lock import LockedSkillV1, LockedToolV1, SkillsLockV1
    from ari.skill_manifest import manifest_digest

    invoke = next(item for item in manifest.resolved_tools() if item.name == "invoke")
    tool = LockedToolV1(
        tool_ref="tool-registry-skill::invoke@1",
        name="invoke",
        skill_name="tool-registry-skill",
        capability_ref=invoke.capability_ref,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        input_schema_digest=canonical_digest({"type": "object"}),
        output_schema_digest=canonical_digest({"type": "object"}),
        policy={
            "side_effects": invoke.side_effects,
            "permissions": list(invoke.permissions),
            "phases": list(invoke.phases),
            "determinism": invoke.determinism,
            "context_requirement": invoke.context_requirement,
        },
    )
    skill = LockedSkillV1(
        name="tool-registry-skill",
        package=manifest.package,
        version=manifest.version,
        entrypoint="python -m server",
        manifest_digest="sha256:" + manifest_digest(manifest),
        provider_digest=canonical_digest({"provider": "tool-registry-skill"}),
        configured_phases=["bfts"],
        environment_policy="complete",
        tool_refs=[tool.tool_ref],
    )
    return SkillsLockV1(
        run_id=run_id,
        registry_digest=canonical_digest({"registry": "test"}),
        skills=[skill],
        tools=[tool],
        phase_active_tools={"bfts": [tool.tool_ref]},
    )


def _catalog_yaml(tmp_path, manifest, *, brokered):
    import yaml

    from ari.skill_manifest import manifest_digest

    document = {
        "schema_version": 1,
        "catalog_source_revision": "test/1",
        "entries": [
            {
                "provider_id": "ari.provider.tool-registry",
                "runtime_name": "tool-registry-skill",
                "package": manifest.package,
                "package_version": manifest.version,
                "status": "verified",
                "maintainer": "ARI maintainers",
                "source": {
                    "repository": "https://github.com/kotama7/ARI.git",
                    "full_commit_sha": "0" * 40,
                    "package_sha256": "sha256:" + ("f" * 64),
                    "license": "MIT",
                },
                "manifest_sha256": "sha256:" + manifest_digest(manifest),
                "declared_capability_refs_by_tool": {},
                "brokered": brokered,
            }
        ],
    }
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")
    return path


def _load(
    tmp_path,
    *,
    refs,
    dispatch_tool="invoke",
    lock_name="CATALOG.lock",
    lifecycle_tools=(),
):
    from ari.config import SkillConfig
    from ari.providers.catalog import load_provider_catalog
    from ari.skill_manifest import load_skill_manifest

    package = _broker_package()
    if not (package / "skill.yaml").is_file():  # pragma: no cover
        pytest.skip("broker package is absent from this checkout")
    manifest_path = str(package / "skill.yaml")
    manifest = load_skill_manifest(manifest_path)
    catalog = _catalog_yaml(
        tmp_path,
        manifest,
        brokered={
            "catalog_lock": lock_name,
            "dispatch_tool": dispatch_tool,
            "lifecycle_tools": list(lifecycle_tools),
            "declared_capability_refs_by_brokered_tool": refs,
        },
    )
    return load_provider_catalog(
        catalog,
        provider_lock=_provider_lock(manifest),
        ontology=_ontology(_contract()),
        configured_skills=(
            SkillConfig(
                name="tool-registry-skill",
                path=str(package),
                package=manifest.package,
                version=manifest.version,
                manifest_path=manifest_path,
            ),
        ),
    )


def test_loader_emits_composites_for_the_real_broker_manifest(tmp_path):
    _write(tmp_path, _lock([_descriptor()]))
    loaded = _load(tmp_path, refs={LEAF: ["ari.eda.place-route/v1"]})
    (provision,) = loaded.provisions
    assert provision.tool_ref == "tool-registry-skill::invoke@1"
    assert provision.subject_tool_ref == LEAF
    assert provision.capability_ref == "ari.eda.place-route/v1"
    # The broker's own invoke is context_requirement: run, and that is the
    # context the runtime will enforce for the whole route.
    assert provision.context_requirement == "run"


def test_loader_binds_the_brokered_lock_into_the_catalog_snapshot(tmp_path):
    document = _lock([_descriptor()])
    _write(tmp_path, document)
    before = _load(tmp_path, refs={LEAF: ["ari.eda.place-route/v1"]})
    assert document["catalog_digest"] in before.snapshot.nested_source_lock_digests

    # Reseal the broker's lock around a different leaf build: the Provider
    # catalog snapshot the binding request pins must move with it.
    reissued = _lock([_descriptor(provider_version="2.1")])
    _write(tmp_path, reissued)
    after = _load(tmp_path, refs={LEAF: ["ari.eda.place-route/v1"]})
    assert after.snapshot.snapshot_digest != before.snapshot.snapshot_digest


def test_loader_refuses_a_dispatch_tool_absent_from_the_run_lock(tmp_path):
    _write(tmp_path, _lock([_descriptor()]))
    with pytest.raises(ValueError, match="dispatch tool is absent"):
        _load(tmp_path, refs={LEAF: ["ari.eda.place-route/v1"]}, dispatch_tool="discover")


def test_loader_refuses_a_missing_brokered_lock(tmp_path):
    with pytest.raises(BrokeredCatalogError, match="regular file"):
        _load(tmp_path, refs={})


def test_the_site_lock_override_wins_over_the_packaged_path(tmp_path, monkeypatch):
    """ARI must read the lock the broker will serve, not the one beside it.

    A site selects its materialized catalog with ARI_TOOL_REGISTRY_LOCK. If ARI
    ignored that and projected the packaged lock, every composite would name a
    leaf the broker is not dispatching -- the provisions would be about a
    different catalog than the calls.
    """

    site = tmp_path / "site"
    site.mkdir()
    _write(site, _lock([_descriptor()]), name="materialized.lock")
    # The path configured in the catalog does not exist at all, so a pass only
    # happens if the override is what was read.
    monkeypatch.setenv("ARI_TOOL_REGISTRY_LOCK", str(site / "materialized.lock"))
    loaded = _load(
        tmp_path, refs={LEAF: ["ari.eda.place-route/v1"]}, lock_name="absent.lock"
    )
    (provision,) = loaded.provisions
    assert provision.subject_tool_ref == LEAF


def test_without_the_override_the_configured_path_is_used(tmp_path, monkeypatch):
    monkeypatch.delenv("ARI_TOOL_REGISTRY_LOCK", raising=False)
    _write(tmp_path, _lock([_descriptor()]))
    loaded = _load(tmp_path, refs={LEAF: ["ari.eda.place-route/v1"]})
    assert loaded.provisions[0].subject_tool_ref == LEAF


# --------------------------------------------------- asynchronous lifecycle


def _async_descriptor(**updates):
    values = _descriptor(
        async_lifecycle={
            "status_tool": "leaf_status",
            "result_tool": "leaf_result",
            "handle_field": "handle_id",
        }
    )
    values.update(updates)
    return values


LIFECYCLE = ("tool-registry-skill::get_result@1", "tool-registry-skill::get_status@1")


def test_an_async_leaf_carries_the_lifecycle_surface():
    """Submitting work the run cannot collect is not a bound capability."""

    contract = _contract()
    (provision,) = _build(
        _lock([_async_descriptor()]),
        contract=contract,
        dispatch=_dispatch(lifecycle_tool_refs=LIFECYCLE),
    )
    assert provision.lifecycle_tool_refs == LIFECYCLE


def test_a_synchronous_leaf_gets_no_lifecycle_surface():
    """A leaf with no job to poll must not widen the run's authority."""

    (provision,) = _build(
        _lock([_descriptor()]), dispatch=_dispatch(lifecycle_tool_refs=LIFECYCLE)
    )
    assert provision.lifecycle_tool_refs == ()


def test_the_authorization_view_admits_the_bound_lifecycle_tools():
    from ari.call_context import ToolCallContextV1
    from ari.capability_binding.validation import BoundToolAuthorizationView

    contract = _contract()
    (provision,) = _build(
        _lock([_async_descriptor()]),
        contract=contract,
        dispatch=_dispatch(lifecycle_tool_refs=LIFECYCLE),
    )
    lock, _ = bind_capabilities(_request(_requirement(contract), (provision,)))
    view = BoundToolAuthorizationView(lock, mode="enforce")
    context = ToolCallContextV1.for_node(run_id="run-1", node_id="n1", phase="bfts")
    for ref in ("tool-registry-skill::invoke@1", *LIFECYCLE):
        decision = view.decide(ref, phase="bfts", context=context)
        assert decision.allowed, ref
        assert decision.reason_code == "bound"
    denied = view.decide(
        "tool-registry-skill::describe@1", phase="bfts", context=context
    )
    assert not denied.allowed
    assert denied.reason_code == "unbound_tool"


def test_lifecycle_tools_inherit_the_binding_phase_not_a_wider_one():
    from ari.call_context import ToolCallContextV1
    from ari.capability_binding.validation import BoundToolAuthorizationView

    contract = _contract()
    (provision,) = _build(
        _lock([_async_descriptor()]),
        contract=contract,
        dispatch=_dispatch(lifecycle_tool_refs=LIFECYCLE),
    )
    lock, _ = bind_capabilities(_request(_requirement(contract), (provision,)))
    view = BoundToolAuthorizationView(lock, mode="enforce")
    context = ToolCallContextV1.for_node(run_id="run-1", node_id="n1", phase="paper")
    decision = view.decide(LIFECYCLE[0], phase="paper", context=context)
    assert not decision.allowed
    assert decision.reason_code == "binding_phase_mismatch"


def test_loader_refuses_lifecycle_tools_absent_from_the_run_lock(tmp_path):
    _write(tmp_path, _lock([_async_descriptor()]))
    with pytest.raises(ValueError, match="lifecycle tools are absent"):
        _load(
            tmp_path,
            refs={LEAF: ["ari.eda.place-route/v1"]},
            lifecycle_tools=["get_status", "no_such_tool"],
        )
