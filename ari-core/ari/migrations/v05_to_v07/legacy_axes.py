"""Legacy 5-axis evaluator-score fallback (Phase 5).

ari/evaluator/llm_evaluator.py historically inlined a fallback that
read ``scientific_score`` from the legacy evaluator output and copied
it across every axis.  v0.6+ writes per-axis scores directly, but
existing checkpoints still rely on the fallback for replay.

The plan (REFACTORING.md §8) is to keep the helper available without
having it confuse the main flow; the evaluator delegates here.
"""

from __future__ import annotations

from typing import Iterable


def legacy_uniform_axis_scores(
    data: dict,
    iter_names: Iterable[str],
) -> dict:
    """Return a per-axis score dict derived from a legacy
    ``scientific_score`` value (clamped to [0, 1]).

    When the legacy field is missing or non-numeric, every axis
    defaults to ``0.0`` so the evaluator's downstream weighting pipeline
    still receives a complete dict.
    """
    names = list(iter_names)
    legacy = data.get("scientific_score")
    if legacy is None:
        return {k: 0.0 for k in names}
    try:
        uniform = max(min(float(legacy), 1.0), 0.0)
    except (TypeError, ValueError):
        uniform = 0.0
    return {k: uniform for k in names}
