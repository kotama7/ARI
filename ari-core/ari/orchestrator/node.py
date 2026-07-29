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

    Automatically assigned by LLM during BFTS expand() based on the parent
    node state. loop.py injects a system prompt corresponding to the label.

    The five canonical labels (DRAFT / IMPROVE / DEBUG / ABLATION /
    VALIDATION) capture the bulk of useful next steps. ``NodeLabel.OTHER``
    is the catch-all for LLM-proposed custom labels (e.g. ``replication``,
    ``generalization``) — the verbatim string is preserved in
    :attr:`Node.raw_label` so downstream consumers can still surface it.
    """
    DRAFT      = "draft"       # New implementation / first attempt
    IMPROVE    = "improve"     # Improve parent node results
    DEBUG      = "debug"       # Debug parent node failures/errors
    ABLATION   = "ablation"    # Ablation by varying parent node configuration
    VALIDATION = "validation"  # Validate parent node results (multiple seeds, etc.)
    OTHER      = "other"       # LLM-invented label (e.g. replication, generalization);
                               # the original string is kept on Node.raw_label

    @classmethod
    def from_str(cls, s: str) -> "NodeLabel":
        try:
            return cls(s.lower())
        except (ValueError, AttributeError):
            return cls.OTHER

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
            NodeLabel.OTHER: (
                "This node uses a custom exploration label proposed by the planner. "
                "Carry out the experimental direction described in eval_summary, "
                "treating it as the primary instruction."
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
    # Objective per-case facts returned by the deterministic harness. Kept
    # outside ``metrics`` because these records contain validity plus
    # harness-defined observations, while BFTS metrics are ranking quantities.
    evaluation_cases: dict = field(default_factory=dict)
    # Typed evaluator outcome. ``infrastructure_error`` is never a scientific
    # zero and causes the study driver to fail/exclude the run.
    evaluation_status: str = ""
    # Raw per-repetition timings and effective compile flags. Kept out of
    # ``to_dict``/tree.json to avoid duplicating a potentially large audit record;
    # node_report.json is its canonical storage location.
    measurement_audit: dict = field(default_factory=dict)
    # Reason returned by the evaluator. This is deliberately separate from
    # ``eval_summary``, which is legacy state that may temporarily hold an
    # LLM-generated exploration direction before evaluation.
    evaluator_reason: str = ""
    eval_summary: str | None = None  # LLM evaluation comment
    label: NodeLabel = NodeLabel.DRAFT  # Exploration purpose label
    raw_label: str = ""  # Original LLM-proposed label (preserved when label==OTHER)
    name: str = ""  # Human-readable short name (set after hypothesis is known)
    ancestor_ids: list[str] = field(default_factory=list)
    # ancestor_ids: list of node IDs from root to parent of self (self not included)
    # = [root_id, depth1_id, ..., parent_id]
    # Only memories within this range can be accessed via search_memory
    children: list[str] = field(default_factory=list)
    created_at: str = ""
    completed_at: str = ""
    # Direction text decided by the parent's expand() LLM call. Preserved
    # verbatim through the lifetime of the node so downstream consumers can
    # see "what we set out to do" even after evaluator overwrites eval_summary.
    original_direction: str | None = None
    # The agent's own natural-language self-report (the ``summary`` field it
    # returns when it concludes). Captured so the handoff summary can carry the
    # agent's narrative of what it did, anchored by deterministic metrics.
    agent_summary: str = ""
    # The agent's own self-reviewed next steps (LLM self-review) — what it would
    # try next to improve this node. Populates node_report ``next_steps_hints``
    # under deterministic scoring, where the evaluator emits no graded axes.
    agent_next_steps: list[str] = field(default_factory=list)
    # The agent's own self-reviewed concerns (LLM self-review) — caveats/risks it
    # flags about this node. Populates node_report ``self_assessment.concerns``
    # (the headline there comes from ``agent_summary``); deterministic scoring
    # emits no graded axes, so this is the real source.
    agent_concerns: list[str] = field(default_factory=list)
    # The agent's own free-form note of the compute environment it actually ran
    # on (compilers, ISA, CPU/GPU it used), authored AFTER querying the real env
    # (describe_environment / run_bash) and kept only when grounded in this
    # node's tool outputs (anti-fabrication). Replaces the framework's old
    # auto-scraped machine provenance in node_report, so no hostname/partition is
    # embedded automatically; the agent records only what it chose to.
    agent_environment: str = ""
    # The agent's own light per-file explanation ({path: note}) from the finish
    # JSON ``file_notes``. The node_report builder grafts each note onto the
    # matching files_changed entry (added/modified/deleted), so a reader sees WHAT
    # each touched file is without opening it. Best-effort; unlisted files carry
    # no note.
    file_notes: dict = field(default_factory=dict)
    # How the ReAct loop ended, and how many iterations it really took.
    # ``ended_by``: "finish_json" (the agent concluded) | "max_steps" (it ran out
    # of budget; any resulting ``success`` came from the framework scoring the
    # work_dir, not from the agent). Surfaced in full_log — without them a reader
    # cannot tell the two apart, and the old ``steps`` field counted TRACE ENTRIES
    # (2 per iteration), which read as double the real count.
    react_steps_used: int = 0
    ended_by: str = ""
    # Full ReAct conversation (system prompt + injected handoff + task + every
    # user/assistant/tool turn) — a live reference set by AgentLoop.run so the
    # per-node ``full_log.json`` can serialize the COMPLETE input+output record,
    # not just the tool-call trace_log. Deliberately EXCLUDED from ``to_dict`` so
    # it never bloats tree.json; it lands only in full_log.json.
    full_messages: list = field(default_factory=list)
    # OpenAI-format tool schemas (name + description + parameters) the model was
    # actually given via the function-calling ``tools=`` argument — i.e. HOW to
    # use each tool, which the AVAILABLE TOOLS prompt line (names only) omits.
    # Set by AgentLoop.run for full_log.json; EXCLUDED from to_dict.
    full_tools: list = field(default_factory=list)
    # Tool-less auxiliary LLM calls made after the main ReAct conversation, such
    # as the forced self-review when a node exhausts its step budget. Stored only
    # in full_log.json so every LLM-generated Reflection field has an auditable
    # prompt and response.
    auxiliary_llm_calls: list = field(default_factory=list)
    # Relative pointer (from checkpoint root) to the per-node report file.
    # Optional: present only after `node_report.json` has been written.
    node_report_path: str | None = None
    # Optional per-node handoff arm. Empty means "use the run-level handoff".
    # Paired handoff experiments stamp sibling children from the same parent with
    # different values so the only per-child difference is the inherited text
    # channel, not the parent workspace.
    handoff_mode: str = ""

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
        d = {
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
            "evaluation_cases": self.evaluation_cases,
            "evaluation_status": self.evaluation_status,
            "eval_summary": self.eval_summary,
            "name": self.name,
            "error_log": self.error_log,
            "ancestor_ids": self.ancestor_ids,
            "trace_log": self.trace_log,
            "node_report_path": self.node_report_path,
        }
        if self.handoff_mode:
            d["handoff_mode"] = self.handoff_mode
        # label / raw_label / original_direction follow ONE switch,
        # ``ARI_BFTS_NO_LABEL``. When the label feature is ON they are emitted so a
        # LIVE variable is never hidden from the record (a record-only suppression
        # is how a label confound once survived a 4-arm study invisibly — the
        # ABLATION share ran 0/1/3/4 across arms). When the feature is OFF the
        # label drives nothing (NODE ROLE, child task line, diversity_bonus are all
        # neutral), so it is INERT and the keys are OMITTED ENTIRELY from tree.json
        # too — consistent with node_report.json. (Lazy import: ``ari.agent.loop``
        # imports ``Node`` at module top, so a top-level import here would cycle.)
        from ari.agent.loop import labels_disabled as _labels_off
        if not _labels_off():
            d["label"] = self.label.value
            d["raw_label"] = self.raw_label
            d["original_direction"] = self.original_direction
        return d
