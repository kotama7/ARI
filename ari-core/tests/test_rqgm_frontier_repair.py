"""RQGM Task 10 — FrontierRepair and selective erasure (docs/plans/ari_rqgm/10 §9).

Covers: the pure ``trace_dependents`` closure (direct hits, transitive
propagation, materiality context pairs, cycle tolerance, idempotence, depth
overflow, deterministic ordering — §9.1), the pure ``rebuild_frontier``
(stale/invalid/sterile exclusion, Rule-A reinstatement, Rule B via
``len(children)``, determinism, depth cutoff — §9.2), the per-role
invalidate-vs-recompute policy (§9.3), the epoch-boundary smoke (§9.4), the
no-physical-deletion byte-compare (§9.5), kernel detection + the
conservative → drain-only failure ladder (§9.6), resume determinism (§9.7),
and the ``simple_bfts`` regression / META_FILES hygiene (§9.8).

No test calls a real LLM; all inputs are deterministic fixtures (P2).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ari.config import ARIConfig, RQGMFrontierRepairConfig
from ari.orchestrator.node import Node, NodeStatus
from ari.rqgm.erasure_state import (
    RQGM_ERASURE_STATE_FILENAME,
    ErasureStateView,
    RqgmErasureStateStore,
    fold_event,
)
from ari.rqgm.frontier_repair import (
    UTILITY_POLICY_HASH_KEY,
    FrontierRepairEngine,
    RepairResult,
    depends_materially,
    load_rqgm_records,
    rebuild_frontier,
    trace_dependents,
)
from ari.rqgm.kernel import ConstitutionalKernel
from ari.rqgm.store import ImmutableAuditLog
from ari.rqgm.transition_engine import EpochTransition

_H = "a" * 12          # retired hash
_H_LIVE = "b" * 12     # surviving hash


@pytest.fixture(autouse=True)
def _no_env_pin(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


# ── fixture builders ────────────────────────────────────────────────────────


def _rec(rid, rtype, *, prompt_hash=None, role="", node_id="",
         source_refs=(), **extra):
    out = {
        "record_id": rid,
        "record_type": rtype,
        "prompt_hash": prompt_hash,
        "role": role,
        "epoch_id": "epoch_001",
        "source_refs": (
            dict(source_refs) if isinstance(source_refs, dict)
            else list(source_refs)
        ),
    }
    if node_id:
        out["node_id"] = node_id
    out.update(extra)
    return out


def _node(nid, *, parent=None, depth=0, status=NodeStatus.SUCCESS,
          score=0.5, children=(), metrics=None):
    m = {"_scientific_score": score}
    m.update(metrics or {})
    return Node(
        id=nid, parent_id=parent, depth=depth, status=status,
        metrics=m, children=list(children),
    )


def _bfts_cfg(max_depth=5, max_exp=4):
    return SimpleNamespace(max_depth=max_depth,
                           max_expansions_per_node=max_exp)


def _transition(retirements):
    return EpochTransition(
        epoch_transition_id="transition_001_to_002",
        from_epoch="epoch_001",
        to_epoch="epoch_002",
        retirements=list(retirements),
    )


def _retirement(prompt_hash=_H, component_id="reviewer_v1", role="reviewer"):
    return {
        "component_id": component_id,
        "prompt_id": f"{role}_prompt_v1",
        "prompt_hash": prompt_hash,
        "role": role,
        "from_status": "quarantine",
        "to_status": "retired",
        "rule_id": "T17",
        "retirement_event_id": "retire_00001",
        "evidence_refs": [],
    }


def _engine(tmp_path, records, *, kernel="real", cfg=None,
            enforcement="standard"):
    if kernel == "real":
        kernel = ConstitutionalKernel()
    return FrontierRepairEngine(
        cfg=cfg if cfg is not None else RQGMFrontierRepairConfig(),
        kernel=kernel,
        audit_log=ImmutableAuditLog(tmp_path),
        record_loader=lambda ckpt: list(records),
        enforcement=enforcement,
    )


def _utility(rid, node_id, *, vat_ids=(), extra_refs=(), base=0.8,
             penalty=0.3, prompt_hash=None):
    return _rec(
        rid, "utility_record",
        prompt_hash=prompt_hash,
        role="utility_policy",
        node_id=node_id,
        source_refs=[node_id] + list(vat_ids) + list(extra_refs),
        base_score=base,
        penalty=penalty,
        final_score=max(0.0, base - penalty),
        input_refs={"result_ref": {}, "review_ids": [],
                    "validated_attack_ids": list(vat_ids)},
        frozen_policy={
            "penalty_cap": 0.5,
            "severity_weights": {"low": 0.05, "medium": 0.15, "high": 0.3,
                                 "critical": 0.5},
            "verdict_factors": {"valid": 1.0, "partially_valid": 0.5},
        },
        supersedes=None,
    )


# ── §9.1 trace_dependents (pure, no I/O) ────────────────────────────────────


def test_trace_direct_hits_by_retired_hash():
    records = [
        _rec("rev_001", "review_record", prompt_hash=_H, role="reviewer"),
        _rec("rev_002", "review_record", prompt_hash=_H_LIVE,
             role="reviewer"),
    ]
    closure = trace_dependents({_H}, records)
    assert closure.direct == frozenset({"rev_001"})
    assert closure.transitive == frozenset()


def test_trace_transitive_closure_through_source_refs():
    records = [
        _rec("atk_001", "raw_attack", prompt_hash=_H, role="adversary"),
        _rec("jdg_001", "judgment_record", role="judge",
             source_refs=["atk_001"]),
        _rec("vat_001", "validated_attack", role="judge",
             source_refs=["atk_001", "jdg_001"]),
        _rec("utl_001", "utility_record", role="utility_policy",
             source_refs=["vat_001"]),
    ]
    closure = trace_dependents({_H}, records)
    assert closure.direct == frozenset({"atk_001"})
    assert closure.transitive == frozenset({"jdg_001", "vat_001", "utl_001"})


def test_trace_context_pair_not_staled():
    # A proposal citing an ancestor's proposal is inspiration, not evidence
    # (P-B slot-scoping): the §5.3 materiality table exempts the pair.
    records = [
        _rec("prop_001", "proposal_record", prompt_hash=_H, role="generator"),
        _rec("prop_002", "proposal_record", role="generator",
             source_refs=["prop_001"]),
        _rec("utl_001", "utility_record", role="utility_policy",
             source_refs=["prop_001"]),
    ]
    closure = trace_dependents({_H}, records)
    assert "prop_002" not in closure.all_stale()
    # Unknown pair (utility citing proposal) stays load-bearing.
    assert "utl_001" in closure.transitive
    assert not depends_materially("proposal_record", "proposal_record")
    assert depends_materially("utility_record", "proposal_record")


def test_trace_cycle_tolerance_and_idempotence():
    records = [
        _rec("a", "review_record", prompt_hash=_H, role="reviewer",
             source_refs=["b"]),
        _rec("b", "judgment_record", role="judge", source_refs=["a"]),
    ]
    closure = trace_dependents({_H}, records)
    assert closure.all_stale() == frozenset({"a", "b"})
    # Idempotence: already-stale inputs are skipped, closure comes out empty.
    again = trace_dependents({_H}, records,
                             already_stale=frozenset({"a", "b"}))
    assert again.all_stale() == frozenset()


def test_trace_depth_overflow_conservative_invalidate():
    # Chain: direct -> c1 -> c2 where the c1->c2 edge is a context pair.
    # With the cap above the chain the exemption applies; with the cap at 1
    # the sweep past the cap ignores materiality (conservative).
    records = [
        _rec("p0", "proposal_record", prompt_hash=_H, role="generator",
             node_id="node_a"),
        _rec("p1", "proposal_record", role="generator", node_id="node_b",
             source_refs=["p0"]),
        _rec("u1", "utility_record", role="utility_policy", node_id="node_c",
             source_refs=["p0"]),
        _rec("p2", "proposal_record", role="generator", node_id="node_d",
             source_refs=["u1"]),
    ]
    deep = trace_dependents({_H}, records, max_depth=8)
    assert "p1" not in deep.all_stale()      # context pair honored
    # (proposal_record, utility_record) is NOT a context pair => material.
    assert "p2" in deep.all_stale()
    shallow = trace_dependents({_H}, records, max_depth=0)
    # Past the cap everything reachable is swept in, exemption or not.
    assert "p1" in shallow.all_stale()
    assert shallow.depth_exceeded >= frozenset({"p1"})
    # Conservative sweep => node invalidated, not recomputed, and the
    # diagnostic reason names the sweep, not a generator retirement.
    assert "node_b" in shallow.invalidated_node_ids
    assert shallow.invalidation_reasons["node_b"] == "trace_depth_exceeded"
    assert shallow.invalidation_reasons["node_a"] == "generator_retired"


def test_trace_deterministic_output():
    records = [
        _rec("r%02d" % i, "review_record", prompt_hash=_H, role="reviewer")
        for i in range(10)
    ] + [
        _rec("u%02d" % i, "utility_record", role="utility_policy",
             source_refs=["r%02d" % i])
        for i in range(10)
    ]
    a = trace_dependents({_H}, records)
    b = trace_dependents({_H}, list(reversed(records)))
    assert a.direct == b.direct
    assert a.transitive == b.transitive
    assert sorted(a.all_stale()) == sorted(b.all_stale())


# ── §9.2 rebuild_frontier (pure) ────────────────────────────────────────────


def test_rebuild_excludes_stale_invalid_and_sterile():
    nodes = [
        _node("n1"),
        _node("n2", metrics={"_stale": True}),
        _node("n3", metrics={"_valid_for_frontier": False}),
        _node("n4", metrics={"_sterile": True}),
        _node("n5", status=NodeStatus.PENDING),
    ]
    out = rebuild_frontier(nodes, ErasureStateView(), _bfts_cfg())
    assert [n.id for n in out] == ["n1"]


def test_rebuild_rule_a_reinstatement_of_parent():
    # Child beat the parent (Rule A retired it) but the child is now erased:
    # the parent re-enters the frontier; the erased child does not.
    parent = _node("n_parent", score=0.5, children=["n_child"])
    child = _node("n_child", parent="n_parent", depth=1, score=0.9,
                  metrics={"_stale": True, "_valid_for_frontier": False})
    out = rebuild_frontier([parent, child], ErasureStateView(), _bfts_cfg())
    assert [n.id for n in out] == ["n_parent"]
    # And with a VALID winning child the parent stays dominated.
    child_ok = _node("n_child", parent="n_parent", depth=1, score=0.9)
    out2 = rebuild_frontier([parent, child_ok], ErasureStateView(),
                            _bfts_cfg())
    assert [n.id for n in out2] == ["n_child"]


def test_rebuild_rule_b_via_len_children_and_depth_cutoff():
    full = _node("n_full", children=["c1", "c2"], score=0.1)
    deep = _node("n_deep", depth=5, score=0.1)
    ok = _node("n_ok", score=0.1)
    out = rebuild_frontier([full, deep, ok], None,
                           _bfts_cfg(max_depth=5, max_exp=2))
    assert [n.id for n in out] == ["n_ok"]


def test_rebuild_deterministic():
    nodes = [_node("n%02d" % i, score=float(i) / 10) for i in range(8)]
    cfg = _bfts_cfg()
    a = rebuild_frontier(nodes, ErasureStateView(), cfg)
    b = rebuild_frontier(list(reversed(nodes)), ErasureStateView(), cfg)
    assert [n.id for n in a] == [n.id for n in b]
    assert [n.id for n in a] == sorted(n.id for n in a)


def test_rebuild_honors_erasure_state_invalid_ids():
    nodes = [_node("n1"), _node("n2")]
    state = ErasureStateView(
        invalid_frontier_node_ids={"n2": "erase_00000"}
    )
    out = rebuild_frontier(nodes, state, _bfts_cfg())
    assert [n.id for n in out] == ["n1"]


# ── §9.3 per-role policy ────────────────────────────────────────────────────


def test_generator_retirement_invalidates_node_and_abandons_pending(tmp_path):
    records = [
        _rec("prop_001", "proposal_record", prompt_hash=_H, role="generator",
             source_refs={"node_id": "n_done", "parent_node_id": "n_root"}),
        _rec("prop_002", "proposal_record", prompt_hash=_H, role="generator",
             source_refs={"node_id": "n_pending", "parent_node_id": "n_done"}),
    ]
    done = _node("n_done", score=0.7)
    pending_child = _node("n_pending", parent="n_done", depth=1,
                          status=NodeStatus.PENDING)
    root = _node("n_root", score=0.4, children=["n_done"])
    frontier = [root, done]
    pending = [pending_child]
    all_nodes = [root, done, pending_child]
    engine = _engine(tmp_path, records)
    result = engine.repair(
        transition=_transition([_retirement(role="generator",
                                            component_id="generator_v1")]),
        frontier=frontier, pending=pending, all_nodes=all_nodes,
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert result.status == "applied"
    assert done.metrics["_stale"] is True
    assert done.metrics["_valid_for_frontier"] is False
    assert done.metrics["_stale_reason"] == "generator_retired"
    assert pending == []
    assert pending_child.status == NodeStatus.ABANDONED
    assert pending_child.metrics["_stale"] is True
    assert "n_pending" in result.erasure_event["abandoned_pending_node_ids"]
    assert "n_done" in result.erasure_event["invalidated_node_ids"]
    # Rule-A reinstatement: the invalidated child no longer dominates root.
    assert [n.id for n in frontier] == ["n_root"]


def test_judge_retirement_recomputes_penalty_out(tmp_path):
    # The VAT was adjudicated by the retired judge prompt: its penalty must
    # drop out by RECOMPUTATION under the original frozen weights.
    records = [
        _rec("vat_001", "validated_attack", prompt_hash=_H, role="judge",
             source_node_id="n1", verdict="valid", severity="high"),
        _utility("utl_001", "n1", vat_ids=["vat_001"], base=0.8,
                 penalty=0.3),
    ]
    node = _node("n1", score=0.5, metrics={"_pre_penalty_score": 0.8,
                                           "_validated_attack_penalty": 0.3})
    frontier = [node]
    engine = _engine(tmp_path, records)
    result = engine.repair(
        transition=_transition([_retirement(role="judge",
                                            component_id="judge_v1")]),
        frontier=frontier, pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert result.status == "applied"
    assert node.metrics["_scientific_score"] == pytest.approx(0.8)
    assert node.metrics["_validated_attack_penalty"] == pytest.approx(0.0)
    assert "n1" in result.rebuild_event["recomputed_utility_node_ids"]
    # The recomputed UtilityRecord supersedes the stale one and keeps the
    # original epoch's frozen weights.
    lines = ImmutableAuditLog.read(tmp_path)
    recs = [ln["payload"] for ln in lines
            if ln.get("event_type") == "utility_record"]
    assert len(recs) == 1
    new_rec = recs[0]
    assert new_rec["supersedes"] == "utl_001"
    assert new_rec["recomputed_in_epoch"] == "epoch_002"
    assert new_rec["frozen_policy"]["severity_weights"]["high"] == 0.3
    assert new_rec["penalty"] == pytest.approx(0.0)
    assert new_rec["input_refs"]["validated_attack_ids"] == []
    # Node survives in the frontier with the recomputed score.
    assert [n.id for n in frontier] == ["n1"]


def test_reviewer_retirement_recomputes_under_original_weights(tmp_path):
    # Utility cites the retired reviewer's review (load-bearing) AND one
    # surviving VAT: recompute keeps the surviving penalty only.
    records = [
        _rec("rev_001", "review_record", prompt_hash=_H, role="reviewer",
             node_id="n1"),
        _rec("vat_001", "validated_attack", prompt_hash=_H_LIVE,
             role="judge", source_node_id="n1", verdict="partially_valid",
             severity="medium"),
        _utility("utl_001", "n1", vat_ids=["vat_001"],
                 extra_refs=["rev_001"], base=0.9, penalty=0.075),
    ]
    node = _node("n1", score=0.825)
    engine = _engine(tmp_path, records)
    result = engine.repair(
        transition=_transition([_retirement(role="reviewer")]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert result.status == "applied"
    # medium (0.15) * partially_valid (0.5) = 0.075 survives.
    assert node.metrics["_validated_attack_penalty"] == pytest.approx(0.075)
    assert node.metrics["_scientific_score"] == pytest.approx(0.825)
    assert "n1" in result.rebuild_event["recomputed_utility_node_ids"]


def test_utility_policy_retirement_invalidates_no_rescaling(tmp_path):
    # UtilityRecords scored under the retired policy: invalidate (P-D).
    records = [
        _utility("utl_001", "n1", vat_ids=[], base=0.8, penalty=0.0,
                 prompt_hash=_H),
    ]
    node = _node("n1", score=0.8)
    engine = _engine(tmp_path, records)
    result = engine.repair(
        transition=_transition([_retirement(role="utility_policy",
                                            component_id="utility_v1")]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert result.status == "applied"
    assert node.metrics["_valid_for_frontier"] is False
    # Utility-policy retirement is NOT a generator retirement (§5.4 row 5).
    assert node.metrics["_stale_reason"] == "utility_invalidated"
    assert result.rebuild_event["recomputed_utility_node_ids"] == []
    assert result.rebuild_event["frontier_after"] == []


def test_utility_policy_retirement_rescores_stamped_node_under_new_policy(
    tmp_path,
):
    # #77: a node STAMPED with the retired policy AND carrying its per-axis raw
    # scores is RE-WEIGHTED under the new epoch criterion (composite +
    # axis_weights), not dropped. The existing validated attack penalty is
    # re-applied; the node is re-stamped and re-enters the frontier. A
    # utility_record with the retired hash is included so the (a) closure path
    # ALSO flags the node — proving #77 clears that policy-only invalidation.
    from ari.evaluator.llm_evaluator import _COMPOSITE_REGISTRY

    axes = {"novelty": 0.8, "rigor": 0.4}
    node = _node("n1", score=0.6, metrics={
        UTILITY_POLICY_HASH_KEY: _H,
        "_axis_scores": dict(axes),
        "_validated_attack_penalty": 0.1,
    })
    new_policy = {
        "composite": "arithmetic_mean",
        "axis_weights": {"novelty": 3.0, "rigor": 1.0},
        "utility_policy_hash": _H_LIVE,
    }
    records = [
        _utility("utl_001", "n1", base=0.6, penalty=0.1, prompt_hash=_H),
    ]
    engine = _engine(tmp_path, records)
    result = engine.repair(
        transition=_transition([_retirement(role="utility_policy",
                                            component_id="utility_v1")]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
        new_utility_policy=new_policy,
    )
    assert result.status == "applied"
    # Re-scored, not invalidated: the policy-only invalidation was cleared.
    assert node.metrics["_valid_for_frontier"] is True
    assert node.metrics.get("_stale_reason") is None
    assert node.metrics[UTILITY_POLICY_HASH_KEY] == _H_LIVE
    compose = _COMPOSITE_REGISTRY.resolve("arithmetic_mean")
    base = compose(axes, new_policy["axis_weights"], axis_names=tuple(axes))
    assert node.metrics["_pre_penalty_score"] == pytest.approx(base)
    assert node.metrics["_scientific_score"] == pytest.approx(
        max(0.0, base - 0.1)
    )
    assert result.erasure_event["policy_rescored_node_ids"] == ["n1"]
    assert "n1" not in result.erasure_event["invalidated_node_ids"]
    assert result.rebuild_event["frontier_after"] == ["n1"]


def test_utility_policy_retirement_rescores_on_composite_only_change(tmp_path):
    # #77 regression (found live in a 6-epoch codex e2e): the PolicyMutator's
    # composite_swap changes ONLY `composite`, leaving axis_weights={}. An empty
    # weight map must NOT fail-close to invalidation — the compose fns use equal
    # per-axis weights, so the node is still re-weighted under the new composite.
    from ari.evaluator.llm_evaluator import _COMPOSITE_REGISTRY

    axes = {"novelty": 0.8, "rigor": 0.4}
    node = _node("n1", score=0.6, metrics={
        UTILITY_POLICY_HASH_KEY: _H,
        "_axis_scores": dict(axes),
        "_validated_attack_penalty": 0.0,
    })
    # composite-only change: harmonic_mean -> weighted_min, axis_weights EMPTY.
    new_policy = {
        "composite": "weighted_min",
        "axis_weights": {},
        "utility_policy_hash": _H_LIVE,
    }
    engine = _engine(tmp_path, [
        _utility("utl_001", "n1", base=0.6, penalty=0.0, prompt_hash=_H),
    ])
    result = engine.repair(
        transition=_transition([_retirement(role="utility_policy",
                                            component_id="utility_v1")]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
        new_utility_policy=new_policy,
    )
    assert result.status == "applied"
    assert node.metrics["_valid_for_frontier"] is True  # re-scored, not dropped
    assert result.erasure_event["policy_rescored_node_ids"] == ["n1"]
    # weighted_min with equal weights over the stored axes == the min axis.
    compose = _COMPOSITE_REGISTRY.resolve("weighted_min")
    expected = compose(axes, {}, axis_names=tuple(axes))
    assert node.metrics["_scientific_score"] == pytest.approx(expected)
    assert node.metrics[UTILITY_POLICY_HASH_KEY] == _H_LIVE


def test_utility_policy_retirement_invalidates_when_no_axis_scores(tmp_path):
    # #77 fail-closed: a stamped node WITHOUT per-axis raw scores cannot be
    # re-weighted, so it still falls back to total invalidation — no
    # stale-criterion score ever survives.
    node = _node("n1", score=0.8, metrics={UTILITY_POLICY_HASH_KEY: _H})
    new_policy = {"composite": "arithmetic_mean",
                  "axis_weights": {"novelty": 1.0},
                  "utility_policy_hash": _H_LIVE}
    engine = _engine(tmp_path, [])
    result = engine.repair(
        transition=_transition([_retirement(role="utility_policy",
                                            component_id="utility_v1")]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
        new_utility_policy=new_policy,
    )
    assert result.status == "applied"
    assert node.metrics["_valid_for_frontier"] is False
    assert node.metrics["_stale_reason"] == "utility_invalidated"
    assert result.erasure_event["policy_rescored_node_ids"] == []
    assert "n1" in result.erasure_event["invalidated_node_ids"]


def test_recompute_utilities_false_invalidates_instead(tmp_path):
    records = [
        _rec("vat_001", "validated_attack", prompt_hash=_H, role="judge",
             source_node_id="n1", verdict="valid", severity="high"),
        _utility("utl_001", "n1", vat_ids=["vat_001"]),
    ]
    node = _node("n1", score=0.5)
    engine = _engine(
        tmp_path, records,
        cfg=RQGMFrontierRepairConfig(recompute_utilities=False),
    )
    result = engine.repair(
        transition=_transition([_retirement(role="judge")]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert result.status == "applied"
    assert node.metrics["_valid_for_frontier"] is False
    assert node.metrics["_stale_reason"] == "utility_invalidated"


# ── §9.4 epoch-boundary smoke ───────────────────────────────────────────────


def test_boundary_smoke_events_state_and_frontier(tmp_path):
    records = [
        _rec("rev_001", "review_record", prompt_hash=_H, role="reviewer",
             node_id="n1"),
    ]
    node = _node("n1", score=0.5)
    frontier = [node]
    engine = _engine(tmp_path, records)
    result = engine.repair(
        transition=_transition([_retirement()]),
        frontier=frontier, pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
        epoch_id="epoch_002",
    )
    assert isinstance(result, RepairResult)
    assert result.status == "applied"
    # Both events appended to the Task 02 audit log.
    lines = ImmutableAuditLog.read(tmp_path)
    types = [ln.get("event_type") for ln in lines]
    assert "selective_erasure" in types
    assert "frontier_rebuild" in types
    # State snapshot written and folds the event.
    state_path = tmp_path / RQGM_ERASURE_STATE_FILENAME
    assert state_path.exists()
    payload = json.loads(state_path.read_text())
    assert payload["schema_version"] == 1
    assert _H in payload["retired_prompt_hashes"]
    assert "rev_001" in payload["stale_record_ids"]
    assert payload["last_erasure_event_id"] == "erase_00000"
    assert payload["last_rebuild_event_id"] == "rebuild_00000"
    # Kernel validation passed; the un-invalidated node stays.
    assert result.rebuild_event["kernel_validation"] == "passed"
    # Events validate against the shipped schemas.
    jsonschema = pytest.importorskip("jsonschema")
    import ari.schemas as schemas

    jsonschema.validate(result.erasure_event,
                        schemas.load("selective_erasure_event.schema"))
    jsonschema.validate(result.rebuild_event,
                        schemas.load("frontier_rebuild_event.schema"))
    jsonschema.validate(payload, schemas.load("erasure_state.schema"))


def test_repair_noop_without_retirements(tmp_path):
    engine = _engine(tmp_path, [])
    result = engine.repair(
        transition=_transition([]), frontier=[], pending=[], all_nodes=[],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert result.status == "noop"
    assert result.erasure_event is None
    assert not (tmp_path / RQGM_ERASURE_STATE_FILENAME).exists()
    assert ImmutableAuditLog.read(tmp_path) == []


def test_repair_second_run_is_idempotent(tmp_path):
    records = [
        _rec("rev_001", "review_record", prompt_hash=_H, role="reviewer",
             node_id="n1"),
    ]
    node = _node("n1", score=0.5)
    engine = _engine(tmp_path, records)
    first = engine.repair(
        transition=_transition([_retirement()]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    second = engine.repair(
        transition=_transition([_retirement()]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert first.status == "applied" and second.status == "applied"
    # The already-stale record is not re-staled.
    assert second.erasure_event["direct_stale_record_ids"] == []


# ── §9.5 no physical deletion ───────────────────────────────────────────────


def test_no_physical_deletion_byte_compare(tmp_path):
    # Pre-existing stores: append-only JSONL truth + memory + prompt trace.
    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir()
    prop_line = json.dumps(
        _rec("prop_001", "proposal_record", prompt_hash=_H,
             role="generator",
             source_refs={"node_id": "n1", "parent_node_id": ""})
    ) + "\n"
    (proposals_dir / "proposal_records.jsonl").write_text(prop_line)
    (tmp_path / "rqgm_adversarial_cases.jsonl").write_text(
        json.dumps(_utility("utl_001", "n1", vat_ids=[])) + "\n"
    )
    (tmp_path / "prompt_trace.jsonl").write_text('{"prompt_name": "x"}\n')
    (tmp_path / "memory_store.jsonl").write_text('{"kind": "memory"}\n')
    # The paper anchor corpus (doc 04 §5.7 / §8.3): origin_epoch_id="anchor_static",
    # outside every prompt-hash closure, so a retirement must NEVER rewrite it
    # (invariant 13 / physical-erasure-free — the deletion-criteria byte-compare).
    (tmp_path / "paper_anchor_corpus.jsonl").write_text(
        json.dumps({"case_id": "anchor_001", "record_type": "PaperAnchorCase",
                    "origin_epoch_id": "anchor_static",
                    "ground_truth_label": "reject", "label_source": "human_curated",
                    "authorship": "human", "manuscript_sha256": "sha1"}) + "\n"
    )
    audit = ImmutableAuditLog(tmp_path)
    audit.append("governance_report", {"record_id": "gr_001",
                                       "record_type": "governance_report"})

    watched = [
        proposals_dir / "proposal_records.jsonl",
        tmp_path / "rqgm_adversarial_cases.jsonl",
        tmp_path / "prompt_trace.jsonl",
        tmp_path / "memory_store.jsonl",
        tmp_path / "paper_anchor_corpus.jsonl",
        tmp_path / "rqgm_audit.jsonl",
    ]
    before = {p: p.read_bytes() for p in watched}

    node = _node("n1", score=0.5)
    engine = FrontierRepairEngine(
        cfg=RQGMFrontierRepairConfig(),
        kernel=ConstitutionalKernel(),
        audit_log=audit,
        record_loader=load_rqgm_records,   # the real aggregation reader
    )
    result = engine.repair(
        transition=_transition([_retirement(role="generator",
                                            component_id="generator_v1")]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert result.status == "applied"
    for path, original in before.items():
        now = path.read_bytes()
        # Append-only: every pre-existing byte survives as a prefix.
        assert now.startswith(original), f"{path.name} was rewritten"
        if path.name in ("prompt_trace.jsonl", "memory_store.jsonl",
                         "proposal_records.jsonl",
                         "rqgm_adversarial_cases.jsonl",
                         "paper_anchor_corpus.jsonl"):
            assert now == original, f"{path.name} changed"
        assert len(now) >= len(original)
    # The record is stale ONLY in the erasure state, not in its JSONL line.
    stored = json.loads(
        (proposals_dir / "proposal_records.jsonl").read_text()
    )
    assert "stale" not in stored or stored.get("stale") is False
    state = json.loads((tmp_path / RQGM_ERASURE_STATE_FILENAME).read_text())
    assert "prop_001" in state["stale_record_ids"]


# ── §9.6 kernel detection + failure ladder ──────────────────────────────────


def test_kernel_detects_stale_frontier_and_conservative_repair_clears(
    tmp_path,
):
    # Force a stale node back into the frontier through a lying rebuild:
    # patch rebuild_frontier's inputs by pre-flagging the node in the state,
    # then verify conservative re-repair drops it.
    kernel = ConstitutionalKernel()
    stale_node = _node("n_bad", metrics={"_stale": True,
                                         "_valid_for_frontier": False})
    good_node = _node("n_good")
    state = ErasureStateView()
    report = kernel.validate_selective_erasure(
        [{"record_id": "n_bad", "stale": True, "valid_for_frontier": False,
          "prompt_hash": None}],
        [],
        frozenset({_H}),
    )
    assert any(v.code in ("CK-ERA-001", "CK-ERA-002")
               for v in report.violations)
    # Conservative drop clears the flagged node.
    frontier = [stale_node, good_node]
    FrontierRepairEngine._conservative_drop(frontier, state)
    assert [n.id for n in frontier] == ["n_good"]


class _BlockingKernel:
    """Deterministic fake: every validation blocks (double failure)."""

    def validate_selective_erasure(self, frontier, records, retired,
                                   **kwargs):
        from ari.rqgm.kernel_types import make_report

        v = SimpleNamespace(
            code="CK-ERA-001", severity="block",
            to_dict=lambda: {"code": "CK-ERA-001"},
        )
        return make_report("frontier_rebuild", [v])


def test_double_failure_degrades_to_halted_expansion(tmp_path):
    records = [
        _rec("rev_001", "review_record", prompt_hash=_H, role="reviewer",
             node_id="n1"),
    ]
    node = _node("n1", score=0.5)
    engine = _engine(tmp_path, records, kernel=_BlockingKernel())
    result = engine.repair(
        transition=_transition([_retirement()]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert result.status == "halted_expansion"
    assert engine.expansion_halted is True
    assert result.erasure_event["status"] == "halted_expansion"
    assert result.rebuild_event["status"] == "halted_expansion"
    assert result.rebuild_event["kernel_validation"] == "failed"
    # No crash: the audit trail still records both events.
    types = [ln.get("event_type") for ln in ImmutableAuditLog.read(tmp_path)]
    assert "selective_erasure" in types and "frontier_rebuild" in types


def test_prompt_trace_cross_check_detects_missing_producer(tmp_path):
    # §5.3 secondary evidence: a prompt_trace line carries the retired hash
    # but NO record was produced by that prompt — the producer index missed
    # an LLM output. The kernel flags CK-ERA-006; a conservative drop cannot
    # recreate the record, so the ladder degrades to drain-only.
    (tmp_path / "prompt_trace.jsonl").write_text(
        json.dumps({"prompt_name": "reviewer", "template_hash": _H,
                    "node_id": "n_ghost"}) + "\n"
    )
    records = [
        _rec("rev_001", "review_record", prompt_hash=_H_LIVE,
             role="reviewer", node_id="n1"),
    ]
    node = _node("n1", score=0.5)
    engine = _engine(tmp_path, records)
    result = engine.repair(
        transition=_transition([_retirement()]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert result.status == "halted_expansion"
    assert engine.expansion_halted is True


def test_prompt_trace_cross_check_passes_when_mapped(tmp_path):
    # The same trace line maps to a direct-set record (same hash, same node
    # anchor): the cross-check is satisfied and repair applies normally.
    (tmp_path / "prompt_trace.jsonl").write_text(
        json.dumps({"prompt_name": "reviewer", "template_hash": _H,
                    "node_id": "n1"}) + "\n"
    )
    records = [
        _rec("rev_001", "review_record", prompt_hash=_H, role="reviewer",
             node_id="n1"),
    ]
    node = _node("n1", score=0.5)
    engine = _engine(tmp_path, records)
    result = engine.repair(
        transition=_transition([_retirement()]),
        frontier=[node], pending=[], all_nodes=[node],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert result.status == "applied"
    assert engine.expansion_halted is False
    assert "rev_001" in result.erasure_event["direct_stale_record_ids"]


# ── §9.7 resume determinism ─────────────────────────────────────────────────


def _roundtrip_node(d: dict) -> Node:
    n = Node(id=d["id"], parent_id=d["parent_id"], depth=d["depth"],
             status=NodeStatus(d["status"]), metrics=dict(d["metrics"]),
             children=list(d["children"]))
    return n


def test_resume_reproduces_post_repair_frontier(tmp_path):
    records = [
        _rec("prop_001", "proposal_record", prompt_hash=_H, role="generator",
             source_refs={"node_id": "n_child", "parent_node_id": "n_root"}),
    ]
    root = _node("n_root", score=0.4, children=["n_child"])
    child = _node("n_child", parent="n_root", depth=1, score=0.9)
    frontier = [child]  # Rule A had retired the root
    engine = _engine(tmp_path, records)
    result = engine.repair(
        transition=_transition([_retirement(role="generator",
                                            component_id="generator_v1")]),
        frontier=frontier, pending=[], all_nodes=[root, child],
        checkpoint_dir=tmp_path, bfts_cfg=_bfts_cfg(),
    )
    assert result.status == "applied"
    post_repair = [n.id for n in frontier]
    assert post_repair == ["n_root"]  # reinstated

    # Kill + resume: nodes come back from their serialized dicts (tree.json
    # round-trip shape), erasure state from disk; the pure rebuild must
    # reproduce the same frontier.
    revived = [_roundtrip_node(root.to_dict()),
               _roundtrip_node(child.to_dict())]
    state = RqgmErasureStateStore().load(tmp_path)
    rebuilt = rebuild_frontier(revived, state, _bfts_cfg())
    assert [n.id for n in rebuilt] == post_repair
    # The erased node's sentinels survived the round-trip.
    revived_child = [n for n in revived if n.id == "n_child"][0]
    assert revived_child.metrics["_stale"] is True
    assert revived_child.metrics["_valid_for_frontier"] is False


def test_erasure_state_fold_roundtrip(tmp_path):
    store = RqgmErasureStateStore()
    event = {
        "record_id": "erase_00000",
        "record_type": "SelectiveErasureEvent",
        "epoch_id": "epoch_001",
        "retired_prompt_hashes": [_H],
        "direct_stale_record_ids": ["r1"],
        "transitive_stale_record_ids": ["r2"],
        "invalidated_node_ids": ["n1"],
        "abandoned_pending_node_ids": [],
    }
    view = store.apply_event(tmp_path, event)
    assert view.is_stale("r1") and view.is_stale("r2")
    assert view.invalid_node_ids() == frozenset({"n1"})
    # Reload from disk reproduces the same view; refold is idempotent.
    reloaded = store.load(tmp_path)
    assert reloaded.to_payload() == view.to_payload()
    assert fold_event(reloaded, event).to_payload() == view.to_payload()
    # Absent file => empty view, never an error.
    empty = store.load(tmp_path / "nowhere")
    assert empty.stale_ids() == frozenset()


# ── §9.8 simple_bfts regression + hygiene ───────────────────────────────────


def test_should_prune_additive_clause_inert_without_key():
    from ari.orchestrator.bfts import BFTS

    bfts = BFTS(ARIConfig().bfts, MagicMock())
    clean = _node("n1", depth=1)
    assert bfts.should_prune(clean, current_total=1) is False
    erased = _node("n2", depth=1, metrics={"_valid_for_frontier": False})
    assert bfts.should_prune(erased, current_total=1) is True


def test_flag_node_retains_score_and_selection_excludes_it():
    # _flag_node's contract: erasure is logical-only, so the stale score (and
    # has_real_data) deliberately SURVIVE on the node. The compensating
    # invariant is that every best-node consumer reads the sentinel —
    # BFTS.should_prune for expansion (above) and
    # verified_context.select_best_node for the paper candidate/seed
    # (plan 10 §1 "selected"; the §3 memory-consumer deferral, settled).
    from ari.pipeline.verified_context import select_best_node

    stale = _node("stale", score=0.9)
    stale.has_real_data = True
    FrontierRepairEngine._flag_node(stale, "generator_retired", "erase_000001")
    assert stale.metrics["_valid_for_frontier"] is False
    assert stale.metrics["_stale"] is True
    assert stale.metrics["_scientific_score"] == 0.9   # retained, not zeroed
    valid = _node("valid", score=0.2)
    valid.has_real_data = True
    assert select_best_node([stale, valid]).id == "valid"
    assert select_best_node([stale]) is None           # all erased ⇒ no winner


def test_meta_files_and_blocklist_registration():
    from ari.orchestrator.node_report.builder import (
        _FILES_CHANGED_BLOCKLIST_NAMES,
    )
    from ari.paths import PathManager

    assert "rqgm_erasure_state.json" in PathManager.META_FILES
    assert "rqgm_erasure_state.json" in _FILES_CHANGED_BLOCKLIST_NAMES


def test_simple_bfts_never_imports_frontier_repair():
    import subprocess

    code = (
        "import ari, ari.cli.bfts_loop, ari.orchestrator.bfts, sys; "
        "import ari.checkpoint, ari.paths, ari.protocols.stores; "
        "bad = [m for m in sys.modules if m.startswith('ari.rqgm')]; "
        "assert not bad, bad; print('clean')"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert out.returncode == 0, out.stderr
    assert "clean" in out.stdout


def test_simple_bfts_writes_no_erasure_file_or_sentinels(tmp_path):
    # A plain node lifecycle without the RQGM runtime writes neither the
    # state file nor any _stale-family key.
    node = _node("n1")
    tree = {"nodes": [node.to_dict()]}
    (tmp_path / "tree.json").write_text(json.dumps(tree, indent=2))
    stored = json.loads((tmp_path / "tree.json").read_text())
    keys = set(stored["nodes"][0]["metrics"])
    assert not [k for k in keys if k.startswith("_stale")]
    assert "_valid_for_frontier" not in keys
    assert not (tmp_path / RQGM_ERASURE_STATE_FILENAME).exists()


def test_defaults_yaml_parity_with_typed_model():
    import yaml

    defaults_path = (Path(__file__).parent.parent / "ari" / "configs"
                     / "defaults.yaml")
    doc = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
    block = doc["rqgm"]["frontier_repair"]
    model = RQGMFrontierRepairConfig()
    assert block["enabled"] == model.enabled
    assert block["max_trace_depth"] == model.max_trace_depth
    assert block["recompute_utilities"] == model.recompute_utilities
    assert block["abandon_stale_pending"] == model.abandon_stale_pending


# ── runtime wiring (Task 10 §5.2 hook shape) ────────────────────────────────


class _StubRepairEngine:
    def __init__(self, status="applied"):
        self.status = status
        self.calls: list = []
        self.expansion_halted = False

    def repair(self, **kwargs):
        self.calls.append(kwargs)
        return RepairResult({}, {}, self.status)


def _rqgm_runtime(tmp_path):
    from ari.rqgm.runtime import RQGMRuntime

    return RQGMRuntime(ARIConfig(), tmp_path)


def test_runtime_repair_hook_passes_search_state(tmp_path):
    rt = _rqgm_runtime(tmp_path)
    stub = _StubRepairEngine()
    rt._frontier_repair = stub
    flushed = []
    search_state = {
        "frontier": ["f"], "pending": ["p"], "all_nodes": ["a"],
        "flush_tree": lambda: flushed.append(True),
    }
    transition = _transition([_retirement()])
    rt._run_frontier_repair(transition, SimpleNamespace(epoch=None),
                            tmp_path, search_state)
    assert len(stub.calls) == 1
    call = stub.calls[0]
    assert call["frontier"] == ["f"] and call["pending"] == ["p"]
    assert call["all_nodes"] == ["a"]
    assert flushed == [True]
    assert rt.expansion_halted is False


def test_runtime_repair_hook_halts_expansion_on_degradation(tmp_path):
    rt = _rqgm_runtime(tmp_path)
    rt._frontier_repair = _StubRepairEngine(status="halted_expansion")
    rt._run_frontier_repair(
        _transition([_retirement()]), SimpleNamespace(epoch=None),
        tmp_path, {"frontier": [], "pending": [], "all_nodes": []},
    )
    assert rt.expansion_halted is True


def test_runtime_repair_hook_noop_without_search_state_or_retirements(
    tmp_path,
):
    rt = _rqgm_runtime(tmp_path)
    stub = _StubRepairEngine()
    rt._frontier_repair = stub
    rt._run_frontier_repair(_transition([_retirement()]),
                            SimpleNamespace(epoch=None), tmp_path, None)
    rt._run_frontier_repair(_transition([]), SimpleNamespace(epoch=None),
                            tmp_path, {"frontier": []})
    assert stub.calls == []


def test_runtime_engine_disabled_by_config(tmp_path):
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig()
    cfg.rqgm.frontier_repair.enabled = False
    rt = RQGMRuntime(cfg, tmp_path)
    assert rt.frontier_repair is None
