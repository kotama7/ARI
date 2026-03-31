"""MCP Server for peer review parsing and rebuttal generation."""

import json

import litellm
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

mcp = FastMCP("review-response-skill")

import os
import re as _re

LLM_MODEL = os.environ.get("ARI_LLM_MODEL") or os.environ.get("LLM_MODEL") or "ollama/qwen3:8b"
_ari_base = os.environ.get("ARI_LLM_API_BASE")
if _ari_base is not None:
    LLM_API_BASE = _ari_base or None
else:
    _legacy = os.environ.get("LLM_API_BASE", "")
    if _legacy:
        LLM_API_BASE = _legacy
    elif LLM_MODEL.startswith("ollama"):
        LLM_API_BASE = "http://127.0.0.1:11434"
    else:
        LLM_API_BASE = None
MODEL = LLM_MODEL  # backward compat


# ── Pydantic schemas ─────────────────────────────────────────────────

class Concern(BaseModel):
    id: str
    severity: str
    text: str


class ParseReviewOutput(BaseModel):
    summary: str
    concerns: list[Concern]
    questions: list[str]
    suggestions: list[str]


class PointByPoint(BaseModel):
    concern_id: str
    response: str


class GenerateRebuttalOutput(BaseModel):
    rebuttal_latex: str
    point_by_point: list[PointByPoint]


class CheckRebuttalOutput(BaseModel):
    coverage: float
    missing: list[str]
    suggestions: list[str]


# ── LLM helper ───────────────────────────────────────────────────────

async def _llm_json(prompt: str, system: str) -> dict:
    """Call LLM via litellm and return parsed JSON."""
    kwargs = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    if LLM_MODEL.startswith("ollama/"):
        kwargs["api_base"] = LLM_API_BASE
    else:
        kwargs["response_format"] = {"type": "json_object"}
    response = await litellm.acompletion(**kwargs)
    raw = response.choices[0].message.content or ""
    raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
    # JSON extraction
    m = _re.search(r"\{.*\}", raw, _re.DOTALL)
    if m:
        raw = m.group(0)
    return json.loads(raw)


# ── MCP Tools ─────────────────────────────────────────────────────────

@mcp.tool()
async def parse_review(review_text: str) -> dict:
    """Parse review comments into structured form."""
    system = (
        "You are an academic review parser. "
        "Parse the given peer-review text into structured JSON.\n"
        "Required fields:\n"
        '- "summary": a brief summary of the review\n'
        '- "concerns": array of objects with {id, severity, text} '
        "where id is R1, R2, ... and severity is 'major' or 'minor'\n"
        '- "questions": array of question strings extracted from the review\n'
        '- "suggestions": array of suggestion strings extracted from the review\n'
        "Return ONLY valid JSON."
    )
    result = await _llm_json(review_text, system)
    return ParseReviewOutput(**result).model_dump()


@mcp.tool()
async def generate_rebuttal(
    concerns: list[dict], paper_context: str, experiment_results: str
) -> dict:
    """Generate a rebuttal to review comments."""
    system = (
        "You are an academic rebuttal writer. "
        "Generate a rebuttal addressing each review concern.\n"
        "Required fields:\n"
        '- "rebuttal_latex": the full rebuttal formatted in LaTeX\n'
        '- "point_by_point": array of {concern_id, response} for each concern\n'
        "Return ONLY valid JSON."
    )
    prompt = json.dumps(
        {
            "concerns": concerns,
            "paper_context": paper_context,
            "experiment_results": experiment_results,
        },
        ensure_ascii=False,
    )
    result = await _llm_json(prompt, system)
    return GenerateRebuttalOutput(**result).model_dump()


@mcp.tool()
async def check_rebuttal(rebuttal: str, original_concerns: list[dict]) -> dict:
    """Check the completeness and appropriateness of a rebuttal."""
    system = (
        "You are an academic rebuttal reviewer. "
        "Check the rebuttal against the original concerns.\n"
        "Required fields:\n"
        '- "coverage": float 0-1 indicating how well concerns are addressed\n'
        '- "missing": array of concern IDs not adequately addressed\n'
        '- "suggestions": array of improvement suggestions\n'
        "Return ONLY valid JSON."
    )
    prompt = json.dumps(
        {"rebuttal": rebuttal, "original_concerns": original_concerns},
        ensure_ascii=False,
    )
    result = await _llm_json(prompt, system)
    return CheckRebuttalOutput(**result).model_dump()


if __name__ == "__main__":
    mcp.run()
