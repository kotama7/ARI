"""Acceptance-criteria suite for the K/C/A separation (Task 20 section 8).

Task 20 names ``test_kca_acceptance.py`` as one of its CI suites and gives each
acceptance criterion a required test id.  This module binds the criteria whose
BEHAVIOUR already exists and already refuses, and whose only gap was that
nothing asserted the refusal:

* 44 ``test_evidence_clerk_attestation_validation``
* 56 ``test_revocation_history_append_only``
* 60 ``test_skill_harness_selection_separation``
* 61 ``test_provider_cannot_attest``
* 66 ``test_three_catalog_revocation_append_only``
* 48 ``test_fixed_resolution_purity`` (Resolver + Kernel)
* 14 ``test_knowledge_binder_purity`` (the Knowledge Binder), which the same
  scanner closes because it is the same property over a different module set.

Each test names the production mechanism it binds, so that deleting the
mechanism turns the test red rather than leaving it vacuously green.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ari.assurance.models import (
    HarnessAttestationV1,
    HarnessPropertyResultV1,
    VerificationRequirementV1,
    VerificationScopeV1,
)
from ari.assurance.suite import mint_verification_contract, obligations_to_requirements
from ari.capability_binding.models import (
    CapabilityContractV1,
    CapabilityOntologySnapshotV1,
)
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
from ari.protocols.scientific_requirements import EvaluationObligationV1
from ari.providers.models import ProviderCatalogEntryV1, ProviderSourceV1
from ari.rqgm.governance._evidence import assemble_evidence_bundle


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
    ``_harness_integrity_reason`` in ``ari/rqgm/governance/_evidence.py``.  The
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
