"""Writer / Reviewer governed roles (paper-archive Task 03,
docs/plans/ari_rqgm_paper/03 §9).

Covers the constitutional amendment (paper_writer PROMOTED to a full evolvable
role + paper_reviewer added), the capability-matrix / context-view / founding
tables, the paper-mode-gated founding registration (exploration boot
byte-identical), and the multi-round co-evolution smoke that PROVES the active
paper_reviewer prompt_hash actually changes at a boundary (the anti-inertness
proof). No litellm / network import.
"""
from __future__ import annotations

import json

import pytest

from ari.config import ARIConfig
from ari.rqgm import kernel_rules
from ari.rqgm.context_views import (
    PAPER_REVIEWER_FIELDS,
    build_paper_reviewer_context,
)
from ari.rqgm.events import EVOLVABLE_ROLES
from ari.rqgm.kernel import ConstitutionalKernel
from ari.rqgm.prompt_spec import (
    build_founding_specs,
    founding_component_payloads,
    founding_registration_events,
)


# ── constitutional tables (§5.2, §5.3, §5.7) ────────────────────────────────

def test_both_roles_in_evolvable_and_matrix():
    for role in ("paper_writer", "paper_reviewer"):
        assert role in EVOLVABLE_ROLES
        assert (role, "institutional") in kernel_rules.CAPABILITY_MATRIX
        assert (role, "meta") in kernel_rules.CAPABILITY_MATRIX


def test_neither_role_writes_registry_or_activates():
    kernel = ConstitutionalKernel()
    for role in ("paper_writer", "paper_reviewer"):
        for tier in ("institutional", "meta"):
            caps = kernel_rules.CAPABILITY_MATRIX[(role, tier)]
            assert ("write", "registry") not in caps
            assert ("activate", "candidates") not in caps
        # the kernel denies both actions (CK-ACC-001 / CK-ROL-901)
        r1 = kernel.validate_capability((role, "institutional"), "write", "registry")
        r2 = kernel.validate_capability((role, "institutional"), "activate", "candidates")
        assert r1.violations and r2.violations


def test_context_whitelists():
    assert kernel_rules.CONTEXT_VIEW_WHITELISTS["paper_writer"] == frozenset(
        {"verified_context", "science_data", "claim_registry"}
    )
    assert kernel_rules.CONTEXT_VIEW_WHITELISTS["paper_reviewer"] == frozenset(
        {"draft_manuscript", "verified_context", "science_data", "reference_context"}
    )


def test_build_paper_reviewer_context_key_set_and_scope():
    kernel = ConstitutionalKernel()
    view = build_paper_reviewer_context(
        draft_manuscript={"tex": "..."}, verified_context={"c": 1},
        science_data={"m": 2}, reference_context={"anchor": "case"},
    )
    assert set(view) == set(PAPER_REVIEWER_FIELDS)
    assert not kernel.validate_context_scope("paper_reviewer", view).violations
    # a foreign field flags CK-CTX-001
    bad = {**view, "frontier_scores": [0.9]}
    report = kernel.validate_context_scope("paper_reviewer", bad)
    assert any(v.code == "CK-CTX-001" for v in report.violations)


def test_constitution_hash_repinned():
    # the amendment necessarily moved the hash off the pre-amendment value
    assert kernel_rules.constitution_hash() == kernel_rules.CONSTITUTION_HASH
    assert kernel_rules.CONSTITUTION_HASH != "951a294dc3c4"


# ── founding tables + required constraints (§5.4, §5.5) ──────────────────────

def test_paper_founding_specs_active_on_creation():
    from ari.prompts import FilesystemPromptLoader

    specs = {s.prompt_id: s for s in build_founding_specs(include_paper=True)}
    for pid, key, role in (
        ("paper_writer_prompt_v1", "rqgm/paper_writer", "paper_writer"),
        ("paper_reviewer_prompt_v1", "rqgm/paper_reviewer", "paper_reviewer"),
    ):
        spec = specs[pid]
        assert spec.status == "active" and spec.role == role
        assert spec.prompt_hash == FilesystemPromptLoader().load_versioned(key)[1]


def test_paper_founding_components_present():
    comps = {c["component_id"] for c in founding_component_payloads(include_paper=True)}
    assert {"paper_writer_v1", "paper_reviewer_v1"} <= comps
    # gated: the exploration set carries neither
    base = {c["component_id"] for c in founding_component_payloads()}
    assert "paper_writer_v1" not in base and "paper_reviewer_v1" not in base


def test_required_constraints():
    from ari.rqgm.prompt_spec import REQUIRED_CONSTRAINTS_BY_ROLE

    assert "Do not override the claim-evidence hard gate." in (
        REQUIRED_CONSTRAINTS_BY_ROLE["paper_reviewer"]
    )
    assert "Do not directly modify frontier scores." in (
        REQUIRED_CONSTRAINTS_BY_ROLE["paper_reviewer"]
    )
    assert REQUIRED_CONSTRAINTS_BY_ROLE["paper_writer"]  # anti-fabrication clause


# ── paper-mode gating: exploration boot byte-identical (§5.5, §8) ────────────

def test_founding_registration_gated():
    base = founding_registration_events()          # exploration default
    withp = founding_registration_events(include_paper=True)
    base_ids = {p.get("prompt_id") or p.get("component_id") for _, p in base}
    assert "paper_reviewer_prompt_v1" not in base_ids
    assert "paper_writer_prompt_v1" not in base_ids
    # Paper-archive Task 05: the eighth adversary is ALSO paper-mode-gated, so
    # the exploration boot never sees it (exploration byte-identity).
    assert "adversary_paper_self_preference_prompt_v1" not in base_ids
    assert "adversary_paper_self_preference_v1" not in base_ids
    # 3 paper prompts (writer, reviewer, self-preference adversary) + their 3
    # components.
    assert len(withp) == len(base) + 6
    prompt_ids = {p["prompt_id"] for et, p in withp if et == "prompt_registered"}
    comp_ids = {p["component_id"] for et, p in withp
                if et == "component_registered"}
    assert "adversary_paper_self_preference_prompt_v1" in prompt_ids
    assert "adversary_paper_self_preference_v1" in comp_ids


def test_exploration_ari_rqgm_boot_unchanged(tmp_path):
    """An exploration ari_rqgm boot registers NO paper rows — its
    registry_version is byte-identical to before the amendment."""
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig()
    cfg.rqgm.enabled = True
    cfg.ari.mode = "ari_rqgm"
    rt = RQGMRuntime(cfg, tmp_path)          # paper_phase defaults False
    rt.ensure_epoch(0, run_id="x")
    roles = {e.role for e in rt.state.prompts.entries().values()}
    assert not any(str(r).startswith("paper_") for r in roles)


# ── co-evolution smoke: the active reviewer hash ACTUALLY changes (§5.9) ─────

class _ScriptedMCP:
    def call_tool(self, name, args):
        if name == "write_paper_iterative":
            return {"latex": "\\section{Intro} % CLAIM:C1:NC1\n" * 3}
        if name == "paper_refine":
            from pathlib import Path
            tex = Path(args["tex_path"]).read_text(encoding="utf-8")
            return {"latex": tex + "\n\\section{More} % CLAIM:CX:NCX\n",
                    "anchors_preserved": True}
        return {}


def _paper_coevo_cfg(rounds, *, evolve=True, anchor=True):
    cfg = ARIConfig()
    cfg.paper.mode = "rqgm_archive"
    cfg.rqgm.enabled = True
    cfg.rqgm.paper.enabled = True
    cfg.rqgm.paper.epoch.rounds = rounds
    cfg.rqgm.paper.anchor.enabled = anchor
    cfg.rqgm.paper.anchor.corpus_path = "paper_anchor_corpus.jsonl"
    cfg.rqgm.paper.anchor.sample_size = 6
    cfg.rqgm.paper.prompt_evolution.enabled = evolve
    cfg.rqgm.governance.enabled = True
    return cfg


def _write_reject_anchor(ckpt):
    cases = [{
        "case_id": f"anchor_{i:03d}", "record_type": "PaperAnchorCase",
        "ground_truth_label": "reject", "label_source": "human_curated",
        "authorship": "human", "manuscript_sha256": f"s{i}", "split": "held_out",
        "expected_behavior": {"accept_recommendation_binary": "reject"},
        # The judge is handed `anchor_case_view` — no label field — so its
        # agreement has to be earned on the MANUSCRIPT. The corpus therefore
        # carries the content the reject label is a judgement OF.
        "manuscript_text": "\\section{Results} The evaluation is weak and the "
                           "claims are unsupported.",
        "results": {},
    } for i in range(6)]
    with (ckpt / "paper_anchor_corpus.jsonl").open("w") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")


class _N:
    def __init__(self):
        self.id = "node_0"
        self.ancestor_ids = []
        self.metrics = {"_scientific_score": 0.5}
        self.has_real_data = True


class _Resp:
    def __init__(self, content):
        self.content = content


class _AdvLLM:
    """A deterministic, .complete-shaped governance LLM for the REAL
    paper_self_preference round (plan 05): routes by prompt to a valid
    attack / defense / judgment so the organic adversary -> Defender ->
    ArtifactJudge -> ValidatedAttackRecord chain produces genuine cross-role
    evidence (replacing the deleted forged bridge)."""

    def __init__(self):
        self.calls = 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        prompt = messages[0]["content"] if messages else ""
        if "ArtifactJudge" in prompt:
            return _Resp(json.dumps(
                {"verdict": "valid", "severity": "high",
                 "rationale": "the reviewer over-accepted an AI draft the "
                              "human anchor rejects"}))
        if "Defender" in prompt:
            return _Resp(json.dumps(
                {"stance": "rebut", "rebuttal_text": "the acceptance is "
                 "anchor-supported", "confidence": 0.4}))
        # adversary (PaperSelfPreferenceAdversary or any exploration type)
        return _Resp(json.dumps(
            {"attack_claim": "the reviewer accepted an AI-authored draft above "
             "the human-anchor bar",
             "target_artifact": {"type": "paper_claim", "ref": "draft"},
             "attack_evidence_refs": [
                 {"path": "rqgm/paper_self_preference_stat.json", "pointer": ""}],
             "severity_claimed": "high", "confidence": 0.8}))


def _run_paper(ckpt, cfg, *, adversary_llm=None):
    from ari.rqgm.paper_runtime import PaperArchiveRuntime

    (ckpt / "nodes_tree.json").write_text("{}", encoding="utf-8")
    mcp = _ScriptedMCP()
    rt = PaperArchiveRuntime(
        cfg, checkpoint_dir=ckpt, mcp=mcp, llm=_mutator_llm,
        reviewer_verdict_fn=_verdict, reviewer_score_fn=_score,
        reviewer_confidence_fn=lambda t: 1.0,
        adversary_llm=adversary_llm,
    )
    rt.run_archive([_N()], {"goal": "g"}, str(ckpt), mcp, "")
    return rt


def _mutator_llm(prompt):
    # The successor carries the paper_reviewer §5.4 clauses VERBATIM, as the
    # real rqgm/prompt_mutator.md meta-prompt requires — otherwise the candidate
    # constitutional gate (_paper_candidate_evaluator) drops it before scoring.
    return ("You are a STRICT academic reviewer. REJECT weak papers. Return "
            "accept_recommendation in {strong_accept, accept, weak_accept, reject}. "
            "Do not override the claim-evidence hard gate. "
            "Do not directly modify frontier scores.")


def _verdict(prompt_text, case):
    """A CONTENT-reading judge (plan 04 §4 / §10 R4): it receives
    ``anchor_case_view``, which has NO ``ground_truth_label``, so its verdict is
    a judgement of the manuscript rather than a copy of the answer key. A STRICT
    reviewer rejects a manuscript that reads weak; the lenient founding reviewer
    accepts everything and so disagrees with this reject-labelled corpus."""
    weak = "weak" in str(case.get("manuscript_text", "")).lower()
    if "strict" in prompt_text.lower():
        return "reject" if weak else "accept"
    return "accept"


def _score(prompt_text, text):
    return min(1.0, 0.15 + 0.05 * text.count("\\section"))


def test_reviewer_hash_coevolves_across_boundaries(tmp_path):
    """Across >= 2 rounds a paper_reviewer candidate is minted, anchor-scored,
    and ADOPTED so the ACTIVE reviewer prompt_hash CHANGES — co-evolution is
    not inert (the P1/Task-14 lesson)."""
    _write_reject_anchor(tmp_path)
    rt = _run_paper(tmp_path, _paper_coevo_cfg(8), adversary_llm=_AdvLLM())
    seq = rt.reviewer_prompt_hash_sequence
    assert len(seq) == 8
    assert len(set(seq)) > 1, f"reviewer hash never changed: {seq}"
    # founding v1 first, a co-evolved successor later
    assert seq[0] != seq[-1]
    # the draft tree deepens to 3 with a signal-bearing reviewer
    from ari.rqgm.paper_archive import read_paper_draft_archive

    recs = read_paper_draft_archive(tmp_path)
    assert max(r["draft_id"].count(".r") + 1 for r in recs) == 3


def test_reviewer_is_reliability_assessable(tmp_path):
    """Each governed reviewer score authors a review_record => paper_reviewer_v1
    is operative (observation_count > 0, non-None reliability), not nominal."""
    from ari.rqgm.governance._reliability import build_reliability_entries
    from ari.rqgm.store import ImmutableAuditLog

    _write_reject_anchor(tmp_path)
    _run_paper(tmp_path, _paper_coevo_cfg(3))
    records = []
    for line in ImmutableAuditLog.read(tmp_path):
        payload = line.get("payload") if isinstance(line.get("payload"), dict) else line
        payload = dict(payload)
        payload.setdefault("record_type", line.get("event_type"))
        records.append(payload)
    reviews = [r for r in records if r.get("record_type") == "review_record"]
    assert reviews, "no review_record authored"
    assert all(r.get("component_id") == "paper_reviewer_v1" for r in reviews)
    assert all(r.get("role") == "paper_reviewer" and r.get("prompt_hash") for r in reviews)
    entries = build_reliability_entries(records)
    v1 = [e for e in entries if e["component_id"] == "paper_reviewer_v1"]
    assert v1 and v1[0]["observation_count"] > 0 and v1[0]["reliability_score"] is not None


def test_reviewer_own_records_are_same_role_excluded(tmp_path):
    """§9/§13: an evidence bundle built AGAINST `paper_reviewer_v1` drops that
    component's OWN `review_record`s with reason `same_role_source` — the records
    inform reliability, never admissibility. Cross-role evidence still admits, so
    this is same-ROLE isolation, not blanket suppression."""
    from ari.rqgm.governance._evidence import (
        EXCLUDE_SAME_ROLE, assemble_evidence_bundle,
    )
    from ari.rqgm.governance._reliability import build_reliability_entries
    from ari.rqgm.store import ImmutableAuditLog

    _write_reject_anchor(tmp_path)
    _run_paper(tmp_path, _paper_coevo_cfg(3))
    records = []
    for line in ImmutableAuditLog.read(tmp_path):
        payload = line.get("payload") if isinstance(line.get("payload"), dict) else line
        payload = dict(payload)
        payload.setdefault("record_type", line.get("event_type"))
        records.append(payload)
    reviews = [r for r in records
               if r.get("record_type") == "review_record"
               and r.get("component_id") == "paper_reviewer_v1"]
    assert reviews, "no review_record authored"

    # a cross-role artifact NAMING the reviewer: admissible, so the exclusion
    # below is proven to be same-ROLE rather than blanket suppression.
    cross = {
        "record_type": "validated_attack", "record_id": "vat_paper_001",
        "epoch_id": reviews[0]["epoch_id"], "component_id": "judge_v1",
        "role": "judge", "target_component_id": "paper_reviewer_v1",
        "source_refs": [],
    }
    by_id = {r["record_id"]: r for r in records if r.get("record_id")}
    by_id[cross["record_id"]] = cross

    # target_role is what the pipeline derives from the reliability entry; pin
    # that it really is "paper_reviewer" (the exclusion fails OPEN if it drifts).
    entry = next(e for e in build_reliability_entries(records)
                 if e["component_id"] == "paper_reviewer_v1")
    assert entry["role"] == "paper_reviewer"

    bundle = assemble_evidence_bundle(
        record_id="evb_paper_001", epoch_id=reviews[0]["epoch_id"],
        clerk_component_id="evidence_clerk_v0",
        target_component_id="paper_reviewer_v1",
        target_role=entry["role"],
        candidate_refs=[r["record_id"] for r in reviews] + ["vat_paper_001"],
        records_by_id=by_id,
    )
    excluded = {i["ref"]: i["reason"] for i in bundle.excluded_items}
    assert all(excluded.get(r["record_id"]) == EXCLUDE_SAME_ROLE for r in reviews)
    assert [i["ref"] for i in bundle.items] == ["vat_paper_001"]
    # ...yet the same records still drive reliability (never admissibility).
    assert entry["observation_count"] == len(reviews)


def test_miscalibrated_reviewer_is_prosecutable_via_the_calibration_channel():
    """§9 (reviewer inside the audit network): a mis-calibrated `paper_reviewer`
    — stated `confidence` far from the `outcome_score` it emits — drives
    `reliability_score` below `RELIABILITY_FLOOR` so `classify_target` returns
    `CLASSIFY_FILE`. This is the exact channel the confidence fabrication had
    disarmed: when `confidence ≡ outcome_score` (the old `else score` default and
    the old constant `1.0`), `calibration_error ≡ 0` and the floor could NEVER be
    reached from calibration. Pure functions, no run."""
    from ari.rqgm.governance._prosecution import (
        CLASSIFY_FILE, RELIABILITY_FLOOR, classify_target,
    )
    from ari.rqgm.governance._reliability import build_reliability_entries

    # A reviewer that asserts full confidence (1.0) while emitting a 0.0 score,
    # and disagrees with ground truth (agreement 0.0) — no attacks involved.
    records = [
        {"record_type": "review_record", "record_id": f"prev_h_{i:04d}",
         "component_id": "paper_reviewer_v1", "role": "paper_reviewer",
         "prompt_hash": "h", "epoch_id": "epoch_000",
         "outcome_score": 0.0, "confidence": 1.0, "agreement": 0.0}
        for i in range(3)
    ]
    entry = next(e for e in build_reliability_entries(records)
                 if e["component_id"] == "paper_reviewer_v1")
    # calibration_error = |1.0 - 0.0| = 1.0 => the calibration part is 0.0
    assert entry["calibration_error"] == 1.0
    # mean([1 - 0/3, agreement 0.0, 1 - calibration 1.0]) = 1/3 < 0.4
    assert entry["reliability_score"] < RELIABILITY_FLOOR
    assert classify_target(entry) == CLASSIFY_FILE

    # CONTROL: a well-calibrated reviewer (confidence == outcome_score) with the
    # SAME low scores is NOT prosecuted by calibration — the fabrication would
    # have made every reviewer look like this, permanently silencing the channel.
    calibrated = [dict(r, confidence=r["outcome_score"]) for r in records]
    cal_entry = next(e for e in build_reliability_entries(calibrated)
                     if e["component_id"] == "paper_reviewer_v1")
    assert cal_entry["calibration_error"] == 0.0


def test_no_confidence_source_emits_no_confidence_and_no_calibration(tmp_path):
    """THE production shape: `cli/projects.py` wires no `confidence_fn`, so the
    reviewer has NO confidence source. Pinned 2026-07-17.

    `stated_confidence()` returned a hardcoded 1.0 until then, and it was
    stamped as `review_record.confidence` in every real run. Because an anchor
    record's `outcome_score` IS its `agreement`, that constant made
    `calibration_error = mean|1.0 - agreement| = 1 - agreement_rate`, so
    `reliability_score = mean[1 - attack_ratio, agreement_rate,
    1 - calibration_error]` averaged ONE signal twice under two names and
    presented it as independent evidence — while gating RELIABILITY_FLOOR.
    Absent => the field is omitted, so `_reliability.py` leaves calibration
    ABSENT and averages only the parts that exist."""
    from ari.rqgm.governance._reliability import build_reliability_entries
    from ari.rqgm.paper_runtime import GovernedPaperReviewer
    from ari.rqgm.store import ImmutableAuditLog

    rev = GovernedPaperReviewer(prompt_text="Score reproducibility only.",
                                prompt_hash="h", checkpoint_dir=str(tmp_path))
    assert rev.stated_confidence() is None

    node = tmp_path / "node1"
    node.mkdir()
    tex = node / "d.tex"
    tex.write_text("% CLAIM:C1\n\\section{A}\nbody", encoding="utf-8")
    # one hit and one miss against ground truth => agreement_rate 0.5
    for agree in (1.0, 0.0):
        rev._append_review_record(node_id="case", outcome_score=agree,
                                  confidence=rev.stated_confidence(),
                                  agreement=agree)
    rev.score(str(tex))

    records = []
    for line in ImmutableAuditLog.read(tmp_path):
        payload = line.get("payload") if isinstance(line.get("payload"), dict) else line
        payload = dict(payload)
        payload.setdefault("record_type", line.get("event_type"))
        records.append(payload)
    reviews = [r for r in records if r.get("record_type") == "review_record"]
    assert reviews and not any("confidence" in r for r in reviews), (
        "a review_record carries a confidence nobody stated")

    entry = [e for e in build_reliability_entries(records)
             if e["component_id"] == "paper_reviewer_v1"][0]
    assert entry["agreement_rate"] == 0.5
    # the restatement is gone: absent, not `1 - agreement_rate` (= 0.5)
    assert entry["calibration_error"] is None
    # and the score averages only the parts that exist: [1 - 0/3, 0.5]
    assert entry["reliability_score"] == 0.75


def test_on_ramp_no_coevolution(tmp_path):
    """rqgm.paper.prompt_evolution.enabled=false: the roles are registered but
    never evolve — the active reviewer hash is constant across rounds."""
    _write_reject_anchor(tmp_path)
    rt = _run_paper(tmp_path, _paper_coevo_cfg(4, evolve=False))
    seq = rt.reviewer_prompt_hash_sequence
    assert len(set(seq)) == 1  # frozen at founding v1, no candidate minted


# ── the reviewer PROMPT drives the draft score (§5.8/§5.9) ───────────────────

def _draft(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_two_different_reviewer_prompts_score_the_same_draft_differently(tmp_path):
    """THE §9 co-evolution proof, and the one that could not pass before: the
    draft score came from `_structural_score(text)`, a prompt-INDEPENDENT
    heuristic, so evolving the reviewer bytes could not move draft selection by
    ANY path — the reviewer half of co-evolution was inert by construction."""
    from ari.rqgm.paper_runtime import GovernedPaperReviewer

    tex = _draft(tmp_path, "d.tex", "% CLAIM:C1\n% CLAIM:C2\n\\section{A}\nx")

    grounding = GovernedPaperReviewer(
        prompt_text="Reward every claim backed by evidence; flag unsupported "
                    "claims. Claim grounding is the only criterion.",
        prompt_hash="h_ground")
    structure = GovernedPaperReviewer(
        prompt_text="Judge the section structure and organization only; a "
                    "complete sectioned paper scores well.",
        prompt_hash="h_struct")

    assert grounding.score(tex) != structure.score(tex), (
        "the reviewer PROMPT is not an input to the draft score")


def test_the_active_prompt_reorders_the_best_belief_winner(tmp_path):
    """Prompt-dependence that MATTERS: the two reviewers disagree about WHICH
    draft is best, so the archive's best-belief selection follows the evolving
    bytes rather than a fixed heuristic.

    Re-pinned 2026-07-17 to the honest contract (plan 03 §4/§5.8): the score
    DIMENSIONS are the venue rubric's, so a prompt emphasises an axis by naming
    the axis the VENUE declared — it can no longer mint a dimension out of its
    own wording, nor zero out the ones it stays silent about. The reorder is
    therefore driven by the two prompts weighting real rubric axes differently,
    which is the property the archive actually depends on."""
    from ari.rqgm.paper_runtime import GovernedPaperReviewer

    # A: claim-rich but leaks environment-specific identifiers.
    # B: leak-free but carries no claims.
    leaky = _draft(tmp_path, "leaky.tex",
                   "% CLAIM:C1\n" * 8 +
                   "Run on /home/u/scratch, hostname node42, cluster name X\n")
    clean = _draft(tmp_path, "clean.tex", "\\section{A}\n" * 6)

    repro = GovernedPaperReviewer(
        prompt_text="Score reproducibility only.", prompt_hash="h1")
    contribution = GovernedPaperReviewer(
        prompt_text="Score contribution and clarity only.", prompt_hash="h2")

    assert repro.score(clean) > repro.score(leaky)
    assert contribution.score(leaky) > contribution.score(clean)


def test_the_injected_score_seam_receives_the_prompt(tmp_path):
    """The seam is `score_fn(prompt_text, text)`: an injected scorer (the hook
    an LLM-backed agent-as-judge plugs into) is never prompt-blind."""
    from ari.rqgm.paper_runtime import GovernedPaperReviewer

    seen = []

    def _spy(prompt_text, text):
        seen.append((prompt_text, text))
        return 0.5

    rev = GovernedPaperReviewer(prompt_text="ACTIVE BYTES", prompt_hash="h",
                                score_fn=_spy)
    assert rev.score(_draft(tmp_path, "d.tex", "body")) == 0.5
    assert seen == [("ACTIVE BYTES", "body")]


def test_a_rubricless_prompt_warns_that_scoring_is_prompt_independent(tmp_path, caplog):
    """A reviewer whose bytes name NO venue-rubric axis is announced. The draft
    is still scored — on the venue rubric's own weighting, which is governance
    data — but the reviewer's own bytes are not an input to it, so evolving them
    cannot move best-belief selection. That fact is stated, never left to be
    discovered (docstring corrected 2026-07-17: the warn no longer implies a
    fall-through to the structural base, which is now reachable only when the
    rubric declares no readable axis at all)."""
    from ari.rqgm.paper_runtime import GovernedPaperReviewer

    rev = GovernedPaperReviewer(prompt_text="xyzzy", prompt_hash="h")
    with caplog.at_level("WARNING"):
        rev.score(_draft(tmp_path, "d.tex", "body"))
    assert any("PROMPT-INDEPENDENT" in r.message for r in caplog.records)


def test_the_score_dimensions_come_from_the_venue_rubric():
    """The score DIMENSIONS are the venue rubric's, derived with the machinery
    plan 03 §4 names for the job — `GENERIC_AXES` + `rubric_to_axes`, composed
    by `dynamic_axes`' own `build_axes_for_run`.

    Pinned 2026-07-17. Until then the axes came from a `_RUBRIC_AXES` table of
    REVIEWER-PROMPT trigger words that no plan sanctioned (`grep dynamic_axes
    paper_runtime.py` returned nothing while §4 named it), which put the axis
    vocabulary inside the evolving bytes it was supposed to judge."""
    from ari.evaluator.dynamic_axes import GENERIC_AXIS_NAMES, rubric_to_axes
    from ari.rqgm.paper_runtime import _venue_rubric, draft_axes

    rubric = _venue_rubric()
    names = [a.name for a in draft_axes(rubric)]
    # the generic floor is always present ...
    assert GENERIC_AXIS_NAMES.issubset(set(names))
    # ... and every venue dimension rides on top of it
    for axis in rubric_to_axes(rubric):
        assert axis.name in names
    # no rubric on disk => the module's own documented degradation: the
    # generic floor alone, never an invented local default
    assert {a.name for a in draft_axes(None)} == set(GENERIC_AXIS_NAMES)


def test_an_axis_no_reader_can_read_is_absent_not_a_constant():
    """`novelty` ("Does the work advance beyond existing approaches?") has no
    deterministic LLM-free read of a .tex file. The honest answer is ABSENT —
    excluded from the composite — never 0.0 and never 1.0. Same discipline
    `_reliability.py` applies to a missing calibration part: average the parts
    that exist, fabricate none of the ones that do not."""
    from ari.evaluator.dynamic_axes import GENERIC_AXES
    from ari.rqgm.paper_runtime import axis_draft_score

    by_name = {a.name: a for a in GENERIC_AXES}
    rich = "% CLAIM:C1\n\\section{A}\n" + "x" * 8000
    assert axis_draft_score(by_name["novelty"], rich) is None
    # an axis a reader CAN read is a bounded [0,1] read, not a sentinel
    read = axis_draft_score(by_name["clarity_of_contribution"], rich)
    assert read is not None and 0.0 <= read <= 1.0


def test_the_founding_prompt_emphasises_only_the_axis_it_names():
    """The reviewer's bytes supply EMPHASIS over the venue's axes, and the
    vocabulary is the RUBRIC's: an axis is emphasised only when the prompt names
    the axis the venue declared. The founding prompt names exactly one
    (`Reproducibility criterion:`, prompts/rqgm/paper_reviewer.md:9).

    Prose that names no rubric axis emphasises nothing — it can no longer
    conjure one. Each string below is a REAL collision the deleted
    prompt-keyword scanner scored as a declared criterion."""
    from ari.prompts import FilesystemPromptLoader
    from ari.rqgm.paper_runtime import _venue_rubric, draft_axes, emphasised_axes

    axes = draft_axes(_venue_rubric())
    text, _ = FilesystemPromptLoader().load_versioned("rqgm/paper_reviewer")
    assert emphasised_axes(text, axes) == {"reproducibility"}

    # the OBJECT of review, not a criterion
    assert emphasised_axes("Review the provided LaTeX section and return JSON.",
                           axes) == set()
    # the review's own prose style, not a property of the manuscript
    assert emphasised_axes("Be concise and technical. No markdown fences.",
                           axes) == set()
    # the reply-shape block names fields, not axes
    assert emphasised_axes(
        "Return JSON with:\n  accept_recommendation: str (one of: accept)\n",
        axes) == set()


def test_the_founding_rubric_discriminates_a_rich_draft_from_a_stub():
    """THE test the shipped scorer could not pass, and the reason best-belief
    selection was degenerate by default: under the SHIPPED founding prompt a
    100-char stub (0 claims, 0 sections) and a rich 8000-char draft (8 claims,
    6 sections) BOTH scored exactly 1.0 — the prompt-sourced reading zeroed
    every axis the founding bytes did not name, leaving `1.0 - sat(leaks/4)`
    alone, which is 1.0 for nearly every draft.

    Re-pinned 2026-07-17: the venue rubric's dimensions all carry weight, the
    prompt only re-weights them, so a rich draft OUTSCORES a stub. The
    reproducibility separation the founding prompt does ask for is kept."""
    from ari.prompts import FilesystemPromptLoader
    from ari.rqgm.paper_runtime import _rubric_draft_score, _venue_rubric, draft_axes

    axes = draft_axes(_venue_rubric())
    text, _ = FilesystemPromptLoader().load_versioned("rqgm/paper_reviewer")
    stub = "\\documentclass{article}\\begin{document}Placeholder.\\end{document}"
    rich = "% CLAIM:C1\n" * 8 + "\\section{S}\n" * 6 + "x" * 8000
    leaky = rich + "Run on /home/u/scratch, hostname node42, cluster name X\n"

    assert _rubric_draft_score(text, rich, axes) > _rubric_draft_score(text, stub, axes)
    # and the ONE criterion the founding bytes actually declare still bites
    assert _rubric_draft_score(text, leaky, axes) < _rubric_draft_score(text, rich, axes)
