"""Fixed component/prompt state-transition table (RQGM Task 09, Layer 0).

Pure-data module (``docs/concepts/rqgm_architecture.md``, "The epoch cycle"):
the complete, non-evolving T1–T21 transition table for governed components
and prompts. T20 (``utility_policy``) and T21 (paper-role shadow standby) are
the two role-scoped supersession edges, and are the sole exceptions to the
one-active-entry rule — see ``docs/concepts/rqgm_architecture.md``, "The epoch
cycle" (and "The four pillars" for why they are the only exceptions).
Imported by BOTH the RegistryTransitionEngine (the engine logic) and the
ConstitutionalKernel's TransitionValidator — single source of truth, no
duplication drift. The table is covered by ``constitution_hash``
(``docs/guides/execution_modes.md``, "Constitutional kernel (Layer 0)"): any
edit here re-pins the hash, by hand, in ``tests/test_rqgm_kernel.py``.

Encoding decision (documented for the |S|×|S| complement test): the table is
keyed by ``(from_status, to_status)`` with exactly 21 entries, one per rule
id. The ⚡ emergency rule T16 spans four ``from`` statuses (probationary_active
| active | warning | probation → quarantine); three of those pairs coincide
with the boundary rules T8/T11/T15 and keep those rule ids as their table
entry, so the T16 *table row* is the one pair with no boundary edge of its own
(``warning → quarantine``). The full four-shape emergency set lives in
:data:`EMERGENCY_EDGE`; a mid-epoch commit is legal ONLY as an emergency
transition over one of those shapes (``boundary_only`` is ``False`` only on
T16).

Everything not listed is forbidden — notably ``candidate → active`` (no
instant activation, invariant 15), any resurrection out of ``retired``, any
edge out of ``banned`` (absorbing), and any edge written by an actor other
than the RegistryTransitionEngine (invariant 10; validated by the kernel).
``active → retired`` (T20) is listed but role-scoped: legal ONLY for the
``utility_policy`` criterion's supersession (Task 14 §5.5); for every
behavioral role the kernel still rejects it (retirement must stage via
quarantine), so the sanction-only replacement model is intact for them.

Deterministic, pure stdlib: no LLM calls, no I/O, no randomness, no wall
clock (P2). Statuses are exactly Task 02's shared ``$defs`` enum
(``ari.rqgm.events.STATUS_VALUES``; parity pinned by tests).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ComponentStatus(str, Enum):
    """The 10 governed statuses (Task 02's closed vocabulary, plan 09 §5.2).

    Forward-compat rule (owned by the engine, restated here): an unknown
    status read from a registry file is treated as ineligible for the active
    set and logged — never a crash (``_parse_decision`` precedent).
    """

    CANDIDATE = "candidate"
    VALIDATED = "validated"
    SHADOW = "shadow"
    PROBATIONARY_ACTIVE = "probationary_active"
    ACTIVE = "active"
    WARNING = "warning"
    PROBATION = "probation"
    QUARANTINE = "quarantine"
    RETIRED = "retired"
    BANNED = "banned"


@dataclass(frozen=True)
class TransitionRule:
    """One fixed table row (plan 09 §7). ``guards`` are deterministic guard
    predicate *names* — the engine (Task 09) evaluates them; the kernel only
    checks table membership, rule-id parity, and boundary/emergency shape."""

    rule_id: str                 # "T6"
    trigger: str                 # machine-readable trigger kind
    guards: tuple[str, ...]      # guard predicate names (all deterministic)
    boundary_only: bool          # False only for T16


def _r(rule_id: str, trigger: str, guards: tuple[str, ...] = (),
       *, boundary_only: bool = True) -> TransitionRule:
    return TransitionRule(rule_id=rule_id, trigger=trigger, guards=guards,
                          boundary_only=boundary_only)


#: Exactly T1..T20 (plan 09 §5.2 + plan 14 §5.5 — T20 supersession). Keys are
#: ``(from_status, to_status)`` value pairs; see the module docstring for the
#: T16 encoding.
TRANSITION_TABLE: dict[tuple[str, str], TransitionRule] = {
    ("candidate", "validated"): _r(
        "T1", "candidate_validation_passed",
        ("candidate_cap_not_exceeded", "constitutional_constraints_present"),
    ),
    ("candidate", "retired"): _r(
        "T2", "validation_failed_or_candidate_expired",
        ("never_served_rejection",),
    ),
    ("validated", "shadow"): _r(
        "T3", "replay_and_anchor_evaluation_passed",
        ("shadow_slot_available",),
    ),
    ("shadow", "validated"): _r(
        "T4", "insufficient_shadow_samples",
        ("shadow_retry_within_limit",),
    ),
    ("shadow", "retired"): _r(
        "T5", "shadow_quality_below_threshold",
        ("never_served_rejection",),
    ),
    ("shadow", "probationary_active"): _r(
        "T6", "shadow_agreement_passed",
        ("role_opening_available", "one_adoption_per_role_per_boundary"),
    ),
    ("probationary_active", "active"): _r(
        "T7", "clean_probation_record",
        ("probation_min_epochs_served",),
    ),
    ("probationary_active", "quarantine"): _r(
        "T8", "upheld_impeachment_or_reliability_collapse",
    ),
    ("active", "warning"): _r(
        "T9", "reliability_warning_or_low_severity_attacks",
        ("component_keeps_serving",),
    ),
    ("active", "probation"): _r(
        "T10", "repeated_warnings_or_medium_severity_attacks",
        ("component_keeps_serving",),
    ),
    ("active", "quarantine"): _r(
        "T11", "upheld_impeachment_or_critical_attack_pattern",
        ("fallback_assigned",),
    ),
    ("warning", "active"): _r(
        "T12", "clean_epoch",
    ),
    ("warning", "probation"): _r(
        "T13", "warning_recurrence_within_memory",
    ),
    ("probation", "active"): _r(
        "T14", "rehabilitation_clean_epochs",
        ("probation_min_epochs_served",),
    ),
    ("probation", "quarantine"): _r(
        "T15", "continued_degradation_or_upheld_impeachment",
    ),
    ("warning", "quarantine"): _r(
        "T16", "constitutional_emergency",
        ("emergency_flag_set", "kernel_violation_attached", "single_sanction"),
        boundary_only=False,
    ),
    ("quarantine", "retired"): _r(
        "T17", "adjudication_confirmed_retirement",
        ("replay_board_confirmation", "emits_retirement_event"),
    ),
    ("quarantine", "probationary_active"): _r(
        "T18", "exoneration",
        ("re_enters_under_probation",),
    ),
    ("retired", "banned"): _r(
        "T19", "contamination_or_critical_finding",
        ("absorbing",),
    ),
    # Task 14 (plan 14 §5.5, amended 2026-07-16): the SUPERSESSION edge. The
    # utility policy is the evaluation CRITERION, not a behavioral actor — it
    # is adopted by SUPERSESSION, so a validated, shadow-passed successor that
    # scores at least as well on the frozen replay board DISPLACES the healthy
    # incumbent at the boundary, retiring it with the OLD utility_policy_hash
    # so ``frontier_repair`` invalidates every node scored under the retired
    # policy. This is the ONLY ``active -> retired`` edge; it is guarded so it
    # is legal ONLY for the ``utility_policy`` role (behavioral components keep
    # the conservative sanction-only replacement model: for them active ->
    # retired stays forbidden — the kernel rejects it, ``_change_violations``).
    # The engine emits it ONLY inside a same-role T6 adoption of a successor,
    # so it can never fire without an adoption to justify the displacement.
    ("active", "retired"): _r(
        "T20", "superseded_by_adopted_successor",
        ("supersession_successor_adopted", "utility_policy_role_only",
         "emits_retirement_event"),
    ),
    # Paper-archive Task 05 / plan 03 §5.9 (wave 3c, amended 2026-07-16): the
    # paper-role SHADOW-STANDBY supersession edge. Paper-role co-evolution is
    # PROMPT-level (the mutator mints unpaired prompt candidates); when a
    # shadow-passed successor prompt adopts (T6), the incumbent active prompt
    # of the same role is moved to ``shadow`` so there is EXACTLY ONE active
    # entry per paper role — never left co-active behind the latest-wins
    # rollup. Unlike T20 it is NOT a retirement: ``shadow`` is a reinstatable
    # standby (a next boundary can re-climb it via T6), so the demoted
    # incumbent is never deleted. Guarded to paper roles ONLY in the kernel
    # (``PAPER_SUPERSESSION_ROLES``); for every behavioral role active ->
    # shadow stays forbidden, so their sanction-only model is intact.
    ("active", "shadow"): _r(
        "T21", "superseded_by_adopted_successor",
        ("supersession_successor_adopted", "paper_prompt_role_only",
         "reinstatable_standby"),
    ),
}

#: Roles for which the T21 paper-role shadow-standby supersession (``active ->
#: shadow``) is legal. Every other role keeps the sanction-only replacement
#: model — the kernel rejects ``active -> shadow`` for them (CK-REG-001),
#: exactly as it does ``active -> retired`` (T20) outside ``utility_policy``.
PAPER_SUPERSESSION_ROLES: frozenset[str] = frozenset(
    {"paper_reviewer", "paper_writer"}
)

#: The four T16 shapes — the ONLY (from, to) pairs a mid-epoch emergency
#: transition may take (plan 09 §5.4; target status always ``quarantine``).
EMERGENCY_EDGE: frozenset[tuple[str, str]] = frozenset({
    ("probationary_active", "quarantine"),
    ("active", "quarantine"),
    ("warning", "quarantine"),
    ("probation", "quarantine"),
})

#: Rule id of the sole mid-epoch edge.
EMERGENCY_RULE_ID = "T16"


def allowed_transitions(status: str) -> frozenset[str]:
    """Boundary-legal ``to`` statuses for *status* (engine convenience;
    excludes nothing — T16's row is a table entry like any other)."""
    return frozenset(
        to for (frm, to) in TRANSITION_TABLE if frm == str(status)
    )
