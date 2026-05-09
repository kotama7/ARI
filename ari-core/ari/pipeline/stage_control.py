"""loop_back / VLM-feedback control helpers (Phase 3C).

Two pure helpers extracted from the legacy ``ari/pipeline.py``:

- :func:`_should_loop_back` — examine a stage result against the
  ``loop_threshold`` / ``loop_when_result_key`` YAML knobs.
- :func:`_format_vlm_feedback` — flatten a VLM-style review dict into
  a text block ready to inject into the regenerator's system prompt.
"""

from __future__ import annotations

from typing import Any


def _should_loop_back(stage_cfg: dict, result: Any) -> bool:
    """Decide whether a stage's result triggers a loop_back_to jump.

    Supported YAML fields:
    - loop_threshold: numeric — loop if `result["score"] < loop_threshold`
    - loop_when_result_key: str — loop if `result[key]` is truthy

    Returns False if result is not a dict (no signal to act on).
    """
    if not isinstance(result, dict):
        return False
    threshold = stage_cfg.get("loop_threshold")
    if threshold is not None:
        try:
            score = float(result.get("score", 1.0))
        except (TypeError, ValueError):
            score = 1.0
        if score < float(threshold):
            return True
    when_key = stage_cfg.get("loop_when_result_key")
    if when_key and result.get(when_key):
        return True
    return False


def _format_vlm_feedback(result: dict) -> str:
    """Flatten a VLM-style review result dict into a text block suitable for
    injection into a regeneration stage's system prompt.

    Consumes keys produced by vlm-skill:review_figure and review_figures_all:
        score, issues, suggestions, review_text. The aggregate variant also
        emits per_figure (ignored here — feedback to the regenerator goes
        through the prefixed [fig_id] entries already in issues/suggestions).
    """
    parts: list[str] = []
    if "score" in result:
        try:
            parts.append(f"Previous VLM score: {float(result['score']):.2f}")
        except (TypeError, ValueError):
            parts.append(f"Previous VLM score: {result['score']}")
    _issues = result.get("issues") or []
    if isinstance(_issues, str):
        _issues = [_issues]
    if _issues:
        parts.append("Issues reported: " + "; ".join(str(i) for i in _issues))
    _sugg = result.get("suggestions") or []
    if isinstance(_sugg, str):
        _sugg = [_sugg]
    if _sugg:
        parts.append("Suggested improvements: " + "; ".join(str(s) for s in _sugg))
    if result.get("review_text"):
        parts.append(f"Reviewer notes: {result['review_text']}")
    return "\n".join(parts)
