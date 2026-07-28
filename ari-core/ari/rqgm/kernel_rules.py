"""Frozen constitutional rule tables (RQGM Task 04, plan 04 §5.4–§5.7, §6).

Rules live in code, not in mutable config: putting role rules or the
capability matrix in a checkpoint-scoped YAML would create an
evolution/tampering channel (any skill can write the flat checkpoint dir).
Only numeric tolerances live in ``ari-core/ari/configs/defaults.yaml``
(``rqgm.kernel.*``). The transition table is NOT here — it is imported from
:mod:`ari.rqgm.transition_rules` (Task 09's Layer-0 module, shared with the
engine; single source of truth, no duplication drift).

Non-evolution is made mechanically checkable via :func:`constitution_hash`:
``sha256(canonical_json(TRANSITION_TABLE, EMERGENCY_EDGE, ROLE_RULES,
CAPABILITY_MATRIX, SEVERITY, CONSTITUTION_VERSION))[:12]``, computed over
content only (no wall clock, git SHA, or host — P2) and hand-pinned in
``ari-core/tests/test_rqgm_kernel.py`` (the ``_EXPECTED_HASHES`` pattern).
Any rule edit — including one to the imported ``transition_rules.py`` — is an
explicit reviewed diff plus a hash re-pin.

Deterministic, pure stdlib + ``ari.rqgm`` types: no LLM calls, no network,
no randomness (enforced by the import-grep test, plan 04 §5.7/§9.7).
"""

from __future__ import annotations

from ari.rqgm import transition_rules
from ari.rqgm.events import canonical_json, hash12

CONSTITUTION_VERSION: int = 1

# ── role-separation rules (plan 04 §5.4 item 6, plan 05 §5.4) ───────────────

#: The single component allowed to write registry status (invariant 10).
REGISTRY_WRITER = "registry_transition_engine"

#: ``{record_type: required_author_role}`` — wrong-author records are
#: role-separation violations. Record schemas are Task 05 deliverables; the
#: author-role constants are fixed constitutionally here.
ROLE_RULES: dict[str, str] = {
    "impeachment_motion": "auditor",
    "evidence_bundle": "evidence_clerk",
}

#: Record types whose payloads carry an accusation target: the accuser role
#: must differ from the accused role (same-role outputs are observations,
#: never accusations — invariants 4–7).
ACCUSATION_RECORD_TYPES: tuple[str, ...] = (
    "impeachment_motion",
    "evidence_bundle",
)

#: Governance record types whose schema violations hard-block (CK-SCH-G*);
#: every other RQGM record type is per-node (CK-SCH-N*, warn-and-flag).
GOVERNANCE_RECORD_TYPES: tuple[str, ...] = (
    "epoch_transition",
    "governance_report",
)

#: Mandatory common record envelope (plan 02 §6 ``rqgm_record_base``).
ENVELOPE_FIELDS: tuple[str, ...] = (
    "record_id",
    "epoch_id",
    "component_id",
    "prompt_hash",
    "role",
    "created_at",
    "source_refs",
    "status",
)

# ── capability matrix (plan 04 §5.4 item 3, §6) ─────────────────────────────

#: Closed action / resource-class vocabularies for capability lookups.
ACTIONS: tuple[str, ...] = ("read", "append", "write", "invoke", "activate")
RESOURCE_CLASSES: tuple[str, ...] = (
    "records",
    "registry",
    "audit_log",
    "frontier",
    "active_prompt_text",
    "retired_prompt_text",
    "checkpoint_artifacts",
    "candidates",
)

_Cap = tuple[str, str]

# Baseline grants per tier. Constitutional constants baked in:
# * NOBODY may read retired prompt text (Task 08's clean-room path has its
#   own whitelist and never flows through this matrix).
# * Only the RegistryTransitionEngine may write the registry or activate
#   candidates (invariant 10; Judge writing the registry is a named
#   violation).
# * meta-tier components additionally never write registries nor activate
#   candidates (invariant 18 posture; Task 11 refines).
_INSTITUTIONAL_BASE: frozenset[_Cap] = frozenset({
    ("read", "records"),
    ("read", "active_prompt_text"),
    ("read", "checkpoint_artifacts"),
    ("append", "records"),
    ("invoke", "records"),
})
_META_BASE: frozenset[_Cap] = frozenset({
    ("read", "records"),
    ("read", "active_prompt_text"),
    ("append", "records"),
})
_FIXED_READONLY: frozenset[_Cap] = frozenset({
    ("read", "records"),
    ("read", "registry"),
    ("read", "audit_log"),
    ("read", "frontier"),
    ("read", "checkpoint_artifacts"),
})

_EVOLVABLE_ROLES: tuple[str, ...] = (
    "generator",
    "reviewer",
    "adversary",
    "defender",
    "judge",
    "router",
    "prompt_mutator",
    "clean_room_generator",
    "replay_selector",
    # Constitutional amendment 2026-07-14: ``failure_summary_compressor``
    # was in ``ari.rqgm.events.EVOLVABLE_ROLES`` (and the Task 11 meta
    # vocabulary) but missing from this matrix, so every capability lookup
    # for the role was CK-ACC-001-blocked in every tier. It receives the
    # same minimal grants as ``replay_selector`` (meta tier: read records /
    # active prompt text, append records — no broader authority). The
    # CONSTITUTION_HASH pin in tests/test_rqgm_kernel.py was re-pinned for
    # this amendment.
    "failure_summary_compressor",
    # Constitutional amendment 2026-07-16 (plan 14 §5.2): ``policy_mutator``
    # is a meta-tier proposer (``ari.rqgm.utility_evolution.PolicyMutator``)
    # with the same minimal grants as ``prompt_mutator``. Registered at
    # ``tier: meta``, where META_HARD_DENIED_FLAGS (meta_rules.py) already
    # makes can_modify_registry / can_activate_candidates a SCHEMA
    # violation rather than a mere denial. The CONSTITUTION_HASH pin in
    # tests/test_rqgm_kernel.py was re-pinned for this amendment.
    "policy_mutator",
    # Constitutional amendment 2026-07-16 (plan ari_rqgm_paper/03 §5.2):
    # ``paper_writer`` is PROMOTED from a context-scope-only whitelist entry
    # (the 2026-07-15 "deliberately NOT EVOLVABLE" note below is SUPERSEDED)
    # to a full evolvable writer role, and ``paper_reviewer`` is a new
    # evaluable evaluator role. Both receive the same minimal institutional +
    # meta grants as ``generator`` / ``reviewer`` (no registry write, no
    # candidate activation). They drive the ungoverned ari-skill-paper
    # executor. The CONSTITUTION_HASH pin in tests/test_rqgm_kernel.py was
    # re-pinned for this amendment.
    "paper_writer",
    "paper_reviewer",
)
#: Governance-actor roles (Task 05 vocabulary; institutional tier only).
#: Constitutional amendment 2026-07-28 (#78b): ``governance_judge`` joins the
#: two Task-05 governance actors. The judge that adjudicates every impeachment
#: motion was an unregistered ``governance_judge_v0`` bootstrap id — outside the
#: role vocabulary, hence never a registrable component and therefore itself
#: unimpeachable (a P4 "no unimpeachable ruler" gap). It is now a real role with
#: the SAME institutional grants as the auditor / evidence_clerk (base + read /
#: append audit_log) and a founding component
#: (``prompt_spec.FOUNDING_COMPONENT_TABLE``), so it is governed, sanctionable
#: and retirable like every other actor. It never writes the registry or
#: activates candidates — that authority is the fixed ``REGISTRY_WRITER`` alone.
#: The CONSTITUTION_HASH pin in tests/test_rqgm_kernel.py was re-pinned for this
#: amendment.
_GOVERNANCE_ROLES: tuple[str, ...] = (
    "auditor",
    "evidence_clerk",
    "governance_judge",
)

#: Constitutional amendment 2026-07-16 (plan 14 §5.2): ``utility_policy`` is
#: deliberately NOT in ``_EVOLVABLE_ROLES`` above. It is a passive policy
#: DOCUMENT, not an actor: it gets ONE explicit institutional row, narrower
#: than ``_INSTITUTIONAL_BASE`` — no ``invoke``, no ``read
#: active_prompt_text``, no ``read checkpoint_artifacts``. The only thing
#: ever stamped in its name is the UtilityRecord
#: (``ari.rqgm.adversarial.records.UtilityRecord``). A policy that could
#: ``invoke`` or ``write registry`` would not be a policy.
#:
#: It still needs a row: a role in ``events.EVOLVABLE_ROLES`` with NO matrix
#: row is CK-ACC-001-blocked in every tier — the exact regression recorded
#: for ``failure_summary_compressor`` above.
_UTILITY_POLICY_CAPS: frozenset[_Cap] = frozenset({
    ("read", "records"),
    ("append", "records"),
})


def _build_capability_matrix() -> dict[tuple[str, str], frozenset[_Cap]]:
    matrix: dict[tuple[str, str], frozenset[_Cap]] = {}
    for role in _EVOLVABLE_ROLES:
        matrix[(role, "institutional")] = _INSTITUTIONAL_BASE
        matrix[(role, "meta")] = _META_BASE
    matrix[("utility_policy", "institutional")] = _UTILITY_POLICY_CAPS
    for role in _GOVERNANCE_ROLES:
        matrix[(role, "institutional")] = _INSTITUTIONAL_BASE | frozenset(
            {("append", "audit_log"), ("read", "audit_log")}
        )
    matrix[(REGISTRY_WRITER, "fixed")] = _FIXED_READONLY | frozenset({
        ("write", "registry"),
        ("activate", "candidates"),
        ("append", "audit_log"),
    })
    matrix[("constitutional_kernel", "fixed")] = _FIXED_READONLY
    matrix[("fixed_verifier", "fixed")] = _FIXED_READONLY
    matrix[("audit_log", "fixed")] = frozenset({("append", "audit_log")})
    return matrix


#: ``{(role, tier): frozenset[(action, resource_class)]}`` — pure lookup
#: table for ``validate_capability`` (pre-flight AND post-hoc replay modes).
CAPABILITY_MATRIX: dict[tuple[str, str], frozenset[_Cap]] = (
    _build_capability_matrix()
)

# ── the violation catalogue (stable codes; §5.4/§5.5) ───────────────────────

#: ``{violation_code: "block" | "warn"}`` — the normative severity map
#: backing the §5.5 blocking matrix. Codes are frozen once implemented and
#: never renumbered.
SEVERITY: dict[str, str] = {
    # schema (CK-SCH-*)
    "CK-SCH-G01": "block",  # governance record fails schema/envelope check
    "CK-SCH-N01": "warn",   # per-node record fails schema/envelope check
    "CK-SCH-N02": "warn",   # per-node summary exceeds a field budget
    # hashes (CK-HSH-*)
    "CK-HSH-001": "warn",   # record prompt_hash mismatch vs registered hash
    "CK-HSH-002": "warn",   # artifact_hash mismatch vs recomputed sha256
    "CK-HSH-003": "warn",   # unresolvable source_ref / missing artifact
    "CK-HSH-010": "block",  # ACTIVE component's registered hash mismatch
    # capability / access (CK-ACC-*)
    "CK-ACC-001": "block",  # out-of-scope access (pre-flight DENY)
    "CK-ACC-002": "block",  # retired-prompt-text access
    # epoch invariance (CK-EPO-*)
    "CK-EPO-001": "warn",   # record prompt_hash outside the frozen active set
    "CK-EPO-002": "block",  # non-emergency active-set change mid-epoch
    # transition rules (CK-REG-*)
    "CK-REG-001": "block",  # (from,to) pair not in the transition table
    "CK-REG-002": "block",  # boundary-only transition stamped mid-epoch
    "CK-REG-003": "block",  # declared rule_id contradicts the table
    "CK-REG-004": "block",  # transition not produced by the RTE
    "CK-REG-005": "block",  # required supporting refs missing
    "CK-REG-006": "block",  # emergency transition shape invalid
    "CK-REG-007": "block",  # from_status contradicts the registry
    "CK-REG-101": "block",  # authority expansion by an evolving candidate
    # role separation (CK-ROL-*)
    "CK-ROL-001": "warn",   # ImpeachmentMotion authored by non-Auditor
    "CK-ROL-002": "warn",   # EvidenceBundle authored by non-EvidenceClerk
    "CK-ROL-003": "warn",   # same-role accusation
    "CK-ROL-901": "block",  # non-RTE actor writing the registry
    # selective erasure (CK-ERA-*)
    "CK-ERA-001": "block",  # stale record present in frontier
    "CK-ERA-002": "block",  # valid_for_frontier=False record in frontier
    "CK-ERA-003": "block",  # retired-prompt-derived record in frontier
    "CK-ERA-004": "block",  # retired-prompt-dependent record not staled
    "CK-ERA-005": "block",  # physical deletion detected (invariant 13)
    "CK-ERA-006": "block",  # prompt_trace line with retired hash unmapped
    # audit log (CK-AUD-*)
    "CK-AUD-001": "block",  # sequence regression / duplicate event ids
    "CK-AUD-002": "block",  # check-pointed prefix mutated
    "CK-AUD-003": "block",  # hash chain broken
    # clean room (CK-CLN-*, semantics: Task 08)
    "CK-CLN-001": "block",  # clean-room bundle violation
    "CK-CLN-002": "block",  # contamination detected
    # context scope (CK-CTX-*, whitelist owner: Task 12)
    "CK-CTX-001": "warn",   # role view exceeds its whitelist
    # governed utility policy (CK-UTL-*, Task 14 §5.6)
    "CK-UTL-001": "block",  # required key missing / extra key present
    "CK-UTL-002": "block",  # composite outside allowed_composite
    "CK-UTL-003": "block",  # frontier_score outside allowed_frontier_score
    "CK-UTL-004": "block",  # an axis weight outside [min, max]
    "CK-UTL-005": "block",  # axis weights do not sum to axis_weight_sum
    "CK-UTL-006": "warn",   # axis key outside the epoch's live axis set
    "CK-UTL-007": "block",  # depth_penalty_lambda / ucb_c out of range
    "CK-UTL-008": "block",  # body bytes do not hash to the registered id
}

# ── context-scope whitelists (v1; Task 12 owns extension) ──────────────────

#: The BFTS-facing ProposalSummaryView field whitelist (Task 03 §6.2 — the
#: ONLY proposal representation BFTS may consume). Roles absent from this
#: map are unchecked until Task 12 defines their views.
#:
#: Constitutional amendment 2026-07-15: added the ``paper_writer`` role
#: (plan 12 §5.4 / §5.7 visibility matrix row "Paper writer"). The paper
#: writer's deterministic view exposes EXACTLY verified context +
#: ``science_data`` + the claim registry and nothing else (no raw
#: transcripts, no governance internals).
#:
#: Constitutional amendment 2026-07-16 (plan ari_rqgm_paper/03 §5.2–§5.3):
#: the 2026-07-15 note that ``paper_writer`` is "deliberately NOT an
#: EVOLVABLE_ROLES member" is SUPERSEDED — the governed writer role now
#: lives in ari-core (not the subprocess), so it is promoted to a full
#: evolvable role (``_EVOLVABLE_ROLES`` above). Its whitelist is UNCHANGED
#: (unified, not forked): promotion adds capability-matrix + transition
#: presence, not context. The new ``paper_reviewer`` evaluator role gets a
#: fresh minimal four-field view — the archive draft under review + the same
#: Layer-0 verified evidence the writer saw + the metrics backing the claims
#: + the anchor/reference-case projection (its content is owned by plan
#: ari_rqgm_paper/04). Adding these rows changes ``CONSTITUTION_HASH``; the
#: pin in ``tests/test_rqgm_kernel.py`` was re-pinned for this amendment.
CONTEXT_VIEW_WHITELISTS: dict[str, frozenset[str]] = {
    "generator": frozenset({
        "proposal_record_id",
        "title",
        "short_description",
        "hypothesis",
        "experiment_plan",
        "success_metric",
        "novelty_risks",
        "expected_artifacts",
        "dissent_summary",
        "scores",
    }),
    "paper_writer": frozenset({
        "verified_context",
        "science_data",
        "claim_registry",
    }),
    "paper_reviewer": frozenset({
        "draft_manuscript",
        "verified_context",
        "science_data",
        "reference_context",
    }),
}

# ── legal utility policies (plan 14 §5.6) ──────────────────────────────────

#: The closed value spaces a governed utility policy must live in. Mirrors
#: the typed config Literals (``ari.config.BFTSConfig.frontier_score``,
#: ``ari.config.EvaluatorConfig.composite``) — the kernel does not INVENT the
#: vocabulary, it PINS it, so an adopted candidate can never name a composite
#: the evaluator cannot compute.
#:
#: Legality is frozen CODE, never config (see this module's docstring): a
#: tunable weight bound is a tunable constitution, and the checkpoint dir is
#: writable by any skill. These bounds are inside ``constitution_hash``, so
#: editing one is an explicit reviewed diff plus a re-pin — the same
#: treatment the transition table gets.
#:
#: **Why bounds at all.** An unbounded re-weighting is how a governed score
#: gets laundered into an ungoverned one: ``axis_weights = {novelty: 1.0}``
#: with everything else at 0 is formally a policy and substantively the
#: DELETION of ``measurement_validity`` and ``reproducibility`` from the
#: method. The floor/ceiling makes the axis set irreducible: a boundary may
#: re-prioritise the axes, never abolish one.
UTILITY_POLICY_RULES: dict = {
    "allowed_composite": ("arithmetic_mean", "geometric_mean",
                          "harmonic_mean", "weighted_min"),
    "allowed_frontier_score": ("depth_penalized", "scientific_only",
                               "scientific_plus_diversity", "ucb_like"),
    "axis_weight_min": 0.05,          # no axis may be zeroed out
    "axis_weight_max": 0.60,          # no axis may dominate
    "axis_weight_sum": 1.0,           # normalised
    "depth_penalty_lambda_max": 0.50,
    "ucb_c_max": 2.0,
    "required_keys": ("composite", "axis_weights", "frontier_score",
                      "depth_penalty_lambda", "ucb_c"),
}


# ── constitution hash (plan 04 §5.7) ────────────────────────────────────────


def _canonical_rules_payload() -> dict:
    """Content-only serialization of every constitutional table (sorted,
    canonical JSON — same discipline as every other RQGM hash)."""
    table = {
        f"{frm}->{to}": {
            "rule_id": rule.rule_id,
            "trigger": rule.trigger,
            "guards": list(rule.guards),
            "boundary_only": rule.boundary_only,
        }
        for (frm, to), rule in transition_rules.TRANSITION_TABLE.items()
    }
    return {
        "constitution_version": CONSTITUTION_VERSION,
        "transition_table": table,
        "emergency_edge": sorted(
            f"{frm}->{to}" for frm, to in transition_rules.EMERGENCY_EDGE
        ),
        "role_rules": dict(ROLE_RULES),
        "accusation_record_types": list(ACCUSATION_RECORD_TYPES),
        "governance_record_types": list(GOVERNANCE_RECORD_TYPES),
        "envelope_fields": list(ENVELOPE_FIELDS),
        "registry_writer": REGISTRY_WRITER,
        "capability_matrix": {
            f"{role}|{tier}": sorted(f"{a}:{r}" for a, r in caps)
            for (role, tier), caps in CAPABILITY_MATRIX.items()
        },
        "severity": dict(SEVERITY),
        "context_view_whitelists": {
            role: sorted(fields)
            for role, fields in CONTEXT_VIEW_WHITELISTS.items()
        },
        # Task 14 §5.6: the legality bounds a governed utility policy must
        # satisfy are constitutional, so they ride the pin (tuples are
        # serialized as lists — canonical_json's JSON shape).
        "utility_policy_rules": {
            k: (list(v) if isinstance(v, tuple) else v)
            for k, v in sorted(UTILITY_POLICY_RULES.items())
        },
    }


def constitution_hash() -> str:
    """``hash12(canonical_json(<all rule tables>))`` — pins the constitution.

    Covers the imported Task 09 transition tables, so an edit to
    ``transition_rules.py`` changes this hash exactly as an edit to this
    module does (the table living outside ``kernel_rules.py`` does not
    escape the pin).
    """
    return hash12(canonical_json(_canonical_rules_payload()))


#: Computed once at import (pure function of the tables above).
CONSTITUTION_HASH: str = constitution_hash()
