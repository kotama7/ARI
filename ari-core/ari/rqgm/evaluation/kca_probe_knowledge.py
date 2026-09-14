"""Knowledge-layer production-path fixtures for Task-20 K/C/A probes."""

from __future__ import annotations

from ari.protocols.integrity import bytes_digest, canonical_digest
from ari.rqgm.kernel import ConstitutionalKernel


def _sealed(value: dict, field: str) -> dict:
    out = dict(value)
    out[field] = canonical_digest(out)
    return out


def knowledge_kernel_probe(mutation: str, *, clean: bool):
    body = "# Procedure\nUse semantic compile capability.\n"
    body_digest = bytes_digest(body.encode("utf-8"))
    source = {
        "repository": "https://example.invalid/knowledge",
        "commit": "a" * 40,
        "path": "knowledge-skills/hpc.gemm.optimization",
        "body_sha256": body_digest,
    }
    manifest = {
        "schema_version": 1,
        "id": "hpc.gemm.optimization",
        "version": "1.0.0",
        "status": "verified",
        "source": source,
        "authority_ceiling": {
            "side_effects": ["read-only", "workspace-write"]
        },
        "forbidden_capabilities": [],
    }
    source["manifest_sha256"] = canonical_digest(manifest)
    requirement = {
        "capability_ref": "ari.execution.compile/v1",
        "side_effect_ceiling": "workspace-write",
        "source_requirement_refs": ["knowledge:" + body_digest],
    }
    status = "verified"
    bodies = {body_digest: body}
    expected_lock_digest = None
    previous_use = None
    attachment_launch = False
    directives: tuple[str, ...] = ()

    if not clean:
        if mutation == "privilege_escalation_instruction":
            directives = ("authority_escalation",)
        elif mutation == "forbidden_capability":
            manifest["forbidden_capabilities"] = [
                "ari.execution.compile/v1"
            ]
            source.pop("manifest_sha256", None)
            source["manifest_sha256"] = canonical_digest(manifest)
        elif mutation == "unpinned_source":
            source["commit"] = "latest"
            source.pop("manifest_sha256", None)
            source["manifest_sha256"] = canonical_digest(manifest)
        elif mutation == "body_digest_mutation":
            bodies = {body_digest: body + "tampered"}
        elif mutation == "revoked_skill_use":
            status = "revoked"
        elif mutation == "hidden_executable_launch":
            attachment_launch = True
        elif mutation == "verification_bypass_instruction":
            directives = ("harness_bypass",)

    entry = {
        "manifest": manifest,
        "status": status,
        "entry_digest": canonical_digest(
            {"manifest": manifest, "status": status}
        ),
    }
    ref = {
        "id": manifest["id"],
        "version": manifest["version"],
        "body_sha256": source["body_sha256"],
        "manifest_sha256": source["manifest_sha256"],
    }
    composition_digest = canonical_digest({"ordered": [body_digest]})
    lock = _sealed(
        {
            "epoch_id": "epoch_000",
            "admitted": [ref],
            "capability_requirements": [requirement],
        },
        "lock_digest",
    )
    use = _sealed(
        {
            "node_id": "node_001",
            "epoch_id": "epoch_000",
            "epoch_lock_digest": lock["lock_digest"],
            "ordered_skills": [ref],
            "knowledge_composition_digest": composition_digest,
        },
        "use_digest",
    )
    if not clean and mutation == "stale_skill_lock":
        expected_lock_digest = canonical_digest("new-lock")
    if not clean and mutation == "mid_node_skill_substitution":
        previous_use = dict(
            use, knowledge_composition_digest=canonical_digest("old-body")
        )

    return ConstitutionalKernel().validate_knowledge_integrity(
        node_use=use,
        epoch_lock=lock,
        catalog_snapshot={"entries": [entry]},
        body_by_sha256=bodies,
        composition_digest=composition_digest,
        expected_epoch_lock_digest=expected_lock_digest,
        previous_node_use=previous_use,
        actor=("generator", "institutional"),
        attachment_launch=attachment_launch,
        effective_directives=directives,
    )


def _knowledge_manifest(*, skill_id: str, conflicts=()):
    from ari.knowledge.models import (
        KnowledgeAuthorityCeilingV1,
        KnowledgeCapabilityRequirementV1,
        KnowledgeCapabilitySetV1,
        KnowledgeCompositionV1,
        KnowledgeSkillApplicabilityV1,
        KnowledgeSkillManifestV1,
        KnowledgeSkillSourceV1,
    )

    return KnowledgeSkillManifestV1(
        id=skill_id,
        version="1.0.0",
        title=skill_id,
        description="deterministic evaluation fixture",
        status="verified",
        source=KnowledgeSkillSourceV1(
            repository="https://example.invalid/knowledge",
            commit="a" * 40,
            path="knowledge-skills/" + skill_id,
            body_sha256=bytes_digest((skill_id + "\n").encode()),
            manifest_sha256="sha256:" + "1" * 64,
        ),
        license={"body": "MIT", "references": "MIT"},
        applies_to=KnowledgeSkillApplicabilityV1(
            roles=("generator",), phases=("bfts",), task_tags=("eval",)
        ),
        requires=KnowledgeCapabilitySetV1(
            capabilities=(
                KnowledgeCapabilityRequirementV1(
                    ref="ari.execution.compile/v1", required=True
                ),
            )
        ),
        authority_ceiling=KnowledgeAuthorityCeilingV1(
            side_effects=("read-only", "workspace-write")
        ),
        conflicts=tuple(conflicts),
        composition=KnowledgeCompositionV1(
            slot="domain-method", priority=100
        ),
    )


def knowledge_admission_probe(mutation: str, *, clean: bool):
    from ari.capability_binding.models import (
        CapabilityContractV1,
        CapabilityOntologySnapshotV1,
    )
    from ari.knowledge.catalog import build_catalog_snapshot
    from ari.knowledge.models import (
        KnowledgeAdmissionContextV1,
        KnowledgeSkillEntryV1,
        KnowledgeSkillSelectionProposalV1,
    )
    from ari.knowledge.resolver import admit_knowledge_skills

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
    contracts = (
        ()
        if not clean and mutation == "unavailable_tool_name"
        else (contract,)
    )
    ontology = CapabilityOntologySnapshotV1.create(
        source_revision="eval/v1",
        property_vocabulary_version="v1",
        contracts=contracts,
    )
    first = _knowledge_manifest(
        skill_id="hpc.eval.primary",
        conflicts=(
            ("hpc.eval.secondary",)
            if not clean and mutation == "conflicting_skill_composition"
            else ()
        ),
    )
    manifests = [first]
    if not clean and mutation == "conflicting_skill_composition":
        manifests.append(_knowledge_manifest(skill_id="hpc.eval.secondary"))
    entries = tuple(
        KnowledgeSkillEntryV1.create(
            manifest=item,
            body_store_key=item.source.body_sha256,
            registration_report_digest="sha256:" + "2" * 64,
            importer_version="eval/v1",
            status="verified",
        )
        for item in manifests
    )
    catalog = build_catalog_snapshot(
        catalog_source_revision="eval/v1",
        importer_version="eval/v1",
        entries=entries,
    )
    proposal = KnowledgeSkillSelectionProposalV1.create(
        run_id="eval-run",
        epoch_id="epoch_000",
        research_contract_digest="sha256:" + "3" * 64,
        proposed=tuple(item.exact_ref() for item in manifests),
        reason="Task-20 deterministic admission probe",
        router_component_id="proposal_router_v1",
        router_prompt_hash=None,
    )
    context = KnowledgeAdmissionContextV1.create(
        role="generator",
        phase="bfts",
        task_tags=("eval",),
        permitted_side_effects=("read-only", "workspace-write"),
        property_vocabulary=("numerical-equivalence",),
    )
    lock = admit_knowledge_skills(
        proposal=proposal,
        catalog=catalog,
        ontology=ontology,
        context=context,
        mode="audit",
    )
    codes = {item.code for item in (*lock.rejected, *lock.unsatisfied)}
    channels = []
    if "unknown_capability" in codes:
        channels.append("knowledge.unsatisfied_capability")
    if codes & {"composition_conflict", "exclusive_slot_conflict"}:
        channels.append("knowledge.conflict_rejected")
    record = {
        "record_type": "knowledge_admission_report",
        "lock_digest": lock.lock_digest,
        "finding_codes": sorted(codes),
        "admitted": [item.model_dump(mode="json") for item in lock.admitted],
    }
    record_types = ("knowledge_admission_report",) if channels else ()
    return tuple(sorted(channels)), record_types, record


__all__ = ["knowledge_admission_probe", "knowledge_kernel_probe"]
