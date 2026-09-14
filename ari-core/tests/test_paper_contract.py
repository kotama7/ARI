"""Digest, lineage, review independence, and finalization invariants."""

from __future__ import annotations

import pytest

from ari.public.paper import (
    PaperArtifactV1,
    PaperBuildV1,
    PaperCompileV1,
    PaperGateSummaryV1,
    PaperModelCallBatchV1,
    PaperModelCallV1,
    PaperNumericCoverageV1,
    PaperRevisionV1,
    parse_paper_build,
    parse_paper_model_call_batch,
)


SHA = "sha256:" + "1" * 64


def _artifact(role: str, path: str | None = None) -> PaperArtifactV1:
    return PaperArtifactV1(
        role=role,
        relative_path=path or f"artifacts/{role}.json",
        digest=SHA,
        media_type="application/json",
        size_bytes=10,
    )


def _revision() -> PaperRevisionV1:
    return PaperRevisionV1.create(
        revision=0,
        reason="initial",
        tex_artifact=_artifact("draft-tex", "paper/revision-00.tex"),
        bib_artifact=_artifact("bibtex", "paper/refs.bib"),
        claim_anchors=("CLAIM:C1:NC1",),
        citation_keys=("source2026",),
        figure_ids=("figure-1",),
        math_digest="sha256:" + "2" * 64,
    )


def _base(**extra):
    values = {
        "build_id": "paper-run-1",
        "run_id": "run-1",
        "build_revision": 0,
        "status": "draft",
        "input_artifacts": tuple(
            _artifact(role)
            for role in (
                "science-data",
                "figure-batch",
                "retrieval-records",
                "ear-manifest",
            )
        ),
        "venue_id": "arxiv",
        "venue_version": "1",
        "template_digest": SHA,
        "rubric_id": "arxiv/v1",
        "rubric_version": "1",
        "rubric_digest": SHA,
        "ear_digest": SHA,
        "revisions": (_revision(),),
    }
    values.update(extra)
    return values


def test_draft_build_is_digest_bound():
    build = PaperBuildV1.create(**_base())
    assert parse_paper_build(build.model_dump(mode="json")) == build
    tampered = build.model_dump(mode="json")
    tampered["venue_id"] = "other"
    with pytest.raises(ValueError, match="digest"):
        parse_paper_build(tampered)


def test_finalized_build_requires_gate_coverage_compile_and_artifacts():
    compile_record = PaperCompileV1.create(
        status="completed",
        commands=(("pdflatex", "-no-shell-escape", "full_paper.tex"),),
        execution_identities=(SHA,),
        log_artifacts=(
            _artifact("compile-stdout", "logs/stdout.log"),
            _artifact("compile-stderr", "logs/stderr.log"),
        ),
        pdf_artifact=_artifact("pdf", "full_paper.pdf"),
        environment_digest=SHA,
    )
    build = PaperBuildV1.create(
        **_base(
            status="finalized",
            gate=PaperGateSummaryV1(
                mode="strict",
                status="pass",
                blocking_error_count=0,
                report_digest=SHA,
            ),
            numeric_coverage=PaperNumericCoverageV1(
                result_mentions=1,
                linked_mentions=1,
                excluded_mentions=0,
                unresolved_anchors=0,
                uncovered_mentions=0,
            ),
            compile=compile_record,
            final_artifacts=(
                _artifact("final-tex", "full_paper.tex"),
                _artifact("bibtex", "refs.bib"),
                _artifact("pdf", "full_paper.pdf"),
            ),
        )
    )
    assert build.status == "finalized"
    with pytest.raises(ValueError, match="numeric coverage"):
        PaperBuildV1.create(
            **_base(
                status="finalized",
                gate=build.gate,
                numeric_coverage=PaperNumericCoverageV1(
                    result_mentions=1,
                    linked_mentions=0,
                    excluded_mentions=0,
                    unresolved_anchors=0,
                    uncovered_mentions=1,
                ),
                compile=compile_record,
                final_artifacts=build.final_artifacts,
            )
        )


def test_revision_lineage_and_block_reason_are_mandatory():
    first = _revision()
    bad_second = PaperRevisionV1.create(
        revision=1,
        parent_revision_digest="sha256:" + "9" * 64,
        reason="refinement",
        tex_artifact=_artifact("draft-tex", "paper/revision-01.tex"),
        math_digest=SHA,
    )
    with pytest.raises(ValueError, match="direct parent"):
        PaperBuildV1.create(**_base(revisions=(first, bad_second)))
    with pytest.raises(ValueError, match="explain"):
        PaperBuildV1.create(**_base(status="blocked"))


def test_model_call_batch_binds_exact_prompt_and_raw_response():
    prompt = _artifact("prompt", "calls/refinement-001/prompt.json")
    raw = _artifact("raw-model-response", "calls/refinement-001/response.txt")
    call = PaperModelCallV1.create(
        call_id="refinement-001",
        purpose="refinement",
        model="provider/model",
        provider="provider",
        prompt_digest=prompt.digest,
        prompt_artifact=prompt,
        raw_response_artifact=raw,
        sampling={"temperature": 0.4},
    )
    batch = PaperModelCallBatchV1.create(
        operation="refinement",
        calls=(call,),
    )
    assert parse_paper_model_call_batch(batch.model_dump(mode="json")) == batch
    tampered = batch.model_dump(mode="json")
    tampered["calls"][0]["model"] = "other/model"
    with pytest.raises(ValueError):
        parse_paper_model_call_batch(tampered)
