"""Acceptance-criteria suite for the K/C/A separation (Task 20 section 8).

Task 20 names ``test_kca_acceptance.py`` as one of its CI suites and gives each
acceptance criterion a required test id.  This module binds the criteria whose
BEHAVIOUR already exists and already refuses, and whose only gap was that
nothing asserted the refusal:

* 5 ``test_provider_satisfies_multiple_skills``
* 44 ``test_evidence_clerk_attestation_validation``
* 56 ``test_revocation_history_append_only``
* 60 ``test_skill_harness_selection_separation``
* 61 ``test_provider_cannot_attest``
* 66 ``test_three_catalog_revocation_append_only``
* 48 ``test_fixed_resolution_purity`` (Resolver + Kernel)
* 14 ``test_knowledge_binder_purity`` (the Knowledge Binder), which the same
  scanner closes because it is the same property over a different module set.
* 31 ``test_generator_harness_mutation_denied``
* 36 ``test_ck_har_tolerance_relaxation``
* 37 ``test_attestation_target_digest``
* 38 ``test_stale_attestation``
* 65 ``test_three_stale_axes``

Each test names the production mechanism it binds, so that deleting the
mechanism turns the test red rather than leaving it vacuously green.
"""

from __future__ import annotations

import ast
import itertools
import json
import typing
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from ari.assurance.attestation import validate_attestation
from ari.assurance.catalog import build_harness_catalog_snapshot
from ari.assurance.lock import write_immutable_harness_lock
from ari.assurance.models import (
    BaselineHarnessLockV1,
    ContainerPinV1,
    HarnessAttestationV1,
    HarnessCatalogSnapshotV1,
    HarnessLockRevisionV1,
    HarnessManifestV1,
    HarnessPropertyCoverageV1,
    HarnessPropertyResultV1,
    HarnessRequirementV1,
    HarnessResourceRequirementsV1,
    HarnessRunRequestV1,
    LockedHarnessV1,
    PinnedHarnessAssetV1,
    VerificationContractV1,
    VerificationRequirementV1,
    VerificationScopeV1,
)
from ari.execution import ExecutionRequestV1, WorkspaceRefV1
from ari.assurance.resolver import (
    HarnessResolutionError,
    resolve_harness_suite,
)
from ari.assurance.suite import (
    assert_monotonic_requirement_revision,
    mint_verification_contract,
    obligations_to_requirements,
)
from ari.capability_binding.models import (
    CapabilityBindingRequestV1,
    CapabilityContractV1,
    CapabilityOntologySnapshotV1,
    CapabilityProvisionV1,
)
from ari.capability_binding.resolver import CapabilityBindingError, bind_capabilities
from ari.knowledge.catalog import (
    GovernedKnowledgeSkillRegistry,
    build_catalog_snapshot,
)
from ari.knowledge.models import (
    KnowledgeAdmissionContextV1,
    KnowledgeAuthorityCeilingV1,
    KnowledgeCapabilityRequirementV1,
    KnowledgeCapabilitySetV1,
    KnowledgeCompositionV1,
    KnowledgeSkillApplicabilityV1,
    KnowledgeSkillEntryV1,
    KnowledgeSkillLicenseV1,
    KnowledgeSkillManifestV1,
    KnowledgeSkillSelectionProposalV1,
    KnowledgeSkillSourceV1,
)
from ari.knowledge.registration_models import KnowledgeSkillPromotionApprovalV1
from ari.knowledge.resolver import admit_knowledge_skills
from ari.protocols.immutable_store import write_once_json
from ari.protocols.integrity import bytes_digest, canonical_digest
from ari.protocols.scientific_requirements import (
    EnvironmentSnapshotV1,
    EvaluationObligationV1,
)
from ari.providers.models import ProviderCatalogEntryV1, ProviderSourceV1
from ari.research_contract import ResearchArtifactRefV1
from ari.rqgm import kernel_rules
from ari.rqgm.governance._evidence import assemble_evidence_bundle
from ari.rqgm.kernel import ConstitutionalKernel


SHA = "sha256:" + "1" * 64
OTHER_SHA = "sha256:" + "3" * 64
BODY = "# Procedure\nUse a compile capability. Never bypass verification.\n"
ATTESTATION_RELATIVE = "rqgm/kca/admission-v1/node_001.attestation.json"


# ── shared fixtures: one real Attestation and its production evidence record ──


def _attestation(**overrides) -> HarnessAttestationV1:
    """One real ``HarnessAttestationV1``, minted the way the fixed verifier does."""

    result = HarnessPropertyResultV1(
        property_id="numerical-equivalence",
        method="differential-testing",
        tier="certify",
        tested_scope=VerificationScopeV1(values={"dtype": ("float64",)}),
        verdict="pass",
        covered_atom_digests=(SHA,),
        evidence_artifact_refs=(),
    )
    values = dict(
        run_id="run-1",
        node_id="node_001",
        epoch_id="epoch_000",
        producer_epoch_id="epoch_000",
        research_contract_digest=SHA,
        verification_contract_digest=SHA,
        knowledge_skill_use_digest=SHA,
        capability_binding_lock_digest=SHA,
        baseline_harness_lock_digest=SHA,
        active_harness_lock_digest=SHA,
        harness_manifest_digest=SHA,
        driver_digest=SHA,
        oracle_digest=SHA,
        dataset_digest=SHA,
        container_digest=SHA,
        target_logical_name="candidate.so",
        target_digest=SHA,
        target_kind="shared-library",
        execution_identity=SHA,
        execution_result_digest=SHA,
        verdict="pass",
        property_results=(result,),
        evidence_artifact_refs=(),
        infrastructure_status="ready",
        nondeterminism_declaration="none",
        nondeterminism_observations=(),
        attempt_id="attempt-1",
        retry_index=0,
    )
    values.update(overrides)
    return HarnessAttestationV1.create(**values)


def _attestation_record(root: Path) -> dict:
    """The ``harness_attestation`` audit record the RQGM runtime appends.

    Field-for-field the payload built in ``ari/rqgm/runtime.py`` when a node's
    ``attestation_refs`` are folded into the epoch audit log: the Attestation
    document flattened into the RQGM envelope, plus the checkpoint-relative
    ``artifact_refs`` entry that carries the file the Clerk re-reads.
    """

    attestation = _attestation()
    document = attestation.model_dump(mode="json")
    path = root / ATTESTATION_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return {
        **{key: value for key, value in document.items() if key != "schema_version"},
        "record_type": "harness_attestation",
        "schema_version": 1,
        "record_id": "har_000001",
        "epoch_id": "epoch_000",
        "component_id": "fixed_verifier_v1",
        "prompt_hash": None,
        "role": "fixed_verifier",
        "created_at": "2026-08-19T00:00:00Z",
        "source_refs": [],
        "artifact_refs": [
            {
                "path": ATTESTATION_RELATIVE,
                "content_digest": canonical_digest(document),
            }
        ],
        "status": attestation.verdict,
        "target_component_id": "generator_v1",
        "target_role": "generator",
        "node_id": "node_001",
        "attestation": document,
        "current_node_target_digest": SHA,
    }


def _bundle(record: dict, root: Path):
    return assemble_evidence_bundle(
        record_id="evb_00001",
        epoch_id="epoch_000",
        clerk_component_id="evidence_clerk_v1",
        target_component_id="generator_v1",
        target_role="generator",
        candidate_refs=[record["record_id"]],
        records_by_id={record["record_id"]: record},
        artifact_root=root,
    )


def _exclusion_reason(record: dict, root: Path) -> str | None:
    bundle = _bundle(record, root)
    if bundle.excluded_items:
        return str(bundle.excluded_items[0]["reason"])
    return None


# ── criterion 44: the Evidence Clerk admits only valid Harness Attestations ──


def test_evidence_clerk_attestation_validation(tmp_path):
    """Every malformation of a ``harness_attestation`` record is excluded with
    its named reason, and the intact record is admitted.

    The mechanism is ``_type_specific_integrity_reason`` /
    ``_harness_integrity_reason`` / ``_artifact_integrity_reason`` in
    ``ari/rqgm/governance/_evidence.py``.  The
    Clerk never raises and never silently drops: an inadmissible item lands in
    ``excluded_items`` with a reason a reader can act on, which is the only way
    "admits ONLY valid Attestations" is checkable after the fact.
    """

    intact = _attestation_record(tmp_path)
    bundle = _bundle(intact, tmp_path)
    assert bundle.excluded_items == ()
    assert [item["kind"] for item in bundle.items] == ["fixed_verifier_result"]
    assert bundle.all_refs_resolved is True

    def mutated(**changes) -> dict:
        record = dict(intact)
        record.update(changes)
        return record

    # Authorship: only the fixed verifier authors an Attestation, and it is
    # never a prompted component.
    assert _exclusion_reason(
        mutated(component_id="tooluniverse_provider_v1"), tmp_path
    ) == "invalid_fixed_verifier_author"
    assert _exclusion_reason(
        mutated(prompt_hash="prompt-abc"), tmp_path
    ) == "prompted_fixed_verifier"

    # Trust anchors: every one of the ten pinned digests must be a full SHA-256.
    for anchor in (
        "attestation_digest",
        "target_digest",
        "verification_contract_digest",
        "baseline_harness_lock_digest",
        "active_harness_lock_digest",
        "harness_manifest_digest",
        "driver_digest",
        "oracle_digest",
        "dataset_digest",
        "container_digest",
    ):
        assert _exclusion_reason(
            mutated(**{anchor: "sha256:abc"}), tmp_path
        ) == "invalid_attestation_digest", anchor

    # Staleness: the Attestation must describe the candidate the node holds now.
    assert _exclusion_reason(
        mutated(current_node_target_digest=OTHER_SHA), tmp_path
    ) == "stale_target_attestation"

    # The embedded Attestation must itself validate against the schema…
    assert _exclusion_reason(mutated(attestation={}), tmp_path) == (
        "malformed_harness_attestation"
    )
    truncated = dict(intact["attestation"])
    truncated.pop("property_results")
    assert _exclusion_reason(mutated(attestation=truncated), tmp_path) == (
        "malformed_harness_attestation"
    )

    # …and it must be the same Attestation the envelope advertises.
    assert _exclusion_reason(mutated(node_id="node_002"), tmp_path) == (
        "attestation_envelope_mismatch"
    )
    assert _exclusion_reason(
        mutated(attestation=_attestation(node_id="node_002").model_dump(mode="json")),
        tmp_path,
    ) == "attestation_envelope_mismatch"

    # The provenance attachment: present, checkpoint-relative, and digest-bound.
    assert _exclusion_reason(mutated(artifact_refs=[]), tmp_path) == (
        "missing_artifact_reference"
    )
    assert _exclusion_reason(
        mutated(
            artifact_refs=[
                {"path": "../escape.json", "content_digest": canonical_digest({})}
            ]
        ),
        tmp_path,
    ) == "invalid_artifact_reference"
    assert _exclusion_reason(
        mutated(
            artifact_refs=[
                {"path": ATTESTATION_RELATIVE, "content_digest": "sha256:abc"}
            ]
        ),
        tmp_path,
    ) == "invalid_artifact_reference"
    assert _exclusion_reason(
        mutated(
            artifact_refs=[{"path": "absent.json", "content_digest": OTHER_SHA}]
        ),
        tmp_path,
    ) == "unresolvable_artifact_reference"
    assert _exclusion_reason(
        mutated(
            artifact_refs=[
                {"path": ATTESTATION_RELATIVE, "content_digest": OTHER_SHA}
            ]
        ),
        tmp_path,
    ) == "artifact_digest_mismatch"

    # The path is refused when it is reached through a symlink, even though the
    # link resolves inside the root and the digest matches.  The intact record
    # above reads the same file by its real path and is admitted, so the only
    # difference here is the link — which is what keeps a later relink from
    # changing what a re-read of the bundle sees.
    linked = tmp_path / "rqgm" / "kca" / "admission-v1" / "linked.json"
    linked.symlink_to(tmp_path / ATTESTATION_RELATIVE)
    assert _exclusion_reason(
        mutated(
            artifact_refs=[
                {
                    "path": "rqgm/kca/admission-v1/linked.json",
                    "content_digest": intact["artifact_refs"][0]["content_digest"],
                }
            ]
        ),
        tmp_path,
    ) == "unsafe_artifact_reference"

    # A ref that is not a mapping at all is excluded rather than raised on: the
    # Clerk reports every inadmissible item, so one malformed ref may not abort
    # the assembly of the bundle the rest of the epoch is judged from.
    assert _exclusion_reason(
        mutated(artifact_refs=[ATTESTATION_RELATIVE]), tmp_path
    ) == "invalid_artifact_reference"

    # A record type outside the closed admissible map is excluded, not coerced.
    assert _exclusion_reason(
        mutated(record_type="harness_attestation_v2"), tmp_path
    ) == "inadmissible_record_type"


# ── criterion 61: a Capability Provider cannot issue a Harness verdict ───────


def test_provider_cannot_attest(tmp_path):
    """No Provider component can author an authoritative Harness verdict.

    Four independent refusals, because a Provider that wanted to attest could
    attack any one of them: the Attestation schema pins its producer, the
    constitutional capability matrix grants ``harness_execution`` to exactly one
    role, the Kernel blocks a foreign-authored Attestation, and the Evidence
    Clerk refuses to carry one into a bundle.
    """

    from ari.rqgm import kernel_rules
    from ari.rqgm.kernel import ConstitutionalKernel

    # 1. The schema: ``producer_component_id`` is a closed literal and the
    #    producer is never prompted.
    with pytest.raises(ValidationError):
        _attestation(producer_component_id="tooluniverse_provider_v1")
    with pytest.raises(ValidationError):
        _attestation(producer_prompt_hash="prompt-abc")

    # 2. The constitution: executing a Harness is a fixed-tier grant held by the
    #    fixed verifier alone.  A Provider's own execution grant is a different
    #    resource class, and no role may write attestations at all.
    holders = {
        key
        for key, grants in kernel_rules.CAPABILITY_MATRIX.items()
        if ("invoke", "harness_execution") in grants
    }
    assert holders == {("fixed_verifier", "fixed")}
    assert not {
        key
        for key, grants in kernel_rules.CAPABILITY_MATRIX.items()
        if any(
            action != "read" and resource == "harness_attestations"
            for action, resource in grants
        )
    }
    assert ("invoke", "harness_execution") not in kernel_rules.CAPABILITY_MATRIX[
        ("generator", "institutional")
    ]

    # 3. The Kernel: a hand-built Attestation naming a Provider producer is a
    #    CK-HAR-014 block even though every digest in it is well formed.
    atom = SHA
    manifest = {"id": "hpc.gemm/v1", "manifest_digest": SHA}
    baseline = {
        "requirements": [{"atom_digest": atom}],
        "harnesses": [
            {
                "harness_id": "hpc.gemm/v1",
                "covered_atom_digests": [atom],
                "manifest_digest": SHA,
                "oracle_digest": SHA,
                "dataset_digest": SHA,
                "driver_digest": SHA,
                "container_digest": SHA,
            }
        ],
        "lock_digest": SHA,
    }
    def sealed(**producer) -> dict:
        """A self-consistent replay Attestation: only the producer varies.

        Sealing matters.  ``CK-HAR-014`` also fires on a digest that does not
        cover its payload, so an unsealed fixture would trip the code for the
        wrong reason and the author branch could be deleted unnoticed.
        """

        document = {
            "node_id": "node_001",
            "producer_component_id": "fixed_verifier_v1",
            "producer_prompt_hash": None,
            "active_harness_lock_digest": SHA,
            "target_digest": SHA,
            "verdict": "pass",
            "property_results": [
                {"tier": "certify", "verdict": "pass", "covered_atom_digests": [atom]}
            ],
        }
        document.update(producer)
        document["attestation_digest"] = canonical_digest(document)
        return document

    def codes(attestation: dict) -> set[str]:
        report = ConstitutionalKernel().validate_harness_integrity(
            verification_contract={"requirements": []},
            baseline_lock=baseline,
            catalog_snapshot={"manifests": [manifest]},
            attestation=attestation,
        )
        return {violation.code for violation in report.violations}

    # The clean control: identical in every respect but the producer.
    assert "CK-HAR-014" not in codes(sealed())
    assert "CK-HAR-014" in codes(
        sealed(producer_component_id="tooluniverse_provider_v1")
    )
    assert "CK-HAR-014" in codes(sealed(producer_prompt_hash="prompt-abc"))

    # 4. The Evidence Clerk: the same record never becomes governance evidence.
    record = _attestation_record(tmp_path)
    record["component_id"] = "tooluniverse_provider_v1"
    record["role"] = "capability_provider"
    assert _exclusion_reason(record, tmp_path) == "invalid_fixed_verifier_author"


# ── criterion 60: Knowledge selection cannot constrain Harness selection ────


def _knowledge_fixture(*, obligations: tuple[EvaluationObligationV1, ...]):
    contract = CapabilityContractV1.create(
        capability_ref="ari.execution.compile/v1",
        contract_version="v1",
        title="Compile",
        description="Compile source",
        side_effect_class="workspace-write",
        determinism_class="conditional",
        context_requirement="node",
        compatibility_rules=("schema",),
    )
    ontology = CapabilityOntologySnapshotV1.create(
        source_revision="test",
        property_vocabulary_version="v1",
        contracts=(contract,),
    )
    body_digest = bytes_digest(BODY.encode())
    manifest = KnowledgeSkillManifestV1(
        id="hpc.gemm.optimization",
        version="1.0.0",
        title="GEMM",
        description="GEMM procedure",
        status="verified",
        source=KnowledgeSkillSourceV1(
            repository="https://example.invalid/knowledge",
            commit="2" * 40,
            path="knowledge-skills/hpc.gemm.optimization",
            body_sha256=body_digest,
            manifest_sha256=SHA,
        ),
        license=KnowledgeSkillLicenseV1(body="MIT", references="MIT"),
        applies_to=KnowledgeSkillApplicabilityV1(
            roles=("generator",), phases=("bfts",), task_tags=("gemm",)
        ),
        requires=KnowledgeCapabilitySetV1(
            capabilities=(
                KnowledgeCapabilityRequirementV1(
                    ref=contract.capability_ref, required=True
                ),
            )
        ),
        evaluation_obligations=obligations,
        authority_ceiling=KnowledgeAuthorityCeilingV1(
            side_effects=("read-only", "workspace-write")
        ),
        composition=KnowledgeCompositionV1(slot="domain-method", priority=100),
    )
    entry = KnowledgeSkillEntryV1.create(
        manifest=manifest,
        body_store_key=body_digest,
        registration_report_digest=SHA,
        importer_version="test/v1",
        status="verified",
    )
    catalog = build_catalog_snapshot(
        catalog_source_revision="test", importer_version="test/v1", entries=(entry,)
    )
    proposal = KnowledgeSkillSelectionProposalV1.create(
        run_id="run-1",
        epoch_id="epoch_000",
        research_contract_digest=SHA,
        proposed=(manifest.exact_ref(),),
        reason="GEMM task",
        router_component_id="proposal_router_v1",
        router_prompt_hash="router-hash",
    )
    context = KnowledgeAdmissionContextV1.create(
        role="generator",
        phase="bfts",
        task_tags=("gemm",),
        permitted_side_effects=("read-only", "workspace-write"),
        property_vocabulary=("numerical-equivalence",),
    )
    return entry, manifest, ontology, catalog, proposal, context


def _baseline_requirement() -> VerificationRequirementV1:
    return VerificationRequirementV1.create(
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


def test_skill_harness_selection_separation():
    """A Knowledge Skill states scientific obligations; it never names a Harness.

    Asserted end to end rather than on an empty contract: a Skill that DOES
    carry an obligation is admitted, the obligation reaches the Verification
    Contract and strengthens it, and no Harness identity appears anywhere along
    the way.  A contract minted from no obligation at all would be silent about
    whether the translation drops Harness identity or never had one to drop.
    """

    obligation = EvaluationObligationV1(
        property_id="numerical-equivalence",
        required_methods=("differential-testing",),
        required_tier="certify",
    )

    # 1. Neither model will even hold a Harness identity: both are closed
    #    schemas, so "the Skill asked for harness X" is unrepresentable.
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EvaluationObligationV1(
            property_id="numerical-equivalence",
            required_methods=("differential-testing",),
            harness_id="hpc.gemm/v1",
        )
    baseline = _baseline_requirement()
    document = baseline.model_dump(mode="json")
    document["harness_id"] = "hpc.gemm/v1"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VerificationRequirementV1.model_validate(document)

    # 2. A REAL obligation, carried by an admitted Knowledge Skill.
    _, manifest, ontology, catalog, proposal, context = _knowledge_fixture(
        obligations=(obligation,)
    )
    lock = admit_knowledge_skills(
        proposal=proposal,
        catalog=catalog,
        ontology=ontology,
        context=context,
        mode="enforce",
    )
    assert len(lock.evaluation_obligations) == 1
    carried = lock.evaluation_obligations[0]
    assert carried.property_id == "numerical-equivalence"
    assert carried.source_skill_digest == manifest.source.body_sha256

    # 3. The obligation is not inert — it strengthens the required tier — and
    #    still contributes no Harness identity.
    requirements = obligations_to_requirements(
        obligations=lock.evaluation_obligations,
        defaults_by_property={"numerical-equivalence": baseline},
    )
    assert [item.required_tier for item in requirements] == ["certify"]
    assert baseline.required_tier == "screen"
    contract = mint_verification_contract(
        run_id="run-1",
        research_contract_digest=SHA,
        research_requirements=(baseline,),
        knowledge_requirements=requirements,
        baseline_knowledge_obligation_refs=(
            f"knowledge:{manifest.source.body_sha256}",
        ),
        admission_confidence=1.0,
        human_review_identity=None,
        property_vocabulary_digest=SHA,
    )
    rendered = json.dumps(contract.model_dump(mode="json"))
    assert "harness" not in rendered.lower()
    assert not any(
        "harness" in field.lower() for field in type(contract).model_fields
    )
    for requirement in contract.requirements:
        assert not any(
            "harness" in field.lower() for field in type(requirement).model_fields
        )
    # The Skill's only trace is a provenance reference, not a selection.
    assert any(
        ref.startswith("knowledge:")
        for requirement in contract.requirements
        for ref in requirement.source_requirement_refs
    )


# ── criteria 56 / 66: revocation appends, it never rewrites ─────────────────


def _registered_registry():
    entry, manifest, *_ = _knowledge_fixture(obligations=())
    candidate = KnowledgeSkillEntryV1.create(
        manifest=entry.manifest,
        body_store_key=entry.body_store_key,
        registration_report_digest=entry.registration_report_digest,
        importer_version=entry.importer_version,
        status="candidate",
    )
    registry = GovernedKnowledgeSkillRegistry()
    registry.register(candidate)
    return registry, candidate, manifest


def test_revocation_history_append_only(tmp_path):
    """Revoking a Knowledge Skill appends a transition; it edits nothing.

    Three independent refusals stand behind that: the catalog entry is a
    digest-bound record whose status is inside its own digest, the registry
    refuses to replace a registered entry ("Knowledge catalog entries are
    immutable"), and a published historical artifact cannot be overwritten by
    the post-revocation value (``write_once_json``).
    """

    registry, candidate, manifest = _registered_registry()
    skill_ref = manifest.exact_ref()
    key = (skill_ref.id, skill_ref.version, skill_ref.body_sha256)
    published = tmp_path / "knowledge_catalog_entry.json"
    write_once_json(published, candidate)
    original_bytes = published.read_bytes()
    original_json = candidate.model_dump_json()

    approval = KnowledgeSkillPromotionApprovalV1.create(
        skill_ref=skill_ref,
        actor_kind="human-maintainer",
        actor_id="test-maintainer",
        authorization_basis="acceptance fixture promotion",
        approved_date="2026-08-19",
    )
    promoted = registry.transition(
        skill_ref=skill_ref,
        to_status="verified",
        actor_id="test-maintainer",
        evidence_digest=approval.approval_digest,
        approval=approval,
    )
    promoted_json = promoted.model_dump_json()
    revoked = registry.transition(
        skill_ref=skill_ref,
        to_status="revoked",
        actor_id="test-maintainer",
        evidence_digest=SHA,
    )

    # The ledger grew; the earlier transition is byte-identical afterwards and
    # the new one names it as its parent, so the order is reconstructible.
    assert [item.to_status for item in registry.transitions] == ["verified", "revoked"]
    assert registry.transitions[0].model_dump_json() == promoted_json
    assert revoked.from_status == "verified"
    assert revoked.parent_transition_digest == promoted.transition_digest
    assert registry.status_at(skill_ref) == "revoked"

    # The registered record did not move: it still says what it said when it
    # was registered, which is what makes an old run's provenance readable.
    assert registry.entries[key].model_dump_json() == original_json
    assert registry.entries[key].status == "candidate"

    # Rewriting it in place is refused by the registry…
    revoked_entry = KnowledgeSkillEntryV1.create(
        manifest=candidate.manifest,
        body_store_key=candidate.body_store_key,
        registration_report_digest=candidate.registration_report_digest,
        importer_version=candidate.importer_version,
        status="revoked",
    )
    assert revoked_entry.entry_digest != candidate.entry_digest
    with pytest.raises(ValueError, match="entries are immutable"):
        registry.register(revoked_entry)
    assert registry.entries[key].model_dump_json() == original_json

    # …by the record's own digest, if someone edits the serialised form…
    tampered = json.loads(candidate.model_dump_json())
    tampered["status"] = "revoked"
    with pytest.raises(ValidationError, match="entry_digest"):
        KnowledgeSkillEntryV1.model_validate(tampered)

    # …and by the write-once store, if someone republishes over the artifact.
    with pytest.raises(ValueError, match="immutable artifact mismatch"):
        write_once_json(published, revoked_entry)
    assert published.read_bytes() == original_bytes
    # Re-publishing the SAME value stays idempotent: the guard is about change.
    assert write_once_json(published, candidate) == published


def _flip_manifest_status(catalog_path: Path, status: str, *, repair_digest: bool):
    manifest_path = catalog_path.parent / "builtin" / "gemm.yaml"
    document = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    document["status"] = status
    if repair_digest:
        from ari.assurance.models import HarnessManifestV1

        recomputed = dict(document)
        recomputed.pop("manifest_digest", None)
        document["manifest_digest"] = HarnessManifestV1.create(
            **recomputed
        ).manifest_digest
    manifest_path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")


def test_three_catalog_revocation_append_only(tmp_path):
    """Knowledge, Provider and Harness: a status flip mints a new record in all
    three, and overwrites the historical one in none of them.

    Same property, three separately-implemented catalogs, so it is asserted
    three times rather than inferred from one.
    """

    # ── Knowledge: the registry refuses to replace a registered entry ────────
    registry, candidate, manifest = _registered_registry()
    key = (
        manifest.id,
        manifest.version,
        manifest.source.body_sha256,
    )
    revoked_entry = KnowledgeSkillEntryV1.create(
        manifest=candidate.manifest,
        body_store_key=candidate.body_store_key,
        registration_report_digest=candidate.registration_report_digest,
        importer_version=candidate.importer_version,
        status="revoked",
    )
    with pytest.raises(ValueError, match="entries are immutable"):
        registry.register(revoked_entry)
    assert registry.entries[key].status == "candidate"

    # ── Provider: the catalog entry's status is inside its own digest ────────
    provider_entry = ProviderCatalogEntryV1.create(
        provider_id="ari.provider.web",
        runtime_name="web",
        package="ari-skill-web",
        package_version="1.0.0",
        status="verified",
        maintainer="ARI maintainers",
        source=ProviderSourceV1(
            repository="https://example.invalid/provider",
            full_commit_sha="0" * 40,
            package_sha256=SHA,
            license="MIT",
        ),
        manifest_sha256=SHA,
        registration_report_digest=SHA,
    )
    revoked_provider = ProviderCatalogEntryV1.create(
        **{
            **provider_entry.model_dump(mode="python", exclude={"entry_digest"}),
            "status": "revoked",
        }
    )
    assert revoked_provider.entry_digest != provider_entry.entry_digest
    tampered_provider = json.loads(provider_entry.model_dump_json())
    tampered_provider["status"] = "revoked"
    with pytest.raises(ValidationError, match="entry_digest"):
        ProviderCatalogEntryV1.model_validate(tampered_provider)
    published_provider = tmp_path / "provider_catalog_entry.json"
    write_once_json(published_provider, provider_entry)
    provider_bytes = published_provider.read_bytes()
    with pytest.raises(ValueError, match="immutable artifact mismatch"):
        write_once_json(published_provider, revoked_provider)
    assert published_provider.read_bytes() == provider_bytes

    # ── Harness: the checked-in catalog refuses an in-place status flip ──────
    from ari.assurance.catalog import load_harness_catalog
    from tests.test_assurance_resolver import _write_verified_catalog

    catalog_path, harness_manifest, report, _ = _write_verified_catalog(tmp_path)
    snapshot = load_harness_catalog(catalog_path)
    published_snapshot = tmp_path / "harness_catalog_snapshot.json"
    write_once_json(published_snapshot, snapshot)
    snapshot_bytes = published_snapshot.read_bytes()

    # A naive flip is caught by the manifest's own advertised digest…
    _flip_manifest_status(catalog_path, "revoked", repair_digest=False)
    with pytest.raises(ValueError, match="manifest digest mismatch"):
        load_harness_catalog(catalog_path)

    # …and repairing that digest — making the manifest self-consistent again —
    # runs into the registration report, which is pinned to the manifest that
    # was actually reviewed.  There is no way to flip status in place.
    _flip_manifest_status(catalog_path, "revoked", repair_digest=True)
    with pytest.raises(ValueError, match="registration report differs"):
        load_harness_catalog(catalog_path)

    # The retained snapshot still describes the catalog that was loaded, and
    # cannot be overwritten by the post-revocation catalog.
    assert published_snapshot.read_bytes() == snapshot_bytes
    assert snapshot.manifests[0].status == "verified"
    assert snapshot.registration_report_digests == {
        harness_manifest.id: report.report_digest
    }


# ── criteria 48 / 14: fixed resolution is pure ─────────────────────────────

#: Modules whose result must be a function of their declared inputs alone: no
#: model call, no socket, and no reading of the clock or the entropy pool.
#: ``time``/``datetime``/``random`` are in the banned set because a resolver
#: that consults any of them cannot yield a byte-identical lock on replay,
#: which is what criteria 17/32 pin.
BANNED_MODULES = (
    "aiohttp",
    "anthropic",
    "datetime",
    "httpx",
    "litellm",
    "openai",
    "random",
    "requests",
    "secrets",
    "socket",
    "time",
    "urllib",
)


def _imported_roots(path: Path) -> set[str]:
    """Every module imported by *path*, including function-local imports."""

    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _assert_pure(paths: tuple[Path, ...]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    assert not missing, f"the purity scanner names modules that do not exist: {missing}"
    offenders = {
        path.name: sorted(_imported_roots(path) & set(BANNED_MODULES))
        for path in paths
    }
    assert {name: found for name, found in offenders.items() if found} == {}


def _package_dir(module_name: str) -> Path:
    import importlib

    return Path(importlib.import_module(module_name).__file__).parent


def test_fixed_resolution_purity():
    """Criterion 48 — the Harness Resolver and the Kernel are pure procedures.

    Both decide admission and both must be replayable from their recorded
    inputs.  An LLM or network import would make the decision unauditable; a
    clock or entropy import would make it unreproducible, which is the same
    failure with a friendlier name.
    """

    rqgm_dir = _package_dir("ari.rqgm")
    assurance_dir = _package_dir("ari.assurance")
    kernel_files = sorted(rqgm_dir.glob("kernel*.py"))
    assert {path.name for path in kernel_files} == {
        "kernel.py",
        "kernel_capability_integrity.py",
        "kernel_harness_integrity.py",
        "kernel_kca_common.py",
        "kernel_knowledge_integrity.py",
        "kernel_rules.py",
        "kernel_types.py",
    }
    _assert_pure(
        (
            *kernel_files,
            rqgm_dir / "kca_kernel_rules.py",
            rqgm_dir / "transition_rules.py",
            assurance_dir / "resolver.py",
            assurance_dir / "suite.py",
            assurance_dir / "lock.py",
        )
    )


def test_knowledge_binder_purity():
    """Criterion 14 — the Knowledge Binder is pure for the same reasons.

    Same scanner, different module set: admission, composition and the epoch
    lock are the three modules whose output is pinned into node provenance.
    """

    knowledge_dir = _package_dir("ari.knowledge")
    _assert_pure(
        (
            knowledge_dir / "resolver.py",
            knowledge_dir / "composition.py",
            knowledge_dir / "lock.py",
        )
    )


# ── criterion 5: one Provider satisfies requirements from several Skills ────


def _capability_contract(ref: str, title: str) -> CapabilityContractV1:
    return CapabilityContractV1.create(
        capability_ref=ref,
        contract_version="v1",
        title=title,
        description=f"{title} a candidate",
        side_effect_class="workspace-write",
        determinism_class="conditional",
        context_requirement="node",
        compatibility_rules=("schema",),
    )


COMPILE_CONTRACT = _capability_contract("ari.execution.compile/v1", "Compile")
PROFILE_CONTRACT = _capability_contract("ari.execution.profile/v1", "Profile")
TWO_CAPABILITY_ONTOLOGY = CapabilityOntologySnapshotV1.create(
    source_revision="test",
    property_vocabulary_version="v1",
    contracts=(COMPILE_CONTRACT, PROFILE_CONTRACT),
)


def _skill_manifest(
    *,
    skill_id: str,
    body: str,
    capabilities: tuple[KnowledgeCapabilityRequirementV1, ...],
) -> KnowledgeSkillManifestV1:
    """One Knowledge Skill whose body — and so whose provenance ref — is its own."""

    return KnowledgeSkillManifestV1(
        id=skill_id,
        version="1.0.0",
        title=skill_id,
        description="acceptance fixture",
        status="verified",
        source=KnowledgeSkillSourceV1(
            repository="https://example.invalid/knowledge",
            commit="2" * 40,
            path="knowledge-skills/" + skill_id,
            body_sha256=bytes_digest(body.encode()),
            manifest_sha256=SHA,
        ),
        license=KnowledgeSkillLicenseV1(body="MIT", references="MIT"),
        applies_to=KnowledgeSkillApplicabilityV1(
            roles=("generator",), phases=("bfts",), task_tags=("gemm",)
        ),
        requires=KnowledgeCapabilitySetV1(capabilities=capabilities),
        authority_ceiling=KnowledgeAuthorityCeilingV1(
            side_effects=("read-only", "workspace-write")
        ),
        composition=KnowledgeCompositionV1(slot="domain-method", priority=100),
    )


def _admitted_skill_lock(manifests: tuple[KnowledgeSkillManifestV1, ...]):
    """Admit several Skills through the real fixed Knowledge Binder."""

    entries = tuple(
        KnowledgeSkillEntryV1.create(
            manifest=item,
            body_store_key=item.source.body_sha256,
            registration_report_digest=SHA,
            importer_version="test/v1",
            status="verified",
        )
        for item in manifests
    )
    catalog = build_catalog_snapshot(
        catalog_source_revision="test", importer_version="test/v1", entries=entries
    )
    proposal = KnowledgeSkillSelectionProposalV1.create(
        run_id="run-1",
        epoch_id="epoch_000",
        research_contract_digest=SHA,
        proposed=tuple(item.exact_ref() for item in manifests),
        reason="several applicable Skills",
        router_component_id="proposal_router_v1",
        router_prompt_hash=None,
    )
    context = KnowledgeAdmissionContextV1.create(
        role="generator",
        phase="bfts",
        task_tags=("gemm",),
        permitted_side_effects=("read-only", "workspace-write"),
        property_vocabulary=("numerical-equivalence",),
    )
    return admit_knowledge_skills(
        proposal=proposal,
        catalog=catalog,
        ontology=TWO_CAPABILITY_ONTOLOGY,
        context=context,
        mode="enforce",
    )


def _capability_provision(
    contract: CapabilityContractV1, *, provider: str, tool: str
) -> CapabilityProvisionV1:
    return CapabilityProvisionV1.create(
        provider_id=provider,
        provider_identity_digest=canonical_digest({"provider": provider}),
        provider_status="verified",
        tool_ref=tool,
        declared_capability_ref="legacy." + contract.title.lower(),
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


def _binding_request(skill_lock, provisions, *, mode: str):
    """Build the request exactly as ``build_kca_admission`` does.

    ``_run_capability_requirements`` is the only step between the Knowledge
    Skill Lock and the binding request, so it is the place a second Skill's
    requirement would be dropped before the binder ever saw it; driving it here
    keeps this criterion bound to the production wiring rather than to a
    hand-assembled requirement tuple.
    """

    from types import SimpleNamespace

    from ari.rqgm.admission_builder import _run_capability_requirements

    requirements = _run_capability_requirements(
        SimpleNamespace(capability_binding=None),
        TWO_CAPABILITY_ONTOLOGY,
        skill_lock,
    )
    return requirements, CapabilityBindingRequestV1.create(
        run_id="run-1",
        epoch_id="epoch_000",
        research_contract_digest=SHA,
        knowledge_skill_lock_digest=skill_lock.lock_digest,
        ontology_snapshot_digest=TWO_CAPABILITY_ONTOLOGY.snapshot_digest,
        provider_catalog_snapshot_digest=SHA,
        provider_lock_digest=SHA,
        requirements=requirements,
        provisions=tuple(provisions),
        available_tool_refs=tuple(sorted({item.tool_ref for item in provisions})),
        role="generator",
        phase="bfts",
        call_context="node",
        authorized_capability_refs=tuple(
            sorted(item.capability_ref for item in TWO_CAPABILITY_ONTOLOGY.contracts)
        ),
        environment=EnvironmentSnapshotV1.create(resource_types=("process",)),
        mode=mode,
    )


def _knowledge_ref(manifest: KnowledgeSkillManifestV1) -> str:
    return f"knowledge:{manifest.source.body_sha256}"


def test_provider_satisfies_multiple_skills():
    """Criterion 5 — one Provider serves several Knowledge Skills at once.

    The mirror of criterion 4.  Knowledge states *what* is needed and Providers
    state *what can execute it*; if the two layers were really separate then the
    fan-in direction has to work as well as the fan-out one, and plan 16/17's
    separation claim rests on it.

    Driven through the real chain — ``admit_knowledge_skills`` →
    ``_run_capability_requirements`` → ``bind_capabilities`` — in both shapes a
    second Skill can take, and with the negative direction included: a Provider
    that satisfies only ONE of the two requirements must not carry the other.
    Without that half, a green test would not distinguish "one Provider
    satisfied both" from "the binder discarded what it could not satisfy".
    """

    gemm = _skill_manifest(
        skill_id="hpc.gemm.optimization",
        body="# GEMM\nCompile the candidate, then measure it.\n",
        capabilities=(
            KnowledgeCapabilityRequirementV1(
                ref=COMPILE_CONTRACT.capability_ref, required=True
            ),
        ),
    )
    stencil = _skill_manifest(
        skill_id="hpc.stencil.tuning",
        body="# Stencil\nProfile the candidate before tuning it.\n",
        capabilities=(
            KnowledgeCapabilityRequirementV1(
                ref=PROFILE_CONTRACT.capability_ref, required=True
            ),
        ),
    )
    # Distinct bodies, so the two provenance refs are distinguishable and an
    # assertion about "both" cannot pass on one ref counted twice.
    assert gemm.source.body_sha256 != stencil.source.body_sha256

    # 1. Two Skills, two different capabilities, ONE Provider offering both.
    skill_lock = _admitted_skill_lock((gemm, stencil))
    assert {item.id for item in skill_lock.admitted} == {gemm.id, stencil.id}
    both = (
        _capability_provision(
            COMPILE_CONTRACT, provider="provider-a", tool="provider-a::compile"
        ),
        _capability_provision(
            PROFILE_CONTRACT, provider="provider-a", tool="provider-a::profile"
        ),
    )
    requirements, request = _binding_request(skill_lock, both, mode="enforce")
    assert {item.capability_ref: item.source_requirement_refs for item in requirements} == {
        COMPILE_CONTRACT.capability_ref: (_knowledge_ref(gemm),),
        PROFILE_CONTRACT.capability_ref: (_knowledge_ref(stencil),),
    }
    lock, _ = bind_capabilities(request)
    assert lock.unsatisfied == ()
    # The single Provider carries both capabilities, and each binding still
    # names the Skill the requirement came from.
    assert {item.capability_ref: item.provider_id for item in lock.bindings} == {
        COMPILE_CONTRACT.capability_ref: "provider-a",
        PROFILE_CONTRACT.capability_ref: "provider-a",
    }
    assert {
        item.capability_ref: set(item.source_requirement_refs)
        for item in lock.bindings
    } == {
        COMPILE_CONTRACT.capability_ref: {_knowledge_ref(gemm)},
        PROFILE_CONTRACT.capability_ref: {_knowledge_ref(stencil)},
    }

    # 2. The other shape: two Skills asking for the SAME capability merge into
    #    one requirement, and the one binding must be attributed to both.
    stencil_compile = _skill_manifest(
        skill_id="hpc.stencil.tuning",
        body="# Stencil\nProfile the candidate before tuning it.\n",
        capabilities=(
            KnowledgeCapabilityRequirementV1(
                ref=COMPILE_CONTRACT.capability_ref, required=True
            ),
        ),
    )
    shared_lock = _admitted_skill_lock((gemm, stencil_compile))
    shared_requirements, shared_request = _binding_request(
        shared_lock,
        (
            _capability_provision(
                COMPILE_CONTRACT, provider="provider-a", tool="provider-a::compile"
            ),
        ),
        mode="enforce",
    )
    assert {item.capability_ref for item in shared_requirements} == {
        COMPILE_CONTRACT.capability_ref
    }
    shared_binding_lock, _ = bind_capabilities(shared_request)
    assert {item.provider_id for item in shared_binding_lock.bindings} == {"provider-a"}
    assert {
        ref
        for item in shared_binding_lock.bindings
        for ref in item.source_requirement_refs
    } == {_knowledge_ref(gemm), _knowledge_ref(stencil_compile)}

    # 3. Negative — the Provider offers no profile capability at all.  Enforce
    #    refuses and names the capability it could not satisfy; audit records it
    #    as unsatisfied instead of quietly binding one Skill and reporting done.
    only_compile = (
        _capability_provision(
            COMPILE_CONTRACT, provider="provider-a", tool="provider-a::compile"
        ),
    )
    _, half_request = _binding_request(skill_lock, only_compile, mode="enforce")
    with pytest.raises(CapabilityBindingError) as absent:
        bind_capabilities(half_request)
    assert PROFILE_CONTRACT.capability_ref in str(absent.value)
    assert COMPILE_CONTRACT.capability_ref not in str(absent.value)
    _, half_audit = _binding_request(skill_lock, only_compile, mode="audit")
    audited, _ = bind_capabilities(half_audit)
    assert {item.capability_ref: item.provider_id for item in audited.bindings} == {
        COMPILE_CONTRACT.capability_ref: "provider-a"
    }
    assert {item.capability_ref: item.rejection_codes for item in audited.unsatisfied} == {
        PROFILE_CONTRACT.capability_ref: ("no_candidate",)
    }
    # The second Skill's provenance must not be attached to a binding it did
    # not obtain.
    assert _knowledge_ref(stencil) not in {
        ref for item in audited.bindings for ref in item.source_requirement_refs
    }

    # 4. Negative — the Provider DOES offer a matching profile provision, but
    #    the second Skill pins another Provider.  The candidate is evaluated and
    #    refused, which is what separates "the binder checked and said no" from
    #    "the binder never looked at the second requirement".
    pinned_stencil = _skill_manifest(
        skill_id="hpc.stencil.tuning",
        body="# Stencil\nProfile the candidate before tuning it.\n",
        capabilities=(
            KnowledgeCapabilityRequirementV1(
                ref=PROFILE_CONTRACT.capability_ref,
                required=True,
                explicit_provider_pin="provider-b",
            ),
        ),
    )
    pinned_lock = _admitted_skill_lock((gemm, pinned_stencil))
    _, pinned_request = _binding_request(pinned_lock, both, mode="enforce")
    with pytest.raises(CapabilityBindingError) as refused:
        bind_capabilities(pinned_request)
    assert PROFILE_CONTRACT.capability_ref in str(refused.value)
    _, pinned_audit = _binding_request(pinned_lock, both, mode="audit")
    pinned_result, pinned_report = bind_capabilities(pinned_audit)
    assert {item.capability_ref: item.provider_id for item in pinned_result.bindings} == {
        COMPILE_CONTRACT.capability_ref: "provider-a"
    }
    assert {
        item.capability_ref: item.rejection_codes for item in pinned_result.unsatisfied
    } == {PROFILE_CONTRACT.capability_ref: ("provider_pin_mismatch",)}
    profile_provision = next(
        item for item in both if item.capability_ref == PROFILE_CONTRACT.capability_ref
    )
    assert any(
        item.provision_digest == profile_provision.provision_digest
        and "provider_pin_mismatch" in item.reason_codes
        for item in pinned_report.rejected_candidates
    )


# ── criteria 31 / 36 / 37 / 38 / 65: Harness authority, tolerance, staleness ──
#
# One internally consistent verification state -- manifest, catalog snapshot,
# Verification Contract, baseline Lock, run request and Attestation -- so that a
# test moves exactly one field and reads the consequence of THAT field.

HARNESS_ID = "hpc/gemm-correctness"
TARGET_SHA = "sha256:" + "7" * 64
OTHER_TARGET_SHA = "sha256:" + "8" * 64
TOLERANCE_SHA = "sha256:" + "d" * 64
RELAXED_TOLERANCE_SHA = "sha256:" + "e" * 64


def _asset(revision: str) -> PinnedHarnessAssetV1:
    return PinnedHarnessAssetV1(
        revision=revision, sha256=canonical_digest(revision), license="MIT"
    )


def _harness_manifest(*, version="1.0.0", tolerance=TOLERANCE_SHA):
    return HarnessManifestV1.create(
        id=HARNESS_ID,
        version=version,
        kind="artifact_verifier",
        status="verified",
        description="GEMM correctness verifier",
        maintainer="ari",
        tags=("hpc",),
        subject_types=("program",),
        target_kinds=("shared-library",),
        accepts_external_target=True,
        supported_languages=("c",),
        supported_hardware=("cpu",),
        supported_architectures=("x86_64",),
        supported_dtypes=("float64",),
        supported_domains=("gemm",),
        properties=(
            HarnessPropertyCoverageV1(
                property_id="numerical-equivalence",
                methods=("differential-testing",),
                tiers=("certify",),
                scope=VerificationScopeV1(values={"dtype": ("float64",)}),
                tolerance_policy_digest=tolerance,
            ),
        ),
        target_interface_contract="gemm-c-abi/v1",
        target_interface_digest=SHA,
        source_repository="https://example.invalid/harness",
        source_full_commit_sha="4" * 40,
        implementation_license="MIT",
        dataset=_asset("dataset-v1"),
        oracle=_asset("oracle-v1"),
        driver=_asset("native-v1"),
        model=_asset("none"),
        container=ContainerPinV1(
            reference="example.invalid/harness@sha256:4",
            resolved_digest=SHA,
            license="MIT",
        ),
        network_policy="deny",
        credential_policy="none",
        filesystem_policy="isolated-readonly-target",
        resources=HarnessResourceRequirementsV1(
            cpu_cores=1, memory_bytes=1024, accelerators=0, disk_bytes=1024
        ),
        timeout_seconds=60,
        scorer_determinism="deterministic",
        nondeterminism_declaration="none",
        hidden_test_policy="verifier-only",
        oracle_independence="independent",
        tolerance_policy_digest=tolerance,
        expected_result_schema="ari.native-hpc-result/v1",
        expected_result_schema_digest=SHA,
        infrastructure_failure_policy="separate",
        retry_limit=1,
        negative_control_report_digest=SHA,
        upstream_parity_report_digest=SHA,
    )


def _harness_atom(*, tolerance=TOLERANCE_SHA) -> HarnessRequirementV1:
    return HarnessRequirementV1.create(
        verification_requirement_digest=SHA,
        property_id="numerical-equivalence",
        method="differential-testing",
        tier="certify",
        target_kind="shared-library",
        scope=VerificationScopeV1(values={"dtype": ("float64",)}),
        tolerance_policy_digest=tolerance,
        independence_requirement="independent",
        determinism_requirement="deterministic",
        source_requirement_refs=("research:metric",),
    )


def _locked_harness(manifest, atom, *, tolerance=None) -> LockedHarnessV1:
    """The Lock entry pinned to *manifest*: every digest is copied FROM it."""

    return LockedHarnessV1(
        harness_id=manifest.id,
        version=manifest.version,
        kind=manifest.kind,
        manifest_digest=manifest.manifest_digest,
        dataset_digest=manifest.dataset.sha256,
        oracle_digest=manifest.oracle.sha256,
        driver_digest=manifest.driver.sha256,
        container_digest=manifest.container.resolved_digest,
        result_schema_digest=manifest.expected_result_schema_digest,
        tolerance_policy_digest=tolerance or manifest.tolerance_policy_digest,
        covered_atom_digests=(atom.atom_digest,),
    )


def _baseline_lock(locked, atom, **overrides) -> BaselineHarnessLockV1:
    values = dict(
        run_id="run-1",
        research_contract_digest=SHA,
        verification_contract_digest=SHA,
        harness_catalog_snapshot_digest=SHA,
        verification_environment_digest=SHA,
        oracle_bundle_digest=SHA,
        suite_digest=SHA,
        requirements=(atom,),
        harnesses=(locked,),
        coverage_proof_digest=SHA,
    )
    values.update(overrides)
    return BaselineHarnessLockV1.create(**values)


def _harness_catalog(manifests):
    snapshot = build_harness_catalog_snapshot(
        catalog_source_revision="acceptance",
        property_vocabulary_digest=SHA,
        driver_protocol_version="v1",
        manifests=tuple(manifests),
        registration_report_digests={item.id: SHA for item in manifests},
        registration_evidence_digests={item.id: SHA for item in manifests},
        promotion_approval_digests={item.id: SHA for item in manifests},
    )
    return snapshot.model_dump(mode="json")


def _verification_contract(*, tolerance=TOLERANCE_SHA, tier="certify"):
    requirement = VerificationRequirementV1.create(
        property_id="numerical-equivalence",
        target_kind="shared-library",
        required_methods=("differential-testing",),
        required_tier=tier,
        failure_policy="exclude-from-scientific-frontier",
        scope=VerificationScopeV1(values={"dtype": ("float64",)}),
        tolerance_policy_ref="hpc.float64/v1",
        tolerance_policy_digest=tolerance,
        source_requirement_refs=("research:metric",),
    )
    return VerificationContractV1.create(
        run_id="run-1",
        research_contract_digest=SHA,
        requirements=(requirement,),
        admission_confidence=1.0,
        property_vocabulary_digest=SHA,
    )


def _run_request(
    root, *, locked, atom, active_lock_digest, target_digest=TARGET_SHA
) -> HarnessRunRequestV1:
    workspace = WorkspaceRefV1(root=str(Path(root) / "verification-workspace"))
    Path(workspace.root).joinpath("candidate.so").write_bytes(b"candidate")
    execution = ExecutionRequestV1(
        workspace=workspace,
        argv=("/bin/true",),
        timeout_seconds=60,
        network="deny",
        request_id="attempt-1",
        input_digests={"candidate.so": target_digest},
    )
    return HarnessRunRequestV1.create(
        run_id="run-1",
        node_id="node_001",
        epoch_id="epoch_000",
        active_harness_lock_digest=active_lock_digest,
        harness=locked,
        target_workspace=workspace,
        target_artifact=ResearchArtifactRefV1(
            logical_name="candidate.so",
            digest=target_digest,
            media_type="application/x-sharedlib",
            role="verification-target",
            source_run_id="run-1",
        ),
        target_logical_name="candidate.so",
        target_kind="shared-library",
        target_digest=target_digest,
        property_atoms=(atom,),
        execution_request=execution,
        attempt_id="attempt-1",
        retry_index=0,
        expected_result_schema="ari.native-hpc-result/v1",
    )


def _bound_attestation(*, request, baseline, manifest, **overrides):
    """The Attestation a fixed verifier mints for *request* under *baseline*."""

    result = HarnessPropertyResultV1(
        property_id="numerical-equivalence",
        method="differential-testing",
        tier="certify",
        tested_scope=VerificationScopeV1(values={"dtype": ("float64",)}),
        verdict="pass",
        covered_atom_digests=tuple(
            item.atom_digest for item in request.property_atoms
        ),
        evidence_artifact_refs=(),
    )
    values = dict(
        active_harness_lock_digest=request.active_harness_lock_digest,
        baseline_harness_lock_digest=baseline.lock_digest,
        harness_manifest_digest=manifest.manifest_digest,
        driver_digest=manifest.driver.sha256,
        oracle_digest=manifest.oracle.sha256,
        dataset_digest=manifest.dataset.sha256,
        container_digest=manifest.container.resolved_digest,
        target_digest=request.target_digest,
        property_results=(result,),
    )
    values.update(overrides)
    return _attestation(**values)


def _verification_state(root, *, target_digest=TARGET_SHA):
    """manifest / atom / locked / baseline / request / attestation, all agreeing."""

    manifest = _harness_manifest()
    atom = _harness_atom()
    locked = _locked_harness(manifest, atom)
    baseline = _baseline_lock(locked, atom)
    request = _run_request(
        root,
        locked=locked,
        atom=atom,
        active_lock_digest=baseline.lock_digest,
        target_digest=target_digest,
    )
    attestation = _bound_attestation(
        request=request, baseline=baseline, manifest=manifest
    )
    return manifest, atom, locked, baseline, request, attestation


def _harness_codes(**kwargs) -> set[str]:
    """Every violation code the Constitutional Kernel raises for a Harness state.

    The tests below never name a CK-HAR code.  Each one takes the DIFFERENCE
    between the codes raised for a coherent state and for the same state with a
    single field moved, so the code that answers for the criterion is read out
    of the Kernel rather than restated here -- and deleting the rule empties the
    difference and turns the assertion red.
    """

    report = ConstitutionalKernel().validate_harness_integrity(**kwargs)
    return {violation.code for violation in report.violations}


def _harness_findings(**kwargs) -> set[tuple[str, str]]:
    """The same, keeping each finding's rule id: two arms of one rule are two
    rule ids under one code, and a single arm counted twice is not."""

    report = ConstitutionalKernel().validate_harness_integrity(**kwargs)
    return {
        (violation.code, violation.rule_id) for violation in report.violations
    }


def _all_blocking(codes) -> bool:
    return bool(codes) and all(
        kernel_rules.SEVERITY[code] == "block" for code in codes
    )


# ── criterion 31: a Generator cannot change the required Harness/tolerance ───


def test_generator_harness_mutation_denied(tmp_path):
    """Every route by which a Generator could change the required Harness set,
    its tolerance policy, its oracle pin or the Lock itself refuses.

    Task 19 section 5.1 states the authority this binds: a Generator "cannot
    ... rewrite a lock, ... remove a required Harness, change
    tolerance/oracle/dataset/driver/container, or override fail".  There is no
    single ``generator_changed_the_harness`` signal, and there does not need to
    be one -- the refusals are structural and there are seven of them, so this
    walks all seven.  A guard that covered only the capability matrix would
    miss the resumed run, which reads its Lock back as plain JSON and never
    revalidates it against the model that pins its producer.
    """

    from ari.rqgm.kernel_rules import kca_kernel_rules
    from ari.rqgm.runtime import RQGMRuntime

    kernel = ConstitutionalKernel()

    # 1. AUTHORITY. Over the WHOLE Knowledge/Capability/Assurance resource
    #    table -- not a hand-picked Harness subset of it -- the Generator holds
    #    exactly one non-read grant, invoking a tool the Binding Lock already
    #    bound, and the Kernel blocks every other mutating pair in every tier
    #    the role has. The table and the action vocabulary are read from the
    #    constitution, so a resource class added there is covered here the day
    #    it lands.
    resources = set(kca_kernel_rules.RESOURCE_CLASSES)
    mutating = tuple(action for action in kernel_rules.ACTIONS if action != "read")
    assert resources and mutating, "the K/C/A capability vocabulary is empty"
    granted, denied = set(), set()
    for tier in ("institutional", "meta"):
        caps = kernel_rules.CAPABILITY_MATRIX[("generator", tier)]
        for action in mutating:
            for resource in sorted(resources):
                if (action, resource) in caps:
                    granted.add((tier, action, resource))
                    continue
                report = kernel.validate_capability(
                    ("generator", tier), action, resource
                )
                assert report.violations, (tier, action, resource)
                assert all(
                    item.severity == "block" for item in report.violations
                ), (tier, action, resource)
                denied.add((tier, action, resource))
    assert granted == {("institutional", "invoke", "provider_execution")}, granted
    harness_resources = {name for name in resources if "harness" in name}
    assert harness_resources, "the resource table names no Harness resource"
    assert {resource for _t, _a, resource in denied} >= harness_resources
    assert len(denied) >= len(resources), "the denial enumeration collapsed"

    manifest, atom, locked, baseline, _request, _att = _verification_state(tmp_path)
    payload = baseline.model_dump(mode="json")

    # 2. AUTHORSHIP is a schema literal, so a Generator cannot even claim to
    #    have produced a Lock: the producer is fixed and the prompt hash -- the
    #    mark of a prompted producer -- must be absent.
    for field, value in (
        ("producer_component_id", "generator_v1"),
        ("prompt_hash", SHA),
    ):
        with pytest.raises(ValidationError):
            _baseline_lock(locked, atom, **{field: value})

    # 3. THE PINS. The Lock digest covers every digest a locked Harness carries
    #    -- the Harness identity, its oracle, dataset, driver, container, result
    #    schema and tolerance policy -- so an edited copy is refused at
    #    construction. The field list is read off the model: a pin added to
    #    ``LockedHarnessV1`` is driven here without anyone remembering to.
    pins = tuple(
        name for name in LockedHarnessV1.model_fields if name.endswith("_digest")
    )
    assert pins, "a locked Harness pins nothing any more"
    for field in pins:
        edited = json.loads(json.dumps(payload))
        edited["harnesses"][0][field] = canonical_digest("generator-chose-" + field)
        with pytest.raises(ValidationError, match="lock_digest"):
            BaselineHarnessLockV1.model_validate(edited)

    # 4. THE TOLERANCE POLICY lives in the Verification Contract, whose own
    #    requirement digests cover it the same way. Same derivation, different
    #    document.
    contract = _verification_contract()
    contract_payload = contract.model_dump(mode="json")
    requirement_pins = tuple(
        name
        for name in VerificationRequirementV1.model_fields
        if name.endswith("_digest")
        and name != VerificationRequirementV1._digest_field
    )
    assert requirement_pins, "a Verification requirement pins nothing any more"
    for field in requirement_pins:
        edited = json.loads(json.dumps(contract_payload))
        edited["requirements"][0][field] = canonical_digest("relaxed-" + field)
        with pytest.raises(ValidationError):
            VerificationContractV1.model_validate(edited)

    # 5. THE HONEST THREAT: a Generator that writes its own Lock writes a
    #    SELF-CONSISTENT one, and a resumed run reads it back as plain JSON. No
    #    digest check can see that; the Lock's own producer field can, and the
    #    runtime derivation that reads it is the one production uses.
    catalog = _harness_catalog((manifest,))
    forged = dict(payload, producer_component_id="bfts_generator_v1")
    forged["lock_digest"] = canonical_digest(
        {key: value for key, value in forged.items() if key != "lock_digest"}
    )
    common = dict(
        verification_contract=contract_payload,
        catalog_snapshot=catalog,
    )
    resolved = _harness_codes(
        baseline_lock=payload,
        selector_component_id=RQGMRuntime._lock_selector_component_id(
            payload, RQGMRuntime._FIXED_HARNESS_SELECTOR
        ),
        **common,
    )
    assert resolved == set(), resolved
    chosen = _harness_codes(
        baseline_lock=forged,
        selector_component_id=RQGMRuntime._lock_selector_component_id(
            forged, RQGMRuntime._FIXED_HARNESS_SELECTOR
        ),
        **common,
    )
    assert _all_blocking(chosen - resolved), chosen

    # 6. REMOVAL. A revision that drops the required Harness is refused, and a
    #    revision that keeps it is not.
    def _revision(active):
        return HarnessLockRevisionV1.create(
            run_id="run-1",
            next_epoch_id="epoch_001",
            parent_lock_digest=baseline.lock_digest,
            baseline_lock_digest=baseline.lock_digest,
            added_requirement_refs=(),
            added_or_strengthened_harnesses=(),
            active_harnesses=active,
            coverage_proof_digest=baseline.coverage_proof_digest,
        ).model_dump(mode="json")

    kept = _harness_codes(
        baseline_lock=payload, revision=_revision(baseline.harnesses), **common
    )
    assert kept == set(), kept
    removed = _harness_codes(
        baseline_lock=payload, revision=_revision(()), **common
    )
    assert _all_blocking(removed - kept), removed

    # 7. AND ON DISK the Lock is write-once: re-writing the identical bytes is
    #    what a resumed run does, replacing them with another Lock is not.
    path = tmp_path / "baseline_harness_lock.json"
    write_immutable_harness_lock(path, baseline)
    write_immutable_harness_lock(path, baseline)
    replacement = _baseline_lock(
        _locked_harness(_harness_manifest(version="1.0.1"), atom), atom
    )
    with pytest.raises(ValueError, match="immutable"):
        write_immutable_harness_lock(path, replacement)


# ── criterion 36: the Kernel blocks a tolerance relaxation ──────────────────


def _tolerance_bearing_models() -> tuple[str, ...]:
    """Every assurance document that carries a tolerance policy digest.

    Read off the models so the inventory cannot drift away from the schema it
    describes; the test asserts it is non-empty before relying on it.
    """

    import ari.assurance.models as models

    return tuple(sorted(
        name
        for name, value in vars(models).items()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and "tolerance_policy_digest" in getattr(value, "model_fields", {})
    ))


def _comparison_sites(token: str, *, occurrences: int = 2) -> set[tuple[str, str]]:
    """``(module, function)`` for every production comparison mentioning *token*
    at least *occurrences* times.

    The repeated defect in this repository is a guard written for a real rule
    that then covers part of where the rule lives.  Each criterion below states
    its rule once and then reads the places production applies it out of the
    source, so a site added later fails the test until something drives it, and
    the last site removed empties the inventory and trips that criterion's
    floor.
    """

    import ari

    root = Path(ari.__file__).resolve().parent
    sites: set[tuple[str, str]] = set()
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - never our own source
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Compare):
                    continue
                # Equality only: ``x is None`` is a presence check, not a
                # comparison of two identities, and the distinction is read
                # off the operator rather than written down as an exception.
                if not all(
                    isinstance(op, (ast.Eq, ast.NotEq)) for op in inner.ops
                ):
                    continue
                if ast.unparse(inner).count(token) >= occurrences:
                    sites.add((str(path.relative_to(root)), node.name))
    return sites


def test_ck_har_tolerance_relaxation(tmp_path):
    """A verification tolerance that moves is refused at every layer that
    compares one, and an identical one raises nothing anywhere.

    A tolerance policy is what makes a numerical verdict mean anything, so it
    is the cheapest thing to weaken and the hardest to notice afterwards: the
    Attestation still says ``pass`` and every digest still checks out.  The
    Kernel treats the policy as IMMUTABLE rather than merely monotonic --
    there is no ordering on an opaque policy digest -- which is strictly
    stronger than "relaxation" asks for.

    The Kernel raises this finding from two producers, a Verification Contract
    whose requirement swaps its policy between epochs and a Harness Lock
    revision that "strengthens" a Harness while swapping the policy underneath
    it, and both are driven because covering one would leave the other free.
    The two layers around it -- the Verification revision check and the
    Resolver's own compatibility rule, which is what stops a Harness with a
    laxer policy from being selected to satisfy the requirement in the first
    place -- are driven for the same reason, against an inventory of comparison
    sites read from the source rather than listed here.
    """

    bearers = _tolerance_bearing_models()
    assert bearers, "no assurance document carries a tolerance policy any more"
    sites = _comparison_sites("tolerance_policy_digest")
    assert sites, "nothing in production compares two tolerance policy digests"

    manifest = _harness_manifest()
    atom = _harness_atom()
    locked = _locked_harness(manifest, atom)
    baseline = _baseline_lock(locked, atom)
    catalog = _harness_catalog((manifest,))
    common = dict(
        baseline_lock=baseline.model_dump(mode="json"), catalog_snapshot=catalog
    )

    # ARM 1 (``kernel_harness_integrity``): the Verification Contract's own
    # requirement, between one epoch and the next.
    previous = _verification_contract().model_dump(mode="json")
    unchanged = _harness_findings(
        verification_contract=_verification_contract().model_dump(mode="json"),
        previous_verification_contract=previous,
        **common,
    )
    assert unchanged == set(), unchanged
    relaxed = _harness_findings(
        verification_contract=_verification_contract(
            tolerance=RELAXED_TOLERANCE_SHA
        ).model_dump(mode="json"),
        previous_verification_contract=previous,
        **common,
    )
    contract_delta = relaxed - unchanged
    assert _all_blocking({code for code, _rule in contract_delta}), relaxed

    # ARM 2 (``assurance.lock``, reached through the Kernel): a Lock revision
    # that swaps the policy under a "strengthened" Harness. The added entry
    # carries a different Harness manifest, so it is not the same pinned bytes
    # the baseline holds -- the shape that gets past the byte-identity check.
    successor = _harness_manifest(version="1.0.1")

    def _revision(added):
        return HarnessLockRevisionV1.create(
            run_id="run-1",
            next_epoch_id="epoch_001",
            parent_lock_digest=baseline.lock_digest,
            baseline_lock_digest=baseline.lock_digest,
            added_requirement_refs=(),
            added_or_strengthened_harnesses=(added,),
            active_harnesses=(*baseline.harnesses, added),
            coverage_proof_digest=baseline.coverage_proof_digest,
        ).model_dump(mode="json")

    contract = _verification_contract().model_dump(mode="json")
    kept = _harness_findings(
        verification_contract=contract,
        revision=_revision(_locked_harness(successor, atom)),
        **common,
    )
    assert kept == set(), kept
    swapped = _harness_findings(
        verification_contract=contract,
        revision=_revision(
            _locked_harness(successor, atom, tolerance=RELAXED_TOLERANCE_SHA)
        ),
        **common,
    )
    revision_delta = swapped - kept
    assert _all_blocking({code for code, _rule in revision_delta}), swapped

    # ONE code answers for both arms, under TWO different rule ids: the same
    # rule about tolerance, raised from two places, rather than two
    # coincidences or one place counted twice.
    assert {code for code, _rule in contract_delta} == {
        code for code, _rule in revision_delta
    }, (contract_delta, revision_delta)
    assert {rule for _code, rule in contract_delta}.isdisjoint(
        {rule for _code, rule in revision_delta}
    ), (contract_delta, revision_delta)

    # ARM 3 (``assurance.suite``): the Verification revision check the Contract
    # mint runs before the Kernel ever sees the two contracts.
    baseline_requirements = _verification_contract().requirements
    assert_monotonic_requirement_revision(
        baseline_requirements, _verification_contract().requirements
    )
    with pytest.raises(ValueError, match="tolerance"):
        assert_monotonic_requirement_revision(
            baseline_requirements,
            _verification_contract(tolerance=RELAXED_TOLERANCE_SHA).requirements,
        )

    # ARM 4 (``assurance.resolver``): a Harness whose own policy is laxer than
    # the requirement's cannot be selected to satisfy it at all, which is what
    # keeps the relaxation from arriving as a covered atom instead of as a
    # finding.
    environment = EnvironmentSnapshotV1.create(
        resource_types=("process", "cpu"), features=()
    )
    matched = resolve_harness_suite(
        contract=_verification_contract(),
        catalog=HarnessCatalogSnapshotV1.model_validate(catalog),
        environment=environment,
    )
    assert matched.covered_atom_digests and not matched.unsatisfied_atom_digests
    with pytest.raises(HarnessResolutionError, match="unsatisfied"):
        resolve_harness_suite(
            contract=_verification_contract(),
            catalog=HarnessCatalogSnapshotV1.model_validate(
                _harness_catalog((_harness_manifest(
                    tolerance=RELAXED_TOLERANCE_SHA
                ),))
            ),
            environment=environment,
        )

    driven = {
        ("rqgm/kernel_harness_integrity.py", "_append_requirement_monotonicity"),
        ("assurance/lock.py", "validate_harness_revision"),
        ("assurance/suite.py", "assert_monotonic_requirement_revision"),
        ("assurance/resolver.py", "_coverage"),
    }
    undriven = sites - driven
    assert not undriven, f"tolerance comparison nothing drives here: {sorted(undriven)}"


# ── criterion 62: Harness execution never follows a freely chosen tool ───────


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_SCOPE = VerificationScopeV1(
    values={"language": ("c",), "hardware": ("cpu",), "dtype": ("float64",)}
)
#: The driver revision the request builder knows how to launch.  Read from the
#: builder rather than written out, so a renamed revision fails here loudly
#: instead of silently changing which worker the fixture describes.
LAUNCHABLE_DRIVER_REVISION = "ari.assurance.native-hpc/v1"


def _harness_asset(revision: str, digest: str = SHA):
    from ari.assurance.models import PinnedHarnessAssetV1

    return PinnedHarnessAssetV1(revision=revision, sha256=digest, license="MIT")


def _verifiable_manifest(harness_id: str = "hpc/gemm-correctness"):
    """One ``verified`` artifact verifier the resolver will actually select."""

    from ari.assurance.models import (
        ContainerPinV1,
        HarnessManifestV1,
        HarnessPropertyCoverageV1,
        HarnessResourceRequirementsV1,
    )

    return HarnessManifestV1.create(
        id=harness_id,
        version="1.0.0",
        kind="artifact_verifier",
        status="verified",
        description="locked verifier fixture",
        maintainer="ari",
        tags=("hpc",),
        subject_types=("program",),
        target_kinds=("shared-library",),
        accepts_external_target=True,
        supported_languages=("c",),
        supported_hardware=("cpu",),
        supported_architectures=("x86_64",),
        supported_dtypes=("float64",),
        supported_domains=("gemm",),
        properties=(
            HarnessPropertyCoverageV1(
                property_id="numerical-equivalence",
                methods=("differential-testing",),
                tiers=("screen",),
                scope=HARNESS_SCOPE,
                tolerance_policy_digest=SHA,
            ),
        ),
        target_interface_contract="gemm-c-abi/v1",
        target_interface_digest=SHA,
        source_repository="https://example.invalid/ari",
        source_full_commit_sha="5" * 40,
        implementation_license="MIT",
        dataset=_harness_asset("cases/v1"),
        oracle=_harness_asset("reference/v1"),
        driver=_harness_asset(LAUNCHABLE_DRIVER_REVISION),
        model=_harness_asset("none"),
        container=ContainerPinV1(
            reference="example.invalid/ari-harness@sha256:" + "5" * 64,
            resolved_digest=SHA,
            license="MIT",
        ),
        network_policy="deny",
        credential_policy="none",
        filesystem_policy="isolated-readonly-target",
        resources=HarnessResourceRequirementsV1(
            cpu_cores=2,
            memory_bytes=64 * 1024 * 1024,
            accelerators=0,
            disk_bytes=16 * 1024 * 1024,
        ),
        timeout_seconds=60,
        scorer_determinism="deterministic",
        nondeterminism_declaration="none",
        hidden_test_policy="verifier-only",
        oracle_independence="independent",
        tolerance_policy_digest=SHA,
        expected_result_schema="ari.native-hpc-verification-report/v1",
        expected_result_schema_digest=SHA,
        infrastructure_failure_policy="separate",
        retry_limit=1,
        negative_control_report_digest=SHA,
        upstream_parity_report_digest=SHA,
    )


def _locked_run(tmp_path: Path):
    """A minted baseline lock and the exact request its Harness would run."""

    from ari.assurance.catalog import build_harness_catalog_snapshot
    from ari.assurance.models import (
        HarnessTargetDeclarationV1,
        VerificationContractV1,
    )
    from ari.assurance.request import build_native_harness_run_request
    from ari.assurance.resolver import mint_baseline_harness_lock, resolve_harness_suite
    from ari.execution import WorkspaceRefV1

    manifest = _verifiable_manifest()
    requirement = VerificationRequirementV1.create(
        property_id="numerical-equivalence",
        target_kind="shared-library",
        required_methods=("differential-testing",),
        required_tier="screen",
        failure_policy="exclude-from-scientific-frontier",
        scope=HARNESS_SCOPE,
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
    catalog = build_harness_catalog_snapshot(
        catalog_source_revision="test",
        property_vocabulary_digest=SHA,
        driver_protocol_version="v1",
        manifests=(manifest,),
        registration_report_digests={manifest.id: SHA},
        registration_evidence_digests={manifest.id: SHA},
        promotion_approval_digests={manifest.id: SHA},
    )
    environment = EnvironmentSnapshotV1.create(
        resource_types=("process", "cpu"), features=()
    )
    baseline = mint_baseline_harness_lock(
        run_id="run-1",
        research_contract_digest=SHA,
        contract=contract,
        catalog=catalog,
        environment=environment,
        oracle_bundle_digest=SHA,
        suite=resolve_harness_suite(
            contract=contract, catalog=catalog, environment=environment
        ),
    )
    candidate = WorkspaceRefV1(root=str(tmp_path / "candidate"))
    payload = b"ELF fixture bytes"
    candidate.atomic_write_bytes("candidate.so", payload)
    declaration = HarnessTargetDeclarationV1.create(
        logical_name="candidate.so",
        target_kind="shared-library",
        subject_type="program",
        language="c",
        hardware="cpu",
        architecture="x86_64",
        dtype="float64",
        interface_contract="gemm-c-abi/v1",
        target_digest=bytes_digest(payload),
    )
    request = build_native_harness_run_request(
        run_id="run-1",
        node_id="node-1",
        epoch_id="epoch_000",
        workspace=candidate,
        execution_workspace=WorkspaceRefV1(root=str(tmp_path / "verification")),
        declaration=declaration,
        manifest=manifest,
        locked=baseline.harnesses[0],
        baseline=baseline,
    )
    return manifest, baseline, request


def _agent_harness_server():
    """The default-off MCP surface an agent may be given, loaded from source."""

    import importlib.util

    path = REPO_ROOT / "ari-skill-harness" / "src" / "server.py"
    spec = importlib.util.spec_from_file_location("ari_skill_harness_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tool_arguments(schema: dict, fixtures: dict) -> dict:
    """Arguments satisfying *schema*, so every declared tool is really driven.

    Built from the tool's own ``inputSchema`` rather than from a table written
    here: a tool added to the surface later is called by this test without
    anyone remembering to add it.  A pattern-constrained field has no generic
    value, so it fails loudly rather than letting the tool go unexercised.
    """

    arguments: dict = {}
    for name, field in (schema.get("properties") or {}).items():
        if name in fixtures:
            arguments[name] = fixtures[name]
            continue
        kind = field.get("type")
        if kind == "string":
            assert "pattern" not in field, (
                f"{name} is pattern-constrained; give the fixture a value so "
                f"this tool is exercised instead of erroring"
            )
            arguments[name] = "x"
        elif kind in {"integer", "number"}:
            arguments[name] = 1
        elif kind == "boolean":
            arguments[name] = False
        elif kind == "array":
            arguments[name] = []
        elif kind == "object":
            arguments[name] = {}
        else:
            raise AssertionError(f"no generic value for {name!r} of type {kind!r}")
    return arguments


def _tree_digests(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): bytes_digest(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_fixed_verifier_internal_execution(tmp_path, monkeypatch):
    """Task 20 criterion 62: Harness execution does not follow tool choice.

    The failure this forbids is not an agent calling a forbidden admin tool --
    criterion 55 covers that.  It is subtler: a run where the verification that
    admits a node is whichever verifier the agent happened to reach for, so the
    evidence is a self-report with a Harness-shaped envelope.  Independence has
    to hold at three places, and this binds all three.

    *Authority*: the constitutional matrix is read whole, so a future role that
    is granted ``harness_execution`` fails here rather than being outside a list
    written in this test.

    *Surface*: every tool the agent-facing Harness Provider declares is taken
    from its live ``list_tools`` and actually called, with the one entry point
    that can execute a Harness replaced by a tripwire.  A positive control at
    the end fires the tripwire deliberately, so "nothing executed" cannot mean
    "nothing could have".

    *Execution*: the Fixed Verifier is handed the manifest an agent would have
    chosen, a lock the Harness is absent from, and a driver that rewrites the
    locked command.  Each is refused before anything runs.
    """

    import asyncio

    from ari.assurance.runner import FixedVerifier, HarnessExecutionError

    # ── authority: exactly one holder, and no agent-tier role among them ─────
    holders = {
        key
        for key, grants in kernel_rules.CAPABILITY_MATRIX.items()
        if ("invoke", "harness_execution") in grants
    }
    assert holders == {("fixed_verifier", "fixed")}
    agent_keys = {key for key in kernel_rules.CAPABILITY_MATRIX if key[1] != "fixed"}
    assert agent_keys, "the capability matrix declares no evolvable role at all"
    assert not (agent_keys & holders)

    manifest, baseline, request = _locked_run(tmp_path)

    # ── execution: the lock decides, not the caller ──────────────────────────
    verifier = FixedVerifier(drivers={})
    assert verifier.prompt_hash is None
    assert verifier.component_id == "fixed_verifier_v1"

    def _run(**overrides):
        arguments = dict(
            manifest=manifest,
            request=request,
            baseline_lock=baseline,
            research_contract_digest=SHA,
            verification_contract_digest=SHA,
            knowledge_skill_use_digest=SHA,
            capability_binding_lock_digest=SHA,
            producer_epoch_id="epoch_000",
        )
        arguments.update(overrides)
        return verifier.run(**arguments)

    with pytest.raises(HarnessExecutionError, match="differs from lock"):
        _run(manifest=_verifiable_manifest("science/agent-chosen"))
    with pytest.raises(HarnessExecutionError, match="absent from baseline lock"):
        _run(baseline_lock=baseline.model_copy(update={"harnesses": ()}))

    class _RewritingDriver:
        """A driver that agrees on its identity and then changes the command."""

        def identity(self):
            return {"driver_digest": request.harness.driver_digest}

        def prepare(self, manifest, request):
            return None

        def build_request(self, manifest, request):
            return request.execution_request.model_copy(
                update={"argv": ["/bin/echo", "chosen-by-the-agent"]}
            )

        def normalize_result(self, manifest, request, result):
            raise AssertionError("a rewritten request reached the executor")

        def parity_probe(self, manifest):
            return {}

    def _explode(*_args, **_kwargs):
        raise AssertionError("a rewritten request reached the executor")

    rewriting = FixedVerifier(
        drivers={manifest.driver.revision: _RewritingDriver()}, executor=_explode
    )
    with pytest.raises(HarnessExecutionError, match="change locked ExecutionRequest"):
        rewriting.run(
            manifest=manifest,
            request=request,
            baseline_lock=baseline,
            research_contract_digest=SHA,
            verification_contract_digest=SHA,
            knowledge_skill_use_digest=SHA,
            capability_binding_lock_digest=SHA,
            producer_epoch_id="epoch_000",
        )

    # ── surface: drive every declared agent tool with the seam booby-trapped ──
    checkpoint = tmp_path / "checkpoint"
    attestation = _attestation()
    attestation_path = (
        checkpoint
        / "rqgm"
        / "kca"
        / "nodes"
        / "node_001"
        / "attestations"
        / f"{attestation.attestation_digest.removeprefix('sha256:')}.json"
    )
    attestation_path.parent.mkdir(parents=True)
    attestation_path.write_text(
        attestation.model_dump_json(), encoding="utf-8"
    )

    server = _agent_harness_server()
    monkeypatch.setattr(server, "_checkpoint", lambda: checkpoint)
    monkeypatch.setattr(server, "_manifests", lambda: [manifest.model_dump(mode="json")])
    monkeypatch.setattr(
        server,
        "_admission",
        lambda name: {
            "run_id": "run-1",
            "contract_digest": SHA,
            "requirements": [],
            "verification_contract_digest": SHA,
            "active_harness_lock_digest": baseline.lock_digest,
        },
    )

    executed: list[str] = []

    def _tripwire(*_args, **_kwargs):
        executed.append("FixedVerifier.run")
        raise AssertionError("a Harness was executed")

    monkeypatch.setattr(FixedVerifier, "run", _tripwire)

    before = _tree_digests(checkpoint)
    assert before, "the probe checkpoint holds no file to protect"
    live = asyncio.run(server.list_tools())
    assert live, "the agent Harness surface declares no tool at all"
    responses = {}
    for tool in live:
        arguments = _tool_arguments(
            tool.inputSchema,
            {
                "attestation_digest": attestation.attestation_digest,
                "harness_hint": "chosen/by-the-agent",
            },
        )
        rendered = asyncio.run(server.call_tool(tool.name, arguments))
        body = json.loads(rendered[0].text)
        assert "error" not in body, (tool.name, body)
        responses[tool.name] = body

    assert set(responses) == {tool.name for tool in live}
    assert executed == [], "an agent tool reached the Harness execution seam"
    assert _tree_digests(checkpoint) == before

    # The tripwire is live: "nothing executed" is a fact about the surface.
    with pytest.raises(AssertionError, match="a Harness was executed"):
        FixedVerifier(drivers={}).run()
    assert executed == ["FixedVerifier.run"]

    # The agent's own naming of a Harness survives only as a labelled hint.
    hint = responses["request_auxiliary_verification"]
    assert hint["authoritative"] is False
    assert hint["non_authoritative_harness_hint"] == "chosen/by-the-agent"
    assert hint["activation"] == "fixed-harness-resolver-required-at-epoch-boundary"

    # ── the human CLI is not a way around it either ──────────────────────────
    from typer.testing import CliRunner

    from ari.cli import app

    refused = CliRunner().invoke(app, ["harness", "suite", "run"])
    assert refused.exit_code != 0
    assert "Fixed Verifier" in refused.output


# ── criterion 37: an Attestation whose target is not the candidate is invalid ─


def _dotted(node) -> str:
    """``a.b.c`` for an attribute chain rooted at a name; ``""`` otherwise."""

    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    parts.append(node.id)
    return ".".join(reversed(parts))


def _attestation_target_references() -> set[str]:
    """Every target digest ``validate_attestation`` is handed besides the
    Attestation's own, derived from its SIGNATURE.

    Deliberately NOT read out of the comparisons the body performs.  An
    inventory taken from the checks shrinks exactly when a check is deleted, so
    a test driving it would follow the defect down and stay green -- measured:
    dropping the current-candidate half of the comparison left an
    AST-derived version of this test passing.  What the validator is GIVEN
    cannot shrink that way, so a reference that stops being compared is still
    driven here and still has to refuse.
    """

    subject = "attestation.target_digest"
    references: set[str] = set()
    for name, hint in typing.get_type_hints(validate_attestation).items():
        if name == "return":
            continue
        if name.endswith("target_digest"):
            references.add(name)
        elif (
            isinstance(hint, type)
            and issubclass(hint, BaseModel)
            and "target_digest" in hint.model_fields
        ):
            references.add(f"{name}.target_digest")
    return references - {subject}


def _validate_attestation_call_sites():
    """Every production call of ``validate_attestation``, with the expression
    each one passes as ``current_target_digest`` resolved one assignment deep.

    A comparison is only worth as much as the value it is handed.  Passing
    ``request.target_digest`` back in would make the current-target arm compare
    a number with itself and pass on every substituted candidate, at a call
    site that still looks exactly like a check.  So the call sites are
    enumerated from the source instead of being trusted, which is the guard
    against covering two of them and not the third.
    """

    import ari

    root = Path(ari.__file__).resolve().parent
    sites = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assigned = {
            target.id: ast.unparse(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _dotted(node.func).split(".")[-1] != "validate_attestation":
                continue
            passed = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            sites.append((
                str(path.relative_to(root)),
                {name: ast.unparse(value) for name, value in passed.items()},
                assigned,
            ))
    return sites


def test_attestation_target_digest(tmp_path):
    """An Attestation is invalid unless its target digest is the candidate's.

    Driven at every place production decides that -- the procedural validator
    every driver's result passes through, the Constitutional Kernel's Harness
    integrity pass, the Evidence Clerk that decides whether an Attestation may
    enter an evidence bundle, and the manuscript snapshot, where nothing raises
    and a wrong answer would simply be believed -- against an inventory of
    comparison sites read out of the source, so a fifth place fails this test
    until something drives it.

    Inside the validator the references the target must agree with come from
    its SIGNATURE, for the reason given on ``_attestation_target_references``,
    and each production call site is checked for handing it an independently
    obtained current target rather than one it already compares.
    """

    manifest, atom, locked, baseline, request, attestation = _verification_state(
        tmp_path
    )
    fixed = dict(
        attestation=attestation, request=request, baseline_lock=baseline,
        current_target_digest=request.target_digest,
    )
    validate_attestation(**fixed)  # the coherent quadruple is accepted

    references = _attestation_target_references()
    assert references, (
        "validate_attestation is handed no target to compare the Attestation "
        "against: the criterion has no mechanism left to bind"
    )
    substituted = {
        "request.target_digest": lambda: dict(
            request=_run_request(
                tmp_path / "substituted",
                locked=locked,
                atom=atom,
                active_lock_digest=baseline.lock_digest,
                target_digest=OTHER_TARGET_SHA,
            )
        ),
        "current_target_digest": lambda: dict(
            current_target_digest=OTHER_TARGET_SHA
        ),
    }
    undriven = references - set(substituted)
    assert not undriven, f"target reference nothing drives here: {sorted(undriven)}"
    for reference in sorted(references):
        with pytest.raises(ValueError, match="target digest"):
            validate_attestation(**dict(fixed, **substituted[reference]()))

    # And the Attestation's own claim: the same refusal from the other side.
    forged = _bound_attestation(
        request=request, baseline=baseline, manifest=manifest,
        target_digest=OTHER_TARGET_SHA,
    )
    with pytest.raises(ValueError, match="target digest"):
        validate_attestation(**dict(fixed, attestation=forged))

    # Every production caller hands it an INDEPENDENTLY obtained current
    # target. Echoing a value the validator already compares would leave a call
    # site that looks like a check and is not one.
    sites = _validate_attestation_call_sites()
    assert sites, "no production call of validate_attestation was found"
    for module, passed, assigned in sites:
        assert "current_target_digest" in passed, module
        echoes = {
            f"{passed[name]}.target_digest"
            for name in ("attestation", "request")
            if name in passed
        }
        expression = passed["current_target_digest"]
        assert expression not in echoes, module
        assert assigned.get(expression, expression) not in echoes, module

    # The Kernel, over the same documents. The code is never named here: it is
    # whatever appears when the candidate under the node is not the candidate
    # the Attestation describes, and disappears when it is.
    common = dict(
        verification_contract=_verification_contract().model_dump(mode="json"),
        baseline_lock=baseline.model_dump(mode="json"),
        catalog_snapshot=_harness_catalog((manifest,)),
        attestation=attestation.model_dump(mode="json"),
        request=request.model_dump(mode="json"),
    )
    agreed = _harness_codes(current_target_digest=request.target_digest, **common)
    assert agreed == set(), agreed
    moved = _harness_codes(current_target_digest=OTHER_TARGET_SHA, **common)
    assert _all_blocking(moved - agreed), moved

    # And the Evidence Clerk, which is where an Attestation becomes evidence.
    # Both of its target comparisons: the candidate the node holds now, and the
    # target the envelope advertises for the document it carries.
    record = _attestation_record(tmp_path)
    assert _exclusion_reason(record, tmp_path) is None
    assert _exclusion_reason(
        dict(record, current_node_target_digest=OTHER_SHA), tmp_path
    ) == "stale_target_attestation"
    # The envelope arm is isolated: the substituted document carries its own
    # correct digest and the record advertises it, so the only disagreement
    # left is the target -- otherwise the digest arm answers first and this
    # assertion would hold with the target comparison deleted.
    elsewhere = _attestation(target_digest=OTHER_TARGET_SHA)
    assert _exclusion_reason(
        dict(
            record,
            attestation=elsewhere.model_dump(mode="json"),
            attestation_digest=elsewhere.attestation_digest,
        ),
        tmp_path,
    ) == "attestation_envelope_mismatch"

    # And the manuscript snapshot, which is where an Attestation becomes a
    # published certification. An Attestation for another candidate is recorded
    # ``stale`` and does not certify -- the same claim at the other end of the
    # run, where nothing raises and a wrong answer would simply be believed.
    from types import SimpleNamespace

    from ari.manuscript.snapshot import _attestation_artifacts

    node_root = tmp_path / "manuscript"
    node_root.mkdir(parents=True, exist_ok=True)
    (node_root / "node.attestation.json").write_text(
        json.dumps(attestation.model_dump(mode="json")), encoding="utf-8"
    )

    def _snapshot(verified_target):
        node = SimpleNamespace(
            id=attestation.node_id,
            attestation_refs=("node.attestation.json",),
            verified_target_digest=verified_target,
        )
        return _attestation_artifacts(node_root, [node])[0]

    present = _snapshot(attestation.target_digest)
    assert present.status == "present"
    assert present.metadata["target_matches"] is True
    stale = _snapshot(OTHER_TARGET_SHA)
    assert stale.status == "stale", stale.status
    assert stale.metadata["target_matches"] is False
    assert stale.metadata["certify_pass"] is False

    # Every place production compares an Attestation target has been driven.
    driven = {
        ("assurance/attestation.py", "validate_attestation"),
        ("rqgm/kernel_harness_integrity.py", "_append_attestation_findings"),
        ("rqgm/governance/_evidence.py", "_harness_integrity_reason"),
        ("manuscript/snapshot.py", "_attestation_artifacts"),
    }
    compared = _comparison_sites("target_digest")
    assert compared, "nothing in production compares an Attestation target"
    undriven = compared - driven
    assert not undriven, f"target comparison nothing drives here: {sorted(undriven)}"


# ── criterion 38: a reused Attestation from a superseded Lock is detected ────


def _attestation_lock_pins() -> tuple[str, ...]:
    """Every field by which an Attestation names a Harness Lock it belongs to.

    Off the model, not off a list here: a third Lock pin added to
    ``HarnessAttestationV1`` is checked by this test without anyone
    remembering, and the day the last one goes the floor below fails.
    """

    return tuple(
        name
        for name in HarnessAttestationV1.model_fields
        if name.endswith("harness_lock_digest")
    )


def test_stale_attestation(tmp_path):
    """An Attestation minted under one Harness Lock cannot be re-presented
    under another.

    This is the cheapest possible forgery, because nothing about the document
    is wrong: it was minted by the fixed verifier, its digest still checks out,
    its target is still the candidate.  Only its Lock identity says it answers
    a question that is no longer the one being asked -- which is why the
    reuse below is a genuine re-presentation of a genuinely valid Attestation,
    not a tampered one.
    """

    manifest, atom, locked, baseline, request, attestation = _verification_state(
        tmp_path
    )
    fixed = dict(
        attestation=attestation, request=request, baseline_lock=baseline,
        current_target_digest=request.target_digest,
    )
    validate_attestation(**fixed)

    pins = _attestation_lock_pins()
    assert pins, "an Attestation no longer names the Harness Lock it belongs to"
    superseded_digest = canonical_digest("a-superseded-harness-lock")
    for pin in pins:
        stale = _bound_attestation(
            request=request, baseline=baseline, manifest=manifest,
            **{pin: superseded_digest},
        )
        assert stale.attestation_digest != attestation.attestation_digest
        with pytest.raises(ValueError, match="lock"):
            validate_attestation(**dict(fixed, attestation=stale))

    # THE REUSE ITSELF. The run revises its Lock; the Attestation from before
    # the revision is offered again, unchanged and still internally valid.
    successor = _harness_manifest(version="1.0.1")
    successor_locked = _locked_harness(successor, atom)
    revised = _baseline_lock(successor_locked, atom)
    assert revised.lock_digest != baseline.lock_digest
    revised_request = _run_request(
        tmp_path / "revised",
        locked=successor_locked,
        atom=atom,
        active_lock_digest=revised.lock_digest,
    )
    with pytest.raises(ValueError, match="stale"):
        validate_attestation(
            attestation=attestation,
            request=revised_request,
            baseline_lock=revised,
            current_target_digest=revised_request.target_digest,
        )

    # The Kernel reaches the same finding from the run's frozen active Lock
    # alone, without a request to compare against.
    common = dict(
        verification_contract=_verification_contract().model_dump(mode="json"),
        baseline_lock=baseline.model_dump(mode="json"),
        catalog_snapshot=_harness_catalog((manifest,)),
        attestation=attestation.model_dump(mode="json"),
        request=request.model_dump(mode="json"),
    )
    current = _harness_codes(
        active_harness_lock_digest=baseline.lock_digest,
        current_target_digest=request.target_digest,
        **common,
    )
    assert current == set(), current
    reused = _harness_codes(
        active_harness_lock_digest=revised.lock_digest,
        current_target_digest=request.target_digest,
        **common,
    )
    assert _all_blocking(reused - current), reused

    # And the Fixed Verifier refuses to EXECUTE under a request whose active
    # Lock is not the baseline it was handed, which is what stops a stale
    # Attestation from being minted rather than merely caught afterwards.
    from ari.assurance.runner import FixedVerifier, HarnessExecutionError

    verifier = FixedVerifier({}, executor=lambda *_a, **_k: None)
    minting = dict(
        manifest=manifest,
        baseline_lock=baseline,
        research_contract_digest=SHA,
        verification_contract_digest=SHA,
        knowledge_skill_use_digest=SHA,
        capability_binding_lock_digest=SHA,
        producer_epoch_id="epoch_000",
    )
    with pytest.raises(HarnessExecutionError, match="baseline lock"):
        verifier.run(
            request=_run_request(
                tmp_path / "mint-under-revision",
                locked=locked,
                atom=atom,
                active_lock_digest=revised.lock_digest,
            ),
            **minting,
        )

    # Every place production compares a Harness Lock identity on an Attestation
    # or on the request that produces one has been driven.
    driven = {
        ("assurance/attestation.py", "validate_attestation"),
        ("assurance/runner.py", "run"),
        ("rqgm/kernel_harness_integrity.py", "_append_attestation_findings"),
    }
    compared = _comparison_sites("harness_lock_digest", occurrences=1)
    assert compared, "nothing in production compares a Harness Lock identity"
    undriven = compared - driven
    assert not undriven, f"Lock comparison nothing drives here: {sorted(undriven)}"


# ── criterion 65: stale Skill, Binding and Attestation, each detected alone ──


_KCA_ENVIRONMENT = canonical_digest("kca-verification-environment")


def _kca_sealed(document: dict, field: str = "lock_digest") -> dict:
    """Reseal *field* over the document the way its mint computes it.

    Every document below is resealed over its own content, so no digest rule
    fires alongside and the ONLY thing wrong with a superseded artifact is
    which lock it belongs to.  That is also the honest threat: a superseded
    document was valid when it was written.
    """

    payload = {key: value for key, value in document.items() if key != field}
    return dict(payload, **{field: canonical_digest(payload)})


def _kca_skill_lock(*, epoch_id: str) -> dict:
    return _kca_sealed({
        "schema_version": "ari.epoch-knowledge-skill-lock/v1",
        "epoch_id": epoch_id,
        "admitted": [],
        "capability_requirements": [],
    })


def _kca_binding_lock(*, epoch_id: str) -> dict:
    return _kca_sealed({
        "schema_version": "ari.capability-binding-lock/v1",
        "run_id": "run-1",
        "epoch_id": epoch_id,
        "environment_digest": _KCA_ENVIRONMENT,
        "requirements": [],
        "bindings": [],
        "mode": "enforce",
        "producer_component_id": "capability_binder_v1",
        "prompt_hash": None,
    })


def _kca_harness_lock(*, suite_digest: str) -> dict:
    return _kca_sealed({
        "schema_version": "ari.baseline-harness-lock/v1",
        "run_id": "run-1",
        "research_contract_digest": SHA,
        "verification_contract_digest": SHA,
        "harness_catalog_snapshot_digest": SHA,
        "verification_environment_digest": _KCA_ENVIRONMENT,
        "oracle_bundle_digest": SHA,
        "suite_digest": suite_digest,
        "requirements": [],
        "unsatisfied_atom_digests": [],
        "harnesses": [],
        "coverage_proof_digest": SHA,
        "producer_component_id": "harness_resolver_v1",
        "prompt_hash": None,
    })


#: The three superseded-artifact axes, named by the artifact that is stale.
_STALE_AXES = ("skill", "binding", "attestation")


def _stale_axis_reports(root, *, superseded=()):
    """Drive the PRODUCTION per-node K/C/A fan-out over one node whose Skill
    lock, Binding Lock and Attestation are all current except those named.

    Entering at ``_kca_reports_for_node`` -- the fan-out
    ``run_per_node_kernel_check`` calls -- is what makes this a claim about the
    run rather than about three functions that happen to exist.
    """

    from types import SimpleNamespace

    from ari.rqgm.runtime import RQGMRuntime

    checkpoint = Path(root)
    node_root = checkpoint / "rqgm" / "kca" / "nodes" / "n1"
    node_root.mkdir(parents=True, exist_ok=True)

    current_skill = _kca_skill_lock(epoch_id="epoch_001")
    current_binding = _kca_binding_lock(epoch_id="epoch_001")
    current_harness = _kca_harness_lock(suite_digest=canonical_digest("suite-2"))
    skill_in_force = (
        _kca_skill_lock(epoch_id="epoch_000")
        if "skill" in superseded else current_skill
    )
    binding_in_force = (
        _kca_binding_lock(epoch_id="epoch_000")
        if "binding" in superseded else current_binding
    )
    attested_lock = (
        _kca_harness_lock(suite_digest=canonical_digest("suite-1"))["lock_digest"]
        if "attestation" in superseded else current_harness["lock_digest"]
    )

    (node_root / "knowledge_skill_use.json").write_text(
        json.dumps(_kca_sealed({
            "node_id": "n1",
            "epoch_id": "epoch_001",
            "epoch_lock_digest": skill_in_force["lock_digest"],
            "ordered_skills": [],
        }, "use_digest")),
        encoding="utf-8",
    )
    relative = "rqgm/kca/nodes/n1/node.attestation.json"
    (checkpoint / relative).write_text(
        json.dumps(_kca_sealed({
            "node_id": "n1",
            "producer_component_id": "fixed_verifier_v1",
            "producer_prompt_hash": None,
            "active_harness_lock_digest": attested_lock,
            "target_digest": TARGET_SHA,
            "verdict": "pass",
            "property_results": [],
        }, "attestation_digest")),
        encoding="utf-8",
    )

    runtime = RQGMRuntime.__new__(RQGMRuntime)
    runtime.checkpoint_dir = checkpoint
    runtime._admission_artifacts = SimpleNamespace(documents={
        "knowledge_skill_lock.json": skill_in_force,
        "knowledge_catalog_snapshot.json": {},
        "knowledge_bodies.json": {},
        "capability_binding_lock.json": binding_in_force,
        "provider_lock.json": {},
        "verification_contract.json": {},
        "baseline_harness_lock.json": current_harness,
        "harness_catalog_snapshot.json": {},
    })
    runtime._capability_authorization_view = None
    admission = SimpleNamespace(
        knowledge_skill_lock_digest=current_skill["lock_digest"],
        capability_binding_lock_digest=current_binding["lock_digest"],
        verification_contract_digest=SHA,
        verification_environment_digest=_KCA_ENVIRONMENT,
        baseline_harness_lock_digest=current_harness["lock_digest"],
        active_harness_lock_digest=current_harness["lock_digest"],
        modes=SimpleNamespace(
            knowledge="enforce", capability_binding="enforce", assurance="enforce"
        ),
    )
    node = SimpleNamespace(
        id="n1",
        attestation_refs=(relative,),
        verified_target_digest=TARGET_SHA,
        assurance_status="pass",
        property_verdicts={"numerical-equivalence": "pass"},
        frontier_class="scientific_frontier",
    )
    return runtime._kca_reports_for_node(
        ConstitutionalKernel(), admission, node, "n1"
    )


def test_three_stale_axes(tmp_path):
    """A superseded Skill lock, a superseded Binding Lock and a reused
    Attestation are three findings, not one.

    Independence is the whole claim, so it is not enough for a node with all
    three superseded to be refused: one rule firing would refuse it too, and
    the run would then be told the wrong thing about what went wrong -- and
    would keep passing on the two axes that had lost their detector.  So each
    artifact is superseded ALONE, and the finding it raises has to land in its
    own checker and nowhere else.

    The axis inventory is the set of report contexts the production fan-out
    actually emits, not a list of three written here: a fourth K/C/A axis would
    have to bring its own staleness case with it or fail the last assertion.
    """

    fresh = _stale_axis_reports(tmp_path / "fresh")
    contexts = {report.context for report in fresh}
    assert contexts, "the per-node K/C/A fan-out produced no report at all"
    assert not [
        violation for report in fresh for violation in report.violations
    ], [
        (report.context, violation.code, violation.detail)
        for report in fresh
        for violation in report.violations
    ]

    lit: dict[str, set[str]] = {}
    for axis in _STALE_AXES:
        found = {
            (report.context, violation.code)
            for report in _stale_axis_reports(tmp_path / axis, superseded=(axis,))
            for violation in report.violations
        }
        assert found, f"a superseded {axis} raised nothing"
        assert _all_blocking({code for _context, code in found}), (axis, found)
        lit[axis] = {context for context, _code in found}
        assert len(lit[axis]) == 1, (axis, found)

    for first, second in itertools.combinations(_STALE_AXES, 2):
        assert lit[first].isdisjoint(lit[second]), (first, second, lit)
    assert set().union(*lit.values()) == contexts, (lit, contexts)
