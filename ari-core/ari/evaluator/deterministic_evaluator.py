"""Fixed, non-LLM evaluator for the handoff study (B2).

Selected via ``ARI_EVALUATOR=deterministic`` (see ``ari/core.py``). Unlike
``LLMEvaluator`` it calls no LLM judge: it owns the measurement through a fixed
reference oracle and timing harness. Performance measurements remain noisy, so
raw repetitions are retained for audit and the selected candidate is remeasured
independently. The ranking value it writes to ``metrics["_scientific_score"]`` is
exactly what BFTS selection / parent-retire / the sterile gate consume
(``ari/orchestrator/bfts.py:336`` etc.). For speedup-shaped HPC tasks this value
is the native valid geomean speedup, not a [0, 1] normalization, so good
candidates above an arbitrary target do not collapse to ties.

This module owns the SCORING CONTRACT (pure, unit-tested here): geomean over the
fixed family set, native speedup ranking for speedup tasks, and the
"node-invalid if any required family fails" rule (no zeros mixed into the
geomean). The SpMM kernel compile + run + timing + reference-oracle correctness
(per-row epsilon model) lives under ``ari-core/handoff_study/spmm/`` (added
separately; compute-node validated) and is invoked through ``measure_fn``.

Contract returned by ``evaluate_sync`` (and async ``evaluate``):
``{"metrics": {"_scientific_score": float, "valid_geomean_speedup": float, ...},
   "has_real_data": bool, "scientific_score": float, "valid": bool,
   "evaluation_cases": {case: {"valid": bool, "measurements": {...}}},
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


def scientific_score(
    geomean_speedup: float | None,
    target: float = 16.0,
    scale: str = "linear",
) -> float:
    """Return the BFTS ranking value for speedup-shaped tasks.

    The historical name is kept for compatibility with checkpoints, BFTS, and
    visualization code. For GEMM/SpMM/Stencil the ranking value is now the native
    valid geomean speedup ``g`` itself. ``target`` and ``scale`` are accepted for
    API compatibility with older configs but are intentionally not used: BFTS
    compares nodes within the same task, so a [0, 1] target clamp only removes
    ordering information among strong candidates.
    """
    del target, scale
    if not geomean_speedup or geomean_speedup <= 0.0:
        return 0.0
    g = float(geomean_speedup)
    return g if math.isfinite(g) else 0.0


def gamma(k: int, u: float) -> float:
    """Backward-stable summation error factor ``k*u / (1 - k*u)`` (PREREG eps model).

    Used by the SpMM oracle's per-output-element correctness bound
    ``|y_cand - y_ref| <= C * gamma_k * sum(|A||x|)``. ``inf`` when ``k*u >= 1``
    (the bound is vacuous — the row is too long for the working precision).
    """
    ku = float(k) * float(u)
    return ku / (1.0 - ku) if ku < 1.0 else float("inf")


_UNSUPPORTED = object()


def _objective_scalar(value: Any) -> Any:
    """Return a JSON-safe scalar without assigning task-specific meaning."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return _UNSUPPORTED


def _evaluation_cases(families: dict[str, dict]) -> dict[str, dict]:
    """Preserve each harness case generically as validity + named measurements."""
    cases: dict[str, dict] = {}
    for name, family in families.items():
        measurements: dict[str, Any] = {}
        for key, value in family.items():
            if key == "valid":
                continue
            scalar = _objective_scalar(value)
            if scalar is not _UNSUPPORTED:
                measurements[str(key)] = scalar
        cases[str(name)] = {
            "valid": bool(family.get("valid")),
            "measurements": measurements,
        }
    return cases


def _measurement_audit(result: dict, families: dict[str, dict]) -> dict[str, Any]:
    """Preserve evaluator-only raw records without injecting them into handoff.

    ``evaluation_cases`` is intentionally compact because it is eligible for the
    Evidence handoff. Raw repetition timings and effective compile flags are audit
    material, not treatment text, so they live in this separate report field.
    """
    cases: dict[str, list[dict[str, Any]]] = {}
    for name, family in families.items():
        repetitions = family.get("repetitions")
        if isinstance(repetitions, list):
            cases[str(name)] = [
                _json_audit_value(item)
                for item in repetitions
                if isinstance(item, dict)
            ]
    return {
        "effective_candidate_compile_flags": [
            str(v) for v in (result.get("candidate_cflags") or [])
        ],
        "rejected_candidate_compile_flags": [
            str(v) for v in (result.get("rejected_cflags") or [])
        ],
        "cases": cases,
    }


def _json_audit_value(value: Any) -> Any:
    """Recursively make raw audit observations strict-JSON serializable."""
    if isinstance(value, dict):
        return {str(k): _json_audit_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_audit_value(v) for v in value]
    scalar = _objective_scalar(value)
    if scalar is not _UNSUPPORTED:
        return scalar
    return str(value)


def _measurement_reason(
    result: dict,
    *,
    compile_ok: bool,
    all_valid: bool,
    evaluation_cases: dict[str, dict],
) -> str:
    """Return a verdict that cannot say ``ok`` for an invalid measurement."""
    reason = str(result.get("reason") or "").strip()
    if all_valid:
        return reason or "ok"
    if not compile_ok:
        return reason if reason and reason.lower() != "ok" else "compile failed"
    if reason and reason.lower() != "ok":
        return reason

    invalid: list[str] = []
    for name, case in evaluation_cases.items():
        measurements = case.get("measurements") or {}
        speedup = measurements.get("speedup")
        if case.get("valid") and isinstance(speedup, (int, float)) and speedup > 0:
            continue
        details = [f"valid={bool(case.get('valid'))}"]
        details.extend(f"{key}={value}" for key, value in measurements.items())
        invalid.append(f"{name} ({', '.join(details)})")
    suffix = "; ".join(invalid) if invalid else "no valid measurable family"
    return f"measurement invalid: {suffix}"


def _default_measure(work_dir: str) -> dict:
    """Invoke the SpMM harness measurement (compute-node validated; added in B2b).

    Importing lazily so the evaluator/dispatch are usable before the kernel
    harness lands. Raises a clear error if the harness is not yet installed.

    Problem size and the OpenMP thread budget are study parameters (frozen
    defaults, env-overridable). They MUST sit where parallelism actually pays
    off: on a many-core node a tiny matrix makes even a perfect kernel ~1x
    (parallel overhead dominates), which would collapse the study's dynamic
    range. Validated on a compute node — n=20000/k=64/48 threads gives a naive
    1x baseline room to reach ~12-15x, keeping the native speedup ranking
    informative.
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
        task: str | None = None,
        target_speedup: float | None = None,
        measure_fn: Callable[[str], dict] | None = None,
        scale: str | None = None,
        **_ignored: Any,
    ) -> None:
        self.task = (task or _resolve_task()).strip().lower()
        # Kept for backward-compatible construction from older configs. Speedup
        # tasks no longer normalize by target/scale; score-shaped legacy tasks
        # are handled separately in _score().
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
                "evaluation_status": "valid" if compile_ok else "candidate_invalid",
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
        evaluation_cases = _evaluation_cases(families)
        metrics: dict[str, Any] = {
            "_scientific_score": s,
            "valid_geomean_speedup": g,
        }
        for name, f in families.items():
            metrics[f"speedup_{name}"] = float(f.get("speedup", 0.0) or 0.0)
        raw_status = str(result.get("evaluation_status") or "candidate_invalid")
        if not all_valid and raw_status == "valid":
            raw_status = "measurement_invalid"
        return {
            "metrics": metrics,
            "has_real_data": all_valid,
            "scientific_score": s,
            "valid": all_valid,
            "evaluation_status": "valid" if all_valid else raw_status,
            "evaluation_cases": evaluation_cases,
            "measurement_audit": _measurement_audit(result, families),
            "reason": _measurement_reason(
                result,
                compile_ok=compile_ok,
                all_valid=all_valid,
                evaluation_cases=evaluation_cases,
            ),
        }

    def score_result(self, result: dict) -> dict:
        """Public pure adapter for evaluator-owned remeasurement workflows."""
        return self._score(result)

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
                "evaluation_status": "infrastructure_error",
                "evaluation_cases": {},
                "measurement_audit": {
                    "effective_candidate_compile_flags": [],
                    "rejected_candidate_compile_flags": [],
                    "cases": {},
                },
                "reason": f"deterministic eval infrastructure error: {e}",
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
