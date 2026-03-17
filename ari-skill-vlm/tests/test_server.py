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
    review_figure,
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
