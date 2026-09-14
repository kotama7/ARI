"""The aggregate that answers "is this paper trustworthy?" in one place.

Every integrity check already wrote a finding somewhere; nothing read them
together, so a run could ship a paper containing a fabricated verification
claim and print only DONE eighteen times.
"""
from __future__ import annotations

import json
from pathlib import Path

from ari.pipeline.integrity import build_integrity_report, write_integrity_report


def _ck(tmp_path: Path, **files) -> Path:
    ck = tmp_path / "ck"
    (ck / "evaluation").mkdir(parents=True)
    for name, payload in files.items():
        p = ck / (name.replace("__", "/") + ".json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload))
    return ck


def test_a_check_that_did_not_run_is_null_not_clean(tmp_path):
    """"The check did not run" and "the check found nothing" must not look the
    same — reporting an absent gate as zero findings is how a broken pipeline
    reads as a healthy one."""
    rep = build_integrity_report(_ck(tmp_path))
    assert rep["claim_gate"] is None
    assert rep["artifact_provenance"] is None
    assert rep["refine_insertions"] is None
    assert "claim-evidence gate produced NO report" in " ".join(rep["concerns"])


def test_unverified_assertions_are_counted_separately_from_wrong_ones(tmp_path):
    """A reader asking "how much of this paper is machine-checked?" needs the
    UNVERIFIED count: unknown_formula / claim_id_collision / operand_unresolved
    mean the claim was never checked, which is not the same as checked-and-wrong."""
    ck = _ck(tmp_path, evaluation__claim_evidence_hard_gate_final={
        "status": "failed", "should_block": False,
        "errors": [{"type": "unknown_formula"}] * 7
                  + [{"type": "claim_id_collision"}] * 2
                  + [{"type": "numeric_mismatch"}],
        "warnings": [], "metrics": {"numeric_claim_reproducible_rate": 0.0},
    })
    rep = build_integrity_report(ck)
    assert rep["claim_gate"]["unverified_assertions"] == 9   # not the mismatch
    joined = " ".join(rep["concerns"])
    assert "9 numeric assertion(s) were NOT verified" in joined
    assert "no number in the paper was machine-checked" in joined


def test_an_unrequested_verification_claim_reaches_the_summary(tmp_path):
    """The exact defect that shipped: paper_refine inserted "we independently
    re-verified ... and confirm they agree to within rounding" — a process that
    never happened — and the run printed only DONE."""
    ck = _ck(tmp_path, paper_refine={
        "inserted_sentences": ["a", "b"],
        "unrequested_process_claims": [
            "We independently re-verified each such figure and confirm they agree."],
    })
    rep = build_integrity_report(ck)
    assert rep["refine_insertions"]["unrequested_process_claims"] == 1
    assert any("nobody requested" in c for c in rep["concerns"])


def test_tampered_artifacts_and_ungrounded_ideation_are_raised(tmp_path):
    ck = _ck(
        tmp_path,
        node_provenance_audit={"summary": {"verified": 3, "mismatch": 1}},
        idea={"papers_analyzed": 0, "virsci_integration_status": "router:cheap"},
        related_refs={"count": 8, "s2_available": False, "fallback_used": True},
    )
    rep = build_integrity_report(ck)
    joined = " ".join(rep["concerns"])
    assert "1 artifact(s) mismatch" in joined
    assert "NO prior art" in joined
    assert "keyword fallback" in joined
    assert rep["ideation"]["novelty_grounded"] is False


def test_prior_art_generator_counts_as_grounded_even_with_zero_papers_analyzed(tmp_path):
    """The RQGM PriorArtDifferentiationGenerator only fires
    (virsci_integration_status == '...prior_art') when _root_survey_refs supplied
    non-empty survey_refs — so it IS grounded, even though the idea-skill's own
    papers_analyzed counter (a different path) is 0. Keying solely on
    papers_analyzed raised a false 'NO prior art' concern (observed in a real
    codex e2e whose novelty text cited the seeded refs)."""
    ck = _ck(
        tmp_path,
        idea={"papers_analyzed": 0, "virsci_integration_status": "router:prior_art"},
    )
    rep = build_integrity_report(ck)
    assert rep["ideation"]["novelty_grounded"] is True
    assert not any("NO prior art" in c for c in rep["concerns"])


def test_locked_paper_evidence_takes_precedence_over_stale_prelock_reports(tmp_path):
    ck = _ck(
        tmp_path,
        evaluation__claim_evidence_hard_gate_final={
            "status": "failed", "should_block": True,
            "errors": [{"type": "numeric_mismatch"}], "warnings": [],
            "metrics": {"numeric_claim_reproducible_rate": 0.0},
        },
        evaluation__claim_evidence_hard_gate_locked={
            "status": "warn", "should_block": False,
            "blocking_findings": [], "advisory_findings": [],
            "metrics": {"numeric_claim_reproducible_rate": 1.0},
        },
        evaluation__evidence_grounded_semantic_review_post_refine={
            "status": "revise", "detected_overclaim_count": 4,
            "resolved_overclaim_count": 0, "phase": "post_refine",
        },
        evaluation__evidence_grounded_semantic_review_locked={
            "status": "unavailable", "detected_overclaim_count": 0,
            "resolved_overclaim_count": 0, "phase": "locked",
        },
        paper_claim_links_final={
            "counts": {"anchors": 3, "resolved_anchors": 2,
                       "dropped_declarations": 1},
        },
        paper_claim_links_locked={
            "counts": {"anchors": 4, "resolved_anchors": 4,
                       "dropped_declarations": 0},
        },
    )

    rep = build_integrity_report(ck)

    assert rep["claim_gate"]["numeric_claim_reproducible_rate"] == 1.0
    assert rep["semantic_review"]["phase"] == "locked"
    assert rep["claim_links"]["resolved_anchors"] == 4
    assert not any("unresolved overclaim" in item for item in rep["concerns"])
    assert any("semantic review was unavailable" in item for item in rep["concerns"])


def test_a_clean_run_says_so_and_the_report_is_written(tmp_path, capsys):
    ck = _ck(
        tmp_path,
        evaluation__claim_evidence_hard_gate_final={
            "status": "ok", "should_block": False, "errors": [], "warnings": [],
            "metrics": {"numeric_claim_reproducible_rate": 1.0}},
        node_provenance_audit={"summary": {"verified": 5}},
        idea={"papers_analyzed": 12, "virsci_integration_status": "router:prior_art"},
    )
    rep = write_integrity_report(ck)
    assert rep["concerns"] == []
    assert (ck / "run_integrity.json").is_file()
    assert "no concerns" in capsys.readouterr().out


def test_an_unreadable_artifact_is_never_reported_as_clean(tmp_path):
    ck = _ck(tmp_path)
    (ck / "node_provenance_audit.json").write_text("{not json")
    rep = build_integrity_report(ck)
    assert rep["artifact_provenance"] is not None   # not silently "no findings"


def test_run_integrity_concerns_helper_reads_report(tmp_path):
    """#4: `ari run` reads run_integrity.json's concerns to emit a run-level
    failure signal (and, under ARI_RUN_STRICT_EXIT, a non-zero exit). The pure
    reader returns [] for absent/corrupt reports (no false failure) and the
    concern list otherwise."""
    import json as _j
    from ari.cli.run import _run_integrity_concerns
    ck = tmp_path / "ck"; ck.mkdir()
    assert _run_integrity_concerns(ck) == []                      # absent -> []
    (ck / "run_integrity.json").write_text('not json{')
    assert _run_integrity_concerns(ck) == []                      # corrupt -> []
    (ck / "run_integrity.json").write_text(
        _j.dumps({"concerns": ["1 unresolved overclaim(s) remain in the finalized paper"]}))
    got = _run_integrity_concerns(ck)
    assert got == ["1 unresolved overclaim(s) remain in the finalized paper"]


def test_blocked_build_and_unrun_ors_are_never_clean(tmp_path):
    ck = _ck(
        tmp_path,
        paper_build={
            "status": "blocked",
            "blocking_reasons": ["final revision changed mathematical content"],
        },
    )
    (ck / "workflow.yaml").write_text(
        "pipeline:\n"
        "- stage: ors_generate_rubric\n"
        "  enabled: true\n"
        "- stage: ors_grade\n"
        "  enabled: true\n",
        encoding="utf-8",
    )

    report = build_integrity_report(ck)

    assert report["paper_build"]["status"] == "blocked"
    assert report["ors"]["status"] == "incomplete"
    assert report["ors"]["missing_stages"] == [
        "ors_generate_rubric",
        "ors_grade",
    ]
    concerns = " ".join(report["concerns"])
    assert "paper build status is blocked" in concerns
    assert "enabled ORS stages did not complete" in concerns
