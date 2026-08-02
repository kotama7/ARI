"""Strict LLM spec planning over native ``ScienceDataV1`` evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import litellm

from ari.public.execution import WorkspaceRefV1
from ari.public.figures import (
    FigureAxisV1,
    FigureFeedbackV1,
    FigureSourceV1,
    FigureSpecV1,
    FigureUncertaintyV1,
    canonical_figure_digest,
)
from ari.public.science_data import ScienceDataV1, parse_science_data
from ari.public.visual_review import parse_visual_review_batch


_PROMPT_PATH = Path(__file__).with_name("prompts") / "figure_planner.md"
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")
_ALLOWED_CHARTS = {"bar", "line", "scatter", "hist"}
_ALLOWED_X_MODES = {"configuration", "rank"}


def _bytes_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def load_native_science_data(path: str) -> tuple[ScienceDataV1, str, bytes]:
    payload = Path(path).read_bytes()
    if len(payload) > 64 * 1024 * 1024:
        raise ValueError("science data exceeds the 64 MiB figure input limit")
    try:
        science = parse_science_data(payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("science data must be UTF-8 JSON") from exc
    return science, _bytes_digest(payload), payload


def metric_units(science: ScienceDataV1) -> dict[str, str]:
    units: dict[str, str] = {}
    for config in science.raw.configurations:
        if not config.claim_eligible:
            continue
        for record in config.measurement_records:
            if record.unit_status != "declared" or not record.unit:
                continue
            previous = units.setdefault(record.metric_id, record.unit)
            if previous != record.unit:
                raise ValueError(
                    f"metric {record.metric_id!r} has inconsistent measurement units"
                )
    summary_units = {
        summary.metric_id: summary.unit for summary in science.derived.metric_summaries
    }
    if set(units) != set(summary_units) or any(
        units[key] != summary_units[key] for key in units
    ):
        raise ValueError("figure metric units differ from derived summaries")
    if not units:
        raise ValueError("science data has no claim-eligible unit-bearing measurements")
    return dict(sorted(units.items()))


def _metric_values(
    science: ScienceDataV1,
    metric_id: str,
) -> tuple[list[str], list[int], list[float], tuple[str, ...], tuple[str, ...]]:
    labels: list[str] = []
    ranks: list[int] = []
    values: list[float] = []
    records: list[str] = []
    nodes: list[str] = []
    for config in sorted(science.raw.configurations, key=lambda item: item.rank):
        if not config.claim_eligible or metric_id not in config.measurements:
            continue
        labels.append(config.label or config.config_id)
        ranks.append(config.rank)
        values.append(float(config.measurements[metric_id]))
        records.append(f"{config.config_id}:{metric_id}")
        nodes.append(config.node_id)
    if not values:
        raise ValueError(f"metric {metric_id!r} has no claim-eligible values")
    return labels, ranks, values, tuple(records), tuple(nodes)


def _figure_id(metric_id: str, index: int) -> str:
    slug = _SAFE_ID.sub("-", metric_id).strip("-._") or "metric"
    return f"figure-{index + 1:02d}-{slug}"[:128]


def build_spec(
    *,
    science: ScienceDataV1,
    science_artifact_digest: str,
    metric_id: str,
    unit: str,
    chart_type: str,
    x_mode: str,
    index: int,
    revision: int,
) -> FigureSpecV1:
    labels, ranks, values, record_ids, node_ids = _metric_values(science, metric_id)
    if chart_type == "hist":
        data: dict[str, Any] = {metric_id: values}
        x_field = None
        x_axis = FigureAxisV1(label=metric_id, unit=unit)
        y_axis = FigureAxisV1(label="Count", unit="1")
    else:
        x_field = "configuration" if x_mode == "configuration" else "rank"
        data = {x_field: labels if x_mode == "configuration" else ranks, metric_id: values}
        x_axis = FigureAxisV1(
            label="Configuration" if x_mode == "configuration" else "Execution rank",
            unit="1",
        )
        y_axis = FigureAxisV1(label=metric_id, unit=unit)
    source = FigureSourceV1(
        artifact_digest=science_artifact_digest,
        data_digest=canonical_figure_digest(data),
        record_ids=record_ids,
        node_ids=node_ids,
    )
    caption = (
        f"{metric_id} ({unit}) across {len(values)} claim-eligible configurations; "
        f"observed range {min(values):.6g} to {max(values):.6g}."
    )
    return FigureSpecV1.create(
        figure_id=_figure_id(metric_id, index),
        revision=revision,
        chart_type=chart_type,
        data=data,
        source=source,
        x_field=x_field,
        y_field=metric_id,
        x_axis=x_axis,
        y_axis=y_axis,
        value_unit=unit,
        aggregation="none",
        uncertainty=FigureUncertaintyV1(kind="none"),
        title=f"{metric_id} by configuration",
        caption=caption,
    )


def deterministic_specs(
    science: ScienceDataV1,
    science_artifact_digest: str,
    *,
    revision: int,
    limit: int = 3,
) -> list[FigureSpecV1]:
    units = metric_units(science)
    return [
        build_spec(
            science=science,
            science_artifact_digest=science_artifact_digest,
            metric_id=metric_id,
            unit=unit,
            chart_type="bar",
            x_mode="configuration",
            index=index,
            revision=revision,
        )
        for index, (metric_id, unit) in enumerate(list(units.items())[:limit])
    ]


def _parse_plan(raw: str, units: dict[str, str], limit: int) -> list[dict[str, str]]:
    if len(raw.encode("utf-8")) > 64 * 1024:
        raise ValueError("figure planner response exceeds 64 KiB")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("figure planner returned invalid JSON") from exc
    if not isinstance(value, list) or not value or len(value) > limit:
        raise ValueError("figure planner must return a non-empty bounded array")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "metric_id",
            "chart_type",
            "x_mode",
        }:
            raise ValueError("figure planner item does not match the closed schema")
        metric_id = item.get("metric_id")
        chart_type = item.get("chart_type")
        x_mode = item.get("x_mode")
        if metric_id not in units:
            raise ValueError("figure planner selected an unadmitted metric")
        if chart_type not in _ALLOWED_CHARTS or x_mode not in _ALLOWED_X_MODES:
            raise ValueError("figure planner selected an unsupported rendering option")
        if metric_id in seen:
            raise ValueError("figure planner selected a metric more than once")
        seen.add(metric_id)
        result.append(
            {"metric_id": metric_id, "chart_type": chart_type, "x_mode": x_mode}
        )
    return result


def _render_prompt(
    *,
    units: dict[str, str],
    counts: dict[str, int],
    n_figures: int,
    context: str,
    feedback: str,
) -> bytes:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    values = {
        "N_FIGURES": str(n_figures),
        "METRIC_CATALOG_JSON": json.dumps(
            [
                {"metric_id": metric, "unit": unit, "count": counts[metric]}
                for metric, unit in units.items()
            ],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "EXPERIMENT_CONTEXT": context[:8_000],
        "REVIEW_FEEDBACK": feedback[:8_000],
    }
    for name, replacement in values.items():
        template = template.replace("{{" + name + "}}", replacement)
    if re.search(r"\{\{[A-Z0-9_]+\}\}", template):
        raise ValueError("figure planner prompt has unresolved placeholders")
    payload = template.encode("utf-8")
    if len(payload) > 64 * 1024:
        raise ValueError("figure planner prompt exceeds 64 KiB")
    return payload


async def plan_specs(
    science: ScienceDataV1,
    science_artifact_digest: str,
    *,
    revision: int,
    n_figures: int,
    context: str,
    feedback_text: str,
    required_metric_ids: tuple[str, ...] | None = None,
) -> tuple[list[FigureSpecV1], bytes, bytes, str, str | None, dict[str, Any]]:
    units = metric_units(science)
    if required_metric_ids is not None:
        if len(required_metric_ids) != len(set(required_metric_ids)) or any(
            metric not in units for metric in required_metric_ids
        ):
            raise ValueError("previous figure batch names an unavailable metric")
        units = {metric: units[metric] for metric in required_metric_ids}
    n_figures = min(n_figures, len(units))
    counts = {
        metric: sum(
            1
            for config in science.raw.configurations
            if config.claim_eligible and metric in config.measurements
        )
        for metric in units
    }
    prompt = _render_prompt(
        units=units,
        counts=counts,
        n_figures=n_figures,
        context=context,
        feedback=feedback_text,
    )
    model = (
        os.environ.get("ARI_MODEL_PLOT")
        or os.environ.get("ARI_LLM_MODEL")
        or os.environ.get("LLM_MODEL")
    )
    if not model:
        raise ValueError("ARI_MODEL_PLOT or ARI_LLM_MODEL must select a planner model")
    api_base = os.environ.get("ARI_LLM_API_BASE") or os.environ.get("LLM_API_BASE")
    sampling: dict[str, Any] = {"temperature": 0.0}
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt.decode("utf-8")}],
        "temperature": 0.0,
        "timeout": 120,
    }
    if api_base:
        kwargs["api_base"] = api_base
    response = await litellm.acompletion(**kwargs)
    raw = str(response.choices[0].message.content or "")
    plan = _parse_plan(raw, units, n_figures)
    if required_metric_ids is not None:
        if {item["metric_id"] for item in plan} != set(required_metric_ids):
            raise ValueError("a feedback revision must preserve the prior metric set")
        by_metric = {item["metric_id"]: item for item in plan}
        plan = [by_metric[metric] for metric in required_metric_ids]
    specs = [
        build_spec(
            science=science,
            science_artifact_digest=science_artifact_digest,
            metric_id=item["metric_id"],
            unit=units[item["metric_id"]],
            chart_type=item["chart_type"],
            x_mode=item["x_mode"],
            index=index,
            revision=revision,
        )
        for index, item in enumerate(plan)
    ]
    return (
        specs,
        prompt,
        raw.encode("utf-8"),
        model,
        os.environ.get("ARI_MODEL_PLOT_REVISION") or None,
        sampling,
    )


def parse_feedback(
    value: str,
    *,
    revision: int,
    figure_id: str,
) -> FigureFeedbackV1 | None:
    if revision == 0:
        if value.strip():
            raise ValueError("initial figure revision cannot include feedback")
        return None
    try:
        batch = parse_visual_review_batch(value)
    except ValueError as exc:
        raise ValueError("figure feedback must be a valid ari.visual-review-batch/v1") from exc
    if batch.iteration != revision - 1:
        raise ValueError("figure feedback is not for the direct parent revision")
    review = next(
        (item for item in batch.reviews if item.figure_id == figure_id),
        None,
    )
    if review is None:
        raise ValueError(f"figure feedback lacks review for {figure_id}")
    if review.status == "completed":
        issues = tuple(item.message for item in review.issues)
        suggestions = tuple(
            item.suggestion for item in review.issues if item.suggestion
        )
    else:
        issues = (
            f"{review.status}: {review.error_kind}: {review.error_message}",
        )
        suggestions = ()
    assert review.source_manifest_digest is not None
    return FigureFeedbackV1.create(
        figure_id=figure_id,
        source_manifest_digest=review.source_manifest_digest,
        review_digest=review.review_digest,
        iteration=revision,
        issues=issues,
        suggestions=suggestions,
    )


def workspace_from_output(output_dir: str) -> tuple[WorkspaceRefV1, str]:
    path = Path(output_dir)
    if not path.is_absolute():
        raise ValueError("figure output_dir must be an absolute workspace path")
    path.mkdir(parents=True, exist_ok=True)
    workspace = WorkspaceRefV1(root=str(path))
    return workspace, "figures"


__all__ = [
    "build_spec",
    "deterministic_specs",
    "load_native_science_data",
    "metric_units",
    "parse_feedback",
    "plan_specs",
    "workspace_from_output",
]
