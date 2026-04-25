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


# --- review_compiled_paper: N resolution + ensemble/meta integration ---
#
# Guards the GUI → env → skill chain: the Wizard stuffs N into
# ARI_NUM_REVIEWS_ENSEMBLE via _api_launch (covered in
# ari-core/tests/test_wizard.py); these tests verify the skill side
# consumes that env and drives run_ensemble + run_meta_review accordingly.

import json as _jsn  # noqa: E402


def _canned_review_json() -> str:
    return _jsn.dumps({
        "soundness": 3, "presentation": 3, "contribution": 3,
        "overall": 6, "confidence": 3,
        "strengths": "S", "weaknesses": "W", "questions": "Q",
        "decision": "accept",
    })


@pytest.mark.asyncio
async def test_review_compiled_paper_env_drives_n(tmp_path, monkeypatch):
    """ARI_NUM_REVIEWS_ENSEMBLE=3 must route through run_ensemble with N=3
    and trigger run_meta_review (N>1), without the caller passing N."""
    from src import server as _srv
    from src.review_engine import FewshotExample

    tex = tmp_path / "full_paper.tex"
    tex.write_text(
        r"\documentclass{article}\begin{document}"
        r"A minimal but non-empty paper body for the extractor to return."
        r"\end{document}"
    )
    monkeypatch.setenv("ARI_NUM_REVIEWS_ENSEMBLE", "3")
    monkeypatch.delenv("ARI_RUBRIC", raising=False)
    # num_reflections=0 keeps each reviewer to a single LLM call so we can
    # count total calls deterministically: 3 ensemble + 1 meta = 4.
    monkeypatch.setenv("ARI_NUM_REFLECTIONS", "0")

    calls: list[dict] = []

    async def fake_llm(messages, temperature, model=None):
        calls.append({"temperature": temperature, "model": model})
        return _canned_review_json()

    monkeypatch.setattr(_srv, "_litellm_caller", fake_llm)
    monkeypatch.setattr(_srv, "load_static_fewshot", lambda r: [])
    monkeypatch.setattr(_srv, "load_dynamic_fewshot", lambda r, t, a: [])

    out = await _srv.review_compiled_paper(tex_path=str(tex), rubric_id="neurips")

    # Ensemble ran N=3 times; meta-review aggregated → +1 call
    assert out.get("n") == 3, f"expected n=3, got {out.get('n')}"
    assert len(out.get("ensemble_reviews", [])) == 3
    assert isinstance(out.get("meta_review"), dict)
    assert len(calls) == 4
    # Temperature jitter across ensemble members (at least two distinct)
    ensemble_temps = {c["temperature"] for c in calls[:3]}
    assert len(ensemble_temps) > 1, f"expected jittered temps, got {ensemble_temps}"


@pytest.mark.asyncio
async def test_review_compiled_paper_n1_no_ensemble_or_meta(tmp_path, monkeypatch):
    """N=1 (the default) must NOT attach ensemble_reviews or meta_review —
    otherwise the frontend renders a spurious ensemble badge for a single review."""
    from src import server as _srv

    tex = tmp_path / "full_paper.tex"
    tex.write_text(
        r"\documentclass{article}\begin{document}"
        r"Another minimal non-empty paper body for the extractor."
        r"\end{document}"
    )
    monkeypatch.setenv("ARI_NUM_REVIEWS_ENSEMBLE", "1")
    monkeypatch.delenv("ARI_RUBRIC", raising=False)
    monkeypatch.setenv("ARI_NUM_REFLECTIONS", "0")

    calls: list[dict] = []

    async def fake_llm(messages, temperature, model=None):
        calls.append({"temperature": temperature, "model": model})
        return _canned_review_json()

    monkeypatch.setattr(_srv, "_litellm_caller", fake_llm)
    monkeypatch.setattr(_srv, "load_static_fewshot", lambda r: [])
    monkeypatch.setattr(_srv, "load_dynamic_fewshot", lambda r, t, a: [])

    out = await _srv.review_compiled_paper(tex_path=str(tex), rubric_id="neurips")

    assert out.get("n") == 1
    assert "ensemble_reviews" not in out
    assert "meta_review" not in out
    assert len(calls) == 1  # single review, no meta aggregation


@pytest.mark.asyncio
async def test_review_compiled_paper_arg_beats_env(tmp_path, monkeypatch):
    """Explicit num_reviews_ensemble arg must override the env var."""
    from src import server as _srv

    tex = tmp_path / "full_paper.tex"
    tex.write_text(
        r"\documentclass{article}\begin{document}"
        r"Non-empty body so the extractor returns text."
        r"\end{document}"
    )
    monkeypatch.setenv("ARI_NUM_REVIEWS_ENSEMBLE", "5")
    monkeypatch.delenv("ARI_RUBRIC", raising=False)
    monkeypatch.setenv("ARI_NUM_REFLECTIONS", "0")

    async def fake_llm(messages, temperature, model=None):
        return _canned_review_json()

    monkeypatch.setattr(_srv, "_litellm_caller", fake_llm)
    monkeypatch.setattr(_srv, "load_static_fewshot", lambda r: [])
    monkeypatch.setattr(_srv, "load_dynamic_fewshot", lambda r, t, a: [])

    out = await _srv.review_compiled_paper(
        tex_path=str(tex), rubric_id="neurips", num_reviews_ensemble=2,
    )
    assert out.get("n") == 2, f"arg=2 must win over env=5, got n={out.get('n')}"
