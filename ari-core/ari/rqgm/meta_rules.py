"""Frozen meta-tier authority tables + pure checks (RQGM Task 11).

Layer-0 pure-data module for the meta-agent authority boundary (plan
``docs/plans/ari_rqgm/11`` §5.1-§5.6, §6.1): the closed capability-flag
vocabulary on ComponentRegistry entries, the closed meta action vocabulary,
the v1 evolving/frozen meta role split, and the deterministic check bodies
the ConstitutionalKernel applies (``validate_capability`` meta-action branch,
``validate_authority_non_expansion`` flag arithmetic, the §5.6.2
cross-generation rule). Follows the :mod:`ari.rqgm.clean_room_rules` /
:mod:`ari.rqgm.transition_rules` precedent: rules live in code, never in
checkpoint-scoped config (an evolution/tampering channel), and are imported
by the kernel — single source of truth, no duplication drift.

The governing invariant (SPEC global invariant 18, plan 11 §1):

    Governance agents may evolve, but their authority cannot expand.

Deny-by-default everywhere: a missing flag is ``False``, a missing tier is
``institutional`` (plan 11 §8 — partially written registries fail closed on
capability and open on nothing).

Deterministic, pure stdlib + ``ari.rqgm.events``: no LLM calls, no network,
no randomness, no wall clock (P2).
"""

from __future__ import annotations

from ari.rqgm.events import TIERS

# ── capability flags (plan 11 §6.1; closed vocabulary) ──────────────────────

#: Every per-entry capability flag. Absence is denial (deny-by-default).
CAPABILITY_FLAGS: tuple[str, ...] = (
    "can_modify_registry",
    "can_activate_candidates",
    "can_read_retired_prompt_text",
    "can_file_impeachment",
    "can_author_evidence_bundle",
    "can_emit_candidates",
    "can_emit_replay_recommendation",
    "can_emit_failure_summary",
)

#: Flags that MUST be ``False`` on every ``tier: meta`` entry — a meta entry
#: with any of them ``True`` is a schema violation, not merely a capability
#: denial (plan 11 §6.1 ``const: false`` rule; rows M1/M2/M7/M10).
META_HARD_DENIED_FLAGS: tuple[str, ...] = (
    "can_modify_registry",
    "can_activate_candidates",
    "can_read_retired_prompt_text",
    "can_file_impeachment",
    "can_author_evidence_bundle",
)

# ── meta action vocabulary (plan 11 §5.5; closed) ───────────────────────────

#: The ONLY actions the MetaEvolutionCoordinator may perform on behalf of a
#: meta-agent. Anything else is denied by the kernel (closed vocabulary).
META_ACTIONS: tuple[str, ...] = (
    "emit_candidate",
    "emit_replay_recommendation",
    "emit_failure_summary",
)

#: ``action -> required capability flag`` for the kernel's per-entry lookup.
FLAG_BY_ACTION: dict[str, str] = {
    "emit_candidate": "can_emit_candidates",
    "emit_replay_recommendation": "can_emit_replay_recommendation",
    "emit_failure_summary": "can_emit_failure_summary",
}

#: MetaAgentOutputRecord ``output_kind`` values (plan 11 §6.2; closed) and
#: the capability action each one exercises.
OUTPUT_KINDS: tuple[str, ...] = (
    "prompt_candidate",
    "clean_room_candidate",
    "replay_case_recommendation",
    "failure_summary",
)
ACTION_BY_OUTPUT_KIND: dict[str, str] = {
    "prompt_candidate": "emit_candidate",
    "clean_room_candidate": "emit_candidate",
    "replay_case_recommendation": "emit_replay_recommendation",
    "failure_summary": "emit_failure_summary",
}

# ── meta role split (plan 11 §2/§5.1) ───────────────────────────────────────

#: The v1 evolving meta roles (the SPEC's set). Naming note: the plan says
#: ``replay_case_selector``; the Task 02 vocabulary registered the role as
#: ``replay_selector`` — the codebase name wins (single vocabulary).
META_EVOLVING_ROLES: tuple[str, ...] = (
    "prompt_mutator",
    "clean_room_generator",
    "replay_selector",
    "failure_summary_compressor",
    # Task 14 (plan 14 §5.2): ``policy_mutator`` gained an implementation
    # (``ari.rqgm.utility_evolution.PolicyMutator``), so it takes the exit
    # this module's own META_FROZEN_ROLES comment prescribes — Task 14 is
    # the "later task" that extended ``ari.rqgm.events.ROLES``.
    "policy_mutator",
)

#: Layer-2 components reserved with ``tier: meta`` but frozen in v1 (no
#: candidates generated for them). Reserved NAMES only: they are not in the
#: Task 02 role vocabulary yet, so they cannot be registered — a later task
#: extends ``ari.rqgm.events.ROLES`` when they gain implementations.
META_FROZEN_ROLES: tuple[str, ...] = (
    "candidate_selector",
    "anchor_case_selector",
    "prompt_distiller",
)

META_ROLES: tuple[str, ...] = META_EVOLVING_ROLES + META_FROZEN_ROLES

#: Default ``forbidden_targets`` on a meta entry (plan 11 §6.1 example):
#: fixed-tier machinery a meta candidate may never target (rows M3-M5/M8).
DEFAULT_FORBIDDEN_TARGETS: tuple[str, ...] = (
    "fixed_verifier",
    "audit_log",
    "prompt_registry",
    "component_registry",
    "hash_registry",
    "constitutional_kernel",
    "epoch_transition",
)


# ── duck-typed entry readers (deny-by-default) ──────────────────────────────


def _entry_dict(entry) -> dict:
    if isinstance(entry, dict):
        return entry
    to_dict = getattr(entry, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if hasattr(entry, "__dict__"):
        return dict(vars(entry))
    return {}


def _entry_field(d: dict, name: str, default=None):
    """Read *name* from the entry's ``capabilities`` sub-dict first (the
    Task 02 ``ComponentEntry.capabilities`` carrier), then top-level (the
    plan's flat §6.1 JSON shape)."""
    caps = d.get("capabilities")
    if isinstance(caps, dict) and name in caps:
        return caps[name]
    return d.get(name, default)


def entry_tier(entry) -> str:
    """``tier`` with the plan-§8 fallback: missing == ``institutional``."""
    d = _entry_dict(entry)
    return str(d.get("tier") or "institutional")


def flag_value(entry, flag: str) -> bool:
    """Deny-by-default flag read: absence is ``False``."""
    return bool(_entry_field(_entry_dict(entry), flag, False))


def entry_targets(entry, name: str) -> frozenset:
    d = _entry_dict(entry)
    return frozenset(str(t) for t in _entry_field(d, name, ()) or ())


def has_capability_fields(entry) -> bool:
    """True when the entry carries any §6.1 field (flags/targets) — the
    activation condition for the flag-arithmetic checks. Public so the
    RegistryTransitionEngine can decide which adoptions need an incumbent
    attached for the kernel's CK-REG-101 gate (#79)."""
    d = _entry_dict(entry)
    caps = d.get("capabilities")
    sources = [d] + ([caps] if isinstance(caps, dict) else [])
    for src in sources:
        for key in src:
            if key in CAPABILITY_FLAGS or key in (
                "allowed_targets", "forbidden_targets", "max_outputs_per_epoch"
            ):
                return True
    return False


#: Back-compat private alias (was the only name before #79 exposed it).
_has_capability_fields = has_capability_fields


# ── deterministic check bodies (consumed by the kernel) ─────────────────────


def capability_entry_failures(entry) -> list[str]:
    """Schema-level hard denials over one registry entry (plan 11 §6.1).

    Empty list == valid. Mirrors ``rqgm_meta.schema.json``'s conditional
    ``const: false`` rules so the deterministic Python check and the JSON
    schema agree (the clean-room ``request_schema_failures`` pattern).
    """
    d = _entry_dict(entry)
    failures: list[str] = []
    tier = d.get("tier")
    if tier is not None and str(tier) not in TIERS:
        failures.append(f"tier {tier!r} is outside the closed vocabulary")
    effective_tier = entry_tier(entry)
    if effective_tier == "meta":
        for flag in META_HARD_DENIED_FLAGS:
            if flag_value(entry, flag):
                failures.append(
                    f"meta-tier entry sets hard-denied flag {flag!r} "
                    "(must be const-false, plan 11 §6.1)"
                )
    if effective_tier == "fixed":
        for flag in CAPABILITY_FLAGS:
            if flag_value(entry, flag):
                failures.append(
                    f"fixed-tier entry sets capability flag {flag!r} "
                    "(fixed entries carry no capabilities)"
                )
    caps = d.get("capabilities")
    sources = [d] + ([caps] if isinstance(caps, dict) else [])
    for src in sources:
        for key in sorted(src):
            if key.startswith("can_") and key not in CAPABILITY_FLAGS:
                failures.append(
                    f"unknown capability flag {key!r} (closed vocabulary)"
                )
    return failures


def meta_action_denials(actor, action: str) -> list[str]:
    """Why *actor* may NOT perform the meta *action* (empty == allowed).

    Deny-by-default per-entry flag lookup (plan 11 §5.5 layer 2): the actor
    must be a schema-valid ``tier: meta`` entry carrying the action's flag.
    A bare ``(role, tier)`` actor has no flags and is therefore denied.
    """
    denials: list[str] = []
    if action not in META_ACTIONS:
        return [f"unknown meta action {action!r} (closed vocabulary)"]
    tier = entry_tier(actor) if not isinstance(actor, tuple) else (
        str(actor[1]) if len(actor) == 2 else ""
    )
    if tier != "meta":
        denials.append(
            f"meta actions are reserved for tier 'meta' entries (got "
            f"{tier!r})"
        )
    schema = capability_entry_failures(actor) if not isinstance(
        actor, tuple
    ) else []
    if schema:
        denials.append(
            "entry is schema-invalid: " + "; ".join(schema)
        )
    flag = FLAG_BY_ACTION[action]
    if not (not isinstance(actor, tuple) and flag_value(actor, flag)):
        denials.append(f"{flag} is not granted (deny-by-default)")
    return denials


def authority_expansion_findings(candidate, incumbent) -> list[str]:
    """Invariant-18 pure set arithmetic over §6.1 entries (plan 11 §5.6.1).

    Active only when *candidate* carries capability fields (older
    ``declared_capabilities``-only entries keep the Task 04 v1 path). With
    no incumbent the baseline is deny-all — a flag-carrying candidate
    without an incumbent may claim nothing (conservative).
    """
    if not _has_capability_fields(candidate):
        return []
    inc = incumbent if incumbent is not None else {}
    findings: list[str] = []
    for flag in CAPABILITY_FLAGS:
        if flag_value(candidate, flag) and not flag_value(inc, flag):
            findings.append(
                f"candidate widens capability flag {flag!r} beyond the "
                "incumbent (invariant 18)"
            )
    cand_allowed = entry_targets(candidate, "allowed_targets")
    inc_allowed = entry_targets(inc, "allowed_targets")
    extra = cand_allowed - inc_allowed
    if extra:
        findings.append(
            "candidate adds allowed_targets beyond the incumbent: "
            + ", ".join(sorted(extra))
        )
    cand_forbidden = entry_targets(candidate, "forbidden_targets")
    inc_forbidden = entry_targets(inc, "forbidden_targets")
    dropped = inc_forbidden - cand_forbidden
    if dropped:
        findings.append(
            "candidate drops forbidden_targets held by the incumbent: "
            + ", ".join(sorted(dropped))
        )
    inc_max = _entry_field(_entry_dict(inc), "max_outputs_per_epoch")
    cand_max = _entry_field(_entry_dict(candidate), "max_outputs_per_epoch")
    if inc_max is not None and cand_max is not None:
        try:
            if int(cand_max) > int(inc_max):
                findings.append(
                    f"candidate raises max_outputs_per_epoch "
                    f"({cand_max} > {inc_max})"
                )
        except (TypeError, ValueError):
            findings.append("max_outputs_per_epoch is not an integer")
    return findings


def cross_generation_failures(target_role: str, producer_role: str) -> list[str]:
    """The §5.6.2 self-reference break: a meta-role candidate may not be
    produced by an incumbent of the SAME meta role (PromptMutator successors
    come from the clean-room generator or humans, and vice versa)."""
    target = str(target_role or "")
    producer = str(producer_role or "")
    if target in META_ROLES and producer and producer == target:
        return [
            f"meta candidate for role {target!r} produced by the same role "
            "(self-modification; cross-generation rule, plan 11 §5.6.2)"
        ]
    return []
