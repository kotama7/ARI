"""RQGM Task 04 — ConstitutionalKernel (docs/plans/ari_rqgm/04 §9).

Covers: per-violation-code trigger/pass fixtures over all twelve entry
points, the T1-T19 transition table (|S|x|S| complement enumeration,
boundary-only mid-epoch blocking, emergency-quarantine mid-epoch pass,
kernel/engine table import identity), role separation, selective erasure
(incl. physical-deletion detection), the hash12 scheme cross-check against
``FilesystemPromptLoader.load_versioned``, audit-log integrity (seq
regression / prefix mutation / chain break / chain-absent auto posture),
determinism (double-invocation byte equality, sorted violations, the
no-LLM/network import grep), the hand-pinned ``constitution_hash``, the
enforcement adapters (blocked-transition carry-over + audit entry, blocked
frontier rebuild, MCP pre-flight ``{"error"}`` denial with untouched CoW
path, fail-open per-node hook, ``audit_only`` downgrade), and the
mode-gating regressions (simple_bfts constructor spy; ari_rqgm + VirSci
off).

No test calls a real LLM: the kernel is deterministic by construction (P2)
and every collaborator is a stub.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ari.config import ARIConfig, RQGMKernelConfig
from ari.rqgm import kernel_rules, transition_rules
from ari.rqgm.events import (
    TransitionEvent,
    canonical_json,
    finalize_event,
    payload_hash,
)
from ari.rqgm.kernel import (
    CapabilityGatedMCPClient,
    ConstitutionalKernel,
    per_node_warn_check,
    should_block,
)
from ari.rqgm.kernel_types import kernel_report_audit_payload
from ari.rqgm.registry import (
    ComponentEntry,
    ComponentRegistry,
    GovernedPromptEntry,
    GovernedPromptRegistry,
)
from ari.rqgm.transition_rules import (
    EMERGENCY_EDGE,
    EMERGENCY_RULE_ID,
    TRANSITION_TABLE,
    ComponentStatus,
)

# Hand-pinned (plan 04 §5.7/§9.8): any rule-table edit — including one to the
# imported transition_rules.py — must be an explicit reviewed diff + re-pin.
# Re-pinned for CK-ERA-006 (Task 10 §5.3 prompt_trace cross-check).
# Re-pinned 2026-07-14: constitutional amendment adding
# ``failure_summary_compressor`` to the capability matrix with the same
# minimal grants as ``replay_selector`` (the role was in
# events.EVOLVABLE_ROLES but missing from the matrix, so every capability
# was CK-ACC-001-blocked in every tier).
# Re-pinned 2026-07-15: constitutional amendment adding the ``paper_writer``
# context-scope whitelist (plan 12 §5.4/§5.7: verified_context + science_data
# + claim_registry). Context-scope role only — deliberately NOT in
# EVOLVABLE_ROLES / the capability matrix (the paper skill is a separate
# ungoverned subprocess package in v1).
# Re-pinned 2026-07-16: constitutional amendment for governed utility
# evolution (plan 14 §5.2/§5.6). THREE table edits ride this one re-pin:
#   1. ``policy_mutator`` joins the capability matrix (_EVOLVABLE_ROLES),
#      receiving the same minimal meta grants as ``prompt_mutator``;
#   2. ``("utility_policy", "institutional")`` gains ONE explicit row,
#      narrower than _INSTITUTIONAL_BASE — {read,append} × records only. A
#      policy is a document, not an actor: no invoke, no write, no activate;
#   3. ``UTILITY_POLICY_RULES`` (the closed value spaces + weight bounds a
#      legal utility policy must live in) enters _canonical_rules_payload,
#      so the bounds are frozen code inside the pin rather than tunable
#      config — a tunable weight bound would be a tunable constitution.
# Both roles were previously in NEITHER events.EVOLVABLE_ROLES nor
# FIXED_ROLES (a role limbo), while live code named them; adding a role to
# events.py without a matrix row is the already-committed
# failure_summary_compressor failure mode above.
# Re-pinned 2026-07-16: constitutional amendment (plan ari_rqgm_paper/03)
# PROMOTING ``paper_writer`` from a context-scope-only whitelist entry to a
# full EVOLVABLE role (capability-matrix institutional + meta grants +
# transition presence, unifying its existing whitelist unchanged) and ADDING
# the new evaluable ``paper_reviewer`` role (institutional + meta grants + a
# {draft_manuscript, verified_context, science_data, reference_context}
# context view). The 2026-07-15 "deliberately NOT EVOLVABLE" note above is
# SUPERSEDED — the governed writer/reviewer prompts now live in ari-core and
# DRIVE the ungoverned ari-skill-paper executor (the skill is the hands and is
# never governed cross-process). Two capability-matrix rows per role plus the
# paper_reviewer whitelist row move the hash; the founding paper prompt/
# component rows are paper-mode-gated and do NOT ride the constitution pin.
# Re-pinned 2026-07-16: constitutional amendment (plan ari_rqgm_paper/05 /
# 03 §5.9, wave 3c) adding TRANSITION_TABLE row T21 (``active -> shadow``),
# the paper-role SHADOW-STANDBY supersession edge. Paper-role co-evolution is
# prompt-level, so on a successor's T6 adoption the incumbent active prompt is
# demoted to a reinstatable ``shadow`` standby (kernel-guarded to the paper
# roles, PAPER_SUPERSESSION_ROLES; behavioral roles keep the sanction-only
# model, active -> shadow forbidden for them) — exactly ONE active per paper
# role. The new table row rides constitution_hash (transition_rules feeds
# _canonical_rules_payload); the paper_self_preference ADVERSARY founding
# rows are paper-mode-gated and do NOT (founding rows are not in the payload).
# Re-pinned 2026-07-28 (#78b): constitutional amendment adding
# ``governance_judge`` to ``kernel_rules._GOVERNANCE_ROLES`` so the impeachment
# judge is a registrable, sanctionable role (a CAPABILITY_MATRIX institutional
# row rides the hash). The auditor/evidence_clerk/governance_judge FOUNDING
# COMPONENT rows do NOT ride the hash (founding rows are not in the payload) —
# they change registry identity / epoch fingerprint instead, asserted elsewhere.
_EXPECTED_CONSTITUTION_HASH = "2edf93776904"

RTE = kernel_rules.REGISTRY_WRITER
_H = "a" * 12
_H2 = "b" * 12
_RETIRED = "d" * 12


# ── fixture builders ────────────────────────────────────────────────────────


def _envelope(record_type: str = "proposal_record", **over) -> dict:
    rec = {
        "record_id": "rec_000001",
        "record_type": record_type,
        "epoch_id": "epoch_000",
        "component_id": "generator_v1",
        "prompt_hash": _H,
        "role": "generator",
        "created_at": "2026-07-06T00:00:00Z",
        "source_refs": {},
        "status": "candidate",
    }
    rec.update(over)
    return rec


def _prompt_registry(*, active_hash: str = _H):
    # Self-consistent registered pair: prompt_sha256[:12] == prompt_hash.
    return GovernedPromptRegistry({
        "generator_prompt_v1": GovernedPromptEntry(
            prompt_id="generator_prompt_v1", role="generator",
            status="active", prompt_hash=active_hash,
            prompt_sha256=active_hash + "0" * 52,
        ),
    })


def _inconsistent_registry():
    # Registered pair disagrees by scheme: sha256[:12] != prompt_hash.
    return GovernedPromptRegistry({
        "generator_prompt_v1": GovernedPromptEntry(
            prompt_id="generator_prompt_v1", role="generator",
            status="active", prompt_hash=_H,
            prompt_sha256="f" * 64,
        ),
    })


def _component_registry(status: str = "active"):
    return ComponentRegistry({
        "generator_v1": ComponentEntry(
            component_id="generator_v1", role="generator",
            tier="institutional", status=status,
        ),
    })


def _transition(**over) -> dict:
    t = {
        "epoch_transition_id": "transition_000_to_001",
        "schema_version": 1,
        "from_epoch": "epoch_000",
        "to_epoch": "epoch_001",
        "status": "pending",
        "emergency": False,
        "produced_by": RTE,
        "adoptions": [],
        "sanctions": [],
        "retirements": [],
        "bans": [],
        "clean_room_requests": [],
    }
    t.update(over)
    return t


def _emergency_transition(**over) -> dict:
    t = _transition(
        emergency=True,
        sanctions=[{
            "component_id": "generator_v1", "from_status": "active",
            "to_status": "quarantine", "rule_id": EMERGENCY_RULE_ID,
        }],
        kernel_violation={"code": "CK-HSH-010", "subject_ref": "generator_v1"},
    )
    t.update(over)
    return t


def _epoch_state(active: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        epoch_id="epoch_000",
        active_prompt_hashes=dict(active if active is not None
                                  else {"generator": _H}),
    )


def _chained_log(payloads: list) -> list:
    entries, prev = [], ""
    for i, payload in enumerate(payloads):
        h = payload_hash(payload)
        entries.append({
            "schema_version": 1, "event_id": "evt_%06d" % i,
            "event_type": "kernel_report", "payload": payload,
            "event_hash": h, "prev_event_hash": prev,
            "ts": None, "ts_iso": "",
        })
        prev = h
    return entries


def _era_inputs(**over):
    """Selective-erasure default inputs: one clean frontier record."""
    records = {
        "prop_000001": {
            "record_id": "prop_000001", "prompt_hash": _H,
            "stale": False, "valid_for_frontier": True, "source_refs": {},
        },
    }
    inputs = {
        "frontier": ["prop_000001"],
        "records": records,
        "prompt_registry": frozenset({_RETIRED}),
        "known_record_ids": set(records),
    }
    inputs.update(over)
    return inputs


def _era(k, **over):
    inputs = _era_inputs(**over)
    return k.validate_selective_erasure(
        inputs["frontier"], inputs["records"], inputs["prompt_registry"],
        known_record_ids=inputs["known_record_ids"],
        prompt_trace=inputs.get("prompt_trace"),
    )


# ── §9.1 per-code fixtures: one trigger + one pass per violation code ──────
# Each entry: code -> (trigger(kernel) -> report, clean(kernel) -> report).

#: A LEGAL governed utility policy (plan 14 §5.6): the canonical five axes at
#: weights inside [0.05, 0.60] summing to 1.0, a composite and frontier_score
#: from the closed sets, knobs in range.
_LEGAL_POLICY = {
    "composite": "harmonic_mean",
    "axis_weights": {
        "clarity_of_contribution": 0.15,
        "comparative_rigor": 0.20,
        "measurement_validity": 0.30,
        "novelty": 0.20,
        "reproducibility": 0.15,
    },
    "frontier_score": "scientific_plus_diversity",
    "depth_penalty_lambda": 0.05,
    "ucb_c": 0.5,
}


def _utl_policy(**overrides) -> dict:
    out = dict(_LEGAL_POLICY)
    out["axis_weights"] = dict(_LEGAL_POLICY["axis_weights"])
    for k, v in overrides.items():
        if v is _DROP:
            out.pop(k, None)
        else:
            out[k] = v
    return out


_DROP = object()

_FIXTURES = {
    # ── Task 14 §5.6: the governed utility policy (CK-UTL-*) ──────────
    "CK-UTL-001": (
        # A required key missing is as illegal as an unknown key present:
        # the policy body's key set is closed.
        lambda k: k.validate_utility_policy(_utl_policy(ucb_c=_DROP)),
        lambda k: k.validate_utility_policy(_utl_policy()),
    ),
    "CK-UTL-002": (
        lambda k: k.validate_utility_policy(_utl_policy(composite="median")),
        lambda k: k.validate_utility_policy(_utl_policy(composite="weighted_min")),
    ),
    "CK-UTL-003": (
        lambda k: k.validate_utility_policy(
            _utl_policy(frontier_score="vibes")),
        lambda k: k.validate_utility_policy(
            _utl_policy(frontier_score="ucb_like")),
    ),
    "CK-UTL-004": (
        # THE axis-abolition candidate: {novelty: 1.0} is formally a policy
        # and substantively the deletion of measurement_validity and
        # reproducibility from the method. Blocked by the floor AND the
        # ceiling (plan 14 §5.6).
        lambda k: k.validate_utility_policy(
            _utl_policy(axis_weights={"novelty": 1.0})),
        lambda k: k.validate_utility_policy(_utl_policy()),
    ),
    "CK-UTL-005": (
        lambda k: k.validate_utility_policy(
            _utl_policy(axis_weights={"novelty": 0.5, "reproducibility": 0.2})),
        lambda k: k.validate_utility_policy(
            _utl_policy(axis_weights={"novelty": 0.5, "reproducibility": 0.5})),
    ),
    "CK-UTL-006": (
        # WARN, not block: under axis_mode dynamic the live axis set is not
        # the canonical five, and the evaluator silently drops unknown keys.
        lambda k: k.validate_utility_policy(
            _utl_policy(axis_weights={"novelty": 0.5, "retired_axis": 0.5}),
            live_axes=("novelty",)),
        lambda k: k.validate_utility_policy(
            _utl_policy(axis_weights={"novelty": 0.5, "reproducibility": 0.5}),
            live_axes=("novelty", "reproducibility")),
    ),
    "CK-UTL-007": (
        lambda k: k.validate_utility_policy(_utl_policy(ucb_c=99.0)),
        lambda k: k.validate_utility_policy(_utl_policy(ucb_c=2.0)),
    ),
    "CK-UTL-008": (
        # The body no longer hashes to its registered identity: in-place
        # mutation of a governed object.
        lambda k: k.validate_utility_policy(
            _utl_policy(), registered_hash="0" * 12),
        lambda k: k.validate_utility_policy(
            _utl_policy(), registered_hash=payload_hash(_LEGAL_POLICY)),
    ),
    "CK-SCH-G01": (
        lambda k: k.validate_record_schema(
            {kk: v for kk, v in _envelope("governance_report").items()
             if kk != "prompt_hash"}),
        lambda k: k.validate_record_schema(_envelope("governance_report")),
    ),
    "CK-SCH-N01": (
        lambda k: k.validate_record_schema(_envelope(record_id="")),
        lambda k: k.validate_record_schema(_envelope()),
    ),
    "CK-SCH-N02": (
        lambda k: k.validate_record_schema(
            _envelope(summary={"title": "x" * 201})),
        lambda k: k.validate_record_schema(
            _envelope(summary={"title": "ok"})),
    ),
    "CK-HSH-001": (
        lambda k: k.validate_hashes(_envelope(prompt_hash=_H2),
                                    {"generator": _H}),
        lambda k: k.validate_hashes(_envelope(), {"generator": _H}),
    ),
    "CK-HSH-002": (
        lambda k: k.validate_hashes(
            _envelope(artifact_hashes={"out.txt": "0" * 64}),
            {"generator": _H}, artifacts={"out.txt": "1" * 64}),
        lambda k: k.validate_hashes(
            _envelope(artifact_hashes={"out.txt": "0" * 64}),
            {"generator": _H}, artifacts={"out.txt": "0" * 64}),
    ),
    "CK-HSH-003": (
        lambda k: k.validate_hashes(
            _envelope(artifact_hashes={"gone.txt": "0" * 64}),
            {"generator": _H}, artifacts={}),
        lambda k: k.validate_hashes(
            _envelope(artifact_hashes={"out.txt": "0" * 64}),
            {"generator": _H}, artifacts={"out.txt": "0" * 64}),
    ),
    "CK-HSH-010": (
        lambda k: k.validate_hashes(_envelope(prompt_hash=_H),
                                    _inconsistent_registry()),
        lambda k: k.validate_hashes(_envelope(prompt_hash=_H),
                                    _prompt_registry()),
    ),
    "CK-ACC-001": (
        lambda k: k.validate_capability(("reviewer", "institutional"),
                                        "read", "audit_log"),
        lambda k: k.validate_capability(("reviewer", "institutional"),
                                        "read", "records"),
    ),
    "CK-ACC-002": (
        lambda k: k.validate_capability(("reviewer", "institutional"),
                                        "read", "retired_prompt_text"),
        lambda k: k.validate_capability(("reviewer", "institutional"),
                                        "read", "active_prompt_text"),
    ),
    "CK-EPO-001": (
        lambda k: k.validate_epoch_invariance(
            _epoch_state(), [_envelope(prompt_hash=_H2)]),
        lambda k: k.validate_epoch_invariance(
            _epoch_state(), [_envelope(prompt_hash=_H)]),
    ),
    "CK-EPO-002": (
        lambda k: k.validate_epoch_invariance(
            _epoch_state(),
            [{"event_type": "component_status_change",
              "payload": {"component_id": "generator_v1"}}]),
        lambda k: k.validate_epoch_invariance(
            _epoch_state(),
            [{"event_type": "emergency_quarantine",
              "payload": {"component_id": "generator_v1"}}]),
    ),
    "CK-REG-001": (
        lambda k: k.validate_transition(_transition(adoptions=[
            {"component_id": "generator_v2", "from_status": "candidate",
             "to_status": "active"}]), None, None),
        lambda k: k.validate_transition(_transition(adoptions=[
            {"component_id": "generator_v2", "from_status": "shadow",
             "to_status": "probationary_active", "rule_id": "T6"}]),
            None, None),
    ),
    "CK-REG-002": (
        lambda k: k.validate_transition(_transition(sanctions=[
            {"component_id": "generator_v1", "from_status": "active",
             "to_status": "warning", "rule_id": "T9"}]),
            None, None, at_boundary=False),
        lambda k: k.validate_transition(_transition(sanctions=[
            {"component_id": "generator_v1", "from_status": "active",
             "to_status": "warning", "rule_id": "T9"}]), None, None),
    ),
    "CK-REG-003": (
        lambda k: k.validate_transition(_transition(adoptions=[
            {"component_id": "generator_v2", "from_status": "shadow",
             "to_status": "probationary_active", "rule_id": "T7"}]),
            None, None),
        lambda k: k.validate_transition(_transition(adoptions=[
            {"component_id": "generator_v2", "from_status": "shadow",
             "to_status": "probationary_active", "rule_id": "T6"}]),
            None, None),
    ),
    "CK-REG-004": (
        lambda k: k.validate_transition(_transition(produced_by="judge_v1"),
                                        None, None),
        lambda k: k.validate_transition(_transition(), None, None),
    ),
    "CK-REG-005": (
        lambda k: k.validate_transition(_transition(retirements=[
            {"component_id": "reviewer_v3", "from_status": "quarantine",
             "to_status": "retired", "rule_id": "T17"}]), None, None),
        lambda k: k.validate_transition(_transition(
            retirements=[{
                "component_id": "reviewer_v3", "from_status": "quarantine",
                "to_status": "retired", "rule_id": "T17",
                "retirement_event_id": "retire_00042",
                "evidence_refs": ["impeach_00007"]}],
            clean_room_requests=[{
                "request_id": "cleanroom_req_00042",
                "target_role": "reviewer",
                "retirement_event_id": "retire_00042"}],
        ), None, None),
    ),
    "CK-REG-006": (
        lambda k: k.validate_transition(
            _emergency_transition(kernel_violation=None), None, None,
            at_boundary=False),
        lambda k: k.validate_transition(
            _emergency_transition(), None, None, at_boundary=False),
    ),
    "CK-REG-007": (
        lambda k: k.validate_transition(_transition(sanctions=[
            {"component_id": "generator_v1", "from_status": "warning",
             "to_status": "probation", "rule_id": "T13"}]),
            _component_registry("active"), None),
        lambda k: k.validate_transition(_transition(sanctions=[
            {"component_id": "generator_v1", "from_status": "active",
             "to_status": "warning", "rule_id": "T9"}]),
            _component_registry("active"), None),
    ),
    "CK-REG-101": (
        lambda k: k.validate_authority_non_expansion(
            {"component_id": "reviewer_v5", "role": "reviewer",
             "tier": "institutional",
             "declared_capabilities": ["write:registry"]}, None),
        lambda k: k.validate_authority_non_expansion(
            {"component_id": "reviewer_v5", "role": "reviewer",
             "tier": "institutional",
             "declared_capabilities": ["read:records"]}, None),
    ),
    "CK-ROL-001": (
        lambda k: k.validate_role_separation(
            _envelope("impeachment_motion", role="reviewer",
                      accused_role="generator")),
        lambda k: k.validate_role_separation(
            _envelope("impeachment_motion", role="auditor",
                      accused_role="generator")),
    ),
    "CK-ROL-002": (
        lambda k: k.validate_role_separation(
            _envelope("evidence_bundle", role="auditor",
                      accused_role="generator")),
        lambda k: k.validate_role_separation(
            _envelope("evidence_bundle", role="evidence_clerk",
                      accused_role="generator")),
    ),
    "CK-ROL-003": (
        lambda k: k.validate_role_separation(
            _envelope("impeachment_motion", role="auditor",
                      accuser_role="reviewer", accused_role="reviewer")),
        lambda k: k.validate_role_separation(
            _envelope("impeachment_motion", role="auditor",
                      accuser_role="adversary", accused_role="reviewer")),
    ),
    "CK-ROL-901": (
        lambda k: k.validate_role_separation(
            _envelope("epoch_transition", produced_by="judge_v1")),
        lambda k: k.validate_role_separation(
            _envelope("epoch_transition", produced_by=RTE)),
    ),
    "CK-ERA-001": (
        lambda k: _era(k, records={"prop_000001": {
            "record_id": "prop_000001", "prompt_hash": _H, "stale": True,
            "valid_for_frontier": True, "source_refs": {}}}),
        lambda k: _era(k),
    ),
    "CK-ERA-002": (
        lambda k: _era(k, records={"prop_000001": {
            "record_id": "prop_000001", "prompt_hash": _H, "stale": False,
            "valid_for_frontier": False, "source_refs": {}}}),
        lambda k: _era(k),
    ),
    "CK-ERA-003": (
        lambda k: _era(k, records={"prop_000001": {
            "record_id": "prop_000001", "prompt_hash": _RETIRED,
            "stale": False, "valid_for_frontier": True, "source_refs": {}}}),
        lambda k: _era(k),
    ),
    "CK-ERA-004": (
        lambda k: _era(k, frontier=[], records={
            "prop_000001": {"record_id": "prop_000001",
                            "prompt_hash": _RETIRED, "stale": True,
                            "valid_for_frontier": False, "source_refs": {}},
            "prop_000002": {"record_id": "prop_000002", "prompt_hash": _H,
                            "stale": False, "valid_for_frontier": True,
                            "source_refs": {"parent": "prop_000001"}},
        }, known_record_ids=set()),
        lambda k: _era(k, frontier=[], records={
            "prop_000001": {"record_id": "prop_000001",
                            "prompt_hash": _RETIRED, "stale": True,
                            "valid_for_frontier": False, "source_refs": {}},
            "prop_000002": {"record_id": "prop_000002", "prompt_hash": _H,
                            "stale": True, "valid_for_frontier": False,
                            "source_refs": {"parent": "prop_000001"}},
        }, known_record_ids=set()),
    ),
    "CK-ERA-005": (
        lambda k: _era(k, known_record_ids={"prop_000001", "prop_gone"}),
        lambda k: _era(k),
    ),
    "CK-ERA-006": (
        # A prompt_trace line carries the retired hash but no record was
        # produced by that prompt (producer index incomplete, plan 10 §5.3).
        lambda k: _era(k, prompt_trace=[
            {"prompt_name": "reviewer", "template_hash": _RETIRED,
             "node_id": "node_001"}]),
        lambda k: _era(k, records={
            "prop_000001": {
                "record_id": "prop_000001", "prompt_hash": _H,
                "stale": False, "valid_for_frontier": True,
                "source_refs": {}},
            "rev_000001": {
                "record_id": "rev_000001", "prompt_hash": _RETIRED,
                "stale": True, "valid_for_frontier": False,
                "node_id": "node_001", "source_refs": {}},
        }, prompt_trace=[
            {"prompt_name": "reviewer", "template_hash": _RETIRED,
             "node_id": "node_001"}]),
    ),
    "CK-AUD-001": (
        lambda k: k.validate_audit_log_integrity([
            {"event_id": "evt_000000"}, {"event_id": "evt_000002"},
            {"event_id": "evt_000001"}]),
        lambda k: k.validate_audit_log_integrity([
            {"event_id": "evt_000000"}, {"event_id": "evt_000001"}]),
    ),
    "CK-AUD-002": (
        lambda k: k.validate_audit_log_integrity(
            _chained_log([{"a": 1}, {"a": 2}]),
            checkpointed=(2, "not-the-head")),
        lambda k: k.validate_audit_log_integrity(
            _chained_log([{"a": 1}, {"a": 2}]),
            checkpointed=(2, payload_hash({"a": 2}))),
    ),
    "CK-AUD-003": (
        lambda k: k.validate_audit_log_integrity(
            [dict(e, payload={"tampered": True}) if i == 1 else e
             for i, e in enumerate(_chained_log([{"a": 1}, {"a": 2}]))]),
        lambda k: k.validate_audit_log_integrity(
            _chained_log([{"a": 1}, {"a": 2}])),
    ),
    "CK-CLN-001": (
        lambda k: k.validate_clean_room_bundle(
            {"role_spec": "reviewer", "contains_retired_prompt_text": True},
            {}, None),
        lambda k: k.validate_clean_room_bundle(
            {"role_spec": "reviewer", "contains_retired_prompt_text": False},
            {"allowed_fields": ["role_spec",
                                "contains_retired_prompt_text"]}, None),
    ),
    "CK-CLN-002": (
        lambda k: k.validate_contamination_free(
            "the quick brown fox jumps over the lazy dog",
            {"retirement_event_id": "retire_00042",
             "forbidden_texts": [
                 "the quick brown fox jumps over the lazy dog"]}, []),
        lambda k: k.validate_contamination_free(
            "a completely different candidate prompt about ablation studies",
            {"retirement_event_id": "retire_00042",
             "forbidden_texts": [
                 "the quick brown fox jumps over the lazy dog"]}, []),
    ),
    "CK-CTX-001": (
        lambda k: k.validate_context_scope(
            "generator", {"title": "t", "raw_transcript": "leak"}),
        lambda k: k.validate_context_scope("generator", {"title": "t"}),
    ),
}


def test_every_severity_code_has_a_fixture():
    """The violation catalogue is fully exercised (plan 04 §9.1)."""
    assert set(_FIXTURES) == set(kernel_rules.SEVERITY)


@pytest.mark.parametrize("code", sorted(_FIXTURES))
def test_violation_code_trigger_and_pass(code):
    trigger, clean = _FIXTURES[code]
    k = ConstitutionalKernel()
    report = trigger(k)
    codes = [v.code for v in report.violations]
    assert code in codes, f"{code} not triggered (got {codes})"
    # Severity is constitutional, never caller-chosen.
    for v in report.violations:
        assert v.severity == kernel_rules.SEVERITY[v.code]
    clean_report = clean(k)
    assert code not in [v.code for v in clean_report.violations]


@pytest.mark.parametrize("code", sorted(_FIXTURES))
def test_double_invocation_byte_equality(code):
    """P2: identical inputs => byte-identical reports (plan 04 §9.7),
    across invocations AND kernel instances."""
    trigger, _ = _FIXTURES[code]
    first = canonical_json(trigger(ConstitutionalKernel()).to_dict())
    second = canonical_json(trigger(ConstitutionalKernel()).to_dict())
    assert first == second


def test_violations_sorted_deterministically():
    k = ConstitutionalKernel()
    report = _era(k, records={
        "prop_000002": {"record_id": "prop_000002", "prompt_hash": _RETIRED,
                        "stale": False, "valid_for_frontier": False,
                        "source_refs": {}},
        "prop_000001": {"record_id": "prop_000001", "prompt_hash": _RETIRED,
                        "stale": False, "valid_for_frontier": True,
                        "source_refs": {}},
    }, frontier=["prop_000002", "prop_000001"],
        known_record_ids={"prop_000001", "prop_000002"})
    keys = [(v.code, v.subject_ref, v.detail) for v in report.violations]
    assert keys == sorted(keys)
    assert len(keys) >= 3


# ── §9.2 transition table ───────────────────────────────────────────────────


_STATUSES = [s.value for s in ComponentStatus]


def test_full_matrix_exactly_the_21_rows_accepted():
    """|S|x|S| enumeration: CK-REG-001 fires iff the pair is not a row.

    Task 14 (plan 14 §5.5): T20 (active -> retired) is role-scoped to
    ``utility_policy`` (supersession); wave 3c (plan ari_rqgm_paper/05) adds
    T21 (active -> shadow) role-scoped to the paper roles. Each pair is driven
    under EVERY candidate role and accepted iff legal for at least one — so all
    21 rows are accepted and no non-row is.
    """
    k = ConstitutionalKernel()
    roles = ("utility_policy", "paper_reviewer")
    accepted = set()
    for frm in _STATUSES:
        for to in _STATUSES:
            for role in roles:
                t = _transition(sanctions=[{
                    "component_id": "c1", "role": role,
                    "from_status": frm, "to_status": to}])
                report = k.validate_transition(t, None, None)
                if not any(v.code == "CK-REG-001" for v in report.violations):
                    accepted.add((frm, to))
                    break
    assert accepted == set(TRANSITION_TABLE)
    assert len(TRANSITION_TABLE) == 21


def test_active_to_shadow_is_paper_role_only():
    """T21 shadow-standby supersession is legal ONLY for the paper roles;
    every other role gets CK-REG-001 for active -> shadow (their sanction-only
    replacement model is intact)."""
    k = ConstitutionalKernel()
    for role in ("generator", "reviewer", "judge", "utility_policy", ""):
        t = _transition(sanctions=[{
            "component_id": "c1", "role": role,
            "from_status": "active", "to_status": "shadow"}])
        report = k.validate_transition(t, None, None)
        assert any(v.code == "CK-REG-001" for v in report.violations), role
    # ... but a paper-role shadow-standby supersession is accepted.
    t = _transition(sanctions=[{
        "component_id": None, "prompt_id": "paper_reviewer_prompt_v1",
        "role": "paper_reviewer", "from_status": "active",
        "to_status": "shadow", "rule_id": "T21"}])
    report = k.validate_transition(t, None, None)
    assert not any(v.code == "CK-REG-001" for v in report.violations)


def test_active_to_retired_is_utility_policy_only():
    """T20 supersession is legal ONLY for the utility_policy criterion; every
    behavioral role still gets CK-REG-001 for active -> retired (retirement
    must stage via quarantine) — the sanction-only model is intact for them."""
    k = ConstitutionalKernel()
    for role in ("generator", "reviewer", "judge", ""):
        t = _transition(sanctions=[{
            "component_id": "c1", "role": role,
            "from_status": "active", "to_status": "retired"}])
        report = k.validate_transition(t, None, None)
        assert any(v.code == "CK-REG-001" for v in report.violations), role
    # ... but a utility_policy supersession is accepted.
    t = _transition(adoptions=[{
        "component_id": None, "prompt_id": "utility_policy_prompt_v1",
        "role": "utility_policy", "from_status": "active",
        "to_status": "retired", "rule_id": "T20"}])
    report = k.validate_transition(t, None, None)
    assert not any(v.code == "CK-REG-001" for v in report.violations)


def test_boundary_only_pairs_block_mid_epoch():
    k = ConstitutionalKernel()
    for (frm, to), rule in sorted(TRANSITION_TABLE.items()):
        if not rule.boundary_only:
            continue
        t = _transition(sanctions=[{
            "component_id": "c1", "from_status": frm, "to_status": to,
            "rule_id": rule.rule_id}])
        report = k.validate_transition(t, None, None, at_boundary=False)
        assert any(v.code == "CK-REG-002" for v in report.violations), \
            f"{frm}->{to} must block mid-epoch"
        assert report.blocking


def test_emergency_quarantine_passes_mid_epoch():
    k = ConstitutionalKernel()
    for frm, to in sorted(EMERGENCY_EDGE):
        t = _emergency_transition(sanctions=[{
            "component_id": "c1", "from_status": frm, "to_status": to,
            "rule_id": EMERGENCY_RULE_ID}])
        report = k.validate_transition(t, None, None, at_boundary=False)
        assert report.ok, (frm, to, [v.code for v in report.violations])


def test_kernel_imports_the_engine_table_object():
    """Single source of truth: no duplicated table in kernel_rules
    (plan 04 §9.2 import-identity)."""
    import ari.rqgm.kernel as kernel_mod

    assert kernel_mod.transition_rules is transition_rules
    assert kernel_mod.transition_rules.TRANSITION_TABLE is TRANSITION_TABLE
    assert not hasattr(kernel_rules, "TRANSITION_TABLE")
    assert not hasattr(kernel_rules, "EMERGENCY_EDGE")


def test_statuses_match_task02_vocabulary():
    from ari.rqgm.events import STATUS_VALUES

    assert tuple(s.value for s in ComponentStatus) == STATUS_VALUES


# ── §9.3 role separation extras ─────────────────────────────────────────────


def test_rte_authored_registry_write_passes_judge_blocked():
    k = ConstitutionalKernel()
    ok = k.validate_capability((RTE, "fixed"), "write", "registry")
    assert ok.ok
    denied = k.validate_capability(("judge", "institutional"),
                                   "write", "registry")
    assert [v.code for v in denied.violations] == ["CK-ROL-901"]
    assert denied.blocking


def test_meta_tier_cannot_activate_candidates():
    k = ConstitutionalKernel()
    report = k.validate_capability(("prompt_mutator", "meta"),
                                   "activate", "candidates")
    assert report.blocking


# ── §9.5 hashes: the hash12 scheme is the loader's, never a second one ─────


def test_prompt_hash_scheme_cross_checked_against_loader(tmp_path):
    from ari.prompts import FilesystemPromptLoader

    (tmp_path / "generator.md").write_text("You are a careful generator.\n",
                                           encoding="utf-8")
    text, h12 = FilesystemPromptLoader(base=tmp_path).load_versioned(
        "generator")
    assert h12 == hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    k = ConstitutionalKernel()
    assert k.validate_hashes(_envelope(prompt_hash=h12),
                             {"generator": h12}).ok
    bad = k.validate_hashes(_envelope(prompt_hash=h12),
                            {"generator": "f" * 12})
    assert [v.code for v in bad.violations] == ["CK-HSH-001"]


def test_artifact_path_recompute_full_sha256(tmp_path):
    payload = b"experiment output bytes"
    art = tmp_path / "out.txt"
    art.write_bytes(payload)
    good = hashlib.sha256(payload).hexdigest()
    k = ConstitutionalKernel()
    rec = _envelope(artifact_hashes={"out.txt": good})
    assert k.validate_hashes(rec, {"generator": _H},
                             artifacts={"out.txt": art}).ok
    rec_bad = _envelope(artifact_hashes={"out.txt": "0" * 64})
    report = k.validate_hashes(rec_bad, {"generator": _H},
                               artifacts={"out.txt": art})
    assert [v.code for v in report.violations] == ["CK-HSH-002"]


def test_source_refs_resolution_through_injected_reader():
    known = {"prop_000001"}
    k = ConstitutionalKernel(records_reader=known)
    ok = k.validate_hashes(
        _envelope(source_refs={"parent": "prop_000001"}), {"generator": _H})
    assert ok.ok
    bad = k.validate_hashes(
        _envelope(source_refs={"parent": "prop_gone"}), {"generator": _H})
    assert [v.code for v in bad.violations] == ["CK-HSH-003"]


# ── §9.6 audit-log integrity extras ─────────────────────────────────────────


def test_audit_chain_absent_auto_means_no_chain_violations():
    k = ConstitutionalKernel()
    entries = [{"event_id": "evt_%06d" % i, "payload": {"n": i},
                "event_hash": "", "prev_event_hash": ""} for i in range(3)]
    assert k.validate_audit_log_integrity(entries).ok


def test_broken_prev_hash_detected():
    k = ConstitutionalKernel()
    entries = _chained_log([{"a": 1}, {"a": 2}, {"a": 3}])
    entries[2]["prev_event_hash"] = "0" * 12
    report = k.validate_audit_log_integrity(entries)
    assert "CK-AUD-003" in [v.code for v in report.violations]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("event_type", "epoch_close"),
        ("event_id", "evt_000099"),
        ("transaction_id", "transaction_other"),
        ("payload", {"a": 99}),
        ("prev_event_hash", "0" * 64),
    ],
)
def test_schema_v2_digest_detects_every_replay_semantic_edit(
    field, replacement,
):
    prev = ""
    entries = []
    for seq in range(3):
        event = finalize_event(
            TransitionEvent(
                event_type="kernel_report",
                transaction_id="transaction_000",
                payload={"a": seq},
            ),
            event_seq=seq,
            prev_event_hash=prev,
        )
        entries.append(event.to_line_dict())
        prev = event.event_hash
    entries[1] = dict(entries[1], **{field: replacement})
    report = ConstitutionalKernel().validate_audit_log_integrity(entries)
    assert "CK-AUD-003" in [v.code for v in report.violations]


def test_schema_v2_digest_detects_event_reordering():
    prev = ""
    entries = []
    for seq in range(3):
        event = finalize_event(
            TransitionEvent(event_type="kernel_report", payload={"a": seq}),
            event_seq=seq,
            prev_event_hash=prev,
        )
        entries.append(event.to_line_dict())
        prev = event.event_hash
    entries[1], entries[2] = entries[2], entries[1]
    report = ConstitutionalKernel().validate_audit_log_integrity(entries)
    codes = [v.code for v in report.violations]
    assert "CK-AUD-001" in codes
    assert "CK-AUD-003" in codes


def test_audit_log_verifies_real_immutable_audit_log_file(tmp_path):
    from ari.rqgm.store import ImmutableAuditLog

    audit = ImmutableAuditLog(tmp_path)
    assert audit.append("kernel_report", {"n": 1})
    assert audit.append("kernel_report", {"n": 2})
    k = ConstitutionalKernel()
    assert k.validate_audit_log_integrity(ImmutableAuditLog.read(tmp_path)).ok


# ── §9.7 offline guarantee ──────────────────────────────────────────────────


def test_kernel_modules_have_no_llm_or_network_imports():
    """The kernel is NOT an LLM judge (plan 04 §5.7): grep-style guard over
    kernel*.py + transition_rules.py, mirroring test_prompt_provenance."""
    import ari.rqgm as rqgm_pkg

    pkg_dir = Path(rqgm_pkg.__file__).parent
    files = sorted(pkg_dir.glob("kernel*.py")) + [
        pkg_dir / "transition_rules.py"]
    assert len(files) == 4  # kernel, kernel_rules, kernel_types, transitions
    for path in files:
        text = path.read_text(encoding="utf-8")
        for name in ("litellm", "openai", "anthropic", "requests", "httpx",
                     "aiohttp", "socket"):
            assert f"import {name}" not in text, (path.name, name)
            assert f"from {name}" not in text, (path.name, name)


# ── §9.8 constitution hash pin ──────────────────────────────────────────────


def test_constitution_hash_pinned():
    """Any rule-table edit — kernel_rules OR the imported transition_rules —
    must be an explicit reviewed diff plus a re-pin here."""
    k = ConstitutionalKernel()
    assert k.constitution_hash == _EXPECTED_CONSTITUTION_HASH
    # Stable recompute (import-time constant == fresh computation).
    assert kernel_rules.constitution_hash() == _EXPECTED_CONSTITUTION_HASH
    assert kernel_rules.CONSTITUTION_HASH == _EXPECTED_CONSTITUTION_HASH


def test_evolvable_roles_all_have_capability_matrix_rows():
    """Vocabulary-parity guard (GAP-2 regression): every role in
    ``events.EVOLVABLE_ROLES`` must have institutional AND meta capability
    rows, otherwise the kernel CK-ACC-001-blocks the role's every action in
    every tier silently (the ``failure_summary_compressor`` drift)."""
    from ari.rqgm import events

    matrix_roles = {role for role, _tier in kernel_rules.CAPABILITY_MATRIX}
    missing = set(events.EVOLVABLE_ROLES) - matrix_roles
    assert not missing, f"EVOLVABLE_ROLES missing from the matrix: {missing}"
    for role in events.EVOLVABLE_ROLES:
        # Task 14 (plan 14 §5.2/§9): ``utility_policy`` is an ACTOR-less
        # role — a policy document, not a component that acts — so it holds
        # exactly ONE institutional row, deliberately narrower than
        # _INSTITUTIONAL_BASE, and no meta row. The invariant this test
        # actually protects (the failure_summary_compressor drift) is "at
        # least one row, so the role is not CK-ACC-001-blocked in every
        # tier"; the two-tier shape is the actor roles' shape.
        if role == events.UTILITY_POLICY_ROLE:
            assert (role, "institutional") in kernel_rules.CAPABILITY_MATRIX
            assert (role, "meta") not in kernel_rules.CAPABILITY_MATRIX
            continue
        assert (role, "institutional") in kernel_rules.CAPABILITY_MATRIX
        assert (role, "meta") in kernel_rules.CAPABILITY_MATRIX
    # A policy may not act: no invoke, no write, no activate — and narrower
    # than every actor's institutional row.
    utility_caps = kernel_rules.CAPABILITY_MATRIX[
        ("utility_policy", "institutional")
    ]
    assert utility_caps == frozenset(
        {("read", "records"), ("append", "records")}
    )
    assert not {a for a, _r in utility_caps} & {"invoke", "write", "activate"}
    assert utility_caps < kernel_rules.CAPABILITY_MATRIX[
        ("judge", "institutional")
    ]
    # The amendment mirrors replay_selector exactly — no broader authority.
    assert kernel_rules.CAPABILITY_MATRIX[
        ("failure_summary_compressor", "meta")
    ] == kernel_rules.CAPABILITY_MATRIX[("replay_selector", "meta")]
    assert kernel_rules.CAPABILITY_MATRIX[
        ("failure_summary_compressor", "institutional")
    ] == kernel_rules.CAPABILITY_MATRIX[("replay_selector", "institutional")]


def test_constitution_hash_covers_the_imported_transition_table(monkeypatch):
    original = kernel_rules.constitution_hash()
    edited = dict(transition_rules.TRANSITION_TABLE)
    edited[("banned", "active")] = transition_rules.TransitionRule(
        rule_id="T99", trigger="illegal_resurrection", guards=(),
        boundary_only=True)
    monkeypatch.setattr(transition_rules, "TRANSITION_TABLE", edited)
    assert kernel_rules.constitution_hash() != original


# ── §9.9 blocked transition => carry-over + audit entry (stub RTE) ─────────


class _StubRTE:
    """Task 09 stand-in: refuses to commit on a blocking kernel report."""

    def __init__(self, kernel, store, audit, enforcement="standard"):
        self.kernel = kernel
        self.store = store
        self.audit = audit
        self.enforcement = enforcement

    def apply(self, ckpt, state, cfg, transition, events):
        report = self.kernel.validate_transition(
            transition, state, state.epoch)
        self.audit.append("kernel_report", kernel_report_audit_payload(
            report, self.kernel.constitution_hash))
        if should_block(report, self.enforcement):
            return state  # carry-over: previous active set unchanged
        return self.store.run_boundary(
            ckpt, state, cfg, node_count=0, registry_events=list(events))


def _open_rqgm_state(tmp_path):
    from ari.rqgm.events import TransitionEvent
    from ari.rqgm.store import RqgmStateStore

    store = RqgmStateStore()
    store.apply_transition(tmp_path, "bootstrap", [
        TransitionEvent(event_type="component_registered", payload={
            "component_id": "generator_v1", "role": "generator",
            "tier": "institutional", "status": "active"}),
    ])
    state = store.open_epoch(tmp_path, ARIConfig(), node_count=0,
                             prior=store.replay(tmp_path))
    return store, state


def test_blocked_transition_carries_over_and_appends_audit(tmp_path):
    from ari.rqgm.store import ImmutableAuditLog

    store, state = _open_rqgm_state(tmp_path)
    kernel = ConstitutionalKernel()
    audit = ImmutableAuditLog(tmp_path)
    rte = _StubRTE(kernel, store, audit)
    before_epoch = state.epoch.epoch_id
    before_active = state.components.active_set()
    bad = _transition(adoptions=[{
        "component_id": "generator_v1", "from_status": "candidate",
        "to_status": "active"}])  # forbidden instant activation
    after = rte.apply(tmp_path, state, ARIConfig(), bad, [])
    assert after is state
    assert after.epoch.epoch_id == before_epoch
    assert after.components.active_set() == before_active
    lines = ImmutableAuditLog.read(tmp_path)
    assert len(lines) == 1 and lines[0]["event_type"] == "kernel_report"
    payload = lines[0]["payload"]
    assert payload["blocking"] is True
    assert payload["constitution_hash"] == _EXPECTED_CONSTITUTION_HASH
    assert any(v["code"] == "CK-REG-001" for v in payload["violations"])
    # A clean transition through the same stub commits the boundary.
    good = _transition()
    after2 = rte.apply(tmp_path, after, ARIConfig(), good, [])
    assert after2.epoch.epoch_seq == state.epoch.epoch_seq + 1


def test_audit_only_downgrade_commits_despite_blocking(tmp_path):
    """§9.13: enforcement=audit_only => blocking codes become logged
    warnings; the state change proceeds."""
    from ari.rqgm.store import ImmutableAuditLog

    store, state = _open_rqgm_state(tmp_path)
    rte = _StubRTE(ConstitutionalKernel(), store,
                   ImmutableAuditLog(tmp_path), enforcement="audit_only")
    bad = _transition(produced_by="judge_v1")
    after = rte.apply(tmp_path, state, ARIConfig(), bad, [])
    assert after.epoch.epoch_seq == state.epoch.epoch_seq + 1
    # The audit trail keeps the truthful severity.
    lines = ImmutableAuditLog.read(tmp_path)
    assert lines[0]["payload"]["blocking"] is True


# ── §9.10 blocked frontier rebuild => live frontier unchanged (stub) ───────


class _StubFrontierRepair:
    """Task 10 stand-in: commits the rebuilt frontier only if valid."""

    def __init__(self, kernel):
        self.kernel = kernel
        self.live = ["prop_000001"]

    def commit(self, rebuilt, records, retired):
        report = self.kernel.validate_selective_erasure(
            rebuilt, records, retired)
        if should_block(report, "standard"):
            return False
        self.live = list(rebuilt)
        return True


def test_blocked_frontier_rebuild_leaves_live_frontier_unchanged():
    repair = _StubFrontierRepair(ConstitutionalKernel())
    records = {
        "prop_000001": {"record_id": "prop_000001", "prompt_hash": _H,
                        "stale": False, "valid_for_frontier": True,
                        "source_refs": {}},
        "prop_000002": {"record_id": "prop_000002", "prompt_hash": _RETIRED,
                        "stale": False, "valid_for_frontier": True,
                        "source_refs": {}},
    }
    assert repair.commit(["prop_000001", "prop_000002"], records,
                         frozenset({_RETIRED})) is False
    assert repair.live == ["prop_000001"]
    records["prop_000002"]["stale"] = True
    records["prop_000002"]["valid_for_frontier"] = False
    assert repair.commit(["prop_000001"], records,
                         frozenset({_RETIRED})) is True


# ── §9.11 MCP pre-flight gate: exact envelope, CoW untouched ───────────────


class _MockMCP:
    _COW_TOOLS = frozenset({"add_memory"})

    def __init__(self):
        self.calls = []

    def list_tools(self, phase=None):
        return [{"name": "generate_ideas"}]

    def call_tool(self, tool_name, args, *, cow_node_id=None):
        self.calls.append((tool_name, dict(args), cow_node_id))
        return {"result": "ok"}

    def to_claude_mcp_config(self):
        return {"mcpServers": {}}

    def close_all(self):
        pass


def _policy(tool_name, args):
    if tool_name == "read_retired":
        return (("reviewer", "institutional"), "read", "retired_prompt_text")
    if tool_name == "generate_ideas":
        return (("generator", "institutional"), "invoke", "records")
    return None  # ungoverned tool


def test_mcp_preflight_denial_returns_exact_error_envelope():
    inner = _MockMCP()
    gated = CapabilityGatedMCPClient(inner, ConstitutionalKernel(),
                                     tool_policy=_policy)
    result = gated.call_tool("read_retired", {})
    assert set(result) == {"error"}  # the standard envelope, nothing else
    assert "CK-ACC-002" in result["error"]
    assert inner.calls == []  # never dispatched


def test_mcp_preflight_allows_and_preserves_cow_path():
    inner = _MockMCP()
    gated = CapabilityGatedMCPClient(inner, ConstitutionalKernel(),
                                     tool_policy=_policy)
    assert gated.call_tool("generate_ideas", {"n": 1},
                           cow_node_id="node_7") == {"result": "ok"}
    assert gated.call_tool("some_unmapped_tool", {}) == {"result": "ok"}
    assert inner.calls[0] == ("generate_ideas", {"n": 1}, "node_7")
    assert gated._COW_TOOLS is inner._COW_TOOLS
    assert gated.list_tools() == [{"name": "generate_ideas"}]
    assert gated.to_claude_mcp_config() == {"mcpServers": {}}


def test_mcp_preflight_audit_only_dispatches_denied_calls():
    inner = _MockMCP()
    gated = CapabilityGatedMCPClient(inner, ConstitutionalKernel(),
                                     tool_policy=_policy,
                                     enforcement="audit_only")
    assert gated.call_tool("read_retired", {}) == {"result": "ok"}
    assert len(inner.calls) == 1


# ── §9.12 per-node warn hook is fail-open ───────────────────────────────────


class _ExplodingKernel:
    constitution_hash = "boom"

    def validate_record_schema(self, record):
        raise RuntimeError("kernel bug")

    def validate_hashes(self, record, registry, artifacts=None):
        raise RuntimeError("kernel bug")


def test_per_node_warn_hook_swallows_kernel_exceptions(caplog):
    with caplog.at_level(logging.WARNING, logger="ari.rqgm.kernel"):
        result = per_node_warn_check(_ExplodingKernel(), [_envelope()])
    assert result is None  # swallowed, run continues
    assert any("fail-open" in r.getMessage() for r in caplog.records)


def test_per_node_warn_hook_logs_and_audits_findings(tmp_path, caplog):
    from ari.rqgm.store import ImmutableAuditLog

    audit = ImmutableAuditLog(tmp_path)
    with caplog.at_level(logging.WARNING, logger="ari.rqgm.kernel"):
        reports = per_node_warn_check(
            ConstitutionalKernel(), [_envelope(record_id="")],
            audit_log=audit)
    assert reports is not None
    assert any(r.violations for r in reports)
    lines = ImmutableAuditLog.read(tmp_path)
    assert lines and lines[0]["event_type"] == "kernel_report"


# ── §9.13 enforcement modes ─────────────────────────────────────────────────


def test_should_block_matrix():
    k = ConstitutionalKernel()
    blocking = k.validate_capability(("judge", "institutional"),
                                     "write", "registry")
    warn_only = k.validate_context_scope(
        "generator", {"title": "t", "leak": "x"})
    assert should_block(blocking, "standard") is True
    assert should_block(blocking, "audit_only") is False
    assert should_block(warn_only, "standard") is False
    assert warn_only.violations  # warned, flagged, never blocking


def test_authority_manifest_is_complete_and_matches_sparse_source():
    from ari.rqgm.authority_manifest import authority_manifest

    manifest = authority_manifest()
    expected = (
        len(kernel_rules.CAPABILITY_MATRIX)
        * len(kernel_rules.ACTIONS)
        * len(kernel_rules.RESOURCE_CLASSES)
    )
    assert manifest["default"] == "deny"
    assert len(manifest["decisions"]) == expected
    for row in manifest["decisions"]:
        grants = kernel_rules.CAPABILITY_MATRIX[(row["role"], row["tier"])]
        assert row["allowed"] is (
            (row["action"], row["resource"]) in grants
        )


# ── §9.14-15 regression / smoke ─────────────────────────────────────────────


def _stub_runtime_deps(monkeypatch):
    class _StubMCP:
        def __init__(self, skills, disabled_tools=None):
            self.skills = list(skills)

        def list_tools(self, phase=None):
            return []

    class _StubLLM:
        def __init__(self, cfg_llm, *a, **k):
            self.config = cfg_llm
            self.mcp_client = None

        def _model_name(self):
            return "stub-model"

    class _Stub:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr("ari.mcp.client.MCPClient", _StubMCP)
    monkeypatch.setattr("ari.llm.client.LLMClient", _StubLLM)
    monkeypatch.setattr("ari.memory.letta_client.LettaMemoryClient", _Stub)
    monkeypatch.setattr("ari.evaluator.LLMEvaluator", _Stub)
    monkeypatch.setattr("ari.agent.loop.AgentLoop", _Stub)


def test_simple_bfts_never_constructs_the_kernel(monkeypatch, tmp_path):
    """§9.14 constructor spy: a default run constructs no kernel and writes
    no constitution file."""
    import ari.rqgm.kernel as kernel_mod
    from ari.core import build_runtime

    constructed = []
    original_init = kernel_mod.ConstitutionalKernel.__init__

    def _spy(self, *a, **kw):
        constructed.append(True)
        return original_init(self, *a, **kw)

    monkeypatch.setattr(kernel_mod.ConstitutionalKernel, "__init__", _spy)
    _stub_runtime_deps(monkeypatch)
    _, _, _, bfts, _, _ = build_runtime(ARIConfig(), "goal",
                                        checkpoint_dir=tmp_path)
    assert constructed == []
    assert getattr(bfts, "rqgm", None) is None
    assert not (tmp_path / "constitution.yaml").exists()


def test_ari_rqgm_build_attaches_kernel_to_runtime(monkeypatch, tmp_path):
    from ari.core import build_runtime

    _stub_runtime_deps(monkeypatch)
    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    _, _, _, bfts, _, _ = build_runtime(cfg, "goal", checkpoint_dir=tmp_path)
    runtime = bfts.rqgm
    assert isinstance(runtime.kernel, ConstitutionalKernel)
    assert runtime.kernel.constitution_hash == _EXPECTED_CONSTITUTION_HASH
    assert runtime.kernel_enforcement == "standard"
    assert runtime.governance_suspended is False


def test_ari_rqgm_virsci_off_kernel_validates_router_records(tmp_path):
    """§9.15: with VirSci disabled the kernel operates identically on
    router-only ProposalRecords."""
    from ari.rqgm.proposals.records import (
        ProposalRecord,
        ProposalSummaryView,
    )
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    assert cfg.proposal_router.generators.virsci.enabled is False
    runtime = RQGMRuntime(cfg, tmp_path)
    record = ProposalRecord(
        record_id="prop_000001", generator="cheap", epoch_id="epoch_000",
        prompt_hash=_H,
        summary=ProposalSummaryView(proposal_record_id="prop_000001",
                                    title="router-only proposal"),
    )
    report = runtime.kernel.validate_record_schema(record)
    assert report.ok
    scope = runtime.kernel.validate_context_scope(
        "generator", record.summary.to_dict())
    assert scope.ok


def test_resume_integrity_pass_suspends_on_tampered_audit_log(tmp_path):
    """§5.6.6: blocking audit findings => governance-suspended carry-over,
    never a refusal to resume."""
    from ari.rqgm.runtime import RQGMRuntime
    from ari.rqgm.store import RQGM_AUDIT_FILENAME, ImmutableAuditLog

    cfg = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    audit = ImmutableAuditLog(tmp_path)
    audit.append("kernel_report", {"n": 1})
    audit.append("kernel_report", {"n": 2})
    # Tamper the first line's payload (chain break).
    path = tmp_path / RQGM_AUDIT_FILENAME
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["payload"] = {"n": 999}
    path.write_text("\n".join([json.dumps(first)] + lines[1:]) + "\n",
                    encoding="utf-8")
    runtime = RQGMRuntime(cfg, tmp_path)
    runtime.resume_integrity_check(tmp_path)
    assert runtime.governance_suspended is True
    # Clean log => no suspension.
    runtime2 = RQGMRuntime(cfg, tmp_path)
    path.unlink()
    ImmutableAuditLog(tmp_path).append("kernel_report", {"n": 1})
    runtime2.resume_integrity_check(tmp_path)
    assert runtime2.governance_suspended is False


# ── config parity (defaults.yaml <-> typed model, Task 02 pattern) ─────────


def test_kernel_defaults_yaml_matches_typed_config():
    defaults_path = (Path(__file__).parent.parent / "ari" / "configs"
                     / "defaults.yaml")
    data = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
    yaml_kernel = data["rqgm"]["kernel"]
    typed = RQGMKernelConfig()
    assert yaml_kernel["enforcement"] == typed.enforcement == "standard"
    assert yaml_kernel["audit_chain"] == typed.audit_chain == "auto"
    assert yaml_kernel["float_tolerance"] == typed.float_tolerance == 1e-9


def test_constitution_yaml_ships_and_copies_once(tmp_path):
    """Task 01's copy-once path activates now that Task 04 ships the file."""
    from ari.config.finder import package_config_root
    from ari.rqgm.state import copy_constitution_if_missing

    bundled = package_config_root() / "constitution.yaml"
    assert bundled.exists()
    data = yaml.safe_load(bundled.read_text(encoding="utf-8"))
    assert data["constitution_version"] == kernel_rules.CONSTITUTION_VERSION
    copy_constitution_if_missing(tmp_path)
    dst = tmp_path / "constitution.yaml"
    assert dst.exists()
    # Don't-clobber: a second copy never overwrites the checkpoint copy.
    dst.write_text("constitution_version: 999\n", encoding="utf-8")
    copy_constitution_if_missing(tmp_path)
    assert "999" in dst.read_text(encoding="utf-8")


def test_record_constitution_hash_is_additive(tmp_path):
    from ari.rqgm.state import record_constitution_hash

    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"run_id": "run_1"}), encoding="utf-8")
    record_constitution_hash(tmp_path)
    data = json.loads(meta.read_text(encoding="utf-8"))
    assert data["run_id"] == "run_1"
    assert data["constitution_hash"] == _EXPECTED_CONSTITUTION_HASH


# ── the constitutional choke point must be INSTALLED (dead-seam sweep) ───────
#
# `CapabilityGatedMCPClient` shipped complete and was never constructed outside
# tests: under `ari_rqgm` NO tool call was checked against CAPABILITY_MATRIX, so
# CK-ACC-001/002 and CK-ROL-901 could not be raised from the one place a running
# agent touches the world — which left `emergency_quarantine` (T16, the sole
# mid-epoch transition) with no production caller at all.

class _InnerMCPStub:
    _COW_TOOLS = ()

    def __init__(self):
        self.dispatched = []

    def call_tool(self, tool_name, args, cow_node_id=None):
        self.dispatched.append(tool_name)
        return {"result": "ok"}

    def list_tools(self, phase=None):
        return []


def _rqgm_with_epoch(tmp_path):
    from ari.config import ARIConfig
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig()
    cfg.ari.mode = "ari_rqgm"
    cfg.rqgm.enabled = True
    rt = RQGMRuntime(cfg, checkpoint_dir=tmp_path)
    rt.ensure_epoch(0, checkpoint_dir=tmp_path, run_id="gate-test")
    return cfg, rt


def test_build_runtime_installs_the_capability_gate(tmp_path):
    from ari.core import _install_capability_gate
    from ari.rqgm.kernel import CapabilityGatedMCPClient

    cfg, rt = _rqgm_with_epoch(tmp_path)
    gated = _install_capability_gate(cfg, _InnerMCPStub(), rt, tmp_path)
    assert isinstance(gated, CapabilityGatedMCPClient)


def test_gate_allows_ordinary_research_work(tmp_path):
    """Installing the gate must not change what a well-behaved run can do."""
    from ari.core import _install_capability_gate

    cfg, rt = _rqgm_with_epoch(tmp_path)
    inner = _InnerMCPStub()
    gated = _install_capability_gate(cfg, inner, rt, tmp_path)
    assert gated.call_tool("run_bash", {"cmd": "echo hi"}) == {"result": "ok"}
    assert gated.call_tool("survey", {}) == {"result": "ok"}   # ungoverned
    assert inner.dispatched == ["run_bash", "survey"]


def test_gate_denies_a_registry_write_and_fires_T16(tmp_path):
    """The whole point: a critical constitutional code raised at the choke
    point escalates to the emergency transition and COMMITS."""
    import json

    from ari.core import _install_capability_gate

    cfg, rt = _rqgm_with_epoch(tmp_path)
    gated = _install_capability_gate(cfg, _InnerMCPStub(), rt, tmp_path)
    # an ADVERSARY (a registered component) reaching for the registry
    gated._tool_policy = lambda n, a: (
        ("adversary", "institutional"), "write", "registry"
    )
    log_path = tmp_path / "rqgm_transitions.jsonl"
    before = sum(1 for _ in open(log_path))

    out = gated.call_tool("register_prompt", {})

    assert "error" in out and "denied" in out["error"]
    events = [json.loads(l) for l in open(log_path) if l.strip()][before:]
    emergency = [e for e in events
                 if e.get("event_type") == "emergency_quarantine"]
    assert emergency, f"T16 did not commit; new events={events}"
    payload = emergency[0].get("payload", {})
    assert payload.get("rule_id") == "T16"
    assert payload.get("component_id") == "adversary_reproducibility_v1"
    assert payload.get("to_status") == "quarantine"


def test_gate_quarantines_the_registered_generator_actor(tmp_path):
    """The research generator is a registered component, so a denied
    registry write is attributable and triggers the T16 emergency boundary."""
    import json

    from ari.core import _install_capability_gate

    cfg, rt = _rqgm_with_epoch(tmp_path)
    gated = _install_capability_gate(cfg, _InnerMCPStub(), rt, tmp_path)
    log_path = tmp_path / "rqgm_transitions.jsonl"
    before = sum(1 for _ in open(log_path))

    out = gated.call_tool("register_prompt", {})   # actor = generator

    assert "error" in out
    events = [json.loads(l) for l in open(log_path) if l.strip()][before:]
    emergency = [
        e for e in events
        if e.get("event_type") == "emergency_quarantine"
    ]
    assert emergency, f"T16 did not commit; new events={events}"
    payload = emergency[0].get("payload", {})
    assert payload.get("rule_id") == "T16"
    assert payload.get("component_id") == "generator_v1"
    assert payload.get("to_status") == "quarantine"


# ── the kernel validators must actually RUN (dead-seam sweep) ────────────────
#
# `per_node_warn_check` (schema + hash provenance over a node's records) and
# `validate_epoch_invariance` (frozen-active-set) had NO production caller, so
# CK-HSH-001/002/003/010 and CK-EPO-001/002 were never evaluated at all.

def test_epoch_invariance_check_is_clean_on_a_clean_epoch(tmp_path):
    cfg, rt = _rqgm_with_epoch(tmp_path)
    assert rt.check_epoch_invariance() == 0


def test_epoch_invariance_detects_a_record_outside_the_frozen_set(tmp_path):
    """CK-EPO-001. The validator takes TWO shapes — audit EVENTS carry
    `event_type`, RECORDS carry a top-level `record_id` — so feeding it the
    audit log alone would leave this half permanently unevaluated."""
    import json

    cfg, rt = _rqgm_with_epoch(tmp_path)
    (tmp_path / "rqgm_adversarial_cases.jsonl").write_text(json.dumps({
        "record_id": "utl_1", "record_type": "utility_record",
        "epoch_id": "epoch_000", "prompt_hash": "deadbeefdead",
        "role": "reviewer", "node_id": "node_1",
    }) + "\n")

    assert rt.check_epoch_invariance() == 1

    # and it is AUDITED, not just logged
    from ari.rqgm.store import ImmutableAuditLog
    reports = [
        e for e in ImmutableAuditLog.read(tmp_path)
        if e.get("event_type") == "kernel_report"
        and (e.get("payload") or {}).get("check") == "epoch_invariance"
    ]
    assert reports and "CK-EPO-001" in reports[-1]["payload"]["codes"]


def test_epoch_invariance_accepts_registered_non_incumbent_prompt():
    """CK-EPO-001 fix: the frozen set is the COMPLETE active-hash set, not the
    role->incumbent rollup. A record scored under a REGISTERED-but-not-incumbent
    prompt (the founding-proposal case: proposal_prior_art is a governed
    generator prompt that is not the 'generator' role incumbent) is clean, while
    a genuinely UNREGISTERED hash still fires — the check was strengthened by
    governing the prompt, NOT weakened."""
    from types import SimpleNamespace
    k = ConstitutionalKernel()
    epoch = SimpleNamespace(
        epoch_id="epoch_000",
        active_prompt_hashes={"generator": "af0aba2d5805"},         # role incumbent
        active_prompt_hash_set=["af0aba2d5805", "81d78be59631"],    # complete set
    )
    governed = {"record_id": "prop_0", "epoch_id": "epoch_000",
                "role": "generator", "prompt_hash": "81d78be59631"}
    codes = [v.code for v in k.validate_epoch_invariance(epoch, [governed]).violations]
    assert "CK-EPO-001" not in codes                      # governed non-incumbent -> clean

    ungoverned = dict(governed, prompt_hash="deadbeef0000")
    codes2 = [v.code for v in k.validate_epoch_invariance(epoch, [ungoverned]).violations]
    assert "CK-EPO-001" in codes2                         # truly ungoverned -> still fires

    # Backward-compat: a pre-field snapshot (no active_prompt_hash_set) falls
    # back to the role rollup, so the non-incumbent hash trips it (old behaviour).
    old = SimpleNamespace(epoch_id="epoch_000",
                          active_prompt_hashes={"generator": "af0aba2d5805"})
    codes3 = [v.code for v in k.validate_epoch_invariance(old, [governed]).violations]
    assert "CK-EPO-001" in codes3


def test_per_node_kernel_check_is_reachable(tmp_path):
    from types import SimpleNamespace as NS

    cfg, rt = _rqgm_with_epoch(tmp_path)
    assert rt.run_per_node_kernel_check(NS(id="node_1")) >= 0


def test_both_kernel_checks_are_wired_into_the_run_loop():
    from pathlib import Path

    import ari.rqgm.runtime as _rt

    loop = (Path(_rt.__file__).parents[1] / "cli" / "bfts_loop.py").read_text(
        encoding="utf-8"
    )
    assert "run_per_node_kernel_check" in loop
    assert "check_epoch_invariance" in loop


def test_per_node_check_reads_records_not_audit_events(tmp_path):
    """``per_node_warn_check`` feeds ``validate_record_schema`` +
    ``validate_hashes``, which require the ``rqgm_record_base`` envelope
    (record_id / component_id / prompt_hash / role / ...) at the TOP level.

    An audit-log entry is a different shape entirely ({event_id, event_type,
    payload, ts, ...}) and carries NONE of those, so feeding the audit log made
    CK-SCH-N01 fire on every node of every run — a standing false positive on
    the one code that flags a malformed governed record. Round MARKERS are
    idempotency bookkeeping, not governed records, and are excluded too.
    """
    import json as _json
    from types import SimpleNamespace

    from ari.rqgm.adversarial.pool import ROUND_MARKER_RECORD_TYPE
    from ari.rqgm.kernel import ConstitutionalKernel
    from ari.rqgm.runtime import RQGMRuntime

    # An audit entry (the WRONG input) and a round marker: neither is a record.
    audit_event = finalize_event(
        TransitionEvent(
            event_type="governance_level",
            payload={"node_id": "n1", "level": 3},
        ),
        event_seq=0,
        prev_event_hash="",
    )
    (tmp_path / "rqgm_audit.jsonl").write_text(
        _json.dumps(audit_event.to_line_dict()) + "\n"
    )
    (tmp_path / "rqgm_adversarial_cases.jsonl").write_text(_json.dumps({
        "record_type": ROUND_MARKER_RECORD_TYPE, "node_id": "n1",
        "epoch_id": "epoch_000", "kind": "exploration",
    }) + "\n")

    class _RT(RQGMRuntime):
        kernel = ConstitutionalKernel()

    rt = _RT.__new__(_RT)
    rt.checkpoint_dir = tmp_path
    rt._epoch_state = SimpleNamespace(prompts=None)
    node = SimpleNamespace(id="n1")

    assert rt.run_per_node_kernel_check(node) == 0, (
        "audit events / round markers must not be validated as governed records"
    )

    # A GENUINELY malformed governed record is still caught.
    with (tmp_path / "rqgm_adversarial_cases.jsonl").open("a") as fh:
        fh.write(_json.dumps({"record_type": "raw_attack", "node_id": "n1"}) + "\n")
    assert rt.run_per_node_kernel_check(node) > 0

    audit = [_json.loads(l) for l in (tmp_path / "rqgm_audit.jsonl").read_text().splitlines()]
    codes = {v["code"] for a in audit if a.get("event_type") == "kernel_report"
             for v in ((a.get("payload") or {}).get("violations") or [])}
    assert "CK-SCH-N01" in codes
