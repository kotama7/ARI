"""RQGM bridge for Knowledge proposal, fixed admission, use, and provenance."""

from __future__ import annotations

import re
from pathlib import Path

from ari.knowledge.composition import compose_knowledge_instructions
from ari.knowledge.models import (
    EpochKnowledgeSkillLockV1,
    InstructionCompositionV1,
    KnowledgeAdmissionContextV1,
    KnowledgeSkillCatalogSnapshotV1,
    KnowledgeSkillSelectionProposalV1,
    KnowledgeSkillUseRecordV1,
    NodeKnowledgeSkillUseV1,
)
from ari.knowledge.resolver import admit_knowledge_skills
from ari.protocols.immutable_store import write_once_json


class RQGMKnowledgeBridge:
    """Connect non-actor Knowledge artifacts to one frozen RQGM epoch."""

    def __init__(
        self,
        *,
        catalog: KnowledgeSkillCatalogSnapshotV1,
        epoch_lock: EpochKnowledgeSkillLockV1,
        body_by_sha256: dict[str, str],
        checkpoint_dir: str | Path,
    ) -> None:
        self.catalog = catalog
        self.epoch_lock = epoch_lock
        self.body_by_sha256 = dict(body_by_sha256)
        self.checkpoint_dir = Path(checkpoint_dir)

    @classmethod
    def from_admission(cls, artifacts, *, checkpoint_dir: str | Path):
        documents = artifacts.documents
        return cls(
            catalog=KnowledgeSkillCatalogSnapshotV1.model_validate(
                documents["knowledge_catalog_snapshot.json"]
            ),
            epoch_lock=EpochKnowledgeSkillLockV1.model_validate(
                documents["knowledge_skill_lock.json"]
            ),
            body_by_sha256={
                str(key): str(value)
                for key, value in dict(documents.get("knowledge_bodies.json") or {}).items()
            },
            checkpoint_dir=checkpoint_dir,
        )

    @staticmethod
    def propose_applicable(
        *,
        run_id: str,
        epoch_id: str,
        research_contract_digest: str,
        catalog: KnowledgeSkillCatalogSnapshotV1,
        context: KnowledgeAdmissionContextV1,
        router_prompt_hash: str | None,
        required: bool = False,
    ) -> KnowledgeSkillSelectionProposalV1:
        """Router proposal over exact verified entries; still non-authoritative."""

        proposed = []
        for entry in catalog.entries:
            manifest = entry.manifest
            if entry.status != "verified":
                continue
            if context.role not in manifest.applies_to.roles:
                continue
            if context.phase not in manifest.applies_to.phases:
                continue
            if manifest.applies_to.task_tags and not (
                set(manifest.applies_to.task_tags) & set(context.task_tags)
            ):
                continue
            proposed.append(manifest.exact_ref())
        proposed.sort(key=lambda item: (item.id, item.version, item.body_sha256))
        return KnowledgeSkillSelectionProposalV1.create(
            run_id=run_id,
            epoch_id=epoch_id,
            research_contract_digest=research_contract_digest,
            proposed=tuple(proposed),
            scope="epoch",
            required=required,
            reason="existing RQGM Router applicability proposal over the frozen catalog",
            router_component_id="proposal_router_v1",
            router_prompt_hash=router_prompt_hash,
        )

    @staticmethod
    def fixed_admit(*, proposal, catalog, ontology, context, mode):
        """The prompt-free ``knowledge_binder_v1`` resolution call."""

        return admit_knowledge_skills(
            proposal=proposal,
            catalog=catalog,
            ontology=ontology,
            context=context,
            mode=mode,
        )

    def prepare_node(
        self,
        *,
        node,
        experiment: dict,
        base_prompt: str,
        base_prompt_hash: str,
        active_rqgm_prompt_hashes: tuple[str, ...],
        capability_binding_lock_digest: str,
        verification_contract_digest: str,
        active_harness_lock_digest: str,
        subset_sha256: tuple[str, ...] | None = None,
    ) -> tuple[NodeKnowledgeSkillUseV1, InstructionCompositionV1]:
        """Freeze the node subset before AgentLoop and persist its provenance."""

        rendered, node_use, instruction = compose_knowledge_instructions(
            lock=self.epoch_lock,
            body_by_sha256=self.body_by_sha256,
            run_id=self.epoch_lock.run_id,
            node_id=str(node.id),
            base_prompt_hash=base_prompt_hash,
            base_prompt=base_prompt,
            active_rqgm_prompt_hashes=active_rqgm_prompt_hashes,
            capability_binding_lock_digest=capability_binding_lock_digest,
            verification_contract_digest=verification_contract_digest,
            active_harness_lock_digest=active_harness_lock_digest,
            subset_sha256=subset_sha256,
        )
        statuses = {
            item.manifest.source.body_sha256: item.status
            for item in self.catalog.entries
            if item.manifest.source.body_sha256
            in {ref.body_sha256 for ref in node_use.ordered_skills}
        }
        record = KnowledgeSkillUseRecordV1.create(
            run_id=node_use.run_id,
            node_id=node_use.node_id,
            epoch_id=node_use.epoch_id,
            component_id=str(getattr(node, "producer_component_id", "") or "generator_v1"),
            component_prompt_hash=str(
                getattr(node, "producer_prompt_hash", "") or ""
            ) or None,
            node_use_digest=node_use.use_digest,
            instruction_identity=instruction,
            knowledge_skill_status_at_use=statuses,
            capability_binding_lock_digest=capability_binding_lock_digest,
            verification_contract_digest=verification_contract_digest,
            active_harness_lock_digest=active_harness_lock_digest,
        )
        node_id = str(node.id)
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", node_id)
            or node_id in {".", ".."}
        ):
            raise ValueError("unsafe node identity for Knowledge provenance")
        node_root = self.checkpoint_dir / "rqgm" / "kca" / "nodes" / node_id
        write_once_json(node_root / "knowledge_skill_use.json", node_use)
        write_once_json(node_root / "instruction_identity.json", instruction)
        write_once_json(node_root / "knowledge_skill_use_record.json", record)
        experiment["_ari_knowledge_instruction"] = rendered
        node.knowledge_skill_refs = [item.model_dump(mode="json") for item in node_use.ordered_skills]
        node.knowledge_skill_use_digest = node_use.use_digest
        node.instruction_identity_digest = instruction.instruction_digest
        return node_use, instruction


__all__ = ["RQGMKnowledgeBridge"]
