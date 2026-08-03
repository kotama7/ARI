"""ScienceData-to-FigureSpec planning and revision lineage tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ari.public.execution import MeasurementRecordV1
from ari.public.figures import parse_figure_batch
from ari.public.science_data import (
    ScienceArtifactRefV1,
    ScienceConfigurationV1,
    ScienceDataV1,
    ScienceDerivedV1,
    ScienceInterpretationV1,
    ScienceMetricSummaryV1,
    ScienceProvenanceV1,
    ScienceRawV1,
    formula_registry_digest,
)
from ari.public.visual_review import (
    VisualArtifactRefV1,
    VisualCriteriaProfileV1,
    VisualCriterionV1,
    VisualIssueV1,
    VisualModelUsageV1,
    VisualReviewBatchV1,
    VisualReviewV1,
    canonical_visual_review_digest,
)

import planning
import server


def _science_file(tmp_path: Path) -> Path:
    tree = ScienceArtifactRefV1(
        relative_path="tree.json",
        digest="sha256:" + "1" * 64,
        media_type="application/json",
        role="experiment-tree",
        size_bytes=12,
    )
    result_refs = []
    configs = []
    for index, value in enumerate((2.0, 1.5), start=1):
        result = ScienceArtifactRefV1(
            relative_path=f"node-{index}/results.json",
            digest="sha256:" + str(index + 1) * 64,
            media_type="application/json",
            role="measurement-set",
            size_bytes=32,
        )
        result_refs.append(result)
        record = MeasurementRecordV1(
            metric_id="latency",
            value=value,
            unit="ms",
            unit_status="declared",
            execution_identity="sha256:" + str(index + 3) * 64,
            execution_attempt_id=f"attempt-{index}",
            execution_status="completed",
            exit_code=0,
        )
        configs.append(
            ScienceConfigurationV1(
                config_id=f"cfg-{index}",
                run_id="run",
                node_id=f"node-{index}",
                rank=index,
                label=f"Configuration {index}",
                source_kind="typed-measurement",
                claim_eligible=True,
                measurements={"latency": value},
                measurement_records=(record,),
                source_artifacts=(tree, result),
            )
        )
    raw = ScienceRawV1.create(
        tree_artifact=tree,
        configurations=tuple(configs),
        node_report_status="missing",
        measurement_status="complete",
    )
    derived = ScienceDerivedV1.create(
        formula_registry_digest=formula_registry_digest(),
        metric_summaries=(
            ScienceMetricSummaryV1(
                metric_id="latency",
                unit="ms",
                minimum=1.5,
                maximum=2.0,
                best_value=1.5,
                count=2,
                direction="lower",
                source_config_ids=("cfg-1", "cfg-2"),
            ),
        ),
    )
    interpretation = ScienceInterpretationV1.create(
        status="unavailable",
        input_raw_digest=raw.raw_digest,
        error_kind="fixture",
        error_message="fixture",
    )
    science = ScienceDataV1.create(
        run_id="run",
        raw=raw,
        derived=derived,
        interpretation=interpretation,
        provenance=ScienceProvenanceV1(
            producer_tool_ref="transform-skill/nodes-to-science-data@v1",
            producer_version="1",
            input_artifacts=(tree, *result_refs),
        ),
    )
    path = tmp_path / "science_data.json"
    path.write_text(json.dumps(science.model_dump(mode="json")), encoding="utf-8")
    return path


class _Response:
    def __init__(self, content: str):
        self.choices = [
            type(
                "Choice",
                (),
                {"message": type("Message", (), {"content": content})()},
            )()
        ]


def test_deterministic_generation_uses_only_native_typed_measurements(tmp_path: Path):
    science = _science_file(tmp_path)
    value = asyncio.run(
        server.generate_figures(
            science_data_path=str(science),
            output_dir=str(tmp_path),
            n_figures=1,
        )
    )
    batch = parse_figure_batch(value)
    manifest = batch.manifests[0]
    assert manifest.planner == "none"
    assert manifest.spec.data == {
        "configuration": ["Configuration 1", "Configuration 2"],
        "latency": [2.0, 1.5],
    }
    assert manifest.spec.value_unit == "ms"
    assert all(not Path(path).is_absolute() for path in batch.figures.values())


def test_llm_can_select_specs_but_cannot_emit_values_code_or_units(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    science = _science_file(tmp_path)
    monkeypatch.setenv("ARI_MODEL_PLOT", "fixture/planner")

    async def valid(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        assert "2.0" not in prompt and "1.5" not in prompt
        return _Response(
            '[{"metric_id":"latency","chart_type":"line","x_mode":"rank"}]'
        )

    monkeypatch.setattr(planning.litellm, "acompletion", valid)
    value = asyncio.run(
        server.generate_figures_llm(
            science_data_path=str(science),
            output_dir=str(tmp_path),
            n_figures=1,
        )
    )
    batch = parse_figure_batch(value)
    manifest = batch.manifests[0]
    assert manifest.planner == "llm-spec-only"
    assert manifest.spec.data["latency"] == [2.0, 1.5]
    assert manifest.spec.value_unit == "ms"
    assert {item.role for item in manifest.artifacts} == {
        "source-data",
        "spec",
        "png",
        "pdf",
        "prompt",
        "raw-planner-response",
    }
    assert not any(item.relative_path.endswith(".py") for item in manifest.artifacts)

    async def malicious(**_kwargs):
        return _Response(
            '[{"metric_id":"latency","chart_type":"line","x_mode":"rank",'
            '"code":"import socket","values":[999]}]'
        )

    monkeypatch.setattr(planning.litellm, "acompletion", malicious)
    with pytest.raises(ValueError, match="closed schema"):
        asyncio.run(
            server.generate_figures_llm(
                science_data_path=str(science),
                output_dir=str(tmp_path),
                n_figures=1,
            )
        )


def test_feedback_revision_is_bounded_and_preserves_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    science = _science_file(tmp_path)
    monkeypatch.setenv("ARI_MODEL_PLOT", "fixture/planner")

    async def plan(**_kwargs):
        return _Response(
            '[{"metric_id":"latency","chart_type":"bar","x_mode":"rank"}]'
        )

    monkeypatch.setattr(planning.litellm, "acompletion", plan)
    first_value = asyncio.run(
        server.generate_figures_llm(
            science_data_path=str(science),
            output_dir=str(tmp_path),
            n_figures=1,
        )
    )
    first = parse_figure_batch(first_value)
    previous_path = tmp_path / "figures_manifest.json"
    previous_path.write_text(json.dumps(first_value), encoding="utf-8")
    parent = first.manifests[0]
    profile = VisualCriteriaProfileV1.create(
        profile_id="figure-test/v1",
        target_kind="figure",
        version="1",
        criteria=(
            VisualCriterionV1(
                criterion_id="readability",
                description="figure is readable",
            ),
        ),
        passing_score=0.7,
    )
    png = next(item for item in parent.artifacts if item.role == "png")
    visual_review = VisualReviewV1.create(
        target_kind="figure",
        target_id=parent.spec.figure_id,
        figure_id=parent.spec.figure_id,
        source_manifest_digest=parent.manifest_digest,
        target_artifact=VisualArtifactRefV1(
            role="review-target",
            relative_path=png.relative_path,
            digest=png.digest,
            media_type=png.media_type,
            size_bytes=png.size_bytes,
        ),
        context_digest=canonical_visual_review_digest({"context": "fixture"}),
        criteria_profile_id=profile.profile_id,
        criteria_profile_digest=profile.profile_digest,
        iteration=0,
        status="completed",
        score=0.4,
        issues=(
            VisualIssueV1(
                issue_id="issue-001",
                criterion_id="readability",
                severity="major",
                message="crowding",
                suggestion="use a line",
            ),
        ),
        summary="revise",
        model="fixture/vlm",
        provider="fixture",
        prompt_digest="sha256:" + "8" * 64,
        sampling={"temperature": 0.0},
        usage=VisualModelUsageV1(),
        raw_response_artifact=VisualArtifactRefV1(
            role="raw-model-response",
            relative_path=".ari-vlm/fixture.json",
            digest="sha256:" + "9" * 64,
            media_type="application/json",
            size_bytes=2,
        ),
    )
    review = VisualReviewBatchV1.create(
        source_batch_digest=first.batch_digest,
        iteration=0,
        reviews=(visual_review,),
        score=0.4,
        failure_count=0,
        issues=(f"[{parent.spec.figure_id}] crowding",),
        suggestions=(f"[{parent.spec.figure_id}] use a line",),
        review_text="revise",
    )

    async def revised(**_kwargs):
        return _Response(
            '[{"metric_id":"latency","chart_type":"line","x_mode":"rank"}]'
        )

    monkeypatch.setattr(planning.litellm, "acompletion", revised)
    second_value = asyncio.run(
        server.generate_figures_llm(
            science_data_path=str(science),
            output_dir=str(tmp_path),
            n_figures=1,
            revision=1,
            previous_batch_path=str(previous_path),
            vlm_feedback=json.dumps(review.model_dump(mode="json")),
        )
    )
    second = parse_figure_batch(second_value)
    child = second.manifests[0]
    assert child.spec.figure_id == parent.spec.figure_id
    assert child.parent_manifest_digest == parent.manifest_digest
    assert child.feedback is not None
    assert child.feedback.issues == ("crowding",)
    assert child.feedback.suggestions == ("use a line",)
    first_pdf = tmp_path / first.figures[parent.spec.figure_id]
    second_pdf = tmp_path / second.figures[child.spec.figure_id]
    assert first_pdf.is_file() and second_pdf.is_file()
    assert first_pdf != second_pdf

    with pytest.raises(ValueError, match=r"\[0, 2\]"):
        asyncio.run(
            server.generate_figures_llm(
                science_data_path=str(science),
                output_dir=str(tmp_path),
                revision=3,
            )
        )


def test_legacy_or_outside_workspace_science_data_fails_closed(tmp_path: Path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text('{"configurations": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="native|explicit legacy"):
        asyncio.run(
            server.generate_figures(
                science_data_path=str(legacy),
                output_dir=str(tmp_path),
            )
        )
    outside = tmp_path.parent / "outside-science.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        asyncio.run(
            server.generate_figures(
                science_data_path=str(outside),
                output_dir=str(tmp_path),
            )
        )
