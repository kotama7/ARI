"""Tests for the ari-skill-review MCP server tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server import (
    CheckRebuttalOutput,
    GenerateRebuttalOutput,
    ParseReviewOutput,
    check_rebuttal,
    generate_rebuttal,
    parse_review,
)


def _fake_llm_response(content: dict) -> MagicMock:
    """Build a mock litellm response returning *content* as JSON."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = json.dumps(content)
    return resp


# ── parse_review ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_review_returns_structured_output():
    payload = {
        "summary": "The paper lacks novelty.",
        "concerns": [
            {"id": "R1", "severity": "major", "text": "Missing baselines"},
            {"id": "R2", "severity": "minor", "text": "Typos in Section 3"},
        ],
        "questions": ["What dataset was used?"],
        "suggestions": ["Add ablation study"],
    }
    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_fake_llm_response(payload),
    ):
        result = await parse_review(review_text="The paper lacks novelty …")

    assert result["summary"] == payload["summary"]
    assert len(result["concerns"]) == 2
    assert result["concerns"][0]["id"] == "R1"
    assert result["concerns"][0]["severity"] == "major"
    assert result["questions"] == ["What dataset was used?"]
    assert result["suggestions"] == ["Add ablation study"]


@pytest.mark.asyncio
async def test_parse_review_validates_schema():
    """Pydantic validation should reject bad data."""
    bad_payload = {"summary": 123, "concerns": "not a list"}
    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_fake_llm_response(bad_payload),
    ):
        with pytest.raises(Exception):
            await parse_review(review_text="anything")


# ── generate_rebuttal ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_rebuttal_returns_latex_and_points():
    payload = {
        "rebuttal_latex": "\\section{Rebuttal}\nWe thank the reviewer.",
        "point_by_point": [
            {"concern_id": "R1", "response": "We added the missing baselines."},
        ],
    }
    concerns = [{"id": "R1", "severity": "major", "text": "Missing baselines"}]

    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_fake_llm_response(payload),
    ):
        result = await generate_rebuttal(
            concerns=concerns,
            paper_context="Our paper proposes method X.",
            experiment_results="Accuracy improved by 5%.",
        )

    assert "rebuttal_latex" in result
    assert result["rebuttal_latex"].startswith("\\section")
    assert len(result["point_by_point"]) == 1
    assert result["point_by_point"][0]["concern_id"] == "R1"


# ── check_rebuttal ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_rebuttal_full_coverage():
    payload = {"coverage": 1.0, "missing": [], "suggestions": []}
    concerns = [{"id": "R1", "severity": "major", "text": "Missing baselines"}]

    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_fake_llm_response(payload),
    ):
        result = await check_rebuttal(
            rebuttal="We address all concerns.",
            original_concerns=concerns,
        )

    assert result["coverage"] == 1.0
    assert result["missing"] == []
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_check_rebuttal_partial_coverage():
    payload = {
        "coverage": 0.5,
        "missing": ["R2"],
        "suggestions": ["Address reviewer concern R2"],
    }
    concerns = [
        {"id": "R1", "severity": "major", "text": "Missing baselines"},
        {"id": "R2", "severity": "minor", "text": "Typos"},
    ]

    with patch(
        "src.server.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_fake_llm_response(payload),
    ):
        result = await check_rebuttal(
            rebuttal="We added baselines.",
            original_concerns=concerns,
        )

    assert result["coverage"] == 0.5
    assert "R2" in result["missing"]
    assert len(result["suggestions"]) == 1


# ── Pydantic model unit tests ────────────────────────────────────────

def test_parse_review_output_model():
    data = {
        "summary": "ok",
        "concerns": [{"id": "R1", "severity": "major", "text": "issue"}],
        "questions": [],
        "suggestions": [],
    }
    obj = ParseReviewOutput(**data)
    assert obj.summary == "ok"
    assert obj.concerns[0].id == "R1"


def test_generate_rebuttal_output_model():
    data = {
        "rebuttal_latex": "\\section{}",
        "point_by_point": [{"concern_id": "R1", "response": "fixed"}],
    }
    obj = GenerateRebuttalOutput(**data)
    assert obj.point_by_point[0].concern_id == "R1"


def test_check_rebuttal_output_model():
    data = {"coverage": 0.95, "missing": ["R3"], "suggestions": ["do X"]}
    obj = CheckRebuttalOutput(**data)
    assert obj.coverage == 0.95
    assert "R3" in obj.missing
