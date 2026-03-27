"""Node definition and state management for BFTS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ABANDONED = "abandoned"


class NodeLabel(str, Enum):
    """Label indicating the exploration purpose of each node.

    Automatically assigned by LLM during BFTS expand() based on the parent node state.
    loop.py injects a system prompt corresponding to the label.
    """
    DRAFT      = "draft"       # New implementation / first attempt
    IMPROVE    = "improve"     # Improve parent node results
    DEBUG      = "debug"       # Debug parent node failures/errors
    ABLATION   = "ablation"    # Ablation by varying parent node configuration
    VALIDATION = "validation"  # Validate parent node results (multiple seeds, etc.)

    @classmethod
    def from_str(cls, s: str) -> "NodeLabel":
        try:
            return cls(s.lower())
        except ValueError:
            return cls.DRAFT

    def system_hint(self) -> str:
        """Hint text appended to the system prompt by loop.py."""
        hints = {
            NodeLabel.DRAFT: (
                "This is a DRAFT node. Implement the experiment from scratch. "
                "Focus on getting a working baseline result."
            ),
            NodeLabel.IMPROVE: (
                "This is an IMPROVE node. The parent experiment succeeded. "
                "Your goal is to beat the parent's metrics by tuning parameters, "
                "compiler flags, or algorithms."
            ),
            NodeLabel.DEBUG: (
                "This is a DEBUG node. The parent experiment failed or produced no real data. "
                "Diagnose the error, fix the script, and resubmit."
            ),
            NodeLabel.ABLATION: (
                "This is an ABLATION node. Remove or disable one component/flag from the parent "
                "and measure the impact. Report the delta vs parent metrics."
            ),
            NodeLabel.VALIDATION: (
                "This is a VALIDATION node. Your goal is to rigorously verify the parent node's "
                "claims. This includes but is not limited to: "
                "(1) Re-running with different random seeds to check variance; "
                "(2) Intentionally injecting wrong/corrupted inputs to verify error detection; "
                "(3) Testing boundary/edge cases (e.g., 1 thread, max threads, empty input); "
                "(4) Stress testing under extreme conditions; "
                "(5) Checking that disabling an optimization degrades performance as expected. "
                "Report pass/fail for each validation scenario and highlight any unexpected results."
            ),
        }
        return hints.get(self, "")




@dataclass
class Node:
    id: str
    parent_id: str | None
    depth: int
    status: NodeStatus = NodeStatus.PENDING
    retry_count: int = 0
    memory_snapshot: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    trace_log: list[str] = field(default_factory=list)  # tool call trace for viz
    error_log: str | None = None
    # Evaluation results: raw metric values (used for LLM selection)
    metrics: dict = field(default_factory=dict)
    has_real_data: bool = False
    eval_summary: str | None = None  # LLM evaluation comment
    label: NodeLabel = NodeLabel.DRAFT  # Exploration purpose label
    name: str = ""  # Human-readable short name (set after hypothesis is known)
    ancestor_ids: list[str] = field(default_factory=list)
    # ancestor_ids: list of node IDs from root to parent of self (self not included)
    # = [root_id, depth1_id, ..., parent_id]
    # Only memories within this range can be accessed via search_memory
    children: list[str] = field(default_factory=list)
    created_at: str = ""
    completed_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def mark_running(self) -> None:
        self.status = NodeStatus.RUNNING

    def mark_success(self, artifacts: list[dict] | None = None, eval_summary: str | None = None) -> None:
        self.status = NodeStatus.SUCCESS
        self.completed_at = datetime.now(timezone.utc).isoformat()
        if artifacts:
            self.artifacts = artifacts
        if eval_summary:
            self.eval_summary = eval_summary

    def mark_failed(self, error_log: str | None = None) -> None:
        self.status = NodeStatus.FAILED
        self.completed_at = datetime.now(timezone.utc).isoformat()
        if error_log:
            self.error_log = error_log

    def mark_abandoned(self) -> None:
        self.status = NodeStatus.ABANDONED
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "depth": self.depth,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "children": self.children,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "artifacts": self.artifacts,
            "metrics": self.metrics,
            "has_real_data": self.has_real_data,
            "eval_summary": self.eval_summary,
            "label": self.label.value,
            "name": self.name,
            "error_log": self.error_log,
            "ancestor_ids": self.ancestor_ids,
            "trace_log": self.trace_log[-200:],  # last 200 entries (avoid huge JSON)
        }
