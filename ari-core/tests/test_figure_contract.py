"""Public scientific figure contract tests."""

from __future__ import annotations

import pytest

from ari.public.figures import (
    FigureArtifactV1,
    FigureAxisV1,
    FigureBatchV1,
    FigureEnvironmentV1,
    FigureFeedbackV1,
    FigureManifestV1,
    FigureSourceV1,
    FigureSpecV1,
    FigureUncertaintyV1,
    canonical_figure_digest,
    parse_figure_batch,
    parse_figure_manifest,
    read_legacy_figure_batch,
)


def _spec(*, revision: int = 0, chart: str = "line") -> FigureSpecV1:
    data = {"rank": [1, 2], "latency": [2.0, 1.5]}
    return FigureSpecV1.create(
        figure_id="latency",
        revision=revision,
        chart_type=chart,
        data=data,
        source=FigureSourceV1(
            artifact_digest="sha256:" + "1" * 64,
            data_digest=canonical_figure_digest(data),
            record_ids=("cfg-1:latency", "cfg-2:latency"),
        ),
        x_field="rank",
        y_field="latency",
        x_axis=FigureAxisV1(label="Rank", unit="1"),
        y_axis=FigureAxisV1(label="Latency", unit="ms"),
        value_unit="ms",
        uncertainty=FigureUncertaintyV1(kind="none"),
    )


def _environment() -> FigureEnvironmentV1:
    return FigureEnvironmentV1.create(
        renderer_version="fixture/v1",
        python_version="3.13",
        matplotlib_version="3.10",
        backend="agg",
        font_family="DejaVu Sans",
        font_digest="sha256:" + "2" * 64,
        platform="fixture",
    )


def _artifacts(*, planned: bool = False) -> tuple[FigureArtifactV1, ...]:
    roles = [
        ("source-data", "source.json", "application/json"),
        ("spec", "spec.json", "application/json"),
        ("png", "figure.png", "image/png"),
        ("pdf", "figure.pdf", "application/pdf"),
    ]
    if planned:
        roles.extend(
            [
                ("prompt", "prompt.txt", "text/plain; charset=utf-8"),
                ("raw-planner-response", "raw.json", "application/json"),
            ]
        )
    return tuple(
        FigureArtifactV1(
            role=role,
            relative_path=path,
            digest="sha256:" + str(index + 3) * 64,
            media_type=media_type,
            size_bytes=1,
        )
        for index, (role, path, media_type) in enumerate(roles)
    )


def _manifest() -> FigureManifestV1:
    return FigureManifestV1.create(
        spec=_spec(),
        environment=_environment(),
        artifacts=_artifacts(),
    )


def test_digest_bound_spec_manifest_and_batch_round_trip():
    manifest = _manifest()
    batch = FigureBatchV1.create(
        revision=0,
        manifests=(manifest,),
        figures={"latency": "figure.pdf"},
        latex_snippets={"latency": "\\label{fig:latency}"},
        figure_kinds={"latency": "line"},
    )
    assert parse_figure_manifest(manifest.model_dump(mode="json")) == manifest
    assert parse_figure_batch(batch.model_dump(mode="json")) == batch

    tampered = batch.model_dump(mode="json")
    tampered["figures"]["latency"] = "other.pdf"
    with pytest.raises(ValueError, match="batch|path"):
        parse_figure_batch(tampered)


def test_source_values_units_and_fields_are_bound():
    value = _spec().model_dump(mode="json")
    value["data"]["latency"][0] = 200.0
    with pytest.raises(ValueError, match="digest"):
        FigureSpecV1.model_validate(value)

    value = _spec().model_dump(mode="json")
    value["y_field"] = "throughput"
    with pytest.raises(ValueError, match="absent|digest"):
        FigureSpecV1.model_validate(value)

    value = _spec().model_dump(mode="json")
    value["y_axis"]["unit"] = ""
    with pytest.raises(ValueError):
        FigureSpecV1.model_validate(value)


def test_feedback_must_bind_the_immediate_parent():
    parent = _manifest()
    feedback = FigureFeedbackV1.create(
        figure_id="latency",
        source_manifest_digest=parent.manifest_digest,
        review_digest="sha256:" + "9" * 64,
        iteration=1,
        issues=("crowding",),
        suggestions=("line chart",),
    )
    child = FigureManifestV1.create(
        spec=_spec(revision=1),
        planner="llm-spec-only",
        planner_model="fixture",
        prompt_digest="sha256:" + "8" * 64,
        sampling={"temperature": 0.0},
        feedback=feedback,
        parent_manifest_digest=parent.manifest_digest,
        environment=_environment(),
        artifacts=_artifacts(planned=True),
    )
    assert child.feedback is not None

    value = child.model_dump(mode="json")
    value["parent_manifest_digest"] = "sha256:" + "7" * 64
    with pytest.raises(ValueError, match="feedback|digest"):
        FigureManifestV1.model_validate(value)


def test_legacy_reader_cannot_be_confused_with_native_batch():
    legacy = read_legacy_figure_batch({"figures": {"f": "/tmp/f.pdf"}})
    assert legacy.schema_version == "ari.figure-batch/legacy-v0"
    with pytest.raises(ValueError):
        parse_figure_batch(legacy.model_dump(mode="json"))
