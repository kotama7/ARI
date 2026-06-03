"""Typed research-memory schema (ARI Verifiable Research Memory, Phase 1).

These are *thin index* records, not a second source of truth: provenance
(metrics / artifacts / commands / hardware) lives in ``node_report.json``
and on disk. A ``ResearchMemory`` therefore carries a ``node_report_ref``
pointer plus a searchable ``text`` and minimal artifact refs — it does not
re-store node_report fields. See ``PLAN_memory_inheritance.md`` §2, §4.

Dataclasses (not Pydantic) to match this skill's existing style
(``config.py``) and avoid a hard Pydantic dependency in the backend path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

MemoryKind = Literal[
    "observation",
    "experiment_result",
    "failure_case",
    "procedure",
    "reflection",
    "artifact_summary",
    "paper_claim",
    "reproducibility_event",
]
ReproStatus = Literal[
    "unverified",
    "rerun_passed",
    "rerun_failed",
    "paper_only_reproduced",
]

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


@dataclass
class ResearchMemory:
    """A thin, typed index record pointing at node_report + artifacts.

    ``text`` is the embedding/search target (a short NL claim). Heavy
    provenance is dereferenced from ``node_report_ref`` on demand.
    """

    id: str
    checkpoint_id: str
    node_id: str
    kind: str
    text: str
    ancestor_ids: list[str] = field(default_factory=list)
    node_report_ref: dict | None = None  # {"run_id", "node_id"}
    artifact_refs: list[ArtifactRef] = field(default_factory=list)
    metric_ptr: dict | None = None  # optional denormalized {name,value,unit}
    repro_target_id: str | None = None  # for kind == reproducibility_event
    repro_status: str | None = None
    confidence: float | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.kind not in MEMORY_KINDS:
            raise ValueError(
                f"unknown MemoryKind {self.kind!r}; expected one of {sorted(MEMORY_KINDS)}"
            )
        if self.repro_status is not None and self.repro_status not in REPRO_STATUSES:
            raise ValueError(
                f"unknown ReproStatus {self.repro_status!r}; "
                f"expected one of {sorted(REPRO_STATUSES)}"
            )
        if self.kind == "reproducibility_event" and not self.repro_target_id:
            raise ValueError("reproducibility_event requires repro_target_id")

    def has_artifacts(self) -> bool:
        return bool(self.artifact_refs)

    def to_metadata(self) -> dict:
        """Footer metadata for the Letta passage (Phase 2 adapter consumes this).

        ``mem_kind`` is promoted to a top-level key so ``_match`` /
        ``archival_list`` can filter on it server-side (PLAN §4.1). Heavy
        fields stay as refs, not copies of node_report.
        """
        return {
            "mem_kind": self.kind,
            "node_report_ref": self.node_report_ref,
            "artifact_refs": [a.to_dict() for a in self.artifact_refs],
            "metric_ptr": self.metric_ptr,
            "repro_target_id": self.repro_target_id,
            "repro_status": self.repro_status,
            "confidence": self.confidence,
        }
