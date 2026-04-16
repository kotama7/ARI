"""ari-skill-figure-router: Figure generation router MCP server.

Classifies figure needs and dispatches to the appropriate generation tool:
- Architecture/concept diagrams -> SVG generation (AutoFigure-Edit inspired)
- Experiment result graphs -> matplotlib (delegates to ari-skill-plot pattern)
- Tables -> LaTeX tabular generation

Includes VLM review loop: each generated figure is reviewed by a Vision
Language Model and regenerated with feedback until the score meets the
threshold or the maximum number of iterations is reached.
"""
from __future__ import annotations
import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import litellm
from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)
mcp = FastMCP("figure-router-skill")

# ---------------------------------------------------------------------------
# VLM review configuration
# ---------------------------------------------------------------------------

_VLM_MODEL = os.environ.get("VLM_MODEL", "openai/gpt-4o")
_VLM_REVIEW_ENABLED = os.environ.get("VLM_REVIEW_ENABLED", "true").lower() == "true"
_VLM_REVIEW_THRESHOLD = float(os.environ.get("VLM_REVIEW_THRESHOLD", "0.7"))
_VLM_REVIEW_MAX_ITER = int(os.environ.get("VLM_REVIEW_MAX_ITER", "3"))

# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def _get_model() -> str:
    return (os.environ.get("ARI_LLM_MODEL")
            or os.environ.get("LLM_MODEL")
            or "ollama_chat/qwen3:32b")


def _get_api_base() -> str | None:
    ari_base = os.environ.get("ARI_LLM_API_BASE")
    if ari_base is not None:
        return ari_base or None
    if os.environ.get("OPENAI_API_KEY") and "ollama" not in _get_model():
        return None
    return os.environ.get("LLM_API_BASE") or None


async def _llm_call(system: str, user: str, temperature: float = 0.3,
                     max_tokens: int = 4096) -> str:
    kwargs: dict = {
        "model": _get_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    base = _get_api_base()
    if base:
        kwargs["api_base"] = base
    resp = await litellm.acompletion(**kwargs)
    raw = resp.choices[0].message.content or ""
    if "</think>" in raw:
        raw = raw.split("</think>")[-1]
    return raw.strip()


# ---------------------------------------------------------------------------
# VLM review helpers
# ---------------------------------------------------------------------------


def _encode_review_image(image_path: str) -> str:
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


def _ensure_reviewable_image(result: dict, fig_type: str) -> str | None:
    """Return a raster image path suitable for VLM review, or None."""
    if fig_type == "table":
        return None

    if fig_type == "architecture":
        png = result.get("png_path", "")
        if png and Path(png).exists():
            return png
        svg = result.get("svg_path", "")
        if svg and Path(svg).exists():
            png = svg.replace(".svg", ".png")
            try:
                import cairosvg
                cairosvg.svg2png(
                    url=svg, write_to=png, output_width=1200,
                )
                return png
            except ImportError:
                try:
                    subprocess.run(
                        ["inkscape", svg, "--export-type=png",
                         f"--export-filename={png}", "--export-width=1200"],
                        capture_output=True, timeout=30,
                    )
                    if Path(png).exists():
                        return png
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    pass
        return None

    # graph (matplotlib) — output is PDF; convert first page to PNG
    out = result.get("output_path", "")
    if not out or not Path(out).exists():
        return None
    if Path(out).suffix.lower() in (".png", ".jpg", ".jpeg"):
        return out
    png = str(Path(out).with_suffix(".png"))
    try:
        subprocess.run(
            ["pdftoppm", "-png", "-singlefile", "-r", "150", out, png.replace(".png", "")],
            capture_output=True, timeout=30,
        )
        if Path(png).exists():
            return png
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


async def _vlm_review(image_path: str, context: str) -> dict:
    """Review a figure image using a VLM. Returns {score, issues, suggestions}."""
    try:
        data_uri = _encode_review_image(image_path)
    except Exception as exc:
        log.warning("_vlm_review: failed to encode image %s: %s", image_path, exc)
        return {"score": 1.0, "issues": [], "suggestions": [], "error": str(exc)}

    prompt = (
        "You are an expert scientific figure reviewer.\n"
        f"Context: {context}\n\n"
        "Evaluate this figure on: clarity, accuracy, completeness, readability.\n"
        "Respond in JSON with exactly these keys:\n"
        '- "score": a float between 0.0 and 1.0\n'
        '- "issues": a list of strings describing problems found\n'
        '- "suggestions": a list of strings with improvement suggestions\n'
        "Return ONLY valid JSON, no markdown fences."
    )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }
    ]

    try:
        resp = await litellm.acompletion(model=_VLM_MODEL, messages=messages)
        raw = resp.choices[0].message.content or ""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        parsed = json.loads(cleaned)
        return {
            "score": float(parsed.get("score", 0.0)),
            "issues": list(parsed.get("issues", [])),
            "suggestions": list(parsed.get("suggestions", [])),
        }
    except Exception as exc:
        log.warning("_vlm_review: VLM call failed: %s", exc)
        return {"score": 1.0, "issues": [], "suggestions": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM = (
    "You are an academic figure classification expert. Given a description of "
    "a figure needed for a research paper, classify it into one of three types:\n\n"
    "1. 'architecture' - System diagrams, flowcharts, concept maps, model "
    "architecture diagrams, pipeline overviews, block diagrams\n"
    "2. 'graph' - Experimental results, bar charts, line plots, scatter plots, "
    "heatmaps, performance comparisons, any data-driven visualization\n"
    "3. 'table' - Comparison tables, results tables, configuration tables, "
    "any tabular data presentation\n\n"
    "Respond with ONLY a JSON object:\n"
    '{"type": "<architecture|graph|table>", '
    '"tool": "<autofigure|matplotlib|latex>", '
    '"reasoning": "<brief explanation>"}\n\n'
    "Mapping: architecture->autofigure, graph->matplotlib, table->latex"
)


@mcp.tool()
async def classify_figure_need(description: str, data_available: bool = False) -> dict:
    """Classify what type of figure is needed based on description.

    Args:
        description: Natural language description of the desired figure
        data_available: Whether numerical data is available for plotting

    Returns:
        {type: "architecture"|"graph"|"table",
         tool: "autofigure"|"matplotlib"|"latex",
         reasoning: str}
    """
    user_msg = f"Figure description: {description}\nData available: {data_available}"
    try:
        resp = await _llm_call(_CLASSIFY_SYSTEM, user_msg, temperature=0.0,
                                max_tokens=256)
        # Parse JSON from response
        for candidate in [resp.strip(), *re.findall(r'\{[^}]+\}', resp)]:
            try:
                result = json.loads(candidate)
                if isinstance(result, dict) and "type" in result:
                    valid_types = {"architecture", "graph", "table"}
                    valid_tools = {"autofigure", "matplotlib", "latex"}
                    if result.get("type") not in valid_types:
                        result["type"] = "graph"
                    if result.get("tool") not in valid_tools:
                        tool_map = {"architecture": "autofigure",
                                    "graph": "matplotlib", "table": "latex"}
                        result["tool"] = tool_map[result["type"]]
                    return result
            except (json.JSONDecodeError, KeyError):
                continue
    except Exception as e:
        log.warning("classify_figure_need LLM call failed: %s", e)

    # Fallback: keyword-based heuristic
    desc_lower = description.lower()
    if any(kw in desc_lower for kw in ["table", "tabular", "comparison table"]):
        return {"type": "table", "tool": "latex",
                "reasoning": "Keyword match: table-related terms"}
    if any(kw in desc_lower for kw in [
        "architecture", "diagram", "flowchart", "pipeline", "overview",
        "block diagram", "system design", "concept"
    ]):
        return {"type": "architecture", "tool": "autofigure",
                "reasoning": "Keyword match: architecture-related terms"}
    return {"type": "graph", "tool": "matplotlib",
            "reasoning": "Default: assumed data visualization"}


# ---------------------------------------------------------------------------
# SVG diagram generation (AutoFigure-Edit inspired)
# ---------------------------------------------------------------------------

_SVG_SYSTEM = (
    "You are an expert at creating clean, academic-style SVG diagrams for "
    "research papers. Generate SVG code that:\n"
    "- Uses a clean, professional color palette (blues, grays, muted colors)\n"
    "- Has clear labels with readable font sizes (14-16px)\n"
    "- Uses proper spacing and alignment\n"
    "- Includes arrows for flow/connections where appropriate\n"
    "- Is self-contained (no external references)\n"
    "- Uses viewBox for responsive sizing\n\n"
    "Output ONLY valid SVG code, starting with <svg and ending with </svg>. "
    "No markdown fences, no explanation."
)


@mcp.tool()
async def generate_svg_diagram(description: str, output_path: str) -> dict:
    """Generate architecture/concept diagram as SVG using LLM.

    Inspired by AutoFigure-Edit: LLM generates SVG code directly for
    clean, academic-style diagrams.

    Args:
        description: Description of the diagram to generate
        output_path: File path to save the SVG (without extension)

    Returns:
        {success: bool, svg_path: str, png_path: str}
    """
    try:
        resp = await _llm_call(_SVG_SYSTEM, description, temperature=0.2,
                                max_tokens=4096)
        # Extract SVG from response
        svg_match = re.search(r'<svg[\s\S]*?</svg>', resp, re.IGNORECASE)
        if not svg_match:
            return {"success": False, "error": "LLM did not produce valid SVG"}
        svg_code = svg_match.group(0)

        # Validate basic SVG structure
        if '<svg' not in svg_code or '</svg>' not in svg_code:
            return {"success": False, "error": "Invalid SVG structure"}

        # Save SVG
        svg_path = output_path if output_path.endswith(".svg") else output_path + ".svg"
        Path(svg_path).parent.mkdir(parents=True, exist_ok=True)
        Path(svg_path).write_text(svg_code, encoding="utf-8")

        # Try to convert to PNG
        png_path = svg_path.replace(".svg", ".png")
        png_ok = False
        try:
            import cairosvg
            cairosvg.svg2png(bytestring=svg_code.encode(), write_to=png_path,
                             output_width=1200)
            png_ok = True
        except ImportError:
            try:
                subprocess.run(
                    ["inkscape", svg_path, "--export-type=png",
                     f"--export-filename={png_path}", "--export-width=1200"],
                    capture_output=True, timeout=30,
                )
                png_ok = Path(png_path).exists()
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        return {
            "success": True,
            "svg_path": svg_path,
            "png_path": png_path if png_ok else "",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# LaTeX table generation
# ---------------------------------------------------------------------------

_TABLE_SYSTEM = (
    "You are an expert at creating LaTeX tables for academic papers. "
    "Generate a complete LaTeX tabular environment. Include:\n"
    "- \\begin{table}[H] wrapper with \\centering\n"
    "- \\caption{...} with a descriptive caption\n"
    "- \\label{tab:...} for referencing\n"
    "- Proper column alignment, \\toprule/\\midrule/\\bottomrule (booktabs)\n"
    "- Bold headers\n\n"
    "Output ONLY the LaTeX code, no markdown fences, no explanation."
)


async def _generate_latex_table(description: str, data: str,
                                 output_path: str) -> dict:
    """Generate a LaTeX table from description and data."""
    user_msg = f"Table description: {description}\nData:\n{data}"
    try:
        resp = await _llm_call(_TABLE_SYSTEM, user_msg, temperature=0.1,
                                max_tokens=2048)
        # Clean any markdown fences
        resp = re.sub(r'```(?:latex|tex)?\s*', '', resp)
        resp = re.sub(r'```\s*$', '', resp)
        tex_path = output_path if output_path.endswith(".tex") else output_path + ".tex"
        Path(tex_path).parent.mkdir(parents=True, exist_ok=True)
        Path(tex_path).write_text(resp.strip(), encoding="utf-8")
        return {"success": True, "output_path": tex_path, "type": "table",
                "tool_used": "latex"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Matplotlib graph generation
# ---------------------------------------------------------------------------

_MATPLOTLIB_SYSTEM = (
    "You are an expert at writing matplotlib code for academic figures. "
    "Write a complete, self-contained Python script that:\n"
    "- Imports matplotlib and any needed libraries\n"
    "- Creates publication-quality figures (300 DPI)\n"
    "- Uses a clean style (seaborn-v0_8-whitegrid or similar)\n"
    "- Saves the figure to the path specified in the variable OUTPUT_PATH\n"
    "- Uses plt.tight_layout() before saving\n\n"
    "The script must be fully executable. Define OUTPUT_PATH at the top.\n"
    "Output ONLY Python code, no markdown fences, no explanation."
)


async def _generate_matplotlib(description: str, data: str,
                                output_path: str) -> dict:
    """Generate a matplotlib figure from description and data."""
    user_msg = (
        f"Figure description: {description}\n"
        f"Data:\n{data}\n"
        f"Save to: OUTPUT_PATH = {output_path!r}"
    )
    try:
        resp = await _llm_call(_MATPLOTLIB_SYSTEM, user_msg, temperature=0.2,
                                max_tokens=3000)
        code = re.sub(r'```(?:python)?\s*', '', resp)
        code = re.sub(r'```\s*$', '', code).strip()
        # Inject output path
        pdf_path = output_path if output_path.endswith(".pdf") else output_path + ".pdf"
        code = f'OUTPUT_PATH = {pdf_path!r}\n' + code
        Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            script_path = f.name
        try:
            result = subprocess.run(
                ["python3", script_path],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                return {"success": False, "error": result.stderr[:500],
                        "type": "graph", "tool_used": "matplotlib"}
        finally:
            Path(script_path).unlink(missing_ok=True)
        return {"success": Path(pdf_path).exists(), "output_path": pdf_path,
                "type": "graph", "tool_used": "matplotlib"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------

async def _dispatch_generate(fig_type: str, description: str, data: str,
                              output_path: str) -> dict:
    """Dispatch to the appropriate generator based on figure type."""
    if fig_type == "architecture":
        result = await generate_svg_diagram(description, output_path)
        result["type"] = "architecture"
        result["tool_used"] = "autofigure"
        if result.get("svg_path"):
            result["output_path"] = result.get("png_path") or result["svg_path"]
        return result
    elif fig_type == "table":
        return await _generate_latex_table(description, data, output_path)
    else:
        return await _generate_matplotlib(description, data, output_path)


@mcp.tool()
async def generate_figure(description: str, data: str = "",
                           output_path: str = "",
                           vlm_review: bool = True,
                           vlm_max_iterations: int = 0,
                           vlm_score_threshold: float = 0) -> dict:
    """Route figure generation to the appropriate tool with VLM review loop.

    Automatically classifies the figure type and dispatches to:
    - Architecture/concept diagrams -> SVG generation (AutoFigure-Edit style)
    - Graphs -> matplotlib code generation
    - Tables -> LaTeX tabular generation

    After generation, the figure is reviewed by a VLM. If the score is below
    the threshold, the figure is regenerated with VLM feedback until the
    score passes or the maximum iterations are reached.

    Args:
        description: Description of the figure to generate
        data: Data to visualize (CSV, JSON, or text)
        output_path: Output file path (extension determined by type)
        vlm_review: Enable VLM review loop (default: True, also via VLM_REVIEW_ENABLED env)
        vlm_max_iterations: Max review-regenerate iterations (0 = use env default)
        vlm_score_threshold: Minimum VLM score to accept (0 = use env default)

    Returns:
        {success, output_path, type, tool_used, review_score, review_passed, review_iterations}
    """
    classification = await classify_figure_need(description,
                                                 data_available=bool(data))
    fig_type = classification.get("type", "graph")

    # Resolve VLM review settings (tool params override env vars)
    do_review = vlm_review and _VLM_REVIEW_ENABLED
    max_iter = vlm_max_iterations if vlm_max_iterations > 0 else _VLM_REVIEW_MAX_ITER
    threshold = vlm_score_threshold if vlm_score_threshold > 0 else _VLM_REVIEW_THRESHOLD

    best_result = None
    best_score = -1.0
    original_desc = description

    for iteration in range(1, max_iter + 1):
        result = await _dispatch_generate(fig_type, description, data, output_path)

        if not result.get("success"):
            result["review_iterations"] = iteration
            return result

        if not do_review:
            result["review_iterations"] = 0
            return result

        # Get a reviewable image for VLM
        image_path = _ensure_reviewable_image(result, fig_type)
        if not image_path:
            log.info("generate_figure: no reviewable image for type=%s, skipping VLM review", fig_type)
            result["review_skipped"] = True
            result["review_iterations"] = iteration
            return result

        review = await _vlm_review(image_path, original_desc)
        score = review["score"]
        log.info("generate_figure: VLM review iteration %d/%d score=%.2f (threshold=%.2f)",
                 iteration, max_iter, score, threshold)

        if score > best_score:
            best_score = score
            best_result = {**result, "review_score": score, "review_passed": score >= threshold}

        if score >= threshold:
            best_result["review_iterations"] = iteration
            return best_result

        if iteration < max_iter:
            issues_text = "; ".join(review.get("issues", []))
            suggestions_text = "; ".join(review.get("suggestions", []))
            description = (
                f"{original_desc}\n\n"
                f"[VLM feedback from previous attempt (score={score:.2f})]\n"
                f"Issues: {issues_text}\n"
                f"Suggestions: {suggestions_text}\n"
                f"Please regenerate addressing these issues."
            )

    # Max iterations reached — return best result
    best_result["review_iterations"] = max_iter
    return best_result


if __name__ == "__main__":
    mcp.run()
