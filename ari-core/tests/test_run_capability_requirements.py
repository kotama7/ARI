"""A run can require a capability no Knowledge Skill happens to mention.

Knowledge was the only requirement source, so a domain instrument could hold a
contract, a reviewed supplier, admitted evidence, and a proven invocation path
and still never be asked for by a production run. These cover the operator
declaration that closes that, and the ways it deliberately refuses to become a
discovery channel.
"""

from __future__ import annotations

import pytest

from ari.capability_binding.models import (
    CapabilityContractV1,
    CapabilityOntologySnapshotV1,
    CapabilityRequirementV1,
)
from ari.config import CapabilityBindingRuntimeConfig
from ari.rqgm.admission_builder import _run_capability_requirements


def _contract(ref="ari.eda.openroad.place-route/v1", **updates):
    values = dict(
        capability_ref=ref,
        contract_version="v1",
        title="Place and route",
        description="Place and route a netlist",
        side_effect_class="workspace-write",
        determinism_class="conditional",
        context_requirement="node",
        required_permissions=("workspace-write",),
        resource_type="eda-cpu",
        environment_requirements=("sif-container-runtime",),
        compatibility_rules=("schema",),
    )
    values.update(updates)
    return CapabilityContractV1.create(**values)


def _ontology(*contracts):
    return CapabilityOntologySnapshotV1.create(
        source_revision="test/1",
        property_vocabulary_version="v1",
        contracts=tuple(sorted(contracts, key=lambda item: item.capability_ref)),
    )


class _Cfg:
    def __init__(self, **kwargs):
        self.capability_binding = CapabilityBindingRuntimeConfig(**kwargs)


class _KnowledgeLock:
    def __init__(self, requirements):
        self.capability_requirements = tuple(requirements)


def _knowledge_requirement(contract, **updates):
    values = dict(
        capability_ref=contract.capability_ref,
        capability_contract_digest=contract.contract_digest,
        context_requirement=contract.context_requirement,
        side_effect_ceiling="read-only",
        source_requirement_refs=("knowledge:some-skill",),
    )
    values.update(updates)
    return CapabilityRequirementV1.create(**values)


def test_a_declared_capability_becomes_a_requirement():
    contract = _contract()
    requirements = _run_capability_requirements(
        _Cfg(mode="enforce", required_capability_refs=[contract.capability_ref]),
        _ontology(contract),
        None,
    )
    (requirement,) = requirements
    assert requirement.capability_ref == contract.capability_ref
    assert requirement.required is True
    assert requirement.source_requirement_refs == (
        f"config:capability_binding/{contract.capability_ref}",
    )
    # The contract, not the declaration, fixes what the capability costs.
    assert requirement.side_effect_ceiling == contract.side_effect_class
    assert requirement.resource_types == (contract.resource_type,)
    assert requirement.environment_requirements == contract.environment_requirements


def test_an_optional_capability_is_not_required():
    contract = _contract()
    (requirement,) = _run_capability_requirements(
        _Cfg(mode="audit", optional_capability_refs=[contract.capability_ref]),
        _ontology(contract),
        None,
    )
    assert requirement.required is False


def test_an_unknown_capability_is_refused_not_ignored():
    with pytest.raises(ValueError, match="unknown capability"):
        _run_capability_requirements(
            _Cfg(mode="enforce", required_capability_refs=["ari.eda.nonexistent/v1"]),
            _ontology(_contract()),
            None,
        )


def test_knowledge_requirements_are_preserved_alongside_declared_ones():
    eda = _contract()
    compile_ = _contract(
        ref="ari.execution.compile/v1",
        side_effect_class="workspace-write",
        resource_type="process",
        environment_requirements=(),
    )
    lock = _KnowledgeLock([_knowledge_requirement(compile_)])
    requirements = _run_capability_requirements(
        _Cfg(mode="enforce", required_capability_refs=[eda.capability_ref]),
        _ontology(eda, compile_),
        lock,
    )
    assert {item.capability_ref for item in requirements} == {
        "ari.eda.openroad.place-route/v1",
        "ari.execution.compile/v1",
    }


def test_a_declaration_cannot_relax_a_knowledge_requirement():
    """Both survive; the Skill's stricter one is never replaced."""

    contract = _contract()
    strict = _knowledge_requirement(contract, side_effect_ceiling="read-only")
    requirements = _run_capability_requirements(
        _Cfg(mode="enforce", required_capability_refs=[contract.capability_ref]),
        _ontology(contract),
        _KnowledgeLock([strict]),
    )
    assert strict.requirement_digest in {
        item.requirement_digest for item in requirements
    }
    assert any(item.side_effect_ceiling == "read-only" for item in requirements)


def test_no_declaration_leaves_the_knowledge_requirements_untouched():
    contract = _contract()
    strict = _knowledge_requirement(contract)
    requirements = _run_capability_requirements(
        _Cfg(mode="enforce"), _ontology(contract), _KnowledgeLock([strict])
    )
    assert requirements == (strict,)


def test_requirements_are_deterministically_ordered():
    a = _contract(ref="ari.aaa.first/v1", resource_type="process",
                  environment_requirements=())
    b = _contract(ref="ari.zzz.last/v1", resource_type="process",
                  environment_requirements=())
    forward = _run_capability_requirements(
        _Cfg(mode="enforce", required_capability_refs=[a.capability_ref, b.capability_ref]),
        _ontology(a, b),
        None,
    )
    reverse = _run_capability_requirements(
        _Cfg(mode="enforce", required_capability_refs=[b.capability_ref, a.capability_ref]),
        _ontology(a, b),
        None,
    )
    assert [item.capability_ref for item in forward] == [
        "ari.aaa.first/v1",
        "ari.zzz.last/v1",
    ]
    assert forward == reverse


def test_a_required_capability_forbids_legacy_binding_mode():
    """The interlock existed; nothing had ever given it the signal."""

    from ari.config.kca_runtime import KCAAdmissionConfigError, resolve_kca_modes

    class Config:
        capability_binding = CapabilityBindingRuntimeConfig(mode="legacy")

        class knowledge:
            mode = "off"

        class assurance:
            mode = "off"

        class ari:
            mode = "ari_rqgm"

        class rqgm:
            enabled = False

    with pytest.raises(KCAAdmissionConfigError, match="required capability"):
        resolve_kca_modes(Config(), required_capability=True)
