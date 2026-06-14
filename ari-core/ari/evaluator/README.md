# ari.evaluator

LLM-driven metric extraction and dynamic axis generation — the BFTS judge
that scores each completed node into the multi-axis composite the
orchestrator consumes.

## Contents

- `README.md` — this file.
- `__init__.py` — public symbols + axis design.
- `deterministic_evaluator.py` — `DeterministicEvaluator`: non-LLM judge owning the SpMM measurement; writes `metrics._scientific_score` to drive BFTS selection (handoff study B2). Selected via `ARI_EVALUATOR=deterministic`.
- `dynamic_axes.py` — venue/run-specific evaluation-axis derivation.
- `handoff_stats.py` — run-level analysis statistics for the handoff study (Stage 4 core): geomean, run-cluster bootstrap CI, TOST equivalence (RQ1 parity), Holm correction, per-arm summary. Pure; consumed by `scripts/analyze_handoff_ablation.py`.
- `llm_evaluator.py` — `LLMEvaluator`: extraction + multi-axis composite scoring.
- `spmm_harness.py` — SpMM measurement core (handoff study B2b): fp64 reference oracle, per-element correctness bound (eps model), seeded matrix families, geomean aggregation (`measure_node`). Pure parts login-tested; compile/run/timing runner is compute-node only.
- `spmm_kernels/` — C kernel fixtures for the handoff-study SpMM measurement (B2b). The frozen
  - `README.md` — spmm_kernels index.
  - `baseline_spmm.c` — FROZEN 1x reference CSR SpMM (naive, single-thread); the speedup denominator.
  - `candidate_spmm.c` — agent-edited `spmm()` template (seeded identical to baseline); copied per node into the work_dir.
  - `experiment.md` — the SpMM optimization task handed to the agent (goal + `spmm()` contract + the deterministic-evaluator judging rules); the experiment file for the pilot/MVP runs.
  - `Makefile` — manual build (the Python runner compiles directly with identical flags for baseline/candidate).
  - `Plan.md` — B2b compile/run/timing runner plan (deps + deletion requirement).
  - `selftest.c` — local developer self-test (`make selftest`): runs the candidate on a seeded problem, checks correctness with the evaluator's eps bound, and prints an estimated speedup vs the naive baseline; NOT used for scoring (seeded so the agent can iterate locally).
  - `spmm_kernel.h` — the `spmm()` contract the candidate must keep.
  - `spmm_main.c` — FROZEN timing + binary-I/O harness (warmup/reps/median); agent must not edit.

## See also

- **Public symbols (`LLMEvaluator`, `MetricSpec`) & axis design** → the `__init__.py` module docstring (authoritative).
- **Plan / Venue contract** → `docs/concepts/architecture.md`.
- **History** → `git log -- ari-core/ari/evaluator/`.
