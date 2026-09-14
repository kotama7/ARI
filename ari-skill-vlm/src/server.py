"""Artifact-bound, criteria-versioned visual review MCP server."""

from __future__ import annotations

import asyncio
import hashlib
import io
from typing import Any

from mcp.server.fastmcp import FastMCP
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from ari.public.execution import WorkspaceRefV1
from ari.public.visual_review import (
    VisualArtifactRefV1,
    VisualReviewBatchV1,
    VisualReviewV1,
)
from artifacts import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
    VisualTargetError,
    load_figure_batch,
    manifest_visual_artifact,
    resolve_figure_target,
)
from criteria import get_profile
from review import failure_review, review_target


mcp = FastMCP("vlm-review-skill")

try:
    from ari.public import cost_tracker as _ari_cost_tracker

    _ari_cost_tracker.bootstrap_skill("vlm")
except Exception:
    pass


class ReviewBudgetV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_figures: int = Field(default=20, ge=1, le=100)
    max_total_bytes: int = Field(
        default=100 * 1024 * 1024,
        ge=1,
        le=512 * 1024 * 1024,
    )
    max_concurrency: int = Field(default=2, ge=1, le=4)
    max_model_calls: int = Field(default=20, ge=1, le=100)
    max_output_tokens: int = Field(default=2_048, ge=128, le=8_192)


def _target_description(manifest) -> str:
    spec = manifest.spec
    return (
        f"chart_type={spec.chart_type}; title={spec.title}; caption={spec.caption}; "
        f"x={spec.x_axis.label}[{spec.x_axis.unit}]; "
        f"y={spec.y_axis.label}[{spec.y_axis.unit}]; "
        f"source_data_digest={spec.source.data_digest}"
    )


def _artifact_failure(
    *,
    manifest,
    artifact: VisualArtifactRefV1,
    context: str,
    profile,
    status: str,
    kind: str,
    message: str,
) -> VisualReviewV1:
    return failure_review(
        target_kind="figure",
        target_id=manifest.spec.figure_id,
        figure_id=manifest.spec.figure_id,
        source_manifest_digest=manifest.manifest_digest,
        artifact=artifact,
        context=context,
        profile=profile,
        iteration=manifest.spec.revision,
        status=status,
        error_kind=kind,
        error_message=message,
    )


async def _review_manifest(
    *,
    workspace,
    batch,
    manifest,
    context: str,
    profile,
    max_output_tokens: int,
) -> VisualReviewV1:
    artifact = manifest_visual_artifact(manifest)
    try:
        target = resolve_figure_target(
            workspace,
            batch,
            manifest.spec.figure_id,
        )
    except VisualTargetError as exc:
        return _artifact_failure(
            manifest=manifest,
            artifact=exc.artifact,
            context=context,
            profile=profile,
            status=("limit-error" if exc.kind.startswith("image-") else "artifact-error"),
            kind=exc.kind,
            message=str(exc),
        )
    return await review_target(
        workspace=workspace,
        target_kind="figure",
        target_id=manifest.spec.figure_id,
        figure_id=manifest.spec.figure_id,
        source_manifest_digest=manifest.manifest_digest,
        artifact=artifact,
        payload=target.payload,
        media_type=target.media_type,
        context=context,
        target_description=_target_description(manifest),
        profile=profile,
        iteration=manifest.spec.revision,
        max_output_tokens=max_output_tokens,
    )


@mcp.tool()
async def review_figure(
    figures_manifest_path: str,
    figure_id: str,
    context: str = "",
    criteria_profile_id: str = "figure-publication/v1",
    max_output_tokens: int = 2_048,
) -> dict[str, Any]:
    """Review one figure selected by ID from a verified FigureBatchV1."""

    budget = ReviewBudgetV1(max_output_tokens=max_output_tokens)
    workspace, batch = load_figure_batch(figures_manifest_path)
    manifest = next(
        (item for item in batch.manifests if item.spec.figure_id == figure_id),
        None,
    )
    if manifest is None:
        raise ValueError(f"figure batch has no figure_id {figure_id!r}")
    profile = get_profile(criteria_profile_id, target_kind="figure")
    result = await _review_manifest(
        workspace=workspace,
        batch=batch,
        manifest=manifest,
        context=context,
        profile=profile,
        max_output_tokens=budget.max_output_tokens,
    )
    return result.model_dump(mode="json")


@mcp.tool()
async def review_figures_all(
    figures_manifest_path: str,
    context: str = "",
    criteria_profile_id: str = "figure-publication/v1",
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Review every figure, preserving individual failures and raw evidence."""

    limits = ReviewBudgetV1.model_validate(budget or {})
    workspace, batch = load_figure_batch(figures_manifest_path)
    profile = get_profile(criteria_profile_id, target_kind="figure")
    semaphore = asyncio.Semaphore(limits.max_concurrency)
    cumulative_bytes = 0
    model_calls = 0
    tasks = []

    async def _bounded(manifest):
        async with semaphore:
            return await _review_manifest(
                workspace=workspace,
                batch=batch,
                manifest=manifest,
                context=context,
                profile=profile,
                max_output_tokens=limits.max_output_tokens,
            )

    precomputed: dict[str, VisualReviewV1] = {}
    for index, manifest in enumerate(batch.manifests):
        artifact = manifest_visual_artifact(manifest)
        if index >= limits.max_figures:
            precomputed[manifest.spec.figure_id] = _artifact_failure(
                manifest=manifest,
                artifact=artifact,
                context=context,
                profile=profile,
                status="limit-error",
                kind="max-figures",
                message="figure exceeds the declared batch limit",
            )
            continue
        if cumulative_bytes + artifact.size_bytes > limits.max_total_bytes:
            precomputed[manifest.spec.figure_id] = _artifact_failure(
                manifest=manifest,
                artifact=artifact,
                context=context,
                profile=profile,
                status="limit-error",
                kind="max-total-bytes",
                message="figure exceeds the declared batch byte budget",
            )
            continue
        if model_calls >= limits.max_model_calls:
            precomputed[manifest.spec.figure_id] = _artifact_failure(
                manifest=manifest,
                artifact=artifact,
                context=context,
                profile=profile,
                status="limit-error",
                kind="max-model-calls",
                message="figure exceeds the declared model-call budget",
            )
            continue
        cumulative_bytes += artifact.size_bytes
        model_calls += 1
        tasks.append((manifest.spec.figure_id, asyncio.create_task(_bounded(manifest))))

    completed = {
        figure_id: await task
        for figure_id, task in tasks
    }
    reviews = tuple(
        precomputed.get(manifest.spec.figure_id)
        or completed[manifest.spec.figure_id]
        for manifest in batch.manifests
    )
    failures = sum(item.status != "completed" for item in reviews)
    score = (
        0.0
        if failures
        else min(float(item.score) for item in reviews if item.score is not None)
    )
    issues: list[str] = []
    suggestions: list[str] = []
    summaries: list[str] = []
    for review in reviews:
        if review.status != "completed":
            issues.append(
                f"[{review.target_id}] {review.status}: "
                f"{review.error_kind}: {review.error_message}"
            )
        for issue in review.issues:
            issues.append(f"[{review.target_id}] {issue.message}")
            if issue.suggestion:
                suggestions.append(f"[{review.target_id}] {issue.suggestion}")
        if review.summary:
            summaries.append(f"[{review.target_id}] {review.summary}")
    result = VisualReviewBatchV1.create(
        source_batch_digest=batch.batch_digest,
        iteration=batch.revision,
        reviews=reviews,
        aggregation="minimum-fail-closed",
        score=score,
        failure_count=failures,
        issues=tuple(issues),
        suggestions=tuple(suggestions),
        review_text="\n\n".join(summaries),
    )
    return result.model_dump(mode="json")


def _table_payload(
    workspace: WorkspaceRefV1,
    artifact: VisualArtifactRefV1,
) -> tuple[bytes, str]:
    if artifact.role != "table-source":
        raise ValueError("table artifact must use role=table-source")
    if artifact.size_bytes > MAX_IMAGE_BYTES:
        raise ValueError("table artifact exceeds 20 MiB")
    payload = workspace.read_bytes(artifact.relative_path, max_bytes=MAX_IMAGE_BYTES)
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if len(payload) != artifact.size_bytes or digest != artifact.digest:
        raise ValueError("table artifact bytes differ from the request")
    if artifact.media_type.startswith("image/"):
        try:
            with Image.open(io.BytesIO(payload)) as image:
                image.verify()
            with Image.open(io.BytesIO(payload)) as image:
                width, height = image.size
                image_format = str(image.format or "").upper()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError("table image is corrupt") from exc
        if image_format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("table image format is unsupported")
        if (
            width > MAX_IMAGE_DIMENSION
            or height > MAX_IMAGE_DIMENSION
            or width * height > MAX_IMAGE_PIXELS
        ):
            raise ValueError("table image dimensions exceed policy")
    elif artifact.media_type not in {
        "text/x-tex; charset=utf-8",
        "text/markdown; charset=utf-8",
        "text/plain; charset=utf-8",
    }:
        raise ValueError("table artifact media type is unsupported")
    return payload, artifact.media_type


@mcp.tool()
async def review_table(request: dict[str, Any]) -> dict[str, Any]:
    """Review one content-addressed table artifact under a closed workspace."""

    if not isinstance(request, dict) or set(request) != {
        "workspace",
        "target_id",
        "artifact",
        "context",
        "criteria_profile_id",
        "iteration",
        "max_output_tokens",
    }:
        raise ValueError("review_table request does not match the closed schema")
    workspace = WorkspaceRefV1.model_validate(request["workspace"])
    artifact = VisualArtifactRefV1.model_validate(request["artifact"])
    context = str(request["context"])
    profile = get_profile(str(request["criteria_profile_id"]), target_kind="table")
    iteration = int(request["iteration"])
    if not 0 <= iteration <= 2:
        raise ValueError("table review iteration must be in [0, 2]")
    max_tokens = ReviewBudgetV1(
        max_output_tokens=int(request["max_output_tokens"])
    ).max_output_tokens
    try:
        payload, media_type = _table_payload(workspace, artifact)
    except ValueError as exc:
        result = failure_review(
            target_kind="table",
            target_id=str(request["target_id"]),
            figure_id=None,
            source_manifest_digest=None,
            artifact=artifact,
            context=context,
            profile=profile,
            iteration=iteration,
            status="artifact-error",
            error_kind="table-artifact-invalid",
            error_message=str(exc),
        )
    else:
        result = await review_target(
            workspace=workspace,
            target_kind="table",
            target_id=str(request["target_id"]),
            figure_id=None,
            source_manifest_digest=None,
            artifact=artifact,
            payload=payload,
            media_type=media_type,
            context=context,
            target_description="content-addressed scientific table",
            profile=profile,
            iteration=iteration,
            max_output_tokens=max_tokens,
        )
    return result.model_dump(mode="json")


if __name__ == "__main__":
    mcp.run()
