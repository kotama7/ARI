"""RegistryTransitionEngine — the sole registry status writer (RQGM Task 09).

Implements the sole-registry-writer facade
(``docs/concepts/rqgm_architecture.md``, "The four facades"): the single
component allowed to change ``status`` fields in the Task 02 registries. It
consumes the Task 05 ``GovernanceReport`` and Task 07 candidate evaluations,
resolves them deterministically against the fixed Layer-0 table in
:mod:`ari.rqgm.transition_rules` (T1–T20), produces an :class:`EpochTransition`
record, has it validated by the Task 04 ConstitutionalKernel, and commits it
atomically through the Task 02 boundary transaction
(:meth:`ari.rqgm.store.RqgmStateStore.run_boundary`). Emergency quarantine
(:meth:`RegistryTransitionEngine.emergency_quarantine`) ends the current epoch
immediately and rides the same atomic close/change/open transaction.

Determinism stance (P2): :meth:`resolve_transition` is a pure function
of ``(epoch_state, governance_report, candidate_evaluations, registries,
status_history, config)`` — no LLM, no I/O, no randomness, no wall clock in
decisions. ``created_at`` is stamped only at ``apply`` time (audit metadata,
never hashed). Given identical inputs the resolved transition serializes
byte-identically.

v1 resolution notes (documented simplifications, deterministic by design):

* ``warning``/``probation`` are *serving* postures tracked on the COMPONENT
  entry only; the linked prompt entry keeps serving unchanged (the plan's
  "component keeps serving" guard). Removal statuses (quarantine/retired/
  banned) and the adoption spine mirror onto the prompt entry.
* A ``retire`` recommendation against an ``active`` component stages through
  quarantine (T11); T17 fires only from ``quarantine`` at a later boundary.
* T10's "repeated warnings" trigger counts committed T9 applications in the
  status history: the ``warning_escalation_count``-th warning against an
  ``active`` component escalates straight to probation.
* T17's ReplayBoard coverage guard reads the report-level
  ``budget_usage.replay_cases_used`` (per-target coverage is a Task 12/13
  refinement).
* Exoneration (T18) is signalled by a ``no_action`` recommendation targeting
  a quarantined component; T19 by ``self_audit.ban_recommendations``.
* With no GovernanceReport (audit failed/absent) or under the Task 04
  ``governance_suspended`` carry-over, the resolved transition is empty:
  promotions and retirements are frozen and the incumbent set keeps serving.

Under ``simple_bfts`` this module is never imported: ``build_runtime``
constructs the transition engine only on the ``ari_rqgm`` branch, so the
simple mode carries no registry writer at all. VirSci-independent: no
``vendor/virsci`` import.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ari.rqgm import meta_rules, transition_rules
from ari.rqgm.events import (
    STATUS_VALUES,
    UTILITY_POLICY_ROLE,
    TransitionEvent,
    canonical_json,
    event_from_line_dict,
    format_epoch_id,
    format_transition_id,
)
from ari.rqgm.kernel_rules import REGISTRY_WRITER, SEVERITY

log = logging.getLogger(__name__)

EPOCH_TRANSITION_SCHEMA_VERSION = 1

#: Closed recommendation vocabulary consumed from Task 05 reports (parity
#: with ``ari.rqgm.governance._records.RECOMMENDATION_ACTIONS`` is pinned by
#: tests). Unknown actions are dropped with a note — the ``_parse_decision``
#: unknown-action precedent, never a crash.
KNOWN_ACTIONS: tuple[str, ...] = (
    "promote_candidate",
    "promote",
    "demote",
    "warn",
    "quarantine",
    "retire",
    "no_action",
)

#: Negative (sanctioning) actions, weakest→strongest; the strongest wins when
#: several target one component (deterministic tie-break).
_NEGATIVE_STRENGTH: dict[str, int] = {
    "warn": 1,
    "demote": 2,
    "quarantine": 3,
    "retire": 4,
}

#: The closed emergency-trigger class: deterministic kernel critical
#: violation codes ONLY (never performance signals, reviewer opinions, raw
#: attacks, or any LLM output).
EMERGENCY_TRIGGER_CODES: frozenset[str] = frozenset({
    "CK-HSH-010",   # active-prompt hash mismatch
    "CK-EPO-002",   # out-of-band active-set mutation
    "CK-AUD-001",   # audit-log append-only violation
    "CK-AUD-002",   # audit-log prefix tampering
    "CK-AUD-003",   # audit-log hash chain broken
    "CK-ACC-001",   # out-of-scope access
    "CK-ACC-002",   # retired-prompt-text access
    "CK-ROL-901",   # forged registry-writer authority
})

#: Statuses that keep a component serving its role: warning and probation are
#: serving postures, quarantine is what removes a holder from serving.
SERVING_STATUSES: tuple[str, ...] = (
    "active",
    "probationary_active",
    "warning",
    "probation",
)

#: Statuses eligible as an emergency/quarantine fallback holder — a fallback
#: must itself still be serving, so the eligible set IS the serving set.
_FALLBACK_ELIGIBLE: tuple[str, ...] = SERVING_STATUSES

#: Role-holder statuses that BLOCK a T6 adoption (no opening while the
#: incumbent is healthy; probation/quarantine/retired count as an opening).
_NO_OPENING_STATUSES: tuple[str, ...] = ("active", "probationary_active",
                                         "warning")

#: The evaluation-side sentinel an evaluator sets to DECLARE that no EXECUTED
#: replay/shadow case stands behind its board. It is the honest alternative to
#: padding ``case_refs`` / ``shadow_samples`` with synthetic entries sized to
#: clear the T3 ``replay_min_cases`` and T6 ``shadow_min_samples`` floors: an
#: absent board is reported as absent (``None``/``0``/``[]``) and the FLOOR is
#: waived here, in the open, by role — never cleared by numbers nobody computed.
NO_REPLAY_BASIS_KEY = "no_replay_basis"

#: The T6 half, declared SEPARATELY (see below): the candidate is never
#: shadow-EXECUTED, so the ``shadow_min_samples`` floor has no sample to count.
NO_SHADOW_BASIS_KEY = "no_shadow_basis"

#: The two floors are declared by two keys because their conditions genuinely
#: differ, and one boolean conflated them (recorded 2026-07-17). Only the
#: EVALUATOR knows whether ITS ``case_refs`` are countable evidence:
#:
#: * :data:`NO_REPLAY_BASIS_KEY` waives T3's ``replay_min_cases``. It means
#:   "no executed replay case stands behind this board". ``utility_policy``
#:   declares it always (its ``case_refs`` are the policy's own DIMENSIONS —
#:   never executed cases, so the floor has nothing honest to count).
#:   ``paper_reviewer`` declares it ONLY when its replay board is
#:   genuinely ABSENT: its ``case_refs`` ARE real pool case_ids, so a board that
#:   HAS cases must be COUNTED, not waived (amended 2026-07-17 — an
#:   unconditional declaration let a genuine 1-case board clear a 4-case floor,
#:   which nothing sanctions).
#: * :data:`NO_SHADOW_BASIS_KEY` waives T6's ``shadow_min_samples``. It means
#:   "this candidate is never shadow-EXECUTED, so the stage is vacuous BY
#:   CONSTRUCTION" — a structural fact independent of the replay board, true for
#:   every role below and always. Without it, a paper candidate with a GOOD,
#:   REAL replay board would pass T3 on its merits and then be retired at T4/T5
#:   for lacking shadow samples that no paper path can ever produce, while a
#:   candidate with NO board sailed through on the waiver — perverse, and the
#:   Red Queen dies quietly.
#:
#: Both keys are gated by this ONE role allowlist, scoped exactly as hard as
#: this module's other two role-scoped rules
#: (:meth:`RegistryTransitionEngine._maybe_supersede_utility_policy`,
#: :meth:`RegistryTransitionEngine._attach_utility_policy_bodies`):
#:
#: * ``utility_policy`` — a passive policy DOCUMENT holds no
#:   ``invoke`` grant, so it is never shadow-EXECUTED. Its shadow stage is
#:   vacuous by construction, so T6 reduces to CK-UTL legality (the T1 dry-run
#:   + the live kernel gate) + non-degeneracy + the supersession/adoption-cap
#:   guards. Its T3 board (axis-ordering agreement) is real and pool-INdependent
#:   — the sentinel waives the case COUNT, never the score.
#: * ``paper_writer`` (amended 2026-07-17) — a candidate writer PROMPT has
#:   authored no drafts yet, so no
#:   replay or anchor case can exist for it. It climbs to ``shadow`` and WAITS
#:   there; T6's ``_role_opening`` guard is untouched, so adoption still
#:   requires a real claim-gate faithfulness sanction against the incumbent.
#: * ``paper_reviewer`` (amended 2026-07-17) — the zero-coverage on-ramp
#:   ("the first paper reviewer is never
#:   blocked for lacking cases it could not yet have"). A reviewer that HAS
#:   coverage and merely scored badly emits real scores WITHOUT the replay
#:   sentinel and keeps failing T3 on its merits — count floor included.
#:
#: Behavioural exploration roles are deliberately absent: Task 09's live-shadow
#: board is the real thing for them, and a role-agnostic relaxation would break
#: it. Exploration/``simple_bfts``/``linear`` resolve byte-identically — no
#: evaluator off the paper phase or the utility criterion sets either sentinel.
NO_REPLAY_BASIS_ROLES: frozenset[str] = frozenset({
    UTILITY_POLICY_ROLE,
    "paper_writer",
    "paper_reviewer",
})

_EPOCH_ID_RE = re.compile(r"^epoch_(\d+)$")
_TRANSITION_ID_RE = re.compile(r"^transition_(\d+)_to_(\d+)$")


def _seq_from_epoch_id(epoch_id: str) -> int | None:
    m = _EPOCH_ID_RE.match(str(epoch_id or ""))
    return int(m.group(1)) if m else None


def _seq_from_transition_id(transition_id: str) -> int | None:
    m = _TRANSITION_ID_RE.match(str(transition_id or ""))
    return int(m.group(2)) if m else None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _as_dict(obj) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {}


def _entries(registry) -> dict:
    """Entry map out of a ComponentRegistry/GovernedPromptRegistry or a plain
    mapping (empty when absent)."""
    if registry is None:
        return {}
    entries = getattr(registry, "entries", None)
    if callable(entries):
        return entries()
    if isinstance(registry, dict):
        return dict(registry)
    return {}


# ── EpochTransition (the boundary's one output record) ─────────────────────


@dataclass
class EpochTransition:
    """The single output record of one boundary resolution; the persisted
    field set is fixed by ``docs/reference/rqgm_schemas.md``,
    "`epoch_transition.schema.json`".

    ``created_at`` stays empty until :meth:`RegistryTransitionEngine.apply`
    stamps it (P2: ``resolve_transition`` reads no clock), so two resolves
    over identical inputs serialize byte-identically.
    """

    epoch_transition_id: str
    from_epoch: str
    to_epoch: str
    status: str = "pending"
    emergency: bool = False
    produced_by: str = REGISTRY_WRITER
    inputs: dict = field(default_factory=dict)
    adoptions: list = field(default_factory=list)
    sanctions: list = field(default_factory=list)
    retirements: list = field(default_factory=list)
    clean_room_requests: list = field(default_factory=list)
    bans: list = field(default_factory=list)
    next_active_components: dict = field(default_factory=dict)
    fallbacks: list = field(default_factory=list)
    kernel_violation: dict | None = None
    kernel_validation: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    created_at: str = ""
    schema_version: int = EPOCH_TRANSITION_SCHEMA_VERSION

    @property
    def record_id(self) -> str:
        return self.epoch_transition_id

    def changes(self) -> list:
        """All status-change entries, group order fixed (adoptions,
        sanctions, retirements, bans) — the kernel flattens identically."""
        return (list(self.adoptions) + list(self.sanctions)
                + list(self.retirements) + list(self.bans))

    def is_empty(self) -> bool:
        return not (self.adoptions or self.sanctions or self.retirements
                    or self.bans)

    def to_dict(self) -> dict:
        """Serialized layout with the ``rqgm_record_base`` envelope fields
        first (governance record: the kernel schema check reads the
        envelope)."""
        return {
            "record_type": "epoch_transition",
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "epoch_transition_id": self.epoch_transition_id,
            "epoch_id": self.from_epoch,
            "component_id": REGISTRY_WRITER,
            "prompt_hash": None,
            "role": REGISTRY_WRITER,
            "created_at": self.created_at,
            "source_refs": [
                str(self.inputs.get("governance_report_ref") or "")
            ] if self.inputs.get("governance_report_ref") else [],
            "status": self.status,
            "produced_by": self.produced_by,
            "from_epoch": self.from_epoch,
            "to_epoch": self.to_epoch,
            "emergency": self.emergency,
            "inputs": dict(self.inputs),
            "adoptions": [dict(e) for e in self.adoptions],
            "sanctions": [dict(e) for e in self.sanctions],
            "retirements": [dict(e) for e in self.retirements],
            "clean_room_requests": [dict(e) for e in self.clean_room_requests],
            "bans": [dict(e) for e in self.bans],
            "next_active_components": dict(self.next_active_components),
            "fallbacks": [dict(e) for e in self.fallbacks],
            "kernel_violation": (
                dict(self.kernel_violation)
                if self.kernel_violation is not None else None
            ),
            "kernel_validation": dict(self.kernel_validation),
            "notes": list(self.notes),
        }


@dataclass
class AppliedTransition:
    """Result of :meth:`RegistryTransitionEngine.apply` (or the emergency
    commit): what happened and the post-commit replayed state."""

    transition: EpochTransition
    committed: bool = False
    aborted: bool = False
    noop: bool = False
    kernel_report: object | None = None
    state: object | None = None
    events: tuple = ()


# ── status history (crash-safe, replayed from the Task 02 log) ─────────────


def build_status_history(events) -> dict:
    """Pure fold of committed transition events into
    ``{id: {"status", "since_seq", "rule_counts"}}`` (epoch ages for the
    T2/T4/T5/T7/T13/T14 guards). ``since_seq`` is the epoch seq at which the
    current status took effect; ``rule_counts`` counts rule applications
    (bounded-retry guards). Deterministic: file order in, dict out."""
    hist: dict = {}

    def _touch(key: str) -> dict:
        return hist.setdefault(
            key, {"status": "", "since_seq": 0, "rule_counts": {}}
        )

    for ev in events or ():
        etype = getattr(ev, "event_type", "") or ""
        payload = getattr(ev, "payload", None)
        payload = payload if isinstance(payload, dict) else {}
        if etype in ("component_registered", "prompt_registered"):
            key = str(payload.get("component_id")
                      or payload.get("prompt_id") or "")
            if not key:
                continue
            entry = _touch(key)
            entry["status"] = str(payload.get("status", "candidate"))
            entry["since_seq"] = _seq_from_epoch_id(
                str(payload.get("epoch_id", ""))
            ) or 0
        elif etype in ("component_status_change", "prompt_status_change",
                       "emergency_quarantine"):
            since = _seq_from_transition_id(
                str(payload.get("transition_id", ""))
            )
            if since is None:
                since = _seq_from_epoch_id(str(payload.get("epoch_id", "")))
            for id_key in ("component_id", "prompt_id"):
                key = str(payload.get(id_key) or "")
                if not key:
                    continue
                entry = _touch(key)
                entry["status"] = str(payload.get("to_status", ""))
                if since is not None:
                    entry["since_seq"] = since
                rule_id = str(payload.get("rule_id", "") or "")
                if rule_id:
                    counts = entry["rule_counts"]
                    counts[rule_id] = int(counts.get(rule_id, 0)) + 1
    return hist


# ── config view (the thresholds are the ONLY tunable part) ─────────────────


class _Thresholds:
    """Duck-typed reader over ``rqgm.transition`` (typed model, dict, or
    absent — plan defaults). The table topology itself is fixed code."""

    _DEFAULTS = {
        "replay_pass_threshold": 0.8,
        "replay_min_cases": 4,
        "shadow_pass_threshold": 0.7,
        "shadow_min_samples": 5,
        "shadow_max_epochs": 2,
        "shadow_retry_limit": 1,
        "probation_min_epochs": 1,
        "warning_escalation_count": 2,
        "warning_memory_epochs": 3,
        "retirement_replay_min_cases": 8,
        "candidate_max_age_epochs": 3,
        "max_adoptions_per_role_per_boundary": 1,
    }

    def __init__(self, rqgm_cfg=None) -> None:
        block = getattr(rqgm_cfg, "transition", None)
        if block is None and isinstance(rqgm_cfg, dict):
            block = rqgm_cfg.get("transition")
        self._block = block
        # T1's per-role candidate cap has no key of its own: it rides Task
        # 07's ``max_candidates_per_role_per_epoch``, so candidate intake and
        # the T1 gate can never disagree about the cap.
        pe = getattr(rqgm_cfg, "prompt_evolution", None)
        if pe is None and isinstance(rqgm_cfg, dict):
            pe = rqgm_cfg.get("prompt_evolution")
        raw = (pe.get("max_candidates_per_role_per_epoch")
               if isinstance(pe, dict)
               else getattr(pe, "max_candidates_per_role_per_epoch", 1))
        try:
            self.max_candidates_per_role = max(0, int(raw))
        except (TypeError, ValueError):
            self.max_candidates_per_role = 1

    def __getattr__(self, name: str):
        if name not in self._DEFAULTS:
            raise AttributeError(name)
        default = self._DEFAULTS[name]
        block = self.__dict__.get("_block")
        if isinstance(block, dict):
            raw = block.get(name, default)
        else:
            raw = getattr(block, name, default)
        try:
            return type(default)(raw)
        except (TypeError, ValueError):
            return default


# ── the engine ──────────────────────────────────────────────────────────────


class RegistryTransitionEngine:
    """The single writer of registry status (global invariant 10 — see
    ``docs/concepts/rqgm_architecture.md``, "Key invariants").

    Constructed only under ``ari_rqgm`` (``RQGMRuntime``); ``simple_bfts``
    never imports this module. All persistence goes through the injected
    Task 02 store; the engine writes no file of its own.
    """

    def __init__(
        self,
        config=None,
        kernel=None,
        prompt_registry=None,
        component_registry=None,
        store=None,
        *,
        enforcement: str = "standard",
        audit_log=None,
    ) -> None:
        self.cfg = _Thresholds(config)
        self.kernel = kernel
        self.prompt_registry = prompt_registry
        self.component_registry = component_registry
        self.store = store
        self.enforcement = (
            enforcement if enforcement in ("standard", "audit_only")
            else "standard"
        )
        self.audit_log = audit_log

    # ── table surface ─────────────────────────────────────────────────

    @staticmethod
    def allowed_transitions(status: str) -> frozenset:
        """Legal ``to`` statuses for *status* per the fixed table. Unknown
        statuses yield the empty set (ineligible, never a crash)."""
        return transition_rules.allowed_transitions(str(status))

    # ── boundary steps 1-2: freeze inputs, then resolve purely ────────

    def resolve_transition(
        self,
        *,
        epoch_state,
        governance_report,
        candidate_evaluations=(),
        components=None,
        prompts=None,
        status_history=None,
        governance_suspended: bool = False,
    ) -> EpochTransition:
        """Pure and deterministic: no I/O, no LLM, no randomness, no clock.

        *components*/*prompts* default to the constructor-held registries;
        *status_history* is the :func:`build_status_history` fold (an input,
        so purity holds). Returns the pending :class:`EpochTransition`.
        """
        comps = _entries(components if components is not None
                         else self.component_registry)
        proms = _entries(prompts if prompts is not None
                         else self.prompt_registry)
        cur_seq = int(getattr(epoch_state, "epoch_seq", 0) or 0)
        from_epoch = str(getattr(epoch_state, "epoch_id", "")
                         or format_epoch_id(cur_seq))
        t = EpochTransition(
            epoch_transition_id=format_transition_id(cur_seq, cur_seq + 1),
            from_epoch=from_epoch,
            to_epoch=format_epoch_id(cur_seq + 1),
        )
        report = _as_dict(governance_report)
        evaluations = list(candidate_evaluations or ())
        if not evaluations and report.get("candidate_evaluations"):
            evaluations = list(report["candidate_evaluations"])
        t.inputs = self._freeze_inputs(report, evaluations, comps, proms)
        history = status_history or {}

        if governance_suspended:
            # Task 04 resume-integrity carry-over: promotions/retirements
            # frozen; the incumbent set keeps serving (empty transition).
            t.notes.append("governance_suspended: active set frozen")
            t.next_active_components = self._active_after(comps, {})
            return t
        if governance_report is None:
            t.notes.append("no_governance_report: no state changes resolved")
            t.next_active_components = self._active_after(comps, {})
            return t

        comp_actions, prompt_actions = self._collect_signals(report, t.notes)
        evals_by_prompt: dict = {}
        for ev in evaluations:
            ev = _as_dict(ev)
            pid = str(ev.get("prompt_id", ""))
            if pid and pid not in evals_by_prompt:
                evals_by_prompt[pid] = ev

        new_status: dict = {}          # id -> resolved to_status
        adoptions_per_role: dict = {}  # role -> count (T6 cap)
        t1_per_role: dict = {}         # role -> count (T1 cap)
        coverage = self._replay_coverage(report)
        ban_targets = self._ban_targets(report)

        # Components first (their sanctions define role openings).
        for cid, entry in sorted(comps.items()):
            self._resolve_component(
                t, cid, entry, comp_actions.get(cid, []),
                evals_by_prompt, history, cur_seq, new_status,
                coverage, ban_targets, adoptions_per_role, t1_per_role,
                comps,
            )
        # Then unpaired governed prompts (the Task 07 candidate spine).
        paired = {
            str(getattr(e, "prompt_id", "") or "") for e in comps.values()
        }
        for pid, entry in sorted(proms.items()):
            if pid in paired:
                continue
            self._resolve_prompt(
                t, pid, entry, prompt_actions.get(pid, []),
                evals_by_prompt.get(pid), history, cur_seq, new_status,
                adoptions_per_role, t1_per_role, comps, proms,
            )

        t.next_active_components = self._active_after(comps, new_status)
        self._assign_fallbacks(t, comps, new_status)
        return t

    # ── boundary steps 3-5: validate → prepare → apply → commit ───────

    def apply(
        self,
        transition: EpochTransition,
        *,
        checkpoint_dir,
        state,
        cfg,
        node_count: int,
        run_id: str = "",
        intake_events: list | tuple = (),
    ) -> AppliedTransition:
        """Kernel-validated commit through the Task 02 boundary transaction.

        Double-commit guard: a transition whose ``from_epoch`` is no longer
        the open epoch is a no-op (the deterministic re-run after a commit).
        A kernel-blocked transition is aborted fail-closed — NO resolved
        status change — while the boundary itself still advances fail-open
        with the incumbent set serving unchanged: a blocked transition must
        never be able to stall the epoch clock.

        *intake_events* are Task 07 candidate-intake ``prompt_registered``
        events (status=``candidate``) supplied by the runtime boundary hook.
        They ride the SAME boundary transaction so the next boundary's
        ``resolve_transition`` can iterate the minted candidates (plan 09
        T1); they are registrations (not T-edge transitions) so they are not
        kernel-gated here — exactly the founding-registration posture — and
        they commit even when the resolved transition aborts (registration is
        independent of the resolved status decisions).
        """
        if state is None or getattr(state, "epoch", None) is None:
            transition.status = "aborted"
            transition.notes.append("apply: no open epoch")
            return AppliedTransition(transition, aborted=True, state=state)
        if transition.from_epoch != state.epoch.epoch_id:
            transition.notes.append(
                f"apply: {transition.from_epoch} is not the open epoch "
                f"({state.epoch.epoch_id}); guarded no-op"
            )
            return AppliedTransition(transition, noop=True, state=state)
        if self._commit_exists(checkpoint_dir,
                               transition.epoch_transition_id):
            # Double-commit rule: a transition_id whose commit event
            # already exists in the log is a no-op even against stale state.
            transition.notes.append(
                f"apply: commit event for {transition.epoch_transition_id} "
                f"already in the log; guarded no-op"
            )
            return AppliedTransition(transition, noop=True, state=state)
        transition.created_at = self._now_iso()
        intake = list(intake_events or ())
        # Task 14: put the adopted utility_policy
        # BODY on the adoption entry so the kernel legality gate fires on the
        # LIVE path (validate_transition -> validate_utility_policy). Done here
        # (apply-side I/O) so resolve_transition stays pure. An illegal policy
        # is BLOCKED before it can score a node.
        self._attach_utility_policy_bodies(transition, state, checkpoint_dir, cfg)
        # #79: attach each capability-declaring adoption's incumbent so the
        # kernel's CK-REG-101 gate compares candidate vs incumbent (not None).
        self._attach_incumbent_capabilities(transition, state)
        report = self._validate(transition, state, at_boundary=True)
        if report is not None and self._blocks(report):
            transition.status = "aborted"
            self._audit("epoch_transition", self._audit_payload(transition))
            # Intake registrations still commit: they are independent of the
            # aborted status decisions and must reach the next boundary.
            new_state = self.store.run_boundary(
                checkpoint_dir, state, cfg,
                node_count=int(node_count), run_id=run_id,
                registry_events=intake,
            )
            return AppliedTransition(
                transition, aborted=True, kernel_report=report,
                state=new_state,
            )
        events = intake + self.decompose(transition)
        new_state = self.store.run_boundary(
            checkpoint_dir, state, cfg,
            node_count=int(node_count), run_id=run_id,
            registry_events=events,
        )
        committed = (
            new_state is not None
            and getattr(new_state, "epoch", None) is not None
            and new_state.epoch.epoch_id == transition.to_epoch
        )
        transition.status = "committed" if committed else "failed"
        self._audit("epoch_transition", self._audit_payload(transition))
        if committed:
            for entry in transition.retirements:
                self._audit("retirement_event", {
                    "retirement_event_id": entry.get("retirement_event_id"),
                    "component_id": entry.get("component_id"),
                    "prompt_id": entry.get("prompt_id"),
                    "prompt_hash": entry.get("prompt_hash"),
                    "role": entry.get("role"),
                    "epoch_id": transition.from_epoch,
                    "transition_id": transition.epoch_transition_id,
                    "evidence_refs": list(entry.get("evidence_refs") or ()),
                })
            for req in transition.clean_room_requests:
                self._audit("clean_room_generation_request", dict(req))
        return AppliedTransition(
            transition, committed=committed, kernel_report=report,
            state=new_state, events=tuple(events),
        )

    def decompose(self, transition: EpochTransition) -> list:
        """Boundary step 5(a): one ``component_status_change`` /
        ``prompt_status_change`` event per change, payloads carrying
        ``transition_id``, ``rule_id``, from/to, ``evidence_refs``,
        ``produced_by`` and the frozen input hash."""
        inputs_hash = str(transition.inputs.get("inputs_sha256", ""))
        events: list = []
        for entry in transition.changes():
            base = {
                "transition_id": transition.epoch_transition_id,
                "rule_id": entry.get("rule_id"),
                "from_status": entry.get("from_status"),
                "to_status": entry.get("to_status"),
                "evidence_refs": list(entry.get("evidence_refs") or ()),
                "produced_by": transition.produced_by,
                "inputs_sha256": inputs_hash,
            }
            cid = str(entry.get("component_id") or "")
            pid = str(entry.get("prompt_id") or "")
            if cid:
                events.append(TransitionEvent(
                    event_type="component_status_change",
                    payload=dict(base, component_id=cid),
                ))
            if pid:
                # prompt_to_status=None suppresses the mirror: serving
                # sanctions (T9/T10/T13...) posture the component only.
                if "prompt_to_status" in entry and \
                        entry.get("prompt_to_status") is None:
                    continue
                payload = dict(base, prompt_id=pid)
                payload["from_status"] = entry.get(
                    "prompt_from_status", entry.get("from_status")
                )
                payload["to_status"] = entry.get(
                    "prompt_to_status", entry.get("to_status")
                )
                events.append(TransitionEvent(
                    event_type="prompt_status_change", payload=payload,
                ))
        return events

    # ── emergency boundary (one sanction, kernel-critical trigger only) ─

    def emergency_quarantine(
        self,
        *,
        violation,
        component_id: str,
        epoch_state,
        components=None,
        prompts=None,
        checkpoint_dir=None,
        node_count: int | None = None,
        run_id: str = "",
    ) -> EpochTransition:
        """Single-sanction emergency boundary transition.

        Only a deterministic kernel critical violation
        (:data:`EMERGENCY_TRIGGER_CODES`, block severity) qualifies —
        performance signals never do. The transition is kernel-validated
        under the emergency shape and, when a store/checkpoint is available,
        committed immediately inside an atomic boundary transaction carrying
        the reserved ``emergency_quarantine`` event. Returned ``status``:
        ``committed`` | ``rejected`` | ``pending`` (validated, no store).
        """
        comps = _entries(components if components is not None
                         else self.component_registry)
        proms = _entries(prompts if prompts is not None
                         else self.prompt_registry)
        v = _as_dict(violation)
        code = str(v.get("code", ""))
        epoch_id = str(getattr(epoch_state, "epoch_id", "") or "")
        epoch_seq = int(getattr(epoch_state, "epoch_seq", 0) or 0)
        transition_id = format_transition_id(epoch_seq, epoch_seq + 1)
        entry = comps.get(component_id)
        from_status = str(getattr(entry, "status", "") or "")
        prompt_id = str(getattr(entry, "prompt_id", "") or "")
        # The linked prompt's OWN current status (from the governed-prompt
        # registry, not the component's), so the mirror below postures the
        # prompt from where it actually stands.
        prompt_entry = proms.get(prompt_id) if prompt_id else None
        prompt_from_status = str(getattr(prompt_entry, "status", "") or "")
        t = EpochTransition(
            epoch_transition_id=transition_id,
            from_epoch=epoch_id,
            to_epoch=format_epoch_id(epoch_seq + 1),
            emergency=True,
            kernel_violation=v,
            inputs={"kernel_violation_code": code,
                    "kernel_violation_subject": str(v.get("subject_ref", ""))},
        )
        rejected = []
        if code not in EMERGENCY_TRIGGER_CODES:
            rejected.append(f"non-critical trigger {code!r}")
        if SEVERITY.get(code) != "block" and str(v.get("severity")) != "block":
            rejected.append(f"trigger {code!r} is not block severity")
        if entry is None:
            rejected.append(f"unknown component {component_id!r}")
        elif (from_status, "quarantine") not in transition_rules.EMERGENCY_EDGE:
            rejected.append(
                f"{from_status!r} is not an emergency-edge from-status"
            )
        if rejected:
            t.status = "rejected"
            t.notes.extend(rejected)
            log.warning("emergency quarantine rejected: %s", "; ".join(rejected))
            return t
        sanction = {
            "component_id": component_id,
            "prompt_id": prompt_id or None,
            "role": str(getattr(entry, "role", "")),
            "from_status": from_status,
            "to_status": "quarantine",
            "rule_id": transition_rules.EMERGENCY_RULE_ID,
            "evidence_refs": [code],
            "severity": "critical",
        }
        if prompt_id:
            # Mirror the component quarantine onto its linked prompt, the same
            # way the normal T11 boundary quarantine does (``_mirror_prompt``
            # -> ``decompose`` emits a ``prompt_status_change``): the prompt
            # leaves the serving set too, so ``_active_evolvable_incumbents``
            # stops breeding it into successor candidates. Carried as fields
            # on the SINGLE sanction — never a second change entry — so the
            # kernel's one-change emergency shape (CK-REG-006) still passes.
            sanction["prompt_from_status"] = prompt_from_status
            sanction["prompt_to_status"] = "quarantine"
        t.sanctions = [sanction]
        new_status = {component_id: "quarantine"}
        t.next_active_components = self._active_after(comps, new_status)
        self._assign_fallbacks(t, comps, new_status)
        report = self._validate_dictless(t, comps)
        if report is not None and self._blocks(report):
            t.status = "rejected"
            t.notes.append("kernel rejected the emergency shape")
            return t
        t.created_at = self._now_iso()
        if self.store is not None and checkpoint_dir is not None:
            payload = {
                "transition_id": transition_id,
                "epoch_id": epoch_id,
                "component_id": component_id,
                "prompt_id": prompt_id or None,
                "from_status": from_status,
                "to_status": "quarantine",
                "rule_id": transition_rules.EMERGENCY_RULE_ID,
                "emergency": True,
                "produced_by": t.produced_by,
                "kernel_violation": v,
                "fallbacks": [dict(f) for f in t.fallbacks],
                "emergency_boundary": True,
            }
            from ari.rqgm.store import RqgmRuntimeState
            from ari.rqgm.registry import (
                ComponentRegistry,
                GovernedPromptRegistry,
            )
            current_state = RqgmRuntimeState(
                epoch=epoch_state,
                components=ComponentRegistry(comps),
                prompts=GovernedPromptRegistry(proms),
            )
            boundary_state = self.store.run_boundary(
                checkpoint_dir,
                current_state,
                None,
                node_count=(
                    int(node_count)
                    if node_count is not None
                    else int(getattr(epoch_state, "node_count_at_open", 0) or 0)
                ),
                run_id=run_id or str(getattr(epoch_state, "run_id", "") or ""),
                registry_events=[
                    TransitionEvent(
                        event_type="emergency_quarantine",
                        payload=payload,
                    )
                ],
                utility_policy_override=dict(
                    getattr(epoch_state, "utility_policy", None) or {}
                ),
            )
            ok = (
                boundary_state is not None
                and getattr(boundary_state, "epoch", None) is not None
                and boundary_state.epoch.epoch_id == t.to_epoch
            )
            t.status = "committed" if ok else "failed"
            self._audit("epoch_transition", t.to_dict())
        return t

    # ── status history I/O helper (apply-side; resolve stays pure) ────

    def load_status_history(self, checkpoint_dir) -> dict:
        """Fold the committed Task 02 event log into the resolve input
        (absence-tolerant; ``{}`` when the log does not exist)."""
        try:
            from ari.rqgm.store import (
                RQGM_TRANSITIONS_FILENAME,
                committed_events,
            )

            path = Path(checkpoint_dir) / RQGM_TRANSITIONS_FILENAME
            if not path.exists():
                return {}
            events = []
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(d, dict):
                        events.append(event_from_line_dict(d))
            return build_status_history(committed_events(events))
        except Exception:
            log.warning("status history load failed", exc_info=True)
            return {}

    # ── internals ─────────────────────────────────────────────────────

    @staticmethod
    def _commit_exists(checkpoint_dir, transition_id: str) -> bool:
        """True iff an ``epoch_transaction_commit`` for *transition_id* is
        already in the Task 02 log (absence-tolerant; ``False`` on any read
        failure — the from-epoch guard still holds)."""
        try:
            from ari.rqgm.store import RQGM_TRANSITIONS_FILENAME

            path = Path(checkpoint_dir) / RQGM_TRANSITIONS_FILENAME
            if not path.exists():
                return False
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (isinstance(d, dict)
                            and d.get("event_type")
                            == "epoch_transaction_commit"
                            and (d.get("payload") or {}).get("transition_id")
                            == transition_id):
                        return True
        except Exception:
            log.warning("commit-existence scan failed", exc_info=True)
        return False

    @staticmethod
    def _now_iso() -> str:
        import time

        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _blocks(self, report) -> bool:
        from ari.rqgm.kernel import should_block

        return should_block(report, self.enforcement)

    def _attach_utility_policy_bodies(
        self, transition: EpochTransition, state, checkpoint_dir, cfg=None,
    ) -> None:
        """Resolve each utility_policy adoption's successor body and attach it
        as ``entry['policy']`` so the kernel's
        legality gate (``validate_transition`` -> ``validate_utility_policy``,
        kernel.py) runs on the LIVE adoption path — an illegal candidate is
        BLOCKED before it can ever score a node. Apply-side I/O keeps
        ``resolve_transition`` pure. Best-effort: an unreadable body leaves the
        entry ``policy``-less and the gate degrades to the incumbent-safe
        no-op (the mint + the T1 legality evaluation already blocked illegal
        candidates upstream, so this is defense in depth, never the sole
        gate).

        Also attaches ``entry['live_axes']`` — one validator, two callers, and
        BOTH must feed it the same evidence: the epoch's live axis set, so
        CK-UTL-006 fires on THIS caller
        too. Without it the apply path validated against ``live_axes=None`` and
        the advisory was dead on the T6 adoption path even after the candidate
        hook was fixed."""
        prompts = getattr(state, "prompts", None)
        resolve = getattr(prompts, "resolve_text", None)
        if not callable(resolve):
            return
        live_axes = None
        if cfg is not None:
            try:
                from ari.evaluator.dynamic_axes import resolve_live_axis_set
                live_axes = resolve_live_axis_set(cfg, checkpoint_dir)
            except Exception:
                live_axes = None
        for entry in transition.adoptions:
            if str(entry.get("role", "")) != UTILITY_POLICY_ROLE:
                continue
            if isinstance(entry.get("policy"), dict):
                continue
            pid = str(entry.get("prompt_id", "") or "")
            if not pid:
                continue
            try:
                text, _h = resolve(pid, checkpoint_dir=checkpoint_dir)
                body = json.loads(text)
                if isinstance(body, dict):
                    body.pop("utility_policy_hash", None)
                    entry["policy"] = body
                    if live_axes is not None:
                        entry["live_axes"] = list(live_axes)
            except Exception:
                log.warning(
                    "utility_policy body attach failed for %s (kernel gate "
                    "falls back to incumbent-safe no-op)", pid, exc_info=True,
                )

    def _attach_incumbent_capabilities(
        self, transition: EpochTransition, state,
    ) -> None:
        """#79: resolve each capability-declaring adoption's INCUMBENT registry
        entry and attach it as ``entry['_incumbent_entry']`` so the kernel's
        authority-non-expansion gate (CK-REG-101, invariant 18) compares the
        candidate against the incumbent on the LIVE adoption path rather than
        against a ``None`` baseline. The kernel is stateless (it reads only what
        it is passed); the RTE holds the registry, so incumbent resolution lives
        here — the same apply-side pattern as ``_attach_utility_policy_bodies``.

        The incumbent is the currently-ACTIVE component of the adoption's role
        (``ComponentRegistry.active_set``), excluding the candidate itself.
        Best-effort: an unresolvable incumbent (a genuinely new role, or a
        registry read failure) leaves the entry untouched and the gate degrades
        to its prior conservative ``None`` baseline — the CAPABILITY_MATRIX cap
        plus the deny-all flag baseline — so authority is never widened by the
        absence of an incumbent."""
        components = getattr(state, "components", None)
        get = getattr(components, "get", None)
        active_set = getattr(components, "active_set", None)
        if not callable(get) or not callable(active_set):
            return
        try:
            active = active_set()  # role -> component_id (latest active wins)
        except Exception:
            log.warning("incumbent-capability attach: active_set failed",
                        exc_info=True)
            return
        for entry in transition.adoptions:
            if isinstance(entry.get("_incumbent_entry"), dict):
                continue
            if not (entry.get("declared_capabilities")
                    or meta_rules.has_capability_fields(entry)):
                continue
            role = str(entry.get("role", "") or "")
            if not role:
                continue
            inc_id = active.get(role)
            if not inc_id or inc_id == str(entry.get("component_id", "") or ""):
                continue  # no distinct incumbent (founding / self-adoption)
            try:
                inc = get(inc_id)
            except Exception:
                inc = None
            if inc is not None:
                to_dict = getattr(inc, "to_dict", None)
                entry["_incumbent_entry"] = (
                    to_dict() if callable(to_dict) else dict(inc)
                    if isinstance(inc, dict) else None
                )
                if entry.get("_incumbent_entry") is None:
                    entry.pop("_incumbent_entry", None)

    def _validate(self, transition: EpochTransition, state, *,
                  at_boundary: bool):
        if self.kernel is None:
            return None
        report = self.kernel.validate_transition(
            transition.to_dict(), state,
            getattr(state, "epoch", None), at_boundary=at_boundary,
        )
        transition.kernel_validation = {
            "passed": not report.blocking,
            "checks_run": ["validate_transition"],
            "violations": [v.to_dict() for v in report.violations],
        }
        if report.violations:
            self._audit_kernel_report(report)
        return report

    def _validate_dictless(self, transition: EpochTransition, comps: dict):
        """Emergency-path validation against a bare entries map."""
        if self.kernel is None:
            return None

        class _Reg:
            def __init__(self, m):
                self.components = _RegMap(m)

        class _RegMap:
            def __init__(self, m):
                self._m = m

            def get(self, cid):
                return self._m.get(cid)

        report = self.kernel.validate_transition(
            transition.to_dict(), _Reg(comps), None, at_boundary=False,
        )
        transition.kernel_validation = {
            "passed": not report.blocking,
            "checks_run": ["validate_transition"],
            "violations": [v.to_dict() for v in report.violations],
        }
        if report.violations:
            self._audit_kernel_report(report)
        return report

    def _audit(self, event_type: str, payload: dict) -> None:
        if self.audit_log is None:
            return
        try:
            self.audit_log.append(event_type, payload)
        except Exception:
            log.warning("%s audit append failed", event_type, exc_info=True)

    def _audit_kernel_report(self, report) -> None:
        if self.audit_log is None or self.kernel is None:
            return
        try:
            from ari.rqgm.kernel_types import kernel_report_audit_payload

            self.audit_log.append(
                "kernel_report",
                kernel_report_audit_payload(
                    report, self.kernel.constitution_hash
                ),
            )
        except Exception:
            log.warning("kernel_report audit append failed", exc_info=True)

    # ── resolution helpers (all pure) ─────────────────────────────────

    def _freeze_inputs(self, report: dict, evaluations: list,
                       comps: dict, proms: dict) -> dict:
        """Boundary step 1: content hashes over the frozen inputs so the
        transition is auditable and deterministically replayable."""
        eval_refs = [str(_as_dict(e).get("prompt_id", "")) for e in evaluations]
        eval_hashes = [
            _sha256_text(canonical_json(_as_dict(e))) for e in evaluations
        ]
        inputs = {
            "governance_report_ref": str(report.get("record_id", "")),
            "governance_report_sha256": (
                _sha256_text(canonical_json(report)) if report else ""
            ),
            "candidate_evaluation_refs": eval_refs,
            "candidate_evaluation_sha256s": eval_hashes,
            "component_registry_sha256": _sha256_text(canonical_json(
                sorted([cid, str(getattr(e, "status", "")),
                        str(getattr(e, "role", ""))]
                       for cid, e in comps.items())
            )),
            "prompt_registry_sha256": _sha256_text(canonical_json(
                sorted([pid, str(getattr(e, "status", "")),
                        str(getattr(e, "prompt_sha256", ""))]
                       for pid, e in proms.items())
            )),
        }
        inputs["inputs_sha256"] = _sha256_text(canonical_json(inputs))
        return inputs

    def _collect_signals(self, report: dict, notes: list):
        """Recommendations → per-target action lists (report order kept;
        unknown actions dropped with a note, ``_parse_decision`` precedent)."""
        comp_actions: dict = {}
        prompt_actions: dict = {}
        for rec in report.get("recommendations") or ():
            rec = _as_dict(rec)
            action = str(rec.get("action", ""))
            if action not in KNOWN_ACTIONS:
                notes.append(f"dropped unknown recommendation action "
                             f"{action!r}")
                continue
            refs = [str(r) for r in (rec.get("basis_refs") or ())]
            cid = str(rec.get("target_component_id", "") or "")
            pid = str(rec.get("target_prompt_id", "") or "")
            if cid:
                comp_actions.setdefault(cid, []).append((action, refs))
            elif pid:
                prompt_actions.setdefault(pid, []).append((action, refs))
        return comp_actions, prompt_actions

    @staticmethod
    def _replay_coverage(report: dict) -> int:
        usage = report.get("budget_usage")
        usage = usage if isinstance(usage, dict) else {}
        try:
            return int(usage.get("replay_cases_used", 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _ban_targets(report: dict) -> frozenset:
        audit = report.get("self_audit")
        audit = audit if isinstance(audit, dict) else {}
        return frozenset(
            str(c) for c in (audit.get("ban_recommendations") or ())
        )

    @staticmethod
    def _strongest_negative(actions) -> tuple:
        """``(action, refs)`` of the strongest negative signal, or
        ``("", [])``."""
        best, best_refs, strength = "", [], 0
        for action, refs in actions:
            s = _NEGATIVE_STRENGTH.get(action, 0)
            if s > strength:
                best, best_refs, strength = action, list(refs), s
        return best, best_refs

    @staticmethod
    def _since_seq(history: dict, key: str, entry) -> int:
        info = history.get(key)
        if isinstance(info, dict) and "since_seq" in info:
            return int(info["since_seq"])
        return _seq_from_epoch_id(
            str(getattr(entry, "epoch_id_registered", ""))
        ) or 0

    @staticmethod
    def _rule_count(history: dict, key: str, rule_id: str) -> int:
        info = history.get(key)
        if isinstance(info, dict):
            return int((info.get("rule_counts") or {}).get(rule_id, 0))
        return 0

    def _add_change(self, t: EpochTransition, group: str, entry_dict: dict):
        getattr(t, group).append(entry_dict)

    @staticmethod
    def _audit_payload(transition: EpochTransition) -> dict:
        """``to_dict`` minus the transient apply-side attachments —
        ``_``-prefixed keys on adoption entries (``_incumbent_entry`` from
        the #79 attach, utility-policy body attachments). They exist only so
        the stateless kernel can validate; the hash-chained audit event must
        carry durable fields only (the kernel already ran by audit time)."""
        payload = transition.to_dict()
        payload["adoptions"] = [
            {k: v for k, v in e.items() if not str(k).startswith("_")}
            if isinstance(e, dict) else e
            for e in payload.get("adoptions", [])
        ]
        return payload

    def _change(self, cid: str, entry, rule_id: str, to_status: str,
                refs: list, **extra) -> dict:
        out = {
            "component_id": cid,
            "prompt_id": getattr(entry, "prompt_id", None),
            "prompt_hash": getattr(entry, "prompt_hash", None),
            "role": str(getattr(entry, "role", "")),
            "tier": getattr(entry, "tier", None),
            "from_status": str(getattr(entry, "status", "")),
            "to_status": to_status,
            "rule_id": rule_id,
            "evidence_refs": list(refs),
        }
        # #79 producer half: a SUCCESSION entry (T6 adoption; T20/T21
        # supersession — the edges that displace a DISTINCT incumbent)
        # carries the component's declared registry capabilities, so a
        # capability-declaring successor actually reaches the kernel's
        # CK-REG-101 incumbent comparison — without this, no live adoption
        # ever had capability fields and the gate was structurally
        # unreachable (its tests proved the consumer only). Deliberately NOT
        # on the self-shaped activation edges (T7/T8/T12/T14/T18
        # promotion / re-activation / exoneration): there is no distinct
        # incumbent there, so a capability-carrying entry would hit the
        # conservative deny-all None baseline and abort the whole transition
        # — permanently wedging governance for the five founding
        # capability-declaring components. Conditional on non-empty, so
        # every current live entry (no registry entry outside the founding
        # tables declares capabilities) stays byte-identical.
        if rule_id in ("T6", "T20", "T21"):
            caps = getattr(entry, "capabilities", None)
            if isinstance(caps, dict) and caps:
                out["capabilities"] = dict(caps)
        out.update(extra)
        return out

    def _resolve_component(  # noqa: C901 - one closed decision table
        self, t: EpochTransition, cid: str, entry, actions,
        evals_by_prompt: dict, history: dict, cur_seq: int,
        new_status: dict, coverage: int, ban_targets: frozenset,
        adoptions_per_role: dict, t1_per_role: dict, comps: dict,
    ) -> None:
        status = str(getattr(entry, "status", ""))
        role = str(getattr(entry, "role", ""))
        if status not in STATUS_VALUES:
            t.notes.append(
                f"{cid}: unknown status {status!r} — ineligible, skipped"
            )
            return
        negative, neg_refs = self._strongest_negative(actions)
        no_action = any(a == "no_action" for a, _ in actions)
        served = cur_seq - self._since_seq(history, cid, entry)

        def sanction(rule_id, to_status, refs, **extra):
            change = self._change(cid, entry, rule_id, to_status, refs,
                                  **extra)
            self._mirror_prompt(change, to_status)
            self._add_change(t, "sanctions", change)
            new_status[cid] = to_status

        def adopt(rule_id, to_status, refs, **extra):
            change = self._change(cid, entry, rule_id, to_status, refs,
                                  **extra)
            self._mirror_prompt(change, to_status)
            self._add_change(t, "adoptions", change)
            new_status[cid] = to_status

        if status == "active":
            if negative == "warn":
                # T10 "repeated warnings" trigger: once this component has
                # accumulated warning_escalation_count warnings (prior T9
                # applications in the committed history plus this one), the
                # warning escalates straight to probation.
                prior_warnings = self._rule_count(history, cid, "T9")
                if (prior_warnings + 1
                        >= int(self.cfg.warning_escalation_count)):
                    sanction("T10", "probation", neg_refs, severity="medium",
                             reason="repeated_warnings",
                             prompt_to_status=None)
                else:
                    # T9: serving posture only — the prompt keeps serving.
                    sanction("T9", "warning", neg_refs, severity="low",
                             prompt_to_status=None)
            elif negative == "demote":
                sanction("T10", "probation", neg_refs, severity="medium",
                         prompt_to_status=None)
            elif negative in ("quarantine", "retire"):
                extra = {"severity": "high"}
                if negative == "retire":
                    extra["note"] = "retire staged via quarantine (T17 at a later boundary)"
                sanction("T11", "quarantine", neg_refs, **extra)
        elif status == "warning":
            if negative:
                memory = int(self.cfg.warning_memory_epochs)
                if served <= memory:
                    sanction("T13", "probation", neg_refs,
                             prompt_to_status=None)
                else:
                    t.notes.append(
                        f"{cid}: warning recurrence outside "
                        f"warning_memory_epochs ({served} > {memory}); "
                        f"stays warning"
                    )
            elif self._clean(actions):
                # T12: clean epoch (no negative signal this boundary).
                adopt("T12", "active", [r for _, rs in actions for r in rs],
                      prompt_to_status=None)
        elif status == "probation":
            if negative in ("quarantine", "retire"):
                sanction("T15", "quarantine", neg_refs, severity="high")
            elif negative:
                t.notes.append(f"{cid}: stays in probation ({negative})")
            elif served >= int(self.cfg.probation_min_epochs):
                adopt("T14", "active", [], prompt_to_status=None)
            else:
                t.notes.append(
                    f"{cid}: probation_min_epochs not served "
                    f"({served} < {self.cfg.probation_min_epochs})"
                )
        elif status == "probationary_active":
            if negative in ("quarantine", "retire"):
                sanction("T8", "quarantine", neg_refs, severity="high")
            elif negative:
                t.notes.append(
                    f"{cid}: {negative} during probationary_active noted; "
                    f"disposition at T7 review"
                )
            elif served >= int(self.cfg.probation_min_epochs):
                adopt("T7", "active", [])
            else:
                t.notes.append(
                    f"{cid}: probation_min_epochs not served "
                    f"({served} < {self.cfg.probation_min_epochs})"
                )
        elif status == "quarantine":
            if negative == "retire":
                if coverage >= int(self.cfg.retirement_replay_min_cases):
                    n = len(t.retirements)
                    rev = f"retire_{t.epoch_transition_id}_{n:03d}"
                    change = self._change(
                        cid, entry, "T17", "retired", neg_refs,
                        retirement_event_id=rev,
                    )
                    self._mirror_prompt(change, "retired")
                    self._add_change(t, "retirements", change)
                    new_status[cid] = "retired"
                    t.clean_room_requests.append({
                        "request_id": f"cleanroom_req_"
                                      f"{t.epoch_transition_id}_{n:03d}",
                        "target_role": role,
                        "retirement_event_id": rev,
                    })
                else:
                    t.notes.append(
                        f"{cid}: retirement below retirement_replay_min_"
                        f"cases ({coverage} < "
                        f"{self.cfg.retirement_replay_min_cases})"
                    )
            elif no_action:
                # T18 exoneration: re-enters under probation, never active.
                adopt("T18", "probationary_active",
                      [r for _, rs in actions for r in rs])
        elif status == "retired":
            if cid in ban_targets:
                change = self._change(cid, entry, "T19", "banned",
                                      ["self_audit.ban_recommendations"])
                self._mirror_prompt(change, "banned")
                self._add_change(t, "bans", change)
                new_status[cid] = "banned"
        elif status in ("candidate", "validated", "shadow"):
            pid = str(getattr(entry, "prompt_id", "") or "")
            self._resolve_spine(
                t, key=cid, entry=entry, status=status, role=role,
                evaluation=evals_by_prompt.get(pid), history=history,
                cur_seq=cur_seq, new_status=new_status,
                adoptions_per_role=adoptions_per_role,
                t1_per_role=t1_per_role, comps=comps,
                component_level=True, proms=None,
            )
        # "banned" is absorbing: no edges out, ever.

    @staticmethod
    def _clean(actions) -> bool:
        return not any(a in _NEGATIVE_STRENGTH for a, _ in actions)

    @staticmethod
    def _mirror_prompt(change: dict, to_status: str) -> None:
        """Serving sanctions (warning/probation) posture the component only;
        removal/adoption statuses mirror onto the linked prompt entry
        (``prompt_to_status=None`` in the change suppresses the mirror)."""
        if "prompt_to_status" in change:
            return
        if change.get("prompt_id"):
            change["prompt_to_status"] = to_status

    def _resolve_prompt(
        self, t: EpochTransition, pid: str, entry, actions,
        evaluation, history: dict, cur_seq: int, new_status: dict,
        adoptions_per_role: dict, t1_per_role: dict, comps: dict,
        proms: dict | None = None,
    ) -> None:
        """Unpaired governed prompt: candidate spine + T7 auto-promotion."""
        status = str(getattr(entry, "status", ""))
        role = str(getattr(entry, "role", ""))
        if status not in STATUS_VALUES:
            t.notes.append(
                f"{pid}: unknown status {status!r} — ineligible, skipped"
            )
            return
        if status in ("candidate", "validated", "shadow"):
            self._resolve_spine(
                t, key=pid, entry=entry, status=status, role=role,
                evaluation=evaluation, history=history, cur_seq=cur_seq,
                new_status=new_status, adoptions_per_role=adoptions_per_role,
                t1_per_role=t1_per_role, comps=comps, component_level=False,
                proms=proms,
            )
        elif status == "probationary_active":
            negative, _ = self._strongest_negative(actions)
            served = cur_seq - self._since_seq(history, pid, entry)
            if not negative and served >= int(self.cfg.probation_min_epochs):
                self._add_change(t, "adoptions", {
                    "component_id": None,
                    "prompt_id": pid,
                    "prompt_hash": getattr(entry, "prompt_hash", None),
                    "role": role,
                    "from_status": status,
                    "to_status": "active",
                    "rule_id": "T7",
                    "evidence_refs": [],
                })
                new_status[pid] = "active"

    def _resolve_spine(  # noqa: C901 - one closed decision table
        self, t: EpochTransition, *, key: str, entry, status: str,
        role: str, evaluation, history: dict, cur_seq: int,
        new_status: dict, adoptions_per_role: dict, t1_per_role: dict,
        comps: dict, component_level: bool, proms: dict | None = None,
    ) -> None:
        """T1–T6: the candidate → validated → shadow → probationary_active
        spine, one edge per boundary (multi-hop would contradict the
        registry from-status the kernel checks)."""
        ev = _as_dict(evaluation) if evaluation is not None else None
        age = cur_seq - self._since_seq(history, key, entry)

        def change(rule_id, to_status, refs, group, **extra):
            if component_level:
                out = self._change(key, entry, rule_id, to_status, refs,
                                   **extra)
            else:
                out = {
                    "component_id": None,
                    "prompt_id": key,
                    "prompt_hash": getattr(entry, "prompt_hash", None),
                    "role": role,
                    "from_status": status,
                    "to_status": to_status,
                    "rule_id": rule_id,
                    "evidence_refs": list(refs),
                }
                out.update(extra)
            self._add_change(t, group, out)
            new_status[key] = to_status

        if status == "candidate":
            verdict = str(ev.get("verdict", "")) if ev else ""
            if verdict == "fail":
                # T2: never-served rejection — NO RetirementEvent (T17-only);
                # the failure summary rides evidence_refs for Task 08.
                change("T2", "retired", self._eval_refs(ev), "sanctions",
                       reason="validation_failed")
            elif age >= int(self.cfg.candidate_max_age_epochs):
                change("T2", "retired", [], "sanctions",
                       reason="candidate_expired")
            elif verdict == "pass":
                cap = self.cfg.max_candidates_per_role
                if t1_per_role.get(role, 0) < cap:
                    t1_per_role[role] = t1_per_role.get(role, 0) + 1
                    change("T1", "validated", self._eval_refs(ev),
                           "adoptions")
                else:
                    t.notes.append(
                        f"{key}: T1 candidate cap reached for role "
                        f"{role!r}"
                    )
        elif status == "validated":
            if ev is None or str(ev.get("verdict", "")) != "pass":
                return
            replay = ev.get("replay_score")
            anchor = ev.get("anchor_score")
            cases = len(ev.get("case_refs") or ())
            threshold = float(self.cfg.replay_pass_threshold)
            waived = self._declared_no_basis(ev, role, NO_REPLAY_BASIS_KEY)
            # A board that IS reported always gates on its merits — the waiver
            # excuses the case COUNT and an honestly ABSENT board, never a
            # score. Absent both boards WITHOUT the waiver stays a non-pass.
            scores_ok = (
                (replay is None or float(replay) >= threshold)
                and (anchor is None or float(anchor) >= threshold)
            )
            passes = scores_ok and (
                waived
                or (replay is not None
                    and cases >= int(self.cfg.replay_min_cases))
            )
            if passes:
                if waived:
                    t.notes.append(self._waiver_note(key, role, "T3"))
                change("T3", "shadow", self._eval_refs(ev), "adoptions")
            else:
                t.notes.append(
                    f"{key}: T3 replay/anchor guard failed "
                    f"(replay={replay}, cases={cases}, anchor={anchor})"
                )
        elif status == "shadow":
            samples = int((ev or {}).get("shadow_samples") or 0)
            score = (ev or {}).get("shadow_score")
            waived = self._declared_no_basis(ev, role, NO_SHADOW_BASIS_KEY)
            if waived:
                t.notes.append(self._waiver_note(key, role, "T6"))
            if waived or (samples >= int(self.cfg.shadow_min_samples)
                          and score is not None):
                # An absent shadow board under the waiver cannot fail on
                # quality (there is nothing to fail on); a REPORTED one still
                # retires below threshold (T5), waived or not.
                if score is None or float(score) >= float(
                        self.cfg.shadow_pass_threshold):
                    cap = int(self.cfg.max_adoptions_per_role_per_boundary)
                    if adoptions_per_role.get(role, 0) >= cap:
                        t.notes.append(
                            f"{key}: T6 adoption cap reached for role "
                            f"{role!r}"
                        )
                    else:
                        opening = self._role_opening(
                            role, comps, new_status, exclude=key
                        )
                        # Amended 2026-07-16: the utility_policy
                        # criterion is adopted by SUPERSESSION. When no opening
                        # exists (the incumbent is healthy) a shadow-passed
                        # utility_policy successor still adopts — and DISPLACES
                        # the incumbent, retiring it with the OLD hash (T20) so
                        # frontier_repair fires. Behavioral roles keep the
                        # sanction-only model: for them a missing opening is a
                        # "no role opening" no-op, exactly as before.
                        superseded = False
                        if not opening:
                            superseded = self._maybe_supersede_utility_policy(
                                t, role=role, proms=proms,
                                new_status=new_status, successor_key=key,
                                component_level=component_level,
                            )
                        if opening or superseded:
                            adoptions_per_role[role] = (
                                adoptions_per_role.get(role, 0) + 1
                            )
                            change("T6", "probationary_active",
                                   self._eval_refs(ev), "adoptions")
                            # Paper-archive Task 05 (wave 3c):
                            # paper-role co-evolution is PROMPT-level, so on a
                            # successor's T6 adoption demote the incumbent
                            # active prompt to SHADOW STANDBY (T21) — exactly
                            # one active per paper role, never both co-active.
                            self._shadow_superseded_paper_prompt(
                                t, role=role, proms=proms,
                                new_status=new_status, successor_key=key,
                                component_level=component_level,
                            )
                        else:
                            t.notes.append(
                                f"{key}: no role opening for {role!r}"
                            )
                else:
                    # T5: quality below threshold with sufficient samples.
                    change("T5", "retired", self._eval_refs(ev), "sanctions",
                           reason="shadow_quality_below_threshold")
            elif age >= int(self.cfg.shadow_max_epochs):
                retries = self._rule_count(history, key, "T4")
                if retries < int(self.cfg.shadow_retry_limit):
                    change("T4", "validated", [], "sanctions",
                           reason="insufficient_shadow_samples")
                else:
                    change("T5", "retired", [], "sanctions",
                           reason="shadow_retry_limit_exhausted")

    @staticmethod
    def _declared_no_basis(ev, role: str, basis_key: str) -> bool:
        """True iff *ev* DECLARES it has no executed basis for *basis_key*'s
        gate (:data:`NO_REPLAY_BASIS_KEY` for T3's ``replay_min_cases``,
        :data:`NO_SHADOW_BASIS_KEY` for T6's ``shadow_min_samples``) AND *role*
        is one of the cited :data:`NO_REPLAY_BASIS_ROLES`.

        Both halves are required: an evaluator cannot waive a floor for a role
        the plan set does not exempt, and an exempt role gets no waiver unless
        its evaluation actually declares the absence FOR THAT GATE. Waives the
        COUNT floor only — never a score, never a verdict, never the T6 role
        opening."""
        return (
            bool((ev or {}).get(basis_key))
            and str(role) in NO_REPLAY_BASIS_ROLES
        )

    @staticmethod
    def _waiver_note(key: str, role: str, rule_id: str) -> str:
        """The audit note that makes the waiver greppable in the transition
        record: which gate, which role, which declaration, and that the basis is
        DECLARED absent rather than cleared by evidence.

        The reason clause states WHY the role can have no executed basis, so
        the record explains its own waiver instead of deferring to a
        cross-reference the reader may not have."""
        floor, declared = (
            ("replay_min_cases", NO_REPLAY_BASIS_KEY) if rule_id == "T3"
            else ("shadow_min_samples", NO_SHADOW_BASIS_KEY)
        )
        cite = ("a passive policy document is never shadow-executed"
                if role == UTILITY_POLICY_ROLE
                else "a candidate paper prompt has produced nothing to replay")
        return (
            f"{key}: {rule_id} {floor} floor WAIVED — role {role!r} declared "
            f"{declared} (no executed case stands behind this board; {cite}). "
            f"Reported scores still gate on their merits."
        )

    def _maybe_supersede_utility_policy(
        self, t: EpochTransition, *, role: str, proms: dict | None,
        new_status: dict, successor_key: str, component_level: bool,
    ) -> bool:
        """Utility-policy supersession (amended 2026-07-16). A shadow-passed
        ``utility_policy`` successor DISPLACES the healthy incumbent policy:
        emit a T20 (``active -> retired``) retirement for the incumbent policy
        PROMPT carrying the OLD ``utility_policy_hash`` and ``role`` so
        ``frontier_repair`` invalidates every node scored under the retired
        policy. Returns ``True`` iff a supersession retirement was emitted.

        Scoped hard: ONLY the ``utility_policy`` role, ONLY bare-prompt
        candidates (``component_level`` False — the utility policy is a policy
        DOCUMENT, never a behavioral component). Behavioral roles never reach
        this path, so they keep the conservative sanction-only replacement
        model unchanged. The displacement rides the SAME boundary transaction
        as the T6 adoption, so the swap and the invalidation are one committed
        act (the within-epoch freeze holds — the policy changes AT a boundary,
        never inside an epoch; repair runs strictly after commit).
        """
        if component_level or role != UTILITY_POLICY_ROLE or proms is None:
            return False
        incumbent = None
        for pid, prom in proms.items():
            if pid == successor_key:
                continue
            if str(getattr(prom, "role", "")) != UTILITY_POLICY_ROLE:
                continue
            # The serving incumbent is the active policy this successor
            # displaces (post-sanction status wins, so a policy already
            # quarantined this boundary is handled by the ordinary T17 path
            # instead — role_opening would then be True and we never get here).
            status = new_status.get(pid, str(getattr(prom, "status", "")))
            if status == "active":
                incumbent = (pid, prom)
        if incumbent is None:
            return False
        pid, prom = incumbent
        n = len(t.retirements)
        rev = f"supersede_{t.epoch_transition_id}_{n:03d}"
        self._add_change(t, "retirements", {
            "component_id": None,
            "prompt_id": pid,
            "prompt_hash": getattr(prom, "prompt_hash", None),
            "role": UTILITY_POLICY_ROLE,
            "from_status": "active",
            "to_status": "retired",
            "rule_id": "T20",
            "retirement_event_id": rev,
            "evidence_refs": [f"supersession:{successor_key}"],
        })
        new_status[pid] = "retired"
        return True

    def _shadow_superseded_paper_prompt(
        self, t: EpochTransition, *, role: str, proms: dict | None,
        new_status: dict, successor_key: str, component_level: bool,
    ) -> None:
        """Shadow-standby supersession (wave 3c). On a paper-role
        PROMPT T6 adoption, move the role's incumbent active prompt(s) to
        ``shadow`` (T21) so exactly ONE prompt is active per paper role — the
        incumbent is never left co-active behind the latest-wins rollup.

        Scoped hard: ONLY the paper roles, ONLY bare-prompt candidates
        (``component_level`` False). Behavioral roles never reach this path, so
        their sanction-only replacement model is unchanged. Unlike the
        ``utility_policy`` supersession (T20 → retired) this is a REINSTATABLE
        standby: ``shadow`` can re-climb via T6 at a later boundary, so the
        demoted incumbent is never deleted."""
        if (component_level or proms is None
                or role not in transition_rules.PAPER_SUPERSESSION_ROLES):
            return
        for pid, prom in proms.items():
            if pid == successor_key:
                continue
            if str(getattr(prom, "role", "")) != role:
                continue
            status = new_status.get(pid, str(getattr(prom, "status", "")))
            if status != "active":
                continue
            self._add_change(t, "sanctions", {
                "component_id": None,
                "prompt_id": pid,
                "prompt_hash": getattr(prom, "prompt_hash", None),
                "role": role,
                "from_status": "active",
                "to_status": "shadow",
                "rule_id": "T21",
                "evidence_refs": [f"supersession:{successor_key}"],
            })
            new_status[pid] = "shadow"

    @staticmethod
    def _eval_refs(ev) -> list:
        if not ev:
            return []
        refs = [str(r) for r in (ev.get("case_refs") or ())]
        pid = str(ev.get("prompt_id", ""))
        return refs or ([f"candidate_evaluation:{pid}"] if pid else [])

    @staticmethod
    def _role_opening(role: str, comps: dict, new_status: dict,
                      *, exclude: str = "") -> bool:
        """T6 guard: the role has an opening iff no holder is healthy
        (active/probationary_active/warning) AFTER this boundary's
        sanctions — incumbent in probation/quarantine/retired, or role
        unfilled. A healthy holder blocks T6 outright."""
        for cid, entry in comps.items():
            if cid == exclude or str(getattr(entry, "role", "")) != role:
                continue
            status = new_status.get(cid, str(getattr(entry, "status", "")))
            if status in _NO_OPENING_STATUSES:
                return False
        return True

    @staticmethod
    def _active_after(comps: dict, new_status: dict) -> dict:
        """``role -> component_id`` over the post-change serving statuses
        (ACTIVE first; a warning/probation holder keeps the role — warning and
        probation are serving postures). Insertion order = replay order,
        latest wins."""
        primary: dict = {}
        secondary: dict = {}
        for cid, entry in comps.items():
            role = str(getattr(entry, "role", ""))
            status = new_status.get(cid, str(getattr(entry, "status", "")))
            if status in ("active", "probationary_active"):
                primary[role] = cid
            elif status in ("warning", "probation"):
                secondary[role] = cid
        out = dict(secondary)
        out.update(primary)
        return dict(sorted(out.items()))

    def _assign_fallbacks(self, t: EpochTransition, comps: dict,
                          new_status: dict) -> None:
        """Fallback policy for every role whose serving holder was
        removed this transition: the most recent prior version of the role
        still in an eligible serving status, else the committed baseline
        ``.md`` prompt (which always exists). No role is ever left empty."""
        removed_roles: dict = {}
        for cid, entry in comps.items():
            before = str(getattr(entry, "status", ""))
            after = new_status.get(cid, before)
            if before in SERVING_STATUSES and after not in SERVING_STATUSES:
                removed_roles[str(getattr(entry, "role", ""))] = cid
        for role, removed_cid in sorted(removed_roles.items()):
            fallback_cid = None
            for cid, entry in comps.items():  # replay order: latest wins
                if cid == removed_cid:
                    continue
                if str(getattr(entry, "role", "")) != role:
                    continue
                status = new_status.get(cid, str(getattr(entry, "status", "")))
                if status in _FALLBACK_ELIGIBLE:
                    fallback_cid = cid
            if fallback_cid is not None:
                t.fallbacks.append({
                    "role": role,
                    "from_component_id": removed_cid,
                    "fallback_component_id": fallback_cid,
                    "baseline": False,
                })
            else:
                # The committed simple_bfts template for the role.
                t.fallbacks.append({
                    "role": role,
                    "from_component_id": removed_cid,
                    "fallback_component_id": None,
                    "baseline": True,
                })
