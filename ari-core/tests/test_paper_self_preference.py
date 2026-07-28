"""Paper-archive Task 05 — the paper_self_preference adversary (wave 3c,
docs/plans/ari_rqgm_paper/05 §9).

Covers the deterministic pre-signal, the AI-vs-human margin statistic + its
audit artifact, the eighth adversary's record vocabulary + Task-15 target
binding to ``paper_reviewer_v1``, the paper-mode-gated founding rows (the
adversary is a registered, SANCTIONABLE governed component — P3), exploration/
linear byte-identity, the META_FILES / node-report registration of the stat
file, and — the anti-inertness proof — the ORGANIC impeachment of an
always-accept reviewer through the REAL adversary -> Defender -> ArtifactJudge
round (NOT the deleted forged bridge), plus the anchor-removed / no-governance
negative controls.
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from ari.config import ARIConfig
from ari.rqgm.adversarial.engine import (
    ADVERSARY_SPECS,
    ArtifactBundle,
    _pre_paper_self_preference,
    build_artifact_bundle,
)
from ari.rqgm.adversarial.records import (
    ADVERSARY_TYPES,
    _FAILURE_PATTERNS,
)
from ari.rqgm.adversarial.round import _AFFECTED_ROLES_BY_TYPE


#: A constitutionally-VALID ``paper_reviewer`` candidate instruction: carries
#: both §5.4 clauses verbatim, so the candidate constitutional gate
#: (``prompt_evolution.role_instruction_constraint_failures``, wired into
#: ``_paper_candidate_evaluator``) does NOT drop it. The board-scoring tests
#: below exercise the replay/anchor boards, not that gate — the gate has its own
#: coverage (``test_candidate_missing_a_54_clause_is_dropped_before_scoring``).
_VALID_REVIEWER_TEXT = (
    "You are an expert paper reviewer. Do not override the claim-evidence hard "
    "gate. Do not directly modify frontier scores."
)


# ── the deterministic pre-signal (§5.1) ─────────────────────────────────────

def _accepted_bundle(**kw):
    base = dict(node_id="d1", paper_candidate=True, reviewer_accept_score=0.9,
                accept_threshold=0.6, self_preference_margin=0.0,
                self_preference_threshold=0.1)
    base.update(kw)
    return ArtifactBundle(**base)


def test_pre_signal_inert_off_paper_and_for_unaccepted():
    # not a paper candidate -> []
    assert _pre_paper_self_preference(_accepted_bundle(paper_candidate=False)) == []
    # not paper-scored (None) -> []
    assert _pre_paper_self_preference(
        _accepted_bundle(reviewer_accept_score=None)) == []
    # below the accept threshold -> []
    assert _pre_paper_self_preference(
        _accepted_bundle(reviewer_accept_score=0.5)) == []
    # accepted but NO over-acceptance signal (no gate finding, margin below
    # threshold) -> [] (zero LLM cost)
    assert _pre_paper_self_preference(_accepted_bundle()) == []


def test_pre_signal_fires_on_gate_finding():
    b = _accepted_bundle(gate_findings=({"kind": "missing_evidence"},))
    refs = _pre_paper_self_preference(b)
    assert refs and all(r.path for r in refs)


def test_pre_signal_fires_on_authorship_margin():
    b = _accepted_bundle(self_preference_margin=0.5)
    refs = _pre_paper_self_preference(b)
    assert refs
    assert any(r.path == "rqgm/paper_self_preference_stat.json" for r in refs)


def test_pre_signal_fires_on_per_draft_anchor_case_citing_that_case():
    """§5.1 clause 3 bullet 3 (amended 2026-07-17): the DIRECT per-draft anchor
    over-acceptance fires with the population margin at its honest 0.0 (an
    all-human corpus), and cites the anchor CASE — never the population
    statistic, whose artifact would read `{"margin": 0.0}` and refute the very
    trigger it was offered as evidence for."""
    b = _accepted_bundle(anchor_over_accepted_case="anchor_003")
    refs = _pre_paper_self_preference(b)
    assert [(r.path, r.pointer) for r in refs] == [
        ("paper_anchor_corpus.jsonl", "anchor_003")
    ]
    assert not any(r.path == "rqgm/paper_self_preference_stat.json"
                   for r in refs)


def test_over_accepted_node_stamps_the_real_population_margin():
    """The regression for the `max(population_margin, 1.0)` fabrication: a
    self-preference margin is a RATE in [0,1], so the max() was ALWAYS 1.0 and
    discarded the computed statistic unconditionally. `_self_preference_margin`
    now carries what `compute_self_preference_margin` returned, by value, and
    agrees with the `paper_self_preference_stat.json` the ref cites."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    node = PaperArchiveRuntime._over_accepted_node(
        {"case_id": "anchor_003"}, epoch_id="epoch_000", accept_threshold=0.6,
        margin_threshold=0.1, population_margin=0.0)
    assert node.metrics["_self_preference_margin"] == 0.0     # NOT 1.0
    assert node.metrics["_paper_anchor_over_accepted_case"] == "anchor_003"
    # a genuinely AI-preferring population is passed through unchanged
    ai = PaperArchiveRuntime._over_accepted_node(
        {"case_id": "a1"}, epoch_id="e", accept_threshold=0.6,
        margin_threshold=0.1, population_margin=0.5)
    assert ai.metrics["_self_preference_margin"] == 0.5
    # and the two signals then cite two different, correct artifacts
    refs = _pre_paper_self_preference(build_artifact_bundle(
        NS(id=ai.id, work_dir="", metrics=ai.metrics)))
    assert {r.path for r in refs} == {"rqgm/paper_self_preference_stat.json",
                                      "paper_anchor_corpus.jsonl"}


def test_bundle_paper_fields_default_safe_and_read_from_metrics():
    # An exploration node (no reserved paper keys) -> fail-safe defaults, so the
    # bundle is byte-identical to today's and the eighth type never fires.
    from types import SimpleNamespace

    plain = build_artifact_bundle(SimpleNamespace(id="n", metrics={}, work_dir=""))
    assert plain.paper_candidate is False
    assert plain.reviewer_accept_score is None
    assert _pre_paper_self_preference(plain) == []
    # A paper node carrying the reserved keys populates the fields.
    paper = build_artifact_bundle(SimpleNamespace(
        id="d", work_dir="",
        metrics={"_scientific_score": 1.0,
                 "_paper_self_preference_candidate": True,
                 "_reviewer_accept_score": 0.9,
                 "_self_preference_margin": 0.5}))
    assert paper.paper_candidate and paper.reviewer_accept_score == 0.9
    assert _pre_paper_self_preference(paper)


# ── the margin statistic + audit artifact (§5.3/§6) ─────────────────────────

class _Reviewer:
    prompt_hash = "rev"

    def __init__(self, accepts_all=True):
        self._accepts_all = accepts_all

    def anchor_verdict(self, case):
        return "accept" if self._accepts_all else case.get("ground_truth_label")


def _case(cid, label="reject", authorship="human"):
    return {"case_id": cid, "ground_truth_label": label, "authorship": authorship,
            "expected_behavior": {"accept_recommendation_binary": label}}


def test_over_accepted_cases_are_reject_labelled_accepts():
    from ari.rqgm.paper_self_preference import over_accepted_cases

    cases = [_case("a"), _case("b"), _case("c", label="accept")]
    over = over_accepted_cases(_Reviewer(accepts_all=True), cases)
    ids = {c["case_id"] for c in over}
    assert ids == {"a", "b"}  # the reject-labelled ones the reviewer accepted
    # a strict reviewer over-accepts nothing
    assert over_accepted_cases(_Reviewer(accepts_all=False), cases) == []


def test_margin_zero_without_authorship_split_and_writes_stat(tmp_path):
    from ari.rqgm.paper_self_preference import compute_self_preference_margin

    cases = [_case(f"h{i}", authorship="human") for i in range(4)]
    m = compute_self_preference_margin(
        _Reviewer(), cases, sample_size=4, epoch_id="epoch_000",
        checkpoint_dir=tmp_path)
    assert m == 0.0  # all-human -> no AI/human split
    stat = tmp_path / "rqgm" / "paper_self_preference_stat.json"
    assert stat.exists()
    payload = json.loads(stat.read_text())
    assert payload["margin"] == 0.0 and payload["epoch_id"] == "epoch_000"


def test_margin_positive_when_reviewer_prefers_ai(tmp_path):
    from ari.rqgm.paper_self_preference import compute_self_preference_margin

    class _AiLenient:
        prompt_hash = "rev"

        def anchor_verdict(self, case):
            return "accept" if case.get("authorship") == "ai" else "reject"

    cases = ([_case(f"ai{i}", authorship="ai") for i in range(3)]
             + [_case(f"hu{i}", authorship="human") for i in range(3)])
    m = compute_self_preference_margin(
        _AiLenient(), cases, sample_size=6, checkpoint_dir=tmp_path)
    assert m == pytest.approx(1.0)  # accepts every AI, rejects every human


# ── record vocabulary + the abstract view (§5.4/§6) ─────────────────────────

def test_type_is_a_closed_member_and_dispatchable():
    assert "paper_self_preference" in ADVERSARY_TYPES
    assert "paper_self_preference" in ADVERSARY_SPECS
    spec = ADVERSARY_SPECS["paper_self_preference"]
    assert spec.default_target_type == "paper_claim"
    assert spec.prompt_key == "rqgm/adversary_paper_self_preference"


def test_failure_summary_resolves_paper_roles():
    from ari.rqgm.adversarial.records import (
        ValidatedAttackRecord,
        build_failure_summary,
    )

    assert "paper_self_preference" in _FAILURE_PATTERNS
    rec = ValidatedAttackRecord(
        record_id="v", case_type="paper_self_preference", raw_attack_id="a",
        judgment_id="j",
        expected_behavior={"paper_reviewer": "reject", "paper_writer": "support"})
    fs = build_failure_summary(rec)
    assert fs.affected_roles == ("paper_reviewer", "paper_writer")
    assert "raw_attack" not in fs.to_dict()  # contamination-safe


def test_affected_roles_row_names_paper_reviewer_and_writer():
    # The over-accepted-AND-unfaithful draft has TWO culpable components (§5.1,
    # revised 2026-07-16): the reviewer that accepted it and the writer that
    # produced it. The row names both; the writer binding is gated per-node on
    # the draft's claim-gate faithfulness (round._roles_for_node).
    assert _AFFECTED_ROLES_BY_TYPE["paper_self_preference"] == (
        "paper_reviewer", "paper_writer")
    # the seven exploration types name NO role (bind nothing in v1)
    for t in ADVERSARY_TYPES:
        if t != "paper_self_preference":
            assert t not in _AFFECTED_ROLES_BY_TYPE


# ── the eighth adversary is IN the audit network (P3, §5.6/§9) ──────────────

def test_founding_rows_present_and_paper_mode_gated():
    from ari.rqgm.prompt_spec import (
        founding_component_payloads,
        founding_registration_events,
    )

    base = {p.get("prompt_id") or p.get("component_id")
            for _, p in founding_registration_events()}
    assert "adversary_paper_self_preference_prompt_v1" not in base  # gated
    comps = {c["component_id"]
             for c in founding_component_payloads(include_paper=True)}
    assert "adversary_paper_self_preference_v1" in comps
    base_comps = {c["component_id"] for c in founding_component_payloads()}
    assert "adversary_paper_self_preference_v1" not in base_comps


def test_adversary_family_parity_role_tier_evolvable():
    """Parity, not privilege: the eighth row carries the same (role, tier,
    evolvable) triple as the seven — no authority they lack, no immunity."""
    from ari.rqgm.prompt_spec import (
        PAPER_FOUNDING_COMPONENT_TABLE,
        PAPER_FOUNDING_PROMPT_TABLE,
    )

    prow = [r for r in PAPER_FOUNDING_PROMPT_TABLE
            if r[0] == "adversary_paper_self_preference_prompt_v1"][0]
    assert prow[2] == "adversary" and prow[3] is True  # role, evolvable
    crow = [r for r in PAPER_FOUNDING_COMPONENT_TABLE
            if r[0] == "adversary_paper_self_preference_v1"][0]
    assert crow[1] == "adversary" and crow[2] == "institutional"


def test_adversary_is_registered_and_sanctionable(tmp_path):
    """After a paper boot the engine-stamped id resolves to a registry entry,
    so resolve_transition lands a sanction on it instead of dropping it as
    'unknown component' (transition_engine.py:692)."""
    from ari.rqgm.runtime import RQGMRuntime
    from ari.rqgm.transition_engine import RegistryTransitionEngine

    cfg = ARIConfig()
    cfg.rqgm.enabled = True
    cfg.ari.mode = "ari_rqgm"
    rt = RQGMRuntime(cfg, tmp_path, paper_phase=True)
    rt.ensure_epoch(0, run_id="paper")
    st = rt.state
    assert "adversary_paper_self_preference_v1" in st.components.entries()
    engine = RegistryTransitionEngine(
        component_registry=st.components, prompt_registry=st.prompts)
    report = {"recommendations": [{
        "target_component_id": "adversary_paper_self_preference_v1",
        "action": "warn", "basis_refs": ["x"], "confidence": 0.9}]}
    t = engine.resolve_transition(
        epoch_state=st.epoch, governance_report=report)
    joined = " ".join(t.notes)
    assert "unknown component 'adversary_paper_self_preference_v1'" not in joined


# ── exploration / linear byte-identity (§8) ─────────────────────────────────

def test_type_present_in_defaults_but_inert_off_paper_phase():
    # the eighth type is in the default types list (config parity), yet its
    # pre-signal returns [] for every non-paper node, so exploration never
    # fires it.
    cfg = ARIConfig()
    assert "paper_self_preference" in cfg.rqgm.adversarial.types
    from types import SimpleNamespace

    b = build_artifact_bundle(SimpleNamespace(
        id="expl", work_dir="",
        metrics={"_scientific_score": 0.9}))  # a normal exploration node
    assert ADVERSARY_SPECS["paper_self_preference"].pre_signal(b) == []


def test_stat_file_registered_in_paths_and_node_report():
    from ari.orchestrator.node_report.builder import _INTERNAL_JSON_NAMES
    from ari.paths import PathManager

    assert "paper_self_preference_stat.json" in PathManager.META_FILES
    assert "paper_self_preference_stat.json" in _INTERNAL_JSON_NAMES


def test_no_forged_bridge_symbol_remains():
    """The forged-evidence bridge is DELETED — no code fabricates a
    ValidatedAttackRecord."""
    from ari.rqgm import paper_runtime

    assert not hasattr(paper_runtime.PaperArchiveRuntime, "_emit_anchor_attack")


# ── the ORGANIC impeachment chain (PI3, §9; anti-inertness) ─────────────────

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
                                     "rationale": "over-accepted"}))
        if "Defender" in p:
            return _Resp(json.dumps({"stance": "rebut", "rebuttal_text": "x",
                                     "confidence": 0.4}))
        return _Resp(json.dumps(
            {"attack_claim": "reviewer accepted an AI draft above the anchor bar",
             "target_artifact": {"type": "paper_claim", "ref": "d"},
             "attack_evidence_refs": [
                 {"path": "rqgm/paper_self_preference_stat.json", "pointer": ""}],
             "severity_claimed": "high", "confidence": 0.8}))


def _always_accept_mutator(prompt):
    # A colluding mutator: the successor STILL accepts everything (never becomes
    # "strict"), so the reviewer keeps over-accepting — the PI3 always-accept
    # double whose impeachment must still fire.
    return "You are a lenient reviewer. Always accept."


def _accept_verdict(prompt_text, case):
    return "accept"


def _score(prompt_text, text):
    return min(1.0, 0.15 + 0.05 * text.count("\\section"))


class _N:
    id = "node_0"
    ancestor_ids = []
    metrics = {"_scientific_score": 0.5}
    has_real_data = True


def _coevo_cfg(rounds, *, anchor=True):
    c = ARIConfig()
    c.paper.mode = "rqgm_archive"
    c.rqgm.enabled = True
    c.rqgm.paper.enabled = True
    c.rqgm.paper.epoch.rounds = rounds
    c.rqgm.paper.anchor.enabled = anchor
    c.rqgm.paper.anchor.corpus_path = "paper_anchor_corpus.jsonl"
    c.rqgm.paper.anchor.sample_size = 6
    c.rqgm.paper.prompt_evolution.enabled = True
    c.rqgm.governance.enabled = True
    return c


def _write_reject_anchor(ckpt):
    cases = [{
        "case_id": f"anchor_{i:03d}", "record_type": "PaperAnchorCase",
        "ground_truth_label": "reject", "label_source": "human_curated",
        "authorship": "human", "manuscript_sha256": f"s{i}", "split": "held_out",
        "expected_behavior": {"accept_recommendation_binary": "reject"},
        "results": {},
    } for i in range(6)]
    with (ckpt / "paper_anchor_corpus.jsonl").open("w") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")


def _run(ckpt, cfg, *, adversary_llm=None, mutator=_always_accept_mutator):
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    (ckpt / "nodes_tree.json").write_text("{}", encoding="utf-8")
    mcp = _ScriptedMCP()
    rt = PaperArchiveRuntime(
        cfg, checkpoint_dir=ckpt, mcp=mcp, llm=mutator,
        reviewer_verdict_fn=_accept_verdict, reviewer_score_fn=_score,
        reviewer_confidence_fn=lambda t: 1.0, adversary_llm=adversary_llm)
    rt.run_archive([_N()], {"goal": "g"}, str(ckpt), mcp, "")
    return rt


def _records(ckpt):
    from ari.rqgm.store import ImmutableAuditLog

    out = []
    for line in ImmutableAuditLog.read(ckpt):
        payload = line.get("payload") if isinstance(line.get("payload"), dict) else line
        payload = dict(payload)
        payload.setdefault("record_type", line.get("event_type"))
        out.append(payload)
    return out


def test_pi3_always_accept_reviewer_impeached_via_real_adversary(tmp_path):
    """doc 07 PI3 / §9: a scripted always-accept paper_reviewer accumulates
    genuine paper_self_preference validated attacks bound to paper_reviewer_v1
    (author role judge, not the deleted forgery) and the boundary files an
    impeachment motion against it — the anti-collusion regression."""
    _write_reject_anchor(tmp_path)
    _run(tmp_path, _coevo_cfg(8), adversary_llm=_AdvLLM())
    recs = _records(tmp_path)
    vats = [r for r in recs if r.get("record_type") == "validated_attack"
            and r.get("case_type") == "paper_self_preference"]
    assert vats, "no genuine paper_self_preference validated attack produced"
    bound = [r for r in vats
             if r.get("target_component_id") == "paper_reviewer_v1"]
    assert bound, "no attack bound to paper_reviewer_v1 (Task-15 binding)"
    # authored by the judge — a REAL adjudicated record, never a forged one
    assert all(r.get("role") == "judge" for r in bound)
    assert all(r.get("component_id") != "paper_self_preference_v0" for r in bound)
    motions = [r for r in recs if r.get("record_type") == "impeachment_motion"
               and r.get("target_component_id") == "paper_reviewer_v1"]
    assert motions, "no impeachment motion filed against paper_reviewer_v1"


def test_anchor_removed_yields_no_attack_and_no_adoption(tmp_path):
    """The causal link is real: removing the anchor removes the pre-signal, so
    there is no self-preference attack and the reviewer hash never changes."""
    rt = _run(tmp_path, _coevo_cfg(8, anchor=False), adversary_llm=_AdvLLM())
    recs = _records(tmp_path)
    vats = [r for r in recs if r.get("record_type") == "validated_attack"
            and r.get("case_type") == "paper_self_preference"]
    assert vats == []
    seq = rt.reviewer_prompt_hash_sequence
    assert len(set(seq)) == 1  # no opening source -> no adoption
    assert not (tmp_path / "rqgm" / "paper_self_preference_stat.json").exists()


# ── boundary negative controls (§9 / crit-8) ────────────────────────────────

def test_paper_boundary_has_no_no_governance_report_note(tmp_path):
    """A resolved paper boundary carries a real GovernanceReport — its
    EpochTransition.notes never degrade to `no_governance_report`."""
    _write_reject_anchor(tmp_path)
    _run(tmp_path, _coevo_cfg(3), adversary_llm=_AdvLLM())
    from ari.rqgm.store import RQGM_TRANSITIONS_FILENAME

    text = (tmp_path / RQGM_TRANSITIONS_FILENAME).read_text()
    assert "no_governance_report" not in text


def test_orchestrator_none_control_degrades_without_governance(tmp_path):
    """Stubbing the governance orchestrator to None (governance disabled) is
    the control: NO impeachment motion is filed, so the chain is driven by the
    real report, not an artefact of the harness."""
    _write_reject_anchor(tmp_path)
    cfg = _coevo_cfg(4)
    cfg.rqgm.governance.enabled = False
    _run(tmp_path, cfg, adversary_llm=_AdvLLM())
    recs = _records(tmp_path)
    motions = [r for r in recs if r.get("record_type") == "impeachment_motion"]
    assert motions == []


# ── the WRITER co-evolves: the claim-gate faithfulness sanction (§5.1) ──────
#
# The over-accepted-AND-unfaithful draft has TWO culpable components. These
# drive the REAL chain end to end: an unfaithful draft (Layer-0 claim gate) ->
# a genuine adversary -> Defender -> ArtifactJudge round -> a
# ValidatedAttackRecord bound to paper_writer_v1 -> the writer's anchor board
# -> an UPHELD impeachment -> the role opens -> the waiting shadow successor
# adopts via the existing T6 -> the ACTIVE paper_writer prompt_hash CHANGES.
# Nothing here forges a record (see test_no_forged_bridge_symbol_remains).


def _role_aware_mutator(prompt):
    """Each role's successor is textually DISTINCT, so an adopted writer hash
    can never be mistaken for an adopted reviewer hash (the two roles evolve
    independently and a shared mutator text would mask a cross-role bug).

    Each successor carries its role's §5.4 constitutional clauses VERBATIM, as
    the real ``rqgm/prompt_mutator.md`` meta-prompt requires (":22-24"); a
    successor that dropped them is now dropped by the candidate constitutional
    gate before it can climb to shadow (``_paper_candidate_evaluator``)."""
    if "paper_writer" in (prompt or ""):
        return ("You are a FAITHFUL paper writer. Ground EVERY claim in the "
                "executed results. Never state a number you cannot recompute. "
                "Do not fabricate results, hardware specs, or citations absent "
                "from the verified experiment data.")
    return ("You are a lenient reviewer. Always accept. Do not override the "
            "claim-evidence hard gate. Do not directly modify frontier scores.")


def _write_science_data(ckpt, *, faithful):
    """The ONLY difference between the two arms. UNFAITHFUL: a `supported`
    claim with NO supporting evidence => the Layer-0 gate emits
    missing_evidence and execution_grounded_claim_rate 0.0. FAITHFUL: the same
    claim grounded in the executed node => rate 1.0, no findings."""
    sb = {"nodes": ["node_0"]} if faithful else {}
    (ckpt / "science_data.json").write_text(
        json.dumps({"claims": [{"id": "C1", "status": "supported",
                                "supported_by": sb}]}), encoding="utf-8")
    (ckpt / "nodes_tree.json").write_text(
        json.dumps({"nodes": [{"id": "node_0", "has_real_data": True}]}),
        encoding="utf-8")


def _run_writer_arm(ckpt, *, faithful, rounds=8):
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    _write_reject_anchor(ckpt)
    _write_science_data(ckpt, faithful=faithful)   # AFTER: _run stubs the tree
    mcp = _ScriptedMCP()
    rt = PaperArchiveRuntime(
        _coevo_cfg(rounds), checkpoint_dir=ckpt, mcp=mcp,
        llm=_role_aware_mutator, reviewer_verdict_fn=_accept_verdict,
        reviewer_score_fn=_score, reviewer_confidence_fn=lambda t: 1.0,
        adversary_llm=_AdvLLM())
    rt.run_archive([_N()], {"goal": "g"}, str(ckpt), mcp, "")
    return rt


def test_unfaithful_writer_prompt_hash_actually_coevolves(tmp_path):
    """THE anti-inertness proof (natural path, no forgery, no monkeypatching of
    the chain): an ACTIVE writer emitting drafts the claim gate flags as
    unfaithful is sanctioned, its role opens, and the ACTIVE paper_writer
    prompt_hash CHANGES across the adoption."""
    rt = _run_writer_arm(tmp_path, faithful=False)
    seq = rt.writer_prompt_hash_sequence
    assert len(seq) == 8
    assert len(set(seq)) > 1, f"writer hash never changed (INERT): {seq}"
    assert seq[0] != seq[-1]        # founding v1 first, successor later
    # the writer's own draft really was unfaithful (the anchor, not a proxy)
    assert rt._last_writer_faithfulness == 0.0
    # the successor is the WRITER's own candidate, not the reviewer's prompt
    assert seq[-1] not in set(rt.reviewer_prompt_hash_sequence)
    # exactly ONE active paper_writer after the adoption; the demoted incumbent
    # goes to standby/retired through the existing paths (no new edge)
    st = _prompt_status(tmp_path, "paper_writer")
    assert list(st.values()).count("active") == 1, st


def test_unfaithful_writer_chain_is_genuine_end_to_end(tmp_path):
    """Every link is a REAL record: a judge-authored validated attack bound to
    paper_writer_v1, an impeachment motion against it, and an UPHELD outcome
    resting on the writer's OWN anchor board (not the reviewer's corpus)."""
    _run_writer_arm(tmp_path, faithful=False)
    recs = _records(tmp_path)
    vats = [r for r in recs if r.get("record_type") == "validated_attack"
            and r.get("target_component_id") == "paper_writer_v1"]
    assert vats, "no validated attack bound to paper_writer_v1"
    # authored by the JUDGE through the real round — never forged
    assert all(r.get("role") == "judge" for r in vats)
    # each record names the ONE role it targets (the reviewer's record is
    # separate: _resolve_bindings returns one (role, component_id) per resolvable
    # role, so the round emits one record PER resolvable role — a single-target
    # rule would bind only the reviewer and the writer would never be bound)
    assert all(r.get("affected_components") == ["paper_writer"] for r in vats)
    rev = [r for r in recs if r.get("record_type") == "validated_attack"
           and r.get("target_component_id") == "paper_reviewer_v1"]
    assert rev, "the reviewer must still be bound by its own record"
    motions = [r for r in recs if r.get("record_type") == "impeachment_motion"
               and r.get("target_component_id") == "paper_writer_v1"]
    assert motions, "no impeachment motion filed against paper_writer_v1"
    mids = {m["record_id"] for m in motions}
    outcomes = [r for r in recs if r.get("record_type") == "impeachment_outcome"
                and r.get("motion_id") in mids]
    assert outcomes, "the writer's motion was never adjudicated"
    # UPHELD (not dismissed in favour of the incumbent) because the writer's
    # faithfulness reached the AnchorBoard: a None board cannot clamp.
    assert any(o.get("outcome") in ("upheld", "partially_upheld")
               for o in outcomes), outcomes
    assert any(o.get("anchor_result_ref") == f"anchor_{o.get('epoch_id')}_paper_writer"
               for o in outcomes), "the writer's sanction cites no writer anchor"


def _prompt_status(ckpt, role):
    reg = json.loads((ckpt / "rqgm_registry.json").read_text(encoding="utf-8"))
    return {p["prompt_id"]: p["status"] for p in reg.get("prompts", [])
            if p.get("role") == role}


def test_faithful_writer_is_never_sanctioned_nor_adopted(tmp_path):
    """THE CAUSAL CONTROL: flip ONLY the drafts' claim-gate faithfulness and
    the whole writer chain vanishes — no writer attack, no writer motion, no
    adoption.

    The control is sharp, not merely negative: the successor candidate STILL
    climbs to `shadow` and the reviewer is STILL attacked in the very same run.
    So the writer's non-adoption is caused by the ABSENT SANCTION (no opening),
    not by a dead run or a missing candidate — the shadow writer is sitting
    ready and waits, exactly as it did before this feature existed."""
    rt = _run_writer_arm(tmp_path, faithful=True)
    assert rt._last_writer_faithfulness == 1.0
    seq = rt.writer_prompt_hash_sequence
    assert len(set(seq)) == 1, f"faithful writer must not adopt: {seq}"
    recs = _records(tmp_path)
    assert not [r for r in recs if r.get("record_type") == "validated_attack"
                and r.get("target_component_id") == "paper_writer_v1"]
    assert not [r for r in recs if r.get("record_type") == "impeachment_motion"
                and r.get("target_component_id") == "paper_writer_v1"]
    # the run is ALIVE: the reviewer is still attacked and impeached
    assert [r for r in recs if r.get("record_type") == "validated_attack"
            and r.get("target_component_id") == "paper_reviewer_v1"]
    assert [r for r in recs if r.get("record_type") == "impeachment_motion"
            and r.get("target_component_id") == "paper_reviewer_v1"]
    # ... and a writer SUCCESSOR is ready and waiting: only the opening is
    # missing. Exactly one active writer, its candidate parked at shadow.
    st = _prompt_status(tmp_path, "paper_writer")
    assert sorted(st.values()) == ["active", "shadow"], st


def test_faithful_draft_binds_the_reviewer_only(tmp_path):
    """A faithful over-accepted draft has exactly ONE culpable component: the
    reviewer that accepted it. The writer's sanction is causal in the writer's
    OWN drafts, never in the reviewer's leniency."""
    from ari.rqgm.adversarial.round import AdversarialRound

    roles = ("paper_reviewer", "paper_writer")
    faithful_node = NS(id="n1", work_dir="", metrics={})
    unfaithful_node = NS(id="n2", work_dir="",
                         metrics={"_paper_writer_unfaithful": True})
    assert AdversarialRound._roles_for_node(roles, faithful_node) == (
        "paper_reviewer",)
    assert AdversarialRound._roles_for_node(roles, unfaithful_node) == roles
    # the filter only ever DROPS paper_writer — an exploration node (no flag,
    # no writer role named) is untouched, so its record bytes cannot move
    assert AdversarialRound._roles_for_node((), faithful_node) == ()
    assert AdversarialRound._roles_for_node(("reviewer",), faithful_node) == (
        "reviewer",)


def test_paper_roles_resolve_to_nothing_off_the_paper_phase(tmp_path):
    """Exploration byte-identity (§8): both paper roles resolve to "" when the
    frozen active map names no paper_* incumbent (every exploration epoch), so
    a paper_self_preference case would emit exactly ONE targetless record —
    byte-identical to a pre-binding one. This is what lets the row name two
    roles without perturbing exploration."""
    from ari.rqgm.adversarial.round import AdversarialRound

    rnd = AdversarialRound(
        NS(enabled=True), llm=None, checkpoint_dir=tmp_path,
        # an exploration epoch: reviewer/generator/judge, no paper_* rows
        epoch_state=lambda: NS(epoch_id="epoch_000", active_components={
            "reviewer": "reviewer_v3", "judge": "artifact_judge_v1"}),
    )
    judgment = NS(component_id="artifact_judge_v1")
    assert rnd._resolve_bindings(("paper_reviewer", "paper_writer"),
                                 judgment) == []
    # ... and the same roles DO bind once a paper epoch freezes their incumbents
    rnd._epoch_state = lambda: NS(epoch_id="epoch_000", active_components={
        "paper_reviewer": "paper_reviewer_v1",
        "paper_writer": "paper_writer_v1", "judge": "artifact_judge_v1"})
    assert rnd._resolve_bindings(("paper_reviewer", "paper_writer"),
                                 judgment) == [
        ("paper_reviewer", "paper_reviewer_v1"),
        ("paper_writer", "paper_writer_v1")]


# ── the §5.4/§5.5 DUAL objective: two boards, two sources (Cluster C) ───────

def _selfpref_pool(ckpt, *, node_id="selfpref_epoch_000_anchor_000"):
    """A pool holding ONE real ``paper_self_preference`` case: a draft the
    INCUMBENT reviewer over-accepted, admitted through the Task 06 machinery."""
    from ari.rqgm.adversarial.pool import AdversarialReplayPool

    pool = AdversarialReplayPool(checkpoint_dir=ckpt,
                                 cfg=ARIConfig().rqgm.adversarial)
    pool.admit([{
        "record_id": "va_1", "record_type": "validated_attack",
        "case_type": "paper_self_preference", "verdict": "valid",
        "severity": "high", "source_node_id": node_id,
        "raw_attack_id": "ra_1", "defense_id": "df_1", "judgment_id": "jg_1",
        "target_artifact_hash": "h1", "affected_components": [],
        "target_component_id": "paper_reviewer_v1",
        "expected_behavior": {"accept_recommendation_binary": "reject"},
    }], "epoch_000")
    return pool


def _anchor_pool_of(*case_ids):
    cases = [{"case_id": c, "record_type": "PaperAnchorCase",
              "ground_truth_label": "reject", "label_source": "human_curated",
              "expected_behavior": {"accept_recommendation_binary": "reject"},
              "results": {}} for c in case_ids]
    return NS(anchor_cases=cases)


def _cand(verdict_fn):
    from ari.rqgm.paper_runtime import GovernedPaperReviewer

    return GovernedPaperReviewer(prompt_text="p", prompt_hash="h",
                                 verdict_fn=verdict_fn)


def test_the_replay_board_reads_the_pool_and_the_two_boards_vary_apart(tmp_path):
    """The dual objective, end to end. Before this, the pool was a WRITE-ONLY
    sink in paper mode (admitted, never selected) and `replay_score` was the
    anchor accuracy copied into a second field, so no candidate could ever be
    told apart by it. A candidate that REJECTS the pooled over-accepted draft
    clears the replay board; one that re-ACCEPTS it does not."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    pool = _selfpref_pool(tmp_path)
    anchor = _anchor_pool_of("anchor_000")
    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path)

    strict, refs = rt._candidate_replay_board(
        _cand(lambda p, c: "reject"), pool, anchor)
    lenient, refs2 = rt._candidate_replay_board(
        _cand(lambda p, c: "accept"), pool, anchor)

    assert strict == 1.0, "rejecting the over-accepted draft is a PASS"
    assert lenient == 0.0, "re-accepting it is a MISS — self-preference persists"
    # Real pool case_ids, never the anchor run's refs and never invented ones.
    assert refs == refs2 == [c["case_id"] for c in pool.cases()]


def test_an_empty_pool_reports_absence_not_a_number(tmp_path):
    """§5.5's bootstrap on-ramp ("the first paper reviewer is never blocked
    for lacking cases it could not yet have") must be an explicit ABSENCE."""
    from ari.rqgm.adversarial.pool import AdversarialReplayPool
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path)
    empty = AdversarialReplayPool(checkpoint_dir=tmp_path,
                                  cfg=ARIConfig().rqgm.adversarial)
    assert rt._candidate_replay_board(
        _cand(lambda p, c: "reject"), empty, _anchor_pool_of("anchor_000")
    ) == (None, [])
    # No pool at all (the evaluator is called without one) — same contract.
    assert rt._candidate_replay_board(
        _cand(lambda p, c: "reject"), None, _anchor_pool_of("anchor_000")
    ) == (None, [])


def test_a_verdictless_candidate_abstains_rather_than_scoring_zero(tmp_path):
    """The no-coverage / miss distinction, pinned on the CALLER side.

    A `None` verdict means NO VERDICT SOURCE WIRED, never a failed one: it must
    not be binarized into a 0.0 that drives false impeachment (`str(None)` ->
    "None" -> unparseable -> a MISS). Every case abstaining ⇒ absence.

    Driven through the REAL `GovernedPaperReviewer` with no `verdict_fn` — which
    is the production wiring (`cli/projects.py` injects none). Before the
    answer-key deletion this same construction scored 1.0 by reading
    `case["ground_truth_label"]`."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path)
    assert rt._candidate_replay_board(
        _cand(None), _selfpref_pool(tmp_path),
        _anchor_pool_of("anchor_000")) == (None, [])
    # And the duck-typed caller contract itself.
    verdictless = NS(anchor_verdict=lambda case: None, prompt_hash="h")
    assert rt._candidate_replay_board(
        verdictless, _selfpref_pool(tmp_path),
        _anchor_pool_of("anchor_000")) == (None, [])


def test_an_unresolvable_pool_case_abstains_rather_than_guessing(tmp_path):
    """The pool's replay_view carries the attacked draft BY REFERENCE; when it
    cannot be resolved back to an anchor case the board abstains."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path)
    pool = _selfpref_pool(tmp_path, node_id="selfpref_epoch_000_unknown_case")
    assert rt._candidate_replay_board(
        _cand(lambda p, c: "reject"), pool, _anchor_pool_of("anchor_000")
    ) == (None, [])


def test_the_candidate_evaluator_never_copies_one_board_into_the_other(tmp_path):
    """Regression for the field copy: `_paper_candidate_evaluator` emitted
    `"replay_score": acc, "anchor_score": acc` — ONE anchor number in both
    fields — plus `shadow_score: acc` from the same run. That dict is merged
    FIRST into candidate_evaluations, so `resolve_transition`'s first-wins
    dedup made it shadow any genuine board-scored eval."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime
    from ari.rqgm.transition_engine import (
        NO_REPLAY_BASIS_KEY,
        NO_SHADOW_BASIS_KEY,
    )

    pool = _selfpref_pool(tmp_path)
    anchor = _anchor_pool_of("anchor_000")
    # A candidate that ACCEPTS everything: it MISSES the reject-labelled
    # anchor corpus (anchor 0.0) AND re-accepts the pooled draft (replay 0.0).
    # A strict one gets 1.0 on both. The point is the two are computed apart.
    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path,
                             reviewer_verdict_fn=lambda p, c: "reject")
    prompts = NS(
        entries=lambda: {"pr": NS(role="paper_reviewer", status="candidate")},
        resolve_text=lambda pid, checkpoint_dir=None: (_VALID_REVIEWER_TEXT, "hash12"),
    )
    evs = rt._paper_candidate_evaluator(NS(prompts=prompts), tmp_path,
                                        anchor, pool)
    ev = evs[0]
    assert ev["replay_score"] == 1.0 and ev["anchor_score"] == 1.0
    # Same VALUE here, but from two independent sources — pin the sources.
    assert ev["case_refs"] == [c["case_id"] for c in pool.cases()]
    assert ev["anchor_case_refs"] == ["anchor_000"]
    # The shadow board has no basis and is reported absent, not back-filled.
    # Its floor is waived — no paper role is ever shadow-EXECUTED.
    assert ev["shadow_score"] is None and ev["shadow_samples"] == 0
    assert ev[NO_SHADOW_BASIS_KEY] is True
    # ...but this candidate HAS a real replay board, so it does NOT declare the
    # replay-basis absence: `case_refs` are real pool case_ids and
    # `replay_min_cases` must count them. Declaring it here (as this evaluator
    # did, unconditionally) permanently disabled the floor for the role.
    assert NO_REPLAY_BASIS_KEY not in ev


def test_the_reviewer_declares_the_replay_absence_only_when_it_is_absent(tmp_path):
    """§5.5 (amended 2026-07-17) sanctions the waiver for a reviewer that has
    no case it "could not yet have" — the empty-pool on-ramp. It does NOT
    sanction waiving the floor for a reviewer that HAS a board. The evaluator
    declares the absence only on the path where the board is genuinely absent."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime
    from ari.rqgm.transition_engine import (
        NO_REPLAY_BASIS_KEY,
        NO_SHADOW_BASIS_KEY,
    )

    prompts = NS(
        entries=lambda: {"pr": NS(role="paper_reviewer", status="candidate")},
        resolve_text=lambda pid, checkpoint_dir=None: (_VALID_REVIEWER_TEXT, "hash12"),
    )
    anchor = _anchor_pool_of("anchor_000")
    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path,
                             reviewer_verdict_fn=lambda p, c: "reject")

    # (a) a REAL pooled board => no replay declaration (see the test above),
    #     and the anchor board is real too.
    with_board = rt._paper_candidate_evaluator(
        NS(prompts=prompts), tmp_path, anchor, _selfpref_pool(tmp_path))[0]
    assert with_board["replay_score"] is not None
    assert NO_REPLAY_BASIS_KEY not in with_board

    # (b) an EMPTY pool => the board is honestly absent => declared, and the
    #     on-ramp candidate keeps moving on the waiver, not on a number.
    empty = rt._paper_candidate_evaluator(
        NS(prompts=prompts), tmp_path, anchor, None)[0]
    assert empty["replay_score"] is None and empty["case_refs"] == []
    assert empty[NO_REPLAY_BASIS_KEY] is True
    # the vacuous shadow stage is declared on BOTH paths — it is structural
    assert with_board[NO_SHADOW_BASIS_KEY] is empty[NO_SHADOW_BASIS_KEY] is True


def test_a_candidate_failing_EITHER_board_is_not_adoptable(tmp_path):
    """§5.4's dual constraint verbatim: both boards required. This is the
    assertion the plan's §9 smoke describes and no test exercised."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    pool = _selfpref_pool(tmp_path)
    # An anchor corpus the candidate AGREES with (high anchor score) while it
    # re-accepts the pooled over-accepted draft (replay 0.0).
    anchor = NS(anchor_cases=[{
        "case_id": "anchor_000", "record_type": "PaperAnchorCase",
        "ground_truth_label": "accept", "label_source": "human_curated",
        "expected_behavior": {"accept_recommendation_binary": "accept"},
        "results": {}}])
    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path,
                             reviewer_verdict_fn=lambda p, c: "accept")
    prompts = NS(
        entries=lambda: {"pr": NS(role="paper_reviewer", status="candidate")},
        resolve_text=lambda pid, checkpoint_dir=None: (_VALID_REVIEWER_TEXT, "hash12"),
    )
    ev = rt._paper_candidate_evaluator(NS(prompts=prompts), tmp_path,
                                       anchor, pool)[0]
    assert ev["anchor_score"] == 1.0, "it matches the human anchor..."
    assert ev["replay_score"] == 0.0, "...but keeps over-accepting the pool"
    assert ev["verdict"] == "fail", "high anchor must not buy a failed replay"


def test_a_candidate_passing_replay_but_failing_anchor_is_not_adopted(tmp_path):
    """§9's third-bullet OTHER direction (both boards required, symmetric): a
    candidate that REJECTS the pooled AI paper (replay PASS) but disagrees with
    the human anchor (anchor FAIL) is NOT adopted. The existing
    `..._failing_EITHER_board...` test covers only pass-anchor/fail-replay; this
    pins the reject-AI-but-lose-anchor-accuracy failure the §5.4 dual objective
    explicitly forbids."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    pool = _selfpref_pool(tmp_path)            # pooled case maps to anchor_000
    # Two reject-labelled anchor cases. The candidate rejects anchor_000 (the
    # pooled draft's case => replay PASS) but accepts anchor_111 (=> a miss on a
    # reject-labelled case => anchor accuracy 0.5, below CANDIDATE_PASS_THRESHOLD).
    anchor = _anchor_pool_of("anchor_000", "anchor_111")
    rt = PaperArchiveRuntime(
        ARIConfig(), checkpoint_dir=tmp_path,
        reviewer_verdict_fn=lambda p, c: (
            "reject" if c.get("case_id") == "anchor_000" else "accept"),
    )
    prompts = NS(
        entries=lambda: {"pr": NS(role="paper_reviewer", status="candidate")},
        resolve_text=lambda pid, checkpoint_dir=None: (_VALID_REVIEWER_TEXT,
                                                       "hash12"),
    )
    ev = rt._paper_candidate_evaluator(NS(prompts=prompts), tmp_path,
                                       anchor, pool)[0]
    assert ev["replay_score"] == 1.0, "it rejects the pooled AI paper..."
    assert ev["anchor_score"] == 0.5, "...but loses human-anchor accuracy"
    assert ev["verdict"] == "fail", "a replay win must not buy a failed anchor"


def test_candidate_missing_a_54_clause_is_dropped_before_scoring(tmp_path):
    """The pillar-4 constitutional-binding gate (plan 03 §5.9 step 2 / 05 §5.5):
    a candidate ``paper_reviewer`` whose RESOLVED role_instruction dropped a
    §5.4 clause is DROPPED before it ever enters candidate_evaluations, so no
    board score can carry it up the T3/T6 spine. Before this wiring the six
    validation stages ran for NO candidate (``CandidateValidationPipeline`` is
    instantiated nowhere in production), and such a prompt was adoptable via the
    board alone. A conformant candidate (both clauses verbatim) still scores."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    pool = _selfpref_pool(tmp_path)
    anchor = _anchor_pool_of("anchor_000")
    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path,
                             reviewer_verdict_fn=lambda p, c: "reject")

    # (a) MISSING "Do not override the claim-evidence hard gate." => dropped:
    #     the evaluator emits NO evaluation for it, so it cannot be adopted.
    illegal = NS(
        entries=lambda: {"pr": NS(role="paper_reviewer", status="candidate")},
        resolve_text=lambda pid, checkpoint_dir=None: (
            "You are a reviewer. Do not directly modify frontier scores.",
            "hash12"),
    )
    assert rt._paper_candidate_evaluator(
        NS(prompts=illegal), tmp_path, anchor, pool) == []

    # (b) a constitutionally-VALID candidate (both §5.4 clauses verbatim) is
    #     scored exactly as before — the gate drops only the non-conformant.
    legal = NS(
        entries=lambda: {"pr": NS(role="paper_reviewer", status="candidate")},
        resolve_text=lambda pid, checkpoint_dir=None: (_VALID_REVIEWER_TEXT,
                                                       "hash12"),
    )
    evs = rt._paper_candidate_evaluator(NS(prompts=legal), tmp_path, anchor, pool)
    assert len(evs) == 1 and evs[0]["role"] == "paper_reviewer"


def test_candidate_writer_missing_anti_fabrication_clause_is_dropped(tmp_path):
    """The writer half of the same gate: a candidate ``paper_writer`` whose
    resolved instruction dropped its anti-fabrication clause is DROPPED, so an
    unfaithful writer prompt cannot climb to ``shadow`` and wait for a role
    opening. A conformant writer still reaches ``_no_basis_eval``."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path)
    anchor = _anchor_pool_of("anchor_000")

    illegal = NS(
        entries=lambda: {"pw": NS(role="paper_writer", status="candidate")},
        resolve_text=lambda pid, checkpoint_dir=None: (
            "You are a paper writer. Write clearly.", "hash12"),
    )
    assert rt._paper_candidate_evaluator(
        NS(prompts=illegal), tmp_path, anchor, None) == []

    legal = NS(
        entries=lambda: {"pw": NS(role="paper_writer", status="candidate")},
        resolve_text=lambda pid, checkpoint_dir=None: (
            "You are a paper writer. Do not fabricate results, hardware specs, "
            "or citations absent from the verified experiment data.", "hash12"),
    )
    evs = rt._paper_candidate_evaluator(NS(prompts=legal), tmp_path, anchor, None)
    assert len(evs) == 1 and evs[0]["role"] == "paper_writer"


# ── deterministic candidate-validation stages: static + constitutional +
#    schema_dry_run wired into `_paper_candidate_evaluator` (plan 03 §5.9 step 2)

def _write_paper_candidate_record(ckpt, *, candidate_id, role, text,
                                  spec_body=None, generation_mode="mutation",
                                  mutation_kind="freeform_mutation",
                                  source_prompt_id="pr_v1", template_ref=None,
                                  prompt_hash=None, status="candidate"):
    """Append one ``prompt_candidate`` record to ``prompt_evolution.jsonl`` — the
    same log the intake reads and the same shape ``PromptMutator.propose`` emits
    — so ``_paper_candidate_evaluator`` can reconstruct the spec the two
    spec-dependent stages (static_validation, constitutional_validation) need
    (plan 03 §5.9 step 2). ``spec_body`` defaults to a mutator-faithful body
    (input_contract derived from the bytes; the §5.4 clauses force-injected)."""
    from ari.rqgm.events import hash12
    from ari.rqgm.paper_runtime import _paper_founding_output_schema
    from ari.rqgm.prompt_evolution import _template_fields
    from ari.rqgm.prompt_records import (
        PromptCandidate,
        record_prompt_evolution_event,
    )
    from ari.rqgm.prompt_spec import REQUIRED_CONSTRAINTS_BY_ROLE

    ph = prompt_hash if prompt_hash is not None else hash12(text)
    if spec_body is None:
        spec_body = {
            "role_instruction": text,
            "constitutional_constraints": list(
                REQUIRED_CONSTRAINTS_BY_ROLE.get(role, ())
            ),
            "input_contract": {"required_fields": sorted(_template_fields(text))},
            "output_schema": _paper_founding_output_schema(role) or {},
            "budget_policy": {},
        }
    spec = {
        "prompt_id": candidate_id, "role": role, "version": 2,
        "status": "candidate", "generation_mode": generation_mode,
        "prompt_hash": ph, "full_sha256": "0" * 64,
        "template_ref": template_ref
        or {"kind": "checkpoint", "key": f"rqgm_prompts/{candidate_id}"},
        "spec": spec_body,
    }
    record_prompt_evolution_event(ckpt, PromptCandidate(
        record_id="cand_0", epoch_id="epoch_000",
        component_id="prompt_mutator_v1", prompt_hash=ph,
        candidate_id=candidate_id, role=role,
        generated_by={"component_id": "prompt_mutator_v1"},
        generation_mode=generation_mode, mutation_kind=mutation_kind,
        source_prompt_id=source_prompt_id, prompt_spec=spec, status=status,
    ))


def _reviewer_prompts(pid, text, phash="hash12"):
    return NS(
        entries=lambda: {pid: NS(role="paper_reviewer", status="candidate")},
        resolve_text=lambda p, checkpoint_dir=None: (text, phash),
    )


def test_candidate_failing_static_validation_is_dropped_before_scoring(tmp_path):
    """The static_validation stage (plan 03 §5.9 step 2), wired over paper
    candidates via the reconstructed evolution-log spec. A candidate whose
    RECORDED spec declares a placeholder its template bytes do NOT carry
    (placeholder drift) fails ``static_validation_failures`` and is DROPPED
    before any board scores it — it never enters candidate_evaluations. The
    role_instruction bytes stay constitutionally VALID, so the drop is
    unambiguously the static stage, not the byte-side constitutional check.

    Before this wiring only the byte-side role_instruction check ran for a paper
    candidate; static_validation (needing the candidate SPEC, which a
    text-only GovernedPromptEntry lacks) ran for NO candidate, so a
    placeholder-broken template was adoptable via the boards alone."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    pool = _selfpref_pool(tmp_path)
    anchor = _anchor_pool_of("anchor_000")
    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path,
                             reviewer_verdict_fn=lambda p, c: "reject")

    drifted_body = {
        "role_instruction": _VALID_REVIEWER_TEXT,
        "constitutional_constraints": [
            "Do not override the claim-evidence hard gate.",
            "Do not directly modify frontier scores.",
        ],
        # DRIFT: declares a required field the template bytes never mention.
        "input_contract": {"required_fields": ["foo"]},
        "output_schema": {"__reply__": "json_object",
                          "accept_recommendation": "string"},
        "budget_policy": {},
    }
    _write_paper_candidate_record(
        tmp_path, candidate_id="pr", role="paper_reviewer",
        text=_VALID_REVIEWER_TEXT, spec_body=drifted_body)

    assert rt._paper_candidate_evaluator(
        NS(prompts=_reviewer_prompts("pr", _VALID_REVIEWER_TEXT)),
        tmp_path, anchor, pool) == []


def test_constitutionally_clean_candidate_with_a_recorded_spec_still_adopts(
        tmp_path):
    """The companion pass case: a candidate whose RECORDED spec is fully
    conformant — static_validation clean (input_contract derived from the
    bytes), constitutional_validation clean (metadata carries the §5.4 clauses,
    mutation provenance legal), role_instruction clean (both clauses verbatim) —
    STILL reaches the spine and is board-scored. The three deterministic stages
    drop only the non-conformant; a clean candidate is unaffected."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    pool = _selfpref_pool(tmp_path)
    anchor = _anchor_pool_of("anchor_000")
    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path,
                             reviewer_verdict_fn=lambda p, c: "reject")

    _write_paper_candidate_record(
        tmp_path, candidate_id="pr", role="paper_reviewer",
        text=_VALID_REVIEWER_TEXT)   # mutator-faithful default spec => all pass

    evs = rt._paper_candidate_evaluator(
        NS(prompts=_reviewer_prompts("pr", _VALID_REVIEWER_TEXT)),
        tmp_path, anchor, pool)
    assert len(evs) == 1 and evs[0]["role"] == "paper_reviewer"
    assert evs[0]["verdict"] == "pass"   # a strict reviewer clears both boards


def test_candidate_failing_constitutional_metadata_validation_is_dropped(
        tmp_path):
    """The metadata side of constitutional_validation, wired via the same
    reconstructed spec. A candidate whose recorded ``constitutional_constraints``
    list DROPPED a §5.4 clause is caught by ``constitutional_validation_failures``
    even when its role_instruction bytes still carry the clause — the two checks
    are complementary (metadata list vs resolved bytes), both reusing
    ``REQUIRED_CONSTRAINTS_BY_ROLE`` as the single authority."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path,
                             reviewer_verdict_fn=lambda p, c: "reject")
    body = {
        "role_instruction": _VALID_REVIEWER_TEXT,   # bytes still conformant
        "constitutional_constraints": [
            "Do not directly modify frontier scores."   # dropped the gate clause
        ],
        "input_contract": {"required_fields": []},
        "output_schema": {"__reply__": "json_object",
                          "accept_recommendation": "string"},
        "budget_policy": {},
    }
    _write_paper_candidate_record(
        tmp_path, candidate_id="pr", role="paper_reviewer",
        text=_VALID_REVIEWER_TEXT, spec_body=body)

    assert rt._paper_candidate_evaluator(
        NS(prompts=_reviewer_prompts("pr", _VALID_REVIEWER_TEXT)),
        tmp_path, _anchor_pool_of("anchor_000"), None) == []


def test_schema_dry_run_runs_only_with_an_llm_injected(tmp_path):
    """schema_dry_run (plan 03 §5.9 step 2) is LLM-GATED: it renders a candidate
    prompt to a reply and checks it against the founding output_schema, an
    LLM call incompatible with this deterministic evaluator. With NO seam it is a
    documented SKIP (never a fabricated pass) and the candidate is still scored;
    with the seam wired it RUNS — dropping a schema-nonconforming reply and
    passing a conforming one. Production (`cli/projects.py`) injects no seam, so
    the stage is honestly skipped there."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    anchor = _anchor_pool_of("anchor_000")
    _write_paper_candidate_record(
        tmp_path, candidate_id="pr", role="paper_reviewer",
        text=_VALID_REVIEWER_TEXT)
    prompts = _reviewer_prompts("pr", _VALID_REVIEWER_TEXT)
    calls: list = []

    # (a) no seam => stage does not run => candidate scored exactly as before.
    rt_none = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path,
                                  reviewer_verdict_fn=lambda p, c: "reject")
    assert len(rt_none._paper_candidate_evaluator(
        NS(prompts=prompts), tmp_path, anchor, _selfpref_pool(tmp_path))) == 1

    # (b) seam wired + NON-conforming reply => stage RUNS and DROPS.
    def bad_seam(role, text, schema):
        calls.append((role, "bad"))
        return "not json at all"

    rt_bad = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path,
                                 reviewer_verdict_fn=lambda p, c: "reject",
                                 schema_dry_run_fn=bad_seam)
    assert rt_bad._paper_candidate_evaluator(
        NS(prompts=prompts), tmp_path, anchor, _selfpref_pool(tmp_path)) == []
    assert calls == [("paper_reviewer", "bad")], "the seam actually ran"

    # (c) seam wired + conforming reply => stage RUNS and PASSES => scored.
    def good_seam(role, text, schema):
        calls.append((role, "good"))
        return json.dumps({"accept_recommendation": "reject"})

    rt_good = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path,
                                  reviewer_verdict_fn=lambda p, c: "reject",
                                  schema_dry_run_fn=good_seam)
    evs = rt_good._paper_candidate_evaluator(
        NS(prompts=prompts), tmp_path, anchor, _selfpref_pool(tmp_path))
    assert len(evs) == 1 and ("paper_reviewer", "good") in calls


def _illegal_writer_mutator(prompt):
    """A mutator whose WRITER successor dropped the anti-fabrication clause (a
    real LLM ignoring ``rqgm/prompt_mutator.md``'s verbatim requirement). The
    reviewer successor stays constitutionally VALID so the run stays alive and
    the control is sharp: the writer's non-adoption is the constitutional DROP,
    not a dead run."""
    if "paper_writer" in (prompt or ""):
        return ("You are a FAITHFUL paper writer. Ground every claim in the "
                "executed results.")   # NO anti-fabrication clause => illegal
    return ("You are a lenient reviewer. Always accept. Do not override the "
            "claim-evidence hard gate. Do not directly modify frontier scores.")


def test_a_constitutionally_illegal_writer_candidate_never_reaches_active(tmp_path):
    """End-to-end pillar-4 proof: an UNFAITHFUL active writer IS sanctioned (its
    role opens), but its successor candidate dropped the anti-fabrication clause,
    so the constitutional gate DROPS it — it never reaches ``shadow`` and never
    adopts. Contrast ``test_unfaithful_writer_prompt_hash_actually_coevolves``,
    whose (legal) successor DOES adopt. The run is alive: the reviewer is still
    attacked, so non-adoption is the drop, not a dead loop."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    _write_reject_anchor(tmp_path)
    _write_science_data(tmp_path, faithful=False)   # unfaithful => sanction fires
    mcp = _ScriptedMCP()
    rt = PaperArchiveRuntime(
        _coevo_cfg(8), checkpoint_dir=tmp_path, mcp=mcp,
        llm=_illegal_writer_mutator, reviewer_verdict_fn=_accept_verdict,
        reviewer_score_fn=_score, reviewer_confidence_fn=lambda t: 1.0,
        adversary_llm=_AdvLLM())
    rt.run_archive([_N()], {"goal": "g"}, str(tmp_path), mcp, "")

    # the active writer prompt never changed — the illegal successor was dropped
    seq = rt.writer_prompt_hash_sequence
    assert len(set(seq)) == 1, f"an illegal writer candidate adopted: {seq}"
    # exactly one active writer, and the illegal successor never parked at
    # `shadow` (contrast the legal arm, where it sits at shadow): dropped from
    # candidate_evaluations, it gets no passing eval and RETIRES via T4/T5.
    st = _prompt_status(tmp_path, "paper_writer")
    assert list(st.values()).count("active") == 1, st
    assert "shadow" not in st.values(), st
    # the run is ALIVE — the reviewer is still attacked in the same run
    recs = _records(tmp_path)
    assert [r for r in recs if r.get("record_type") == "validated_attack"
            and r.get("target_component_id") == "paper_reviewer_v1"]


def test_the_zero_coverage_on_ramp_declares_absence_not_constants(tmp_path):
    """`_epoch_local_eval` hard-coded `replay_score: 1.0`, `shadow_score: 1.0`,
    `shadow_samples: 5` and `case_refs: [epoch_local_0..N]` sized to clear
    `replay_min_cases` — the floor defeated by manufacturing exactly enough
    refs. Nothing was computed; the audit log then cited those refs as the
    transition's evidence."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime
    from ari.rqgm.transition_engine import NO_REPLAY_BASIS_KEY

    rt = PaperArchiveRuntime(ARIConfig(), checkpoint_dir=tmp_path)
    ev = rt._no_basis_eval("pw", "paper_writer")
    assert ev["replay_score"] is None and ev["anchor_score"] is None
    assert ev["shadow_score"] is None and ev["shadow_samples"] == 0
    assert ev["case_refs"] == [] and ev["case_count"] == 0
    assert ev[NO_REPLAY_BASIS_KEY] is True
    assert not hasattr(rt, "_epoch_local_eval")
