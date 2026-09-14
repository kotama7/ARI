"""Skill-boundary tests for typed hard-gate and independent semantic review."""

from __future__ import annotations

import asyncio
import json

from ari.public.claim_gate import SemanticFindingV1, SemanticReviewV1
from ari.public.research_contract import canonical_digest
from src.server import (
    _agg_score,
    _load_jsonish,
    _load_prompt_versioned,
    _tool_claim_evidence_hard_gate,
    _tool_evidence_grounded_semantic_review,
)


def test_agg_score_and_jsonish(tmp_path):
    assert _agg_score({"a": 0.5, "b": 1.0}) == 0.75
    assert _agg_score({"a": "x", "b": 0.4}) == 0.4
    assert _load_jsonish({"k": 1}) == {"k": 1}
    assert _load_jsonish('{"k": 2}') == {"k": 2}
    path = tmp_path / "value.json"
    path.write_text('{"k": 3}')
    assert _load_jsonish(str(path)) == {"k": 3}
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


def test_gate_wrapper_blocks_on_typed_should_block(monkeypatch, tmp_path):
    import ari.public.claim_gate as claim_gate

    monkeypatch.setattr(
        claim_gate,
        "run_hard_gate",
        lambda *_args, **_kwargs: {
            "schema_version": "ari.gate-report/v1",
            "should_block": True,
            "blocking_findings": [{"type": "numeric_mismatch"}],
        },
    )
    result = asyncio.run(_tool_claim_evidence_hard_gate(_gate_args(tmp_path)))
    assert set(result) == {"error"}
    assert "blocking finding" in result["error"]


def test_gate_wrapper_passes_nonblocking_report(monkeypatch, tmp_path):
    import ari.public.claim_gate as claim_gate

    report = {
        "schema_version": "ari.gate-report/v1",
        "status": "warn",
        "should_block": False,
        "blocking_findings": [],
        "advisory_findings": [{"type": "no_paper_anchor"}],
    }
    monkeypatch.setattr(claim_gate, "run_hard_gate", lambda *_a, **_k: report)
    assert asyncio.run(_tool_claim_evidence_hard_gate(_gate_args(tmp_path))) == report


def test_semantic_review_missing_paper_is_typed_unavailable(tmp_path):
    result = asyncio.run(
        _tool_evidence_grounded_semantic_review(
            {
                "checkpoint_dir": str(tmp_path),
                "paper_path": str(tmp_path / "missing.tex"),
            }
        )
    )
    parsed = SemanticReviewV1.model_validate(result)
    assert parsed.status == "unavailable"
    assert not parsed.findings
    assert (tmp_path / "evaluation" / "evidence_grounded_semantic_review.json").is_file()


def _write_previous_review(tmp_path):
    _, prompt_digest = _load_prompt_versioned("semantic_review_sys")
    previous = SemanticReviewV1.create(
        phase="initial",
        status="revise",
        model="provider/semantic-model",
        prompt_digest=prompt_digest,
        evidence_digest=canonical_digest({"evidence": 1}),
        scores={"reasoning": 0.6},
        findings=(
            SemanticFindingV1(
                type="overclaim", section="results", message="first"
            ),
            SemanticFindingV1(
                type="unsupported_claim", section="results", message="second"
            ),
        ),
        detected_overclaim_count=2,
        resolved_overclaim_count=0,
    )
    output = tmp_path / "evaluation" / "evidence_grounded_semantic_review.json"
    output.parent.mkdir()
    output.write_text(json.dumps(previous.model_dump(mode="json")))
    return previous


def test_semantic_post_refine_delta_is_unclamped(tmp_path, monkeypatch):
    previous = _write_previous_review(tmp_path)
    paper = tmp_path / "full_paper.tex"
    paper.write_text("\\section{Results}\nThe method is universally best.\n")
    payload = {
        "scores": {"reasoning": 0.6},
        "warnings": [
            {"type": "overclaim", "section": "results", "message": "a"},
            {
                "type": "overgeneralization",
                "section": "results",
                "message": "b",
            },
            {
                "type": "unsupported_claim",
                "section": "results",
                "message": "c",
            },
        ],
        "suggested_revisions": [],
    }

    class Response:
        choices = [type("Choice", (), {"message": type("M", (), {"content": json.dumps(payload)})()})()]

    async def fake(**_kwargs):
        return Response()

    monkeypatch.setattr("litellm.acompletion", fake)
    result = asyncio.run(
        _tool_evidence_grounded_semantic_review(
            {
                "checkpoint_dir": str(tmp_path),
                "paper_path": str(paper),
                "phase": "post_refine",
                "model": "provider/semantic-model",
            }
        )
    )
    parsed = SemanticReviewV1.model_validate(result)
    assert parsed.previous_review_digest == previous.review_digest
    assert parsed.detected_overclaim_count == 3
    assert parsed.resolved_overclaim_count == -1


def test_semantic_failure_never_changes_hard_gate(tmp_path, monkeypatch):
    paper = tmp_path / "full_paper.tex"
    paper.write_text("\\section{Results}\nA claim.\n")
    hard_gate = tmp_path / "gate.json"
    hard_gate.write_text(json.dumps({"legacy": "immutable"}, sort_keys=True))
    before = hard_gate.read_bytes()

    async def fail(**_kwargs):
        raise TimeoutError("review timed out")

    monkeypatch.setattr("litellm.acompletion", fail)
    result = asyncio.run(
        _tool_evidence_grounded_semantic_review(
            {
                "checkpoint_dir": str(tmp_path),
                "paper_path": str(paper),
                "hard_gate_path": str(hard_gate),
                "model": "provider/semantic-model",
            }
        )
    )
    assert result["status"] == "unavailable"
    assert hard_gate.read_bytes() == before
    assert result["hard_gate_report_digest"] == canonical_digest({"legacy": "immutable"})


def test_semantic_uses_dedicated_model_policy(tmp_path, monkeypatch):
    paper = tmp_path / "full_paper.tex"
    paper.write_text("\\section{Results}\nA bounded claim.\n")
    captured = {}

    class Response:
        choices = [type("Choice", (), {"message": type("M", (), {"content": '{"scores":{},"warnings":[],"suggested_revisions":[]}'})()})()]

    async def fake(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("litellm.acompletion", fake)
    monkeypatch.setenv("ARI_MODEL", "legacy/model")
    monkeypatch.setenv("ARI_MODEL_EVAL", "legacy/evaluator")
    monkeypatch.setenv("ARI_MODEL_SEMANTIC_REVIEW", "provider/dedicated")
    result = asyncio.run(
        _tool_evidence_grounded_semantic_review(
            {"checkpoint_dir": str(tmp_path), "paper_path": str(paper)}
        )
    )
    assert captured["model"] == "provider/dedicated"
    assert result["model"] == "provider/dedicated"
