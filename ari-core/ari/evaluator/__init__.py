"""ari.evaluator — LLM-driven metric extraction and dynamic axis generation.

Hosts the BFTS judge: it reads each completed node's artefacts, asks
an LLM to extract numeric metrics from `experiment.md` declarations,
and produces the multi-axis composite score consumed by the
orchestrator.  The dynamic-axis path (since v0.6) augments the fixed
five judge axes with rubric-derived `score_dimensions` and plan
`§-tag` keywords so the same rubric drives both BFTS scoring and
the published paper review.

Public symbols:
- ``LLMEvaluator`` — the evaluator entry point.
- ``MetricSpec`` — typed declaration of a metric to extract.

See also:
- ``docs/concepts/architecture.md`` (Plan / Venue contract).
- ``git log -- ari-core/ari/evaluator/`` for the Phase PC6 history.
"""

from .llm_evaluator import LLMEvaluator, MetricSpec

__all__ = ["LLMEvaluator", "MetricSpec"]
