"""Rubric-driven paper review engine.

Implements the AI Scientist v1/v2-compatible review pipeline per plan.md:
    - rubric YAML-driven prompts (score dimensions, text sections, decision)
    - reflection loop (self-critique rounds, +2% accuracy per Nature Ablation)
    - few-shot examples (static file-based, or dynamic OpenReview retrieval)
    - VLM figure findings injected as reviewer notes
    - ensemble (N independent reviews) + Area Chair meta-review

The engine is deliberately independent of the MCP layer so it can be unit-tested
without a running MCP server.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

try:
    from src.rubric import Rubric, RubricError, load_rubric  # type: ignore
except ImportError:  # running from within the src/ directory
    from rubric import Rubric, RubricError, load_rubric  # type: ignore

log = logging.getLogger(__name__)


# Type of async LLM caller: (messages, temperature, model) -> response text
LLMCaller = Callable[[list[dict], float, str | None], Awaitable[str]]


@dataclass
class FewshotExample:
    paper_id: str
    paper_text: str  # typically truncated
    review_json: dict
    source: str = ""  # file path or URL


def _extract_json(raw: str) -> dict:
    """Extract the outermost JSON object from an LLM response."""
    if "</think>" in raw:
        raw = raw.split("</think>")[-1]
    s = raw.find("{")
    e = raw.rfind("}") + 1
    if s < 0 or e <= s:
        return {}
    try:
        return json.loads(raw[s:e])
    except Exception:
        return {}


def build_system_prompt(rubric: Rubric) -> str:
    """Build the reviewer system prompt from the rubric schema."""
    dim_lines = []
    for d in rubric.score_dimensions:
        dim_lines.append(
            f"  {d.name}: int {d.scale[0]}-{d.scale[1]} — {d.description}"
        )
    text_lines = []
    for s in rubric.text_sections:
        req = " (required)" if s.required else " (optional)"
        text_lines.append(f"  {s.name}: string{req}")

    decision_opts = ", ".join(rubric.decision.options)
    dec_line = (
        f"  decision: one of [{decision_opts}] "
        f"(threshold: {rubric.decision.threshold_dimension} "
        f">= {rubric.decision.threshold_value})"
    )

    hint = rubric.system_hint or ""

    return (
        f"You are a rigorous peer reviewer for {rubric.venue} ({rubric.domain}). "
        f"{hint}\n"
        f"Evaluate the paper and return ONLY valid JSON with these exact keys:\n"
        + "\n".join(dim_lines)
        + "\n"
        + "\n".join(text_lines)
        + "\n"
        + dec_line
        + "\n"
        + "No markdown, no prose outside JSON."
    )


def _truncate_paper(text: str, max_chars: int = 50000) -> str:
    if len(text) <= max_chars:
        return text
    keep_head = int(max_chars * 0.8)
    keep_tail = max_chars - keep_head
    return (
        text[:keep_head]
        + "\n\n[... middle truncated ...]\n\n"
        + text[-keep_tail:]
    )


def build_user_prompt(
    rubric: Rubric,
    paper_text: str,
    captions: list[str],
    citation_note: str,
) -> str:
    """Build the reviewer user prompt.

    Reviewer independence contract: this function must NOT inject the VLM
    figure review, the research brief (experiment_summary), or the figures
    manifest. The text reviewer evaluates the paper text only, matching the
    AI Scientist v2 `perform_review` contract (ai_scientist/review/llm_review.py).
    The VLM review runs independently via the vlm_review_figures stage and is
    combined post-hoc by the merge_reviews stage — see workflow.yaml.
    """
    snippet = _truncate_paper(paper_text)
    caps = "\n".join(f"- {c}" for c in captions[:8]) if captions else "(none)"

    return (
        f"Paper text ({len(snippet)} chars):\n{snippet}\n\n"
        f"Figure captions (from LaTeX):\n{caps}\n\n"
        f"Citation audit: {citation_note}"
    )


def load_static_fewshot(rubric: Rubric) -> list[FewshotExample]:
    """Load few-shot examples from rubric.fewshot_dir (static mode).

    Expected layout:
        <fewshot_dir>/<paper_id>.pdf   (or .txt)
        <fewshot_dir>/<paper_id>.json  (completed review form)

    Returns at most rubric.params.num_fs_examples in deterministic sorted order.
    """
    n = rubric.params.num_fs_examples
    if n <= 0 or not rubric.params.fewshot_dir:
        return []
    # Resolve fewshot_dir relative to rubric source file first, then cwd
    rubric_dir = Path(rubric.source_path).parent if rubric.source_path else Path.cwd()
    candidates = [
        rubric_dir / rubric.params.fewshot_dir,
        Path(rubric.params.fewshot_dir),
    ]
    base: Path | None = None
    for c in candidates:
        if c.exists():
            base = c
            break
    if not base:
        log.debug("fewshot_dir not found: %s", rubric.params.fewshot_dir)
        return []

    jsons = sorted(base.glob("*.json"))[:n]
    out: list[FewshotExample] = []
    for jp in jsons:
        try:
            review = json.loads(jp.read_text())
        except Exception as e:
            log.warning("skip malformed fewshot review %s: %s", jp, e)
            continue
        # paper text: prefer .txt sibling, else .pdf stem (no extract)
        stem = jp.with_suffix("")
        text = ""
        txt_path = stem.with_suffix(".txt")
        if txt_path.exists():
            try:
                text = txt_path.read_text(errors="ignore")
            except Exception:
                pass
        elif stem.with_suffix(".md").exists():
            text = stem.with_suffix(".md").read_text(errors="ignore")
        out.append(
            FewshotExample(
                paper_id=jp.stem,
                paper_text=text[:8000],  # keep prompt budget under control
                review_json=review,
                source=str(jp),
            )
        )
    return out


def load_dynamic_fewshot(
    rubric: Rubric,
    title: str,
    abstract: str,
) -> list[FewshotExample]:
    """Retrieve similar papers + reviews from OpenReview (Phase 2).

    Falls back to an empty list when:
        - openreview-py is not installed
        - network is unavailable
        - rubric does not declare a compatible venue

    When `strict_dynamic=true` env is set, failures raise instead of falling back.
    """
    if rubric.params.fewshot_mode != "dynamic":
        return []
    strict = os.environ.get("ARI_STRICT_DYNAMIC", "").lower() in ("1", "true", "yes")
    # Cache key for determinism (Phase 2)
    sig_src = f"{title}\n{abstract}\n{rubric.hash}\n{rubric.params.fewshot_dir}"
    sig = hashlib.sha256(sig_src.encode("utf-8", errors="ignore")).hexdigest()[:16]
    cache_dir = Path(os.environ.get("ARI_CHECKPOINT_DIR", ".")) / ".ari_fewshot_cache"
    cache_file = cache_dir / f"{sig}.json"
    if cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text())
            return [FewshotExample(**p) for p in payload]
        except Exception as e:
            log.warning("cache miss (corrupt) %s: %s", cache_file, e)

    try:
        import openreview  # type: ignore  # noqa: F401
    except ImportError:
        if strict:
            raise RubricError(
                "Dynamic fewshot requested but openreview-py not installed. "
                "Install with: pip install ari-skill-paper[retrieval]"
            )
        log.info("openreview-py not installed; dynamic fewshot falls back to static")
        return load_static_fewshot(rubric)

    # Placeholder for Phase 2 retrieval implementation. In the MVP we keep the
    # code path wired but defer the actual API calls to a future change so the
    # test suite can run without network access. Real implementation would:
    #   1. search OpenReview for papers in rubric.venue within year range
    #   2. score by abstract embedding similarity
    #   3. balance by score spectrum
    #   4. cache payload to cache_file
    log.info(
        "dynamic fewshot retrieval placeholder invoked (sig=%s); "
        "returning static fallback. Wire implementation in "
        "ari_skill_paper.retrieval.openreview_client.",
        sig,
    )
    return load_static_fewshot(rubric)


def fewshot_block(examples: list[FewshotExample], rubric: Rubric | None = None) -> str:
    """Format few-shot examples as a prompt block (positioned before paper text)."""
    if not examples:
        return ""
    venue = (rubric.venue or "").strip() if rubric else ""
    preamble = (
        f"Below are sample reviews from previous {venue} submissions. "
        "Use them as format and calibration references.\n"
        if venue
        else "Below are sample reviews from prior submissions to this venue. "
        "Use them as format and calibration references.\n"
    )
    parts = [preamble]
    for i, ex in enumerate(examples, start=1):
        parts.append(f"=== EXAMPLE REVIEW #{i} (paper: {ex.paper_id}) ===")
        if ex.paper_text:
            parts.append(
                "Paper excerpt:\n" + ex.paper_text[:4000]
            )
        parts.append(
            "Completed review JSON:\n"
            + json.dumps(ex.review_json, ensure_ascii=False, indent=2)
        )
    parts.append("=== END EXAMPLES ===\n")
    return "\n\n".join(parts)


def decide(rubric: Rubric, scores: dict) -> str:
    """Compute the final decision from scores per rubric rules."""
    dim = rubric.decision.threshold_dimension
    thr = rubric.decision.threshold_value
    val = scores.get(dim)
    if not isinstance(val, (int, float)):
        return rubric.decision.options[-1]  # reject-ish fallback
    if rubric.decision.type == "binary":
        return rubric.decision.options[0] if val >= thr else rubric.decision.options[-1]
    # categorical: map by quantile into options
    opts = rubric.decision.options
    # Scale value into [0, 1] relative to threshold_dimension scale
    dim_obj = next(
        (d for d in rubric.score_dimensions if d.name == dim), None
    )
    if not dim_obj:
        return opts[len(opts) // 2]
    lo, hi = dim_obj.scale
    norm = (val - lo) / max(hi - lo, 1)
    norm = max(0.0, min(1.0, norm))
    idx = int(norm * (len(opts) - 1))
    # options assumed ordered best-first (e.g., [accept, weak_accept, ..., reject])
    # idx=0 -> best, idx=len-1 -> worst; invert because norm high = better score
    return opts[len(opts) - 1 - idx]


def normalize_review(rubric: Rubric, raw: dict) -> dict:
    """Shape the raw LLM JSON into the canonical review_report schema."""
    scores: dict[str, Any] = {}
    for d in rubric.score_dimensions:
        v = raw.get(d.name)
        if isinstance(v, (int, float)):
            # clamp to scale
            lo, hi = d.scale
            v = max(lo, min(hi, v))
        else:
            v = None
        scores[d.name] = v
    score_dimensions_out = [
        {"name": d.name, "value": scores[d.name], "scale": list(d.scale)}
        for d in rubric.score_dimensions
    ]
    text_fields = {}
    for s in rubric.text_sections:
        val = raw.get(s.name)
        if isinstance(val, list):
            val = "\n".join(str(x) for x in val)
        if val is not None:
            text_fields[s.name] = str(val)
    decision_val = raw.get("decision")
    if not isinstance(decision_val, str) or decision_val not in rubric.decision.options:
        decision_val = decide(rubric, scores)
    overall = scores.get("overall") or scores.get(rubric.decision.threshold_dimension)
    out = {
        "rubric_id": rubric.id,
        "rubric_version": rubric.version,
        "rubric_hash": rubric.hash,
        "venue": rubric.venue,
        "scores": scores,
        "score_dimensions": score_dimensions_out,
        "decision": decision_val,
        "overall_score": overall,
        # legacy compatibility mirrors
        "score": overall,
    }
    out.update(text_fields)
    # Pass through structural extras (issues, recommendations, figure_caption_issues)
    for extra in ("issues", "recommendations", "figure_caption_issues"):
        if extra in raw:
            out[extra] = raw[extra]
    conf = scores.get("confidence")
    if conf is not None:
        out["confidence"] = conf
    return out


async def run_single_review(
    rubric: Rubric,
    user_prompt: str,
    llm: LLMCaller,
    temperature: float | None = None,
    model: str | None = None,
    num_reflections: int | None = None,
    fewshot_examples: list[FewshotExample] | None = None,
) -> dict:
    """Run one reviewer agent: initial draft + reflection rounds.

    Reflection prompts the model to critique & improve its previous JSON.
    """
    temp = rubric.params.temperature if temperature is None else temperature
    reflections = (
        rubric.params.num_reflections if num_reflections is None else num_reflections
    )
    system = build_system_prompt(rubric)
    fs_block = fewshot_block(fewshot_examples or [], rubric)
    user = (fs_block + "\n\n" if fs_block else "") + user_prompt
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = await llm(messages, temp, model)
    draft = _extract_json(raw)
    reflection_trace = [draft]

    for i in range(max(0, reflections)):
        critique = (
            "Reconsider your previous review. Identify any inaccuracies, "
            "biases, unsupported claims, or weak calibration. Re-score and "
            "revise text sections. Return ONLY the improved JSON (same schema)."
        )
        messages2 = messages + [
            {"role": "assistant", "content": json.dumps(draft, ensure_ascii=False)},
            {"role": "user", "content": critique},
        ]
        try:
            raw2 = await llm(messages2, temp, model)
            improved = _extract_json(raw2)
            if improved:
                draft = improved
                reflection_trace.append(improved)
        except Exception as e:
            log.warning("reflection round %d failed: %s", i + 1, e)
            break

    norm = normalize_review(rubric, draft)
    norm["reflection_trace"] = reflection_trace
    return norm


async def run_ensemble(
    rubric: Rubric,
    user_prompt: str,
    llm: LLMCaller,
    fewshot_examples: list[FewshotExample] | None = None,
    n: int | None = None,
) -> list[dict]:
    """Run N independent reviewer agents with different seeds (temperature
    perturbation for diversity)."""
    count = rubric.params.num_reviews_ensemble if n is None else n
    count = max(1, count)
    base_temp = rubric.params.temperature
    reviews: list[dict] = []
    for i in range(count):
        # small temperature jitter to encourage diverse reviews
        temp = base_temp + (0.1 * ((i % 3) - 1)) if count > 1 else base_temp
        temp = max(0.0, min(1.5, temp))
        reviews.append(
            await run_single_review(
                rubric,
                user_prompt,
                llm,
                temperature=temp,
                fewshot_examples=fewshot_examples,
            )
        )
    return reviews


async def run_meta_review(
    rubric: Rubric,
    reviews: list[dict],
    llm: LLMCaller,
    model: str | None = None,
) -> dict:
    """Area Chair meta-review: aggregate ensemble into a final decision."""
    if not reviews:
        return {"error": "no reviews to aggregate"}
    if len(reviews) == 1:
        out = dict(reviews[0])
        out["meta_review_note"] = "single review, no aggregation performed"
        return out

    system = (
        f"You are an Area Chair at {rubric.venue}. "
        f"Given {len(reviews)} independent peer reviews of a paper, synthesize "
        f"the final decision. Weigh each review by its confidence. "
        f"Return ONLY valid JSON with the same schema as a single review "
        f"(same score dimensions, decision field, strengths/weaknesses summary)."
    )
    reviews_blob = json.dumps(
        [
            {k: v for k, v in r.items() if k != "reflection_trace"}
            for r in reviews
        ],
        ensure_ascii=False,
        indent=2,
    )
    user = f"Reviews to aggregate:\n{reviews_blob}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        raw = await llm(messages, rubric.params.temperature, model)
    except Exception as e:
        log.warning("meta_review LLM failed: %s", e)
        return {"error": f"meta_review failed: {e}", "reviews": reviews}
    raw_json = _extract_json(raw)
    meta = normalize_review(rubric, raw_json) if raw_json else {}
    meta["meta_review_note"] = (
        f"aggregated from {len(reviews)} reviews by Area Chair"
    )
    return meta


def resolve_rubric(rubric_id: str | None = None) -> Rubric:
    """Resolve the rubric to use: explicit arg > ARI_RUBRIC env > 'neurips'.

    On failure (unknown rubric id), falls back to 'neurips' — the default
    rubric that is guaranteed to ship with the repo. The legacy rubric was
    removed in v0.6.0.
    """
    rid = rubric_id or os.environ.get("ARI_RUBRIC") or "neurips"
    try:
        return load_rubric(rid)
    except RubricError:
        if rid == "neurips":
            raise
        log.warning("rubric %s not found; falling back to neurips", rid)
        return load_rubric("neurips")
