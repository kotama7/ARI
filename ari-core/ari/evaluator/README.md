# ari.evaluator

LLM-driven metric extraction and dynamic axis generation — the BFTS judge
that scores each completed node into the multi-axis composite the
orchestrator consumes.

## Contents

- `README.md` — this file.
- `__init__.py` — public symbols + axis design.
- `dynamic_axes.py` — venue/run-specific evaluation-axis derivation.
- `llm_evaluator.py` — `LLMEvaluator`: extraction + multi-axis composite scoring.
- `Plan.md` — B2 deterministic evaluator＋測定器ユニットの実装計画（handoff study）.

## See also

- **Public symbols (`LLMEvaluator`, `MetricSpec`) & axis design** → the `__init__.py` module docstring (authoritative).
- **Plan / Venue contract** → `docs/concepts/architecture.md`.
- **History** → `git log -- ari-core/ari/evaluator/`.
