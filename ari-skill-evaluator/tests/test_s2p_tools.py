"""Tests for Story2Proposal evaluator additions (Phase D + gate wrapper helpers).

The hard-gate logic itself is tested in ari-core; here we cover the evaluator's
deterministic helpers and the non-blocking no-op path of the semantic review
(no LLM / no ari-core import needed).
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.server import _agg_score, _load_jsonish, _tool_evidence_grounded_semantic_review


def test_agg_score():
    assert _agg_score({"a": 0.5, "b": 1.0}) == 0.75
    assert _agg_score({}) == 0.0
    assert _agg_score({"a": "x", "b": 0.4}) == 0.4


def test_load_jsonish_dict_passthrough():
    assert _load_jsonish({"k": 1}) == {"k": 1}


def test_load_jsonish_json_string():
    assert _load_jsonish('{"k": 2}') == {"k": 2}


def test_load_jsonish_path(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"k": 3}')
    assert _load_jsonish(str(p)) == {"k": 3}


def test_load_jsonish_empty():
    assert _load_jsonish("") == {}
    assert _load_jsonish(None) == {}


def _gate_args(tmp_path):
    paper = tmp_path / "full_paper.tex"
    paper.write_text("The measured value is $99$.\n% CLAIM:C1:NC1\n")
    return {
        "checkpoint_dir": str(tmp_path),
        "paper_path": str(paper),
        "science_data_json": {},
        "phase": "final",
        "policy": {"mode": "strict"},
    }


def test_gate_wrapper_blocks_on_should_block(monkeypatch, tmp_path):
    """final + strict + blocking errors → the wrapper returns EXACTLY {"error": ...}.

    This is the Story2Proposal blocking contract's skill-layer link: the stage
    runner only raises (so finalize_paper is skipped) when the MCP result has the
    error key AND no other keys; the wrapper must therefore return *exactly*
    {"error": ...}, not the report-with-error. (Audit gap: previously untested.)
    """
    import pytest
    pytest.importorskip("ari.public.claim_gate")
    import ari.public.claim_gate as cg
    from src.server import _tool_claim_evidence_hard_gate

    monkeypatch.setattr(cg, "run_hard_gate", lambda *a, **k: {
        "gate": "claim_evidence_hard_gate", "phase": "final", "status": "failed",
        "should_block": True,
        "errors": [{"type": "numeric_mismatch", "numeric_id": "NC1"}], "warnings": [],
    })
    out = asyncio.run(_tool_claim_evidence_hard_gate(_gate_args(tmp_path)))
    assert set(out.keys()) == {"error"}, out          # exactly {"error": ...}
    assert "blocking error" in out["error"]


def test_gate_wrapper_passthrough_when_not_blocking(monkeypatch, tmp_path):
    """warn / non-blocking report → wrapper returns the full report unchanged.

    The draft gate and warn/off mode must never block: the wrapper passes the
    report through (no error key) so finalize_paper still runs.
    """
    import pytest
    pytest.importorskip("ari.public.claim_gate")
    import ari.public.claim_gate as cg
    from src.server import _tool_claim_evidence_hard_gate

    report = {"gate": "claim_evidence_hard_gate", "phase": "final", "status": "warn",
              "should_block": False, "errors": [], "warnings": [{"type": "no_paper_anchor"}]}
    monkeypatch.setattr(cg, "run_hard_gate", lambda *a, **k: report)
    out = asyncio.run(_tool_claim_evidence_hard_gate(_gate_args(tmp_path)))
    assert "error" not in out
    assert out["status"] == "warn" and out["should_block"] is False


def test_semantic_review_noop_when_paper_missing(tmp_path):
    ckpt = tmp_path
    out = asyncio.run(_tool_evidence_grounded_semantic_review({
        "checkpoint_dir": str(ckpt),
        "paper_path": str(ckpt / "does_not_exist.tex"),
    }))
    assert out["stage"] == "evidence_grounded_semantic_review"
    assert out["status"] == "ok"          # non-blocking no-op
    assert out["suggested_revisions"] == []
    assert out["detected_overclaim_count"] == 0
    assert out["human_verified_overclaim_precision"] is None
    # report is written to evaluation/
    assert (ckpt / "evaluation" / "evidence_grounded_semantic_review.json").is_file()


def test_semantic_review_post_refine_delta_unclamped(tmp_path, monkeypatch):
    """A post-refine count INCREASE must surface as a negative resolved count
    (the old max(0, ...) clamp reported it as 0, hiding the regression)."""
    ckpt = tmp_path
    (ckpt / "evaluation").mkdir()
    (ckpt / "evaluation" / "evidence_grounded_semantic_review.json").write_text(
        json.dumps({
            "scores": {"reasoning": 0.6},
            "detected_overclaim_count": 2,
        })
    )
    paper = ckpt / "full_paper.tex"
    paper.write_text("\\section{Results}\nOur kernel is the fastest possible.\n")

    llm_json = json.dumps({
        "scores": {"reasoning": 0.6},
        "warnings": [
            {"type": "overclaim", "section": "results", "message": "claim a"},
            {"type": "overgeneralization", "section": "results", "message": "claim b"},
            {"type": "unsupported_claim", "section": "results", "message": "claim c"},
        ],
        "suggested_revisions": [],
    })

    class _Msg:
        content = llm_json

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    import litellm

    async def fake_acompletion(**kwargs):
        return _Resp()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    out = asyncio.run(_tool_evidence_grounded_semantic_review({
        "checkpoint_dir": str(ckpt),
        "paper_path": str(paper),
        "phase": "post_refine",
    }))
    assert out["detected_overclaim_count"] == 3
    assert out["detected_overclaim_count_prev"] == 2
    assert out["resolved_overclaim_count"] == -1   # regression visible, not clamped
