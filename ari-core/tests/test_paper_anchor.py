"""Paper-archive anchor utility + epoch winners (paper-archive Task 04;
docs/concepts/rqgm_architecture.md §The paper-archive layer, "The two
anchors"; docs/reference/rqgm_schemas.md §``paper_anchor_corpus.jsonl`` —
the read-only accept/reject anchor).

Unit coverage for ``ari.rqgm.paper_anchor``: the accept/reject binarization and
agreement metric, the deterministic run-fixed held-out split, the
machine-enforced bootstrap-label cap (over the corpus AND the held-out subset,
degrade-to-None), the self-label bar, the required ``label_source``, the
``PaperAnchorPool`` board interop, and the ``paper_utility_policy`` freeze
(the writer IS anchored — a claim-evidence faithfulness descriptor, §5.1
revised 2026-07-16; hash moves iff the identity — including EITHER
label-source mix — moves). No litellm / network import.

Also covers the WRITER's half of the anchor asymmetry: the deterministic
claim-gate faithfulness score, the unfaithfulness bar, and the anchor-board
wiring that makes the writer's anchor OPERATIVE — i.e. reachable by
``adjudicate_motion``'s ``board_score`` — rather than merely computed.
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from ari.rqgm import paper_anchor as pa


def _anchor_cfg(**over):
    a = NS(enabled=True, corpus_path="paper_anchor_corpus.jsonl",
           sample_size=8, max_bootstrap_label_fraction=0.5)
    for k, v in over.items():
        setattr(a, k, v)
    return NS(rqgm=NS(paper=NS(anchor=a)))


def _write_corpus(ckpt, cases):
    p = ckpt / "paper_anchor_corpus.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")
    return p


def _case(i, *, label="reject", source="human_curated", authorship="human",
          split=None):
    c = {
        "case_id": f"anchor_{i:03d}", "record_type": "PaperAnchorCase",
        "ground_truth_label": label, "label_source": source,
        "authorship": authorship, "manuscript_sha256": f"sha{i}",
        "expected_behavior": {"accept_recommendation_binary": label},
        "results": {},
    }
    if split is not None:
        c["split"] = split
    return c


# ── binarization + agreement (§5.4) ─────────────────────────────────────────

def test_binarize_four_levels():
    assert pa.binarize_recommendation("strong_accept") == "accept"
    assert pa.binarize_recommendation("accept") == "accept"
    assert pa.binarize_recommendation("weak_accept") == "accept"  # weak-accept IS accepted
    assert pa.binarize_recommendation("reject") == "reject"
    assert pa.binarize_recommendation("garbage") is None  # unparseable => miss


def test_agreement_metric():
    accept_case = {"ground_truth_label": "accept"}
    reject_case = {"ground_truth_label": "reject"}
    assert pa.paper_reviewer_agreement({"accept_recommendation": "accept"}, accept_case)
    assert pa.paper_reviewer_agreement({"accept_recommendation": "weak_accept"}, accept_case)
    assert pa.paper_reviewer_agreement({"accept_recommendation": "reject"}, reject_case)
    # cross-label fails
    assert not pa.paper_reviewer_agreement({"accept_recommendation": "reject"}, accept_case)
    # schema violation (missing / unparseable) is a miss, never agreement
    assert not pa.paper_reviewer_agreement({}, accept_case)
    assert not pa.paper_reviewer_agreement({"accept_recommendation": "??"}, reject_case)


# ── deterministic held-out split (§5.3) ─────────────────────────────────────

def test_assign_split_deterministic_and_epoch_independent():
    cases = [_case(i) for i in range(10)]
    d = pa.corpus_digest(cases)
    s1 = pa.assign_split(cases, sample_size=4, corpus_digest=d)
    s2 = pa.assign_split(cases, sample_size=4, corpus_digest=d)
    held1 = sorted(c["case_id"] for c in s1 if c["split"] == "held_out")
    held2 = sorted(c["case_id"] for c in s2 if c["split"] == "held_out")
    assert held1 == held2 and len(held1) == 4  # same twice, no epoch input


def test_assign_split_honors_pinned_and_sample_ge_len():
    cases = [_case(0, split="train"), _case(1, split="held_out"),
             _case(2), _case(3)]
    d = pa.corpus_digest(cases)
    out = pa.assign_split(cases, sample_size=10, corpus_digest=d)
    by_id = {c["case_id"]: c["split"] for c in out}
    assert by_id["anchor_000"] == "train"       # pinned honored
    assert by_id["anchor_001"] == "held_out"    # pinned honored
    # sample_size >= len => all free cases held out
    assert by_id["anchor_002"] == "held_out" and by_id["anchor_003"] == "held_out"


# ── bootstrap-label cap (§5.3) — all return None, never raise ───────────────

def test_corpus_level_bootstrap_breach_refuses(tmp_path):
    # 6/10 gate_bootstrap over the corpus at cap 0.5 => refused
    cases = [_case(i, source="gate_bootstrap" if i < 6 else "human_curated")
             for i in range(10)]
    _write_corpus(tmp_path, cases)
    assert pa.load_anchor_corpus(_anchor_cfg(sample_size=8), tmp_path) is None


def test_held_out_level_bootstrap_breach_refuses(tmp_path):
    # Corpus PASSES (4/10 = 0.4) but the held-out sample is bootstrap-heavy:
    # pin the 4 bootstrap cases into held_out plus 2 curated => 4/6 = 0.67 > cap.
    cases = (
        [_case(i, source="gate_bootstrap", split="held_out") for i in range(4)]
        + [_case(4, split="held_out"), _case(5, split="held_out")]
        + [_case(i) for i in range(6, 10)]
    )
    _write_corpus(tmp_path, cases)
    assert pa.load_anchor_corpus(_anchor_cfg(sample_size=6), tmp_path) is None


def test_exactly_at_cap_loads(tmp_path):
    # 3/10 bootstrap overall, held-out balanced => under cap => loads.
    cases = ([_case(i, source="gate_bootstrap") for i in range(3)]
             + [_case(i) for i in range(3, 10)])
    _write_corpus(tmp_path, cases)
    pool = pa.load_anchor_corpus(_anchor_cfg(sample_size=4), tmp_path)
    assert pool is not None and 0 <= pool.label_source_mix["gate_bootstrap"] <= 3


def test_cap_one_loads_fully_self_labelled(tmp_path):
    cases = [_case(i, source="gate_bootstrap") for i in range(6)]
    _write_corpus(tmp_path, cases)
    pool = pa.load_anchor_corpus(
        _anchor_cfg(sample_size=6, max_bootstrap_label_fraction=1.0), tmp_path
    )
    assert pool is not None  # explicit opt-out, fingerprinted


def test_self_label_barred_from_held_out(tmp_path):
    # accept + ai + gate_bootstrap self-labels are train-only.
    self_labels = [
        {**_case(i, label="accept", source="gate_bootstrap", authorship="ai")}
        for i in range(3)
    ]
    curated = [_case(i, label="reject") for i in range(3, 9)]
    _write_corpus(tmp_path, self_labels + curated)
    pool = pa.load_anchor_corpus(
        _anchor_cfg(sample_size=8, max_bootstrap_label_fraction=1.0), tmp_path
    )
    assert pool is not None
    held_ids = set(pool.held_out_ids)
    assert not any(f"anchor_{i:03d}" in held_ids for i in range(3))


def test_missing_label_source_rejected(tmp_path):
    good = _case(0)
    bad = {"case_id": "anchor_001", "ground_truth_label": "reject",
           "manuscript_sha256": "x"}  # no label_source
    _write_corpus(tmp_path, [good, bad])
    pool = pa.load_anchor_corpus(_anchor_cfg(sample_size=8), tmp_path)
    assert pool is not None  # the bad case is dropped, the good one loads
    assert pool.label_source_mix["human_curated"] == 1
    # a corpus of ONLY bad cases => None (on-ramp), never a partial corpus
    _write_corpus(tmp_path, [bad])
    assert pa.load_anchor_corpus(_anchor_cfg(sample_size=8), tmp_path) is None


def test_disabled_and_missing_are_on_ramp(tmp_path):
    _write_corpus(tmp_path, [_case(i) for i in range(4)])
    assert pa.load_anchor_corpus(_anchor_cfg(enabled=False), tmp_path) is None
    assert pa.load_anchor_corpus(
        _anchor_cfg(corpus_path="does_not_exist.jsonl"), tmp_path) is None


def test_eval_namespace_leak_refused(tmp_path):
    cases = [_case(0), {"case_id": "eval_001", "ground_truth_label": "reject",
                        "label_source": "human_curated", "manuscript_sha256": "e"}]
    _write_corpus(tmp_path, cases)
    assert pa.load_anchor_corpus(_anchor_cfg(sample_size=8), tmp_path) is None


# ── PaperAnchorPool board interop (§7) ──────────────────────────────────────

def test_pool_anchor_cases_and_board_score(tmp_path):
    from ari.rqgm.governance._adjudication import anchor_cases, board_score

    cases = [_case(i) for i in range(6)]
    _write_corpus(tmp_path, cases)
    pool = pa.load_anchor_corpus(_anchor_cfg(sample_size=6), tmp_path)
    assert pool is not None
    assert anchor_cases(pool) is pool.anchor_cases
    # cache a per-subject result on each held-out case, then board_score = mean
    for c in pool.anchor_cases:
        c.setdefault("results", {})["revhash"] = 1.0
    score, refs, used = board_score(pool.anchor_cases, ("revhash",), max_cases=6)
    assert score == 1.0 and used == len(pool.anchor_cases)


def test_score_reviewer_on_anchor_helper(tmp_path):
    cases = [_case(i, label="reject") for i in range(6)]
    _write_corpus(tmp_path, cases)
    pool = pa.load_anchor_corpus(_anchor_cfg(sample_size=6), tmp_path)
    # an always-reject reviewer agrees with the reject-labelled sample => 1.0
    acc, refs = pa.score_reviewer_on_anchor(pool, lambda case: "reject")
    assert acc == 1.0 and len(refs) == len(pool.anchor_cases)
    # an always-accept reviewer disagrees => 0.0
    acc2, _ = pa.score_reviewer_on_anchor(pool, lambda case: "accept")
    assert acc2 == 0.0


def test_score_reviewer_on_anchor_abstains_on_a_none_verdict(tmp_path):
    """The no-coverage / miss distinction (plan 04 §5.9). `None` means NO
    VERDICT SOURCE and the case is SKIPPED; scoring it would binarize
    `str(None)` -> "None" -> unparseable -> a MISS, turning "nothing was wired"
    into a 0.0 anchor board and impeaching the reviewer on absent evidence."""
    _write_corpus(tmp_path, [_case(i, label="reject") for i in range(6)])
    pool = pa.load_anchor_corpus(_anchor_cfg(sample_size=6), tmp_path)

    assert pa.score_reviewer_on_anchor(pool, lambda case: None) == (None, [])

    # A PARTIAL verdict source scores only what it judged — never a miss for
    # the cases it abstained on (2 of 6 judged, both agreeing => 1.0, not 0.33).
    judged = {"anchor_000", "anchor_001"}
    acc, refs = pa.score_reviewer_on_anchor(
        pool, lambda c: "reject" if c["case_id"] in judged else None)
    assert acc == 1.0
    assert set(refs) == judged & {c["case_id"] for c in pool.anchor_cases}


# ── the anchor-case view: the label is never an input (§4, §10 R4) ───────────

def test_anchor_case_view_strips_every_label_bearing_field():
    case = _case(0, label="reject")
    case.update({"manuscript_text": "body", "manuscript_ref": "r.tex",
                 "venue": "neurips", "split": "held_out"})
    view = pa.anchor_case_view(case)

    assert set(view) == set(pa.ANCHOR_CASE_VIEW_FIELDS)
    # The manuscript side survives — the judge has something to judge.
    assert view["manuscript_text"] == "body" and view["venue"] == "neurips"
    # Structural, not advisory: the field does not exist to be read.
    for leak in ("ground_truth_label", "expected_behavior", "label_source",
                 "split", "authorship", "results"):
        assert leak not in view
        with pytest.raises(KeyError):
            view[leak]


def test_a_flipped_corpus_scores_identically_for_a_content_reading_judge(tmp_path):
    """THE regression for the answer-key read (plan 04 §10 R4 / §9 test (ii)).

    A fixed judge that reads the MANUSCRIPT must score the same whether the
    corpus labels are flipped or not — its verdict cannot depend on an input it
    never receives. Under the old `anchor_verdict` fallback this failed: the
    verdict WAS `case["ground_truth_label"]`, so accuracy tracked the labels
    perfectly and flipping them changed nothing about the reviewer while keeping
    agreement pinned at 1.0."""
    from ari.rqgm.paper_runtime import GovernedPaperReviewer

    def _content_judge(prompt_text, case):
        return "reject" if "weak" in case["manuscript_text"] else "accept"

    def _acc_for(label):
        ckpt = tmp_path / label
        ckpt.mkdir()
        cases = []
        for i in range(4):
            c = _case(i, label=label)
            c["manuscript_text"] = "weak evaluation" if i % 2 else "strong work"
            cases.append(c)
        _write_corpus(ckpt, cases)
        pool = pa.load_anchor_corpus(_anchor_cfg(sample_size=4), ckpt)
        rev = GovernedPaperReviewer(prompt_text="p", prompt_hash="h",
                                    verdict_fn=_content_judge)
        return pa.score_reviewer_on_anchor(pool, rev.anchor_verdict)[0]

    # Half the manuscripts read weak, so a content judge splits 50/50 either way.
    assert _acc_for("reject") == _acc_for("accept") == 0.5


# ── utility-policy freeze (§5.5) ────────────────────────────────────────────

def test_capture_paper_utility_policy_shape_and_hash():
    cfg = _anchor_cfg(sample_size=8)
    p = pa.capture_paper_utility_policy(
        cfg, corpus_digest="abc", held_out_ids=["anchor_001"],
        label_source_mix={"human_curated": 10, "gate_bootstrap": 0},
        held_out_label_source_mix={"human_curated": 8, "gate_bootstrap": 0},
    )
    # The writer IS anchored (§5.1, revised 2026-07-16): the claim-evidence
    # faithfulness descriptor, not None — so the writer's role can be opened by
    # a real sanction and its PROMPT co-evolves (the coding-domain shape).
    assert isinstance(p["writer_anchor"], dict)
    assert p["writer_anchor"]["metric"] == "claim_evidence_faithfulness_v1"
    assert p["writer_anchor"]["source"] == "claim_evidence_hard_gate"
    assert p["writer_anchor"]["components"] == [
        "execution_grounded_claim_rate",
        "numeric_claim_reproducible_rate",
        "numeric_coverage_rate",
    ]
    assert p["reviewer_score_source"] == "paper_reviewer"
    assert p["agreement_metric"] == "binary_accept_reject_v1"
    assert p["ties_favor_incumbent"] is True
    assert "paper_utility_policy_hash" in p


def test_hash_moves_iff_identity_moves():
    cfg = _anchor_cfg(sample_size=8)

    def cap(mix, held_mix, digest="abc", ids=("anchor_001",)):
        return pa.capture_paper_utility_policy(
            cfg, corpus_digest=digest, held_out_ids=list(ids),
            label_source_mix=mix, held_out_label_source_mix=held_mix,
        )["paper_utility_policy_hash"]

    base = cap({"human_curated": 10, "gate_bootstrap": 0},
               {"human_curated": 8, "gate_bootstrap": 0})
    # re-capturing identical inputs => byte-identical hash (P2, no wall clock)
    assert base == cap({"human_curated": 10, "gate_bootstrap": 0},
                       {"human_curated": 8, "gate_bootstrap": 0})
    # SAME digest-relevant content but a shifted CORPUS label-source mix => different hash
    assert base != cap({"human_curated": 5, "gate_bootstrap": 5},
                       {"human_curated": 8, "gate_bootstrap": 0})
    # a shifted HELD-OUT label-source mix => different hash
    assert base != cap({"human_curated": 10, "gate_bootstrap": 0},
                       {"human_curated": 6, "gate_bootstrap": 2})
    # corpus digest change => different hash
    assert base != cap({"human_curated": 10, "gate_bootstrap": 0},
                       {"human_curated": 8, "gate_bootstrap": 0}, digest="zzz")


# ── the freeze into paper_archive_state (§5.5/§6.3) + resume safety (§8.5) ───


def _freeze_with(ckpt, cfg, *, digest, ids, mix, held_mix):
    """Drive ``PaperArchiveRuntime._freeze_paper_utility_policy`` against a
    stand-in anchor pool, bypassing the heavy __init__ (the method touches only
    ``self.cfg`` and ``self._anchor_pool``)."""
    from ari.rqgm.paper_runtime import PaperArchiveRuntime
    rt = PaperArchiveRuntime.__new__(PaperArchiveRuntime)
    rt.cfg = cfg
    rt._anchor_pool = NS(corpus_digest=digest, held_out_ids=list(ids),
                         label_source_mix=dict(mix),
                         held_out_label_source_mix=dict(held_mix))
    rt._freeze_paper_utility_policy(str(ckpt))


def test_freeze_writes_fingerprint_as_the_policy_hash(tmp_path):
    """§6.3 (as landed): ``paper_epoch_fingerprint`` IS
    ``paper_utility_policy["paper_utility_policy_hash"]`` — the fingerprint is
    the policy hash, and it moves iff the anchor identity moves (§5.5)."""
    from ari.rqgm.paper_runtime import read_paper_archive_state
    cfg = _anchor_cfg(sample_size=8)
    _freeze_with(tmp_path, cfg, digest="d1", ids=("anchor_001",),
                 mix={"human_curated": 10}, held_mix={"human_curated": 8})
    st = read_paper_archive_state(tmp_path)
    assert st is not None
    fp = st["paper_epoch_fingerprint"]
    assert fp == st["paper_utility_policy"]["paper_utility_policy_hash"]

    # flipping sample_size moves the fingerprint (§9 smoke bullet 3)
    _freeze_with(tmp_path, _anchor_cfg(sample_size=4), digest="d1",
                 ids=("anchor_001",), mix={"human_curated": 10},
                 held_mix={"human_curated": 8})
    st2 = read_paper_archive_state(tmp_path)
    assert st2["paper_epoch_fingerprint"] != fp

    # so does a label_source drift toward self-labelling
    _freeze_with(tmp_path, _anchor_cfg(sample_size=4), digest="d1",
                 ids=("anchor_001",), mix={"human_curated": 5, "gate_bootstrap": 5},
                 held_mix={"human_curated": 8})
    st3 = read_paper_archive_state(tmp_path)
    assert st3["paper_epoch_fingerprint"] != st2["paper_epoch_fingerprint"]


def test_resume_unchanged_corpus_is_silent_and_byte_identical(tmp_path, caplog):
    """§8.5: re-freezing an UNCHANGED corpus is idempotent — no warning, the
    fingerprint is byte-identical, and no journal entry is added."""
    import logging
    cfg = _anchor_cfg(sample_size=8)
    _freeze_with(tmp_path, cfg, digest="d1", ids=("anchor_001",),
                 mix={"human_curated": 10}, held_mix={"human_curated": 8})
    from ari.rqgm.paper_runtime import read_paper_archive_state
    first = read_paper_archive_state(tmp_path)["paper_epoch_fingerprint"]

    with caplog.at_level(logging.WARNING, logger="ari.rqgm.paper_runtime"):
        _freeze_with(tmp_path, cfg, digest="d1", ids=("anchor_001",),
                     mix={"human_curated": 10}, held_mix={"human_curated": 8})
    st = read_paper_archive_state(tmp_path)
    assert st["paper_epoch_fingerprint"] == first
    assert "digest mismatch" not in caplog.text
    assert "paper_utility_policy_journal" not in st


def test_resume_mutated_corpus_warns_and_journals_without_flipping_silently(
        tmp_path, caplog):
    """§8.5 / §9 Resume: a corpus swap across resume is DETECTED and announced —
    never a silent mid-run policy flip. The prior policy is preserved in a
    journal so the flip stays diffable, and nothing raises."""
    import logging
    cfg = _anchor_cfg(sample_size=8)
    _freeze_with(tmp_path, cfg, digest="d1", ids=("anchor_001",),
                 mix={"human_curated": 10}, held_mix={"human_curated": 8})
    from ari.rqgm.paper_runtime import read_paper_archive_state
    prior_hash = read_paper_archive_state(tmp_path)["paper_epoch_fingerprint"]

    with caplog.at_level(logging.WARNING, logger="ari.rqgm.paper_runtime"):
        # a mutated corpus: different digest AND a shifted label-source mix
        _freeze_with(tmp_path, cfg, digest="d2", ids=("anchor_002",),
                     mix={"human_curated": 5, "gate_bootstrap": 5},
                     held_mix={"human_curated": 4, "gate_bootstrap": 4})

    st = read_paper_archive_state(tmp_path)
    new_hash = st["paper_epoch_fingerprint"]
    assert new_hash != prior_hash
    assert "digest mismatch" in caplog.text
    assert prior_hash in caplog.text and new_hash in caplog.text
    # the flip is diffable: the superseded policy is journaled, not destroyed
    journal = st["paper_utility_policy_journal"]
    assert journal and journal[-1]["event"] == "policy_digest_mismatch"
    assert (journal[-1]["prior_paper_utility_policy"]["paper_utility_policy_hash"]
            == prior_hash)
    assert journal[-1]["new_paper_utility_policy_hash"] == new_hash


# ── the WRITER's anchor: claim-gate faithfulness (§5.1, rev. 2026-07-16) ────


def _gate(*, claims=0, grounded=0, nums=0, repro=0, targeted=0, covered=0,
          errors=()):
    """A `run_hard_gate(write=False)`-shaped report (the only thing the writer
    anchor reads — the gate itself stays Layer-0 and is never wrapped)."""
    return {
        "errors": list(errors),
        "metrics": {
            "total_claims": claims,
            "execution_grounded_claim_rate": (grounded / claims) if claims else 0.0,
            "numeric_assertions_total": nums,
            "numeric_claim_reproducible_rate": (repro / nums) if nums else 0.0,
            "targeted_result_claims": targeted,
            "numeric_coverage_rate": (covered / targeted) if targeted else 1.0,
        },
    }


def test_writer_faithfulness_folds_the_three_gate_rates():
    # all three rates live and perfect => 1.0
    assert pa.writer_faithfulness_score(
        _gate(claims=4, grounded=4, nums=2, repro=2, targeted=2, covered=2)
    ) == 1.0
    # all three live and zero => 0.0
    assert pa.writer_faithfulness_score(
        _gate(claims=4, grounded=0, nums=2, repro=0, targeted=2, covered=0)
    ) == 0.0
    # the mean of the live rates: grounded 1.0, repro 0.5, coverage 0.0
    assert pa.writer_faithfulness_score(
        _gate(claims=4, grounded=4, nums=2, repro=1, targeted=2, covered=0)
    ) == round((1.0 + 0.5 + 0.0) / 3, 6)


def test_writer_faithfulness_skips_dead_denominators():
    """A paper with no numeric claims is not penalised for a vacuous
    numeric_claim_reproducible_rate — only rates with a live denominator are
    averaged, else an honest qualitative paper would score as an overclaimer."""
    # only the claim rate is live (1.0); the 0.0 numeric rates are vacuous
    assert pa.writer_faithfulness_score(_gate(claims=2, grounded=2)) == 1.0
    # nothing to verify at all => vacuously faithful
    assert pa.writer_faithfulness_score(_gate()) == 1.0
    assert pa.writer_faithfulness_score(None) == 1.0
    assert pa.writer_faithfulness_score({}) == 1.0


def test_draft_is_unfaithful_on_gate_error_or_below_threshold():
    # ANY Layer-0 error finding => unfaithful regardless of the rates
    assert pa.draft_is_unfaithful(
        _gate(claims=1, grounded=1, errors=[{"type": "missing_evidence"}])
    ) is True
    # below the bar => unfaithful; at/above => faithful (strict-below test)
    assert pa.draft_is_unfaithful(_gate(claims=4, grounded=1)) is True   # 0.25
    assert pa.draft_is_unfaithful(_gate(claims=4, grounded=3)) is False  # 0.75
    assert pa.draft_is_unfaithful(_gate(claims=4, grounded=3),
                                  threshold=0.9) is True
    # a vacuously-faithful draft is never sanctioned
    assert pa.draft_is_unfaithful(_gate()) is False


def test_writer_anchor_descriptor_names_the_layer0_gate():
    d = pa.WRITER_ANCHOR_DESCRIPTOR
    assert d["metric"] == pa.WRITER_FAITHFULNESS_METRIC_ID
    assert d["source"] == "claim_evidence_hard_gate"
    assert d["threshold"] == pa.WRITER_FAITHFULNESS_THRESHOLD


# ── the writer anchor is OPERATIVE: it reaches the AnchorBoard ──────────────


def _pool(cases=()):
    return pa.PaperAnchorPool(
        list(cases), corpus_digest="d",
        label_source_mix={"human_curated": 1, "gate_bootstrap": 0},
        held_out_label_source_mix={"human_curated": 1, "gate_bootstrap": 0},
    )


def test_writer_faithfulness_is_readable_by_the_anchor_board():
    """THE anti-inertness unit: `adjudicate_motion` board-scores a motion via
    `board_score(anchor_cases(pool), subject_keys)`. Unless the writer's
    faithfulness lands on the pool as a case keyed by the writer's prompt_hash,
    the writer's board is None, `_bounded_outcome` cannot clamp, and every
    writer motion is dismissed in favour of the incumbent."""
    from ari.rqgm.governance._adjudication import anchor_cases, board_score

    pool = _pool()
    pool.record_writer_faithfulness(prompt_hash="wh1", score=0.0,
                                    epoch_id="epoch_000")
    score, refs, used = board_score(anchor_cases(pool), ("wh1",), max_cases=8)
    assert score == 0.0 and used == 1 and refs
    # and it is board-LOW, i.e. the incumbent cannot be exonerated (§ BOARD_LOW)
    from ari.rqgm.governance._adjudication import BOARD_LOW

    assert score <= BOARD_LOW


def test_writer_board_is_hash_keyed_so_a_successor_never_inherits():
    """Keyed on prompt_hash ALONE, never component_id: one component id spans
    successive prompt versions, so a component-keyed score would leak the
    retired incumbent's faithfulness onto its fresh successor and make it
    instantly impeachable (P-D: erase, don't re-scale)."""
    from ari.rqgm.governance._adjudication import anchor_cases, board_score

    pool = _pool()
    pool.record_writer_faithfulness(prompt_hash="incumbent_hash", score=0.0,
                                    epoch_id="epoch_000")
    # the successor's hash reads NO evidence (board unavailable, not 0.0)
    assert board_score(anchor_cases(pool), ("successor_hash",),
                       max_cases=8) == (None, [], 0)
    # the component id is not a key either
    assert board_score(anchor_cases(pool), ("paper_writer_v1",),
                       max_cases=8) == (None, [], 0)


def test_writer_faithfulness_is_idempotent_within_an_epoch():
    """One case per (epoch, hash): re-recording UPDATES in place, so a resumed
    or re-driven epoch cannot stack duplicate observations of one draft."""
    from ari.rqgm.governance._adjudication import anchor_cases, board_score

    pool = _pool()
    pool.record_writer_faithfulness(prompt_hash="wh", score=1.0, epoch_id="e0")
    pool.record_writer_faithfulness(prompt_hash="wh", score=0.0, epoch_id="e0")
    score, _refs, used = board_score(anchor_cases(pool), ("wh",), max_cases=8)
    assert used == 1 and score == 0.0
    # a DIFFERENT epoch is a separate honest observation (board averages them)
    pool.record_writer_faithfulness(prompt_hash="wh", score=1.0, epoch_id="e1")
    score, _refs, used = board_score(anchor_cases(pool), ("wh",), max_cases=8)
    assert used == 2 and score == 0.5


def test_writer_case_never_contaminates_the_reviewer_anchor():
    """The pool carries two anchor sources. A writer case must never score the
    reviewer: it has no ground_truth_label, so it would count as a MISS and
    dilute the reviewer's agreement with evidence that is not its anchor."""
    from ari.rqgm.governance._adjudication import anchor_cases, board_score

    corpus = [_case(0), _case(1)]
    for c in corpus:
        c["results"] = {"rev_hash": 1.0}
    pool = _pool(corpus)
    pool.record_writer_faithfulness(prompt_hash="wh", score=0.0, epoch_id="e0")
    # the reviewer's board still reads ONLY its own two corpus cases
    score, _refs, used = board_score(anchor_cases(pool), ("rev_hash",),
                                     max_cases=8)
    assert used == 2 and score == 1.0
    # the reviewer-side consumers see the corpus only (no writer case)
    rc = pa.reviewer_anchor_cases(pool)
    assert [c["case_id"] for c in rc] == ["anchor_000", "anchor_001"]
    # ... while the pool as a whole carries the writer case too
    assert len(pool.anchor_cases) == 3


def test_score_reviewer_on_anchor_ignores_writer_cases():
    """The reviewer's held-out accuracy is computed over its corpus only —
    a perfect reviewer stays 1.0 after the writer's anchor lands on the pool."""
    pool = _pool([_case(0), _case(1)])
    acc, refs = pa.score_reviewer_on_anchor(pool, lambda c: "reject")
    assert acc == 1.0 and len(refs) == 2
    pool.record_writer_faithfulness(prompt_hash="wh", score=0.0, epoch_id="e0")
    acc2, refs2 = pa.score_reviewer_on_anchor(pool, lambda c: "reject")
    assert (acc2, refs2) == (acc, refs)


def test_record_writer_faithfulness_never_raises_and_needs_a_hash():
    pool = _pool()
    assert pool.record_writer_faithfulness(prompt_hash="", score=0.0) is None
    assert pool.anchor_cases == []
