"""Tests for the ari-skill-paper MCP server."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server import (
    TEMPLATES_DIR,
    VENUES,
    _count_pdf_pages,
    check_format,
    compile_paper,
    generate_section,
    get_template,
    list_venues,
)


# --- list_venues ---

@pytest.mark.asyncio
async def test_list_venues_returns_all():
    result = await list_venues()
    assert len(result) == 6


@pytest.mark.asyncio
async def test_list_venues_has_required_fields():
    result = await list_venues()
    for venue in result:
        assert "id" in venue
        assert "name" in venue
        assert "deadline" in venue
        assert "pages" in venue


@pytest.mark.asyncio
async def test_list_venues_contains_neurips():
    result = await list_venues()
    ids = [v["id"] for v in result]
    assert "neurips" in ids


# --- get_template ---

@pytest.mark.asyncio
async def test_get_template_neurips():
    result = await get_template("neurips")
    assert "files" in result
    assert "main.tex" in result["files"]
    assert "refs.bib" in result["files"]
    assert "\\documentclass" in result["files"]["main.tex"]


@pytest.mark.asyncio
async def test_get_template_all_venues():
    for venue in VENUES:
        result = await get_template(venue["id"])
        assert "files" in result
        assert "main.tex" in result["files"]


@pytest.mark.asyncio
async def test_get_template_invalid_venue():
    with pytest.raises(ValueError, match="Unknown venue"):
        await get_template("nonexistent")


# --- generate_section ---

@pytest.mark.asyncio
async def test_generate_section_invalid_section():
    with pytest.raises(ValueError, match="Unknown section"):
        await generate_section("garbage_section", "some context", "neurips")


@pytest.mark.asyncio
async def test_generate_section_invalid_venue():
    with pytest.raises(ValueError, match="Unknown venue"):
        await generate_section("introduction", "some context", "nonexistent")


@pytest.mark.asyncio
async def test_generate_section_calls_litellm():
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "\\section{Introduction}\nTest content."

    with patch("src.server.litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await generate_section("introduction", "We tested X and got Y.", "neurips")
        assert "latex" in result
        assert "Introduction" in result["latex"]


# --- compile_paper ---

@pytest.mark.asyncio
async def test_compile_paper_missing_dir():
    result = await compile_paper("/nonexistent/dir")
    assert result["success"] is False
    assert "not found" in result["log"].lower()


@pytest.mark.asyncio
async def test_compile_paper_missing_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = await compile_paper(tmpdir, "missing.tex")
        assert result["success"] is False
        assert "not found" in result["log"].lower()


# --- check_format ---

@pytest.mark.asyncio
async def test_check_format_missing_pdf():
    result = await check_format("neurips", "/nonexistent/paper.pdf")
    assert result["ok"] is False
    assert len(result["issues"]) > 0


@pytest.mark.asyncio
async def test_check_format_invalid_venue():
    with pytest.raises(ValueError, match="Unknown venue"):
        await check_format("nonexistent", "/some/path.pdf")


@pytest.mark.asyncio
async def test_check_format_small_pdf():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 tiny")
        f.flush()
        result = await check_format("neurips", f.name)
        assert result["ok"] is False
        assert any("too small" in i for i in result["issues"])


# --- _count_pdf_pages ---

def test_count_pdf_pages_none_on_missing():
    result = _count_pdf_pages(Path("/nonexistent/file.pdf"))
    assert result is None


# --- template directory structure ---

def test_templates_dir_exists():
    assert TEMPLATES_DIR.is_dir()


def test_all_venue_templates_exist():
    for venue in VENUES:
        venue_dir = TEMPLATES_DIR / venue["id"]
        assert venue_dir.is_dir(), f"Missing template dir for {venue['id']}"
        assert (venue_dir / "main.tex").is_file()
        assert (venue_dir / "refs.bib").is_file()
