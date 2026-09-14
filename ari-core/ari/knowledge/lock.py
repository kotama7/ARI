"""Atomic immutable persistence for epoch Knowledge locks."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ari.knowledge.models import EpochKnowledgeSkillLockV1
from ari.protocols.integrity import canonical_json_bytes


def write_or_verify_knowledge_lock(
    path: str | Path, lock: EpochKnowledgeSkillLockV1
) -> EpochKnowledgeSkillLockV1:
    target = Path(path)
    expected = canonical_json_bytes(lock) + b"\n"
    if target.exists():
        if target.is_symlink() or target.read_bytes() != expected:
            raise ValueError("immutable Knowledge lock mismatch")
        return EpochKnowledgeSkillLockV1.model_validate_json(target.read_bytes())
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".knowledge-lock-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return lock


__all__ = ["write_or_verify_knowledge_lock"]
