"""Knowledge use provenance validation."""

from __future__ import annotations

from ari.knowledge.models import (
    EpochKnowledgeSkillLockV1,
    KnowledgeSkillUseRecordV1,
    NodeKnowledgeSkillUseV1,
)


def validate_knowledge_use(
    *,
    lock: EpochKnowledgeSkillLockV1,
    node_use: NodeKnowledgeSkillUseV1,
    record: KnowledgeSkillUseRecordV1,
) -> None:
    if node_use.epoch_lock_digest != lock.lock_digest:
        raise ValueError("node use references a stale Knowledge lock")
    if record.node_use_digest != node_use.use_digest:
        raise ValueError("Knowledge use record does not match frozen node use")
    if tuple(item.body_sha256 for item in node_use.ordered_skills) != (
        record.instruction_identity.ordered_knowledge_skill_hashes
    ):
        raise ValueError("instruction identity differs from used Knowledge bodies")
    if node_use.knowledge_composition_digest != (
        record.instruction_identity.knowledge_composition_digest
    ):
        raise ValueError("Knowledge composition digest mismatch")


__all__ = ["validate_knowledge_use"]
