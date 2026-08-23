"""Deterministic prompt composition for already-admitted Knowledge bodies."""

from __future__ import annotations

from xml.sax.saxutils import escape

from ari.knowledge.models import (
    EpochKnowledgeSkillLockV1,
    InstructionCompositionV1,
    NodeKnowledgeSkillUseV1,
)
from ari.protocols.integrity import bytes_digest, canonical_digest


def compose_knowledge_instructions(
    *,
    lock: EpochKnowledgeSkillLockV1,
    body_by_sha256: dict[str, str],
    run_id: str,
    node_id: str,
    base_prompt_hash: str,
    base_prompt: str,
    active_rqgm_prompt_hashes: tuple[str, ...],
    capability_binding_lock_digest: str,
    verification_contract_digest: str,
    active_harness_lock_digest: str,
    subset_sha256: tuple[str, ...] | None = None,
) -> tuple[str, NodeKnowledgeSkillUseV1, InstructionCompositionV1]:
    """Render data-bounded bodies; concrete tool text has no authority effect."""

    admitted = {
        item.body_sha256: item for item in lock.admitted
    }
    order = subset_sha256 or tuple(item.body_sha256 for item in lock.admitted)
    if len(order) != len(set(order)) or any(item not in admitted for item in order):
        raise ValueError("node subset must be a unique subset of the epoch lock")
    blocks: list[str] = []
    refs = []
    for digest in order:
        body = body_by_sha256.get(digest)
        if body is None or bytes_digest(body.encode("utf-8")) != digest:
            raise ValueError("Knowledge body missing or digest-mismatched")
        ref = admitted[digest]
        refs.append(ref)
        blocks.append(
            '<knowledge-skill skill_id="{}" skill_sha256="{}" '
            'authority="instruction-only">\n{}\n</knowledge-skill>'.format(
                escape(ref.id, {'"': "&quot;"}),
                digest,
                escape(body, {'"': "&quot;"}),
            )
        )
    rendered = "\n\n".join(blocks)
    composition_digest = canonical_digest(
        {
            "ordered_skill_hashes": list(order),
            "rendered_sha256": bytes_digest(rendered.encode("utf-8")),
        }
    )
    node_use = NodeKnowledgeSkillUseV1.create(
        run_id=run_id,
        node_id=node_id,
        epoch_id=lock.epoch_id,
        epoch_lock_digest=lock.lock_digest,
        ordered_skills=tuple(refs),
        knowledge_composition_digest=composition_digest,
    )
    identity = InstructionCompositionV1.create(
        base_prompt_hash=base_prompt_hash,
        base_prompt_sha256=bytes_digest(base_prompt.encode("utf-8")),
        active_rqgm_prompt_hashes=active_rqgm_prompt_hashes,
        ordered_knowledge_skill_hashes=order,
        knowledge_composition_digest=composition_digest,
        capability_binding_lock_digest=capability_binding_lock_digest,
        verification_contract_digest=verification_contract_digest,
        active_harness_lock_digest=active_harness_lock_digest,
    )
    return rendered, node_use, identity


__all__ = ["compose_knowledge_instructions"]
