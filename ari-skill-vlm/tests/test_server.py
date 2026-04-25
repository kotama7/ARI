"""Tests for ari-skill-vlm MCP server."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.server import (
    _build_figure_prompt,
    _build_table_prompt,
    _encode_image,
    _is_file_path,
    _is_latex,
    _parse_json_response,
    _resolve_figure_path,
    review_figure,
    review_figures_all,
    review_table,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_tiny_png(path: Path) -> None:
    """Write a minimal valid 1x1 white PNG file."""
    from PIL import Image

    img = Image.new("RGB", (1, 1), color="white")
    img.save(str(path), format="PNG")


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestEncodeImage:
    def test_png(self, tmp_path: Path) -> None:
        img = tmp_path / "fig.png"
        _create_tiny_png(img)
        uri = _encode_image(str(img))
        assert uri.startswith("data:image/png;base64,")

    def test_jpeg(self, tmp_path: Path) -> None:
        from PIL import Image

        img_path = tmp_path / "fig.jpg"
        Image.new("RGB", (1, 1), color="red").save(str(img_path), format="JPEG")
        uri = _encode_image(str(img_path))
        assert uri.startswith("data:image/jpeg;base64,")


class TestBuildFigurePrompt:
    def test_default_criteria(self) -> None:
        prompt = _build_figure_prompt("some context", [])
        assert "clarity, accuracy, completeness" in prompt

    def test_custom_criteria(self) -> None:
        prompt = _build_figure_prompt("ctx", ["resolution", "labeling"])
        assert "resolution, labeling" in prompt
        assert "ctx" in prompt


class TestBuildTablePrompt:
    def test_latex_mode(self) -> None:
        prompt = _build_table_prompt("ctx", is_latex=True)
        assert "LaTeX source code" in prompt

    def test_image_mode(self) -> None:
        prompt = _build_table_prompt("ctx", is_latex=False)
        assert "image" in prompt


class TestIsFilePath:
    def test_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.png"
        f.write_bytes(b"\x00")
        assert _is_file_path(str(f)) is True

    def test_nonexistent(self) -> None:
        assert _is_file_path("/nonexistent/path.png") is False


class TestIsLatex:
    def test_latex_tabular(self) -> None:
        assert _is_latex(r"\begin{tabular}{|c|c|}") is True

    def test_plain_text(self) -> None:
        assert _is_latex("col1, col2, col3") is False


class TestParseJsonResponse:
    def test_plain_json(self) -> None:
        text = '{"score": 0.8, "issues": [], "suggestions": []}'
        result = _parse_json_response(text)
        assert result["score"] == 0.8

    def test_fenced_json(self) -> None:
        text = '```json\n{"score": 0.9, "issues": ["x"], "suggestions": ["y"]}\n```'
        result = _parse_json_response(text)
        assert result["score"] == 0.9
        assert result["issues"] == ["x"]

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_json_response("not json at all")


# ---------------------------------------------------------------------------
# Integration tests for tools (with mocked VLM)
# ---------------------------------------------------------------------------

MOCK_FIGURE_RESPONSE = json.dumps(
    {
        "score": 0.85,
        "issues": ["Low resolution"],
        "suggestions": ["Increase DPI"],
        "review_text": "Good figure overall.",
    }
)

MOCK_TABLE_RESPONSE = json.dumps(
    {
        "score": 0.9,
        "issues": [],
        "suggestions": ["Add caption"],
    }
)


def _make_mock_vlm_response(content: str) -> AsyncMock:
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = content
    return mock_response


class TestResolveFigurePath:
    """Regression: workflow.yaml hard-codes ``image_path: {ckpt}/fig_1.png``
    but the figure-generation LLM is free to name files anything (e.g.
    ``fig_3``). Without a manifest fallback, ``review_figure`` raises
    FileNotFoundError on every run where the LLM picked a different name.
    """

    def test_literal_path_used_when_present(self, tmp_path: Path) -> None:
        img = tmp_path / "fig_1.png"
        _create_tiny_png(img)
        assert _resolve_figure_path(str(img)) == img

    def test_falls_back_to_manifest_when_literal_missing(
        self, tmp_path: Path
    ) -> None:
        # Simulate a real checkpoint: pipeline asked for fig_1.png, but the
        # plot LLM emitted fig_3.* and recorded the PDF in the manifest.
        actual = tmp_path / "fig_3.png"
        _create_tiny_png(actual)
        (tmp_path / "fig_3.pdf").write_bytes(b"%PDF-1.4 fake")
        manifest = {
            "figures": {"fig_3": str(tmp_path / "fig_3.pdf")},
            "figure_kinds": {"fig_3": "svg"},
        }
        (tmp_path / "figures_manifest.json").write_text(json.dumps(manifest))

        resolved = _resolve_figure_path(str(tmp_path / "fig_1.png"))
        assert resolved == actual  # .png sibling preferred over .pdf

    def test_prefers_png_sibling_over_pdf(self, tmp_path: Path) -> None:
        png = tmp_path / "myfig.png"
        _create_tiny_png(png)
        (tmp_path / "myfig.pdf").write_bytes(b"%PDF-1.4")
        manifest = {"figures": {"myfig": str(tmp_path / "myfig.pdf")}}
        (tmp_path / "figures_manifest.json").write_text(json.dumps(manifest))

        resolved = _resolve_figure_path(str(tmp_path / "fig_1.png"))
        assert resolved.suffix == ".png"

    def test_raises_when_no_manifest(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _resolve_figure_path(str(tmp_path / "fig_1.png"))

    def test_raises_when_manifest_has_no_figures(self, tmp_path: Path) -> None:
        (tmp_path / "figures_manifest.json").write_text(
            json.dumps({"figures": {}})
        )
        with pytest.raises(FileNotFoundError):
            _resolve_figure_path(str(tmp_path / "fig_1.png"))

    def test_raises_when_manifest_unparseable(self, tmp_path: Path) -> None:
        (tmp_path / "figures_manifest.json").write_text("{not valid json")
        with pytest.raises(FileNotFoundError):
            _resolve_figure_path(str(tmp_path / "fig_1.png"))


@pytest.mark.asyncio
class TestReviewFigureManifestFallback:
    """End-to-end: review_figure should succeed when the literal image_path
    is missing but figures_manifest.json points at a real figure."""

    async def test_uses_manifest_when_literal_missing(
        self, tmp_path: Path
    ) -> None:
        actual = tmp_path / "fig_3.png"
        _create_tiny_png(actual)
        manifest = {"figures": {"fig_3": str(actual)}}
        (tmp_path / "figures_manifest.json").write_text(json.dumps(manifest))

        with patch("src.server.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_mock_vlm_response(MOCK_FIGURE_RESPONSE)
            )
            result = await review_figure(
                image_path=str(tmp_path / "fig_1.png"),  # does NOT exist
                context="Test",
            )

        assert result["score"] == 0.85
        mock_litellm.acompletion.assert_called_once()


@pytest.mark.asyncio
class TestReviewFigure:
    async def test_basic(self, tmp_path: Path) -> None:
        img = tmp_path / "fig.png"
        _create_tiny_png(img)

        with patch("src.server.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_mock_vlm_response(MOCK_FIGURE_RESPONSE)
            )
            result = await review_figure(
                image_path=str(img),
                context="Test figure",
                criteria=["clarity"],
            )

        assert result["score"] == 0.85
        assert result["issues"] == ["Low resolution"]
        assert result["suggestions"] == ["Increase DPI"]
        assert result["review_text"] == "Good figure overall."
        mock_litellm.acompletion.assert_called_once()

    async def test_default_criteria(self, tmp_path: Path) -> None:
        img = tmp_path / "fig.png"
        _create_tiny_png(img)

        with patch("src.server.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_mock_vlm_response(MOCK_FIGURE_RESPONSE)
            )
            result = await review_figure(image_path=str(img))

        assert isinstance(result["score"], float)


@pytest.mark.asyncio
class TestReviewFiguresAll:
    """Regression: previously the pipeline only reviewed fig_1.png and silently
    skipped every other figure. ``review_figures_all`` walks the manifest so
    fig_2/fig_3/... are evaluated and their issues feed back into the
    regenerator with [fig_id] prefixes."""

    async def test_aggregates_per_figure_and_takes_min_score(
        self, tmp_path: Path
    ) -> None:
        img1 = tmp_path / "fig_1.png"
        img2 = tmp_path / "fig_2.png"
        img3 = tmp_path / "fig_3.png"
        for p in (img1, img2, img3):
            _create_tiny_png(p)
        manifest = {
            "figures": {
                "fig_1": str(img1),
                "fig_2": str(img2),
                "fig_3": str(img3),
            }
        }
        manifest_path = tmp_path / "figures_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        responses = [
            _make_mock_vlm_response(json.dumps({
                "score": 0.9, "issues": ["fine"], "suggestions": ["s1"],
                "review_text": "f1 ok",
            })),
            _make_mock_vlm_response(json.dumps({
                "score": 0.4, "issues": ["text overflow"], "suggestions": ["wider canvas"],
                "review_text": "f2 cropped",
            })),
            _make_mock_vlm_response(json.dumps({
                "score": 0.8, "issues": [], "suggestions": [],
                "review_text": "f3 ok",
            })),
        ]

        with patch("src.server.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=responses)
            result = await review_figures_all(
                figures_manifest_path=str(manifest_path),
                context="benchmark sweep",
            )

        # min across {0.9, 0.4, 0.8} -> 0.4 trips loop_threshold=0.7
        assert result["score"] == 0.4
        # issues/suggestions are flat and prefixed with [fig_id]
        assert "[fig_2] text overflow" in result["issues"]
        assert "[fig_2] wider canvas" in result["suggestions"]
        assert "[fig_1] fine" in result["issues"]
        # per_figure preserves the unprefixed individual reviews
        assert set(result["per_figure"].keys()) == {"fig_1", "fig_2", "fig_3"}
        assert result["per_figure"]["fig_2"]["score"] == 0.4
        assert mock_litellm.acompletion.call_count == 3

    async def test_prefers_png_sibling_when_manifest_lists_pdf(
        self, tmp_path: Path
    ) -> None:
        png = tmp_path / "fig_1.png"
        _create_tiny_png(png)
        (tmp_path / "fig_1.pdf").write_bytes(b"%PDF-1.4 fake")
        manifest = {"figures": {"fig_1": str(tmp_path / "fig_1.pdf")}}
        manifest_path = tmp_path / "figures_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        with patch("src.server.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_mock_vlm_response(MOCK_FIGURE_RESPONSE)
            )
            result = await review_figures_all(
                figures_manifest_path=str(manifest_path)
            )

        assert result["score"] == 0.85
        assert result["per_figure"]["fig_1"]["score"] == 0.85
        mock_litellm.acompletion.assert_called_once()

    async def test_records_failure_and_zeroes_score_when_image_unreadable(
        self, tmp_path: Path
    ) -> None:
        # Manifest points at a PDF with no PNG sibling — VLM cannot read it.
        (tmp_path / "fig_1.pdf").write_bytes(b"%PDF-1.4 fake")
        manifest = {"figures": {"fig_1": str(tmp_path / "fig_1.pdf")}}
        manifest_path = tmp_path / "figures_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        with patch("src.server.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock()
            result = await review_figures_all(
                figures_manifest_path=str(manifest_path)
            )

        # Unreadable figure forces score=0 so loop_back fires, and the VLM is
        # never called for it.
        assert result["score"] == 0.0
        assert result["per_figure"]["fig_1"]["score"] == 0.0
        assert any("[fig_1]" in i for i in result["issues"])
        mock_litellm.acompletion.assert_not_called()

    async def test_raises_when_manifest_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            await review_figures_all(
                figures_manifest_path=str(tmp_path / "missing.json")
            )

    async def test_raises_when_manifest_has_no_figures(
        self, tmp_path: Path
    ) -> None:
        manifest_path = tmp_path / "figures_manifest.json"
        manifest_path.write_text(json.dumps({"figures": {}}))
        with pytest.raises(ValueError):
            await review_figures_all(figures_manifest_path=str(manifest_path))


@pytest.mark.asyncio
class TestReviewTable:
    async def test_latex_input(self) -> None:
        latex = r"\begin{tabular}{|c|c|}\hline A & B \\\hline\end{tabular}"

        with patch("src.server.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_mock_vlm_response(MOCK_TABLE_RESPONSE)
            )
            result = await review_table(latex_or_path=latex, context="Test table")

        assert result["score"] == 0.9
        assert result["issues"] == []
        assert result["suggestions"] == ["Add caption"]

    async def test_image_input(self, tmp_path: Path) -> None:
        img = tmp_path / "table.png"
        _create_tiny_png(img)

        with patch("src.server.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_mock_vlm_response(MOCK_TABLE_RESPONSE)
            )
            result = await review_table(latex_or_path=str(img), context="Table image")

        assert result["score"] == 0.9

    async def test_plain_text_input(self) -> None:
        with patch("src.server.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_mock_vlm_response(MOCK_TABLE_RESPONSE)
            )
            result = await review_table(
                latex_or_path="col1, col2\n1, 2", context="Plain table"
            )

        assert isinstance(result["score"], float)
