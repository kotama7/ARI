"""Strict multimodal review execution and provenance materialization."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

import litellm
from pydantic import BaseModel, ConfigDict, Field

from ari.public.execution import WorkspaceRefV1
from ari.public.visual_review import (
    VisualArtifactRefV1,
    VisualCriteriaProfileV1,
    VisualIssueV1,
    VisualModelUsageV1,
    VisualRegionV1,
    VisualReviewV1,
    canonical_visual_review_digest,
)


_PROMPT_DIR = Path(__file__).with_name("prompts")
_PLACEHOLDER = re.compile(r"\{\{[A-Z0-9_]+\}\}")


class _RawRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class _RawIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_id: str
    severity: Literal["info", "minor", "major", "blocking"]
    message: str = Field(min_length=1, max_length=4_096)
    suggestion: str = Field(default="", max_length=4_096)
    evidence: str = Field(default="", max_length=4_096)
    region: _RawRegion | None = None
    page: int | None = Field(default=None, ge=1, le=100_000)


class _RawReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: float = Field(ge=0, le=1)
    issues: tuple[_RawIssue, ...] = Field(default_factory=tuple, max_length=1_000)
    summary: str = Field(min_length=1, max_length=8_192)


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _model_identity() -> tuple[str, str | None, str | None]:
    model = os.environ.get("ARI_VLM_MODEL") or os.environ.get("VLM_MODEL")
    if not model:
        raise ValueError("ARI_VLM_MODEL must select a visual review model")
    revision = os.environ.get("ARI_MODEL_VLM_REVISION") or None
    provider = os.environ.get("ARI_MODEL_VLM_PROVIDER") or model.split("/", 1)[0]
    return model, revision, provider


def _render_prompt(
    *,
    target_kind: str,
    target_id: str,
    profile: VisualCriteriaProfileV1,
    context: str,
    target_description: str,
) -> bytes:
    template = (_PROMPT_DIR / f"{target_kind}_review.md").read_text(encoding="utf-8")
    replacements = {
        "TARGET_ID": target_id,
        "PROFILE_JSON": json.dumps(profile.model_dump(mode="json"), sort_keys=True),
        "CONTEXT": context[:16_000],
        "TARGET_DESCRIPTION": target_description[:8_000],
    }
    for name, value in replacements.items():
        template = template.replace("{{" + name + "}}", value)
    if _PLACEHOLDER.search(template):
        raise ValueError("visual review prompt has unresolved placeholders")
    payload = template.encode("utf-8")
    if len(payload) > 64 * 1024:
        raise ValueError("visual review prompt exceeds 64 KiB")
    return payload


def _usage(response: Any) -> VisualModelUsageV1:
    usage = getattr(response, "usage", None)

    def _read(name: str) -> int | None:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        return value if isinstance(value, int) and value >= 0 else None

    hidden = getattr(response, "_hidden_params", None)
    cost = hidden.get("response_cost") if isinstance(hidden, dict) else None
    if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0:
        cost = None
    return VisualModelUsageV1(
        input_tokens=_read("prompt_tokens"),
        output_tokens=_read("completion_tokens"),
        cost_usd=float(cost) if cost is not None else None,
        cost_status="reported" if cost is not None else "unavailable",
    )


def _raw_artifact(
    workspace: WorkspaceRefV1,
    *,
    target_id: str,
    iteration: int,
    payload: bytes,
) -> VisualArtifactRefV1:
    digest = _digest(payload)
    safe_target = re.sub(r"[^A-Za-z0-9._-]+", "-", target_id).strip("-")
    path = (
        f".ari-vlm/reviews/{iteration:02d}/{safe_target}/"
        f"{digest.removeprefix('sha256:')}.json"
    )
    workspace.atomic_write_bytes(path, payload)
    return VisualArtifactRefV1(
        role="raw-model-response",
        relative_path=path,
        digest=digest,
        media_type="application/json",
        size_bytes=len(payload),
    )


def failure_review(
    *,
    target_kind: str,
    target_id: str,
    figure_id: str | None,
    source_manifest_digest: str | None,
    artifact: VisualArtifactRefV1,
    context: str,
    profile: VisualCriteriaProfileV1,
    iteration: int,
    status: str,
    error_kind: str,
    error_message: str,
    model: str | None = None,
    model_revision: str | None = None,
    provider: str | None = None,
    prompt_digest: str | None = None,
    raw_response_artifact: VisualArtifactRefV1 | None = None,
    usage: VisualModelUsageV1 | None = None,
) -> VisualReviewV1:
    return VisualReviewV1.create(
        target_kind=target_kind,
        target_id=target_id,
        figure_id=figure_id,
        source_manifest_digest=source_manifest_digest,
        target_artifact=artifact,
        context_digest=canonical_visual_review_digest({"context": context}),
        criteria_profile_id=profile.profile_id,
        criteria_profile_digest=profile.profile_digest,
        iteration=iteration,
        status=status,
        score=None,
        issues=(),
        summary="",
        model=model,
        model_revision=model_revision,
        provider=provider,
        prompt_digest=prompt_digest,
        sampling={"temperature": 0.0},
        usage=usage or VisualModelUsageV1(),
        raw_response_artifact=raw_response_artifact,
        error_kind=error_kind,
        error_message=error_message[:4_096],
    )


async def review_target(
    *,
    workspace: WorkspaceRefV1,
    target_kind: Literal["figure", "table"],
    target_id: str,
    figure_id: str | None,
    source_manifest_digest: str | None,
    artifact: VisualArtifactRefV1,
    payload: bytes,
    media_type: str,
    context: str,
    target_description: str,
    profile: VisualCriteriaProfileV1,
    iteration: int,
    max_output_tokens: int,
) -> VisualReviewV1:
    prompt = _render_prompt(
        target_kind=target_kind,
        target_id=target_id,
        profile=profile,
        context=context,
        target_description=target_description,
    )
    prompt_digest = _digest(prompt)
    try:
        model, model_revision, provider = _model_identity()
    except ValueError as exc:
        return failure_review(
            target_kind=target_kind,
            target_id=target_id,
            figure_id=figure_id,
            source_manifest_digest=source_manifest_digest,
            artifact=artifact,
            context=context,
            profile=profile,
            iteration=iteration,
            status="model-error",
            error_kind="model-unconfigured",
            error_message=str(exc),
            prompt_digest=prompt_digest,
        )

    if media_type.startswith("image/"):
        data_uri = f"data:{media_type};base64,{base64.b64encode(payload).decode('ascii')}"
        content: Any = [
            {"type": "text", "text": prompt.decode("utf-8")},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]
    else:
        try:
            source_text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            return failure_review(
                target_kind=target_kind,
                target_id=target_id,
                figure_id=figure_id,
                source_manifest_digest=source_manifest_digest,
                artifact=artifact,
                context=context,
                profile=profile,
                iteration=iteration,
                status="artifact-error",
                error_kind="non-utf8-table",
                error_message=str(exc),
                model=model,
                model_revision=model_revision,
                provider=provider,
                prompt_digest=prompt_digest,
            )
        content = f"{prompt.decode('utf-8')}\n\nTABLE SOURCE:\n{source_text}"

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.0,
        "max_tokens": max_output_tokens,
        "timeout": 120,
    }
    api_base = os.environ.get("ARI_LLM_API_BASE") or os.environ.get("LLM_API_BASE")
    if api_base:
        kwargs["api_base"] = api_base
    try:
        response = await litellm.acompletion(**kwargs)
    except Exception as exc:
        return failure_review(
            target_kind=target_kind,
            target_id=target_id,
            figure_id=figure_id,
            source_manifest_digest=source_manifest_digest,
            artifact=artifact,
            context=context,
            profile=profile,
            iteration=iteration,
            status="model-error",
            error_kind="model-call-failed",
            error_message=str(exc),
            model=model,
            model_revision=model_revision,
            provider=provider,
            prompt_digest=prompt_digest,
        )
    usage = _usage(response)
    raw = str(response.choices[0].message.content or "").encode("utf-8")
    raw_artifact = _raw_artifact(
        workspace,
        target_id=target_id,
        iteration=iteration,
        payload=raw,
    )
    try:
        if len(raw) > 128 * 1024:
            raise ValueError("model response exceeds 128 KiB")
        parsed = _RawReview.model_validate_json(raw)
        allowed_criteria = {item.criterion_id for item in profile.criteria}
        if any(item.criterion_id not in allowed_criteria for item in parsed.issues):
            raise ValueError("model response names a criterion outside the profile")
    except ValueError as exc:
        return failure_review(
            target_kind=target_kind,
            target_id=target_id,
            figure_id=figure_id,
            source_manifest_digest=source_manifest_digest,
            artifact=artifact,
            context=context,
            profile=profile,
            iteration=iteration,
            status="schema-error",
            error_kind="invalid-structured-output",
            error_message=str(exc),
            model=model,
            model_revision=model_revision,
            provider=provider,
            prompt_digest=prompt_digest,
            raw_response_artifact=raw_artifact,
            usage=usage,
        )

    issues = tuple(
        VisualIssueV1(
            issue_id=f"issue-{index + 1:03d}",
            criterion_id=item.criterion_id,
            severity=item.severity,
            message=item.message,
            suggestion=item.suggestion,
            evidence=item.evidence,
            region=(
                VisualRegionV1(**item.region.model_dump())
                if item.region is not None
                else None
            ),
            page=item.page,
        )
        for index, item in enumerate(parsed.issues)
    )
    return VisualReviewV1.create(
        target_kind=target_kind,
        target_id=target_id,
        figure_id=figure_id,
        source_manifest_digest=source_manifest_digest,
        target_artifact=artifact,
        context_digest=canonical_visual_review_digest({"context": context}),
        criteria_profile_id=profile.profile_id,
        criteria_profile_digest=profile.profile_digest,
        iteration=iteration,
        status="completed",
        score=parsed.score,
        issues=issues,
        summary=parsed.summary,
        model=model,
        model_revision=model_revision,
        provider=provider,
        prompt_digest=prompt_digest,
        sampling={"temperature": 0.0},
        usage=usage,
        raw_response_artifact=raw_artifact,
    )


__all__ = ["failure_review", "review_target"]
