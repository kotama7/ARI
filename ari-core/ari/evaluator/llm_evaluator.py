"""
LLM-based node evaluator for ARI.

Design principles:
- LLMEvaluator itself is domain-agnostic (generic)
- Per-experiment evaluation criteria are injected externally as MetricSpec
- MetricSpec: expected metric names, units, and quality thresholds passed as prompts to LLM
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import litellm

logger = logging.getLogger(__name__)


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
        "  scientific_score: float 0.0-1.0\n"
        "    Judge scientific contribution as a peer reviewer would. "
        "You decide what matters and how much. "
        "Score 0.0 if no real measurements exist. "
        "Score toward 1.0 as the work becomes more scientifically rigorous and publishable. "
        "Consider factors such as: measurement validity, comparative evaluation, "
        "systematic analysis, reproducibility, and clarity of contribution — "
        "but weigh these as you see fit for the given experiment.\n"
        "  scientific_score_rationale: str (your reasoning for the score)\n"
        "  comparison_found: bool (true if results involve comparison with existing approaches)\n"
        "Return ONLY valid JSON, no markdown fences."
    )

    def __init__(
        self,
        model: str,
        api_base: str | None = None,
        metric_spec: MetricSpec | None = None,
    ) -> None:
        self.model = model
        self.api_base = api_base
        self.metric_spec = metric_spec or MetricSpec()  # default: generic

    def _build_system_prompt(self) -> str:
        spec_section = self.metric_spec.to_prompt_section()
        if spec_section.strip() == "Experiment type: generic experiment":
            return self.BASE_SYSTEM
        return self.BASE_SYSTEM + f"\n\nDomain context:\n{spec_section}"

    def evaluate_sync(
        self,
        goal: str,
        artifacts: list[dict],
        summary: str,
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
                return loop.run_until_complete(self.evaluate(goal, artifacts, summary))
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
                return asyncio.run(self.evaluate(goal, artifacts, summary))
        except Exception as e:
            _log.warning("evaluate_sync failed: %s", e)
            return {"score": None, "reason": f"sync error: {e}",
                    "has_real_data": False, "has_paper_section": False, "metrics": {}}

    async def evaluate(
        self,
        goal: str,
        artifacts: list[dict],
        summary: str,
    ) -> dict:
        """Return dict: score, reason, has_real_data, has_paper_section, metrics."""
        artifact_str = str(artifacts)[:2000]
        prompt = (
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

            # Add scientific_score and comparison_found to metrics so BFTS
            # can use them as expansion signals (higher score = better node)
            sci_score = float(data.get("scientific_score", 0.0))
            comparison_found = bool(data.get("comparison_found", False))
            if sci_score > 0:
                extracted_metrics["_scientific_score"] = sci_score
            if comparison_found:
                extracted_metrics["_comparison_found"] = 1.0

            return {
                "reason": str(data.get("reason", "")),
                "has_real_data": bool(data.get("has_real_data", False)),
                "scientific_score": sci_score,
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
