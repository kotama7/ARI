"""RQGM vocabulary, id/hash formats, and the transition-event envelope (Task 02).

Single home (plan ``docs/plans/ari_rqgm/02`` §5.4–§5.5, §6) for:

* :func:`canonical_json` — the ONE canonicalisation every RQGM hash uses;
* the id formats (``epoch_%03d``, ``transition_%03d_to_%03d``, ``evt_%06d``,
  ``{role}_v{N}``, ``{role}_prompt_v{N}``);
* the closed status / role / tier vocabularies shared by prompts and
  components (Task 09 owns the transition *table*; this module owns the
  value sets);
* :class:`TransitionEvent` — the hash-chained line envelope shared by
  ``rqgm_transitions.jsonl`` and ``rqgm_audit.jsonl``.

Hash discipline (P2): ``event_hash = hash12(canonical_json(payload))`` where
:func:`ari.prompts._provenance.hash12` is reused verbatim (no second scheme).
Timestamps (``ts`` / ``ts_iso``) are envelope metadata OUTSIDE the hashed
payload — no wall-clock, git SHA, host, or absolute path ever enters a hash.
Pure stdlib: no LLM calls, no network, no randomness.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace

# The exact sha256(text)[:12] scheme used by FilesystemPromptLoader
# .load_versioned — reused, never re-implemented (plan 02 §5.4).
from ari.prompts._provenance import hash12  # noqa: F401  (re-exported)

RQGM_EVENT_SCHEMA_VERSION = 1

# ── vocabulary (owned by Task 02; consumed by Tasks 03–13) ──────────────────

#: Status lifecycle values shared by prompts and components (plan 02 §5.3).
#: Which transitions between them are legal is Task 09's transition table.
STATUS_VALUES: tuple[str, ...] = (
    "candidate",
    "validated",
    "shadow",
    "probationary_active",
    "active",
    "warning",
    "probation",
    "quarantine",
    "retired",
    "banned",
)

#: Statuses that place an entry in the frozen per-epoch active set (§5.6).
ACTIVE_STATUSES: tuple[str, ...] = ("active", "probationary_active")

#: Governed roles whose incumbent may be REPLACED at an epoch boundary
#: (Tasks 03/05/06/07/08/11/14). Prompt-defined, EXCEPT ``utility_policy``,
#: whose incumbent is a policy document (plan 14 §5.3) — the role is
#: evolvable in exactly the same sense: one incumbent, replaced only through
#: the RegistryTransitionEngine at a boundary.
#:
#: ``replay_selector``: plan 11 §5.1 uses the name ``replay_case_selector``;
#: registered here under the Task 05 name (the codebase name wins).
EVOLVABLE_ROLES: tuple[str, ...] = (
    "generator",
    "reviewer",
    "adversary",
    "defender",
    "judge",
    "router",
    "prompt_mutator",
    "clean_room_generator",
    "replay_selector",
    "failure_summary_compressor",
    # Task 14 (plan 14 §5.2): the role limbo, resolved. Both roles were
    # named by live code — ``frontier_repair.INVALIDATE_ROLES`` and
    # ``adversarial.records.UTILITY_POLICY_ROLE`` for ``utility_policy``,
    # ``meta_rules.META_FROZEN_ROLES`` for ``policy_mutator`` — while being
    # in NEITHER half of ``ROLES``, so neither could ever be registered.
    "policy_mutator",     # un-frozen from meta_rules.META_FROZEN_ROLES
    "utility_policy",     # the governed score itself
    # Paper-archive co-evolution (plan ari_rqgm_paper/03 §5.2): promote the
    # manuscript WRITER from a context-scope-only entry to a full evolvable
    # role, and add the manuscript REVIEWER as a new evaluable role. Both
    # DRIVE the ungoverned ari-skill-paper executor (the skill is the hands);
    # the skill itself imports no ari.rqgm and is never governed cross-process.
    # They enter the registry only under the effective ``rqgm_archive`` paper
    # mode (paper-mode-gated founding registration), so an exploration
    # ``ari_rqgm`` boot is byte-identical.
    "paper_writer",
    "paper_reviewer",
)

#: Governance-actor roles (#78b, 2026-07-28): the auditor / evidence_clerk /
#: governance_judge that run the impeachment machinery. A THIRD role category,
#: distinct from both halves above: unlike ``EVOLVABLE_ROLES`` they have no
#: prompt-mutation successor path (no meta agent emits governance-actor
#: candidates), and unlike ``FIXED_ROLES`` they are NOT constitutionally
#: immutable — they are institutional actors that can be sanctioned, retired
#: and banned like any other component. They were named by live code
#: (``kernel_rules._GOVERNANCE_ROLES``, ``governance/_pipeline``) while being in
#: NEITHER half of ``ROLES``, so no registry entry could represent them and the
#: judiciary that adjudicates every impeachment was itself unregistered
#: (``*_v0``) and unimpeachable — the same "role limbo" Task 14 closed for
#: ``utility_policy`` / ``policy_mutator``, closed here for the judiciary (P4).
GOVERNANCE_ACTOR_ROLES: tuple[str, ...] = (
    "auditor",
    "evidence_clerk",
    "governance_judge",
)

#: Fixed-layer entries — registered for provenance but constitutionally
#: immutable (INDEX invariant: kernel / fixed verifier / audit log never
#: evolve; enforced by Tasks 04/09, stored here).
FIXED_ROLES: tuple[str, ...] = (
    "constitutional_kernel",
    "fixed_verifier",
    "audit_log",
)

ROLES: tuple[str, ...] = EVOLVABLE_ROLES + GOVERNANCE_ACTOR_ROLES + FIXED_ROLES

#: Task 14 role names, stated once here (the vocabulary module) so no
#: consumer re-spells them. ``ari.rqgm.adversarial.records`` keeps its own
#: equal literal (Task 06's module, import-light by design); the parity is
#: pinned by the role-limbo regression test in
#: ``tests/test_rqgm_utility_evolution.py``.
UTILITY_POLICY_ROLE = "utility_policy"
POLICY_MUTATOR_ROLE = "policy_mutator"

#: Component tiers (Task 11 consumes ``meta``; present from day one so adding
#: it later is not a schema bump — plan 02 §5.3).
TIERS: tuple[str, ...] = ("fixed", "institutional", "meta")

#: Closed v1 event-type set for ``rqgm_transitions.jsonl`` (plan 02 §6).
EVENT_TYPES: tuple[str, ...] = (
    "epoch_transaction_prepare",
    "component_registered",
    "prompt_registered",
    "component_status_change",
    "prompt_status_change",
    "epoch_close",
    "epoch_open",
    "epoch_transaction_commit",
    "emergency_quarantine",
)

#: The sole event type accepted OUTSIDE an epoch-boundary transaction
#: (the spec's emergency exception; still logged and kernel-validated).
EMERGENCY_EVENT_TYPE = "emergency_quarantine"


# ── canonical hashing (P2) ──────────────────────────────────────────────────


def canonical_json(payload: object) -> str:
    """The single canonical JSON form every RQGM hash is computed over.

    Byte-golden-pinned by tests before anything consumes it (plan 02 §10):
    sorted keys, no whitespace, ``ensure_ascii=False``.
    """
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def payload_hash(payload: object) -> str:
    """``hash12(canonical_json(payload))`` — the event/fingerprint hash."""
    return hash12(canonical_json(payload))


# ── id formats (plan 02 §5.5) ───────────────────────────────────────────────


def format_epoch_id(epoch_seq: int) -> str:
    """``epoch_%03d`` — per-checkpoint counter starting ``epoch_000``."""
    return "epoch_%03d" % int(epoch_seq)


def format_transition_id(from_seq: int, to_seq: int) -> str:
    """``transition_%03d_to_%03d`` (e.g. ``transition_003_to_004``)."""
    return "transition_%03d_to_%03d" % (int(from_seq), int(to_seq))


def format_event_id(event_seq: int) -> str:
    """``evt_%06d`` — per-checkpoint monotonic line counter from ``evt_000000``."""
    return "evt_%06d" % int(event_seq)


def format_component_id(role: str, version: int) -> str:
    """``{role}_v{N}`` (spec example: ``reviewer_v3``)."""
    return f"{role}_v{int(version)}"


def format_prompt_id(role: str, version: int) -> str:
    """``{role}_prompt_v{N}`` (spec example: ``reviewer_prompt_v4``)."""
    return f"{role}_prompt_v{int(version)}"


# ── the hash-chained line envelope ──────────────────────────────────────────


@dataclass(frozen=True)
class TransitionEvent:
    """One line of ``rqgm_transitions.jsonl`` / ``rqgm_audit.jsonl``.

    Callers construct it with just ``event_type`` + ``payload``; the store
    fills the envelope fields (``event_id``, ``event_hash``,
    ``prev_event_hash``, ``ts``/``ts_iso``) at append time under its lock via
    :func:`finalize_event`. Frozen so a finalized event can never be edited.
    """

    event_type: str
    payload: dict = field(default_factory=dict)
    event_id: str = ""
    event_hash: str = ""
    prev_event_hash: str = ""
    ts: float | None = None
    ts_iso: str = ""
    schema_version: int = RQGM_EVENT_SCHEMA_VERSION

    def to_line_dict(self) -> dict:
        """JSONL line layout, key order fixed to the plan's §6 example."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "event_hash": self.event_hash,
            "prev_event_hash": self.prev_event_hash,
            "ts": self.ts,
            "ts_iso": self.ts_iso,
        }


def finalize_event(
    event: TransitionEvent,
    *,
    event_seq: int,
    prev_event_hash: str,
) -> TransitionEvent:
    """Fill the envelope: id from *event_seq*, hash chain, timestamp metadata.

    ``event_hash`` covers ONLY the payload (via :func:`canonical_json`);
    the timestamps assigned here never enter any hash (P2).
    """
    now = time.time()
    return replace(
        event,
        event_id=format_event_id(event_seq),
        event_hash=payload_hash(event.payload),
        prev_event_hash=prev_event_hash,
        ts=now,
        ts_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
    )


def event_from_line_dict(d: dict) -> TransitionEvent:
    """Rebuild a :class:`TransitionEvent` from a parsed JSONL line (replay)."""
    return TransitionEvent(
        event_type=str(d.get("event_type", "")),
        payload=d.get("payload") if isinstance(d.get("payload"), dict) else {},
        event_id=str(d.get("event_id", "")),
        event_hash=str(d.get("event_hash", "")),
        prev_event_hash=str(d.get("prev_event_hash", "")),
        ts=d.get("ts") if isinstance(d.get("ts"), (int, float)) else None,
        ts_iso=str(d.get("ts_iso", "")),
        schema_version=int(d.get("schema_version", RQGM_EVENT_SCHEMA_VERSION)),
    )
