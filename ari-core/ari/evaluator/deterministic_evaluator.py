"""Deterministic, non-LLM evaluator for the handoff study (B2).

Selected via ``ARI_EVALUATOR=deterministic`` (see ``ari/core.py``). Unlike
``LLMEvaluator`` it calls no LLM judge: it owns the measurement (a fixed
reference oracle + timing harness) so node scores are reproducible and
un-gameable. The score it writes to ``metrics["_scientific_score"]`` (normalized
to ``[0, 1]``) is exactly what BFTS selection / parent-retire / the sterile gate
consume (``ari/orchestrator/bfts.py:336`` etc.), so this evaluator is what makes
the deterministic selector (G9a) meaningful and removes the LLM judge from the
loop (PREREG §7).

This module owns the SCORING CONTRACT (pure, unit-tested here): geomean over the
fixed family set, the PREREG ``min(geomean / TARGET, 1.0)`` normalization, and
the "node-invalid if any required family fails" rule (no zeros mixed into the
geomean). The SpMM kernel compile + run + timing + reference-oracle correctness
(per-row epsilon model) lives under ``ari-core/handoff_study/spmm/`` (added
separately; compute-node validated) and is invoked through ``measure_fn``.

Contract returned by ``evaluate_sync`` (and async ``evaluate``):
``{"metrics": {"_scientific_score": float, "valid_geomean_speedup": float, ...},
   "has_real_data": bool, "scientific_score": float, "valid": bool,
   "reason": str}``. ``node.metrics`` is populated from ``["metrics"]`` at
``ari/agent/loop.py``, so ``_scientific_score`` MUST live inside ``metrics``.

See ari-core/ari/evaluator/Plan.md and ari-core/PREREG_handoff_study.md.
"""

from __future__ import annotations

import math
import os
from typing import Any, Callable


def geomean(values: list[float]) -> float:
    """Geometric mean of strictly-positive values; 0.0 if none are positive."""
    vals = [float(v) for v in values if v is not None and float(v) > 0.0]
    if not vals:
        return 0.0
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def scientific_score(geomean_speedup: float | None, target: float = 4.0) -> float:
    """Map a (>=0) geomean speedup to [0, 1] for BFTS selection.

    PREREG: ``s = min(geomean_speedup / TARGET, 1.0)`` with TARGET=4.0x. Keeping
    the score in [0, 1] keeps it commensurable with the diversity bonus the
    deterministic frontier scorer adds (``ari/orchestrator/bfts.py``).
    """
    if not geomean_speedup or geomean_speedup <= 0.0 or target <= 0.0:
        return 0.0
    return min(float(geomean_speedup) / float(target), 1.0)


def gamma(k: int, u: float) -> float:
    """Backward-stable summation error factor ``k*u / (1 - k*u)`` (PREREG eps model).

    Used by the SpMM oracle's per-output-element correctness bound
    ``|y_cand - y_ref| <= C * gamma_k * sum(|A||x|)``. ``inf`` when ``k*u >= 1``
    (the bound is vacuous — the row is too long for the working precision).
    """
    ku = float(k) * float(u)
    return ku / (1.0 - ku) if ku < 1.0 else float("inf")


def _default_measure(work_dir: str) -> dict:
    """Invoke the SpMM harness measurement (compute-node validated; added in B2b).

    Importing lazily so the evaluator/dispatch are usable before the kernel
    harness lands. Raises a clear error if the harness is not yet installed.
    """
    try:
        from ari_handoff_study.spmm.measure import measure_node  # type: ignore
    except Exception as e:  # pragma: no cover - harness not yet present (B2b)
        raise RuntimeError(
            "SpMM harness not installed (ari-core/handoff_study/spmm). "
            "DeterministicEvaluator needs the kernel measurement harness (B2b). "
            f"underlying import error: {e}"
        )
    return measure_node(work_dir)


class DeterministicEvaluator:
    """Protocol-compatible (``ari/protocols/evaluator.py``) deterministic judge.

    The loop calls ``evaluate_sync`` (NOT the async ``evaluate``) at
    ``ari/agent/loop.py``; both are provided. ``measure_fn`` is injectable for
    testing; in production it defaults to the SpMM harness (B2b).
    """

    def __init__(
        self,
        *,
        target_speedup: float | None = None,
        measure_fn: Callable[[str], dict] | None = None,
        **_ignored: Any,
    ) -> None:
        if target_speedup is None:
            try:
                target_speedup = float(os.environ.get("ARI_SPMM_TARGET", "4.0"))
            except ValueError:
                target_speedup = 4.0
        self.target = target_speedup
        self._measure_fn = measure_fn
        # Present so callers that introspect metric_spec (node_report builder)
        # do not break; the deterministic evaluator does not use it.
        self.metric_spec = None

    def _score(self, result: dict) -> dict:
        """Map a harness measurement dict to the evaluator return contract.

        ``result`` shape: ``{"compile_ok": bool, "reason": str,
        "families": {name: {"speedup": float, "valid": bool}, ...}}``.
        """
        families = result.get("families") or {}
        compile_ok = bool(result.get("compile_ok", False))
        # PREREG: a node is invalid if it fails to compile OR any required family
        # is invalid. Invalid families are NOT mixed into the geomean as zeros.
        all_valid = bool(compile_ok and families) and all(
            bool(f.get("valid")) for f in families.values()
        )
        g = geomean([f.get("speedup", 0.0) for f in families.values()]) if all_valid else 0.0
        s = scientific_score(g, self.target)
        metrics: dict[str, Any] = {
            "_scientific_score": s,
            "valid_geomean_speedup": g,
        }
        for name, f in families.items():
            metrics[f"speedup_{name}"] = float(f.get("speedup", 0.0) or 0.0)
        return {
            "metrics": metrics,
            "has_real_data": all_valid,
            "scientific_score": s,
            "valid": all_valid,
            "reason": str(result.get("reason", "deterministic SpMM evaluation")),
        }

    def evaluate_sync(
        self,
        goal: str,
        artifacts: list[dict],
        summary: str,
        node_id: str | None = None,
        node_label: str | None = None,
    ) -> dict:
        work_dir = os.environ.get("ARI_WORK_DIR", "")
        try:
            measure = self._measure_fn or _default_measure
            result = measure(work_dir)
        except Exception as e:
            return {
                "metrics": {"_scientific_score": 0.0, "valid_geomean_speedup": 0.0},
                "has_real_data": False,
                "scientific_score": 0.0,
                "valid": False,
                "reason": f"deterministic eval error: {e}",
            }
        return self._score(result)

    async def evaluate(
        self,
        goal: str,
        artifacts: list[dict],
        summary: str,
        node_id: str | None = None,
        node_label: str | None = None,
    ) -> dict:
        return self.evaluate_sync(goal, artifacts, summary, node_id, node_label)
