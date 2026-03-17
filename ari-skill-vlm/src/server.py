"""ari-skill-vlm: MCP Server for VLM-based figure and table review."""

from __future__ import annotations

import base64
import os
from pathlib import Path

import litellm
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("vlm-review-skill")

DEFAULT_MODEL = os.environ.get("VLM_MODEL", "openai/gpt-4o")


def _encode_image(image_path: str) -> str:
    """Read an image file and return a base64-encoded data URI."""
    path = Path(image_path)
    suffix = path.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime = mime_map.get(suffix, "image/png")
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


def _build_figure_prompt(context: str, criteria: list[str]) -> str:
    criteria_text = ", ".join(criteria) if criteria else "clarity, accuracy, completeness"
    return (
        "You are an expert scientific figure reviewer.\n"
        f"Context: {context}\n\n"
        f"Evaluate this figure on the following criteria: {criteria_text}.\n"
        "Respond in JSON with exactly these keys:\n"
        '- "score": a float between 0.0 and 1.0\n'
        '- "issues": a list of strings describing problems found\n'
        '- "suggestions": a list of strings with improvement suggestions\n'
        '- "review_text": a concise overall review paragraph\n'
        "Return ONLY valid JSON, no markdown fences."
    )


def _build_table_prompt(context: str, is_latex: bool) -> str:
    source_type = "LaTeX source code" if is_latex else "image"
    return (
        f"You are an expert scientific table reviewer. The table is provided as {source_type}.\n"
        f"Context: {context}\n\n"
        "Evaluate the table for correctness, formatting, readability, and completeness.\n"
        "Respond in JSON with exactly these keys:\n"
        '- "score": a float between 0.0 and 1.0\n'
        '- "issues": a list of strings describing problems found\n'
        '- "suggestions": a list of strings with improvement suggestions\n'
        "Return ONLY valid JSON, no markdown fences."
    )


def _is_file_path(value: str) -> bool:
    """Heuristic: treat as file path if it looks like one and exists."""
    return Path(value).is_file()


def _is_latex(value: str) -> bool:
    """Heuristic: treat as LaTeX if it contains common LaTeX table commands."""
    latex_markers = ["\\begin{", "\\tabular", "\\hline", "\\toprule", "\\midrule"]
    return any(m in value for m in latex_markers)


async def _call_vlm(messages: list[dict], model: str | None = None) -> str:
    """Call a VLM via litellm and return the text response."""
    model = model or DEFAULT_MODEL
    response = await litellm.acompletion(model=model, messages=messages)
    return response.choices[0].message.content


def _parse_json_response(text: str) -> dict:
    """Parse a JSON response from the VLM, stripping markdown fences if present."""
    import json

    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)


@mcp.tool(
    name="review_figure",
    description="Review a scientific figure using a Vision Language Model.",
)
async def review_figure(
    image_path: str,
    context: str = "",
    criteria: list[str] | None = None,
) -> dict:
    """Review a figure image with VLM.

    Args:
        image_path: Path to the figure image file.
        context: Description or paper context for the figure.
        criteria: Evaluation criteria (default: clarity, accuracy, completeness).
    """
    if criteria is None:
        criteria = ["clarity", "accuracy", "completeness"]

    data_uri = _encode_image(image_path)
    prompt = _build_figure_prompt(context, criteria)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }
    ]

    raw = await _call_vlm(messages)
    result = _parse_json_response(raw)

    return {
        "score": float(result.get("score", 0.0)),
        "issues": list(result.get("issues", [])),
        "suggestions": list(result.get("suggestions", [])),
        "review_text": str(result.get("review_text", "")),
    }


@mcp.tool(
    name="review_table",
    description="Review a scientific table (LaTeX source or image) using a Vision Language Model.",
)
async def review_table(
    latex_or_path: str,
    context: str = "",
) -> dict:
    """Review a table given as LaTeX source or an image path.

    Args:
        latex_or_path: LaTeX source code of the table, or path to a table image.
        context: Description or paper context for the table.
    """
    if _is_file_path(latex_or_path):
        data_uri = _encode_image(latex_or_path)
        prompt = _build_table_prompt(context, is_latex=False)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ]
    elif _is_latex(latex_or_path):
        prompt = _build_table_prompt(context, is_latex=True)
        messages = [
            {
                "role": "user",
                "content": f"{prompt}\n\nLaTeX source:\n```\n{latex_or_path}\n```",
            }
        ]
    else:
        prompt = _build_table_prompt(context, is_latex=False)
        messages = [
            {
                "role": "user",
                "content": f"{prompt}\n\nTable content:\n{latex_or_path}",
            }
        ]

    raw = await _call_vlm(messages)
    result = _parse_json_response(raw)

    return {
        "score": float(result.get("score", 0.0)),
        "issues": list(result.get("issues", [])),
        "suggestions": list(result.get("suggestions", [])),
    }


if __name__ == "__main__":
    mcp.run()
