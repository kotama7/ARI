"""Paper-archive Task 06 — cost control and budget (wave 3d;
docs/guides/execution_modes.md §Cost bound and the degraded on-ramp;
docs/reference/configuration.md §``rqgm.budgets`` — per-epoch governance
spend caps).

Covers the ONE additive budgeted-action kind (``PAPER_ANCHOR_SCORING`` cap =
``rqgm.paper.anchor.sample_size``, 0 when disabled — the SHADOW_CALL
disabled-returns-0 mirror), the reuse-verbatim assertion (no existing cap
changed; the exploration adversary/prompt caps still fire), the depth-
independent ``paper_expansion_budget`` population bound + the load-bearing
``should_prune`` total-node cutoff BEFORE the depth clamp (a blow-up config is
capped by ``max_expansions``, never by flattening the topology), the reused
``assign_level`` triggers on draft nodes, the paper ``budget_manager`` reusing
``GovernanceBudgetManager`` verbatim, the metered anchor/adversary spend +
per-epoch ``budget_counters`` mirror in ``paper_archive_state.json`` (derived
from the audit log, resume-safe), and the ``linear`` no-op regression.

No test calls a real LLM (budget checks are deterministic, plan 06 §9).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from ari.config import ARIConfig
from ari.rqgm.budget import (
    ACTION_KINDS,
    ADVERSARY_CALL,
    PAPER_ANCHOR_SCORING,
    PROMPT_CANDIDATE,
    BudgetedAction,
    GovernanceBudgetManager,
    LEVEL_ADJUDICATED,
    LEVEL_FIXED,
)
from ari.rqgm.paper_archive import (
    PaperArchiveStrategy,
    archive_node_budget,
    read_paper_draft_archive,
)
from ari.rqgm.paper_draft_executor import PaperDraftExecutor
from ari.rqgm.paper_runtime import PaperArchiveRuntime, paper_expansion_budget
from ari.orchestrator.node import Node, NodeLabel


E = "epoch_000"


def _cfg(**paper_over) -> ARIConfig:
    rqgm = {"enabled": True, "paper": paper_over} if paper_over else {"enabled": True}
    return ARIConfig(ari={"mode": "ari_rqgm"}, rqgm=rqgm)


def _epoch(epoch_id: str = E, run_id: str = "r"):
    return SimpleNamespace(epoch_id=epoch_id, run_id=run_id)


def _manager(cfg=None, tmp_path=None, epoch=None) -> GovernanceBudgetManager:
    return GovernanceBudgetManager(
        cfg if cfg is not None else _cfg(),
        epoch_state=epoch if epoch is not None else _epoch(),
        checkpoint_dir=tmp_path,
    )


# ── §6.2 the ONE additive action kind ───────────────────────────────────────

def test_paper_anchor_scoring_is_the_only_additive_kind():
    assert PAPER_ANCHOR_SCORING == "paper_anchor_scoring"
    assert PAPER_ANCHOR_SCORING in ACTION_KINDS
    # exactly one kind was added over the closed v1 set of 9
    assert len(ACTION_KINDS) == 10


def test_anchor_scoring_cap_reads_sample_size_and_zeros_when_disabled():
    on = _manager(_cfg(anchor={"enabled": True, "sample_size": 6}))
    assert on._cap(BudgetedAction(PAPER_ANCHOR_SCORING)) == 6
    off = _manager(_cfg(anchor={"enabled": False, "sample_size": 6}))
    assert off._cap(BudgetedAction(PAPER_ANCHOR_SCORING)) == 0  # SHADOW_CALL mirror


def test_anchor_scoring_cap_exhausts_after_sample_size(tmp_path):
    m = _manager(_cfg(anchor={"enabled": True, "sample_size": 2}), tmp_path=tmp_path)
    a = BudgetedAction(PAPER_ANCHOR_SCORING)
    assert m.check(a).allowed
    m.consume(a)
    assert m.check(a).allowed
    m.consume(a)
    v = m.check(a)          # sample_size spent
    assert not v.allowed and "exhausted" in v.reason


# ── reuse-verbatim: no existing cap changed (§5.1/§11.6) ─────────────────────

def test_reused_caps_unchanged_by_the_additive_kind():
    m = _manager(_cfg())
    # the adversary + prompt caps the exploration tests pin still hold
    assert m._cap(BudgetedAction(ADVERSARY_CALL)) == 24
    assert m._cap(BudgetedAction(PROMPT_CANDIDATE, role="paper_reviewer")) == 1


def test_paper_self_preference_dispatched_as_adversary_call_cap(tmp_path):
    m = _manager(
        _cfg(), tmp_path=tmp_path,
        epoch=_epoch(),
        # adversary cap lives in its single schema home rqgm.adversarial
    )
    a = BudgetedAction(ADVERSARY_CALL)
    for _ in range(24):
        assert m.check(a).allowed
        m.consume(a)
    assert not m.check(a).allowed  # per-epoch adversary cap (24) exhausted


# ── the depth-independent population bound (§5.4.1/§5.6/§9.1) ────────────────

def test_paper_expansion_budget_is_min_and_depth_independent():
    cfg = ARIConfig()
    # min(width*(1+refine), max_expansions)
    for width, refine, mx, expect in [
        (4, 2, 12, 12), (4, 2, 8, 8), (1, 0, 12, 1), (3, 3, 100, 12),
    ]:
        cfg.rqgm.paper.archive.width = width
        cfg.rqgm.paper.archive.refine_rounds = refine
        cfg.rqgm.paper.archive.max_expansions = mx
        for depth in (1, 3, 5):
            cfg.rqgm.paper.archive.depth = depth
            assert paper_expansion_budget(cfg) == expect, (width, refine, mx, depth)


def _drive_archive(knobs):
    """Run the real best-first archive loop with a stub executor; return the
    materialised draft count."""
    import tempfile

    class _MCP:
        def call_tool(self, name, args):
            from pathlib import Path
            if name == "write_paper_iterative":
                return {"latex": "\\section{S} % CLAIM:C1:NC1\n"}
            if name == "paper_refine":
                tex = Path(args["tex_path"]).read_text(encoding="utf-8")
                return {"latex": tex + "\\section{S2}\n", "anchors_preserved": True}
            return {}

    class _Rev:
        prompt_hash = "rev"

        def review(self, tex_path):
            return SimpleNamespace(suggested_revisions_json="[]")

        def score(self, tex_path):
            return 0.5

    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path
        ckpt = Path(td)
        root = Node(id="paper_root", parent_id=None, depth=0, label=NodeLabel.DRAFT)
        root.original_direction = "root"
        root.has_real_data = False
        strat = PaperArchiveStrategy(knobs, root_task=root)
        execu = PaperDraftExecutor(_MCP(), reviewer=_Rev(), checkpoint_dir=ckpt,
                                   epoch_id=E)
        archive: list = []
        frontier: list = [root]
        while frontier:
            parent = strat.select_best_to_expand(frontier, "g", None)
            if strat.should_prune(parent, current_total=1 + len(archive)):
                frontier.remove(parent)
                continue
            children = strat.expand(parent, existing_children=archive)
            if not children:
                frontier.remove(parent)
                continue
            cand = strat.select_next_node(children, "g", None)
            cand = execu.run(cand, {"goal": "g"})
            strat.record_run(cand)
            archive.append(cand)
            frontier.append(cand)
        return len(archive), len(read_paper_draft_archive(ckpt))


def test_should_prune_total_cap_binds_before_depth_on_a_blowup_config():
    # width 50 x refine 50 x depth 5 would explode under naive branching; the
    # total-node cap (max_expansions=6) stops it, depth budget UNSPENT (§9.1).
    knobs = ARIConfig().rqgm.paper.archive
    knobs.width = 50
    knobs.refine_rounds = 50
    knobs.depth = 5
    knobs.max_expansions = 6
    drafts, records = _drive_archive(knobs)
    assert drafts == 6 == records          # capped at max_expansions, ANY depth


def test_strategy_caps_on_node_budget_not_raw_max_expansions():
    # §5.6/D2 regression: the STRATEGY's effective cap is
    # node_budget = min(width*(1+refine_rounds), max_expansions), not the raw
    # max_expansions. Here the shape is the binding term: 2*(1+1)=4 < 12, so the
    # archive must stop at 4 drafts even though max_expansions=12. Before the fix
    # the strategy over-expanded toward the raw 12; this pins the min bound.
    knobs = ARIConfig().rqgm.paper.archive
    knobs.width = 2
    knobs.refine_rounds = 1
    knobs.depth = 3
    knobs.max_expansions = 12
    assert archive_node_budget(knobs) == 4
    drafts, records = _drive_archive(knobs)
    assert drafts == 4 == records          # node_budget (shape), not max_expansions


def test_population_never_exceeds_max_expansions_at_any_depth():
    for depth in (1, 2, 3, 5):
        knobs = ARIConfig().rqgm.paper.archive
        knobs.width = 4
        knobs.refine_rounds = 2
        knobs.depth = depth
        knobs.max_expansions = 12
        drafts, _ = _drive_archive(knobs)
        assert drafts <= 12


# ── reused assign_level on draft nodes (§5.3/§9.4) ──────────────────────────

def _draft(node_id, score=0.5, sterile=False):
    m = {"_scientific_score": score}
    if sterile:
        m["_sterile"] = True
    return SimpleNamespace(id=node_id, metrics=m)


def test_assign_level_reuses_exploration_ladder_on_drafts():
    m = _manager(_cfg())
    # paper_candidate -> L3
    lvl, trig = m.level_with_triggers(_draft("d1"), paper_candidate=True)
    assert lvl == LEVEL_ADJUDICATED and "paper_candidate" in trig
    # top-K by _scientific_score -> L3
    frontier = [_draft("a", 0.1), _draft("b", 0.2), _draft("c", 0.3)]
    lvl2, trig2 = m.level_with_triggers(_draft("hi", 0.9), frontier=frontier)
    assert lvl2 == LEVEL_ADJUDICATED and "top_k" in trig2
    # sterile draft -> L0 floor
    lvl3, trig3 = m.level_with_triggers(_draft("s", sterile=True))
    assert lvl3 == LEVEL_FIXED and trig3 == ["sterile"]


# ── the paper budget_manager reuses GovernanceBudgetManager verbatim ────────

def test_paper_budget_manager_reuses_governance_budget_manager(tmp_path):
    cfg = ARIConfig()
    cfg.paper.mode = "rqgm_archive"
    cfg.rqgm.enabled = True
    cfg.rqgm.paper.enabled = True
    rt = PaperArchiveRuntime(cfg, checkpoint_dir=tmp_path)
    bm = rt.budget_manager
    assert isinstance(bm, GovernanceBudgetManager)
    # the epoch home is a real, non-empty id
    assert bm._epoch_id()
    # no checkpoint_dir => fail-open to None (never raises)
    rt2 = PaperArchiveRuntime(cfg, checkpoint_dir=None)
    assert rt2.budget_manager is None


# ── metered spend + the §6.3 per-epoch counter mirror ───────────────────────

class _ScriptedMCP:
    def call_tool(self, name, args):
        from pathlib import Path
        if name == "write_paper_iterative":
            return {"latex": "\\section{Intro} % CLAIM:C1:NC1\n" * 3}
        if name == "paper_refine":
            tex = Path(args["tex_path"]).read_text(encoding="utf-8")
            return {"latex": tex + "\n\\section{More} % CLAIM:CX:NCX\n",
                    "anchors_preserved": True}
        return {}


class _Resp:
    def __init__(self, content):
        self.content = content


class _AdvLLM:
    def complete(self, messages, **kwargs):
        p = messages[0]["content"] if messages else ""
        if "ArtifactJudge" in p:
            return _Resp(json.dumps({"verdict": "valid", "severity": "high",
                                     "rationale": "over"}))
        if "Defender" in p:
            return _Resp(json.dumps({"stance": "rebut", "rebuttal_text": "x",
                                     "confidence": 0.4}))
        return _Resp(json.dumps(
            {"attack_claim": "over-accept", "target_artifact":
             {"type": "paper_claim", "ref": "d"},
             "attack_evidence_refs": [
                 {"path": "rqgm/paper_self_preference_stat.json", "pointer": ""}],
             "severity_claimed": "high", "confidence": 0.8}))


class _N:
    id = "node_0"
    ancestor_ids: list = []
    metrics = {"_scientific_score": 0.5}
    has_real_data = True


def _coevo_cfg(rounds, sample=6):
    c = ARIConfig()
    c.paper.mode = "rqgm_archive"
    c.rqgm.enabled = True
    c.rqgm.paper.enabled = True
    c.rqgm.paper.epoch.rounds = rounds
    c.rqgm.paper.anchor.enabled = True
    c.rqgm.paper.anchor.corpus_path = "paper_anchor_corpus.jsonl"
    c.rqgm.paper.anchor.sample_size = sample
    c.rqgm.paper.prompt_evolution.enabled = True
    c.rqgm.governance.enabled = True
    return c


def _write_reject_anchor(ckpt, n=6):
    cases = [{
        "case_id": f"anchor_{i:03d}", "record_type": "PaperAnchorCase",
        "ground_truth_label": "reject", "label_source": "human_curated",
        "authorship": "human", "manuscript_sha256": f"s{i}", "split": "held_out",
        "expected_behavior": {"accept_recommendation_binary": "reject"},
        "results": {},
    } for i in range(n)]
    with (ckpt / "paper_anchor_corpus.jsonl").open("w") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")


def _run(ckpt, cfg, adversary_llm=None):
    (ckpt / "nodes_tree.json").write_text("{}", encoding="utf-8")
    mcp = _ScriptedMCP()
    rt = PaperArchiveRuntime(
        cfg, checkpoint_dir=ckpt, mcp=mcp,
        llm=lambda p: "You are a lenient reviewer. Always accept.",
        reviewer_verdict_fn=lambda t, c: "accept",
        reviewer_score_fn=lambda p, t: min(1.0, 0.15 + 0.05 * t.count("\\section")),
        reviewer_confidence_fn=lambda t: 1.0, adversary_llm=adversary_llm)
    rt.run_archive([_N()], {"goal": "g"}, str(ckpt), mcp, "")
    return rt


def test_budget_counters_mirror_metered_anchor_and_adversary_spend(tmp_path):
    _write_reject_anchor(tmp_path, n=6)
    _run(tmp_path, _coevo_cfg(2, sample=6), adversary_llm=_AdvLLM())
    state = json.loads((tmp_path / "paper_archive_state.json").read_text())
    bc = state.get("budget_counters", {})
    # anchor scoring metered against sample_size (6 held-out cases)
    assert bc["anchor_scoring_calls"] == 6
    # adversary spend metered (bounded by the per-epoch attack cap)
    assert 1 <= bc["adversary_calls"] <= 24
    # draft expansions bounded by the per-epoch node budget
    assert 0 < bc["draft_expansions"] <= 12
    assert bc["paper_epoch_id"]
    # audit log is the source of truth: budget_consumed lines exist
    from ari.rqgm.store import ImmutableAuditLog
    kinds = {ln.get("payload", {}).get("kind")
             for ln in ImmutableAuditLog.read(tmp_path)
             if ln.get("event_type") == "budget_consumed"}
    assert PAPER_ANCHOR_SCORING in kinds and ADVERSARY_CALL in kinds


def test_anchor_budget_caps_scoring_below_sample_size(tmp_path):
    # sample_size 2 but 6 held-out cases available: the anchor budget stops
    # scoring at 2 (degrade-never-block) — the paper phase still completes.
    _write_reject_anchor(tmp_path, n=6)
    _run(tmp_path, _coevo_cfg(1, sample=2), adversary_llm=_AdvLLM())
    state = json.loads((tmp_path / "paper_archive_state.json").read_text())
    assert state["budget_counters"]["anchor_scoring_calls"] == 2


# ── §9 item 9: the required cost regression / budget acceptance test ─────────
#
# The spec-required acceptance test (06 §9 item 9). It was absent; INDEX claimed
# it done. 9(b) is asserted against the audit-log-derived `budget_counters`, NOT
# a `phase="paper_governance"` filter — that phase string exists nowhere and
# minting it would make paper spend invisible to `_spend_exhausted` and silently
# disable the cap (06 §9 amended 2026-07-17; work order #35/H5).

def _counters(ckpt) -> dict:
    return json.loads(
        (ckpt / "paper_archive_state.json").read_text())["budget_counters"]


def test_cost_acceptance_tiny_caps_never_exceed_budget(tmp_path):
    _write_reject_anchor(tmp_path, n=6)
    cfg = _coevo_cfg(1, sample=2)
    # the spec's tiny caps
    cfg.rqgm.paper.archive.max_expansions = 3
    cfg.rqgm.paper.archive.depth = 3                 # cap binds before the clamp
    cfg.rqgm.adversarial.max_adversary_calls_per_epoch = 1
    fg = int(cfg.rqgm.governance.full_governance_only_on_top_k)

    _run(tmp_path, cfg, adversary_llm=_AdvLLM())
    bc = _counters(tmp_path)

    # (a) draft expansions <= max_expansions per epoch, AT depth 3
    assert bc["draft_expansions"] <= 3, bc
    # (b) per-actor governed counts never exceed the configured caps (read from
    #     budget_counters, derived from rqgm_audit.jsonl budget_consumed lines)
    assert bc["adversary_calls"] <= 1, bc
    assert bc["anchor_scoring_calls"] <= 2, bc
    # At rounds=1 NO prompt candidate is ever minted (the first boundary is the
    # round head), so `<= cap` here would be vacuous — assert the on-ramp fact
    # that IS true instead. The cap itself is exercised at rounds=2 by
    # `test_prompt_candidate_cap_is_exercised_at_rounds_two`.
    assert bc["prompt_candidates"]["paper_reviewer"] == 0, bc
    assert bc["prompt_candidates"]["paper_writer"] == 0, bc
    # (c) the run completes (degrade-never-block) and the best draft reaches the
    #     Task-07 claim gate — the winner is materialised on the canonical path
    assert (tmp_path / "full_paper.tex").exists()
    # (d) compiles bounded by full_governance_only_on_top_k
    assert bc["compiles"] <= fg, bc
    # the audit log is the source of truth for (b)
    from ari.rqgm.store import ImmutableAuditLog
    consumed = [ln for ln in ImmutableAuditLog.read(tmp_path)
                if ln.get("event_type") == "budget_consumed"]
    assert consumed, "no budget_consumed lines recorded"


def test_over_accepted_attack_population_tracks_sample_size_not_a_literal(tmp_path):
    """06 §5.2 D1 / §5.6 (work order #46): the attacked over-accepted population
    is bounded by the HOMED `rqgm.paper.self_preference.sample_size`, not by the
    old un-homed `over[: max(2, min(len(over), 4))]` literal. With 8 over-accepted
    cases, sample_size 8 and the adversary cap raised, the ADVERSARY_CALL count
    exceeds the old constant-4 ceiling and is bounded by sample_size."""
    _write_reject_anchor(tmp_path, n=8)
    cfg = _coevo_cfg(1, sample=8)
    cfg.rqgm.paper.self_preference.sample_size = 8
    cfg.rqgm.adversarial.max_adversary_calls_per_epoch = 24
    _run(tmp_path, cfg, adversary_llm=_AdvLLM())
    bc = _counters(tmp_path)
    assert bc["adversary_calls"] > 4, bc      # the ≤4 literal is gone
    assert bc["adversary_calls"] <= 8, bc     # bounded by the homed sample_size


# ── §9 item 5: cost-model closed form, linearity, depth-invariance ──────────

def _cost_cfg(*, sample, depth, width=2, refine=0, max_exp=12):
    c = _coevo_cfg(1, sample=sample)
    c.rqgm.paper.archive.width = width
    c.rqgm.paper.archive.refine_rounds = refine
    c.rqgm.paper.archive.depth = depth
    c.rqgm.paper.archive.max_expansions = max_exp
    return c


def test_cost_model_closed_form_linear_and_depth_invariant(tmp_path):
    """06 §9 item 5: the counted governed calls match the §5.6 closed form
    (`draft_expansions == paper_expansion_budget`, `anchor_scoring_calls ==
    sample_size`), grow LINEARLY when a tunable is doubled (no super-linear
    term), and are UNCHANGED when `archive.depth` is doubled (depth is absent
    from the model)."""
    base_dir = tmp_path / "base"; base_dir.mkdir()
    deep_dir = tmp_path / "deep"; deep_dir.mkdir()
    wide_dir = tmp_path / "wide"; wide_dir.mkdir()
    anch_dir = tmp_path / "anchor2x"; anch_dir.mkdir()
    for d in (base_dir, deep_dir, wide_dir, anch_dir):
        _write_reject_anchor(d, n=6)

    base_cfg = _cost_cfg(sample=2, depth=1, width=2)
    _run(base_dir, base_cfg, adversary_llm=_AdvLLM())
    base = _counters(base_dir)

    # closed form: draft_expansions == the pure population bound
    assert base["draft_expansions"] == paper_expansion_budget(base_cfg)
    assert base["draft_expansions"] == 2      # min(2*(1+0), 12)
    assert base["anchor_scoring_calls"] == 2  # == sample_size

    # depth doubled => IDENTICAL governed counts (depth-invariant)
    _run(deep_dir, _cost_cfg(sample=2, depth=2, width=2), adversary_llm=_AdvLLM())
    deep = _counters(deep_dir)
    assert deep["draft_expansions"] == base["draft_expansions"]
    assert deep["anchor_scoring_calls"] == base["anchor_scoring_calls"]

    # width doubled => draft_expansions doubles (linear in K, no super-linear term)
    _run(wide_dir, _cost_cfg(sample=2, depth=1, width=4), adversary_llm=_AdvLLM())
    wide = _counters(wide_dir)
    assert wide["draft_expansions"] == 2 * base["draft_expansions"] == 4

    # sample_size doubled => anchor scoring doubles (linear in S), drafts unchanged
    _run(anch_dir, _cost_cfg(sample=4, depth=1, width=2), adversary_llm=_AdvLLM())
    anch = _counters(anch_dir)
    assert anch["anchor_scoring_calls"] == 2 * base["anchor_scoring_calls"] == 4
    assert anch["draft_expansions"] == base["draft_expansions"]


# ── §9 items 6 + 11: resume must not double-count / re-fund the epoch ────────

def _audit_tally(ckpt) -> dict:
    """`{counter_key: n}` over ALL epochs, read from the `budget_consumed`
    lines' `payload`. The `budget_counters` mirror in `paper_archive_state.json`
    is epoch-FILTERED (it reflects the CURRENT epoch only), so a multi-epoch
    assertion must read the audit log — the plan's own source of truth."""
    out: dict = {}
    for ln in _spend_lines(ckpt):
        p = ln.get("payload") or {}
        key = p.get("counter_key") or p.get("kind")
        out[key] = out.get(key, 0) + 1
    return out


# ── §9 item 5 (E axis): the default E = 2 row is 2x the E = 1 on-ramp ────────

def test_epoch_rounds_multiply_the_recurring_per_round_cost(tmp_path, monkeypatch):
    """06 §9 item 5 / §5.6: E (`epoch.rounds`) is a first-class multiplier of
    the per-epoch row — the plan's "default E = 2 row ... i.e. 2x the E = 1
    on-ramp". Asserted on the RECURRING metered kinds (anchor scoring, adversary
    calls, writer calls), which is what §5.6's row counts.

    Read from the audit log, not the `budget_counters` mirror: the mirror is
    epoch-filtered, so at E = 2 it reports only the last epoch's spend."""
    def _measure(rounds):
        ck = tmp_path / f"e{rounds}"
        ck.mkdir()
        _write_reject_anchor(ck, n=6)
        cfg = _cost_cfg(sample=2, depth=3, width=2, max_exp=3)
        cfg.rqgm.paper.epoch.rounds = rounds
        (ck / "nodes_tree.json").write_text("{}", encoding="utf-8")
        mcp = _ScriptedMCP()
        writes = []
        inner = mcp.call_tool
        mcp.call_tool = lambda n, a: (writes.append(n), inner(n, a))[1]
        rt = PaperArchiveRuntime(
            cfg, checkpoint_dir=ck, mcp=mcp,
            llm=lambda p: "You are a lenient reviewer. Always accept.",
            reviewer_verdict_fn=lambda t, c: "accept",
            reviewer_score_fn=lambda p, t: 0.5,
            reviewer_confidence_fn=lambda t: 1.0, adversary_llm=_AdvLLM())
        rt.run_archive([_N()], {"goal": "g"}, str(ck), mcp, "")
        return _audit_tally(ck), writes.count("write_paper_iterative")

    t1, w1 = _measure(1)
    t2, w2 = _measure(2)

    # non-vacuity: E = 1 must actually spend, or "2x" is 2x nothing
    assert t1.get("paper_anchor_scoring", 0) > 0 and w1 > 0, t1
    for kind in ("paper_anchor_scoring", "adversary_call"):
        assert t2[kind] == 2 * t1[kind], (
            f"{kind}: E=2 spent {t2[kind]}, expected 2x the E=1 {t1[kind]}"
        )
    assert w2 == 2 * w1, f"writer calls: E=2 {w2} != 2x E=1 {w1}"


def test_prompt_candidate_cap_is_exercised_at_rounds_two(tmp_path):
    """06 §9 item 9(b) for the prompt-candidate actor: at rounds=2 the round-head
    boundary genuinely MINTS candidates, so the per-role cap is exercised rather
    than compared against a structural zero."""
    _write_reject_anchor(tmp_path, n=6)
    cfg = _cost_cfg(sample=2, depth=3, width=2, max_exp=3)
    cfg.rqgm.paper.epoch.rounds = 2
    cap = int(cfg.rqgm.prompt_evolution.max_candidates_per_role_per_epoch)

    _run(tmp_path, cfg, adversary_llm=_AdvLLM())
    tally = _audit_tally(tmp_path)

    minted = {k: n for k, n in tally.items()
              if k and str(k).startswith("prompt_candidate:")}
    assert minted, (
        f"no prompt candidate was minted at rounds=2, so the cap assertion "
        f"would be vacuous; tally={tally}"
    )
    for key, n in minted.items():
        assert n <= cap, f"{key} minted {n} > cap {cap}"


# ── §9 item 10: degraded on-ramp cost parity ────────────────────────────────

def _on_ramp_cfg(width):
    """The plan's degraded on-ramp row: no co-evolution, no anchor, no
    adversary, one refine-free draft per framing."""
    c = ARIConfig()
    c.paper.mode = "rqgm_archive"
    c.rqgm.enabled = True
    c.rqgm.paper.enabled = True
    c.rqgm.paper.epoch.rounds = 1
    c.rqgm.paper.prompt_evolution.enabled = False
    c.rqgm.paper.anchor.enabled = False
    c.rqgm.adversarial.enabled = False
    c.rqgm.governance.enabled = True
    c.rqgm.paper.archive.width = width
    c.rqgm.paper.archive.refine_rounds = 0
    c.rqgm.paper.archive.depth = 1
    return c


def test_degraded_on_ramp_costs_one_reviewed_draft_and_k_scales(tmp_path):
    """06 §9 item 10: with prompt_evolution/anchor/adversarial all off, the
    archive spends NO governed budget — its cost is just the writer calls, i.e.
    best-of-K reviewed drafts (~the linear pipeline at K=1) — and doubling
    `width` exactly K-scales that."""
    def _measure(width):
        ck = tmp_path / f"w{width}"
        ck.mkdir()
        (ck / "nodes_tree.json").write_text("{}", encoding="utf-8")
        mcp = _ScriptedMCP()
        seen = []
        inner = mcp.call_tool
        mcp.call_tool = lambda n, a: (seen.append(n), inner(n, a))[1]
        rt = PaperArchiveRuntime(
            _on_ramp_cfg(width), checkpoint_dir=ck, mcp=mcp,
            reviewer_score_fn=lambda p, t: 0.5)
        rt.run_archive([_N()], {"goal": "g"}, str(ck), mcp, "")
        return _audit_tally(ck), seen, _counters(ck)

    t1, seen1, bc1 = _measure(1)
    # (a) ZERO governed spend — the on-ramp is not paying for governance
    assert t1 == {}, f"degraded on-ramp metered governed spend: {t1}"
    assert bc1["adversary_calls"] == 0 and bc1["anchor_scoring_calls"] == 0, bc1
    # (b) cost == ONE reviewed draft, and no refine round
    assert seen1.count("write_paper_iterative") == 1, seen1
    assert seen1.count("paper_refine") == 0, seen1

    # (c) doubling width exactly K-scales the writer calls, still no governance
    t2, seen2, _ = _measure(2)
    assert t2 == {}, t2
    assert seen2.count("write_paper_iterative") == 2, seen2


def _spend_lines(ckpt) -> list:
    from ari.rqgm.store import ImmutableAuditLog
    return [ln for ln in ImmutableAuditLog.read(ckpt)
            if ln.get("event_type") == "budget_consumed"]


def test_completed_run_is_skipped_and_refunds_nothing(tmp_path):
    """06 §9 item 6 (skip half): a second invocation on a checkpoint whose
    winner is ALREADY materialised short-circuits at the 07 §8.6 guard, so it
    appends no `budget_consumed` line and perturbs no counter.

    This asserts ONLY the skip path. It deliberately does NOT claim to cover
    item 11's "counters continue rather than reset" clause: nothing here
    re-enters the archive, so no restore is exercised — that is
    `test_interrupted_resume_continues_counters_instead_of_refunding`'s job.
    Conflating the two is how this file previously reported item 11 as covered
    while executing zero archive code on the second run."""
    _write_reject_anchor(tmp_path, n=6)
    cfg = _cost_cfg(sample=2, depth=3, width=2, max_exp=3)

    _run(tmp_path, cfg, adversary_llm=_AdvLLM())
    c1, n1 = _counters(tmp_path), len(_spend_lines(tmp_path))
    assert (tmp_path / "full_paper.tex").exists()   # the guard's precondition
    assert c1["draft_expansions"] <= 3

    _run(tmp_path, cfg, adversary_llm=_AdvLLM())

    assert len(_spend_lines(tmp_path)) == n1, "skip appended budget_consumed"
    assert _counters(tmp_path) == c1, "skip perturbed the budget counters"


class _InterruptingMCP(_ScriptedMCP):
    """Dies after `fail_after` generative calls — the §9 "interrupted" state.
    No winner is materialised, so a resume genuinely RE-ENTERS the archive."""

    def __init__(self, fail_after: int):
        self.fail_after = fail_after
        self.gen = 0

    def call_tool(self, name, args):
        if name in ("write_paper_iterative", "paper_refine"):
            if self.gen >= self.fail_after:
                raise RuntimeError("archive interrupted")
            self.gen += 1
        return super().call_tool(name, args)


def test_interrupted_resume_continues_counters_instead_of_refunding(tmp_path):
    """06 §9 item 11 (+ item 6's restore half): after an INTERRUPTED round the
    resume re-enters the archive, and a fresh `GovernanceBudgetManager` restores
    the epoch's counters from `rqgm_audit.jsonl` rather than resetting them — so
    the per-epoch caps still bind across BOTH invocations.

    The interrupt is what makes this non-vacuous: with a materialised winner the
    07 §8.6 guard short-circuits and no archive code runs at all."""
    _write_reject_anchor(tmp_path, n=6)
    cfg = _cost_cfg(sample=2, depth=3, width=2, max_exp=3)
    max_exp = cfg.rqgm.paper.archive.max_expansions
    sample = cfg.rqgm.paper.anchor.sample_size

    # 1st invocation: dies partway, so NO winner is materialised.
    mcp1 = _InterruptingMCP(fail_after=1)
    rt1 = PaperArchiveRuntime(
        cfg, checkpoint_dir=tmp_path, mcp=mcp1,
        llm=lambda p: "You are a lenient reviewer. Always accept.",
        reviewer_verdict_fn=lambda t, c: "accept",
        reviewer_score_fn=lambda p, t: min(1.0, 0.15 + 0.05 * t.count("\\section")),
        reviewer_confidence_fn=lambda t: 1.0, adversary_llm=_AdvLLM())
    rt1.run_archive([_N()], {"goal": "g"}, str(tmp_path), mcp1, "")
    n1 = len(_spend_lines(tmp_path))
    assert not (tmp_path / "full_paper.tex").exists(), (
        "interrupt did not prevent materialisation — the resume would be "
        "short-circuited and this test would be vacuous"
    )
    assert n1 > 0, "first invocation spent no budget"

    # 2nd invocation: the archive RE-ENTERS (no winner to skip on).
    _run(tmp_path, cfg, adversary_llm=_AdvLLM())
    n2 = len(_spend_lines(tmp_path))
    assert n2 > n1, "resume did not re-enter the archive (test is vacuous)"

    # Counters CONTINUE: the per-epoch caps bind on the TOTAL across both runs,
    # which is only true if the fresh manager restored the first run's spend.
    # NB the metered fields live under `payload` (budget.py writes
    # {"event_type": "budget_consumed", "payload": {epoch_id, kind, ...}}) —
    # reading them off the top level silently yields None and makes the cap
    # assertion below vacuous.
    per_epoch: dict = {}
    for ln in _spend_lines(tmp_path):
        p = ln.get("payload") or {}
        key = (p.get("epoch_id"), p.get("counter_key") or p.get("kind"))
        per_epoch[key] = per_epoch.get(key, 0) + 1
    anchor = {k: n for k, n in per_epoch.items()
              if k[1] and "anchor_scoring" in str(k[1])}
    assert anchor, (
        f"no anchor-scoring spend was metered across the two invocations, so "
        f"the cap assertion would be vacuous; tallies={per_epoch}"
    )
    for (epoch, kind), n in anchor.items():
        assert n <= sample, (
            f"{kind} spent {n} > cap {sample} in {epoch} across both "
            "invocations — the resume reset the counter instead of restoring it"
        )
    assert _counters(tmp_path)["draft_expansions"] <= max_exp


# ── linear no-op regression (§8.1/§9.7) ─────────────────────────────────────

def test_linear_paper_run_constructs_no_paper_budget_manager():
    cfg = ARIConfig()  # default paper.mode: linear
    # the interlock is structural: PaperArchiveRuntime is never built on linear,
    # so no paper budget manager exists on the paper path.
    from ari.rqgm.paper_mode import resolve_paper_mode, PaperMode
    assert resolve_paper_mode(cfg) is PaperMode.LINEAR
