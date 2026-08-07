"""RQGM Task 12 — cost control and context budget
(docs/reference/rqgm_schemas.md §Governance-cache schema (Task 12) for the
``cache_key``; docs/reference/configuration.md §``rqgm.budgets`` — per-epoch
governance spend caps / §``rqgm.shadow`` — shadow live-evaluation sampling;
docs/concepts/rqgm_runtime_walkthrough.md §4. Per node — proposal, execution,
governance level for the L0-L3 trigger ladder).

Covers: the golden ``cache_key`` (component order + separator pinned;
timestamps provably excluded), canonical-JSON hashing (key order
independence), the ``assign_level`` §5.2 trigger table (sterile floor,
top-K id tie-break, score jump, novelty, low-confidence escalation),
deterministic hash-based shadow sampling (cross-process stable, ±2%
empirical rate, cap truncation), budget counter exhaustion + audit-log
round-trip (resume-safety), the additive ``CallRecord.epoch`` field
(old lines parse; simple_bfts lines byte-free of the key), the §6.2
replay cache-lookup rule and its live wiring into the candidate
evaluation path (cache consulted first, pool scores written back), the
Task 07 shadow sampler's delegation to the single §5.6 hash rule, the
spec-required cost regression / budget check (stub LLM, tiny caps,
degrade-never-block, real governance spend through ``_LLMBudget``), the
``simple_bfts`` no-op regression, and META_FILES hygiene for the new
cache file.

No test calls a real LLM (plan 12: budget checks are deterministic and
testable without an LLM).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import yaml

from ari.config import (
    ARIConfig,
    RQGMGovernanceConfig,
    RQGMShadowConfig,
    RQGMSpendBudgetConfig,
)
from ari.cost_tracker import CostTracker
from ari.rqgm.budget import (
    ADVERSARY_CALL,
    BUDGET_CONSUMED_EVENT,
    BUDGET_DEGRADED_EVENT,
    DEFENDER_CALL,
    GOVERNANCE_LEVEL_EVENT,
    GOVERNANCE_LLM_CALL,
    JUDGE_CALL,
    PROMPT_CANDIDATE,
    REPLAY_CASE,
    SHADOW_CALL,
    VIRSCI_CALL,
    BudgetedAction,
    GovernanceBudgetManager,
)
from ari.rqgm.governance_cache import (
    GOVERNANCE_CACHE_FILENAME,
    GovernanceCache,
    canonical_hash,
    make_cache_key,
    replay_lookup_key,
)
from ari.rqgm.store import ImmutableAuditLog

E = "epoch_000"


def _cfg(**rqgm_over) -> ARIConfig:
    rqgm = {"enabled": True}
    rqgm.update(rqgm_over)
    return ARIConfig(ari={"mode": "ari_rqgm"}, rqgm=rqgm)


def _epoch(epoch_id: str = E, run_id: str = "run-x"):
    return SimpleNamespace(epoch_id=epoch_id, run_id=run_id)


def _manager(cfg=None, tmp_path=None, tracker=None, store=None,
             epoch=None) -> GovernanceBudgetManager:
    return GovernanceBudgetManager(
        cfg if cfg is not None else _cfg(),
        epoch_state=epoch if epoch is not None else _epoch(),
        cost_tracker=tracker,
        checkpoint_dir=tmp_path,
        proposal_store=store,
    )


def _node(node_id="node_a", score=0.5, sterile=False, axis=None):
    metrics = {"_scientific_score": score}
    if sterile:
        metrics["_sterile"] = True
    if axis is not None:
        metrics["_axis_scores"] = dict(axis)
    return SimpleNamespace(id=node_id, metrics=metrics)


# ── §9.1 cache_key golden test ───────────────────────────────────────────────


def test_cache_key_golden_composition_and_separator():
    key = make_cache_key(
        artifact_hash="sha256:aa",
        prompt_hash="9f2c01ab34de",
        role="judge",
        epoch_id="epoch_004",
        input_context_hash="sha256:bb",
        output_schema_hash="sha256:cc",
    )
    # Golden: fixed inputs -> fixed key (component order + separator pinned).
    assert key == "944ccdbbaa7205d5"
    # The exact §5.5 recipe: "\x1f"-joined components, sha256, 16 hex chars.
    manual = hashlib.sha256(
        "\x1f".join([
            "sha256:aa", "9f2c01ab34de", "judge", "epoch_004",
            "sha256:bb", "sha256:cc",
        ]).encode("utf-8")
    ).hexdigest()[:16]
    assert key == manual
    # Component order is load-bearing: swapping two components changes it.
    swapped = make_cache_key(
        artifact_hash="9f2c01ab34de",
        prompt_hash="sha256:aa",
        role="judge",
        epoch_id="epoch_004",
        input_context_hash="sha256:bb",
        output_schema_hash="sha256:cc",
    )
    assert swapped != key


def test_cache_key_excludes_timestamps(tmp_path):
    """Two records differing only in created_at collide on one key (P2)."""
    cache = GovernanceCache(tmp_path)
    components = dict(
        artifact_hash="sha256:aa", prompt_hash="p" * 12, role="reviewer",
        epoch_id=E, input_context_hash="sha256:bb",
        output_schema_hash="sha256:cc",
    )
    k1 = cache.make_key(**components)
    cache.put(k1, {"result_ref": "judgment_1",
                   "created_at": "2026-01-01T00:00:00Z"})
    cache.put(k1, {"result_ref": "judgment_1",
                   "created_at": "2026-12-31T23:59:59Z"})
    assert cache.make_key(**components) == k1  # created_at never enters
    lines = [
        json.loads(l) for l in
        (tmp_path / GOVERNANCE_CACHE_FILENAME).read_text().splitlines()
    ]
    assert len(lines) == 2  # append-only: both lines kept
    assert {l["cache_key"] for l in lines} == {k1}


# ── §9.2 canonical-JSON hashing ─────────────────────────────────────────────


def test_canonical_hash_is_key_order_independent():
    a = canonical_hash({"b": 2, "a": {"y": 1, "x": [1, 2]}})
    b = canonical_hash({"a": {"x": [1, 2], "y": 1}, "b": 2})
    assert a == b
    assert a.startswith("sha256:")
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


# ── §9.8 replay cache-lookup rule ───────────────────────────────────────────


def test_replay_lookup_uses_case_origin_epoch(tmp_path):
    cache = GovernanceCache(tmp_path)
    seeded = make_cache_key(
        artifact_hash="", prompt_hash="cand" * 3, role="judge",
        epoch_id="epoch_002", input_context_hash="", output_schema_hash="",
    )
    cache.put(seeded, {"role": "judge", "epoch_id": "epoch_002",
                       "prompt_hash": "cand" * 3, "result_ref": "jdg_1"})
    # Replaying case c (origin epoch_002) under candidate prompt p in a
    # LATER epoch builds the key from c.origin_epoch_id + p.hash — and hits.
    case = SimpleNamespace(origin_epoch_id="epoch_002", epoch_id="epoch_005")
    key = replay_lookup_key(case, prompt_hash="cand" * 3, role="judge")
    assert key == seeded
    assert cache.get(key)["result_ref"] == "jdg_1"
    # dict-shaped cases fall back to epoch_id when origin is absent.
    assert replay_lookup_key(
        {"epoch_id": "epoch_002"}, prompt_hash="cand" * 3, role="judge"
    ) == seeded


def test_candidate_evaluation_consults_and_fills_the_cache(tmp_path):
    """§5.5 wiring: with ``use_cached_results`` the replay/candidate path
    consults the governance cache FIRST (a hit scores a case whose pool
    results are silent) and writes pool-derived scores back."""
    from ari.rqgm.governance._adjudication import evaluate_candidates

    cache = GovernanceCache(tmp_path)
    case = {"case_id": "case_001", "origin_epoch_id": "epoch_002",
            "results": {}}  # the pool holds NO stored result
    key = replay_lookup_key(case, prompt_hash="b" * 12, role="reviewer")
    cache.put(key, {"role": "reviewer", "epoch_id": "epoch_002",
                    "prompt_hash": "b" * 12, "result_ref": "case_001",
                    "score": 0.9})
    pool = SimpleNamespace(cases=lambda: [case])
    evals, replay_used, _ = evaluate_candidates(
        candidate_prompts=[{"prompt_id": "reviewer_prompt_v4",
                            "role": "reviewer", "prompt_hash": "b" * 12}],
        pool=pool, max_cases=8, use_cached=True, cache=cache,
    )
    assert evals[0]["replay_score"] == 0.9  # served from the Task 12 cache
    assert replay_used == 1
    # A pool-scored (case, prompt) pair is written back for later replays.
    case2 = {"case_id": "case_002", "origin_epoch_id": "epoch_002",
             "results": {"c" * 12: 0.4}}
    evaluate_candidates(
        candidate_prompts=[{"prompt_id": "judge_prompt_v2", "role": "judge",
                            "prompt_hash": "c" * 12}],
        pool=SimpleNamespace(cases=lambda: [case2]),
        max_cases=8, use_cached=True, cache=cache,
    )
    key2 = replay_lookup_key(case2, prompt_hash="c" * 12, role="judge")
    hit = GovernanceCache(tmp_path).get(key2)  # fresh index from the JSONL
    assert hit is not None and hit["score"] == 0.4
    # use_cached=false: the cache is never consulted (pool-only scoring).
    evals, _, _ = evaluate_candidates(
        candidate_prompts=[{"prompt_id": "reviewer_prompt_v4",
                            "role": "reviewer", "prompt_hash": "b" * 12}],
        pool=pool, max_cases=8, use_cached=False, cache=cache,
    )
    assert evals[0]["replay_score"] is None


def test_orchestrator_forwards_the_governance_cache(tmp_path):
    """The runtime-built GovernanceOrchestrator carries a cache exactly when
    ``rqgm.replay.use_cached_results`` (the §5.5 construction seam)."""
    from ari.rqgm.runtime import RQGMRuntime

    on = RQGMRuntime(_cfg(), checkpoint_dir=tmp_path)
    assert on.governance is not None
    assert on.governance.governance_cache is not None
    off = RQGMRuntime(
        _cfg(replay={"use_cached_results": False}), checkpoint_dir=tmp_path
    )
    assert off.governance is not None
    assert off.governance.governance_cache is None


def test_cache_record_validates_against_schema(tmp_path):
    import jsonschema

    import ari.schemas as schemas

    cache = GovernanceCache(tmp_path)
    key = make_cache_key(
        artifact_hash="sha256:aa", prompt_hash="p" * 12, role="judge",
        epoch_id=E, input_context_hash=canonical_hash({"x": 1}),
        output_schema_hash=canonical_hash({}),
    )
    cache.put(key, {
        "role": "judge", "epoch_id": E, "prompt_hash": "p" * 12,
        "artifact_hash": "sha256:aa",
        "input_context_hash": canonical_hash({"x": 1}),
        "output_schema_hash": canonical_hash({}),
        "result_ref": "judgment_00042",
    })
    line = json.loads(
        (tmp_path / GOVERNANCE_CACHE_FILENAME).read_text().splitlines()[0]
    )
    jsonschema.validate(line, schemas.load("rqgm_governance_cache.schema"))


def test_cache_absent_file_is_empty_and_index_restores(tmp_path):
    assert GovernanceCache(tmp_path).get("0" * 16) is None  # absence != error
    cache = GovernanceCache(tmp_path)
    cache.put("a" * 16, {"role": "judge", "result_ref": "r1"})
    # A fresh instance rebuilds the index from the JSONL (resume, §8).
    again = GovernanceCache(tmp_path)
    assert again.get("a" * 16)["result_ref"] == "r1"


# ── §9.3 assign_level trigger table ─────────────────────────────────────────


def test_assign_level_sterile_never_exceeds_l0():
    m = _manager()
    level, triggers = m.level_with_triggers(
        _node(sterile=True, score=0.99), frontier=[],
        paper_candidate=True, parent_score=0.0,
    )
    assert (level, triggers) == (0, ["sterile"])


def test_assign_level_default_without_triggers():
    m = _manager()
    frontier = [_node(f"node_top{i}", score=0.9) for i in range(3)]
    level, triggers = m.level_with_triggers(
        _node("node_z", score=0.1), frontier=frontier,
    )
    assert (level, triggers) == (1, [])


def test_assign_level_top_k_with_id_tie_break():
    m = _manager(_cfg(governance={"full_governance_only_on_top_k": 1}))
    tied_a = _node("node_a", score=0.7)
    tied_b = _node("node_b", score=0.7)
    frontier = [tied_b, tied_a]
    # Equal scores: lexicographically smaller id wins the single slot.
    assert m.level_with_triggers(tied_a, frontier=frontier) == (3, ["top_k"])
    assert m.level_with_triggers(tied_b, frontier=frontier) == (1, [])


def test_assign_level_score_jump_and_novelty_and_paper():
    m = _manager()
    frontier = [_node(f"node_top{i}", score=0.95) for i in range(3)]
    lvl, trg = m.level_with_triggers(
        _node("node_j", score=0.5), frontier=frontier, parent_score=0.2,
    )
    assert (lvl, trg) == (2, ["score_jump"])  # 0.3 > jump_threshold 0.25
    lvl, trg = m.level_with_triggers(
        _node("node_n", score=0.5, axis={"novelty": 0.85}), frontier=frontier,
    )
    assert (lvl, trg) == (2, ["novelty_claim"])
    lvl, trg = m.level_with_triggers(
        _node("node_r", score=0.5), frontier=frontier,
        novelty_risks=("prior art overlap",),
    )
    assert (lvl, trg) == (2, ["novelty_claim"])
    lvl, trg = m.level_with_triggers(
        _node("node_p", score=0.1), frontier=frontier, paper_candidate=True,
    )
    assert lvl == 3 and "paper_candidate" in trg


def test_assign_level_low_confidence_escalates_l2_to_l3():
    m = _manager()
    frontier = [_node(f"node_top{i}", score=0.95) for i in range(3)]
    # From L1: low confidence raises into the contested tier.
    lvl, trg = m.level_with_triggers(
        _node("node_c", score=0.3), frontier=frontier, review_confidence=0.3,
    )
    assert (lvl, trg) == (2, ["low_confidence"])
    # From L2 (score jump): disputed -> L3.
    lvl, trg = m.level_with_triggers(
        _node("node_d", score=0.6), frontier=frontier, parent_score=0.2,
        review_confidence=0.3,
    )
    assert lvl == 3 and trg == ["score_jump", "low_confidence"]


def test_assign_level_is_logged_replayably(tmp_path):
    m = _manager(tmp_path=tmp_path)
    m.record_level("node_x", 3, ["top_k"])
    lines = ImmutableAuditLog.read(tmp_path)
    levels = [l for l in lines
              if l.get("event_type") == GOVERNANCE_LEVEL_EVENT]
    assert levels[-1]["payload"] == {
        "epoch_id": E, "node_id": "node_x", "level": 3, "triggers": ["top_k"],
    }


# ── §9.4 shadow-sampling determinism ────────────────────────────────────────


def test_shadow_sample_matches_the_spec_hash_rule():
    m = _manager(epoch=_epoch("epoch_001", "run-1"))
    seed = "run-1:epoch_001:node_42:shadow"
    expected = (
        int(hashlib.sha256(seed.encode()).hexdigest(), 16) % 10_000 < 2_000
    )
    assert m.shadow_sample("node_42") is expected
    # Same (run_id, epoch_id, node_id) -> same verdict, every time.
    assert all(
        m.shadow_sample("node_42") == expected for _ in range(5)
    )


def test_shadow_sample_empirical_rate_and_truncation():
    m = _manager(epoch=_epoch("epoch_001", "run-1"))
    ids = [f"node_{i:05d}" for i in range(10_000)]
    rate = sum(m.shadow_sample(n) for n in ids) / 10_000
    assert abs(rate - 0.2) < 0.02  # ±2% of sample_rate
    cfg = _cfg(shadow={"max_shadow_calls_per_epoch": 5})
    m2 = _manager(cfg, epoch=_epoch("epoch_001", "run-1"))
    selected = m2.select_shadow_nodes(ids)
    assert len(selected) == 5
    assert selected == sorted(selected)  # node-id order truncation
    assert all(m2.shadow_sample(n) for n in selected)


def test_shadow_disabled_means_zero_budget():
    m = _manager(_cfg(shadow={"enabled": False}))
    assert m.shadow_sample("node_1") is False
    assert not m.check(BudgetedAction(SHADOW_CALL)).allowed


def test_pipeline_should_shadow_delegates_to_the_budget_rule():
    """One §5.6 hash rule: the Task 07 live sampler delegates to
    ``GovernanceBudgetManager.shadow_sample`` — same verdicts for the same
    ``(run_id, epoch_id, node_id)`` — and ``shadow.enabled: false`` zeroes
    the Task 07 path too."""
    from ari.rqgm.prompt_evolution import CandidateValidationPipeline

    cfg = _cfg()
    pipeline = CandidateValidationPipeline(cfg=cfg, run_id="run-1")
    m = _manager(cfg, epoch=_epoch("epoch_001", "run-1"))
    ids = [f"node_{i:03d}" for i in range(64)]
    assert [pipeline.should_shadow("epoch_001", n) for n in ids] == [
        m.shadow_sample(n) for n in ids
    ]
    off = CandidateValidationPipeline(
        cfg=_cfg(shadow={"enabled": False}), run_id="run-1"
    )
    assert off.shadow_budget_left("epoch_001") == 0
    assert off.should_shadow("epoch_001", "node_001") is False


# ── §9.5 budget counter exhaustion + resume round-trip ──────────────────────


def test_check_degrade_vs_skip_posture_and_consume_never_raises(tmp_path):
    cfg = _cfg(governance={"max_judge_calls_per_epoch": 1})
    m = _manager(cfg, tmp_path=tmp_path)
    judge = BudgetedAction(JUDGE_CALL)
    assert m.check(judge).allowed and m.check(judge).remaining == 1
    m.consume(judge)
    verdict = m.check(judge)
    assert verdict.decision == "degrade"  # on_exhausted default
    m.consume(judge)  # past the cap: never raises (caps, not assertions)
    m.consume(judge, count=-5)  # garbage counts clamp, never raise
    cfg_skip = _cfg(
        governance={"max_judge_calls_per_epoch": 1},
        budgets={"on_exhausted": "skip"},
    )
    m2 = _manager(cfg_skip, tmp_path=tmp_path)
    assert m2.check(judge).decision == "skip"  # counters restored + posture


def test_counters_round_trip_through_the_audit_log(tmp_path):
    m = _manager(tmp_path=tmp_path)
    m.consume(BudgetedAction(DEFENDER_CALL), count=3)
    m.consume(BudgetedAction(PROMPT_CANDIDATE, role="reviewer"))
    # A fresh manager on the same checkpoint restores every counter
    # (resume-safety: in-memory-only counters would double budgets).
    m2 = _manager(_cfg(governance={"max_defender_calls_per_epoch": 3}),
                  tmp_path=tmp_path)
    assert not m2.check(BudgetedAction(DEFENDER_CALL)).allowed
    assert not m2.check(
        BudgetedAction(PROMPT_CANDIDATE, role="reviewer")
    ).allowed  # per-role cap 1 already consumed
    assert m2.check(BudgetedAction(PROMPT_CANDIDATE, role="adversary")).allowed
    lines = ImmutableAuditLog.read(tmp_path)
    assert [l for l in lines if l.get("event_type") == BUDGET_CONSUMED_EVENT]


def test_prompt_candidate_total_cap_across_roles():
    cfg = _cfg(prompt_evolution={"max_candidates_per_role_per_epoch": 1,
                                 "max_total_candidates_per_epoch": 2})
    m = _manager(cfg)
    for role in ("reviewer", "adversary"):
        m.consume(BudgetedAction(PROMPT_CANDIDATE, role=role))
    verdict = m.check(BudgetedAction(PROMPT_CANDIDATE, role="judge"))
    assert not verdict.allowed and "total cap" in verdict.reason


def test_replay_cap_switches_for_retirement():
    m = _manager()
    normal = m.check(BudgetedAction(REPLAY_CASE))
    retire = m.check(BudgetedAction(REPLAY_CASE, retirement_pending=True))
    assert normal.remaining == 8 and retire.remaining == 12


def test_pipeline_motion_replay_cap_gates_through_the_manager(tmp_path):
    """The epoch-boundary replay-selection cap (plan 12 §5.4): the audit
    pipeline picks ``max_cases_for_retirement`` for retirement-relevant
    motions and honors booked REPLAY_CASE consumption via the manager."""
    from ari.rqgm.governance._pipeline import _motion_replay_cap

    m = _manager(tmp_path=tmp_path)
    kw = dict(max_cases=8, max_cases_retirement=12, budget_manager=m,
              motion_id="imp_00001")
    assert _motion_replay_cap(retirement=False, **kw) == (8, False)
    assert _motion_replay_cap(retirement=True, **kw) == (12, False)
    # Booked consumption lowers the cap; exhaustion (remaining 0) reports
    # exhausted=True so the caller skips board selection instead of
    # falling into board_score's `0 == unlimited` semantics.
    m.consume(BudgetedAction(REPLAY_CASE), count=10)
    assert _motion_replay_cap(retirement=True, **kw) == (2, False)
    assert _motion_replay_cap(retirement=False, **kw) == (0, True)
    # No manager: config caps pass through untouched (fail-open posture).
    kw["budget_manager"] = None
    assert _motion_replay_cap(retirement=True, **kw) == (12, False)


def test_spend_cap_reads_governance_phase_epoch_records():
    tracker = SimpleNamespace(_records=[
        SimpleNamespace(phase="governance", epoch=E,
                        estimated_cost_usd=0.02, total_tokens=100),
        SimpleNamespace(phase="react", epoch=E,  # non-governance: ignored
                        estimated_cost_usd=9.99, total_tokens=10_000),
        SimpleNamespace(phase="governance", epoch="epoch_009",  # other epoch
                        estimated_cost_usd=9.99, total_tokens=10_000),
    ])
    cfg = _cfg(budgets={"max_governance_cost_usd_per_epoch": 0.01})
    m = _manager(cfg, tracker=tracker)
    verdict = m.check(BudgetedAction(JUDGE_CALL))
    assert verdict.decision == "degrade" and "cost" in verdict.reason
    # 0 == unlimited: the same spend passes with the inert default.
    assert _manager(_cfg(), tracker=tracker).check(
        BudgetedAction(JUDGE_CALL)
    ).allowed


def test_virsci_budget_zero_cost_when_disabled_and_store_counted():
    # Disabled (the default): cap 0 -> never allowed, no adapter consulted.
    assert not _manager().check(BudgetedAction(VIRSCI_CALL)).allowed
    # Enabled: counting shares the ProposalStore's durable source.
    cfg = ARIConfig(
        ari={"mode": "ari_rqgm"}, rqgm={"enabled": True},
        proposal_router={"generators": {"virsci": {
            "enabled": True, "max_calls_per_epoch": 2,
        }}},
    )
    used = {"n": 0}
    store = SimpleNamespace(
        count_for_epoch=lambda gen, eid: used["n"] if gen == "virsci" else 0
    )
    m = _manager(cfg, store=store)
    assert m.check(BudgetedAction(VIRSCI_CALL)).remaining == 2
    used["n"] = 2
    assert not m.check(BudgetedAction(VIRSCI_CALL)).allowed


# ── §9.6 CallRecord.epoch additive-field compatibility ──────────────────────


def test_old_cost_trace_lines_parse_and_summary_unchanged(tmp_path):
    old_line = {
        "timestamp": "2026-01-01T00:00:00Z", "node_id": "n1",
        "phase": "react", "skill": "agent_loop", "model": "gpt-4o",
        "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
        "estimated_cost_usd": 0.001,
    }
    (tmp_path / "cost_trace.jsonl").write_text(json.dumps(old_line) + "\n")
    tracker = CostTracker(tmp_path)  # absence of `epoch` is never an error
    assert tracker._records[0].epoch is None
    tracker.record(model="gpt-4o", prompt_tokens=10, completion_tokens=5,
                   phase="react")
    summary = json.loads((tmp_path / "cost_summary.json").read_text())
    assert summary["call_count"] == 2
    assert "epoch" not in json.dumps(summary)


def test_epoch_emitted_only_when_non_none(tmp_path):
    tracker = CostTracker(tmp_path)
    tracker.record(model="m", prompt_tokens=1, completion_tokens=1)
    tracker.record(model="m", prompt_tokens=1, completion_tokens=1,
                   phase="governance", epoch="epoch_003")
    lines = [json.loads(l) for l in
             (tmp_path / "cost_trace.jsonl").read_text().splitlines()]
    assert "epoch" not in lines[0]  # simple_bfts lines: byte-compatible
    assert lines[1]["epoch"] == "epoch_003"


# ── §9.9 cost regression / budget check (stub LLM, tiny caps) ───────────────


class _FakeRec:
    """Minimal adversarial record double (record_id + to_dict only)."""

    def __init__(self, record_id: str, record_type: str = "raw_attack",
                 verdict: str = "") -> None:
        self.record_id = record_id
        self.record_type = record_type
        self.verdict = verdict
        self.raw_attack_id = record_id

    def to_dict(self) -> dict:
        return {"record_id": self.record_id, "record_type": self.record_type,
                "epoch_id": E}


def _gated_round(tmp_path, monkeypatch, cfg):
    """AdversarialRound with fake actors + the Task 12 budget manager."""
    import ari.rqgm.adversarial.round as round_mod
    from ari.rqgm.adversarial.round import AdversarialRound

    manager = _manager(cfg, tmp_path=tmp_path)
    rnd = AdversarialRound(
        cfg.rqgm.adversarial, checkpoint_dir=tmp_path,
        epoch_state=_epoch(), budget_manager=manager,
        governance_cfg=cfg.rqgm.governance,
    )
    bundle = SimpleNamespace(
        score=1.0, node_id="node_1", eval_summary="", proposal_text="",
        gate_findings=[], node_report={}, node_report_path="",
        validate_metrics_flags=[], related_refs=[],
        remaining_node_budget=-1, plan_step_count=0,
    )
    monkeypatch.setattr(round_mod, "build_artifact_bundle",
                        lambda node, ckpt, **_kw: bundle)
    monkeypatch.setattr(
        round_mod, "should_attack", lambda **kw: True
    )
    calls = {"defender": 0, "judge": 0}
    rnd.engine.attack = lambda bundle: [_FakeRec("atk_00001")]

    def _respond(attacks, bundle):
        calls["defender"] += 1
        return [_FakeRec("def_00001", "defender_response")]

    def _adjudicate(attacks, defenses, bundle):
        calls["judge"] += 1
        return []  # no validated attacks -> zero penalty path

    rnd.defender.respond = _respond
    rnd.judge.adjudicate = _adjudicate
    return rnd, manager, calls


def test_round_respects_defender_judge_caps_and_never_blocks(
    tmp_path, monkeypatch
):
    cfg = _cfg(governance={"max_defender_calls_per_epoch": 0,
                           "judge_on_disputed_only": True},
               budgets={"on_exhausted": "skip"})
    rnd, manager, calls = _gated_round(tmp_path, monkeypatch, cfg)
    summary = rnd.run(SimpleNamespace(id="node_1", metrics={}))
    # Budget-denied defender: attacks lapse as observations; the
    # disputed-only judge never runs; the round still completes.
    assert summary is not None and summary["validated"] == 0
    assert calls == {"defender": 0, "judge": 0}
    lines = ImmutableAuditLog.read(tmp_path)
    degraded = [l for l in lines
                if l.get("event_type") == BUDGET_DEGRADED_EVENT]
    assert degraded and degraded[0]["payload"]["kind"] == DEFENDER_CALL


def test_round_consumes_within_caps(tmp_path, monkeypatch):
    cfg = _cfg(governance={"max_defender_calls_per_epoch": 12,
                           "max_judge_calls_per_epoch": 8})
    rnd, manager, calls = _gated_round(tmp_path, monkeypatch, cfg)
    rnd.run(SimpleNamespace(id="node_1", metrics={}))
    assert calls == {"defender": 1, "judge": 1}
    consumed = [
        l["payload"] for l in ImmutableAuditLog.read(tmp_path)
        if l.get("event_type") == BUDGET_CONSUMED_EVENT
    ]
    kinds = {p["kind"] for p in consumed}
    assert {ADVERSARY_CALL, DEFENDER_CALL, JUDGE_CALL} <= kinds
    # Per-role counts recorded never exceed the configured caps.
    per_kind: dict = {}
    for p in consumed:
        per_kind[p["kind"]] = per_kind.get(p["kind"], 0) + p["count"]
    assert per_kind[DEFENDER_CALL] <= 12 and per_kind[JUDGE_CALL] <= 8


def test_governance_llm_budget_consults_manager():
    from ari.rqgm.governance._pipeline import _LLMBudget

    calls = []

    class _StubLLM:
        def complete(self, messages, require_tool=True, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content="{}")

    exhausted = _manager(
        _cfg(governance={"max_llm_calls_per_audit": 0})
    )
    budget = _LLMBudget(_StubLLM(), 5, manager=exhausted)
    assert budget.complete("p") is None  # degrade to deterministic fallback
    assert budget.exhausted and not calls
    allowing = _manager(_cfg())
    budget2 = _LLMBudget(_StubLLM(), 5, manager=allowing)
    assert budget2.complete("p") == "{}"
    assert calls and calls[0].get("phase") == "governance"
    # The successful call was booked back into the manager's counter.
    assert allowing.check(BudgetedAction(GOVERNANCE_LLM_CALL)).remaining == 11


def test_ari_rqgm_smoke_run_with_stub_llm_and_tiny_caps(
    tmp_path, monkeypatch
):
    """The spec-required budget check (§9.9): an ari_rqgm loop with a stub
    LLM completes (degrade-never-block) while a seeded threshold-flagged
    audit target forces real governance spend through the ``_LLMBudget``
    seam — booked to cost_trace.jsonl (phase="governance", per epoch) and
    to the durable ``budget_consumed`` trail, never exceeding the caps."""
    import ari.cost_tracker as ct
    from ari.rqgm.runtime import RQGMRuntime

    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    monkeypatch.setattr(ct, "_tracker", None)
    monkeypatch.setattr(ct, "_DEFAULT_METADATA", {})
    ct.init(tmp_path)

    class _StubLLM:
        def complete(self, messages, require_tool=True, **kwargs):
            ct.record(model="stub-model", prompt_tokens=7,
                      completion_tokens=3,
                      phase=kwargs.get("phase", ""),
                      skill=kwargs.get("skill", ""),
                      epoch=ct._DEFAULT_METADATA.get("epoch"))
            return SimpleNamespace(content="not-json")  # forces fallbacks

    # Seed a threshold-flagged prosecution target into the epoch_000 audit
    # slice (2 validated attacks >= ATTACK_THRESHOLD): the audit's defender
    # and judge steps then spend real stub-LLM calls through _LLMBudget.
    seed = ImmutableAuditLog(tmp_path)
    seed.append("review_record", {
        "record_id": "rev_00001", "record_type": "review_record",
        "epoch_id": E, "component_id": "reviewer_v1", "role": "reviewer",
    })
    for i in (1, 2):
        seed.append("validated_attack", {
            "record_id": f"vat_0000{i}", "record_type": "validated_attack",
            "epoch_id": E, "component_id": "judge_v0", "role": "judge",
            "target_component_id": "reviewer_v1",
        })

    max_llm = 2
    cfg = ARIConfig(
        bfts={"max_total_nodes": 3, "max_parallel_nodes": 1,
              "timeout_per_node": 60},
        ari={"mode": "ari_rqgm"},
        rqgm={"enabled": True, "epoch": {"nodes_per_epoch": 1},
              "governance": {"max_llm_calls_per_audit": max_llm,
                             "max_defender_calls_per_epoch": 1,
                             "max_judge_calls_per_epoch": 1}},
    )
    runtime = RQGMRuntime(cfg, checkpoint_dir=tmp_path, llm=_StubLLM())
    governed = runtime.wrap_search_strategy(_make_strategy())
    total = _run_short_loop(tmp_path, governed, cfg)
    assert total >= 1  # (b) the run completes
    trace = tmp_path / "cost_trace.jsonl"
    assert trace.exists()
    per_epoch_role: dict = {}
    for line in trace.read_text().splitlines():
        d = json.loads(line)
        if d.get("phase") == "governance" and d.get("epoch"):
            key = (d["epoch"], d.get("skill", ""))
            per_epoch_role[key] = per_epoch_role.get(key, 0) + 1
    # (a) non-vacuous: the epoch_000 audit really spent governance calls...
    orchestrator_key = (E, "governance_orchestrator")
    assert orchestrator_key in per_epoch_role, per_epoch_role
    # ...and per-role per-epoch counts never exceed the configured cap.
    assert all(
        n <= max_llm
        for (eid, skill), n in per_epoch_role.items()
        if skill == "governance_orchestrator"
    ), per_epoch_role
    # Every governance-LLM spend was also booked into the durable budget
    # trail — the stub books identically to the real seam.
    consumed = [
        l["payload"] for l in ImmutableAuditLog.read(tmp_path)
        if l.get("event_type") == BUDGET_CONSUMED_EVENT
        and (l.get("payload") or {}).get("kind") == GOVERNANCE_LLM_CALL
    ]
    assert sum(p.get("count", 0) for p in consumed) == (
        per_epoch_role[orchestrator_key]
    )


# ── §9.10 simple_bfts no-op regression ──────────────────────────────────────


def _make_agent():
    agent = MagicMock()
    agent.hints = SimpleNamespace(provided_files=[], slurm_partition="",
                                  slurm_max_cpus=0)
    agent.memory = MagicMock()
    agent.memory.search.return_value = []

    def _run(node, exp_data):
        node.mark_running()
        node.mark_success(eval_summary="ok")
        node.has_real_data = True
        return node

    agent.run.side_effect = _run
    return agent


def _make_strategy():
    from ari.orchestrator.node import Node

    bfts = MagicMock()
    bfts.should_prune.return_value = False
    counter = {"n": 0}

    def _expand(node, *args, **kwargs):
        counter["n"] += 1
        child = Node(id=f"child_{counter['n']}", parent_id=node.id,
                     depth=node.depth + 1)
        node.children.append(child.id)
        return [child]

    bfts.expand.side_effect = _expand
    bfts.select_best_to_expand.side_effect = lambda f, g, m: f[0]
    bfts.select_next_node.side_effect = lambda p, g, m: p[0]
    bfts.expansion_count.return_value = 0
    bfts.diversity_bonus.return_value = 0.0
    return bfts


def _run_short_loop(tmp_path, strategy, cfg):
    from ari.cli import _run_loop
    from ari.orchestrator.node import Node

    root = Node(id="node_root", parent_id=None, depth=0)
    return _run_loop(
        cfg, strategy, _make_agent(), [root], [root],
        {"goal": "g", "topic": "t", "file": "exp.md"},
        checkpoint_dir=tmp_path, run_id="budget-smoke",
    )


def test_simple_bfts_writes_no_cache_and_no_epoch_values(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    cfg = ARIConfig(bfts={"max_total_nodes": 3, "max_parallel_nodes": 1,
                          "timeout_per_node": 60})
    _run_short_loop(tmp_path, _make_strategy(), cfg)
    assert not (tmp_path / GOVERNANCE_CACHE_FILENAME).exists()
    tracker = CostTracker(tmp_path / "costs")
    tracker.record(model="m", prompt_tokens=1, completion_tokens=1,
                   phase="react")
    raw = (tmp_path / "costs" / "cost_trace.jsonl").read_text()
    assert '"epoch"' not in raw  # no epoch values under simple_bfts


# ── §9.11 META_FILES hygiene ────────────────────────────────────────────────


def test_cache_file_registered_in_paths_and_node_report_blocklists():
    from ari.orchestrator.node_report.builder import (
        _FILES_CHANGED_BLOCKLIST_NAMES,
    )
    from ari.paths import PathManager, _TRACE_FILES

    assert GOVERNANCE_CACHE_FILENAME in PathManager.META_FILES
    assert GOVERNANCE_CACHE_FILENAME in _TRACE_FILES
    assert GOVERNANCE_CACHE_FILENAME in _FILES_CHANGED_BLOCKLIST_NAMES


# ── config parity (repo convention: defaults.yaml mirrors typed models) ────


def test_task12_config_blocks_mirror_defaults_yaml():
    defaults = yaml.safe_load(
        (
            Path(__file__).resolve().parents[1]
            / "ari" / "configs" / "defaults.yaml"
        ).read_text(encoding="utf-8")
    )
    budgets = defaults["rqgm"]["budgets"]
    typed = RQGMSpendBudgetConfig()
    assert float(budgets["max_governance_cost_usd_per_epoch"]) == (
        typed.max_governance_cost_usd_per_epoch
    )
    assert budgets["max_governance_tokens_per_epoch"] == (
        typed.max_governance_tokens_per_epoch
    )
    assert budgets["on_exhausted"] == typed.on_exhausted
    shadow = defaults["rqgm"]["shadow"]
    assert shadow["enabled"] == RQGMShadowConfig().enabled
    gov = defaults["rqgm"]["governance"]
    tgov = RQGMGovernanceConfig()
    assert gov["max_defender_calls_per_epoch"] == (
        tgov.max_defender_calls_per_epoch
    )
    assert gov["max_judge_calls_per_epoch"] == tgov.max_judge_calls_per_epoch
    assert gov["low_confidence_threshold"] == tgov.low_confidence_threshold
    assert gov["novelty_claim_threshold"] == tgov.novelty_claim_threshold
    # An absent rqgm: block stays inert (typed defaults only).
    assert ARIConfig().rqgm.budgets.max_governance_cost_usd_per_epoch == 0.0
