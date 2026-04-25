"""ari-skill-paper-re: Reproducibility verification helpers.

This skill no longer drives a ReAct loop. The ReAct loop is driven by
``ari-core/ari/agent/react_driver.py`` from the workflow pipeline, which
uses the MCP skill set filtered by ``phase: reproduce`` declared in
``workflow.yaml``. This skill provides only the deterministic endpoints:

- ``extract_repro_config`` — one-shot LLM call extracting the paper's
  advertised metric value and experimental parameters.
- ``build_repro_report`` — one-shot LLM call producing the final verdict
  and interpretation given claimed + actual measurements.
- ``extract_metric_from_output`` — helper the ReAct agent may call to
  parse a numeric metric from raw benchmark stdout.

All three are P2 exceptions (single-shot LLM usage).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path

import litellm
from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)

mcp = FastMCP("paper-reproducibility-skill")

try:
    from ari import cost_tracker as _ari_cost_tracker  # type: ignore
    _ari_cost_tracker.bootstrap_skill("paper-re")
except Exception:
    pass


# ─── LLM helpers ──────────────────────────────────────────────────────

def _model() -> str:
    # Phase-specific override so the GUI's per-phase model picker takes effect.
    return (
        os.environ.get("ARI_MODEL_PAPER")
        or os.environ.get("ARI_LLM_MODEL")
        or os.environ.get("LLM_MODEL")
        or "ollama_chat/qwen3:32b"
    )


def _api_base() -> str | None:
    ari = os.environ.get("ARI_LLM_API_BASE")
    if ari is not None:
        return ari or None
    legacy = os.environ.get("LLM_API_BASE", "")
    if legacy:
        return legacy
    if _model().startswith("ollama"):
        return "http://127.0.0.1:11434"
    return None


async def _llm(system: str, user: str, timeout: int = 120) -> str:
    kwargs: dict = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "timeout": timeout,
    }
    base = _api_base()
    if base:
        kwargs["api_base"] = base
    resp = await litellm.acompletion(**kwargs)
    raw = resp.choices[0].message.content or ""
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


def _load_paper_text(paper_path: str, paper_text: str) -> str:
    """Resolve paper content from either an inline string or a path."""
    if paper_text:
        return paper_text
    if not paper_path:
        return ""
    p = Path(paper_path)
    if p.suffix == ".pdf":
        try:
            r = subprocess.run(
                ["pdftotext", str(p), "-"],
                capture_output=True, text=True, timeout=30,
            )
            if r.stdout:
                return r.stdout
        except Exception:
            pass
    try:
        return p.read_text()
    except Exception as e:
        log.warning("Cannot read paper at %s: %s", paper_path, e)
        return ""


def _clip_paper(paper_text: str, head: int = 20000, tail: int = 10000) -> str:
    """Truncate a long paper to a head+tail snippet so the LLM fits in context."""
    limit = head + tail
    if len(paper_text) <= limit:
        return paper_text
    return paper_text[:head] + "\n\n[...truncated...]\n\n" + paper_text[-tail:]


# ─── MCP tools ────────────────────────────────────────────────────────


@mcp.tool()
async def extract_repro_config(
    paper_path: str = "",
    paper_text: str = "",
) -> dict:
    """Extract the paper's advertised result and its exact configuration.

    Returns ``{metric_name, claimed_value, description, threads}`` where
    ``threads`` is an int parsed from the description when stated, else 0.
    """
    text = _load_paper_text(paper_path, paper_text)
    if not text:
        return {"error": "No paper text provided", "metric_name": "", "claimed_value": 0.0}

    snippet = _clip_paper(text)

    system = (
        "Extract the PRIME experimental result from the paper — the value "
        "highlighted in the abstract and conclusion as the paper's main "
        "achievement. This is NOT necessarily from the 'main' benchmark "
        "setup; it is the number the authors chose to advertise. "
        "Do NOT use theoretical peaks, roofline upper bounds, or predictions. "
        "Include in the description the EXACT experimental parameters "
        "(all sizes, settings, configuration) stated near the claimed value. "
        "Return ONLY JSON: {\"metric_name\": str, \"claimed_value\": float, "
        "\"description\": str}. No markdown."
    )

    raw = await _llm(system, f"Paper:\n{snippet}")
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {
            "error": "Could not extract config from LLM output",
            "raw": raw[:500],
            "metric_name": "", "claimed_value": 0.0, "description": "",
        }
    try:
        cfg = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return {
            "error": f"JSON parse failed: {e}",
            "raw": raw[:500],
            "metric_name": "", "claimed_value": 0.0, "description": "",
        }

    metric_name   = str(cfg.get("metric_name") or "metric")
    claimed_value = float(cfg.get("claimed_value") or 0.0)
    description   = str(cfg.get("description") or "")

    threads = 0
    m_thr = re.search(r"(\d+)\s*(?:OpenMP\s+)?threads", description, re.IGNORECASE)
    if m_thr:
        try:
            threads = int(m_thr.group(1))
        except ValueError:
            pass

    return {
        "metric_name":   metric_name,
        "claimed_value": claimed_value,
        "description":   description,
        "threads":       threads,
    }


@mcp.tool()
async def extract_metric_from_output(output_text: str, metric_name: str) -> dict:
    """Extract a numeric metric value from raw benchmark output text."""
    prompt = (
        f"Extract the {metric_name} value from the output below.\n"
        "Return ONLY valid JSON: {\"value\": float or null, \"unit\": str, "
        "\"raw_match\": str}\n"
        f"Output:\n{output_text[-2000:]}"
    )
    try:
        kwargs: dict = {
            "model": _model(),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "timeout": 60,
        }
        base = _api_base()
        if base:
            kwargs["api_base"] = base
        resp = await litellm.acompletion(**kwargs)
        raw = resp.choices[0].message.content or ""
        if "</think>" in raw:
            raw = raw.split("</think>")[-1]
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s >= 0 and e > s:
            res = json.loads(raw[s:e])
            if res.get("value") is not None:
                res["value"] = float(res["value"])
            return res
    except Exception:
        pass

    # Regex fallback
    m = re.search(
        r"METRIC[:\s]+([0-9]+\.?[0-9]*(?:e[+-]?[0-9]+)?)",
        output_text, re.IGNORECASE,
    )
    if m:
        return {"value": float(m.group(1)), "unit": "", "raw_match": m.group(0)}
    return {"value": None, "unit": "", "raw_match": "", "error": "extraction failed"}


@mcp.tool()
async def build_repro_report(
    claimed_config: dict,
    actual_value: float | None = None,
    actual_unit: str = "",
    actual_notes: str = "",
    tolerance_pct: float = 5.0,
) -> dict:
    """Compare actual vs. claimed and return a verdict + interpretation.

    Called after the ReAct driver finishes. ``actual_value`` is the value
    the agent reported via its ``report_metric`` final-tool; ``None`` means
    the agent never produced a reliable measurement.
    """
    metric_name   = str(claimed_config.get("metric_name") or "metric")
    claimed_value = float(claimed_config.get("claimed_value") or 0.0)

    diff_pct: float | None = None
    if actual_value is not None and claimed_value != 0:
        diff_pct = abs(float(actual_value) - claimed_value) / claimed_value * 100.0

    if actual_value is None:
        verdict = "UNVERIFIABLE"
    elif diff_pct is None:
        verdict = "UNVERIFIABLE"
    elif diff_pct <= tolerance_pct:
        verdict = "REPRODUCED"
    elif diff_pct <= 20.0:
        verdict = "PARTIAL"
    else:
        verdict = "NOT_REPRODUCED"

    diff_str = f"{diff_pct:.1f}%" if diff_pct is not None else "N/A"
    notes_ctx = f" Agent notes: {actual_notes[:200]}" if actual_notes else ""
    try:
        interpretation = await _llm(
            "Write a 2-3 sentence reproducibility verdict. Be factual, concise. "
            "No markdown.",
            f"Paper claims {claimed_value} {metric_name}. "
            f"Measured: {actual_value}. "
            f"Verdict: {verdict} (diff: {diff_str}).{notes_ctx}",
            timeout=60,
        )
    except Exception as e:
        log.warning("interpretation LLM failed: %s", e)
        interpretation = (
            f"{verdict}. Claimed={claimed_value} {metric_name}, "
            f"measured={actual_value} (diff {diff_str})."
        )

    return {
        "verdict":        verdict,
        "claimed_config": claimed_config,
        "claimed_value":  claimed_value,
        "actual_value":   actual_value,
        "actual_unit":    actual_unit,
        "actual_notes":   actual_notes,
        "diff_pct":       round(diff_pct, 2) if diff_pct is not None else None,
        "metric_name":    metric_name,
        "tolerance_pct":  tolerance_pct,
        "interpretation": interpretation,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
