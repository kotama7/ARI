"""Visual review profile, result, and fail-closed batch contracts."""

from __future__ import annotations

import pytest

from ari.public.visual_review import (
    VisualArtifactRefV1,
    VisualCriteriaProfileV1,
    VisualCriterionV1,
    VisualIssueV1,
    VisualModelUsageV1,
    VisualReviewBatchV1,
    VisualReviewV1,
    canonical_visual_review_digest,
    parse_visual_review,
    parse_visual_review_batch,
)


SHA = "sha256:" + "1" * 64


def _profile():
    return VisualCriteriaProfileV1.create(
        profile_id="figure-test/v1",
        target_kind="figure",
        version="1.0.0",
        criteria=(
            VisualCriterionV1(
                criterion_id="labels",
                description="labels and units are complete",
            ),
        ),
        passing_score=0.7,
    )


def _artifact(role: str = "review-target"):
    return VisualArtifactRefV1(
        role=role,
        relative_path="figure.png" if role == "review-target" else "raw.json",
        digest=SHA,
        media_type="image/png" if role == "review-target" else "application/json",
        size_bytes=10,
    )


def _review(*, score: float = 0.8, iteration: int = 0):
    profile = _profile()
    return VisualReviewV1.create(
        target_kind="figure",
        target_id="figure-1",
        figure_id="figure-1",
        source_manifest_digest="sha256:" + "2" * 64,
        target_artifact=_artifact(),
        context_digest=canonical_visual_review_digest({"context": "fixture"}),
        criteria_profile_id=profile.profile_id,
        criteria_profile_digest=profile.profile_digest,
        iteration=iteration,
        status="completed",
        score=score,
        issues=(
            VisualIssueV1(
                issue_id="issue-001",
                criterion_id="labels",
                severity="minor",
                message="unit is small",
                suggestion="increase label size",
            ),
        ),
        summary="usable",
        model="fixture/vlm",
        model_revision="r1",
        provider="fixture",
        prompt_digest="sha256:" + "3" * 64,
        sampling={"temperature": 0.0},
        usage=VisualModelUsageV1(
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.01,
            cost_status="reported",
        ),
        raw_response_artifact=_artifact("raw-model-response"),
    )


def test_review_and_batch_are_digest_bound():
    review = _review()
    batch = VisualReviewBatchV1.create(
        source_batch_digest="sha256:" + "4" * 64,
        iteration=0,
        reviews=(review,),
        score=0.8,
        failure_count=0,
        issues=("[figure-1] unit is small",),
        suggestions=("[figure-1] increase label size",),
        review_text="usable",
    )
    assert parse_visual_review(review.model_dump(mode="json")) == review
    assert parse_visual_review_batch(batch.model_dump(mode="json")) == batch

    tampered = batch.model_dump(mode="json")
    tampered["score"] = 0.9
    with pytest.raises(ValueError, match="score|digest"):
        parse_visual_review_batch(tampered)


def test_schema_failure_cannot_be_empty_success():
    profile = _profile()
    failed = VisualReviewV1.create(
        target_kind="figure",
        target_id="figure-1",
        figure_id="figure-1",
        source_manifest_digest="sha256:" + "2" * 64,
        target_artifact=_artifact(),
        context_digest="sha256:" + "3" * 64,
        criteria_profile_id=profile.profile_id,
        criteria_profile_digest=profile.profile_digest,
        status="schema-error",
        error_kind="invalid-structured-output",
        error_message="bad JSON",
        raw_response_artifact=_artifact("raw-model-response"),
    )
    assert failed.score is None
    with pytest.raises(ValueError, match="failed visual review"):
        VisualReviewV1.create(
            **{
                **failed.model_dump(
                    mode="json",
                    exclude={"review_digest", "score"},
                ),
                "score": 0.0,
            }
        )


def test_batch_includes_failure_as_zero_score():
    good = _review()
    value = good.model_dump(mode="json")
    value.update(
        {
            "target_id": "figure-2",
            "figure_id": "figure-2",
            "status": "artifact-error",
            "score": None,
            "issues": [],
            "summary": "",
            "model": None,
            "model_revision": None,
            "provider": None,
            "prompt_digest": None,
            "raw_response_artifact": None,
            "error_kind": "digest-mismatch",
            "error_message": "bad bytes",
        }
    )
    value.pop("review_digest")
    failed = VisualReviewV1.create(**value)
    batch = VisualReviewBatchV1.create(
        source_batch_digest="sha256:" + "4" * 64,
        iteration=0,
        reviews=(good, failed),
        score=0.0,
        failure_count=1,
    )
    assert batch.score == 0.0
    assert batch.failure_count == 1


def test_profile_and_cost_status_are_strict():
    with pytest.raises(ValueError, match="unique"):
        VisualCriteriaProfileV1.create(
            profile_id="duplicate/v1",
            target_kind="figure",
            version="1",
            criteria=(
                VisualCriterionV1(criterion_id="x", description="x"),
                VisualCriterionV1(criterion_id="x", description="again"),
            ),
            passing_score=0.5,
        )
    with pytest.raises(ValueError, match="cost status"):
        VisualModelUsageV1(cost_usd=1.0, cost_status="unavailable")
