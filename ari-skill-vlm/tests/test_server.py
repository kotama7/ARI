"""Artifact, structured-output, budget, and lineage tests for VLM review."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from ari.public.figures import (
    FigureArtifactV1,
    FigureAxisV1,
    FigureBatchV1,
    FigureEnvironmentV1,
    FigureManifestV1,
    FigureSourceV1,
    FigureSpecV1,
    canonical_figure_digest,
)
from ari.public.visual_review import (
    VisualArtifactRefV1,
    parse_visual_review,
    parse_visual_review_batch,
)

from src.criteria import PROFILES, get_profile
from src.server import review_figure, review_figures_all, review_table


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _png(*, width: int = 8, height: int = 8) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (width, height), color="white").save(stream, format="PNG")
    return stream.getvalue()


def _environment() -> FigureEnvironmentV1:
    return FigureEnvironmentV1.create(
        renderer_version="fixture/v1",
        python_version="3.13",
        matplotlib_version="3.10",
        backend="agg",
        font_family="DejaVu Sans",
        font_digest="sha256:" + "1" * 64,
        platform="fixture",
    )


def _batch_file(
    root: Path,
    *,
    count: int = 1,
    revision: int = 0,
    tamper_id: str | None = None,
    corrupt_id: str | None = None,
    declared_size: int | None = None,
) -> tuple[Path, FigureBatchV1]:
    manifests = []
    figures = {}
    snippets = {}
    kinds = {}
    for index in range(count):
        figure_id = f"figure-{index + 1}"
        data = {"rank": [1, 2], "latency": [2.0, 1.5]}
        spec = FigureSpecV1.create(
            figure_id=figure_id,
            revision=revision,
            chart_type="line",
            data=data,
            source=FigureSourceV1(
                artifact_digest="sha256:" + "2" * 64,
                data_digest=canonical_figure_digest(data),
                record_ids=(f"record-{index}",),
            ),
            x_field="rank",
            y_field="latency",
            x_axis=FigureAxisV1(label="Rank", unit="1"),
            y_axis=FigureAxisV1(label="Latency", unit="ms"),
            value_unit="ms",
            title="Latency",
            caption="Latency across two configurations.",
        )
        directory = root / "figures" / f"{revision:02d}" / figure_id
        directory.mkdir(parents=True, exist_ok=True)
        png_payload = b"not a png" if corrupt_id == figure_id else _png()
        png_path = directory / f"{figure_id}.png"
        png_path.write_bytes(png_payload)
        pdf_payload = b"%PDF fixture"
        pdf_path = directory / f"{figure_id}.pdf"
        pdf_path.write_bytes(pdf_payload)
        source_payload = json.dumps(data, sort_keys=True).encode()
        spec_payload = json.dumps(spec.model_dump(mode="json"), sort_keys=True).encode()
        source_path = directory / "source.json"
        spec_path = directory / "spec.json"
        source_path.write_bytes(source_payload)
        spec_path.write_bytes(spec_payload)
        def relative(path: Path) -> str:
            return path.relative_to(root).as_posix()
        png_digest = _digest(png_payload)
        if tamper_id == figure_id:
            png_digest = "sha256:" + "f" * 64
        artifacts = (
            FigureArtifactV1(
                role="source-data",
                relative_path=relative(source_path),
                digest=_digest(source_payload),
                media_type="application/json",
                size_bytes=len(source_payload),
            ),
            FigureArtifactV1(
                role="spec",
                relative_path=relative(spec_path),
                digest=_digest(spec_payload),
                media_type="application/json",
                size_bytes=len(spec_payload),
            ),
            FigureArtifactV1(
                role="png",
                relative_path=relative(png_path),
                digest=png_digest,
                media_type="image/png",
                size_bytes=(declared_size if declared_size is not None else len(png_payload)),
            ),
            FigureArtifactV1(
                role="pdf",
                relative_path=relative(pdf_path),
                digest=_digest(pdf_payload),
                media_type="application/pdf",
                size_bytes=len(pdf_payload),
            ),
        )
        manifest = FigureManifestV1.create(
            spec=spec,
            environment=_environment(),
            artifacts=artifacts,
        )
        manifests.append(manifest)
        figures[figure_id] = relative(pdf_path)
        snippets[figure_id] = f"\\label{{fig:{figure_id}}}"
        kinds[figure_id] = "line"
    batch = FigureBatchV1.create(
        revision=revision,
        manifests=tuple(manifests),
        figures=figures,
        latex_snippets=snippets,
        figure_kinds=kinds,
    )
    path = root / "figures_manifest.json"
    path.write_text(json.dumps(batch.model_dump(mode="json")), encoding="utf-8")
    return path, batch


def _response(score: float = 0.8, *, issue: str = ""):
    issues = []
    if issue:
        issues.append(
            {
                "criterion_id": "readability",
                "severity": "major",
                "message": issue,
                "suggestion": "increase label size",
                "evidence": "labels are visibly small",
                "region": None,
                "page": None,
            }
        )
    content = json.dumps(
        {"score": score, "issues": issues, "summary": "reviewed"}
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        _hidden_params={"response_cost": 0.0125},
    )


@pytest.fixture(autouse=True)
def _model_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARI_VLM_MODEL", "fixture/vision")
    monkeypatch.setenv("ARI_MODEL_VLM_REVISION", "fixture-r1")


@pytest.mark.asyncio
async def test_single_review_binds_artifact_profile_model_and_raw_response(tmp_path: Path):
    path, batch = _batch_file(tmp_path)
    with patch("src.review.litellm.acompletion", AsyncMock(return_value=_response())):
        result = await review_figure(str(path), "figure-1", context="benchmark")
    review = parse_visual_review(result)
    assert review.status == "completed"
    assert review.source_manifest_digest == batch.manifests[0].manifest_digest
    assert review.target_artifact.digest == next(
        item.digest for item in batch.manifests[0].artifacts if item.role == "png"
    )
    assert review.criteria_profile_id == "figure-publication/v1"
    assert review.model == "fixture/vision"
    assert review.model_revision == "fixture-r1"
    assert review.usage.cost_usd == 0.0125
    assert review.raw_response_artifact is not None
    raw_path = tmp_path / review.raw_response_artifact.relative_path
    assert raw_path.is_file()
    assert "base64" not in raw_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '```json\n{"score":0.8,"issues":[],"summary":"x"}\n```',
        '{"score":0.8,"issues":[],"summary":"x","extra":true}',
        '{"score":0.8,"issues":[{"criterion_id":"invented","severity":"minor",'
        '"message":"x","suggestion":"","evidence":"","region":null,"page":null}],'
        '"summary":"x"}',
    ],
)
async def test_schema_invalid_response_is_typed_failure_not_empty_success(
    tmp_path: Path,
    content: str,
):
    path, _ = _batch_file(tmp_path)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=None,
        _hidden_params={},
    )
    with patch("src.review.litellm.acompletion", AsyncMock(return_value=response)):
        result = await review_figure(str(path), "figure-1")
    review = parse_visual_review(result)
    assert review.status == "schema-error"
    assert review.score is None
    assert review.raw_response_artifact is not None


@pytest.mark.asyncio
async def test_batch_minimum_and_individual_reviews_are_preserved(tmp_path: Path):
    path, batch = _batch_file(tmp_path, count=3)
    responses = [_response(0.9), _response(0.4, issue="text overflow"), _response(0.8)]
    with patch(
        "src.review.litellm.acompletion",
        AsyncMock(side_effect=responses),
    ) as call:
        result = await review_figures_all(str(path), context="benchmark")
    review_batch = parse_visual_review_batch(result)
    assert review_batch.source_batch_digest == batch.batch_digest
    assert review_batch.score == 0.4
    assert review_batch.failure_count == 0
    assert len(review_batch.reviews) == 3
    assert "[figure-2] text overflow" in review_batch.issues
    assert call.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture_kwargs,error_kind",
    [
        ({"tamper_id": "figure-1"}, "artifact-digest-mismatch"),
        ({"corrupt_id": "figure-1"}, "corrupt-image"),
        ({"declared_size": 21 * 1024 * 1024}, "image-too-large"),
    ],
)
async def test_invalid_artifact_fails_without_model_call(
    tmp_path: Path,
    fixture_kwargs: dict,
    error_kind: str,
):
    path, _ = _batch_file(tmp_path, **fixture_kwargs)
    with patch("src.review.litellm.acompletion", AsyncMock()) as call:
        result = await review_figures_all(str(path))
    batch = parse_visual_review_batch(result)
    assert batch.score == 0.0
    assert batch.failure_count == 1
    assert batch.reviews[0].error_kind == error_kind
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_budget_keeps_each_skipped_failure(tmp_path: Path):
    path, _ = _batch_file(tmp_path, count=3)
    with patch("src.review.litellm.acompletion", AsyncMock(return_value=_response())) as call:
        result = await review_figures_all(
            str(path),
            budget={
                "max_figures": 1,
                "max_total_bytes": 100 * 1024 * 1024,
                "max_concurrency": 1,
                "max_model_calls": 1,
                "max_output_tokens": 512,
            },
        )
    batch = parse_visual_review_batch(result)
    assert batch.failure_count == 2
    assert batch.score == 0.0
    assert [item.status for item in batch.reviews] == [
        "completed",
        "limit-error",
        "limit-error",
    ]
    assert call.await_count == 1


@pytest.mark.asyncio
async def test_model_failure_and_missing_model_are_honest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    path, _ = _batch_file(tmp_path)
    with patch(
        "src.review.litellm.acompletion",
        AsyncMock(side_effect=RuntimeError("offline")),
    ):
        failed = parse_visual_review(await review_figure(str(path), "figure-1"))
    assert failed.status == "model-error"
    assert failed.error_kind == "model-call-failed"

    monkeypatch.delenv("ARI_VLM_MODEL")
    monkeypatch.delenv("VLM_MODEL", raising=False)
    missing = parse_visual_review(await review_figure(str(path), "figure-1"))
    assert missing.status == "model-error"
    assert missing.error_kind == "model-unconfigured"


@pytest.mark.asyncio
async def test_table_review_requires_content_addressed_closed_request(tmp_path: Path):
    payload = b"\\begin{tabular}{cc} A & B \\\\ 1 & 2 \\end{tabular}"
    path = tmp_path / "table.tex"
    path.write_bytes(payload)
    artifact = VisualArtifactRefV1(
        role="table-source",
        relative_path="table.tex",
        digest=_digest(payload),
        media_type="text/x-tex; charset=utf-8",
        size_bytes=len(payload),
    )
    request = {
        "workspace": {"root": str(tmp_path)},
        "target_id": "table-1",
        "artifact": artifact.model_dump(mode="json"),
        "context": "results table",
        "criteria_profile_id": "table-publication/v1",
        "iteration": 0,
        "max_output_tokens": 512,
    }
    response = _response()
    response.choices[0].message.content = json.dumps(
        {"score": 0.9, "issues": [], "summary": "table is clear"}
    )
    with patch("src.review.litellm.acompletion", AsyncMock(return_value=response)):
        review = parse_visual_review(await review_table(request))
    assert review.target_kind == "table"
    assert review.status == "completed"
    assert review.source_manifest_digest is None

    request["artifact"]["digest"] = "sha256:" + "f" * 64
    failed = parse_visual_review(await review_table(request))
    assert failed.status == "artifact-error"


def test_profiles_are_versioned_and_target_specific():
    assert set(PROFILES) == {
        "figure-publication/v1",
        "figure-domain-integrity/v1",
        "table-publication/v1",
    }
    with pytest.raises(ValueError, match="target kind"):
        get_profile("table-publication/v1", target_kind="figure")


@pytest.mark.asyncio
async def test_legacy_manifest_and_arbitrary_image_path_are_not_accepted(tmp_path: Path):
    image = tmp_path / "figure.png"
    image.write_bytes(_png())
    legacy = tmp_path / "figures_manifest.json"
    legacy.write_text(json.dumps({"figures": {"f": str(image)}}), encoding="utf-8")
    with pytest.raises(ValueError, match="FigureBatchV1|invalid"):
        await review_figures_all(str(legacy))
    with pytest.raises(TypeError):
        await review_figure(str(image))  # figure_id is mandatory; no path fallback


def _resolve_provider(model: str) -> str:
    from src.review import _routed_provider as _fn

    return _fn(model)


class TestRoutedProviderProvenance:
    """The provider recorded on a call must name who served it.

    It was derived by splitting the model id on "/", which is not how these
    ids work -- OpenAI and Anthropic models route bare. So the field held the
    model's own name (`claude-opus-4-7` as its own provider): wrong, and
    plausible enough in the record to be read straight past.
    """

    @pytest.mark.parametrize(
        "model, expected",
        [
            ("claude-opus-4-7", "anthropic"),
            ("claude-opus-5", "anthropic"),
            ("gpt-4o", "openai"),
            ("o3", "openai"),
            ("gemini/gemini-2.5-pro", "gemini"),
        ],
    )
    def test_bare_and_prefixed_ids_both_name_a_real_provider(self, model, expected):
        assert _resolve_provider(model) == expected

    def test_unplaceable_id_degrades_instead_of_raising(self):
        """This value annotates the artifact; it must not be able to stop it."""
        assert _resolve_provider("totally-made-up-model-xyz") == "unknown"

    def test_prefixed_private_gateway_keeps_its_own_prefix(self):
        assert _resolve_provider("my-gateway/some-model") == "my-gateway"

    # The checks above exercise the resolver. These drive `_model_identity`,
    # the function that actually stamps the record -- without them the
    # resolver could be correct and simply not wired to anything, which is
    # the failure this whole change is about.
    def test_the_recorded_identity_uses_the_resolver(self, monkeypatch):
        from src.review import _model_identity

        monkeypatch.setenv("ARI_VLM_MODEL", "claude-opus-4-7")
        monkeypatch.delenv("ARI_MODEL_VLM_PROVIDER", raising=False)
        _model, _revision, provider = _model_identity()
        assert provider == "anthropic"

    def test_an_explicit_provider_still_overrides_the_resolver(self, monkeypatch):
        from src.review import _model_identity

        monkeypatch.setenv("ARI_VLM_MODEL", "claude-opus-4-7")
        monkeypatch.setenv("ARI_MODEL_VLM_PROVIDER", "internal-proxy")
        _model, _revision, provider = _model_identity()
        assert provider == "internal-proxy"
