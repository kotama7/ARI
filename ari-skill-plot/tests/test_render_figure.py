"""Golden corpus for the declarative fixed figure renderer."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ari.public.figures import (
    FigureAxisV1,
    FigureFeedbackV1,
    FigureSourceV1,
    FigureSpecV1,
    FigureUncertaintyV1,
    canonical_figure_digest,
    parse_figure_batch,
    parse_figure_manifest,
    read_legacy_figure_batch,
)

import server
from renderer import build_batch, render_spec


def _spec(chart_type: str = "bar", *, revision: int = 0) -> FigureSpecV1:
    data: dict = {"x": ["a", "b", "c"], "latency": [1.0, 2.0, 3.0]}
    x_field: str | None = "x"
    uncertainty = FigureUncertaintyV1(kind="none")
    if chart_type == "hist":
        data = {"latency": [1.0, 2.0, 2.0, 3.0, 4.0]}
        x_field = None
    elif chart_type == "errorbar":
        data["latency_error"] = [0.1, 0.2, 0.1]
        uncertainty = FigureUncertaintyV1(
            kind="standard-deviation",
            field="latency_error",
        )
    elif chart_type == "heatmap":
        data = {"values": [[1.0, 2.0], [3.0, 4.0]]}
        x_field = None
    return FigureSpecV1.create(
        figure_id="migration-latency",
        revision=revision,
        chart_type=chart_type,
        data=data,
        source=FigureSourceV1(
            artifact_digest="sha256:" + "1" * 64,
            data_digest=canonical_figure_digest(data),
            record_ids=("record-a", "record-b"),
            node_ids=("node-a", "node-b"),
        ),
        x_field=x_field,
        y_field="values" if chart_type == "heatmap" else "latency",
        x_axis=FigureAxisV1(label="Configuration", unit="1"),
        y_axis=FigureAxisV1(label="Latency", unit="ms"),
        value_unit="ms",
        uncertainty=uncertainty,
        title="Benchmark migration",
        caption="Latency by configuration.",
    )


@pytest.mark.parametrize(
    "chart_type",
    ["bar", "line", "scatter", "hist", "errorbar", "heatmap"],
)
def test_renderer_covers_scientific_chart_corpus(tmp_path: Path, chart_type: str):
    spec = _spec(chart_type)
    manifest = server.render_figure(
        {
            "spec": spec.model_dump(mode="json"),
            "workspace": {"root": str(tmp_path)},
            "relative_directory": "figures",
        }
    )
    parsed = parse_figure_manifest(manifest)
    assert parsed.spec.chart_type == chart_type
    assert parsed.spec.source.record_ids == ("record-a", "record-b")
    assert parsed.environment.backend == "agg"
    assert parsed.execution_mode == "declarative-fixed-renderer"
    for artifact in parsed.artifacts:
        payload = (tmp_path / artifact.relative_path).read_bytes()
        assert "sha256:" + hashlib.sha256(payload).hexdigest() == artifact.digest


def test_renderer_is_byte_replayable_in_one_environment(tmp_path: Path):
    request = {
        "spec": _spec("line").model_dump(mode="json"),
        "workspace": {"root": str(tmp_path)},
        "relative_directory": "figures",
    }
    first = server.render_figure(request)
    first_bytes = {
        item["role"]: (tmp_path / item["relative_path"]).read_bytes()
        for item in first["artifacts"]
    }
    second = server.render_figure(request)
    second_bytes = {
        item["role"]: (tmp_path / item["relative_path"]).read_bytes()
        for item in second["artifacts"]
    }
    assert first == second
    assert first_bytes == second_bytes


def test_contract_rejects_missing_unit_nonfinite_empty_and_tampering():
    value = _spec().model_dump(mode="json")
    value["y_axis"]["unit"] = ""
    with pytest.raises(ValueError, match="(?i)string should have at least"):
        FigureSpecV1.model_validate(value)

    value = _spec().model_dump(mode="json")
    value["data"]["latency"][0] = float("nan")
    with pytest.raises(ValueError, match="finite JSON"):
        FigureSpecV1.model_validate(value)

    value = _spec().model_dump(mode="json")
    value["data"] = {}
    with pytest.raises(ValueError, match="empty"):
        FigureSpecV1.model_validate(value)

    value = _spec().model_dump(mode="json")
    value["data"]["latency"][0] = 99.0
    with pytest.raises(ValueError, match="data digest|spec_digest"):
        FigureSpecV1.model_validate(value)


def test_renderer_has_no_generated_code_or_path_escape_surface(tmp_path: Path):
    request = {
        "spec": _spec().model_dump(mode="json"),
        "workspace": {"root": str(tmp_path)},
        "relative_directory": "../escape",
    }
    with pytest.raises(ValueError, match="path|relative"):
        server.render_figure(request)
    request["relative_directory"] = "figures"
    request["code"] = "import socket; socket.create_connection(('example.com', 80))"
    with pytest.raises(ValueError, match="exactly"):
        server.render_figure(request)
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "_run_plot_code" not in source
    assert "subprocess" not in source
    assert "exec(" not in source


def test_feedback_revisions_preserve_parent_and_old_artifacts(tmp_path: Path):
    from ari.public.execution import WorkspaceRefV1

    workspace = WorkspaceRefV1(root=str(tmp_path))
    first = render_spec(_spec(revision=0), workspace=workspace)
    feedback = FigureFeedbackV1.create(
        figure_id=first.spec.figure_id,
        source_manifest_digest=first.manifest_digest,
        review_digest="sha256:" + "2" * 64,
        iteration=1,
        issues=("axis label crowding",),
        suggestions=("use a line chart",),
    )
    second = render_spec(
        _spec("line", revision=1),
        workspace=workspace,
        planner_model="fixture/model",
        planner_model_revision="fixture-r1",
        prompt_payload=b"fixture prompt",
        raw_response_payload=b"[]",
        sampling={"temperature": 0.0},
        feedback=feedback,
        parent_manifest_digest=first.manifest_digest,
    )
    assert second.parent_manifest_digest == first.manifest_digest
    first_pdf = next(item for item in first.artifacts if item.role == "pdf")
    second_pdf = next(item for item in second.artifacts if item.role == "pdf")
    assert first_pdf.relative_path != second_pdf.relative_path
    assert (tmp_path / first_pdf.relative_path).is_file()
    assert (tmp_path / second_pdf.relative_path).is_file()
    batch = build_batch([second])
    assert parse_figure_batch(batch.model_dump(mode="json")) == batch


def test_legacy_batch_reader_is_explicit_and_not_native():
    legacy = read_legacy_figure_batch(
        {"figures": {"f": "/tmp/f.pdf"}, "latex_snippets": {"f": "legacy"}}
    )
    assert legacy.schema_version == "ari.figure-batch/legacy-v0"
    with pytest.raises(ValueError):
        parse_figure_batch(legacy.model_dump(mode="json"))
