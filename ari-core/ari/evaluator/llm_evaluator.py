"""
LLM-based node evaluator for ARI.

Design principles:
- LLMEvaluator itself is domain-agnostic (generic)
- Per-experiment evaluation criteria are injected externally as MetricSpec
- MetricSpec: expected metric names, units, and quality thresholds passed as prompts to LLM

Scoring model (multi-axis + weighted harmonic mean):
- The judge LLM returns per-axis scores in [0.0, 1.0] for five axes
  (measurement_validity, comparative_rigor, novelty, reproducibility,
  clarity_of_contribution). The composite ``_scientific_score`` stored on
  the node is the weighted harmonic mean of those axes, which heavily
  penalizes any single weak axis and naturally spreads scores away from
  the centre — directly countering the single-scalar collapse problem.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import litellm

logger = logging.getLogger(__name__)


# Five evaluation axes (ordered). The harmonic-mean composite is defined over
# exactly these keys; anything the LLM returns outside the set is ignored.
AXIS_NAMES: tuple[str, ...] = (
    "measurement_validity",
    "comparative_rigor",
    "novelty",
    "reproducibility",
    "clarity_of_contribution",
)

# Hardcoded fallback weights (equal across axes). Used only when neither the
# MetricSpec nor the evaluator constructor supplies weights.
_DEFAULT_AXIS_WEIGHTS: dict[str, float] = {k: 0.2 for k in AXIS_NAMES}

# Floor applied inside the harmonic mean so a zero-valued axis does not cause
# division by zero. 0.01 keeps the "a single catastrophic axis tanks the
# overall score" semantics intact while still producing a finite number.
_HARMONIC_EPSILON: float = 0.01


def weighted_harmonic_mean(
    axes: dict[str, float],
    weights: dict[str, float],
    epsilon: float = _HARMONIC_EPSILON,
) -> float:
    """Weighted harmonic mean over the canonical AXIS_NAMES.

    Missing or non-numeric axis values are treated as 0. Each value is floored
    at ``epsilon`` to keep the denominator finite. Weights for axes that are
    not in AXIS_NAMES are ignored; absent weights default to the equal weight
    fallback. Returns 0.0 if the total weight is zero.
    """
    total_w = 0.0
    denom = 0.0
    for name in AXIS_NAMES:
        w = float(weights.get(name, _DEFAULT_AXIS_WEIGHTS[name]))
        if w <= 0.0:
            continue
        raw = axes.get(name, 0.0)
        try:
            x = float(raw)
        except (TypeError, ValueError):
            x = 0.0
        x = max(min(x, 1.0), 0.0)  # clamp to [0, 1]
        total_w += w
        denom += w / max(x, epsilon)
    if total_w <= 0.0 or denom <= 0.0:
        return 0.0
    return total_w / denom


def _default_scorer(metrics: dict) -> float | None:
    """Default: no score computed from metrics (left to LLM)."""
    return None


@dataclass
class MetricSpec:
    """Domain-specific evaluation criteria passed to LLM during evaluation.

    Examples::

        # For HPC performance experiments (example)
        MetricSpec(
            name="HPC benchmark speedup",
            expected_metrics=["throughput", "speedup", "efficiency"],
            scoring_guide=(
                "has_real_data=true when numeric throughput values appear in artifacts.\n"
                "score=1.0 when baseline and optimized both measured and speedup calculated.\n"
                "score=0.8 when only one condition measured.\n"
                "score=0.6 when experiment ran but results incomplete."
            ),
        )

        # Generic (default, recommended)
        MetricSpec()  # no metrics specified → LLM infers from experiment goal text
    """

    name: str = "generic experiment"
    expected_metrics: list[str] = field(default_factory=list)
    scoring_guide: str = ""
    artifact_extractor: object = field(default=None)  # callable(artifacts_text: str) -> dict
    # Optional per-axis weights for the harmonic-mean composite. When None,
    # the evaluator falls back to constructor-supplied weights and then to
    # the hardcoded equal-weight default. Keys must be a subset of AXIS_NAMES.
    axis_weights: dict[str, float] | None = None

    def extract_from_artifacts(self, artifacts_text: str) -> dict:
        """Extract domain-specific metrics from raw artifact text (optional).
        Domain-specific fallback to supplement metrics that LLM may have missed.
        """
        if self.artifact_extractor is None:
            return {}
        try:
            result = self.artifact_extractor(artifacts_text)
            return result if isinstance(result, dict) else {}
        except Exception:
            return {}

    def to_prompt_section(self) -> str:
        lines = [f"Experiment type: {self.name}"]
        if self.expected_metrics:
            lines.append(f"Expected metrics: {', '.join(self.expected_metrics)}")
        if self.scoring_guide:
            lines.append(f"Domain-specific scoring guide:\n{self.scoring_guide}")
        return "\n".join(lines)


class LLMEvaluator:
    """Evaluate a completed BFTS node using an LLM judge.

    Implementation is hidden from AgentLoop (injected via DI).
    Domain knowledge is passed externally via MetricSpec.
    """

    BASE_SYSTEM = (
        "You are a research data extractor AND a scientific peer reviewer.\n"
        "Analyze the experiment artifacts and return a JSON with:\n"
        "  has_real_data: bool (true only if numeric measurements appear in artifacts)\n"
        "  metrics: dict of extracted numeric values (e.g. {{\"GFLOP_per_s\": 754.8}})\n"
        "  reason: str (one sentence describing what was measured)\n"
        "  axis_scores: dict with EXACTLY these five keys, each a float in 0.0-1.0:\n"
        "    - measurement_validity: are numeric measurements present and methodologically sound?\n"
        "    - comparative_rigor: are results compared against baselines or prior work?\n"
        "    - novelty: does the work advance beyond existing approaches?\n"
        "    - reproducibility: is there enough detail for someone else to reproduce the result?\n"
        "    - clarity_of_contribution: is the scientific claim stated clearly and specifically?\n"
        "    Score 0.0 on an axis when that dimension is absent or fatally weak. "
        "    Score toward 1.0 as the dimension approaches publishable quality. "
        "    These axes are combined via weighted harmonic mean, so a low score on ANY axis "
        "    drags the overall score down — differentiate axes deliberately.\n"
        "  axis_rationales: dict with the same five keys; each value is one sentence "
        "    explaining the score for that axis.\n"
        "  comparison_found: bool (true if results involve comparison with existing approaches)\n"
        "Return ONLY valid JSON, no markdown fences."
    )

    def __init__(
        self,
        model: str,
        api_base: str | None = None,
        metric_spec: MetricSpec | None = None,
        axis_weights: dict[str, float] | None = None,
    ) -> None:
        self.model = model
        self.api_base = api_base
        self.metric_spec = metric_spec or MetricSpec()  # default: generic
        # Constructor-supplied weights act as a config-level fallback; the
        # MetricSpec still wins if it declares its own weights.
        self._ctor_axis_weights: dict[str, float] | None = (
            dict(axis_weights) if axis_weights else None
        )
        # Per-run score history for calibration context.
        # Each entry: {"node_id": str, "score": float, "label": str}
        self._score_history: list[dict] = []
        self._max_score_history: int = 15

    def _resolve_axis_weights(self) -> dict[str, float]:
        """Resolve axis weights with precedence: MetricSpec > ctor > defaults."""
        if self.metric_spec.axis_weights:
            return {k: float(v) for k, v in self.metric_spec.axis_weights.items()}
        if self._ctor_axis_weights:
            return dict(self._ctor_axis_weights)
        return dict(_DEFAULT_AXIS_WEIGHTS)

    def _build_system_prompt(self) -> str:
        spec_section = self.metric_spec.to_prompt_section()
        weights = self._resolve_axis_weights()
        weights_line = (
            "Axis weights (for your reference — the composite is a weighted harmonic mean):\n"
            + ", ".join(f"{k}={weights.get(k, 0.0):.2f}" for k in AXIS_NAMES)
        )
        if spec_section.strip() == "Experiment type: generic experiment":
            return self.BASE_SYSTEM + "\n\n" + weights_line
        return (
            self.BASE_SYSTEM
            + "\n\n"
            + weights_line
            + f"\n\nDomain context:\n{spec_section}"
        )

    def _build_score_context(self) -> str:
        """Render the score-distribution context block for the user prompt.

        This is the calibration injection that prevents score collapse:
        the LLM sees what scores it has assigned earlier in the same run,
        sorted by score descending, and is asked to use the full 0-1 range.
        Returns an empty string when no scores are available yet.
        """
        if not self._score_history:
            return ""
        sorted_h = sorted(
            self._score_history, key=lambda h: h.get("score", 0.0), reverse=True
        )[: self._max_score_history]
        scores = [float(h.get("score", 0.0)) for h in sorted_h]
        lo = min(scores)
        hi = max(scores)
        lines = [
            "Score distribution context for the current run "
            f"(top {len(sorted_h)} of {len(self._score_history)}, sorted by score):"
        ]
        for h in sorted_h:
            lines.append(
                f"  - {h.get('node_id', '?'):>10s} "
                f"score={float(h.get('score', 0.0)):.2f} "
                f"label={h.get('label') or '?'}"
            )
        lines.append(
            f"Note: scores in this run so far range from {lo:.2f} to {hi:.2f}. "
            "Use the full 0.0–1.0 range deliberately. "
            "Differentiate clearly between weak, average, and strong contributions; "
            "do not cluster every node around the middle."
        )
        return "\n".join(lines) + "\n\n"

    def _record_score(self, node_id: str | None, score: float, label: str | None) -> None:
        """Record a freshly assigned score so future evaluations can calibrate."""
        if not node_id or score is None:
            return
        try:
            entry = {
                "node_id": (str(node_id)[-8:] if len(str(node_id)) > 8 else str(node_id)),
                "score": float(score),
                "label": str(label or ""),
            }
        except (TypeError, ValueError):
            return
        self._score_history.append(entry)
        # Cap memory: keep at most 2x the max so we always have room to sort+slice
        cap = max(self._max_score_history * 2, 30)
        if len(self._score_history) > cap:
            self._score_history = self._score_history[-cap:]

    def evaluate_sync(
        self,
        goal: str,
        artifacts: list[dict],
        summary: str,
        node_id: str | None = None,
        node_label: str | None = None,
    ) -> dict:
        """Synchronous evaluate (for calling from AgentLoop). Handles running event loops gracefully."""
        import asyncio
        import concurrent.futures
        import logging
        _log = logging.getLogger(__name__)

        def _run_in_thread():
            # Each thread gets its own event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self.evaluate(goal, artifacts, summary,
                                  node_id=node_id, node_label=node_label)
                )
            finally:
                loop.close()

        try:
            # Check if there's already a running loop
            try:
                asyncio.get_running_loop()
                already_running = True
            except RuntimeError:
                already_running = False

            if already_running:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_run_in_thread)
                    result = future.result(timeout=120)
                    _log.info("evaluate_sync (thread): metrics=%s", result.get("metrics", {}))
                    return result
            else:
                return asyncio.run(
                    self.evaluate(goal, artifacts, summary,
                                  node_id=node_id, node_label=node_label)
                )
        except Exception as e:
            _log.warning("evaluate_sync failed: %s", e)
            return {"score": None, "reason": f"sync error: {e}",
                    "has_real_data": False, "has_paper_section": False, "metrics": {}}

    async def evaluate(
        self,
        goal: str,
        artifacts: list[dict],
        summary: str,
        node_id: str | None = None,
        node_label: str | None = None,
    ) -> dict:
        """Return dict: score, reason, has_real_data, has_paper_section, metrics."""
        artifact_str = str(artifacts)[:2000]
        score_context_block = self._build_score_context()
        prompt = (
            f"{score_context_block}"
            f"Goal: {goal}\n\n"
            f"Artifacts: {artifact_str}\n\n"
            f"Summary: {summary[:500]}"
        )
        kwargs: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            "metadata": {
                "phase": "evaluation",
                "skill": "llm_evaluator",
                "node_id": str(node_id or ""),
            },
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base

        try:
            response = await litellm.acompletion(**kwargs)
            raw = response.choices[0].message.content or ""
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                raw = m.group(0)
            data = json.loads(raw)
            extracted_metrics = data.get("metrics", {})

            # Supplement with raw artifact text via MetricSpec artifact_extractor
            # (domain-specific fallback when LLM misses some metrics)
            artifacts_text = " ".join(
                (a.get("stdout", "") or a.get("content", "") or str(a)) if isinstance(a, dict) else str(a)
                for a in (artifacts if isinstance(artifacts, list) else [])
            )
            extra_metrics = self.metric_spec.extract_from_artifacts(artifacts_text)
            extracted_metrics.update(extra_metrics)

            # Parse per-axis scores and derive the composite via weighted
            # harmonic mean. If the judge returned only the legacy
            # scientific_score scalar, fall back to treating it as a uniform
            # value across all axes so older judges degrade gracefully.
            raw_axes = data.get("axis_scores")
            axis_scores: dict[str, float] = {}
            if isinstance(raw_axes, dict):
                for k in AXIS_NAMES:
                    try:
                        axis_scores[k] = max(min(float(raw_axes.get(k, 0.0)), 1.0), 0.0)
                    except (TypeError, ValueError):
                        axis_scores[k] = 0.0
            else:
                legacy = data.get("scientific_score")
                if legacy is not None:
                    try:
                        uniform = max(min(float(legacy), 1.0), 0.0)
                    except (TypeError, ValueError):
                        uniform = 0.0
                    axis_scores = {k: uniform for k in AXIS_NAMES}
                else:
                    axis_scores = {k: 0.0 for k in AXIS_NAMES}

            weights = self._resolve_axis_weights()
            composite = weighted_harmonic_mean(axis_scores, weights)

            comparison_found = bool(data.get("comparison_found", False))
            if composite > 0:
                extracted_metrics["_scientific_score"] = composite
            extracted_metrics["_axis_scores"] = axis_scores
            if comparison_found:
                extracted_metrics["_comparison_found"] = 1.0

            # Record this score so future evaluations in the same run can
            # calibrate against the distribution and avoid score collapse.
            self._record_score(node_id, composite, node_label)

            return {
                "reason": str(data.get("reason", "")),
                "has_real_data": bool(data.get("has_real_data", False)),
                "scientific_score": composite,
                "axis_scores": axis_scores,
                "axis_rationales": data.get("axis_rationales", {}) or {},
                "comparison_found": comparison_found,
                "metrics": extracted_metrics,
            }
        except Exception as e:
            logger.warning("LLMEvaluator failed: %s", e)
            return {
                "score": None,
                "reason": f"eval error: {e}",
                "has_real_data": False,
                "has_paper_section": False,
                "metrics": {},
            }
