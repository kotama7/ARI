"""Governance record dataclasses + constructive-prevention builders (Task 05 §6).

Every record carries the mandatory ``rqgm_record_base`` envelope
(``kernel_rules.ENVELOPE_FIELDS``): ``record_id, epoch_id, component_id,
prompt_hash, role, created_at, source_refs, status`` plus ``record_type`` and
``schema_version`` for JSONL multiplexing. ``prompt_hash`` is the existing
``hash12`` (``sha256[:12]``) value, or ``None`` for deterministic
(non-prompted) authors — no second hash scheme.

The ``build_*`` functions are the **constructive prevention** layer of the
same-role accusation prohibition (plan 05 §5.4): they refuse to construct a
violating record (:class:`GovernanceRuleError`). The authority is still the
ConstitutionalKernel — ``validate_role_separation`` independently re-checks
every produced record in the self-audit step; these builders are an
optimization, not the guarantee.

``created_at`` is wall-clock metadata only: it never enters any hash and no
decision logic reads it (P2). Additive-record convention: new fields default,
absence tolerated by readers (``CallRecord``/``PromptUseRecord`` pattern).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

GOVERNANCE_RECORD_SCHEMA_VERSION = 1

# ── role/actor vocabulary (author-role constants are constitutional:
#    kernel_rules.ROLE_RULES; mirrored here for the constructive layer) ──────

GOVERNANCE_ROLE = "governance"
ORCHESTRATOR_COMPONENT_ID = "governance_orchestrator"
AUDITOR_ROLE = "auditor"
EVIDENCE_CLERK_ROLE = "evidence_clerk"
DEFENDER_ROLE = "defender"
GOVERNANCE_JUDGE_ROLE = "governance_judge"

#: Governance-actor roles the MetaReliabilityMonitor / self-audit watch.
GOVERNANCE_ACTOR_ROLES: tuple[str, ...] = (
    AUDITOR_ROLE,
    EVIDENCE_CLERK_ROLE,
    DEFENDER_ROLE,
    GOVERNANCE_JUDGE_ROLE,
)

#: Closed ``recommendations[].action`` set (plan 05 §6.1; reconciled with
#: Task 09's transition table — unknown actions must be droppable by the
#: engine the way ``_parse_decision`` drops unknown lineage actions).
RECOMMENDATION_ACTIONS: tuple[str, ...] = (
    "promote_candidate",
    "promote",
    "demote",
    "warn",
    "quarantine",
    "retire",
    "no_action",
)

#: Subset a motion may request (a motion never *promotes*).
MOTION_ACTIONS: tuple[str, ...] = ("demote", "warn", "quarantine", "retire")

#: Closed adjudication outcomes (§5.3 step 6 incl. the board-failure carry).
ADJUDICATION_OUTCOMES: tuple[str, ...] = (
    "upheld",
    "partially_upheld",
    "dismissed",
    "inconclusive",
)

CANDIDATE_VERDICTS: tuple[str, ...] = ("pass", "fail", "inconclusive")

#: Record types step 1 scans out of the epoch's audit-log slice (§5.3).
#: RawAttackRecord/ValidatedAttackRecord/UtilityRecord content is Task 06's;
#: this module only names the types it reads.
OBSERVATION_RECORD_TYPES: tuple[str, ...] = (
    "validated_attack",
    "raw_attack",
    "review_record",
    "judgment_record",
    "utility_record",
    "comparison_observation",
    "node_report",
)

#: The documented step-5 total fallback text (plan 05 §5.3).
PROCEDURAL_DEFAULT_DEFENSE = (
    "no substantive defense generated; incumbent presumption applies"
)


class GovernanceRuleError(ValueError):
    """A record construction that would violate invariants 4-7 was refused."""


def created_at_now() -> str:
    """UTC metadata timestamp (never hashed, never read by decisions — P2)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _envelope(
    *,
    record_type: str,
    record_id: str,
    epoch_id: str,
    component_id: str,
    prompt_hash: str | None,
    role: str,
    status: str,
    source_refs: list,
) -> dict:
    return {
        "record_type": record_type,
        "schema_version": GOVERNANCE_RECORD_SCHEMA_VERSION,
        "record_id": record_id,
        "epoch_id": epoch_id,
        "component_id": component_id,
        "prompt_hash": prompt_hash,
        "role": role,
        "created_at": created_at_now(),
        "status": status,
        "source_refs": list(source_refs),
    }


# ── ComparisonObservation (§6.2 — same-role output; never admissible) ────────


@dataclass(frozen=True)
class ComparisonObservation:
    """Same-role disagreement record: observation, never accusation."""

    record_id: str
    epoch_id: str
    component_id: str
    role: str
    prompt_hash: str | None
    subject_component_id: str
    subject_role: str
    observation_type: str
    payload: dict = field(default_factory=dict)
    admissible_as_evidence: bool = False
    source_refs: tuple = ()
    status: str = "recorded"

    def to_dict(self) -> dict:
        d = _envelope(
            record_type="comparison_observation",
            record_id=self.record_id,
            epoch_id=self.epoch_id,
            component_id=self.component_id,
            prompt_hash=self.prompt_hash,
            role=self.role,
            status=self.status,
            source_refs=list(self.source_refs),
        )
        d.update(
            {
                "subject_component_id": self.subject_component_id,
                "subject_role": self.subject_role,
                "observation_type": self.observation_type,
                "payload": dict(self.payload),
                "admissible_as_evidence": self.admissible_as_evidence,
            }
        )
        return d


def build_comparison_observation(
    *,
    record_id: str,
    epoch_id: str,
    component_id: str,
    role: str,
    subject_component_id: str,
    subject_role: str,
    observation_type: str,
    payload: dict | None = None,
    prompt_hash: str | None = None,
    source_refs: tuple = (),
) -> ComparisonObservation:
    """§6.2 invariant enforced at construction: ``admissible_as_evidence``
    is ``False`` whenever ``role == subject_role`` (and v1 keeps it False
    unconditionally — observations are leads, never evidence items)."""
    return ComparisonObservation(
        record_id=record_id,
        epoch_id=epoch_id,
        component_id=component_id,
        role=role,
        prompt_hash=prompt_hash,
        subject_component_id=subject_component_id,
        subject_role=subject_role,
        observation_type=observation_type,
        payload=dict(payload or {}),
        admissible_as_evidence=False,
        source_refs=tuple(source_refs),
    )


# ── EvidenceBundle (§6.3 — EvidenceClerk-only author) ───────────────────────


@dataclass(frozen=True)
class EvidenceBundle:
    record_id: str
    epoch_id: str
    component_id: str  # the clerk's component id
    target_component_id: str
    target_role: str
    items: tuple = ()  # ({"kind", "ref", "content_hash"}, ...)
    excluded_items: tuple = ()  # ({"ref", "reason"}, ...)
    all_refs_resolved: bool = True
    status: str = "verified"

    @property
    def source_refs(self) -> list:
        return [str(i.get("ref", "")) for i in self.items]

    def to_dict(self) -> dict:
        d = _envelope(
            record_type="evidence_bundle",
            record_id=self.record_id,
            epoch_id=self.epoch_id,
            component_id=self.component_id,
            prompt_hash=None,  # the clerk is deterministic (non-prompted)
            role=EVIDENCE_CLERK_ROLE,
            status=self.status,
            source_refs=self.source_refs,
        )
        d.update(
            {
                "target_component_id": self.target_component_id,
                "target_role": self.target_role,
                "items": [dict(i) for i in self.items],
                "excluded_items": [dict(i) for i in self.excluded_items],
                "verification": {
                    "checked_by": "evidence_audit_checker",
                    "all_refs_resolved": self.all_refs_resolved,
                },
            }
        )
        return d


def build_evidence_bundle(
    *,
    author_role: str,
    record_id: str,
    epoch_id: str,
    clerk_component_id: str,
    target_component_id: str,
    target_role: str,
    items: tuple = (),
    excluded_items: tuple = (),
    all_refs_resolved: bool = True,
) -> EvidenceBundle:
    """Constructive prevention: an EvidenceBundle is valid only when authored
    by the EvidenceClerk (invariant 5; kernel check CK-ROL-002)."""
    if author_role != EVIDENCE_CLERK_ROLE:
        raise GovernanceRuleError(
            f"EvidenceBundle must be authored by {EVIDENCE_CLERK_ROLE!r}, "
            f"not {author_role!r} (plan 05 §5.4 rule 2)"
        )
    return EvidenceBundle(
        record_id=record_id,
        epoch_id=epoch_id,
        component_id=clerk_component_id,
        target_component_id=target_component_id,
        target_role=target_role,
        items=tuple(items),
        excluded_items=tuple(excluded_items),
        all_refs_resolved=all_refs_resolved,
    )


# ── ImpeachmentMotion / ImpeachmentOutcome (§6.4 — Auditor-only author) ─────


@dataclass(frozen=True)
class ImpeachmentMotion:
    record_id: str
    epoch_id: str
    component_id: str  # the auditor's component id
    prompt_hash: str | None
    target_component_id: str
    target_role: str
    charge: str
    evidence_bundle_id: str
    bond_units: int = 1
    requested_action: str = "demote"
    status: str = "filed"

    def to_dict(self) -> dict:
        d = _envelope(
            record_type="impeachment_motion",
            record_id=self.record_id,
            epoch_id=self.epoch_id,
            component_id=self.component_id,
            prompt_hash=self.prompt_hash,
            role=AUDITOR_ROLE,
            status=self.status,
            source_refs=[self.evidence_bundle_id],
        )
        d.update(
            {
                "target_component_id": self.target_component_id,
                "target_role": self.target_role,
                "charge": self.charge,
                "evidence_bundle_id": self.evidence_bundle_id,
                "bond_units": int(self.bond_units),
                "requested_action": self.requested_action,
            }
        )
        return d


def build_impeachment_motion(
    *,
    author_role: str,
    record_id: str,
    epoch_id: str,
    auditor_component_id: str,
    target_component_id: str,
    target_role: str,
    charge: str,
    evidence_bundle_id: str,
    bond_units: int = 1,
    requested_action: str = "demote",
    prompt_hash: str | None = None,
) -> ImpeachmentMotion:
    """Constructive prevention (invariants 4/6, kernel CK-ROL-001/003):
    only the Auditor files motions, and the Auditor is never the target's
    role — Reviewer v4 can never impeach Reviewer v3 through this path."""
    if author_role != AUDITOR_ROLE:
        raise GovernanceRuleError(
            f"ImpeachmentMotion must be authored by {AUDITOR_ROLE!r}, not "
            f"{author_role!r} (plan 05 §5.4 rule 1)"
        )
    if target_role == AUDITOR_ROLE:
        raise GovernanceRuleError(
            "same-role accusation refused: the Auditor cannot impeach an "
            "auditor-role component (plan 05 §5.4 rule 1)"
        )
    if requested_action not in MOTION_ACTIONS:
        raise GovernanceRuleError(
            f"requested_action {requested_action!r} is outside the closed "
            f"motion action set {MOTION_ACTIONS}"
        )
    return ImpeachmentMotion(
        record_id=record_id,
        epoch_id=epoch_id,
        component_id=auditor_component_id,
        prompt_hash=prompt_hash,
        target_component_id=target_component_id,
        target_role=target_role,
        charge=charge,
        evidence_bundle_id=evidence_bundle_id,
        bond_units=int(bond_units),
        requested_action=requested_action,
    )


@dataclass(frozen=True)
class ImpeachmentOutcome:
    """Standalone adjudication record so Task 09 can consume outcomes
    without parsing full reports (§6.4)."""

    record_id: str
    epoch_id: str
    motion_id: str
    outcome: str  # ADJUDICATION_OUTCOMES
    judge_component_id: str
    judge_prompt_hash: str | None
    replay_result_ref: str = ""
    anchor_result_ref: str = ""
    rationale: str = ""
    clamped_by_board: bool = False
    status: str = "final"

    def to_dict(self) -> dict:
        d = _envelope(
            record_type="impeachment_outcome",
            record_id=self.record_id,
            epoch_id=self.epoch_id,
            component_id=self.judge_component_id,
            prompt_hash=self.judge_prompt_hash,
            role=GOVERNANCE_JUDGE_ROLE,
            status=self.status,
            source_refs=[self.motion_id],
        )
        d.update(
            {
                "motion_id": self.motion_id,
                "outcome": self.outcome,
                "replay_result_ref": self.replay_result_ref,
                "anchor_result_ref": self.anchor_result_ref,
                "rationale": self.rationale,
                "clamped_by_board": self.clamped_by_board,
            }
        )
        return d


# ── GovernanceDefense (step 5; named to avoid Task 06's DefenderResponse) ───


@dataclass(frozen=True)
class GovernanceDefense:
    record_id: str
    epoch_id: str
    component_id: str  # the defender's component id
    prompt_hash: str | None
    motion_id: str
    defense_text: str
    procedural_default: bool = False
    status: str = "recorded"

    def to_dict(self) -> dict:
        d = _envelope(
            record_type="governance_defense",
            record_id=self.record_id,
            epoch_id=self.epoch_id,
            component_id=self.component_id,
            prompt_hash=self.prompt_hash,
            role=DEFENDER_ROLE,
            status=self.status,
            source_refs=[self.motion_id],
        )
        d.update(
            {
                "motion_id": self.motion_id,
                "defense_text": self.defense_text,
                "procedural_default": self.procedural_default,
            }
        )
        return d


# ── GovernanceReport (§6.1 — the facade's single return type) ───────────────


@dataclass
class GovernanceReport:
    """Typed mirror of plan 05 §6.1; ``to_dict()`` for JSONL/schema use."""

    record_id: str
    epoch_id: str
    governance_level: int = 1
    degraded: bool = False
    degradation_reasons: list = field(default_factory=list)
    reliability: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    evidence_bundles: list = field(default_factory=list)
    impeachment_motions: list = field(default_factory=list)
    defenses: list = field(default_factory=list)
    adjudications: list = field(default_factory=list)
    candidate_evaluations: list = field(default_factory=list)
    replay_pool_updates: dict = field(
        default_factory=lambda: {"added": [], "retired": []}
    )
    self_audit: dict = field(default_factory=dict)
    recommendations: list = field(default_factory=list)
    bond_accounting: dict = field(default_factory=dict)
    budget_usage: dict = field(default_factory=dict)
    status: str = "final"
    created_at: str = field(default_factory=created_at_now)

    def to_dict(self) -> dict:
        """§6.1 key order; envelope fields first for kernel schema checks."""
        return {
            "record_type": "governance_report",
            "schema_version": GOVERNANCE_RECORD_SCHEMA_VERSION,
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": ORCHESTRATOR_COMPONENT_ID,
            "prompt_hash": None,
            "role": GOVERNANCE_ROLE,
            "created_at": self.created_at,
            "status": self.status,
            "source_refs": [f"rqgm_audit.jsonl#{self.epoch_id}"],
            "governance_level": int(self.governance_level),
            "degraded": bool(self.degraded),
            "degradation_reasons": list(self.degradation_reasons),
            "reliability": list(self.reliability),
            "observations": list(self.observations),
            "evidence_bundles": list(self.evidence_bundles),
            "impeachment_motions": list(self.impeachment_motions),
            "defenses": list(self.defenses),
            "adjudications": list(self.adjudications),
            "candidate_evaluations": list(self.candidate_evaluations),
            "replay_pool_updates": dict(self.replay_pool_updates),
            "self_audit": dict(self.self_audit),
            "recommendations": list(self.recommendations),
            "bond_accounting": dict(self.bond_accounting),
            "budget_usage": dict(self.budget_usage),
        }
