"""Internal input helpers for the public ``MemoryRecordV1`` contract.

The stored schema lives in :mod:`ari.public.memory`.  ``ArtifactRef`` is only
an unverified candidate produced while reading a node report; the writer turns
it into a digest-checked ``MemoryArtifactRefV1`` before persistence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

MEMORY_KINDS: frozenset[str] = frozenset(
    {
        "observation",
        "experiment_result",
        "failure_case",
        "procedure",
        "reflection",
        "artifact_summary",
        "paper_claim",
        "reproducibility_event",
    }
)
REPRO_STATUSES: frozenset[str] = frozenset(
    {"unverified", "rerun_passed", "rerun_failed", "paper_only_reproduced"}
)


@dataclass
class ArtifactRef:
    """Pointer to an evidence artifact. ``sha256`` is None when not yet hashed."""

    path: str  # checkpoint/work_dir-relative
    sha256: str | None = None
    role: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)


__all__ = ["ArtifactRef", "MEMORY_KINDS", "REPRO_STATUSES"]
