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
    # --- the node's own account of its work ---------------------------------
    #
    # RESTORED. These were dropped by a merge that kept every reader and every
    # test, so the code that writes them still ran and the code that reads them
    # got a default: a node's self-report and how it ended were silently empty
    # for every run since. Nothing raised, because a dataclass accepts an
    # attribute nobody declared and ``getattr(node, ..., "")`` answers for one
    # nobody wrote.
    #
    # ``agent_summary``/``next_steps``/``concerns`` are what a child inherits, so
    # this is the handoff itself -- the quantity the study exists to compare.
    agent_summary: str = ""
    agent_next_steps: list[str] = field(default_factory=list)
    agent_concerns: list[str] = field(default_factory=list)
    #: ``pre_evaluation`` until the post-scoring review replaces the two lists
    #: above. A reader cannot otherwise tell an evaluator-informed self-report
    #: from a guess the agent made before it was scored.
    self_report_stage: str = "pre_evaluation"
    #: The agent's free-form note about what it ran on, kept only when grounded
    #: in this node's tool output. Never auto-scraped, so no machine identity is
    #: embedded without the agent having observed it.
    agent_environment: str = ""
    #: ``{path: note}`` the report builder grafts onto files_changed.
    file_notes: dict = field(default_factory=dict)
    react_steps_used: int = 0
    #: HOW a node ended -- finish_json, max_steps, watchdog, exception. Without
    #: it a crashed node is indistinguishable from one that never converged, and
    #: averaging the two biases exactly the arm comparison the study makes.
    ended_by: str = ""
    full_messages: list = field(default_factory=list)
    full_tools: list = field(default_factory=list)
    #: Auxiliary (non-ReAct) LLM calls made about this node, with their prompts
    #: and replies. Appended to, so its absence was an AttributeError rather
    #: than a silent default -- which is why the two self-review calls could
    #: never complete even once their definitions came back.
    auxiliary_llm_calls: list = field(default_factory=list)
    handoff_mode: str = ""
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
    # RQGM-only producer provenance. A governed runtime stamps these from the
    # epoch-frozen active map; legacy/simple_bfts nodes leave them empty.
    producer_component_id: str = ""
    producer_prompt_hash: str = ""
    producer_epoch_id: str = ""
    # Relative pointer (from checkpoint root) to the per-node report file.
    # Optional: present only after `node_report.json` has been written.
    node_report_path: str | None = None
    # Tasks 16–19 typed scientific provenance.  Values remain empty on the
    # compatibility path and are omitted from serialized legacy nodes.
    knowledge_skill_refs: list[dict] = field(default_factory=list)
    knowledge_skill_use_digest: str = ""
    instruction_identity_digest: str = ""
    capability_binding_lock_digest: str = ""
    bound_tool_refs: list[str] = field(default_factory=list)
    assurance_status: str = ""
    assurance_tier: str = ""
    baseline_harness_lock_digest: str = ""
    active_harness_lock_digest: str = ""
    attestation_refs: list[str] = field(default_factory=list)
    verified_target_digest: str = ""
    property_verdicts: dict = field(default_factory=dict)
    frontier_class: str = ""
    # Manuscript repair lineage. Empty on ordinary exploration nodes; repair
    # nodes inherit one digest-bound request envelope and cannot widen it.
    repair_request_id: str = ""
    repair_requirement_ids: list[str] = field(default_factory=list)
    repair_context_digest: str = ""
    repair_allowed_changes: list[str] = field(default_factory=list)

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
        payload = {
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
            "label": self.label.value,
            "raw_label": self.raw_label,
            "name": self.name,
            "error_log": self.error_log,
            "ancestor_ids": self.ancestor_ids,
            "trace_log": self.trace_log,
            "original_direction": self.original_direction,
            "producer_component_id": self.producer_component_id,
            "producer_prompt_hash": self.producer_prompt_hash,
            "producer_epoch_id": self.producer_epoch_id,
            "node_report_path": self.node_report_path,
        }
        scientific = {
            "knowledge_skill_refs": self.knowledge_skill_refs,
            "knowledge_skill_use_digest": self.knowledge_skill_use_digest,
            "instruction_identity_digest": self.instruction_identity_digest,
            "capability_binding_lock_digest": self.capability_binding_lock_digest,
            "bound_tool_refs": self.bound_tool_refs,
            "assurance_status": self.assurance_status,
            "assurance_tier": self.assurance_tier,
            "baseline_harness_lock_digest": self.baseline_harness_lock_digest,
            "active_harness_lock_digest": self.active_harness_lock_digest,
            "attestation_refs": self.attestation_refs,
            "verified_target_digest": self.verified_target_digest,
            "property_verdicts": self.property_verdicts,
            "frontier_class": self.frontier_class,
            "repair_request_id": self.repair_request_id,
            "repair_requirement_ids": self.repair_requirement_ids,
            "repair_context_digest": self.repair_context_digest,
            "repair_allowed_changes": self.repair_allowed_changes,
        }
        if any(value not in ("", [], {}) for value in scientific.values()):
            payload.update(scientific)
        return payload
