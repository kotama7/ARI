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
    axis_names: "tuple[str, ...] | None" = None,
) -> float:
    """Weighted harmonic mean over a set of axes.

    Missing or non-numeric axis values are treated as 0. Each value is floored
    at ``epsilon`` to keep the denominator finite. Weights for axes that are
    not in the iteration set are ignored; absent weights default to the equal
    weight fallback. Returns 0.0 if the total weight is zero.

    By default iterates over the canonical AXIS_NAMES (legacy / 5-axis path).
    When Phase 3 dynamic axes are in use, the evaluator passes its own
    ``axis_names`` so the harmonic mean covers the dynamic set.
    """
    names = axis_names if axis_names is not None else AXIS_NAMES
    total_w = 0.0
    denom = 0.0
    for name in names:
        # Default to a small equal weight when neither weights nor the
        # legacy default mapping covers this name (covers Phase 3 axes
        # whose weight isn't in _DEFAULT_AXIS_WEIGHTS).
        fallback_w = _DEFAULT_AXIS_WEIGHTS.get(name, 1.0 / max(1, len(names)))
        w = float(weights.get(name, fallback_w))
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
            expected_params=["M", "K", "nnz", "threads"],
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
    # ``expected_metrics`` lists the *measured* quantities (what the experiment
    # produces — throughput, accuracy, latency). ``expected_params`` lists the
    # *input* knobs the experiment runs on (matrix size, thread count, seed).
    # Splitting them lets the evaluator emit a typed ``params`` / ``measurements``
    # pair instead of one ambiguous flat dict, so downstream best-of reductions
    # can never accidentally pick an input size as the "best metric".
    expected_metrics: list[str] = field(default_factory=list)
    expected_params: list[str] = field(default_factory=list)
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
        if self.expected_params:
            lines.append(f"Expected params (inputs, NOT measurements): {', '.join(self.expected_params)}")
        if self.expected_metrics:
            lines.append(f"Expected metrics (measurements): {', '.join(self.expected_metrics)}")
        if self.scoring_guide:
            lines.append(f"Domain-specific scoring guide:\n{self.scoring_guide}")
        return "\n".join(lines)


class LLMEvaluator:
    """Evaluate a completed BFTS node using an LLM judge.

    Implementation is hidden from AgentLoop (injected via DI).
    Domain knowledge is passed externally via MetricSpec.
    """

    # Phase PC6 (PROMPTS_AND_CONFIG.md §3-1): the 5-axis system prompt
    # body lives in ``ari/prompts/evaluator/extract_metrics.md``.  Load
    # it once at class-definition time so existing
    # ``LLMEvaluator.BASE_SYSTEM`` accesses (incl. tests) keep returning
    # the same string.
    @staticmethod
    def _load_base_system() -> str:
        from ari.prompts import FilesystemPromptLoader
        text = FilesystemPromptLoader().load("evaluator/extract_metrics")
        # The Python constant did not have a trailing newline; the file
        # storage layer may add one — strip a single trailing ``\n`` so
        # ``BASE_SYSTEM`` stays byte-identical to the legacy constant.
        if text.endswith("\n"):
            text = text[:-1]
        return text

    BASE_SYSTEM = _load_base_system.__func__()  # type: ignore[func-returns-value]

    def __init__(
        self,
        model: str,
        api_base: str | None = None,
        metric_spec: MetricSpec | None = None,
        axis_weights: dict[str, float] | None = None,
        axes: "list | None" = None,
        *,
        checkpoint_dir: "str | None" = None,
        rubric: "dict | None" = None,
    ) -> None:
        self.model = model
        self.api_base = api_base
        self.metric_spec = metric_spec or MetricSpec()  # default: generic
        # Constructor-supplied weights act as a config-level fallback; the
        # MetricSpec still wins if it declares its own weights.
        self._ctor_axis_weights: dict[str, float] | None = (
            dict(axis_weights) if axis_weights else None
        )
        # Phase 3 modes:
        #   1. ``axes=`` explicit list      → static dynamic mode (tests + advanced)
        #   2. ``checkpoint_dir`` + ``rubric`` → auto dynamic mode (core.py default)
        #   3. neither                       → legacy 5-axis path (back-compat)
        self._checkpoint_dir = checkpoint_dir
        self._rubric = rubric
        # lineage decisions: cache key is a "mtime:contenthash" signature, not just
        # mtime, so coarse-mtime filesystems / same-second swaps still
        # invalidate the cached axes set.
        self._axes_idea_mtime: "str | None" = None
        if axes:
            self._dynamic_axes = list(axes)
            self._axis_names: tuple[str, ...] = tuple(
                a.name for a in self._dynamic_axes
            )
        elif rubric is not None or checkpoint_dir is not None:
            # Build initial axes from whatever is currently available.
            # idea.json may not yet exist at runtime construction; the
            # ``_refresh_axes_if_needed`` hook in evaluate() picks up plan
            # axes once the root node has produced idea.json.
            from ari.evaluator.dynamic_axes import build_axes_for_run
            self._dynamic_axes = list(
                build_axes_for_run(
                    rubric=rubric, idea_data=self._read_idea_data()
                )
            )
            self._axis_names = tuple(a.name for a in self._dynamic_axes)
            self._axes_idea_mtime = self._idea_json_signature()
        else:
            self._dynamic_axes = None
            self._axis_names = AXIS_NAMES
        # Per-run score history for calibration context.
        # Each entry: {"node_id": str, "score": float, "label": str}
        self._score_history: list[dict] = []
        self._max_score_history: int = 15

    def _idea_json_path(self):
        from pathlib import Path as _Path
        if not self._checkpoint_dir:
            return None
        return _Path(self._checkpoint_dir) / "idea.json"

    def _idea_json_signature(self) -> str | None:
        """lineage decisions: cache-key based on file content hash + mtime.

        mtime alone is insufficient — same-second swaps (root_idea_
        selection rewrites idea.json shortly after generate_ideas)
        leave mtime unchanged on coarse-mtime filesystems, hiding the
        plan-derived axis update. Hashing the content avoids that
        race; mtime is folded in only as a fast-path optimisation.
        """
        p = self._idea_json_path()
        if p is None or not p.exists():
            return None
        try:
            import hashlib
            data = p.read_bytes()
            mt = p.stat().st_mtime
            h = hashlib.md5(data).hexdigest()[:16]
            return f"{mt:.6f}:{h}"
        except OSError:
            return None

    def _read_idea_data(self) -> dict:
        p = self._idea_json_path()
        if p is None or not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}

    def _refresh_axes_if_needed(self) -> None:
        """Rebuild dynamic axes when idea.json appears or changes content.

        Cheap (deterministic, no LLM); only re-derived when the source
        changed. Skipped entirely in static-axes / legacy modes.
        """
        if self._dynamic_axes is None:
            return  # legacy 5-axis path
        if self._checkpoint_dir is None:
            return  # static axes provided at construction; nothing to refresh
        cur_sig = self._idea_json_signature()
        if cur_sig is None:
            return  # idea.json absent; keep whatever axes we had
        if cur_sig == self._axes_idea_mtime:
            return  # cached (signature unchanged)
        try:
            from ari.evaluator.dynamic_axes import build_axes_for_run
            self._dynamic_axes = list(
                build_axes_for_run(rubric=self._rubric, idea_data=self._read_idea_data())
            )
            self._axis_names = tuple(a.name for a in self._dynamic_axes)
            self._axes_idea_mtime = cur_sig
        except Exception as e:
            logger.warning("axes refresh failed: %s", e)

    def _resolve_axis_weights(self) -> dict[str, float]:
        """Resolve axis weights with precedence: MetricSpec > ctor > axes > defaults."""
        if self.metric_spec.axis_weights:
            return {k: float(v) for k, v in self.metric_spec.axis_weights.items()}
        if self._ctor_axis_weights:
            return dict(self._ctor_axis_weights)
        if self._dynamic_axes:
            # Each AxisDef carries its own weight; the harmonic-mean
            # interpretation is unchanged but the axis set is wider.
            return {a.name: float(a.weight) for a in self._dynamic_axes}
        return dict(_DEFAULT_AXIS_WEIGHTS)

    def _build_system_prompt(self) -> str:
        spec_section = self.metric_spec.to_prompt_section()
        weights = self._resolve_axis_weights()

        if self._dynamic_axes:
            # Phase 3 path: replace the BASE_SYSTEM's hard-coded 5-axis block
            # with the dynamic axes. PC6 lifts the surrounding prose into
            # ``ari/prompts/evaluator/peer_review.md`` and injects the
            # computed axes block via ``{axes_block}`` so the static text
            # is no longer duplicated between code and the prompt file.
            from ari.evaluator.dynamic_axes import axes_to_prompt_section
            from ari.prompts import FilesystemPromptLoader as _PL_pr
            base = _PL_pr().load("evaluator/peer_review").format(
                axes_block=axes_to_prompt_section(self._dynamic_axes),
            )
            # peer_review.md persists with a trailing newline; the legacy
            # constant did not, so trim a single trailing ``\n`` so
            # downstream concatenations stay byte-identical.
            if base.endswith("\n"):
                base = base[:-1]
            weights_line = (
                "Axis weights (for your reference — the composite is a weighted harmonic mean):\n"
                + ", ".join(
                    f"{a.name}={weights.get(a.name, 0.0):.2f} [{a.source}]"
                    for a in self._dynamic_axes
                )
            )
            head = base + "\n\n" + weights_line
            if spec_section.strip() == "Experiment type: generic experiment":
                return head
            return head + f"\n\nDomain context:\n{spec_section}"

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
        # Phase 3 dynamic axes: refresh from idea.json mtime when it has
        # changed (root node typically writes it after this evaluator was
        # constructed). No-op in static / legacy modes.
        self._refresh_axes_if_needed()
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
            # Typed split: ``params`` (inputs) and ``measurements`` (outputs)
            # are the canonical view. ``metrics`` is kept as a back-compat
            # flat union so downstream code that doesn't yet know about the
            # split (plot-skill, paper-skill prompts) still works.
            raw_params = data.get("params") or {}
            raw_measurements = data.get("measurements") or {}
            params_dict = dict(raw_params) if isinstance(raw_params, dict) else {}
            measurements_dict = (
                dict(raw_measurements) if isinstance(raw_measurements, dict) else {}
            )
            # Prefer the LLM's explicit flat ``metrics`` view when present.
            # Fall back to a synthesized union when only the split was given —
            # measurements take precedence on key collisions because they
            # represent the experiment outcome (the value a reviewer would
            # quote), not the input it was run on.
            flat_metrics = data.get("metrics")
            if not isinstance(flat_metrics, dict) or not flat_metrics:
                flat_metrics = {**params_dict, **measurements_dict}
            extracted_metrics = dict(flat_metrics)

            # Supplement with raw artifact text via MetricSpec artifact_extractor
            # (domain-specific fallback when LLM misses some metrics)
            artifacts_text = " ".join(
                (a.get("stdout", "") or a.get("content", "") or str(a)) if isinstance(a, dict) else str(a)
                for a in (artifacts if isinstance(artifacts, list) else [])
            )
            extra_metrics = self.metric_spec.extract_from_artifacts(artifacts_text)
            extracted_metrics.update(extra_metrics)
            # The artifact extractor cannot distinguish params from measurements
            # (it scans free-form text). When the metric_spec declares which
            # names are inputs, route those to params_dict so the downstream
            # split stays clean.
            _declared_params = set(self.metric_spec.expected_params or [])
            for k, v in extra_metrics.items():
                if k in _declared_params:
                    params_dict[k] = v
                else:
                    measurements_dict.setdefault(k, v)

            # Parse per-axis scores and derive the composite via weighted
            # harmonic mean. If the judge returned only the legacy
            # scientific_score scalar, fall back to treating it as a uniform
            # value across all axes so older judges degrade gracefully.
            raw_axes = data.get("axis_scores")
            axis_scores: dict[str, float] = {}
            # Phase 3: iterate over self._axis_names so dynamic axes (rubric
            # / plan-derived) are honoured. Falls back to legacy AXIS_NAMES
            # when the evaluator was constructed without ``axes=``.
            iter_names = self._axis_names
            if isinstance(raw_axes, dict):
                for k in iter_names:
                    try:
                        axis_scores[k] = max(min(float(raw_axes.get(k, 0.0)), 1.0), 0.0)
                    except (TypeError, ValueError):
                        axis_scores[k] = 0.0
            else:
                # Phase 5 (REFACTORING.md §8): legacy 5-axis fallback
                # lives in ``ari.migrations.v05_to_v07.legacy_axes``.
                from ari.migrations.v05_to_v07.legacy_axes import (
                    legacy_uniform_axis_scores,
                )
                axis_scores = legacy_uniform_axis_scores(data, iter_names)

            weights = self._resolve_axis_weights()
            composite = weighted_harmonic_mean(
                axis_scores, weights, axis_names=iter_names
            )

            comparison_found = bool(data.get("comparison_found", False))
            if composite > 0:
                extracted_metrics["_scientific_score"] = composite
            extracted_metrics["_axis_scores"] = axis_scores
            if comparison_found:
                extracted_metrics["_comparison_found"] = 1.0
            # Typed views — present iff the LLM honoured the new contract.
            # Stored under reserved underscore keys so they don't collide
            # with experiment-named metrics. Downstream consumers that
            # know about the split (nodes_to_science_data) read these in
            # preference to inferring from the flat dict.
            if params_dict:
                extracted_metrics["_params_dict"] = params_dict
            if measurements_dict:
                extracted_metrics["_measurements_dict"] = measurements_dict

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
