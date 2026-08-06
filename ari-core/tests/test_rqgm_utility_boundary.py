"""RQGM Task 14 — THE P1 TEST (docs/plans/ari_rqgm/14 §9 integration).

P1: the search is tree-structured **and at each epoch boundary the entire
score — the utility function itself — is rewritten**.

Before Task 14 that sentence was half-implemented. ``frontier_repair`` could
already destroy every score a retired utility policy produced
(``INVALIDATE_ROLES`` names ``utility_policy``: "no recompute can launder
that"), but NOTHING could retire a utility policy, because no registry entry
represented one, because the role was in neither half of ``events.ROLES``,
because the policy was a function of static config rather than of governed
state. ``utility_policy_hash`` was a permanent constant for a run.

**The primary P1 proof drives the NATURAL path.**
``test_p1_epoch_boundary_rewrites_the_entire_score`` boots a real ``ari_rqgm``
runtime at default config and drives real boundaries through
``ensure_epoch -> _run_epoch_boundary`` — it hand-builds NO transition. The
mint -> evaluate -> supersede -> retire spine runs on its own, and the test
asserts, VIA THE ENGINE, that ``utility_policy_hash`` changes across a
boundary, the ``epoch_fingerprint`` changes, the incumbent is retired with the
OLD hash, and every node scored under the old policy leaves the frontier
flagged ``utility_invalidated`` — with no recompute. A green suite over a
DEAD cause side is exactly what an earlier hand-built version of this test
failed to catch (it called ``engine.apply`` on a fabricated T6+T17
transition, proving only the downstream consequence). That machinery survives
here as an explicit downstream-consequence unit
(``test_downstream_consequence_of_a_hand_built_transition``), never as the P1
proof.

Adoption model (plan 14 §5.5, amended 2026-07-16): the utility policy is the
evaluation CRITERION and is adopted by SUPERSESSION — a validated,
shadow-passed successor displaces the healthy incumbent (T20, ``active ->
retired``), retiring it with the old hash so ``frontier_repair`` fires.
Behavioral roles keep the sanction-only replacement model, untouched.

No test calls a real LLM (P2).
"""

from __future__ import annotations

import json

import pytest

from ari.config import ARIConfig
from ari.orchestrator.node import Node, NodeStatus
from ari.rqgm.events import TransitionEvent, canonical_json
from ari.rqgm.frontier_repair import (
    STALE_KEY,
    STALE_REASON_KEY,
    UTILITY_INVALIDATED_REASON,
    UTILITY_POLICY_HASH_KEY,
    VALID_FOR_FRONTIER_KEY,
)
from ari.rqgm.prompt_loader import write_evolved_policy_body
from ari.rqgm.prompt_spec import UTILITY_POLICY_PROMPT_ID, utility_policy_spec
from ari.rqgm.runtime import RQGMRuntime
from ari.rqgm.store import ImmutableAuditLog, RqgmStateStore
from ari.rqgm.transition_engine import EpochTransition


@pytest.fixture(autouse=True)
def _no_env_run_pin(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


def _Node(nid, score=0.7, policy_hash=None):
    """A real, scored, frontier-eligible Node (the repair engine reads
    status/depth/children, so a stub would not exercise the real path)."""
    metrics = {"_scientific_score": score}
    if policy_hash:
        metrics[UTILITY_POLICY_HASH_KEY] = policy_hash
    return Node(
        id=nid, parent_id=None, depth=0, status=NodeStatus.SUCCESS,
        metrics=metrics, children=[],
    )


def _cfg(**rqgm) -> ARIConfig:
    return ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True, **rqgm})


def _boot(tmp_path, cfg=None):
    rt = RQGMRuntime(cfg or _cfg(), checkpoint_dir=tmp_path)
    epoch = rt.ensure_epoch(1, checkpoint_dir=tmp_path, run_id="p1")
    assert epoch is not None and epoch.epoch_id == "epoch_000"
    return rt, epoch


def _successor_policy(incumbent: dict) -> dict:
    """A legal successor: a different composite and frontier_score."""
    body = {k: v for k, v in incumbent.items() if k != "utility_policy_hash"}
    body["composite"] = "weighted_min"
    body["frontier_score"] = "ucb_like"
    return body


def _register_successor(tmp_path, store, body, *, status="shadow"):
    """Put a successor policy in the registry at *status*, body on disk."""
    spec = utility_policy_spec(
        body, prompt_id="utility_policy_prompt_v2", status=status,
        generation_mode="mutation", parent_prompt_id=UTILITY_POLICY_PROMPT_ID,
    )
    write_evolved_policy_body(tmp_path, spec.prompt_id, canonical_json(body))
    store.apply_transition(
        tmp_path, "transition_seed_successor",
        [TransitionEvent(event_type="prompt_registered", payload={
            "prompt_id": spec.prompt_id,
            "role": "utility_policy",
            "status": status,
            "prompt_hash": spec.prompt_hash,
            "prompt_sha256": spec.full_sha256,
            "source": {"kind": "policy", "path": spec.template_ref["path"]},
            "spec_ref": spec.prompt_id,
            "epoch_id": "epoch_000",
            "source_refs": [],
        })],
    )
    return spec


def _quarantine_incumbent(tmp_path, store):
    """T11 has already sanctioned the incumbent into quarantine — the
    from_status T17 (quarantine -> retired) requires."""
    store.apply_transition(
        tmp_path, "transition_seed_quarantine",
        [TransitionEvent(event_type="prompt_status_change", payload={
            "prompt_id": UTILITY_POLICY_PROMPT_ID,
            "from_status": "active",
            "to_status": "quarantine",
        })],
    )


def _rewrite_transition(old_hash, new_spec) -> EpochTransition:
    """A HAND-BUILT boundary transaction for the downstream-consequence unit
    ONLY (``test_downstream_consequence_of_a_hand_built_transition``) — NOT the
    natural path (§5.5's adoption model is supersession/T20, driven end to end
    by ``test_p1_epoch_boundary_rewrites_the_entire_score``). Here the incumbent
    was already sanctioned into quarantine, so T6 adopts the successor while
    T17 retires the incumbent from quarantine — the sanction path, exercised in
    isolation to prove the consequence side (frontier_repair) given a committed
    retirement. It does not (and must not be read to) prove the natural path
    produces a transition.
    """
    t = EpochTransition(
        epoch_transition_id="transition_000_to_001",
        from_epoch="epoch_000",
        to_epoch="epoch_001",
    )
    t.adoptions.append({
        "component_id": None,
        "prompt_id": new_spec.prompt_id,
        "prompt_hash": new_spec.prompt_hash,
        "role": "utility_policy",
        "from_status": "shadow",
        "to_status": "probationary_active",
        "rule_id": "T6",
        "evidence_refs": ["candidate_evaluation:utility_policy_prompt_v2"],
    })
    t.retirements.append({
        "component_id": None,
        "prompt_id": UTILITY_POLICY_PROMPT_ID,
        "prompt_hash": old_hash,
        "role": "utility_policy",
        "from_status": "quarantine",
        "to_status": "retired",
        "rule_id": "T17",
        "retirement_event_id": "retire_000001",
        "evidence_refs": ["governance_report:epoch_000"],
    })
    return t


# ── THE P1 TEST (natural path — NO hand-built transitions) ──────────────────


def _drive_until_rewrite(rt, tmp_path, nodes, *, max_boundaries=8):
    """Drive real boundaries through ``ensure_epoch`` (search_state supplied so
    ``frontier_repair`` runs inside the boundary window) until the frozen
    ``utility_policy_hash`` changes. Returns ``(rewrite_epoch, prior_hash)`` or
    ``(None, prior_hash)``. Hand-builds NOTHING: the mint -> evaluate ->
    supersede -> retire spine runs entirely on its own."""
    prior_hash = rt.current_epoch.utility_policy["utility_policy_hash"]
    for i in range(max_boundaries):
        frontier = [
            n for n in nodes
            if n.metrics.get(VALID_FOR_FRONTIER_KEY, True) is not False
        ]
        search_state = {
            "frontier": frontier, "pending": [], "all_nodes": nodes,
            "flush_tree": lambda: None,
        }
        ep = rt.ensure_epoch(
            (i + 1) * 11, checkpoint_dir=tmp_path, run_id="p1",
            search_state=search_state,
        )
        if ep.utility_policy["utility_policy_hash"] != prior_hash:
            return ep, prior_hash
    return None, prior_hash


def test_p1_epoch_boundary_rewrites_the_entire_score(tmp_path):
    """THE P1 PROOF, driven by the ENGINE on the natural path. A boundary
    rewrites the score, and every node scored under the old policy leaves the
    frontier. If this test fails, P1 is broken.

    NO hand-built transition: ``ensure_epoch`` fires ``_run_epoch_boundary``,
    which mints the candidate, evaluates it (§5.5 dry-run), supersedes the
    incumbent (T20) and retires it — the test only observes. Asserts, in the
    plan's order (§9):
      1. the epoch's utility_policy_hash CHANGED — the score was rewritten;
      2. the epoch_fingerprint changed — the rewrite is inside the epoch
         identity, not beside it;
      3. the committed transition carries a retirement with role ==
         utility_policy and prompt_hash == the retiring policy's hash;
      4. every node scored under the old policy is _valid_for_frontier False
         with _stale_reason == "utility_invalidated" — no recompute laundered
         it;
      5. the committed transition carries no `no_governance_report` note;
      6. MetricRecomputer was not invoked for any of them.

    MUTATION-CHECK: break any one spine link and this fails. Empirically
    verified against the four independent breakages — deleting the evaluation
    merge (blocker 1), the supersession branch (blocker 2), the T20 table row,
    or the body attach (blocker 4) — each of which leaves the hash constant
    and this assertion 1 red.
    """
    rt, epoch0 = _boot(tmp_path)
    old_hash = epoch0.utility_policy["utility_policy_hash"]
    old_fp = epoch0.epoch_fingerprint

    # Three nodes scored under the incumbent policy, each stamped with its
    # hash — the node's own provenance (plan 14 §5.8 delta 2), which is what
    # makes the rewrite TOTAL rather than a random half-rewrite over the
    # attacked-and-penalised subset that carries a UtilityRecord.
    nodes = [_Node(f"node_{i}", policy_hash=old_hash) for i in range(3)]

    # 6 (set up early): invalidate, never re-weight — no recompute may launder
    # an old score. Hook the live repair engine before any boundary fires.
    recompute_calls = []
    repair = rt.frontier_repair
    assert repair is not None
    _orig = repair._recompute_node
    repair._recompute_node = lambda *a, **k: (
        recompute_calls.append(a) or _orig(*a, **k)
    )

    rewrite_epoch, prior_hash = _drive_until_rewrite(rt, tmp_path, nodes)
    assert rewrite_epoch is not None, (
        "the GOVERNED path never rewrote the score — the cause half of P1 is "
        "dead (this is exactly the failure a green suite hid before)"
    )

    # 1. THE SCORE WAS REWRITTEN, by the engine, with no help from the test.
    new_hash = rewrite_epoch.utility_policy["utility_policy_hash"]
    assert new_hash != prior_hash
    # The adopted policy IS the epoch's frozen policy, in the same map the
    # kernel's CK-EPO-001 check reads.
    assert rewrite_epoch.active_prompt_hashes["utility_policy"] == new_hash

    # 2. The rewrite is inside the epoch identity — and ISOLATING: the
    #    fingerprint also folds in registry_version/epoch_seq, which advance
    #    every boundary, so ``!= old_fp`` alone would pass under a frozen hash.
    #    Prove the utility_policy hash is a LOAD-BEARING input by rewinding
    #    only that field on the rewrite epoch and showing the fingerprint moves.
    import dataclasses as _dc
    from ari.rqgm.state import epoch_fingerprint as _fp
    _rewound = _dc.replace(
        rewrite_epoch,
        utility_policy={**rewrite_epoch.utility_policy,
                        "utility_policy_hash": prior_hash},
        epoch_fingerprint="",
    )
    assert _fp(_rewound) != rewrite_epoch.epoch_fingerprint
    assert rewrite_epoch.epoch_fingerprint != old_fp

    # 3. The committed transition retired the incumbent with the OLD hash and
    #    role, and it was a T20 supersession (the amended §5.5 model).
    audit = ImmutableAuditLog.read(tmp_path)
    util_retirements = [
        line["payload"] for line in audit
        if line.get("event_type") == "retirement_event"
        and line["payload"].get("role") == "utility_policy"
    ]
    assert util_retirements, "no utility_policy retirement was emitted"
    assert any(p["prompt_hash"] == old_hash for p in util_retirements), (
        "the retirement must carry the OLD policy hash so frontier_repair "
        "matches the nodes scored under it"
    )
    committed = [
        line["payload"] for line in audit
        if line.get("event_type") == "epoch_transition"
        and line["payload"].get("status") == "committed"
        and any(
            r.get("rule_id") == "T20"
            for r in line["payload"].get("retirements", [])
        )
    ]
    assert committed, "no committed T20 supersession transition in the audit"
    # 5. The audit actually ran on that boundary (no fail-open shortcut).
    assert not any(
        "no_governance_report" in n for n in committed[-1].get("notes", [])
    ), committed[-1].get("notes")

    # 4. EVERY node scored under the old policy left the frontier, flagged
    #    utility_invalidated — reached through the node's own provenance.
    for node in nodes:
        assert node.metrics[VALID_FOR_FRONTIER_KEY] is False, node.id
        assert node.metrics[STALE_KEY] is True, node.id
        assert node.metrics[STALE_REASON_KEY] == UTILITY_INVALIDATED_REASON

    # 6. Invalidate, never re-weight.
    assert recompute_calls == []

    # The erasure event records the invalidation for the audit trail.
    erasures = [
        line for line in audit
        if line.get("event_type") == "selective_erasure"
    ]
    assert erasures
    payload = erasures[-1]["payload"]
    assert sorted(payload["invalidated_node_ids"]) == [
        "node_0", "node_1", "node_2"
    ]
    assert payload["recompute_node_ids"] == []
    assert old_hash in payload["retired_prompt_hashes"]


def test_the_proposer_keeps_offering_successors_across_boundaries(tmp_path):
    """Blocker 3: once supersession works, the active policy version advances
    each rewrite, so ``_active_utility_policy_identity`` returns the new
    version and the proposer naturally offers vN+1 — never the "already
    recorded" silence of the dead spine. Drive enough boundaries to see the
    lineage climb past v2."""
    rt, _epoch0 = _boot(tmp_path)
    from ari.rqgm.prompt_records import load_prompt_evolution_log

    seen_versions = set()
    for i in range(12):
        rt.ensure_epoch((i + 1) * 11, checkpoint_dir=tmp_path, run_id="p1")
        for r in load_prompt_evolution_log(tmp_path):
            if r.get("record_type") == "utility_policy_candidate":
                seen_versions.add(r.get("candidate_id"))
    # The dead spine minted exactly ONE candidate (v2) then went silent.
    assert "utility_policy_prompt_v2" in seen_versions
    assert "utility_policy_prompt_v3" in seen_versions, (
        "the proposer went silent after the first candidate — blocker 3"
    )
    # And each was actually adopted: the active hash kept changing.
    entry = rt.state.prompts.get("utility_policy_prompt_v1")
    assert entry is not None and entry.status == "retired"


def test_kernel_blocks_an_illegal_candidate_on_the_live_adoption_path(tmp_path):
    """Blocker 4: the kernel legality gate fires on the LIVE adoption path. An
    ILLEGAL utility_policy successor that has (contrived) passing evaluation
    scores is BLOCKED at T6 by ``validate_transition -> validate_utility_policy``
    once ``apply`` attaches its body — the incumbent keeps serving and the
    hash is unchanged. This isolates the kernel gate from the T1 legality
    evaluation (which is the FIRST line of defense): here the candidate slips
    past a fabricated evaluation, and the constitution still refuses it before
    it can score a node (§5.6 / §8.8)."""
    rt, epoch0 = _boot(tmp_path)
    store = RqgmStateStore()
    old_hash = epoch0.utility_policy["utility_policy_hash"]

    # An illegal successor: a composite outside the closed set. Registered at
    # shadow, body write-once on disk (as a real minted candidate would be).
    illegal_body = {
        k: v for k, v in epoch0.utility_policy.items()
        if k != "utility_policy_hash"
    }
    illegal_body["composite"] = "not_a_real_composite"
    spec = utility_policy_spec(
        illegal_body, prompt_id="utility_policy_prompt_v2", status="shadow",
        generation_mode="mutation", parent_prompt_id=UTILITY_POLICY_PROMPT_ID,
    )
    write_evolved_policy_body(
        tmp_path, spec.prompt_id, canonical_json(illegal_body)
    )
    store.apply_transition(
        tmp_path, "transition_seed_illegal",
        [TransitionEvent(event_type="prompt_registered", payload={
            "prompt_id": spec.prompt_id, "role": "utility_policy",
            "status": "shadow", "prompt_hash": spec.prompt_hash,
            "prompt_sha256": spec.full_sha256,
            "source": {"kind": "policy", "path": spec.template_ref["path"]},
            "spec_ref": spec.prompt_id, "epoch_id": "epoch_000",
            "source_refs": [],
        })],
    )
    state = store.load_state(tmp_path)
    engine = rt.transition_engine

    # A FABRICATED passing evaluation (the illegal candidate slips the T1
    # legality gate) drives the resolver to a T6 supersession adoption.
    passing_eval = {
        "prompt_id": spec.prompt_id, "role": "utility_policy",
        "verdict": "pass", "replay_score": 1.0, "anchor_score": None,
        "case_refs": ["a", "b", "c", "d", "e"], "shadow_samples": 5,
        "shadow_score": 1.0,
    }
    transition = engine.resolve_transition(
        epoch_state=state.epoch,
        governance_report={"epoch_id": "epoch_000"},
        candidate_evaluations=[passing_eval],
        components=state.components, prompts=state.prompts,
        status_history=engine.load_status_history(tmp_path),
    )
    # The resolver DID stage the adoption (the evaluation looked good)...
    assert any(
        a.get("prompt_id") == spec.prompt_id and a.get("rule_id") == "T6"
        for a in transition.adoptions
    ), "resolver should have staged the T6 adoption from the passing eval"

    applied = engine.apply(
        transition, checkpoint_dir=tmp_path, state=state, cfg=rt.cfg,
        node_count=3, run_id="p1",
    )
    # ...but the kernel BLOCKED it on the live path: the transition aborted.
    assert not applied.committed
    assert applied.transition.status == "aborted"
    codes = [
        v.get("code")
        for v in applied.transition.kernel_validation.get("violations", [])
    ]
    assert any(str(c).startswith("CK-UTL-") for c in codes), codes
    # The incumbent still governs; the score was NOT rewritten open.
    assert applied.state.epoch.utility_policy["utility_policy_hash"] == old_hash


def test_ck_utl_006_gates_on_the_live_axis_set_not_incumbent_keys(tmp_path):
    """[16] plan 14 §5.6: CK-UTL-006's live axis set is the epoch's ACTUAL
    scored axes (resolved per ``cfg.evaluator.axis_mode``), NOT the incumbent
    policy's static ``axis_weights`` keys — which are empty under the default
    ``axis_mode: dynamic`` and made the advisory dead on the live path
    (``live_axes=None`` => the check never ran in the very mode written for it).

    Driven through the real candidate-eval hook
    (``_utility_policy_candidate_evaluations``), spying on the kernel to capture
    the live axis set it was actually handed. The OLD code fed
    ``sorted(incumbent.axis_weights) or None`` == ``None`` here, so both the
    ``live is not None`` assertion and the CK-UTL-006 reachability assertion
    fail on it."""
    rt, epoch0 = _boot(tmp_path)          # default axis_mode == "dynamic"
    store = RqgmStateStore()
    # Legal on every BLOCK check (5 required keys, weights in-bounds, sum 1.0)
    # but carries one axis key outside the evaluator's set — the CK-UTL-006
    # (warn) case, mirroring test_rqgm_utility_evolution._LEGAL.
    stale_body = {
        "composite": "harmonic_mean",
        "axis_weights": {"novelty": 0.5, "custom_axis": 0.5},
        "frontier_score": "scientific_plus_diversity",
        "depth_penalty_lambda": 0.05,
        "ucb_c": 0.5,
    }
    spec = utility_policy_spec(
        stale_body, prompt_id="utility_policy_prompt_v2", status="candidate",
        generation_mode="mutation", parent_prompt_id=UTILITY_POLICY_PROMPT_ID,
    )
    write_evolved_policy_body(
        tmp_path, spec.prompt_id, canonical_json(stale_body)
    )
    store.apply_transition(
        tmp_path, "transition_seed_stale",
        [TransitionEvent(event_type="prompt_registered", payload={
            "prompt_id": spec.prompt_id, "role": "utility_policy",
            "status": "candidate", "prompt_hash": spec.prompt_hash,
            "prompt_sha256": spec.full_sha256,
            "source": {"kind": "policy", "path": spec.template_ref["path"]},
            "spec_ref": spec.prompt_id, "epoch_id": "epoch_000",
            "source_refs": [],
        })],
    )
    state = store.load_state(tmp_path)

    real = rt.kernel.validate_utility_policy
    captured: dict = {}

    def _spy(body, **kw):
        if (str(body.get("frontier_score")) == "scientific_plus_diversity"
                and "custom_axis" in (body.get("axis_weights") or {})):
            captured["live_axes"] = kw.get("live_axes")
        return real(body, **kw)

    rt.kernel.validate_utility_policy = _spy
    try:
        evals = rt._utility_policy_candidate_evaluations(state, tmp_path)
    finally:
        rt.kernel.validate_utility_policy = real

    # The candidate WAS evaluated on the live path.
    assert any(e.get("prompt_id") == spec.prompt_id for e in evals)
    # It was validated against the evaluator's LIVE axis set (contains the
    # generic axes), NOT the incumbent policy's empty static keys.
    live = captured.get("live_axes")
    assert live is not None, "live_axes came through as None (the dead-path bug)"
    assert "novelty" in live and "custom_axis" not in live
    # That live set makes CK-UTL-006 reachable: a stale key now WARNS (never blocks).
    report = real(stale_body, live_axes=live)
    codes = [v.code for v in report.violations]
    assert "CK-UTL-006" in codes
    assert all(v.severity == "warn" for v in report.violations)


# ── downstream-consequence unit (the OLD hand-built machinery, re-purposed) ──


def test_downstream_consequence_of_a_hand_built_transition(tmp_path):
    """NOT the P1 proof (see ``test_p1_epoch_boundary_rewrites_the_entire_score``
    for that). This unit exercises only the DOWNSTREAM consequence — GIVEN a
    committed retirement, ``frontier_repair`` invalidates old-policy nodes —
    by hand-building the transition and calling ``engine.apply`` directly. It
    proves the consequence side in isolation; it does NOT prove the natural
    path produces a transition (that is what a green suite once hid)."""
    rt, epoch0 = _boot(tmp_path)
    store = RqgmStateStore()
    old_hash = epoch0.utility_policy["utility_policy_hash"]

    nodes = [_Node(f"node_{i}", policy_hash=old_hash) for i in range(3)]
    frontier = list(nodes)

    successor_body = _successor_policy(epoch0.utility_policy)
    new_spec = _register_successor(tmp_path, store, successor_body)
    _quarantine_incumbent(tmp_path, store)
    assert new_spec.prompt_hash != old_hash

    state = store.load_state(tmp_path)
    engine = rt.transition_engine
    assert engine is not None
    transition = _rewrite_transition(old_hash, new_spec)
    applied = engine.apply(
        transition, checkpoint_dir=tmp_path, state=state, cfg=rt.cfg,
        node_count=len(nodes), run_id="p1",
    )
    assert applied.committed, applied.transition.notes
    epoch1 = applied.state.epoch

    new_hash = epoch1.utility_policy["utility_policy_hash"]
    assert new_hash != old_hash
    assert new_hash == new_spec.prompt_hash
    assert epoch1.active_prompt_hashes["utility_policy"] == new_hash
    assert epoch1.epoch_fingerprint != epoch0.epoch_fingerprint

    retirements = applied.transition.retirements
    assert [r["role"] for r in retirements] == ["utility_policy"]
    assert retirements[0]["prompt_hash"] == old_hash
    assert retirements[0]["rule_id"] == "T17"

    recomputer_calls = []
    repair = rt.frontier_repair
    assert repair is not None
    original = repair._recompute_node
    repair._recompute_node = lambda *a, **k: (
        recomputer_calls.append(a) or original(*a, **k)
    )
    result = repair.repair(
        transition=applied.transition,
        frontier=frontier,
        pending=[],
        all_nodes=nodes,
        checkpoint_dir=tmp_path,
        bfts_cfg=rt.cfg.bfts,
        epoch_id=epoch1.epoch_id,
    )
    assert result.status in ("applied", "conservative", "halted_expansion")

    for node in nodes:
        assert node.metrics[VALID_FOR_FRONTIER_KEY] is False, node.id
        assert node.metrics[STALE_KEY] is True, node.id
        assert node.metrics[STALE_REASON_KEY] == UTILITY_INVALIDATED_REASON
    assert frontier == [], "old-policy nodes must not survive in the frontier"
    assert recomputer_calls == []


def test_a_node_stamped_with_the_SURVIVING_policy_is_untouched(tmp_path):
    """The rewrite invalidates the OLD regime, not the frontier wholesale:
    a node scored under a policy that was not retired keeps its score."""
    rt, epoch0 = _boot(tmp_path)
    store = RqgmStateStore()
    old_hash = epoch0.utility_policy["utility_policy_hash"]

    stale_node = _Node("node_old", policy_hash=old_hash)
    fresh_node = _Node("node_new", policy_hash="ffffffffffff")
    unstamped = _Node("node_bare")            # simple_bfts-shaped: no stamp
    assert UTILITY_POLICY_HASH_KEY not in unstamped.metrics

    successor_body = _successor_policy(epoch0.utility_policy)
    new_spec = _register_successor(tmp_path, store, successor_body)
    _quarantine_incumbent(tmp_path, store)
    state = store.load_state(tmp_path)
    applied = rt.transition_engine.apply(
        _rewrite_transition(old_hash, new_spec),
        checkpoint_dir=tmp_path, state=state, cfg=rt.cfg,
        node_count=3, run_id="p1",
    )
    assert applied.committed

    nodes = [stale_node, fresh_node, unstamped]
    rt.frontier_repair.repair(
        transition=applied.transition,
        frontier=list(nodes),
        pending=[],
        all_nodes=nodes,
        checkpoint_dir=tmp_path,
        bfts_cfg=rt.cfg.bfts,
        epoch_id="epoch_001",
    )
    assert stale_node.metrics[VALID_FOR_FRONTIER_KEY] is False
    assert VALID_FOR_FRONTIER_KEY not in fresh_node.metrics
    assert VALID_FOR_FRONTIER_KEY not in unstamped.metrics


# ── the ablation rung (§8.2) ────────────────────────────────────────────────


def test_utility_evolution_disabled_reproduces_todays_behavior(tmp_path):
    """``rqgm.utility_evolution.enabled: false`` IS the pre-Task-14 system,
    reachable by one flag — the ablation rung plan 13 needs.

    The founding utility_policy entry still exists and still governs, so
    capture_utility_policy returns the founding policy (== the cfg policy) in
    every epoch and the hash is a constant again.
    """
    rt, epoch0 = _boot(
        tmp_path, _cfg(utility_evolution={"enabled": False})
    )
    for i in range(3):
        rt.ensure_epoch((i + 1) * 11, checkpoint_dir=tmp_path, run_id="p1")
    epoch_n = rt.current_epoch
    assert epoch_n.epoch_seq > epoch0.epoch_seq, "the run did cross boundaries"

    # The hash is constant across every epoch: nothing proposed a successor.
    assert epoch_n.utility_policy == epoch0.utility_policy
    assert epoch_n.utility_policy["utility_policy_hash"] == (
        epoch0.utility_policy["utility_policy_hash"]
    )
    # ... and it IS the cfg policy.
    from ari.rqgm.state import capture_utility_policy

    assert epoch0.utility_policy == capture_utility_policy(rt.cfg)

    # No candidate was minted, and the skip is audit-visible.
    from ari.rqgm.prompt_records import load_prompt_evolution_log

    assert not [
        r for r in load_prompt_evolution_log(tmp_path)
        if r.get("record_type") == "utility_policy_candidate"
    ]
    skipped = [
        line for line in ImmutableAuditLog.read(tmp_path)
        if line.get("event_type") == "utility_evolution_skipped"
    ]
    assert skipped
    assert skipped[0]["payload"]["reason"] == "utility_evolution.enabled=false"


def test_enabled_boundary_mints_a_policy_candidate(tmp_path):
    """The cause half, live: a real boundary proposes a successor score.
    Before Task 14 nothing in the system could do this."""
    rt, _epoch0 = _boot(tmp_path)
    rt.ensure_epoch(11, checkpoint_dir=tmp_path, run_id="p1")

    from ari.rqgm.prompt_records import load_prompt_evolution_log

    cands = [
        r for r in load_prompt_evolution_log(tmp_path)
        if r.get("record_type") == "utility_policy_candidate"
    ]
    assert len(cands) == 1
    cand = cands[0]
    assert cand["role"] == "policy_mutator"          # the AUTHOR
    assert cand["component_id"] == "policy_mutator_v1"
    assert cand["candidate_id"] == "utility_policy_prompt_v2"
    assert cand["mutation_kind"] in (
        "axis_reweighting", "composite_swap", "frontier_score_swap",
        "exploration_tuning",
    )
    # The candidate is registered at status=candidate through the SAME
    # boundary transaction, so the NEXT boundary can iterate it up the
    # T1->T6 spine.
    entry = rt.state.prompts.get("utility_policy_prompt_v2")
    assert entry is not None
    assert entry.status == "candidate"
    assert entry.role == "utility_policy"           # the TARGET
    assert entry.source["kind"] == "policy"
    # The body is on disk, write-once, and hashes to the registered identity.
    text, version_id = rt.state.prompts.resolve_text(
        "utility_policy_prompt_v2", checkpoint_dir=tmp_path
    )
    assert version_id == entry.prompt_hash
    assert json.loads(text) == cand["policy"]
    # A candidate does NOT yet govern: the incumbent still scores.
    assert rt.current_epoch.active_prompt_hashes["utility_policy"] != (
        entry.prompt_hash
    )


def test_min_epochs_between_rewrites_bounds_the_invalidation_cost(tmp_path):
    """R1: a rewrite invalidates every node scored under the old policy, so
    the boundary rate is bounded (plan 14 §6.3)."""
    rt, _ = _boot(tmp_path, _cfg(
        utility_evolution={"min_epochs_between_rewrites": 99}
    ))
    for i in range(3):
        rt.ensure_epoch((i + 1) * 11, checkpoint_dir=tmp_path, run_id="p1")

    from ari.rqgm.prompt_records import load_prompt_evolution_log

    cands = [
        r for r in load_prompt_evolution_log(tmp_path)
        if r.get("record_type") == "utility_policy_candidate"
    ]
    assert len(cands) == 1, "the gap must bar a second rewrite proposal"
    skipped = [
        line for line in ImmutableAuditLog.read(tmp_path)
        if line.get("event_type") == "utility_evolution_skipped"
        and line["payload"].get("reason") == "min_epochs_between_rewrites"
    ]
    assert skipped


# ── §5.9: a governed rewrite does not open an ungoverned channel ────────────


def test_ungoverned_weight_smuggling_is_still_blocked(tmp_path):
    """MetricSpecWeightCap stays verbatim (plan 14 §5.9). "Weights are
    capped" and "weights are rewritten at boundaries" are not a
    contradiction: the distinction is WHO and WHEN, not WHETHER. A node
    smuggling weights mid-epoch through make_metric_spec is still
    suppressed and audited."""
    from ari.rqgm.meta_evolution import MetricSpecWeightCap

    rt, _ = _boot(tmp_path)
    cap = MetricSpecWeightCap(
        audit_log=ImmutableAuditLog(tmp_path),
        epoch_state=lambda: rt.current_epoch,
    )

    class _Evaluator:
        metric_spec = type("S", (), {"axis_weights": {"novelty": 1.0}})()

    evaluator = _Evaluator()
    observation = cap({"axis_weights": {"novelty": 1.0}}, evaluator)
    assert observation["event"] == "metric_spec_weight_override_suppressed"
    assert observation["policy"] == "epoch_frozen_weights"
    # The smuggled weights are DROPPED, so scoring falls through to the
    # epoch-frozen (now GOVERNED) regime.
    assert evaluator.metric_spec.axis_weights is None
    audited = [
        line for line in ImmutableAuditLog.read(tmp_path)
        if line.get("event_type") == "metric_spec_weight_override_suppressed"
    ]
    assert audited


# ── P3: the proposer is governed, not an absolute ruler ────────────────────


def test_policy_mutator_is_a_registered_sanctionable_component(tmp_path):
    """The thing that proposes the score is itself governed: registered,
    sanctionable and evolvable, with no authority its meta siblings lack and
    no immunity they lack (plan 14 §5.4/§9)."""
    rt, epoch0 = _boot(tmp_path)
    entry = rt.state.components.get("policy_mutator_v1")
    assert entry is not None
    assert entry.status == "active"
    assert entry.role == "policy_mutator"
    assert entry.tier == "meta"
    assert epoch0.active_components["policy_mutator"] == "policy_mutator_v1"
    # Only candidate emission — never registry writes (META_HARD_DENIED).
    assert entry.capabilities.get("can_emit_candidates") is True
    assert not entry.capabilities.get("can_modify_registry")
    assert not entry.capabilities.get("can_activate_candidates")
    # Its OWN template is a governed, evolvable prompt like any other.
    prompt = rt.state.prompts.get("policy_mutator_prompt_v1")
    assert prompt is not None and prompt.status == "active"


def test_a_sanctioned_policy_mutator_is_not_rejected_as_unknown(tmp_path):
    """A governance recommendation against the proposer resolves into a real
    sanction rather than being silently dropped (P3)."""
    rt, _ = _boot(tmp_path)
    engine = rt.transition_engine
    # NOTE the plan (§5.4/§9) names this ``resolve_emergency_quarantine``;
    # the real Task 09 API is ``emergency_quarantine``.
    out = engine.emergency_quarantine(
        component_id="policy_mutator_v1",
        violation={"code": "CK-HSH-010", "subject_ref": "policy_mutator_v1"},
        epoch_state=rt.current_epoch,
        components=rt.state.components,
        checkpoint_dir=tmp_path,
    )
    assert out is not None, "the proposer must be a known, sanctionable actor"
    assert out.emergency is True
    sanctioned = [s["component_id"] for s in out.sanctions]
    assert sanctioned == ["policy_mutator_v1"]


# ── §8.1: simple_bfts is IDENTITY ──────────────────────────────────────────


def test_simple_bfts_writes_no_utility_policy_sentinel(monkeypatch, tmp_path):
    """The §9 regression: a default (simple_bfts) run has no rqgm_prompts/,
    no `_utility_policy_hash` on any node, and never imports the Task 14
    module. The stamp is attached by ``wrap_node_executor``, which
    ``ari.core`` calls only when ``bfts.rqgm`` exists — so under simple_bfts
    the wrapper never runs, the sentinel is absent, and tree.json is
    byte-identical to today (plan 14 §5.11/§8.1).
    """
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from ari.cli import _run_loop
    from ari.orchestrator.node import Node as RealNode

    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    sys.modules.pop("ari.rqgm.utility_evolution", None)

    cfg = ARIConfig(bfts={"max_total_nodes": 2, "max_parallel_nodes": 1,
                          "timeout_per_node": 60})
    agent = MagicMock()
    agent.hints = SimpleNamespace(provided_files=[], slurm_partition="",
                                  slurm_max_cpus=0)
    agent.memory = MagicMock()
    agent.memory.search.return_value = []

    def _run(node, exp_data):
        node.mark_running()
        node.metrics["_scientific_score"] = 0.6   # a SCORED node
        node.mark_success(eval_summary="ok")
        node.has_real_data = True
        return node

    agent.run.side_effect = _run
    bfts = MagicMock()
    bfts.should_prune.return_value = False

    def _expand(node, *args, **kwargs):
        child = RealNode(id="child_1", parent_id=node.id, depth=node.depth + 1)
        node.children.append(child.id)
        return [child]

    bfts.expand.side_effect = _expand
    bfts.select_best_to_expand.side_effect = (
        lambda frontier, goal, mem: frontier[0]
    )
    bfts.select_next_node.side_effect = lambda pending, goal, mem: pending[0]
    bfts.expansion_count.return_value = 0
    bfts.diversity_bonus.return_value = 0.0
    del bfts.rqgm                       # simple_bfts: no runtime attached
    root = RealNode(id="node_root", parent_id=None, depth=0)
    all_nodes = [root]
    _run_loop(
        cfg, bfts, agent, [root], all_nodes,
        {"goal": "g", "topic": "t", "file": "exp.md"},
        checkpoint_dir=tmp_path, run_id="simple-utility-guard",
    )
    for node in all_nodes:
        assert UTILITY_POLICY_HASH_KEY not in (node.metrics or {}), node.id
    assert not (tmp_path / "rqgm_prompts").exists()
    assert not (tmp_path / "rqgm_audit.jsonl").exists()
    assert "ari.rqgm.utility_evolution" not in sys.modules


# ── the utility_policy entry is constitutionally coherent ──────────────────


def test_utility_policy_entry_is_inside_the_frozen_active_set(tmp_path):
    """The forcing function behind §5.8 delta 1: once utility_policy is an
    active registry entry, epoch.active_prompt_hashes carries the epoch
    policy hash, so every UtilityRecord must carry THAT hash or the kernel
    raises CK-EPO-001 on it."""
    rt, epoch0 = _boot(tmp_path)
    frozen = set(epoch0.active_prompt_hashes.values())
    policy_hash = epoch0.utility_policy["utility_policy_hash"]
    assert policy_hash in frozen

    # A Task-14 UtilityRecord (carrying the EPOCH policy hash) is coherent.
    report = rt.kernel.validate_epoch_invariance(epoch0, [{
        "record_id": "utl_000001",
        "epoch_id": epoch0.epoch_id,
        "prompt_hash": policy_hash,
        "role": "utility_policy",
    }])
    assert not report.violations

    # A pre-14 record (carrying the PENALTY policy hash) is exactly what
    # CK-EPO-001 was always meant to catch.
    stale = rt.kernel.validate_epoch_invariance(epoch0, [{
        "record_id": "utl_000002",
        "epoch_id": epoch0.epoch_id,
        "prompt_hash": "0123456789ab",
        "role": "utility_policy",
    }])
    assert [v.code for v in stale.violations] == ["CK-EPO-001"]
