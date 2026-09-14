"""Bounded progress summaries and sanitized immutable run views."""

from __future__ import annotations

import math
from typing import Any

from .contracts import PrincipalV1
from .registry import RunRecord, RunRegistry
from .runtime import ServiceError, safe_json_file


def node_summary(record: RunRecord) -> tuple[int, int, str | None, float | None]:
    data: dict[str, Any] = {}
    for name in ("nodes_tree.json", "bfts_tree.json", "results.json"):
        value = safe_json_file(record.checkpoint_dir / name)
        if value is not None:
            data = value
            break
    nodes = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
    successful = 0
    best_id: str | None = None
    best_score: float | None = None
    for node_id, raw in nodes.items():
        if not isinstance(raw, dict):
            continue
        if raw.get("status") == "success":
            successful += 1
        score = raw.get("score", raw.get("eval_score"))
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            score = float(score)
            if math.isfinite(score) and (best_score is None or score > best_score):
                best_score = score
                best_id = str(node_id)
    return len(nodes), successful, best_id, best_score


def locked_view(
    registry: RunRegistry, run_id: str, principal: PrincipalV1
) -> dict[str, Any]:
    record = registry.get(run_id, principal)
    lock_path = record.checkpoint_dir / "SKILLS.lock"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ServiceError("run has no immutable SKILLS.lock")
    try:
        from ari.public.skill_lock import SkillsLockV1, skills_lock_digest
    except ImportError as exc:
        raise ServiceError("ari-core skill lock verifier is unavailable") from exc
    raw_lock = safe_json_file(lock_path, max_bytes=16 * 1024 * 1024)
    if raw_lock is None:
        raise ServiceError("SKILLS.lock is unreadable or exceeds its limit")
    try:
        lock = SkillsLockV1.model_validate(raw_lock)
    except ValueError as exc:
        raise ServiceError("SKILLS.lock failed schema validation") from exc
    if skills_lock_digest(lock) != lock.registry_digest:
        raise ServiceError("SKILLS.lock registry digest mismatch")
    if lock.run_id != run_id:
        raise ServiceError("SKILLS.lock belongs to a different run")
    return {
        "schema_version": lock.schema_version,
        "run_id": lock.run_id,
        "registry_digest": lock.registry_digest,
        "skills": [
            {
                "name": item.name,
                "package": item.package,
                "version": item.version,
                "provider_digest": item.provider_digest,
                "configured_phases": item.configured_phases,
                "tool_refs": item.tool_refs,
            }
            for item in lock.skills
        ],
        "tools": [
            {
                "tool_ref": item.tool_ref,
                "name": item.name,
                "skill_name": item.skill_name,
                "capability_ref": item.capability_ref,
                "input_schema_digest": item.input_schema_digest,
                "output_schema_digest": item.output_schema_digest,
            }
            for item in lock.tools
        ],
        "phase_active_tools": lock.phase_active_tools,
        "disabled_tools": lock.disabled_tools,
    }


__all__ = ["locked_view", "node_summary"]
