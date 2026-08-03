"""ari-skill-replicate: ORS Auto-Rubric (PaperBench-format) MCP server.

Tools:
    - generate_rubric : produce a PaperBench-compatible auto rubric from a paper.
    - audit_rubric    : flag quality issues (vague / no_paper_evidence / duplicate / unverifiable).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from auditor import audit_rubric_async
from generator import compute_target_leaf_count, generate_rubric_async

log = logging.getLogger(__name__)

mcp = FastMCP("replicate-skill")

try:  # cost-tracker bootstrap, harmless if absent
    from ari.public import cost_tracker as _ari_cost_tracker  # type: ignore

    _ari_cost_tracker.bootstrap_skill("replicate")
except Exception:
    pass


def _load_paper_text(paper_path: str, paper_text: str) -> str:
    """Resolve paper content from either an inline string or a path."""
    if paper_text:
        return paper_text
    if not paper_path:
        return ""
    p = Path(paper_path)
    if p.suffix == ".pdf":
        try:
            import fitz

            with fitz.open(p) as document:
                return "\n".join(page.get_text() for page in document)
        except Exception:
            pass
    try:
        return p.read_text()
    except Exception as e:
        log.warning("Cannot read paper at %s: %s", paper_path, e)
        return ""


def _resolve_env_overrides(
    target_leaf_count: int, temperature: float
) -> tuple[int, float]:
    """Apply ``ARI_RUBRIC_GEN_*`` env-var overrides set by the GUI/wizard.

    The web GUI persists wizard ORS settings as env vars (see
    ari-core/ari/viz/api_experiment.py), but historically only the model
    var was consumed. This makes target leaves and temperature take effect
    when the workflow stage doesn't pass them
    explicitly. Env var wins when set; kwarg default applies otherwise.
    """
    env_l = os.environ.get("ARI_RUBRIC_GEN_TARGET_LEAVES", "").strip()
    if env_l:
        try:
            target_leaf_count = int(env_l)
        except ValueError:
            pass
    env_t = os.environ.get("ARI_RUBRIC_GEN_TEMPERATURE", "").strip()
    if env_t:
        try:
            temperature = float(env_t)
        except ValueError:
            pass
    return target_leaf_count, temperature


@mcp.tool()
async def generate_rubric(
    paper_path: str = "",
    paper_text: str = "",
    output_path: str = "",
    target_leaf_count: int = 0,
    model: str = "",
    temperature: float = 0.0,
    seed: int = 0,
    paperbench_rubric_id: str = "",
    max_model_calls: int = 64,
    subtree_concurrency: int = 4,
    provider: str = "",
    model_revision: str = "",
) -> dict:
    """Generate a PaperBench-compatible auto rubric from paper text.

    Args:
        paper_path: path to .tex / .pdf / .txt. Used when ``paper_text`` is empty.
        paper_text: inline paper text (overrides ``paper_path``).
        output_path: target file for the frozen rubric JSON envelope.
        target_leaf_count: 0 → auto-computed from paper length (~1 leaf / 75 words,
            bounded to [50, 400]). Otherwise the explicit target.
        model: override for ``ARI_MODEL_RUBRIC_GEN``.
        temperature: generator temperature (recorded in manifest).
        seed: optional generator seed (>0 to record).
        paperbench_rubric_id: empty string → bundled prompt verbatim
            (back-compat). Otherwise the ID of a YAML template under
            ``ari-core/config/paperbench_rubrics/`` (e.g. "sc" for the
            HPC paper-audit rubric described in
            HPC PaperBench audit research plan §5 Step 3).

    Returns:
        dict with ``rubric_path``, ``rubric_sha256``, ``leaves_count``,
        ``depth``, ``category_breakdown``, ``warnings`` (or ``error`` on
        terminal failure).
    """
    text = _load_paper_text(paper_path, paper_text)
    if not text:
        return {"error": "No paper text provided"}
    if not output_path:
        return {"error": "output_path is required"}
    seed_arg = int(seed) if seed else None
    target_leaf_count, temperature = _resolve_env_overrides(
        int(target_leaf_count), float(temperature)
    )
    rubric_id_arg = paperbench_rubric_id.strip() or None
    return await generate_rubric_async(
        paper_text=text,
        output_path=output_path,
        target_leaf_count=target_leaf_count,
        model=model,
        temperature=temperature,
        seed=seed_arg,
        paperbench_rubric_id=rubric_id_arg,
        max_model_calls=int(max_model_calls),
        subtree_concurrency=int(subtree_concurrency),
        provider=provider,
        model_revision=model_revision or None,
    )


@mcp.tool()
async def audit_rubric(
    rubric_path: str,
    paper_path: str = "",
    paper_text: str = "",
    auditor_model: str = "",
    output_path: str = "",
    max_model_calls: int = 400,
) -> dict:
    """Write an independent audit without mutating the frozen rubric.

    Flags applied per leaf:
        - vague_qualifier   : non-operational language ("appropriate", "good", ...)
        - no_paper_evidence : rationale_from_paper.quote not present in paper
        - duplicate         : another leaf has the same normalized requirements
        - unverifiable      : LLM-judged uncheckable from artifacts alone

    Returns audit summary including ``regen_recommended`` (True if >20% leaves
    flagged).
    """
    text = _load_paper_text(paper_path, paper_text)
    return await audit_rubric_async(
        rubric_path=rubric_path,
        paper_text=text,
        auditor_model=auditor_model,
        output_path=output_path,
        max_model_calls=max_model_calls,
    )


@mcp.tool()
async def suggest_target_leaf_count(paper_path: str = "", paper_text: str = "") -> dict:
    """Helper: return the auto-computed target leaf count for a paper."""
    text = _load_paper_text(paper_path, paper_text)
    if not text:
        return {"error": "No paper text provided", "target": 0}
    return {"target": compute_target_leaf_count(text), "word_count": len(text.split())}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
