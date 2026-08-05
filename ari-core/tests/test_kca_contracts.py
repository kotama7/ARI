"""Contract and layer-separation tests for Tasks 16-18."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ari.assurance.models import (
    VerificationContractV1,
    VerificationRequirementV1,
    VerificationScopeV1,
)
from ari.capability_binding.models import CapabilityContractV1
from ari.knowledge.models import KnowledgeSkillManifestV1
from ari.protocols.integrity import canonical_digest
from ari.providers import (
    CapabilityProviderConfig,
    CapabilityProviderManifest,
    MCPProviderConnection,
    ProviderLock,
)
from ari.config import SkillConfig
from ari.mcp.connection import SkillConnection
from ari.skill_lock import SkillsLockV1
from ari.skill_manifest import SkillManifestV1


SHA = "sha256:" + ("1" * 64)
COMMIT = "1" * 40


def _knowledge_document() -> dict:
    return {
        "schema_version": 1,
        "id": "hpc.gemm.optimization",
        "version": "1.0.0",
        "title": "GEMM Optimization",
        "description": "Procedural guidance",
        "status": "verified",
        "source": {
            "repository": "https://example.invalid/repository",
            "commit": COMMIT,
            "path": "knowledge-skills/hpc.gemm.optimization",
            "body_sha256": SHA,
            "manifest_sha256": SHA,
        },
        "license": {"body": "MIT", "references": "MIT"},
        "applies_to": {"roles": ["generator"], "phases": ["bfts"]},
        "requires": {
            "capabilities": [{"ref": "ari.execution.compile/v1", "required": True}]
        },
        "authority_ceiling": {"side_effects": ["read-only", "workspace-write"]},
        "composition": {"slot": "domain-method", "priority": 100},
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("entrypoint", "src/server.py"),
        ("transport", "stdio"),
        ("command", ["python", "server.py"]),
        ("required_env", ["SECRET"]),
        ("credential_scope", "admin"),
        ("tools", [{"name": "run"}]),
    ],
)
def test_knowledge_manifest_rejects_execution_fields(field, value):
    document = _knowledge_document()
    document[field] = value
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        KnowledgeSkillManifestV1.model_validate(document)


def test_provider_compatibility_aliases_are_same_objects():
    assert CapabilityProviderManifest is SkillManifestV1
    assert CapabilityProviderConfig is SkillConfig
    assert MCPProviderConnection is SkillConnection
    assert ProviderLock is SkillsLockV1


def test_capability_contract_is_mint_once_and_semantic():
    contract = CapabilityContractV1.create(
        capability_ref="ari.execution.compile/v1",
        contract_version="v1",
        title="Compile",
        description="Compile a source artifact",
        side_effect_class="workspace-write",
        determinism_class="conditional",
        compatibility_rules=("json-schema-structural-conformance",),
    )
    assert contract.contract_digest.startswith("sha256:")
    assert len(contract.contract_digest) == 71
    tampered = contract.model_dump(mode="json")
    tampered["title"] = "Changed"
    with pytest.raises(ValidationError, match="contract_digest"):
        CapabilityContractV1.model_validate(tampered)


def test_verification_contract_is_independent_from_metric_correctness():
    requirement = VerificationRequirementV1.create(
        property_id="numerical-equivalence",
        target_kind="shared-library",
        required_methods=("differential-testing",),
        required_tier="screen",
        failure_policy="exclude-from-scientific-frontier",
        scope=VerificationScopeV1(values={"dtype": ("float64",)}),
        tolerance_policy_ref="hpc.float64/v1",
        tolerance_policy_digest=SHA,
        source_requirement_refs=("research:metric",),
    )
    contract = VerificationContractV1.create(
        run_id="run-1",
        research_contract_digest=SHA,
        requirements=(requirement,),
        admission_confidence=1.0,
        property_vocabulary_digest=SHA,
    )
    document = contract.model_dump(mode="json")
    assert "harness_id" not in json.dumps(document)
    assert contract.contract_digest == canonical_digest(
        contract.model_dump(mode="json", exclude={"contract_digest"})
    )


def test_low_confidence_verification_contract_requires_human_review():
    with pytest.raises(ValidationError, match="human review"):
        VerificationContractV1.create(
            run_id="run-1",
            research_contract_digest=SHA,
            requirements=(),
            admission_confidence=0.2,
            property_vocabulary_digest=SHA,
        )
