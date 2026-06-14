# ari.evaluator

LLM-driven metric extraction and dynamic axis generation — the BFTS judge
that scores each completed node into the multi-axis composite the
orchestrator consumes.

## Contents

- `README.md` — this file.
- `__init__.py` — public symbols + axis design.
- `deterministic_evaluator.py` — `DeterministicEvaluator`: non-LLM judge owning the SpMM measurement; writes `metrics._scientific_score` to drive BFTS selection (handoff study B2). Selected via `ARI_EVALUATOR=deterministic`.
- `dynamic_axes.py` — venue/run-specific evaluation-axis derivation.
- `llm_evaluator.py` — `LLMEvaluator`: extraction + multi-axis composite scoring.
- `spmm_harness.py` — SpMM measurement core (handoff study B2b): fp64 reference oracle, per-element correctness bound (eps model), seeded matrix families, geomean aggregation (`measure_node`). Pure parts login-tested; compile/run/timing runner is compute-node only.

## See also

- **Public symbols (`LLMEvaluator`, `MetricSpec`) & axis design** → the `__init__.py` module docstring (authoritative).
- **Plan / Venue contract** → `docs/concepts/architecture.md`.
- **History** → `git log -- ari-core/ari/evaluator/`.
