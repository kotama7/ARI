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


def scientific_score(geomean_speedup: float | None, target: float = 16.0,
                     scale: str = "linear") -> float:
    """Map a (>=0) geomean speedup to [0, 1] for BFTS selection.

    ``scale="linear"`` (SpMM): ``s = min(g / TARGET, 1.0)`` — TARGET is the
    parallel ceiling (thread budget, default 16) so the score spans the
    achievable range instead of saturating at a low bar.

    ``scale="log"`` (GEMM): ``s = min(log(g) / log(TARGET), 1.0)`` — GEMM speedups
    are MULTIPLICATIVE rungs (naive 1x, cache-order ~tens×, +parallel ~hundreds×),
    so log spacing keeps the rungs evenly separated; linear would crush the
    intermediate rungs to ~0 and hide the gradient the handoff acts on. ``g<=1``
    (no gain over the naive baseline) scores 0.
    """
    if not geomean_speedup or geomean_speedup <= 0.0 or target <= 0.0:
        return 0.0
    g = float(geomean_speedup)
    if scale == "log":
        if g <= 1.0 or target <= 1.0:
            return 0.0
        return min(math.log(g) / math.log(float(target)), 1.0)
    return min(g / float(target), 1.0)


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

    Problem size and the OpenMP thread budget are study parameters (frozen
    defaults, env-overridable). They MUST sit where parallelism actually pays
    off: on a many-core node a tiny matrix makes even a perfect kernel ~1x
    (parallel overhead dominates), which would collapse the study's dynamic
    range. Validated on a compute node — n=20000/k=64/16 threads gives a naive
    1x baseline room to reach ~12-15x, spanning the TARGET (16x, the thread
    budget) so the normalized score discriminates among good kernels.
    """
    return _harness().measure(work_dir)


def _harness():
    """Resolve this run's harness via the registry (packaged, or registered in
    ``workspace/harnesses/<task>/``).

    Replaces a hardcoded ``if task == ...`` chain: adding a task no longer needs
    an ARI core edit, and a study can pin its own frozen scaffolding next to its
    results so ``workspace + the ARI repo`` are self-contained.

    UNKNOWN TASKS: the old chain fell through to SpMM, i.e. a typo in ARI_TASK
    silently scored a DIFFERENT benchmark. The registry raises instead — see
    ``_resolve_task``.
    """
    from ari.harness_registry import load
    return load(_resolve_task())


def _resolve_task() -> str:
    """The task name, defaulting to ``spmm`` when ARI_TASK is unset.

    Unset -> "spmm" preserves the historical default. But a task that is SET and
    unknown is an error, not a silent fallback to SpMM: measuring the wrong
    benchmark and reporting it as the requested one is exactly the failure the
    registry exists to make impossible.
    """
    return os.environ.get("ARI_TASK", "spmm").strip().lower() or "spmm"


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
        scale: str | None = None,
        **_ignored: Any,
    ) -> None:
        self.task = _resolve_task()
        # Explicit values win; otherwise the harness DECLARES them (a GEMM speedup
        # is a multiplicative rung -> log with a ~256x ceiling; SpMM is linear at
        # the thread budget). Resolved lazily: this class also owns the
        # task-INDEPENDENT scoring contract, which callers unit-test with an
        # injected measure_fn and no harness at all.
        self._target_override = target_speedup
        self._scale_override = scale
        self._meta: tuple[float, str] | None = None
        self._measure_fn = measure_fn
        # Present so callers that introspect metric_spec (node_report builder)
        # do not break; the deterministic evaluator does not use it.
        self.metric_spec = None

    def _describe(self) -> tuple[float, str]:
        """``(target, scale)`` from the registered harness, resolved once.

        Falls back to the historical default when no harness is registered rather
        than raising. That cannot leak a wrong number into a real score: without a
        harness nothing can be measured either — ``load()`` raises inside
        ``evaluate_sync``, which records the reason and scores the node 0 — so
        these values only ever serve a caller that injects its own ``measure_fn``.
        """
        if self._meta is None:
            from ari.harness_registry import (
                HarnessIntegrityError,
                describe,
            )
            try:
                self._meta = describe(self.task)
            except HarnessIntegrityError:
                self._meta = (16.0, "linear")
        return self._meta

    @property
    def target(self) -> float:
        return self._describe()[0] if self._target_override is None else self._target_override

    @property
    def scale(self) -> str:
        return self._describe()[1] if self._scale_override is None else self._scale_override

    def _score(self, result: dict) -> dict:
        """Map a harness measurement dict to the evaluator return contract.

        ``result`` shape: ``{"compile_ok": bool, "reason": str,
        "families": {name: {"speedup": float, "valid": bool}, ...}}``.
        """
        # Score-shaped result (erfc / accuracy-coverage tasks): the score is
        # already a fraction in [0,1] — no speedup geomean / normalization. Map
        # it onto valid_geomean_speedup so the whole analyzer (best outcome,
        # distribution, child-improvement) works unchanged; child-improvement
        # then means "the child raised the score" — the cumulative-ladder signal.
        if "score" in result and "families" not in result:
            compile_ok = bool(result.get("compile_ok", False))
            # Clamp the harness-reported score to the [0,1] contract at the gate
            # (the module docstring promises [0,1]); a buggy/out-of-range harness
            # score must not enter BFTS ranking unbounded or negative. NaN is NOT
            # neutralized by min/max (min(nan,1)==nan), so map non-finite -> 0.
            _s_raw = float(result.get("score") or 0.0)
            s = min(max(_s_raw, 0.0), 1.0) if math.isfinite(_s_raw) else 0.0
            # Parity with the speedup path below: a node that did not compile
            # scores 0, and the RANKING METRIC — not just the `valid` flag — must
            # say so. BFTS reads metrics["_scientific_score"] directly and never
            # re-checks `valid` (orchestrator/bfts.py:339 frontier score;
            # cli/bfts_loop.py:786 _child_retires_parent), so leaving a positive
            # score here would let a non-compiling child retire a working parent.
            # The shipped score-axis harnesses (erfc, meshpart) already return
            # score=0.0 on failure; this makes the contract independent of that.
            if not compile_ok:
                s = 0.0
            metrics: dict[str, Any] = {"_scientific_score": s, "valid_geomean_speedup": s}
            for name, frac in (result.get("regions") or {}).items():
                metrics[f"region_{name}"] = float(frac or 0.0)
            return {
                "metrics": metrics,
                "has_real_data": compile_ok,
                "scientific_score": s,
                "valid": compile_ok,
                "reason": str(result.get("reason", "deterministic erfc evaluation")),
            }

        families = result.get("families") or {}
        compile_ok = bool(result.get("compile_ok", False))
        # PREREG: a node is invalid if it fails to compile OR any required family
        # is invalid. Invalid families are NOT mixed into the geomean as zeros.
        # A family must be valid AND measurable: a valid family whose speedup is
        # 0/negative/NaN (sub-resolution or unmeasurable timing) would otherwise
        # be silently dropped by geomean's positivity filter and the node scored
        # on the surviving families, biasing it upward. Require every family's
        # speedup to be finite and > 0 so an unmeasurable family zeros the node.
        all_valid = bool(compile_ok and families) and all(
            bool(f.get("valid"))
            and math.isfinite(float(f.get("speedup", 0.0) or 0.0))
            and float(f.get("speedup", 0.0) or 0.0) > 0.0
            for f in families.values()
        )
        g = geomean([f.get("speedup", 0.0) for f in families.values()]) if all_valid else 0.0
        s = scientific_score(g, self.target, getattr(self, "scale", "linear"))
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
            "reason": str(result.get("reason", f"deterministic {getattr(self, 'task', 'spmm')} evaluation")),
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
