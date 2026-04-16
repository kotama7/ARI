"""MCP Server for dynamic MetricSpec generation from experiment files."""

from __future__ import annotations

import re
import json
from mcp.server import Server
from mcp.types import TextContent, Tool

server = Server("evaluator-skill")


def _parse_success_metrics(text: str) -> list[str]:
    """Extract metric names from the experiment file (deterministic).
    Supports:
      - ## Success Metrics section with "- metric_name: ..."
      - "Metrics: A, B, C" inline line
      - "<!-- metric_keyword: FOO -->" HTML comment
    """
    # 1. ## Success Metrics section
    m = re.search(r"##\s*Success Metrics.*?\n(.*?)(?=\n##|\Z)", text, re.DOTALL | re.IGNORECASE)
    if m:
        found = re.findall(r"-\s*(\w+)\s*:", m.group(1))
        if found:
            return found
    # 2. "Metrics: A, B, C" inline
    m2 = re.search(r"(?:^|\n)Metrics?:\s*([^\n]+)", text, re.IGNORECASE)
    if m2:
        raw = m2.group(1)
        return [w.strip().strip("/") for w in re.split(r"[,;]", raw) if w.strip()]
    # 3. metric_keyword comment
    m3 = re.search(r"metric_keyword:\s*(\w+)", text)
    if m3:
        return [m3.group(1)]
    return []


def _parse_metric_keyword(text: str) -> str | None:
    """Extract keyword from <!-- metric_keyword: FOO --> or front matter."""
    m = re.search(r"metric_keyword:\s*(\w+)", text)
    return m.group(1) if m else None


def _parse_min_expected(text: str) -> float | None:
    """Extract threshold from <!-- min_expected_metric: N -->."""
    m = re.search(r"min_expected_metric:\s*([\d.]+)", text)
    return float(m.group(1)) if m else None


def _build_scoring_guide(
    expected_metrics: list[str],
    metric_keyword: str | None,
    min_expected: float | None,
) -> str:
    """Generate a generic scoring guide from the expected_metrics list (deterministic template)."""
    kw = metric_keyword or "metric"
    min_val = min_expected or 0

    lines = [
        f"STEP 1 - Extract numeric {kw} values from artifacts.",
        f"  has_real_data=true only if actual {kw} numbers appear in artifacts.",
        f"  If no {kw} values found: score=0.2, stop here.",
        "",
        f"STEP 2 - Evaluate {kw} quality.",
        f"  Target threshold: {min_val:g} (from experiment spec).",
        f"  Above threshold: good. Below: poor.",
        "",
        "STEP 3 - Compute final score:",
        f"  1.0 = has_real_data AND {kw} >= {min_val:g} AND paper section present",
        f"  0.9 = has_real_data AND {kw} >= {min_val:g} (no paper)",
        f"  0.7 = has_real_data AND {kw} < {min_val:g}",
        "  0.3 = has_real_data but only baseline measured",
        "  0.2 = no real values in artifacts",
        "",
        "Always extract actual numbers into metrics dict:",
        "  metrics = {" + ", ".join(f"{m}: <value>" for m in expected_metrics) + "}",
    ]
    return "\n".join(lines)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="make_metric_spec",
            description=(
                "Receives experiment file text and generates MetricSpec (expected_metrics,"
                "metric_keyword, scoring_guide, min_expected_metric) and returns it."
                "No LLM. Deterministic template-based."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "experiment_text": {
                        "type": "string",
                        "description": "Full text of the experiment file (.md)",
                    }
                },
                "required": ["experiment_text"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "make_metric_spec":
        raise ValueError(f"Unknown tool: {name}")

    text = arguments["experiment_text"]
    expected_metrics = _parse_success_metrics(text)
    metric_keyword = _parse_metric_keyword(text)
    min_expected = _parse_min_expected(text)

    # If the experiment file does not specify metrics, delegate to LLM
    if not expected_metrics or not metric_keyword:
        try:
            import litellm as _litellm, os as _os
            _model = (_os.environ.get("ARI_MODEL_EVAL")
                      or _os.environ.get("ARI_MODEL")
                      or _os.environ.get("ARI_LLM_MODEL")
                      or "gpt-4o-mini")
            _resp = await _litellm.acompletion(
                model=_model,
                messages=[{
                    "role": "system",
                    "content": (
                        "You are a research evaluation expert. "
                        "Given an experiment description, identify: "
                        "(1) the primary numeric metric to maximize/minimize (one short name, e.g. GFLOP_per_s), "
                        "(2) whether higher is better, "
                        "(3) a list of all relevant metric names the experiment should report. "
                        "Respond ONLY with JSON: "
                        '{{"metric_keyword":"<name>","higher_is_better":true,"expected_metrics":["<m1>","<m2>"]}}'
                    ),
                }, {
                    "role": "user",
                    "content": "Experiment description:\n" + text[:2000]
                }],
                temperature=0.0,
                max_tokens=200,
            )
            import json as _json, re as _re
            _raw = _resp.choices[0].message.content or ""
            _m = _re.search(r"\{.*\}", _raw, _re.DOTALL)
            if _m:
                _parsed = _json.loads(_m.group(0))
                if not metric_keyword:
                    metric_keyword = _parsed.get("metric_keyword", "")
                if not expected_metrics:
                    expected_metrics = _parsed.get("expected_metrics", [])
        except Exception as _e:
            pass  # Fall through to empty defaults

    scoring_guide = _build_scoring_guide(expected_metrics, metric_keyword, min_expected)

    result = {
        "expected_metrics": expected_metrics,
        "metric_keyword": metric_keyword,
        "min_expected_metric": min_expected,
        "scoring_guide": scoring_guide,
    }
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


def _build_artifact_extractor_source(metric_keyword: str | None) -> str:
    """Return the source code of an artifact_extractor function for the given metric_keyword (deterministic).

    Returns a Python code string that can be eval()ed or exec()ed.
    If keyword is None, returns generic numeric extraction code.
    """
    if metric_keyword:
        return (
            f"import re as _re\n"
            f"def _auto_artifact_extractor(text):\n"
            f"    matches = _re.findall(r'{metric_keyword}[:\\s=]+([\\d,]+\\.?\\d*)', text, _re.IGNORECASE)\n"
            f"    result = {{}}\n"
            f"    for i, v in enumerate(matches):\n"
            f"        try:\n"
            f"            val = float(v.replace(',', ''))\n"
            f"            result['{metric_keyword}_' + ('serial' if i == 0 else f'run_{{i}}')] = val\n"
            f"        except ValueError:\n"
            f"            pass\n"
            f"    return result\n"
        )
    else:
        # Generic: extract all significant numeric values (>= 1.0)
        return (
            "import re as _re\n"
            "def _auto_artifact_extractor(text):\n"
            "    nums = [float(x) for x in _re.findall(r'\\b(\\d+\\.\\d+)\\b', text) if float(x) >= 1.0]\n"
            "    return {'metric_' + str(i): v for i, v in enumerate(nums[:10])}\n"
        )


if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server
    async def main():
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())
    asyncio.run(main())
