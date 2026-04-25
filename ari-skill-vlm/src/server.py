"""ari-skill-vlm: MCP Server for VLM-based figure and table review."""

from __future__ import annotations

import base64
import os
from pathlib import Path

import litellm
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("vlm-review-skill")

try:
    from ari import cost_tracker as _ari_cost_tracker  # type: ignore
    _ari_cost_tracker.bootstrap_skill("vlm")
except Exception:
    pass

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


def _prefer_raster_sibling(path: Path) -> Path | None:
    """Return a readable raster sibling of ``path`` (VLMs cannot read PDF)."""
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = path.with_suffix(ext)
        if candidate.exists():
            return candidate
    if path.exists() and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        return path
    return None


def _resolve_figure_path(image_path: str) -> Path:
    """Resolve a figure path with a manifest fallback.

    The pipeline hard-codes ``image_path`` as ``{ckpt}/fig_1.png`` but the
    LLM that generates figures is free to pick any name (e.g. ``fig_3``).
    When the literal path is missing, look for ``figures_manifest.json``
    in the same directory and substitute the first figure listed there,
    preferring a ``.png`` sibling when the manifest only points at a PDF.
    """
    p = Path(image_path)
    if p.exists():
        return p

    manifest = p.parent / "figures_manifest.json"
    if not manifest.exists():
        raise FileNotFoundError(image_path)

    import json as _json
    try:
        figs = (_json.loads(manifest.read_text()) or {}).get("figures") or {}
    except Exception as e:
        raise FileNotFoundError(
            f"{image_path} (and figures_manifest.json unparseable: {e})"
        ) from None
    if not figs:
        raise FileNotFoundError(
            f"{image_path} (figures_manifest.json has no figures)"
        )

    first_path = Path(next(iter(figs.values())))
    raster = _prefer_raster_sibling(first_path)
    if raster is not None:
        return raster
    if first_path.exists():
        return first_path
    raise FileNotFoundError(
        f"{image_path} (manifest pointed at {first_path}, no readable image found)"
    )


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


async def _review_one_figure(
    resolved_path: Path,
    context: str,
    criteria: list[str],
) -> dict:
    """Run the VLM review on a single resolved image path."""
    data_uri = _encode_image(str(resolved_path))
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

    resolved_path = _resolve_figure_path(image_path)
    return await _review_one_figure(resolved_path, context, criteria)


@mcp.tool(
    name="review_figures_all",
    description=(
        "Review every figure listed in a figures_manifest.json with the VLM. "
        "Returns an aggregate dict (score=min across figures, issues/suggestions "
        "prefixed with [fig_id]) plus a per_figure breakdown. The aggregate "
        "shape matches review_figure so the pipeline's loop_back machinery "
        "can consume it unchanged."
    ),
)
async def review_figures_all(
    figures_manifest_path: str,
    context: str = "",
    criteria: list[str] | None = None,
) -> dict:
    """Review all figures in a manifest.

    Args:
        figures_manifest_path: Path to figures_manifest.json (the file written
            by plot-skill.generate_figures_llm). Its ``figures`` mapping is
            ``{fig_id: path}``; each path is resolved to a raster sibling
            (PNG/JPG) before sending to the VLM.
        context: Shared paper / experiment context for all figures.
        criteria: Evaluation criteria (default: clarity, accuracy, completeness).
    """
    import json as _json

    if criteria is None:
        criteria = ["clarity", "accuracy", "completeness"]

    manifest_path = Path(figures_manifest_path)
    if not manifest_path.exists():
        raise FileNotFoundError(figures_manifest_path)

    try:
        figs = (_json.loads(manifest_path.read_text()) or {}).get("figures") or {}
    except Exception as e:
        raise ValueError(
            f"figures_manifest.json unparseable: {figures_manifest_path}: {e}"
        ) from None
    if not figs:
        raise ValueError(
            f"figures_manifest.json has no figures: {figures_manifest_path}"
        )

    per_figure: dict[str, dict] = {}
    agg_issues: list[str] = []
    agg_suggestions: list[str] = []
    agg_review_chunks: list[str] = []

    for fig_id, raw_path in figs.items():
        target = Path(raw_path)
        raster = _prefer_raster_sibling(target)
        if raster is None and target.exists() and target.suffix.lower() in (
            ".png", ".jpg", ".jpeg", ".webp",
        ):
            raster = target

        if raster is None:
            note = f"manifest path missing or not rasterizable: {raw_path}"
            per_figure[fig_id] = {
                "score": 0.0,
                "issues": [note],
                "suggestions": ["Re-render the figure as PNG before review."],
                "review_text": "",
            }
            agg_issues.append(f"[{fig_id}] {note}")
            agg_suggestions.append(
                f"[{fig_id}] Re-render the figure as PNG before review."
            )
            continue

        review = await _review_one_figure(raster, context, criteria)
        per_figure[fig_id] = review
        for item in review["issues"]:
            agg_issues.append(f"[{fig_id}] {item}")
        for item in review["suggestions"]:
            agg_suggestions.append(f"[{fig_id}] {item}")
        if review["review_text"]:
            agg_review_chunks.append(f"[{fig_id}] {review['review_text']}")

    scores = [r["score"] for r in per_figure.values()]
    aggregate_score = min(scores) if scores else 0.0

    return {
        "score": aggregate_score,
        "issues": agg_issues,
        "suggestions": agg_suggestions,
        "review_text": "\n\n".join(agg_review_chunks),
        "per_figure": per_figure,
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
